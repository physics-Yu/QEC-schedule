"""Validate committed serial event boundaries, never intermediate reducer states."""
import json
from math import isclose, isfinite
from dataclasses import replace
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.domain.models import EventType, GateStatus, HolderRef, HolderType, Position2D, SimulationEvent
from neutral_atom_env.domain.operations import OperationType
from neutral_atom_env.replay.operation_codec import event_from_dict
from neutral_atom_env.hardware.rigid_aod import distance
from .event_queue import EventQueue


def validate_runtime(state):
    def require(condition, message, code='INVALID_RUNTIME'):
        if not condition:
            raise ValidationError(code, message)

    runtime=state.active_plan
    pending=[e for _,_,e in state.event_queue.entries]
    physical=[json.loads(r)['event'] for r in state.trace.records
              if json.loads(r)['event']['event_type'].startswith(('plan_', 'operation_'))]
    if runtime is None:
        require(not state.reservations, 'Reservations without active plan')
        require(not physical or physical[-1]['event_type']=='plan_completed', 'Unfinished physical trace without runtime')
        physical_pending=[e for e in pending if e.event_type.value.startswith(('plan_', 'operation_'))]
        if physical_pending:
            require(len(pending)==1 and pending[0].event_type==EventType.PLAN_STARTED, 'Orphan or duplicate physical event')
            event=pending[0]
            require(event.time_us==state.time_us and event.plan_id==event.plan.id, 'Invalid pending plan start')
            from neutral_atom_env.motion.compiler import exact_validate
            exact_validate(event.plan,replace(state,event_queue=EventQueue((),state.event_queue.next_sequence-1)))
        return

    plan=runtime.plan
    require(bool(plan.operations) and len(plan.intent.gate_ids)==1, 'Invalid active plan')
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
    require(bool(bindings), 'Empty capture set')
    from neutral_atom_env.hardware import get_backend
    from neutral_atom_env.domain.aod import motion_target
    backend=get_backend(state.hardware)
    require(plan.initial_aod_configuration is not None, 'Missing initial AOD axes')
    aod=state.aod.configured(plan.initial_aod_configuration)
    expected_configuration=aod.configuration()
    holders=dict(plan.predicted_placement)
    time=runtime.started_us
    events=[first]
    pulse_done=False
    moving=False
    gate=next(iter(plan.intent.gate_ids))
    for i,op in enumerate(plan.operations):
        require(op.id==f'op{i:02d}' and isfinite(op.duration_us) and op.duration_us>0, 'Invalid operation identity/duration')
        duration={OperationType.AOD_LOAD:state.hardware.load_duration_us,
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
                for b in (bindings if op.operation_type==OperationType.AOD_LOAD else op.transfer_bindings):
                    holders[b.atom_id]=HolderRef(HolderType.MOBILE,b.cell)
            elif op.operation_type in (OperationType.AOD_OFFLOAD,OperationType.AOD_PARK):
                for b in (bindings if op.operation_type==OperationType.AOD_OFFLOAD else op.transfer_bindings):
                    holders[b.atom_id]=HolderRef(HolderType.STATIC,b.static_trap_id)
            elif op.operation_type==OperationType.AOD_MOVE: expected_configuration=aod.configuration()
            elif op.operation_type==OperationType.ENTANGLING_PULSE: pulse_done=True
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
    running=(runtime.operation_index<len(plan.operations) and runtime.operation_started_us is not None
             and plan.operations[runtime.operation_index].operation_type==OperationType.ENTANGLING_PULSE)
    status=GateStatus.COMPLETED if pulse_done else GateStatus.RUNNING if running else GateStatus.RESERVED
    require(state.dag.nodes[gate].status==status, 'Gate status differs from pulse boundary')
    require(isclose(time-runtime.started_us,plan.estimated_duration_us,rel_tol=0,abs_tol=1e-8), 'Plan total duration mismatch')
