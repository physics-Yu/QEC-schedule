"""Schedule validated transport and independent Raman branches into a program."""
from dataclasses import replace
from hashlib import sha256
from neutral_atom_env.domain.operations import TaskIntent, OperationInterval, OperationType as K
from neutral_atom_env.replay.serializer import canonical_json
from neutral_atom_env.hardware.dynamic_traps import trap_state
from neutral_atom_env.program.binding import exact_validate
from neutral_atom_env.program.task_validation import EFFECTS


def scheduled_program(base,state,rotations=()):
    """rotations are (gate_id, relative_start_us). Full replay audits overlap.

    Any gate effect in the base plan stays at its original relative time.
    Caller/policy selects windows; this function neither chooses gates nor routes.
    """
    exact_validate(base,state)
    operations=[];intervals=[];time=0.
    for op in base.operations:
        gate=op.gate_id or (next(iter(base.intent.gate_ids)) if op.operation_type in EFFECTS and not op.gate_ids else None)
        operations.append(replace(op,gate_id=gate,depends_on=(operations[-1].id,) if operations else (),task_phase=base.intent.phase))
        intervals.append(OperationInterval(op.id,time,time+op.duration_us,(),()))
        time+=op.duration_us
    from neutral_atom_env.domain.operations import Operation
    for gate,start in rotations:
        index=len(operations);opid=f'op{index:02d}'
        operations.append(Operation(opid,K.RAMAN_ROTATION,'Overlapping Raman',state.hardware.raman_duration_us,gate_id=gate,task_phase='effect'))
        intervals.append(OperationInterval(opid,start,start+state.hardware.raman_duration_us,(),()))
    effects=frozenset(g for o in operations if o.operation_type in EFFECTS for g in o.effect_gate_ids)
    intent=TaskIntent(base.intent.task_id+'/scheduled',base.intent.target,base.intent.atom_ids,
                      phase='program',allowed_atom_ids=base.intent.allowed_atom_ids,allowed_site_ids=base.intent.allowed_site_ids,
                      max_duration_us=base.intent.max_duration_us,gate_effects=effects)
    plan=replace(base,id='program_'+sha256((canonical_json(intent)+base.state_fingerprint).encode()).hexdigest()[:20],intent=intent,
                 execution_mode='scheduled',initial_time_us=state.time_us,initial_metrics=state.physical_metrics,
                 initial_dag=canonical_json(state.dag.nodes),operations=tuple(operations),operation_intervals=tuple(intervals),
                 initial_atoms=tuple(sorted(state.atoms.items())),initial_rng_state=state.rng_state,
                 initial_quantum_state=canonical_json(state.quantum_state.to_dict()) if state.quantum_state is not None else None,
                 initial_measurement_results=tuple(sorted(state.measurement_results.items())))
    from neutral_atom_env.simulation.operation_program import audit
    final,intervals,bindings,travel=audit(plan,state,metadata=False)
    requested=intent.atom_ids|frozenset(q for g in effects for q in state.dag.nodes[g].gate.qubit_ids)
    affected=frozenset(q for i in intervals for q in i.atom_ids)
    plan=replace(plan,operation_intervals=intervals,requested_atom_ids=requested,incidental_atom_ids=affected-requested,
                 bindings=bindings,resources=tuple(sorted({r for i in intervals for r in i.resources})),
                 estimated_duration_us=max(i.end_us for i in intervals),estimated_distance_um=travel,
                 predicted_placement=tuple(sorted(final.placement.atom_to_holder.items())),predicted_traps=trap_state(final))
    from neutral_atom_env.hardware.multi_aod import needs_device_origin
    if needs_device_origin(state):
        plan=replace(plan,initial_aods=tuple(sorted(state.aods.items())),predicted_aods=tuple(sorted(final.aods.items())))
    exact_validate(plan,state)
    return plan


def build_scheduled_program(state,intent,operations,intervals,*,planner_id='external-scheduled'):
    """Audit caller-selected concurrent operations on the complete global state.

    intervals supply relative start/end times. Resources and affected atoms are
    derived independently from actual holders at each operation start.
    """
    from neutral_atom_env.domain.operations import CompiledPlan
    from neutral_atom_env.program.binding import fingerprint
    from neutral_atom_env.simulation.operation_program import audit
    from neutral_atom_env.hardware.dynamic_traps import trap_state
    from neutral_atom_env.hardware.multi_aod import needs_device_origin
    operations=tuple(operations);intervals=tuple(intervals)
    intent=replace(intent,phase='program',effect_gate_id=None,gate_effects=intent.gate_ids)
    digest=fingerprint(state)
    requested=intent.atom_ids|frozenset(q for g in intent.gate_ids for q in state.dag.nodes[g].gate.qubit_ids)
    plan=CompiledPlan('program_'+sha256((intent.task_id+digest).encode()).hexdigest()[:20],state.version,digest,
        intent,(),requested,frozenset(),operations,(),max(i.end_us for i in intervals),0.,
        tuple(sorted(state.placement.atom_to_holder.items())),state.aod.configuration(),planner_id,
        tuple(sorted(state.placement.atom_to_holder.items())),trap_state(state),trap_state(state),intervals,
        canonical_json(state.dag.nodes),'scheduled',state.time_us,state.physical_metrics,
        tuple(sorted(state.atoms.items())),canonical_json(state.quantum_state.to_dict()) if state.quantum_state is not None else None,
        tuple(sorted(state.measurement_results.items())),state.rng_state,
        tuple(sorted(state.aods.items())) if needs_device_origin(state) else (),())
    final,derived,bindings,travel=audit(plan,state,metadata=False)
    affected=frozenset(q for i in derived for q in i.atom_ids)
    plan=replace(plan,operation_intervals=derived,bindings=bindings,resources=tuple(sorted({r for i in derived for r in i.resources})),
        incidental_atom_ids=affected-requested,estimated_distance_um=travel,
        predicted_placement=tuple(sorted(final.placement.atom_to_holder.items())),predicted_traps=trap_state(final),
        predicted_aods=tuple(sorted(final.aods.items())) if needs_device_origin(state) else ())
    exact_validate(plan,state)
    return plan
