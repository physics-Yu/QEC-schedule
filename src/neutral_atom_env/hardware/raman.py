"""Addressed single-qubit U pulse eligibility; no quantum-state/noise simulation."""
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.domain.models import HolderType, Position2D
from neutral_atom_env.domain.operations import OperationType as K
from neutral_atom_env.domain.aod import motion_target
from neutral_atom_env.hardware.gate_contract import SINGLE_QUBIT_GATES


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


def validate_rotation_batch_sweep(state,gate_ids,target=None,start_fraction=0.,end_fraction=1.,aod_id='AOD_0'):
    ids=tuple(gate_ids)
    validate_rotation_batch(state,ids,check_neighbors=False)
    for gid in ids:
        validate_rotation_sweep(state,gid,target,start_fraction,end_fraction,aod_id=aod_id)


def validate_rotation(state, gate_id, *, time_us=None, check_neighbors=True):
    gate = state.dag.nodes[gate_id].gate
    from neutral_atom_env.simulation.quantum_effects import condition_applies, validate_tracked_unitary
    validate_tracked_unitary(state,gate)
    if not condition_applies(state,gate):return gate
    if gate.gate_type not in SINGLE_QUBIT_GATES:
        raise ValidationError('UNSUPPORTED_GATE', 'Executable single-qubit gates are H, X, Y, Z, T only')
    q = gate.qubit_ids[0]
    holder = state.placement.atom_to_holder[q]
    if any(b.atom_id==q for t in state.transfers.values() for b in t.bindings):
        raise ValidationError('RAMAN_HANDOFF_ACTIVE', '1Q requires completed target handoff')
    if holder.holder_type == HolderType.MOBILE and state.aods[holder.holder_id.aod_id].is_moving:
        raise ValidationError('RAMAN_TARGET_MOVING', 'AOD target must remain stationary throughout 1Q light')
    enabled = (state.slm_enabled[holder.holder_id] if holder.holder_type == HolderType.STATIC
               else state.aods[holder.holder_id.aod_id].is_enabled(holder.holder_id) if holder.holder_type == HolderType.MOBILE else False)
    if not enabled or not state.atoms[q].alive or state.atoms[q].measured:
        raise ValidationError('RAMAN_TARGET_UNAVAILABLE', 'Target must be alive, unmeasured and supported by an enabled SLM or AOD')
    pos = state.placement.position(q, state.world, state.aods)
    if not any(z.zone_type.value in state.hardware.raman_zone_types and z.bounds.contains(pos) for z in state.world.zones):
        raise ValidationError('RAMAN_ZONE_UNAVAILABLE', 'Target is outside configured Raman addressing zones')
    if check_neighbors:
        if len(state.aods)>1:
            validate_rotation_sweep(state,gate_id)
            return gate
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


def validate_rotation_sweep(state,gate_id,target=None,start_fraction=0.,end_fraction=1.,aod_id='AOD_0'):
    """Exact distance to all alive neighbors over a clipped monotone move.

    Both backends follow a straight spatial segment, with linear or shared
    cubic time progress. Fractions are physical elapsed-time fractions.
    """
    from neutral_atom_env.hardware import get_backend
    from neutral_atom_env.hardware.rigid_aod import segment_clearance
    gate=validate_rotation(state,gate_id,check_neighbors=False)
    from neutral_atom_env.simulation.quantum_effects import condition_applies
    if not condition_applies(state,gate):return
    if len(state.aods)>1:
        return _validate_multi_sweep(state,gate,target,start_fraction,end_fraction,aod_id)
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


def _validate_multi_sweep(state,gate,target,start_fraction,end_fraction,aod_id):
    """Full registry; moving lanes use their entire workspace as a safe bound.

    This conservative bound also covers unequal-duration cubic motions. The
    explicit move being proposed gets an exact clipped own-lane segment test.
    """
    from neutral_atom_env.hardware.multi_aod import backend_for
    from neutral_atom_env.hardware.rigid_aod import segment_clearance
    q=gate.qubit_ids[0];point=state.placement.position(q,state.world,state.aods)
    if target is not None and state.placement.atom_to_holder[q].holder_type==HolderType.MOBILE and state.placement.atom_to_holder[q].holder_id.aod_id==aod_id:
        raise ValidationError('RAMAN_TARGET_MOVING','Lit target cannot share its AOD MOVE')
    moving={key for key,a in state.aods.items() if a.is_moving}
    if target is not None: moving.add(aod_id)
    for key in moving:
        # A point-to-envelope lower bound guarantees >=5 um from every atom
        # on a moving foreign lane over its complete actual trajectory.
        if key==aod_id and target is not None: continue
        bound=state.aods[key].envelope
        dx=max(0.,bound.lower.x_um-point.x_um,point.x_um-bound.upper.x_um)
        dy=max(0.,bound.lower.y_um-point.y_um,point.y_um-bound.upper.y_um)
        if (dx*dx+dy*dy)**.5+1e-9<state.hardware.raman_minimum_separation_um:
            raise ValidationError('RAMAN_MOVE_ENVELOPE_TOO_CLOSE','Moving device envelope lacks the full Raman safety margin',atom_ids=(q,))
    end=backend_for(state,aod_id).target_aod(state.aods[aod_id],target) if target is not None else None
    cubic=backend_for(state,aod_id).motion_profile=='cubic'
    def progress(v):
        v=max(0.,min(1.,v));return 3*v*v-2*v*v*v if cubic else v
    a,b=progress(start_fraction),progress(end_fraction)
    for other,atom in state.atoms.items():
        h=state.placement.atom_to_holder[other]
        if other==q or not atom.alive or h.holder_type==HolderType.LOST: continue
        start=state.placement.position(other,state.world,state.aods);left=right=start
        if end is not None and h.holder_type==HolderType.MOBILE and h.holder_id.aod_id==aod_id:
            finish=end.position(h.holder_id)
            left=Position2D(start.x_um+a*(finish.x_um-start.x_um),start.y_um+a*(finish.y_um-start.y_um))
            right=Position2D(start.x_um+b*(finish.x_um-start.x_um),start.y_um+b*(finish.y_um-start.y_um))
        d,closest=segment_clearance(point,left,right)
        if d+1e-9<state.hardware.raman_minimum_separation_um:
            raise ValidationError('RAMAN_NEIGHBOR_TOO_CLOSE','Raman must clear every live neighbor on every device',atom_ids=(q,other),position=closest)
