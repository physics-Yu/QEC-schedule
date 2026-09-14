"""Independent plan audit: replay supplied operations, never regenerate a route."""
from dataclasses import replace
from math import isclose,isfinite
from neutral_atom_env.domain.aod import motion_target
from neutral_atom_env.domain.models import GateStatus, HolderType
from neutral_atom_env.domain.operations import EndDisposition, OperationType as K, TaskIntent
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.hardware import get_backend
from neutral_atom_env.world import PlacementState


def require(value,message):
    if not value:raise ValidationError('PLAN_TAMPERED',message)


def plan_origin_dag(plan,state):
    """Recover the logical origin together with the physical replay origin."""
    if plan.initial_dag is not None:
        from neutral_atom_env.program.task_validation import origin_dag
        return origin_dag(plan,state)
    # Legacy serial plans predate stored origin DAGs. During their execution
    # only their own effect changes logical status; reconstruct that boundary
    # from completed predecessors, never replay on the already-completed gate.
    from neutral_atom_env.circuit import DynamicGateDAG
    dag=DynamicGateDAG(state.dag.circuit)
    for gate in state.dag.circuit.gates:
        status=state.dag.nodes[gate.id].status
        if gate.id not in plan.intent.gate_ids and status in {GateStatus.COMPLETED,GateStatus.FAILED}:
            require(dag.nodes[gate.id].status==GateStatus.READY,'Inconsistent legacy plan origin dependencies')
            dag=dag.transitioned(gate.id,GateStatus.RESERVED)
            if status==GateStatus.COMPLETED:dag=dag.transitioned(gate.id,GateStatus.RUNNING)
            dag=dag.transitioned(gate.id,status)
    return dag


def plan_resources(state,requested,bindings,operations=()):
    if operations and all(op.operation_type == K.RAMAN_ROTATION for op in operations):
        mobile=any(state.placement.atom_to_holder[a].holder_type==HolderType.MOBILE for a in requested)
        return (('AOD_0',) if mobile else ()) + tuple('RAMAN:'+a for a in sorted(requested)) + tuple('atom:'+a for a in sorted(requested)) + tuple(
            'trap:'+state.placement.atom_to_holder[a].holder_id for a in sorted(requested)
            if state.placement.atom_to_holder[a].holder_type==HolderType.STATIC)
    base=('AOD_0','ENTANGLING_LASER_0',state.hardware.interaction_slot_id)+tuple('atom:'+a for a in sorted(set(requested)|{b.atom_id for b in bindings}))+tuple('trap:'+b.static_trap_id for b in bindings)
    extra=sorted({'trap:'+b.static_trap_id for op in operations for b in op.transfer_bindings}-set(base))
    if any(op.operation_type == K.RAMAN_ROTATION for op in operations):
        extra.extend('RAMAN:'+a for a in sorted(requested))
    return base+tuple(extra)


def replay_operations(intent,state,bindings,operations):
    if any(op.operation_type in (K.AOD_PARK,K.AOD_RECAPTURE) for op in operations):
        from neutral_atom_env.program.parking_validation import replay_parking
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
            else:
                backend.validate_pulse(work,gate.gate.id)
                from neutral_atom_env.program.builder import predict_cz_completion
                work=predict_cz_completion(work,gate.gate.id)
    require(work.placement==state.placement and work.aod.configuration()==state.aod.configuration(),'RETURN_AND_OFFLOAD must restore initial placement and axes')
    return work,travel


def validate_plan(plan,state,*,restoring=False):
    require(plan.execution_mode in {'serial','scheduled'},'Unknown execution mode')
    require(state.quantum_state is None or plan.execution_mode=='scheduled','Quantum tracking requires a scheduled program')
    if plan.execution_mode=='scheduled':
        from neutral_atom_env.simulation.operation_program import validate_program
        return validate_program(plan,state,restoring)
    from neutral_atom_env.program.binding import fingerprint
    from neutral_atom_env.hardware.dynamic_traps import trap_state, with_traps
    require(plan.initial_traps is not None and plan.predicted_traps is not None, 'Missing support origin/prediction')
    require(all((op.operation_type==K.TRAP_SWITCH)==(op.switch_state is not None) for op in plan.operations), 'Invalid switch operation fields')
    task = isinstance(plan.intent, TaskIntent)
    if task:
        from neutral_atom_env.program.task_validation import validate_task_origin
        validate_task_origin(plan, state, restoring)
    else:
        require(not plan.operation_intervals and plan.initial_dag is None, 'Unexpected task metadata on legacy gate plan')
        require(all(op.gate_id is None and not op.gate_ids and not op.depends_on for op in plan.operations), 'Unexpected task operation metadata')
    if not restoring:
        if plan.state_version!=state.version or plan.state_fingerprint!=fingerprint(state):
            raise ValidationError('OUTDATED_STATE','Plan was compiled against another state')
        require(not (state.active_plan or state.reservations or state.event_queue),'Plan requires idle resources')
        require(plan.initial_placement is not None or not state.placement.mobile_occupancy,'Legacy cycle requires empty AOD')
        require(task or len(plan.intent.gate_ids)==1, 'Unknown gate')
        require(all(g in state.dag.nodes for g in plan.intent.gate_ids), 'Unknown gate')
        require(all(state.dag.nodes[g].status==GateStatus.READY for g in plan.intent.gate_ids),'Gate is not READY')
        require(plan.initial_aod_configuration==state.aod.configuration(),'Initial axes mismatch')
        require(plan.initial_traps==trap_state(state),'Initial light supports mismatch')
        from neutral_atom_env.hardware.dynamic_traps import validate_active_sweep
        require(state.transfer is None,'Plan origin is in an unfinished handoff')
        validate_active_sweep(state,state.aod)
    else:
        # Geometry and the pre-effect DAG must be restored atomically: the
        # current post-CZ DAG can have different EZ neighbor reservations.
        require(plan.initial_aod_configuration is not None,'Missing initial axes')
        state=replace(state,placement=PlacementState(dict(plan.initial_placement if plan.initial_placement is not None else plan.predicted_placement)),
                      aod=replace(state.aod.configured(plan.initial_aod_configuration),is_moving=False,
                                  enabled_rows=plan.initial_traps.rows,enabled_columns=plan.initial_traps.columns),
                      slm_enabled=dict(plan.initial_traps.slm),transfer=None,dag=plan_origin_dag(plan,state))
    if plan.initial_placement is not None:
        from neutral_atom_env.program.builder import replay_program
        work,travel=replay_program(plan,state)
    else:
        work,travel=replay_operations(plan.intent,state,plan.bindings,plan.operations)
    from neutral_atom_env.program.task_validation import requested_atoms, task_intervals
    requested=requested_atoms(plan.intent,state)
    if task:
        intervals=task_intervals(plan,state)
        affected=frozenset(q for interval in intervals for q in interval.atom_ids)
        require(plan.operation_intervals==intervals, 'Task operation intervals mismatch')
        require(plan.requested_atom_ids==requested and plan.incidental_atom_ids==affected-requested, 'Task affected atom metadata mismatch')
        require(plan.resources==tuple(sorted({r for interval in intervals for r in interval.resources})), 'Task resource set mismatch')
    else:
        require(plan.requested_atom_ids==requested and plan.incidental_atom_ids==plan.captured_atom_ids-requested,'Operand/capture metadata mismatch')
        require(plan.resources==plan_resources(state,requested,plan.bindings,plan.operations),'Resource set mismatch')
    require(plan.predicted_placement==tuple(sorted(work.placement.atom_to_holder.items())),'Predicted placement mismatch')
    require(plan.predicted_traps==trap_state(work),'Predicted support state mismatch')
    require(isclose(plan.estimated_distance_um,travel,rel_tol=0,abs_tol=1e-9),'Total travel mismatch')
    require(isclose(plan.estimated_duration_us,sum(o.duration_us for o in plan.operations),rel_tol=0,abs_tol=1e-9),'Total duration mismatch')
