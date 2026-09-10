"""Physical event reducer; only Executor installs returned states."""
from dataclasses import replace
from math import isclose
from neutral_atom_env.domain.models import EventType, SimulationEvent, GateStatus
from neutral_atom_env.domain.operations import (OperationType, PlanRuntime, ResourceReservation)
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.hardware import get_backend
from neutral_atom_env.domain.aod import motion_target
from neutral_atom_env.motion.compiler import exact_validate
from .event_queue import EventQueue


PHYSICAL_EVENTS={EventType.PLAN_STARTED,EventType.OPERATION_STARTED,EventType.OPERATION_COMPLETED,EventType.PLAN_COMPLETED}


def reduce_physical(state,event,queue):
    backend=get_backend(state.hardware);extra={}
    if event.event_type==EventType.PLAN_STARTED:
        if len(state.event_queue.entries)!=1 or event.plan_id!=event.plan.id:
            raise ValidationError('INVALID_PLAN_EVENT','PLAN_STARTED must be the only queued event and match its plan')
        # Scheduling the start event is not a physical commit; restore its pre-enqueue view for exact validation.
        pre=replace(state,event_queue=EventQueue((),state.event_queue.next_sequence-1))
        exact_validate(event.plan,pre)
        plan=event.plan;gate=next(iter(plan.intent.gate_ids))
        runtime=PlanRuntime(plan,event.time_us)
        result=replace(state,dag=state.dag.transitioned(gate,GateStatus.RESERVED),active_plan=runtime,
            physical_metrics=replace(state.physical_metrics,episode_start_us=state.physical_metrics.episode_start_us if state.physical_metrics.episode_start_us is not None else event.time_us),
            reservations=tuple(ResourceReservation(r,plan.id) for r in plan.resources))
        queue=queue.push(SimulationEvent(event.time_us,EventType.OPERATION_STARTED,plan_id=plan.id,operation_id=plan.operations[0].id))
        return result,queue,{'reserved_resources':plan.resources}
    runtime=state.active_plan
    if not runtime or runtime.plan.id!=event.plan_id:
        raise ValidationError('NO_ACTIVE_PLAN','Event does not belong to active plan')
    plan=runtime.plan;gate=next(iter(plan.intent.gate_ids));metrics=state.physical_metrics
    if tuple(r.resource_id for r in state.reservations)!=plan.resources or any(r.plan_id!=plan.id for r in state.reservations):
        raise ValidationError('RESERVATION_LOST','Plan reservations are inconsistent')
    if event.event_type==EventType.PLAN_COMPLETED:
        if runtime.operation_index!=len(plan.operations) or runtime.operation_started_us is not None:
            raise ValidationError('PLAN_NOT_FINISHED','Operations are still pending')
        if tuple(sorted(state.placement.atom_to_holder.items()))!=plan.predicted_placement:
            raise ValidationError('END_STATE_MISMATCH','Final placement differs from validated prediction')
        extra={'plan_duration_us':event.time_us-runtime.started_us,'gate_id':gate}
        return replace(state,active_plan=None,reservations=(),physical_metrics=replace(metrics,
            cycle_makespan_us=event.time_us-runtime.started_us,
            completed_plan_count=metrics.completed_plan_count+1)),queue,extra|{'released_resources':plan.resources}
    if runtime.operation_index>=len(plan.operations):raise ValidationError('NO_OPERATION','Plan has no further operation')
    operation=plan.operations[runtime.operation_index]
    if event.operation_id!=operation.id:raise ValidationError('OPERATION_ORDER','Operation does not match plan cursor')
    kind=operation.operation_type
    target=motion_target(operation)
    transfer_bindings=operation.transfer_bindings or plan.bindings
    if event.event_type==EventType.OPERATION_STARTED:
        if runtime.operation_started_us is not None or event.time_us!=state.time_us:
            raise ValidationError('OPERATION_ORDER','Operation already started or event time is inconsistent')
        expected={OperationType.AOD_LOAD:state.hardware.load_duration_us,OperationType.AOD_OFFLOAD:state.hardware.offload_duration_us,
                  OperationType.ENTANGLING_PULSE:state.hardware.pulse_duration_us,
                  OperationType.AOD_PARK:state.hardware.offload_duration_us,OperationType.AOD_RECAPTURE:state.hardware.load_duration_us}
        if kind==OperationType.AOD_MOVE:
            backend.validate_move(state,target,transfer=operation.transfer_phase,bindings=transfer_bindings)
            duration=backend.move_duration(state.aod,target,state.hardware)
            result=replace(state,aod=replace(state.aod,is_moving=True))
            extra={'source_pose':state.aod.pose,'target_pose':operation.target_pose,'source_configuration':state.aod.configuration(),'target_configuration':backend.target_aod(state.aod,target).configuration(),'motion_profile':backend.motion_profile,'moving_atom_ids':tuple(sorted(state.placement.mobile_occupancy.values()))}
        else:
            duration=expected[kind];result=state
            if kind==OperationType.AOD_LOAD:backend.load(state,plan.bindings)
            elif kind==OperationType.AOD_OFFLOAD:backend.offload(state,plan.bindings)
            elif kind==OperationType.AOD_PARK:backend.park(state,operation.transfer_bindings)
            elif kind==OperationType.AOD_RECAPTURE:backend.recapture(state,operation.transfer_bindings)
            else:
                pairs=backend.validate_pulse(state,gate)
                result=replace(state,dag=state.dag.transitioned(gate,GateStatus.RUNNING))
                extra={'actual_pairs':pairs,'intended_pairs':(tuple(sorted(plan.requested_atom_ids)),)}
        if not isclose(duration,operation.duration_us,abs_tol=1e-9):
            raise ValidationError('INVALID_DURATION','Operation duration differs from hardware timing')
        result=replace(result,active_plan=replace(runtime,operation_started_us=event.time_us))
        queue=queue.push(SimulationEvent(event.time_us+duration,EventType.OPERATION_COMPLETED,plan_id=plan.id,operation_id=operation.id))
        return result,queue,extra|{'operation_type':kind.value,'label':operation.label,'duration_us':duration,'transfer_bindings':operation.transfer_bindings}
    if runtime.operation_started_us is None or not isclose(event.time_us,runtime.operation_started_us+operation.duration_us,abs_tol=1e-9):
        raise ValidationError('INVALID_COMPLETION_TIME','Operation completion time is inconsistent')
    if kind==OperationType.AOD_LOAD:
        result=backend.load(state,plan.bindings)
        metrics=replace(metrics,aod_load_count=metrics.aod_load_count+1,
            captured_atom_count_total=metrics.captured_atom_count_total+len(plan.captured_atom_ids),
            incidental_atom_transport_total=metrics.incidental_atom_transport_total+len(plan.incidental_atom_ids))
        extra={'captured_atom_ids':tuple(sorted(plan.captured_atom_ids)),'incidental_atom_ids':tuple(sorted(plan.incidental_atom_ids))}
    elif kind in (OperationType.AOD_PARK,OperationType.AOD_RECAPTURE):
        recapture=kind==OperationType.AOD_RECAPTURE
        result=backend.recapture(state,operation.transfer_bindings) if recapture else backend.park(state,operation.transfer_bindings)
        metrics=replace(metrics,aod_load_count=metrics.aod_load_count+int(recapture),
            aod_offload_count=metrics.aod_offload_count+int(not recapture),
            captured_atom_count_total=metrics.captured_atom_count_total+(len(operation.transfer_bindings) if recapture else 0),
            incidental_atom_transport_total=metrics.incidental_atom_transport_total+(sum(b.atom_id in plan.incidental_atom_ids for b in operation.transfer_bindings) if recapture else 0))
        extra={'transfer_bindings':operation.transfer_bindings,'transferred_atom_ids':tuple(b.atom_id for b in operation.transfer_bindings)}
    elif kind==OperationType.AOD_MOVE:
        d=backend.move_distance(state.aod,target)
        atom_d=backend.atom_distance(state,target)
        result=backend.move(state,target,transfer=operation.transfer_phase,bindings=transfer_bindings)
        metrics=replace(metrics,total_aod_distance_um=metrics.total_aod_distance_um+d,
            total_atom_distance_um=metrics.total_atom_distance_um+atom_d)
        extra={'source_pose':state.aod.pose,'target_pose':operation.target_pose,'source_configuration':state.aod.configuration(),'target_configuration':backend.target_aod(state.aod,target).configuration(),'motion_profile':backend.motion_profile,'distance_um':d}
    elif kind==OperationType.AOD_OFFLOAD:
        result=backend.offload(state,plan.bindings)
        metrics=replace(metrics,aod_offload_count=metrics.aod_offload_count+1)
    else:
        extra={'actual_pairs':backend.validate_pulse(state,gate)}
        result=replace(state,dag=state.dag.transitioned(gate,GateStatus.COMPLETED))
        metrics=replace(metrics,circuit_makespan_us=event.time_us,laser_busy_time_us=metrics.laser_busy_time_us+operation.duration_us)
    metrics=replace(metrics,aod_busy_time_us=metrics.aod_busy_time_us+operation.duration_us)
    index=runtime.operation_index+1
    result=replace(result,physical_metrics=metrics,active_plan=replace(runtime,operation_index=index,operation_started_us=None))
    if index==len(plan.operations):
        queue=queue.push(SimulationEvent(event.time_us,EventType.PLAN_COMPLETED,plan_id=plan.id))
    else:
        queue=queue.push(SimulationEvent(event.time_us,EventType.OPERATION_STARTED,plan_id=plan.id,operation_id=plan.operations[index].id))
    return result,queue,extra|{'operation_type':kind.value,'label':operation.label}
