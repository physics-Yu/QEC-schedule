"""Validate committed serial event boundaries, never intermediate reducer states."""
import json
from math import isclose, isfinite
from dataclasses import replace
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.domain.models import EventType, GateStatus, HolderRef, HolderType, Position2D, SimulationEvent
from neutral_atom_env.domain.operations import OperationType, TaskIntent
from neutral_atom_env.replay.operation_codec import event_from_dict
from neutral_atom_env.hardware.rigid_aod import distance
from .event_queue import EventQueue
from neutral_atom_env.replay.trace import _event_data


def validate_runtime(state):
    from neutral_atom_env.hardware.ez_neighbors import validate_ez_neighbors
    validate_ez_neighbors(state)
    def require(condition, message, code='INVALID_RUNTIME'):
        if not condition:
            raise ValidationError(code, message)

    runtime=state.active_plan
    pending=[e for _,_,e in state.event_queue.entries]
    physical=[e for r in state.trace.records if
              (e := _event_data(r))['event_type'].startswith(('plan_', 'operation_'))]
    previous=next((event_from_dict(e).plan for e in reversed(physical) if e['event_type']=='plan_started'),None) if runtime is None else None
    if runtime is not None and runtime.plan.execution_mode=='scheduled':
        from .operation_program import validate_program_runtime
        validate_program_runtime(state,runtime.plan)
        return
    if runtime is None and previous is not None and previous.execution_mode=='scheduled':
        from .operation_program import validate_program_runtime
        validate_program_runtime(replace(state,event_queue=EventQueue()) if pending else state,previous)
        if any(e.event_type.value.startswith(('plan_','operation_')) for e in pending):
            require(len(pending)==1 and pending[0].event_type==EventType.PLAN_STARTED,'Unexpected event after program')
            require(pending[0].time_us==state.time_us and pending[0].plan_id==pending[0].plan.id,'Invalid pending plan start')
            from neutral_atom_env.motion.compiler import exact_validate
            exact_validate(pending[0].plan,replace(state,event_queue=EventQueue((),state.event_queue.next_sequence-1)))
        else:
            require(all(e.event_type in {EventType.WAIT_COMPLETED,EventType.RNG_DRAW} for e in pending),'Unexpected nonphysical event after program')
        return
    if runtime is None:
        require(state.transfer is None, 'Handoff without an active operation')
        from neutral_atom_env.hardware.dynamic_traps import validate_active_sweep
        validate_active_sweep(state,state.aod)
        require(not state.reservations, 'Reservations without active plan')
        require(not physical or physical[-1]['event_type']=='plan_completed', 'Unfinished physical trace without runtime')
        if physical:
            from neutral_atom_env.hardware.dynamic_traps import trap_state
            previous=next(event_from_dict(e).plan for e in reversed(physical) if e['event_type']=='plan_started')
            require(trap_state(state)==previous.predicted_traps,'Idle supports differ from completed program')
            if isinstance(previous.intent,TaskIntent):
                from neutral_atom_env.motion.task_validation import validate_target, validate_task_dag
                require(tuple(sorted(state.placement.atom_to_holder.items()))==previous.predicted_placement, 'Idle task placement mismatch')
                validate_target(previous.intent.target,state)
                validate_task_dag(previous,state,GateStatus.COMPLETED if previous.intent.effect_gate_id else None)
        physical_pending=[e for e in pending if e.event_type.value.startswith(('plan_', 'operation_'))]
        if physical_pending:
            require(len(pending)==1 and pending[0].event_type==EventType.PLAN_STARTED, 'Orphan or duplicate physical event')
            event=pending[0]
            require(event.time_us==state.time_us and event.plan_id==event.plan.id, 'Invalid pending plan start')
            from neutral_atom_env.motion.compiler import exact_validate
            exact_validate(event.plan,replace(state,event_queue=EventQueue((),state.event_queue.next_sequence-1)))
        return

    plan=runtime.plan
    require(bool(plan.operations) and (len(plan.intent.gate_ids)==1 or isinstance(plan.intent,TaskIntent)), 'Invalid active plan')
    require(type(runtime.operation_index) is int and 0<=runtime.operation_index<=len(plan.operations), 'Invalid cursor')
    require(isfinite(runtime.started_us) and 0<=runtime.started_us<=state.time_us, 'Invalid plan start time')
    require(tuple((r.resource_id,r.plan_id) for r in state.reservations)==tuple((r,plan.id) for r in plan.resources), 'Reservation set differs from plan')
    require(len(set(plan.resources))==len(plan.resources), 'Duplicate plan resources')
    starts=[i for i,e in enumerate(physical) if e['event_type']=='plan_started']
    require(bool(starts), 'Runtime has no committed plan start')
    suffix=physical[starts[-1]:]
    first=event_from_dict(suffix[0])
    require(first.plan==plan and first.time_us==runtime.started_us, 'Runtime plan differs from committed plan')
    require(first.plan.state_version==state.version-len(suffix), 'Plan version or trace cursor differs')

    from neutral_atom_env.motion.validation import validate_plan
    validate_plan(plan,state,restoring=True)

    # Eager plans return every atom and the AOD to their per-plan starting state.
    bindings=plan.bindings
    require(bool(bindings) or plan.initial_placement is not None, 'Empty legacy capture set')
    from neutral_atom_env.hardware import get_backend
    from neutral_atom_env.domain.aod import motion_target
    backend=get_backend(state.hardware)
    require(plan.initial_aod_configuration is not None, 'Missing initial AOD axes')
    aod=state.aod.configured(plan.initial_aod_configuration)
    expected_configuration=aod.configuration()
    holders=dict(plan.initial_placement if plan.initial_placement is not None else plan.predicted_placement)
    time=runtime.started_us
    events=[first]
    pulse_done=False
    moving=False
    gate=next(iter(plan.intent.gate_ids),None)
    for i,op in enumerate(plan.operations):
        require(op.id==f'op{i:02d}' and isfinite(op.duration_us) and op.duration_us>0, 'Invalid operation identity/duration')
        duration={OperationType.RAMAN_ROTATION:state.hardware.raman_duration_us,OperationType.TRAP_SWITCH:state.hardware.switch_duration_us,OperationType.AOD_LOAD:state.hardware.load_duration_us,
                  OperationType.AOD_OFFLOAD:state.hardware.offload_duration_us,
                  OperationType.ENTANGLING_PULSE:state.hardware.pulse_duration_us,
                  OperationType.AOD_PARK:state.hardware.offload_duration_us,OperationType.AOD_RECAPTURE:state.hardware.load_duration_us}.get(op.operation_type)
        if op.operation_type==OperationType.AOD_MOVE:
            require(motion_target(op) is not None, 'Missing move target')
            require(not (op.target_pose is not None and op.target_configuration is not None), 'Ambiguous move target')
            duration=backend.move_duration(aod,motion_target(op),state.hardware)
            aod=backend.target_aod(aod,motion_target(op))
        require(isclose(duration,op.duration_us,rel_tol=0,abs_tol=1e-9), 'Operation hardware timing mismatch')
        if i<runtime.operation_index:
            events.extend((SimulationEvent(time,EventType.OPERATION_STARTED,plan_id=plan.id,operation_id=op.id),
                           SimulationEvent(time+duration,EventType.OPERATION_COMPLETED,plan_id=plan.id,operation_id=op.id)))
            if op.operation_type in (OperationType.AOD_LOAD,OperationType.AOD_RECAPTURE):
                for b in (op.transfer_bindings or bindings):
                    holders[b.atom_id]=HolderRef(HolderType.MOBILE,b.cell)
            elif op.operation_type in (OperationType.AOD_OFFLOAD,OperationType.AOD_PARK):
                for b in (op.transfer_bindings or bindings):
                    holders[b.atom_id]=HolderRef(HolderType.STATIC,b.static_trap_id)
            elif op.operation_type==OperationType.AOD_MOVE: expected_configuration=aod.configuration()
            elif op.operation_type in (OperationType.ENTANGLING_PULSE,OperationType.RAMAN_ROTATION): pulse_done=True
        elif i==runtime.operation_index:
            if runtime.operation_started_us is not None:
                require(runtime.operation_started_us==time, 'Operation start differs from timeline')
                events.append(SimulationEvent(time,EventType.OPERATION_STARTED,plan_id=plan.id,operation_id=op.id))
                expected=SimulationEvent(time+duration,EventType.OPERATION_COMPLETED,plan_id=plan.id,operation_id=op.id)
                moving=op.operation_type==OperationType.AOD_MOVE
            else:
                expected=SimulationEvent(time,EventType.OPERATION_STARTED,plan_id=plan.id,operation_id=op.id)
        time+=duration
    if runtime.operation_index==len(plan.operations):
        require(runtime.operation_started_us is None, 'Finished cursor still running')
        expected=SimulationEvent(time,EventType.PLAN_COMPLETED,plan_id=plan.id)
    require([event_from_dict(e) for e in suffix]==events, 'Trace and operation cursor disagree')
    require(state.time_us==events[-1].time_us, 'Runtime time differs from last commit')
    require(len(pending)==1, 'Missing or duplicate pending physical event')
    require(pending[0]==expected, 'Pending physical event differs from cursor/timing',
            'INVALID_COMPLETION_TIME' if pending[0].event_type==EventType.OPERATION_COMPLETED else 'INVALID_RUNTIME')
    require(state.placement.atom_to_holder==holders and state.aod.configuration()==expected_configuration, 'Placement/pose differs from operation boundary')
    require(state.aod.is_moving==moving, 'Movement flag differs from operation boundary')
    # Reconstruct supports from the declared origin, never from current masks.
    from neutral_atom_env.hardware.dynamic_traps import trap_state, begin_transfer, TRANSFERS
    from neutral_atom_env.motion.program import apply_operation
    from neutral_atom_env.motion.validation import plan_origin_dag
    from neutral_atom_env.world import PlacementState
    work=replace(state,placement=PlacementState(dict(plan.initial_placement if plan.initial_placement is not None else plan.predicted_placement)),
                 aod=replace(state.aod.configured(plan.initial_aod_configuration),is_moving=False,
                             enabled_rows=plan.initial_traps.rows,enabled_columns=plan.initial_traps.columns),
                 slm_enabled=dict(plan.initial_traps.slm),transfer=None,dag=plan_origin_dag(plan,state))
    for op in plan.operations[:runtime.operation_index]:
        op=replace(op,transfer_bindings=op.transfer_bindings or plan.bindings) if op.operation_type in TRANSFERS or op.transfer_phase else op
        work=apply_operation(work,op,gate)
    if runtime.operation_started_us is not None:
        op=plan.operations[runtime.operation_index]
        if op.operation_type in TRANSFERS:
            work=begin_transfer(backend,work,op.transfer_bindings or plan.bindings,op.operation_type)
    require(trap_state(state)==trap_state(work) and state.transfer==work.transfer, 'Support/transfer stage differs from operation boundary')
    running=(runtime.operation_index<len(plan.operations) and runtime.operation_started_us is not None
             and plan.operations[runtime.operation_index].operation_type in (OperationType.ENTANGLING_PULSE,OperationType.RAMAN_ROTATION))
    status=GateStatus.COMPLETED if pulse_done else GateStatus.RUNNING if running else GateStatus.RESERVED
    if isinstance(plan.intent,TaskIntent):
        from neutral_atom_env.motion.task_validation import validate_task_dag
        validate_task_dag(plan,state,status if gate else None)
    elif gate:
        require(state.dag.nodes[gate].status==status, 'Gate status differs from pulse boundary')
    require(isclose(time-runtime.started_us,plan.estimated_duration_us,rel_tol=0,abs_tol=1e-8), 'Plan total duration mismatch')
