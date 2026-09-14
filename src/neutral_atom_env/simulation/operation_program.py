"""Scheduled operations on one clock. Only Executor installs these pure results.

The platform has one AOD lane and independent per-qubit Raman resources.
Geometry is revalidated over each complete move; lit Raman targets remain stable.
"""
import json
from collections import OrderedDict
from dataclasses import replace
from math import isclose,isfinite
from neutral_atom_env.domain.models import EventType as E, SimulationEvent, GateStatus as G
from neutral_atom_env.domain.operations import OperationType as K, PlanRuntime, ResourceReservation, OperationInterval
from neutral_atom_env.hardware import get_backend
from neutral_atom_env.hardware.dynamic_traps import TRANSFERS, begin_transfer, finish_transfer, switch_traps, trap_state
from neutral_atom_env.hardware.raman import validate_rotation_batch, validate_rotation_batch_sweep
from neutral_atom_env.hardware.gate_contract import compatible_gate_types
from neutral_atom_env.domain.aod import motion_target
from neutral_atom_env.world import PlacementState
from neutral_atom_env.motion.validation import require
from neutral_atom_env.motion.program import operation_duration
from neutral_atom_env.motion.task_validation import operation_demand, origin_dag, validate_target, EFFECTS
from neutral_atom_env.replay.serializer import canonical_json
from .event_queue import EventQueue
from neutral_atom_env.replay.trace import _event_data
from .quantum_effects import complete_effects,condition_applies
from neutral_atom_env.hardware.readout import validate_readout


# Memoize independently reconstructed expectations, never live validation results.
# Only the latest prefix per environment/plan is retained (32 states maximum).
_runtime_prefixes = OrderedDict()


def _replay_key(plan, state):
    world = state.world
    return (plan, world.bounds, tuple(sorted(world.traps.items())), world.zones,
            world.grid_spacing_um, world.grid_origin, world.static_zone_types,
            state.hardware, tuple(sorted(state.atoms.items())), state.dag.circuit,
            state.aod.rows, state.aod.columns, state.aod.spacing_um)


def _expected_prefix(plan, state, timeline, count):
    key = _replay_key(plan, state)
    cached = _runtime_prefixes.get(key)
    if cached is None or cached[0] > count:
        work = origin(plan, state)
        work = replace(work, physical_metrics=replace(work.physical_metrics,
            episode_start_us=work.physical_metrics.episode_start_us
            if work.physical_metrics.episode_start_us is not None else plan.initial_time_us))
        cursor = 0
    else:
        cursor, work = cached
    for event in timeline[cursor:count]:
        if event.event_type == E.PLAN_COMPLETED:
            work = replace(work, active_plan=None, reservations=(), time_us=event.time_us,
                physical_metrics=replace(work.physical_metrics,
                    completed_plan_count=work.physical_metrics.completed_plan_count+1,
                    cycle_makespan_us=event.time_us-plan.initial_time_us))
        else:
            work, _ = transition(work, event)
    _runtime_prefixes[key] = (count, work)
    _runtime_prefixes.move_to_end(key)
    if len(_runtime_prefixes) > 32:
        _runtime_prefixes.popitem(last=False)
    return work


def origin(plan,state):
    require(plan.initial_time_us is not None and plan.initial_metrics is not None,'Missing program origin')
    require(plan.initial_atoms is not None and plan.initial_rng_state is not None,'Missing quantum/atom/RNG program origin')
    from neutral_atom_env.quantum.stabilizer import StabilizerState
    quantum=StabilizerState.from_dict(json.loads(plan.initial_quantum_state)) if plan.initial_quantum_state is not None else None
    return replace(state,placement=PlacementState(dict(plan.initial_placement)),
        aod=replace(state.aod.configured(plan.initial_aod_configuration),is_moving=False,
                    enabled_rows=plan.initial_traps.rows,enabled_columns=plan.initial_traps.columns),
        slm_enabled=dict(plan.initial_traps.slm),transfer=None,dag=origin_dag(plan,state),
        time_us=plan.initial_time_us,physical_metrics=plan.initial_metrics,
        active_plan=PlanRuntime(plan,plan.initial_time_us),reservations=(),event_queue=EventQueue(),
        atoms=dict(plan.initial_atoms),quantum_state=quantum,measurement_results=dict(plan.initial_measurement_results),rng_state=plan.initial_rng_state)


def schedule(plan):
    events=[]
    for interval in plan.operation_intervals:
        events.extend([(interval.start_us,1,interval.operation_id,E.OPERATION_STARTED),
                       (interval.end_us,0,interval.operation_id,E.OPERATION_COMPLETED)])
    # Completion commits precede starts at equal times, independent of insertion.
    return tuple(SimulationEvent(plan.initial_time_us+t,kind,plan_id=plan.id,operation_id=op)
                 for t,_,op,kind in sorted(events))


def demands(state,op):
    resources,atoms,sites=operation_demand(state,op,op.gate_id)
    return resources,atoms,sites


def rotation_metadata(state,op,time_us):
    gates=validate_rotation_batch(state,op.effect_gate_ids,time_us=time_us)
    if not op.gate_ids:
        return {'input_gate':gates[0],'u_parameters_rad':gates[0].u_parameters}
    applied={g.id:condition_applies(state,g) for g in gates}
    return {'input_gates':gates,'u_parameters_by_gate':{g.id:g.u_parameters for g in gates},
            'applied':any(applied.values()),'applied_by_gate':applied,
            'applied_gate_ids':tuple(g for g,yes in applied.items() if yes)}


def transition(state,event):
    """Validate and reduce one scheduled start/completion against latest state."""
    rt=state.active_plan;plan=rt.plan
    index=next((i for i,o in enumerate(plan.operations) if o.id==event.operation_id),None)
    require(index is not None,'Unknown program operation')
    op=plan.operations[index];interval=plan.operation_intervals[index]
    kind=op.operation_type;backend=get_backend(state.hardware);target=motion_target(op)
    effect_ids=op.effect_gate_ids
    running=dict(rt.running_operations);completed=set(rt.completed_operation_ids)
    extra={'task_id':plan.intent.task_id,'task_phase':op.task_phase or plan.intent.phase,'operation_ref':f'{plan.intent.task_id}/{op.id}',
           'effect_gate_id':op.gate_id,'gate_id':op.gate_id,'operation_type':kind.value,'label':op.label,
           'duration_us':op.duration_us,'transfer_bindings':op.transfer_bindings,'resources':interval.resources}
    if op.gate_ids:extra.update(gate_ids=op.gate_ids,effect_gate_ids=op.gate_ids)
    if event.event_type==E.OPERATION_STARTED:
        require(event.time_us==plan.initial_time_us+interval.start_us and op.id not in running and op.id not in completed,'Invalid program start')
        require(set(op.depends_on)<=completed,'Unfinished operation dependency')
        require(not set(interval.resources)&{r.resource_id for r in state.reservations},'Resource interval conflict')
        resources,atoms,sites=demands(state,op)
        require((resources,atoms)==(interval.resources,interval.atom_ids),'Live resource demand mismatch')
        duration=operation_duration(state,kind,target)
        require(isclose(duration,op.duration_us,rel_tol=0,abs_tol=1e-9),'Program hardware timing mismatch')
        work=state
        if kind==K.AOD_MOVE:
            backend.validate_move(state,target,transfer=op.transfer_phase,bindings=op.transfer_bindings)
            for active,active_interval in zip(plan.operations,plan.operation_intervals):
                if active.id in running and active.operation_type==K.RAMAN_ROTATION:
                    overlap_end=min(event.time_us+op.duration_us,plan.initial_time_us+active_interval.end_us)
                    validate_rotation_batch_sweep(state,active.effect_gate_ids,target,0.,(overlap_end-event.time_us)/op.duration_us)
            work=replace(state,aod=replace(state.aod,is_moving=True))
            extra.update(source_configuration=state.aod.configuration(),target_configuration=backend.target_aod(state.aod,target).configuration(),
                         motion_profile=backend.motion_profile,moving_atom_ids=tuple(sorted(state.placement.mobile_occupancy.values())))
        elif kind in TRANSFERS:
            work=begin_transfer(backend,state,op.transfer_bindings,kind)
            extra.update(transfer=work.transfer,supports_before=trap_state(state),supports_overlap=trap_state(work))
        elif kind==K.TRAP_SWITCH:
            switch_traps(state,op.switch_state)
            extra.update(supports_before=trap_state(state),supports_target=op.switch_state)
        else:
            require(kind in EFFECTS and bool(effect_ids) and set(effect_ids)<=plan.intent.gate_ids,'Unauthorized program effect')
            gate_type=state.dag.nodes[effect_ids[0]].gate.gate_type
            for active in plan.operations:
                if active.id in running and active.operation_type in EFFECTS:
                    require(compatible_gate_types(gate_type,state.dag.nodes[active.effect_gate_ids[0]].gate.gate_type),
                            'Different gate types cannot execute concurrently')
            require(all(state.dag.nodes[g].status==G.READY for g in effect_ids),'Program gate is not READY')
            extra['applied']=any(condition_applies(state,state.dag.nodes[g].gate) for g in effect_ids)
            if kind==K.RAMAN_ROTATION:
                extra.update(rotation_metadata(state,op,event.time_us))
                for active in plan.operations:
                    if active.id in running and active.operation_type==K.AOD_MOVE:
                        begin=running[active.id];overlap_end=min(event.time_us+op.duration_us,begin+active.duration_us)
                        validate_rotation_batch_sweep(state,effect_ids,motion_target(active),
                            (event.time_us-begin)/active.duration_us,(overlap_end-begin)/active.duration_us)
            elif kind in {K.MEASUREMENT,K.RESET}:validate_readout(state,effect_ids,kind)
            else:extra.update(actual_pairs=backend.validate_pulse_batch(state,effect_ids))
            dag=state.dag
            for gid in effect_ids:dag=dag.transitioned(gid,G.RESERVED).transitioned(gid,G.RUNNING)
            work=replace(state,dag=dag)
        running[op.id]=event.time_us
    else:
        require(event.event_type==E.OPERATION_COMPLETED and op.id in running,'Completion without running operation')
        require(event.time_us==plan.initial_time_us+interval.end_us and isclose(event.time_us-running[op.id],op.duration_us,abs_tol=1e-8),'Invalid program completion')
        metrics=state.physical_metrics;work=state
        if kind in TRANSFERS:
            work=finish_transfer(backend,state,op.transfer_bindings,kind)
            loading=kind in {K.AOD_LOAD,K.AOD_RECAPTURE}
            metrics=replace(metrics,aod_load_count=metrics.aod_load_count+int(loading),aod_offload_count=metrics.aod_offload_count+int(not loading),
                captured_atom_count_total=metrics.captured_atom_count_total+(len(op.transfer_bindings) if loading else 0),
                incidental_atom_transport_total=metrics.incidental_atom_transport_total+(sum(b.atom_id in plan.incidental_atom_ids for b in op.transfer_bindings) if loading else 0))
        elif kind==K.AOD_MOVE:
            d=backend.move_distance(state.aod,target);atom_d=backend.atom_distance(state,target)
            work=backend.move(state,target,transfer=op.transfer_phase,bindings=op.transfer_bindings)
            metrics=replace(metrics,total_aod_distance_um=metrics.total_aod_distance_um+d,total_atom_distance_um=metrics.total_atom_distance_um+atom_d)
            extra.update(distance_um=d)
        elif kind==K.TRAP_SWITCH:work=switch_traps(state,op.switch_state)
        else:
            require(all(state.dag.nodes[g].status==G.RUNNING for g in effect_ids),'Effect already completed or not started')
            if kind==K.RAMAN_ROTATION:
                extra.update(rotation_metadata(state,op,event.time_us))
                # Device busy time is the union, not the sum of parallel atom pulses.
                previous=[(i.start_us,i.end_us) for o,i in zip(plan.operations,plan.operation_intervals)
                          if o.id in completed and o.operation_type==K.RAMAN_ROTATION
                          and any(condition_applies(state,state.dag.nodes[g].gate) for g in o.effect_gate_ids)]
                def duration_union(values):
                    end=-1.;total=0.
                    for a,b in sorted(values):
                        total+=max(0.,b-max(a,end));end=max(end,b)
                    return total
                extra_busy=(duration_union(previous+[(interval.start_us,interval.end_us)])-duration_union(previous)
                            if any(condition_applies(state,state.dag.nodes[g].gate) for g in effect_ids) else 0.)
                metrics=replace(metrics,raman_busy_time_us=metrics.raman_busy_time_us+extra_busy)
            elif kind in {K.MEASUREMENT,K.RESET}:
                validate_readout(state,effect_ids,kind)
                field='measurement_busy_time_us' if kind==K.MEASUREMENT else 'reset_busy_time_us'
                metrics=replace(metrics,**{field:getattr(metrics,field)+op.duration_us})
            else:
                extra.update(actual_pairs=backend.validate_pulse_batch(state,effect_ids))
                metrics=replace(metrics,laser_busy_time_us=metrics.laser_busy_time_us+op.duration_us)
            metrics=replace(metrics,circuit_makespan_us=event.time_us)
            work,quantum_extra=complete_effects(state,op)
            extra.update(quantum_extra)
            dag=work.dag
            for gid in effect_ids:dag=dag.transitioned(gid,G.COMPLETED)
            work=replace(work,dag=dag)
            extra['effect_completed']=True
        # Preserve the baseline AOD service metric: Raman (singular or batch)
        # is excluded even when its interval reserves AOD_0 against motion.
        if kind!=K.RAMAN_ROTATION:metrics=replace(metrics,aod_busy_time_us=metrics.aod_busy_time_us+op.duration_us)
        work=replace(work,physical_metrics=metrics)
        del running[op.id];completed.add(op.id)
    reservations=tuple(ResourceReservation(r,plan.id) for i in plan.operation_intervals if i.operation_id in running for r in i.resources)
    active_indices=[i for i,o in enumerate(plan.operations) if o.id in running]
    # Legacy observer cursor points to the transport lane; running_operations is authoritative.
    cursor=next((i for i in active_indices if plan.operations[i].operation_type!=K.RAMAN_ROTATION),active_indices[0] if active_indices else len(plan.operations))
    runtime=replace(rt,operation_index=cursor,operation_started_us=running.get(plan.operations[cursor].id) if cursor<len(plan.operations) else None,
                    running_operations=tuple(sorted(running.items())),completed_operation_ids=tuple(sorted(completed)))
    return replace(work,time_us=event.time_us,active_plan=runtime,reservations=reservations),extra


def audit(plan,state,*,metadata=True):
    require(plan.intent.phase=='program' and plan.initial_placement is not None,'Scheduled program requires task origin')
    require(plan.intent.atom_ids<=state.atoms.keys() and all(q in state.atoms for q,_ in plan.intent.target.holders),'Unknown program atom')
    require(plan.intent.gate_ids<=state.dag.nodes.keys(),'Unknown program effect')
    require(plan.intent.allowed_atom_ids is None or plan.intent.allowed_atom_ids<=state.atoms.keys(),'Unknown allowed atom')
    require(plan.intent.allowed_site_ids is None or plan.intent.allowed_site_ids<=state.world.traps.keys(),'Unknown allowed site')
    require(len(plan.operations)==len(plan.operation_intervals)>0,'Missing operation intervals')
    ids=[o.id for o in plan.operations]
    require(ids==[f'op{i:02d}' for i in range(len(ids))],'Invalid program operation IDs')
    intervals=plan.operation_intervals
    for op,i in zip(plan.operations,intervals):
        require(i.operation_id==op.id and all(isfinite(t) and t>=0 for t in (i.start_us,i.end_us)) and i.end_us>i.start_us,'Invalid scheduled interval')
        require(isclose(i.end_us-i.start_us,op.duration_us,abs_tol=1e-8),'Scheduled duration mismatch')
        require(set(op.depends_on)<=set(ids)-{op.id} and len(set(op.depends_on))==len(op.depends_on),'Invalid program dependencies')
        require(bool(op.effect_gate_ids) and set(op.effect_gate_ids)<=plan.intent.gate_ids
                if op.operation_type in EFFECTS else not op.effect_gate_ids,'Invalid gate effect provenance')
        require((op.operation_type==K.TRAP_SWITCH)==(op.switch_state is not None),'Invalid switch fields')
        require(op.task_phase in {None,'transport','prepare','effect','cleanup','program'},'Invalid operation phase')
        if op.operation_type==K.AOD_MOVE:
            require((op.target_pose is None)!=(op.target_configuration is None) and op.transfer_phase in {None,'depart','approach'},'Invalid move fields')
        else:
            require(motion_target(op) is None and op.transfer_phase is None,'Motion fields on non-move')
            require(bool(op.transfer_bindings) if op.operation_type in TRANSFERS else not op.transfer_bindings,'Invalid transfer fields')
    effects=[g for o in plan.operations if o.operation_type in EFFECTS for g in o.effect_gate_ids]
    require(len(effects)==len(set(effects)) and set(effects)==plan.intent.gate_ids,'Missing or duplicate gate effects')
    # Keep the AOD sequence/transfer adjacency audited by the existing program validator.
    work=origin(plan,state);derived=list(intervals);timeline=schedule(plan)
    first_loads={};travel=0.
    for event in timeline:
        j=ids.index(event.operation_id);op=plan.operations[j]
        if event.event_type==E.OPERATION_STARTED:
            resources,atoms,sites=demands(work,op)
            if not metadata:
                derived[j]=replace(derived[j],resources=resources,atom_ids=atoms)
                plan=replace(plan,operation_intervals=tuple(derived));work=replace(work,active_plan=replace(work.active_plan,plan=plan))
            require(plan.intent.allowed_atom_ids is None or set(atoms)<=plan.intent.allowed_atom_ids,'Forbidden program atom')
            require(plan.intent.allowed_site_ids is None or sites<=plan.intent.allowed_site_ids,'Forbidden program site')
            if op.operation_type in {K.AOD_LOAD,K.AOD_RECAPTURE}:
                for b in op.transfer_bindings:first_loads.setdefault(b.atom_id,b)
            if op.operation_type==K.AOD_MOVE:
                travel+=get_backend(work.hardware).move_distance(work.aod,motion_target(op))
                # Exemptions need adjacent same-lane transfers, not arbitrary labels.
                lane=[o for o in plan.operations if o.operation_type!=K.RAMAN_ROTATION];k=lane.index(op)
                if op.transfer_phase:
                    neighbor=lane[k-1] if op.transfer_phase=='depart' and k else lane[k+1] if op.transfer_phase=='approach' and k+1<len(lane) else None
                    kinds={K.AOD_LOAD,K.AOD_RECAPTURE} if op.transfer_phase=='depart' else {K.AOD_OFFLOAD,K.AOD_PARK}
                    require(neighbor is not None and neighbor.operation_type in kinds and neighbor.transfer_bindings==op.transfer_bindings,'Invalid transfer exemption adjacency')
                else:require(not op.transfer_bindings,'Unscoped program transfer exemption')
        work,_=transition(work,event)
    validate_target(plan.intent.target,work)
    require(all(work.dag.nodes[g].status==G.COMPLETED for g in plan.intent.gate_ids),'Unfinished program gate')
    return work,tuple(derived),tuple(first_loads[q] for q in sorted(first_loads)),travel


def validate_program(plan,state,restoring=False):
    from neutral_atom_env.motion.compiler import fingerprint
    if not restoring:
        require(not(state.active_plan or state.event_queue or state.reservations or state.transfer),'Program needs an idle submit boundary')
        for record in state.trace.records:
            event=_event_data(record)
            if event['event_type']=='plan_started':
                require(event['plan']['intent'].get('task_id')!=plan.intent.task_id,'Task ID already executed')
        if plan.state_version!=state.version or plan.state_fingerprint!=fingerprint(state):
            from neutral_atom_env.domain.errors import ValidationError
            raise ValidationError('OUTDATED_STATE','Scheduled program origin changed')
        require(plan.initial_time_us==state.time_us and plan.initial_metrics==state.physical_metrics,'Program origin time/metrics mismatch')
        require(plan.initial_atoms==tuple(sorted(state.atoms.items())) and plan.initial_rng_state==state.rng_state
                and plan.initial_measurement_results==tuple(sorted(state.measurement_results.items()))
                and plan.initial_quantum_state==(canonical_json(state.quantum_state.to_dict()) if state.quantum_state is not None else None),
                'Program quantum/atom/RNG origin mismatch')
        require(plan.initial_placement==tuple(sorted(state.placement.atom_to_holder.items())) and plan.initial_traps==trap_state(state)
                and plan.initial_aod_configuration==state.aod.configuration() and plan.initial_dag==canonical_json(state.dag.nodes),'Program origin mismatch')
    final,intervals,bindings,travel=audit(plan,state)
    require(plan.bindings==bindings,'Program capture metadata mismatch')
    affected=frozenset(q for i in intervals for q in i.atom_ids)
    requested=plan.intent.atom_ids|frozenset(q for g in plan.intent.gate_ids for q in state.dag.nodes[g].gate.qubit_ids)
    require(plan.requested_atom_ids==requested and plan.incidental_atom_ids==affected-requested,'Program atom metadata mismatch')
    require(plan.resources==tuple(sorted({r for i in intervals for r in i.resources})),'Program resources mismatch')
    require(plan.predicted_placement==tuple(sorted(final.placement.atom_to_holder.items())) and plan.predicted_traps==trap_state(final),'Program terminal prediction mismatch')
    require(isclose(plan.estimated_distance_um,travel,abs_tol=1e-8) and isclose(plan.estimated_duration_us,max(i.end_us for i in intervals),abs_tol=1e-8),'Program cost mismatch')
    require(plan.intent.max_duration_us is None or plan.estimated_duration_us<=plan.intent.max_duration_us,'Program budget exhausted')


def reduce_program(state,event,queue):
    from .physical_executor import task_metadata
    if event.event_type==E.PLAN_STARTED:
        plan=event.plan
        validate_program(plan,replace(state,event_queue=EventQueue((),state.event_queue.next_sequence-1)))
        work=replace(state,active_plan=PlanRuntime(plan,event.time_us),physical_metrics=replace(state.physical_metrics,
            episode_start_us=state.physical_metrics.episode_start_us if state.physical_metrics.episode_start_us is not None else event.time_us))
        for upcoming in schedule(plan):queue=queue.push(upcoming)
        queue=queue.push(SimulationEvent(event.time_us+plan.estimated_duration_us,E.PLAN_COMPLETED,plan_id=plan.id))
        return work,queue,task_metadata(plan)
    plan=state.active_plan.plan
    if event.event_type==E.PLAN_COMPLETED:
        require(len(state.active_plan.completed_operation_ids)==len(plan.operations) and not state.active_plan.running_operations,'Unfinished scheduled program')
        validate_target(plan.intent.target,state)
        metrics=replace(state.physical_metrics,completed_plan_count=state.physical_metrics.completed_plan_count+1,
                        cycle_makespan_us=event.time_us-state.active_plan.started_us)
        return replace(state,active_plan=None,reservations=(),physical_metrics=metrics),queue,task_metadata(plan)|{'plan_duration_us':plan.estimated_duration_us}
    work,extra=transition(state,event)
    return work,queue,extra


def validate_program_runtime(state,plan):
    """Independent reconstruction of all in-flight operations and the pending suffix."""
    physical=[_event_data(r) for r in state.trace.records]
    start=next((i for i in range(len(physical)-1,-1,-1) if physical[i]['event_type']=='plan_started'),None)
    require(start is not None,'Missing program start trace')
    from neutral_atom_env.replay.operation_codec import event_from_dict
    first=event_from_dict(physical[start]);require(first.plan==plan and first.time_us==plan.initial_time_us,'Program trace origin mismatch')
    require(first.plan.state_version==start,'Program version mismatch')
    timeline=schedule(plan)+(SimulationEvent(plan.initial_time_us+plan.estimated_duration_us,E.PLAN_COMPLETED,plan_id=plan.id),)
    suffix=physical[start+1:]
    actual=[event_from_dict(e) for e in suffix if e['event_type'].startswith(('plan_','operation_'))]
    require(tuple(event_from_dict(e) for e in suffix[:len(actual)])==tuple(actual),'Nonphysical event interrupted program')
    require(tuple(actual)==timeline[:len(actual)],'Program event sequence mismatch')
    work=_expected_prefix(plan,state,timeline,len(actual))
    if work.active_plan is None:
        require(all(e['event_type'] in {'wait_completed','rng_draw'} for e in suffix[len(actual):]),'Unexpected event after program')
        import random
        rng=random.Random();rng.setstate(work.rng_state)
        for raw in state.trace.records[start+1+len(actual):]:
            record=json.loads(raw)
            if record['event']['event_type']=='rng_draw':
                require(record.get('random_value')==rng.random(),'RNG trace outcome differs from independent replay')
        work=replace(work,rng_state=rng.getstate())
        if suffix:work=replace(work,time_us=suffix[-1]['time_us'])
    else:require(len(suffix)==len(actual),'Nonphysical event during active program')
    for name in ('placement','aod','slm_enabled','transfer','active_plan','reservations','physical_metrics','time_us',
                 'atoms','quantum_state','measurement_results','rng_state'):
        require(getattr(state,name)==getattr(work,name),'Program runtime mismatch: '+name)
    for record in state.trace.records[start+1:start+1+len(actual)]:
        entry=json.loads(record);event=entry['event']
        if event['event_type']!='operation_completed':continue
        operation=next(o for o in plan.operations if o.id==event['operation_id'])
        if operation.operation_type==K.MEASUREMENT:
            require(entry.get('measurement_results')=={g:work.measurement_results[g] for g in operation.effect_gate_ids},
                    'Measurement trace outcome differs from independently projected state')
        if operation.operation_type in EFFECTS:
            require(entry.get('applied')==any(condition_applies(work,work.dag.nodes[g].gate) for g in operation.effect_gate_ids),
                    'Conditional effect trace disagrees with measurement outcomes')
            if operation.operation_type==K.RAMAN_ROTATION and operation.gate_ids:
                applied={g:condition_applies(work,work.dag.nodes[g].gate) for g in operation.effect_gate_ids}
                require(entry.get('applied_by_gate')==applied and
                        entry.get('applied_gate_ids')==[g for g,yes in applied.items() if yes],
                        'Raman batch applied targets disagree with measurement outcomes')
    require(state.dag.nodes==work.dag.nodes,'Program DAG mismatch')
    pending=tuple(e for _,_,e in state.event_queue.entries)
    require(pending==timeline[len(actual):],'Program pending timeline mismatch')
