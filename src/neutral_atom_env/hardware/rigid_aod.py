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
        # Rigid means preserving relative offsets, not requiring uniform pitch.
        # The actual Cartesian axes may have different/nonuniform spacings.
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

    def capture_closure(self,state,pose,*,active_only=False):
        if state.placement.mobile_occupancy or state.aod.is_moving:
            raise ValidationError('AOD_BUSY','Capture requires an empty idle AOD')
        self.validate_pose(state,pose)
        aod=replace(state.aod,pose=pose);tol=state.hardware.alignment_tolerance_um
        bindings=[];axes=aod.configuration()
        for key,holder in sorted(state.placement.atom_to_holder.items()):
            if holder.holder_type!=HolderType.STATIC:continue
            p=state.placement.position(key,state.world,aod)
            if (axes.x_um[0]-tol<=p.x_um<=axes.x_um[-1]+tol and
                axes.y_um[0]-tol<=p.y_um<=axes.y_um[-1]+tol):
                row=min(range(aod.rows),key=lambda i:abs(axes.y_um[i]-p.y_um))
                col=min(range(aod.columns),key=lambda i:abs(axes.x_um[i]-p.x_um))
                cell=MobileCellIndex(row,col)
                # During a bound LOAD, only enabled intersections have fields.
                # A distant atom between inactive capacity cells is not captured.
                # Keep the legacy footprint planner's conservative default.
                if active_only and all(distance(aod.position(c),p)>=state.hardware.minimum_clearance_um
                                       for c in aod.active_cells):
                    continue
                if distance(aod.position(cell),p)>tol:
                    raise ValidationError('CAPTURE_MISALIGNMENT','Atom within footprint does not align with a mobile cell',atom_ids=(key,),position=p)
                bindings.append(CaptureBinding(key,cell,holder.holder_id))
        return tuple(bindings)

    def load(self,state,bindings):
        from .dynamic_traps import transfer
        from neutral_atom_env.domain.operations import OperationType
        return transfer(self,state,bindings,OperationType.AOD_LOAD)

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
        if state.transfer is not None:
            raise ValidationError('TRANSFER_BUSY','Motion cannot interrupt a handoff')
        self.validate_geometry_move(state,target)
        from .dynamic_traps import validate_active_sweep
        validate_active_sweep(state,self.target_aod(state.aod,target))
        from .slm_clearance import validate_slm_clearance
        validate_slm_clearance(state,self.target_aod(state.aod,target),transfer,bindings)
        from .ez_neighbors import validate_ez_neighbors
        validate_ez_neighbors(state, aod=self.target_aod(state.aod,target))

    def move(self,state,target,*,transfer=None,bindings=()):
        self.validate_move(state,target,transfer=transfer,bindings=bindings)
        return replace(state,aod=replace(state.aod,pose=target,is_moving=False))

    def offload(self,state,bindings):
        from .dynamic_traps import transfer
        from neutral_atom_env.domain.operations import OperationType
        return transfer(self,state,bindings,OperationType.AOD_OFFLOAD)

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
        return self.validate_pulse_batch(state,(gate_id,))

    def validate_pulse_batch(self,state,gate_ids):
        gate_ids=tuple(gate_ids)
        if not gate_ids or len(set(gate_ids))!=len(gate_ids) or any(g not in state.dag.nodes for g in gate_ids):
            raise ValidationError('INVALID_CZ_BATCH','CZ batch requires known unique gates')
        gates=tuple(state.dag.nodes[g].gate for g in gate_ids)
        if any(g.gate_type!='CZ' for g in gates):
            raise ValidationError('UNSUPPORTED_GATE','Entangling pulse only executes CZ')
        qubits=tuple(q for g in gates for q in g.qubit_ids)
        if any(not state.atoms[q].alive or state.atoms[q].measured for q in qubits):
            raise ValidationError('CZ_TARGET_UNAVAILABLE','CZ targets must be alive and reset after measurement',atom_ids=qubits)
        if len(set(qubits))!=len(qubits):
            raise ValidationError('OVERLAPPING_CZ_BATCH','Parallel CZ gates must have disjoint qubits',atom_ids=qubits)
        if len(gate_ids)>1:
            statuses={state.dag.nodes[g].status.value for g in gate_ids}
            if len(statuses)!=1 or not statuses<={'ready','reserved','running'}:
                raise ValidationError('CZ_BATCH_NOT_READY','CZ batch is blocked or already completed, or has mixed execution phases')
        if state.aod.is_moving:raise ValidationError('AOD_MOVING','Pulse requires stationary atoms')
        self.validate_move(state,state.aod.pose)
        expected=frozenset(tuple(sorted(g.qubit_ids)) for g in gates)
        actual=self.actual_pairs(state)
        if actual!=expected:
            raise ValidationError('UNINTENDED_PAIR',f'Actual pairs {sorted(actual)} != intended {sorted(expected)}',
                atom_ids=tuple(sorted({a for pair in actual|expected for a in pair})))
        return actual
