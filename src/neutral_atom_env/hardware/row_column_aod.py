"""Crossed-AOD row/column kinematics inspired by Bluvstein et al. (2022, 2024).

All intersections exist; no row/column crossing or independent per-atom motion.
Every axis uses the same cubic progress, so swept paths and pair separation
admit exact segment tests. No RF, optical potential or fidelity simulation.
"""
from dataclasses import replace
from math import hypot, sqrt
from itertools import combinations
from neutral_atom_env.domain.aod import AODConfiguration
from neutral_atom_env.domain.models import Position2D, MobileCellIndex, HolderType
from neutral_atom_env.domain.operations import CaptureBinding
from neutral_atom_env.domain.errors import ValidationError
from .rigid_aod import RigidRectangularAODBackend, distance, segment_clearance


class RowColumnAODBackend(RigidRectangularAODBackend):
    name = 'row_column'
    motion_profile = 'cubic'

    def target_aod(self, aod, target):
        if isinstance(target, Position2D):
            target=aod.configuration().translated(target.x_um-aod.pose.x_um,target.y_um-aod.pose.y_um)
        if not isinstance(target, AODConfiguration):
            raise ValidationError('INVALID_AOD_TARGET', 'Expected ordered axes or a translation pose')
        return replace(aod.configured(target),is_moving=False)

    def validate_pose(self, state, target):
        aod=self.target_aod(state.aod,target)
        config=aod.configuration()
        from .trap_spacing import validate_trap_spacing
        validate_trap_spacing(aod,state.hardware)
        for x in (config.x_um[0],config.x_um[-1]):
            for y in (config.y_um[0],config.y_um[-1]):
                if not state.world.bounds.contains(Position2D(x,y)):
                    raise ValidationError('AOD_OUTSIDE_WORLD', 'AOD axes leave the calibrated field of view',position=Position2D(x,y))

    def move_distance(self, aod, target):
        start,end=aod.configuration(),self.target_aod(aod,target).configuration()
        # Maximum trap path length in a full Cartesian product (includes empty traps).
        dx=max(abs(b-a) for a,b in zip(start.x_um,end.x_um))
        dy=max(abs(b-a) for a,b in zip(start.y_um,end.y_um))
        return hypot(dx,dy)

    def move_duration(self, aod, target, hardware):
        d=self.move_distance(aod,target)
        # u(s)=3s²-2s³: max |u'|=1.5, |u''|=6, |u'''|=12.
        return max(1.5*d/hardware.speed_um_per_us,
                   sqrt(6*d/hardware.max_acceleration_um_per_us2),
                   (12*d/hardware.max_jerk_um_per_us3)**(1/3))

    def atom_distance(self, state, target):
        end=self.target_aod(state.aod,target)
        return sum(distance(state.aod.position(cell),end.position(cell)) for cell in state.placement.mobile_occupancy)

    def capture_closure(self, state, pose):
        if state.placement.mobile_occupancy or state.aod.is_moving:
            raise ValidationError('AOD_BUSY', 'Capture requires an empty idle AOD')
        self.validate_pose(state,pose)
        aod=self.target_aod(state.aod,pose)
        cells=[MobileCellIndex(r,c) for r in range(aod.rows) for c in range(aod.columns)]
        bindings=[]
        for key,holder in sorted(state.placement.atom_to_holder.items()):
            if holder.holder_type!=HolderType.STATIC:continue
            p=state.placement.position(key,state.world,aod)
            aligned=[cell for cell in cells if distance(aod.position(cell),p)<=state.hardware.alignment_tolerance_um]
            if len(aligned)>1:
                raise ValidationError('AMBIGUOUS_CAPTURE','Alignment tolerance associates an atom with multiple traps',atom_ids=(key,))
            if aligned:bindings.append(CaptureBinding(key,aligned[0],holder.holder_id))
        return tuple(bindings)

    def validate_geometry_move(self, state, target):
        self.validate_pose(state,state.aod.configuration())
        self.validate_pose(state,target)
        end=self.target_aod(state.aod,target)
        starts={a:state.aod.position(cell) for cell,a in state.placement.mobile_occupancy.items()}
        ends={a:end.position(cell) for cell,a in state.placement.mobile_occupancy.items()}
        clearance=state.hardware.minimum_clearance_um
        # Shared monotone progress means relative vectors also sweep straight segments.
        for a,b in combinations(sorted(starts),2):
            rel0=Position2D(starts[a].x_um-starts[b].x_um,starts[a].y_um-starts[b].y_um)
            rel1=Position2D(ends[a].x_um-ends[b].x_um,ends[a].y_um-ends[b].y_um)
            d,_=segment_clearance(Position2D(0,0),rel0,rel1)
            if d+1e-9<clearance:
                raise ValidationError('MOBILE_CLEARANCE','Moving atoms violate swept pair clearance',atom_ids=(a,b))
        for atom,start in starts.items():
            for other,value in state.atoms.items():
                if other in starts or not value.alive:continue
                p=state.placement.position(other,state.world,state.aod)
                d,closest=segment_clearance(p,start,ends[atom])
                if d+1e-9<clearance:
                    raise ValidationError('PATH_BLOCKED','Swept mobile/static clearance is below the configured minimum',atom_ids=(atom,other),position=closest)

    def move(self, state, target, *, transfer=None, bindings=()):
        self.validate_move(state,target,transfer=transfer,bindings=bindings)
        return replace(state,aod=self.target_aod(state.aod,target))
