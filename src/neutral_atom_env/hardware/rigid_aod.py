"""Kinematic rigid-array model: continuous pose, discrete cells, exact swept clearance."""
from dataclasses import replace
from itertools import combinations
from math import hypot
from neutral_atom_env.domain.models import Position2D, MobileCellIndex, HolderRef, HolderType, ZoneType
from neutral_atom_env.domain.operations import CaptureBinding
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.world import PlacementState


def distance(a, b):
    return hypot(a.x_um-b.x_um,a.y_um-b.y_um)


def segment_clearance(point, start, end):
    dx,dy=end.x_um-start.x_um,end.y_um-start.y_um
    length2=dx*dx+dy*dy
    fraction=0 if length2==0 else max(0,min(1,((point.x_um-start.x_um)*dx+(point.y_um-start.y_um)*dy)/length2))
    closest=Position2D(start.x_um+fraction*dx,start.y_um+fraction*dy)
    return distance(point,closest),closest


class RigidRectangularAODBackend:
    name = 'rigid'
    motion_profile = 'linear'

    def park(self,state,bindings):
        from .partial_transfer import transfer
        return transfer(self,state,bindings)

    def recapture(self,state,bindings):
        from .partial_transfer import transfer
        return transfer(self,state,bindings,recapture=True)

    def target_aod(self, aod, target):
        if not isinstance(target, Position2D):
            raise ValidationError('UNSUPPORTED_DEFORMATION', 'Rigid AOD only accepts a translation pose')
        if aod.column_offsets_um is not None or aod.row_offsets_um is not None:
            raise ValidationError('UNSUPPORTED_DEFORMATION', 'Rigid AOD requires fixed uniform spacing')
        return replace(aod, pose=target, is_moving=False)

    def move_distance(self, aod, target):
        return distance(aod.pose, self.target_aod(aod,target).pose)

    def move_duration(self, aod, target, hardware):
        return self.move_distance(aod,target)/hardware.speed_um_per_us

    def atom_distance(self, state, target):
        return self.move_distance(state.aod,target)*len(state.placement.mobile_occupancy)

    def validate_pose(self,state,pose):
        aod=self.target_aod(state.aod,pose)
        from .trap_spacing import validate_trap_spacing
        validate_trap_spacing(aod,state.hardware)
        for row in (0,aod.rows-1):
            for col in (0,aod.columns-1):
                p=aod.position(MobileCellIndex(row,col))
                if not state.world.bounds.contains(p):
                    raise ValidationError('AOD_OUTSIDE_WORLD','AOD footprint outside world',position=p)

    def capture_closure(self,state,pose):
        if state.placement.mobile_occupancy or state.aod.is_moving:
            raise ValidationError('AOD_BUSY','Capture requires an empty idle AOD')
        self.validate_pose(state,pose)
        aod=replace(state.aod,pose=pose);tol=state.hardware.alignment_tolerance_um
        bindings=[]
        for key,holder in sorted(state.placement.atom_to_holder.items()):
            if holder.holder_type!=HolderType.STATIC:continue
            p=state.placement.position(key,state.world,aod)
            if (pose.x_um-tol<=p.x_um<=pose.x_um+(aod.columns-1)*aod.spacing_um+tol and
                pose.y_um-tol<=p.y_um<=pose.y_um+(aod.rows-1)*aod.spacing_um+tol):
                row=round((p.y_um-pose.y_um)/aod.spacing_um);col=round((p.x_um-pose.x_um)/aod.spacing_um)
                cell=MobileCellIndex(row,col)
                if distance(aod.position(cell),p)>tol:
                    raise ValidationError('CAPTURE_MISALIGNMENT','Atom within footprint does not align with a mobile cell',atom_ids=(key,),position=p)
                bindings.append(CaptureBinding(key,cell,holder.holder_id))
        return tuple(bindings)

    def load(self,state,bindings):
        actual=self.capture_closure(state,state.aod.pose)
        if actual!=bindings:
            raise ValidationError('CAPTURE_CHANGED','Capture closure differs from the plan',atom_ids=tuple(b.atom_id for b in actual))
        holders=dict(state.placement.atom_to_holder)
        for b in bindings:holders[b.atom_id]=HolderRef(HolderType.MOBILE,b.cell)
        result=replace(state,placement=PlacementState(holders))
        self.validate_geometry_move(result,result.aod.pose)
        return result

    def validate_geometry_move(self,state,target):
        self.validate_pose(state,state.aod.pose);self.validate_pose(state,target)
        moving={a for a,h in state.placement.atom_to_holder.items() if h.holder_type==HolderType.MOBILE}
        current={a:state.placement.position(a,state.world,state.aod) for a in moving}
        delta=Position2D(target.x_um-state.aod.pose.x_um,target.y_um-state.aod.pose.y_um)
        clearance=state.hardware.minimum_clearance_um
        for a,b in combinations(sorted(moving),2):
            if distance(current[a],current[b])<clearance:
                raise ValidationError('MOBILE_CLEARANCE','Loaded atoms are too close',atom_ids=(a,b),position=current[a])
        for atom,start in current.items():
            end=Position2D(start.x_um+delta.x_um,start.y_um+delta.y_um)
            for other,value in state.atoms.items():
                if other in moving or not value.alive:continue
                p=state.placement.position(other,state.world,state.aod)
                d,closest=segment_clearance(p,start,end)
                if d+1e-9<clearance:
                    raise ValidationError('PATH_BLOCKED',f'Swept clearance {d:g} um is below {clearance:g} um',atom_ids=(atom,other),position=closest)

    def validate_move(self,state,target,*,transfer=None,bindings=()):
        self.validate_geometry_move(state,target)
        from .slm_clearance import validate_slm_clearance
        validate_slm_clearance(state,self.target_aod(state.aod,target),transfer,bindings)

    def move(self,state,target,*,transfer=None,bindings=()):
        self.validate_move(state,target,transfer=transfer,bindings=bindings)
        return replace(state,aod=replace(state.aod,pose=target,is_moving=False))

    def offload(self,state,bindings):
        loaded={a for a,h in state.placement.atom_to_holder.items() if h.holder_type==HolderType.MOBILE}
        if loaded!={b.atom_id for b in bindings}:
            raise ValidationError('OFFLOAD_SET_MISMATCH','Offload must account for every loaded atom',atom_ids=tuple(sorted(loaded)))
        holders=dict(state.placement.atom_to_holder);targets=set()
        for b in bindings:
            trap=state.world.traps.get(b.static_trap_id)
            if not trap or not trap.enabled:
                raise ValidationError('OFFLOAD_DISABLED','Offload trap unavailable',atom_ids=(b.atom_id,),holder_id=b.static_trap_id)
            occupant=state.placement.static_occupancy.get(trap.id)
            if occupant or trap.id in targets:
                raise ValidationError('OFFLOAD_OCCUPIED','Offload trap already occupied',atom_ids=tuple(a for a in (b.atom_id,occupant) if a),holder_id=trap.id,position=trap.position)
            p=state.placement.position(b.atom_id,state.world,state.aod)
            if distance(p,trap.position)>state.hardware.alignment_tolerance_um:
                raise ValidationError('OFFLOAD_MISALIGNMENT','Mobile atom must align with the offload trap',atom_ids=(b.atom_id,),holder_id=trap.id,position=p)
            targets.add(trap.id);holders[b.atom_id]=HolderRef(HolderType.STATIC,trap.id)
        return replace(state,placement=PlacementState(holders))

    def actual_pairs(self,state):
        eligible=[]
        for key,atom in state.atoms.items():
            if not atom.alive:continue
            p=state.placement.position(key,state.world,state.aod)
            if any(z.zone_type==ZoneType.ENTANGLEMENT and z.bounds.contains(p) for z in state.world.zones):
                eligible.append((key,p))
        return frozenset(tuple(sorted((a,b))) for (a,pa),(b,pb) in combinations(eligible,2)
                         if distance(pa,pb)<=state.hardware.interaction_distance_um+1e-9)

    def validate_pulse(self,state,gate_id):
        if state.aod.is_moving:raise ValidationError('AOD_MOVING','Pulse requires stationary atoms')
        self.validate_move(state,state.aod.pose)
        gate=state.dag.nodes[gate_id].gate
        expected=frozenset((tuple(sorted(gate.qubit_ids)),))
        actual=self.actual_pairs(state)
        if actual!=expected:
            raise ValidationError('UNINTENDED_PAIR',f'Actual pairs {sorted(actual)} != intended {sorted(expected)}',
                atom_ids=tuple(sorted({a for pair in actual|expected for a in pair})))
        return actual
