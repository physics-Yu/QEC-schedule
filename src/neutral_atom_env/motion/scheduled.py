"""Schedule validated transport and independent Raman branches into a program."""
from dataclasses import replace
from hashlib import sha256
from neutral_atom_env.domain.operations import TaskIntent, OperationInterval, OperationType as K
from neutral_atom_env.replay.serializer import canonical_json
from neutral_atom_env.hardware.dynamic_traps import trap_state
from .compiler import exact_validate
from .task_validation import EFFECTS


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
    exact_validate(plan,state)
    return plan
