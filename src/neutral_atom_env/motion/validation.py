"""Independent plan audit: replay supplied operations, never regenerate a route."""
from dataclasses import replace
from math import isclose,isfinite
from neutral_atom_env.domain.aod import motion_target
from neutral_atom_env.domain.models import GateStatus
from neutral_atom_env.domain.operations import EndDisposition,OperationType as K
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.hardware import get_backend
from neutral_atom_env.world import PlacementState


def require(value,message):
    if not value:raise ValidationError('PLAN_TAMPERED',message)


def plan_resources(state,requested,bindings,operations=()):
    base=('AOD_0','ENTANGLING_LASER_0',state.hardware.interaction_slot_id)+tuple('atom:'+a for a in sorted(set(requested)|{b.atom_id for b in bindings}))+tuple('trap:'+b.static_trap_id for b in bindings)
    extra=sorted({'trap:'+b.static_trap_id for op in operations for b in op.transfer_bindings}-set(base))
    return base+tuple(extra)


def replay_operations(intent,state,bindings,operations):
    if any(op.operation_type in (K.AOD_PARK,K.AOD_RECAPTURE) for op in operations):
        from .parking_validation import replay_parking
        return replay_parking(intent,state,bindings,operations)
    require(not any(op.transfer_bindings for op in operations),'Unexpected partial transfer fields')
    require(intent.end_disposition==EndDisposition.RETURN_AND_OFFLOAD and len(intent.gate_ids)==1,'Only serial return/offload CZ is supported')
    gate=state.dag.nodes.get(next(iter(intent.gate_ids)))
    require(gate is not None and gate.gate.gate_type=='CZ','Unknown or unsupported gate')
    require(bool(bindings) and len({b.atom_id for b in bindings})==len(bindings),'Empty or duplicate capture set')
    kinds=[o.operation_type for o in operations]
    require(all(k in {K.AOD_MOVE,K.AOD_LOAD,K.AOD_OFFLOAD,K.ENTANGLING_PULSE} for k in kinds),'Unknown operation')
    require(all(kinds.count(k)==1 for k in (K.AOD_LOAD,K.ENTANGLING_PULSE,K.AOD_OFFLOAD)),'Require one load, pulse and offload')
    load,pulse,offload=(kinds.index(k) for k in (K.AOD_LOAD,K.ENTANGLING_PULSE,K.AOD_OFFLOAD))
    require(load+1<pulse<offload-1,'Transfers need departure and approach moves')
    work=state;backend=get_backend(state.hardware);travel=0
    for i,op in enumerate(operations):
        require(op.id==f'op{i:02d}' and isfinite(op.duration_us) and op.duration_us>0,'Invalid operation identity or duration')
        kind=op.operation_type;target=motion_target(op)
        phase='depart' if i==load+1 else 'approach' if i==offload-1 else None
        require(op.transfer_phase==phase,'Transfer exemption only immediately after LOAD or before OFFLOAD')
        if kind==K.AOD_MOVE:
            require((op.target_pose is None)!=(op.target_configuration is None),'Move must have exactly one target')
            duration=backend.move_duration(work.aod,target,state.hardware)
            require(isclose(duration,op.duration_us,rel_tol=0,abs_tol=1e-9),'Operation hardware timing mismatch')
            travel+=backend.move_distance(work.aod,target)
            work=backend.move(work,target,transfer=phase,bindings=bindings)
        else:
            require(target is None and op.transfer_phase is None,'Non-move contains motion fields')
            duration={K.AOD_LOAD:state.hardware.load_duration_us,K.AOD_OFFLOAD:state.hardware.offload_duration_us,K.ENTANGLING_PULSE:state.hardware.pulse_duration_us}[kind]
            require(isclose(duration,op.duration_us,rel_tol=0,abs_tol=1e-9),'Operation hardware timing mismatch')
            if kind==K.AOD_LOAD:work=backend.load(work,bindings)
            elif kind==K.AOD_OFFLOAD:work=backend.offload(work,bindings)
            else:backend.validate_pulse(work,gate.gate.id)
    require(work.placement==state.placement and work.aod.configuration()==state.aod.configuration(),'RETURN_AND_OFFLOAD must restore initial placement and axes')
    return work,travel


def validate_plan(plan,state,*,restoring=False):
    from .compiler import fingerprint
    if not restoring:
        if plan.state_version!=state.version or plan.state_fingerprint!=fingerprint(state):
            raise ValidationError('OUTDATED_STATE','Plan was compiled against another state')
        require(not (state.active_plan or state.reservations or state.event_queue or state.placement.mobile_occupancy),'Plan requires idle resources')
        require(len(plan.intent.gate_ids)==1 and state.dag.nodes.get(next(iter(plan.intent.gate_ids))) is not None,'Unknown gate')
        require(state.dag.nodes[next(iter(plan.intent.gate_ids))].status==GateStatus.READY,'Gate is not READY')
        require(plan.initial_aod_configuration==state.aod.configuration(),'Initial axes mismatch')
    else:
        # Eager postcondition equals the origin; reconstruct only geometry for full-path audit.
        require(plan.initial_aod_configuration is not None,'Missing initial axes')
        state=replace(state,placement=PlacementState(dict(plan.predicted_placement)),
                      aod=replace(state.aod.configured(plan.initial_aod_configuration),is_moving=False))
    work,travel=replay_operations(plan.intent,state,plan.bindings,plan.operations)
    requested=frozenset(state.dag.nodes[next(iter(plan.intent.gate_ids))].gate.qubit_ids)
    require(plan.requested_atom_ids==requested and plan.incidental_atom_ids==plan.captured_atom_ids-requested,'Operand/capture metadata mismatch')
    require(plan.resources==plan_resources(state,requested,plan.bindings,plan.operations),'Resource set mismatch')
    require(plan.predicted_placement==tuple(sorted(work.placement.atom_to_holder.items())),'Predicted placement mismatch')
    require(isclose(plan.estimated_distance_um,travel,rel_tol=0,abs_tol=1e-9),'Total travel mismatch')
    require(isclose(plan.estimated_duration_us,sum(o.duration_us for o in plan.operations),rel_tol=0,abs_tol=1e-9),'Total duration mismatch')
