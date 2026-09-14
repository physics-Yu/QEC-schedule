"""Addressed single-qubit U pulse eligibility; no quantum-state/noise simulation."""
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.domain.models import HolderType, Position2D
from neutral_atom_env.domain.operations import OperationType as K
from neutral_atom_env.domain.aod import motion_target
from .gate_contract import SINGLE_QUBIT_GATES


def validate_rotation_batch(state, gate_ids, *, time_us=None, check_neighbors=True):
    """One addressed pulse: identical named gates on distinct physical targets.

    False conditional slots complete without light, as for a singular rotation;
    support/trajectory requirements therefore apply to the actual lit targets.
    """
    ids=tuple(gate_ids)
    if not ids or len(set(ids))!=len(ids) or any(g not in state.dag.nodes for g in ids):
        raise ValidationError('INVALID_RAMAN_BATCH','Raman batch needs known distinct gate IDs')
    gates=tuple(state.dag.nodes[g].gate for g in ids)
    if any(g.gate_type not in SINGLE_QUBIT_GATES for g in gates):
        raise ValidationError('UNSUPPORTED_GATE','Raman batch supports H, X, Y, Z, T only')
    if len({g.gate_type for g in gates})!=1:
        raise ValidationError('MIXED_RAMAN_BATCH','Raman batch requires identical named gates')
    targets=tuple(g.qubit_ids[0] for g in gates)
    if len(set(targets))!=len(targets):
        raise ValidationError('OVERLAPPING_RAMAN_BATCH','Raman batch targets must be distinct')
    for gid in ids:
        validate_rotation(state,gid,time_us=time_us,check_neighbors=check_neighbors)
    return gates


def validate_rotation_batch_sweep(state,gate_ids,target=None,start_fraction=0.,end_fraction=1.):
    ids=tuple(gate_ids)
    validate_rotation_batch(state,ids,check_neighbors=False)
    for gid in ids:
        validate_rotation_sweep(state,gid,target,start_fraction,end_fraction)


def validate_rotation(state, gate_id, *, time_us=None, check_neighbors=True):
    gate = state.dag.nodes[gate_id].gate
    from neutral_atom_env.simulation.quantum_effects import condition_applies,validate_tracked_unitary
    validate_tracked_unitary(state,gate)
    if not condition_applies(state,gate):return gate
    if gate.gate_type not in SINGLE_QUBIT_GATES:
        raise ValidationError('UNSUPPORTED_GATE', 'Executable single-qubit gates are H, X, Y, Z, T only')
    q = gate.qubit_ids[0]
    holder = state.placement.atom_to_holder[q]
    if state.transfer is not None and any(b.atom_id==q for b in state.transfer.bindings):
        raise ValidationError('RAMAN_HANDOFF_ACTIVE', '1Q requires completed target handoff')
    if holder.holder_type == HolderType.MOBILE and state.aod.is_moving:
        raise ValidationError('RAMAN_TARGET_MOVING', 'AOD target must remain stationary throughout 1Q light')
    enabled = (state.slm_enabled[holder.holder_id] if holder.holder_type == HolderType.STATIC
               else state.aod.is_enabled(holder.holder_id) if holder.holder_type == HolderType.MOBILE else False)
    if not enabled or not state.atoms[q].alive or state.atoms[q].measured:
        raise ValidationError('RAMAN_TARGET_UNAVAILABLE', 'Target must be alive, unmeasured and supported by an enabled SLM or AOD')
    pos = state.placement.position(q, state.world, state.aod)
    if not any(z.zone_type.value in state.hardware.raman_zone_types and z.bounds.contains(pos) for z in state.world.zones):
        raise ValidationError('RAMAN_ZONE_UNAVAILABLE', 'Target is outside configured Raman addressing zones')
    if check_neighbors:
        target=None;fraction=0.
        if state.aod.is_moving and state.active_plan is not None:
            running=dict(state.active_plan.running_operations)
            for op in state.active_plan.plan.operations:
                if op.id in running and op.operation_type==K.AOD_MOVE:
                    target=motion_target(op)
                    fraction=((state.time_us if time_us is None else time_us)-running[op.id])/op.duration_us
                    break
        validate_rotation_sweep(state,gate_id,target,fraction,fraction)
    return gate


def validate_rotation_sweep(state,gate_id,target=None,start_fraction=0.,end_fraction=1.):
    """Exact distance to all alive neighbors over a clipped monotone move.

    Both backends follow a straight spatial segment, with linear or shared
    cubic time progress. Fractions are physical elapsed-time fractions.
    """
    from . import get_backend
    from .rigid_aod import segment_clearance
    gate=validate_rotation(state,gate_id,check_neighbors=False)
    from neutral_atom_env.simulation.quantum_effects import condition_applies
    if not condition_applies(state,gate):return
    q=gate.qubit_ids[0];point=state.placement.position(q,state.world,state.aod)
    if target is not None and state.placement.atom_to_holder[q].holder_type == HolderType.MOBILE:
        raise ValidationError('RAMAN_TARGET_MOVING', 'AOD target cannot move during 1Q light')
    backend=get_backend(state.hardware)
    end=backend.target_aod(state.aod,target) if target is not None else state.aod
    def progress(v):
        v=max(0.,min(1.,v))
        return 3*v*v-2*v*v*v if backend.motion_profile=='cubic' else v
    a,b=progress(start_fraction),progress(end_fraction)
    for other,atom in state.atoms.items():
        if other==q or not atom.alive:continue
        holder=state.placement.atom_to_holder[other]
        start=state.placement.position(other,state.world,state.aod);finish=start
        if holder.holder_type==HolderType.MOBILE and target is not None:
            dest=end.position(holder.holder_id)
            def at(t):return Position2D(start.x_um+(dest.x_um-start.x_um)*t,start.y_um+(dest.y_um-start.y_um)*t)
            left,right=at(a),at(b)
        else:left,right=start,finish
        d,closest=segment_clearance(point,left,right)
        if d+1e-9<state.hardware.raman_minimum_separation_um:
            raise ValidationError('RAMAN_NEIGHBOR_TOO_CLOSE',
                f'Single-qubit light requires neighbor distance >= {state.hardware.raman_minimum_separation_um:g} um; {other} reaches {d:g} um',
                atom_ids=(q,other),position=closest)
