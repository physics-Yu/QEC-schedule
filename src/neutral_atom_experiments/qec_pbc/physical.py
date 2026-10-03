"""Execute and audit an upstream memory circuit through the physical environment.

Evidence contains accepted plans, committed trace, real operation timing and
independent replay. The quantum model is ideal; this is not a noise/FT claim.
"""
from collections import Counter
from dataclasses import asdict
import json
import hashlib
from pathlib import Path
import platform
from time import perf_counter

from neutral_atom_env import NeutralAtomEnv
from neutral_atom_env.domain.models import GateStatus, ZoneType
from neutral_atom_env.program.task_validation import validate_target
from neutral_atom_env.replay.serializer import canonical_json
from neutral_atom_env.visualization import VisualRecorder
from neutral_atom_strategies.scheduling.m3 import initial_terminal
from neutral_atom_strategies.scheduling.qec import run_qec
from neutral_atom_strategies.motion.single_trap import in_zone

from .surface import decode_ideal_memory, logical_product, stabilizers
from .pauli import PauliProduct


def fresh_output(path):
    """Never overwrite an earlier successful or failed attempt."""
    requested = Path(path)
    output, attempt = requested, 2
    while output.exists():
        output = requested.with_name(requested.name + f'-attempt{attempt}')
        attempt += 1
    output.mkdir(parents=True, exist_ok=False)
    return output


def sparse_memory_destinations(inputs):
    """Single A patch on existing 20um EZ sites; unused atoms stay in SZ.

    This is a placement policy, not a hardware or code geometry definition.
    Moving each atom uses real AOD load/route/offload operations.
    """
    roles = inputs.compiled.program.roles
    if {r.id for r in roles} != {f'A.d{i}' for i in range(9)} | {
            f'A.{kind}{i}' for kind in ('X', 'Z') for i in range(4)}:
        raise ValueError('Sparse memory layout currently requires canonical A patch roles')
    state = inputs.create_environment().state
    sites = {(t.position.x_um, t.position.y_um): t.id for t in state.world.traps.values()
             if in_zone(state, t.position, ZoneType.ENTANGLEMENT)}
    # These are targets inside the existing EZ grid, not new traps.
    coordinates = {f'A.d{i}': (20 * (i % 3), -100 + 20 * (i // 3)) for i in range(9)}
    checks = ((5, 5), (15, 15), (15, -5), (5, 25),
              (15, 5), (5, 15), (-5, 5), (25, 15))
    for j, (x, y) in enumerate(checks):
        coordinates[f'A.{"X" if j < 4 else "Z"}{j % 4}'] = (2*x, -100+2*y)
    bindings = dict(inputs.compiled.bindings)
    return {bindings[role]: sites[point] for role, point in coordinates.items()}


def operation_schedule(plans, trace_rows):
    """Derive absolute physical intervals and validate against committed trace."""
    events = {}
    for row in trace_rows:
        event = row['event']
        if event['event_type'] in ('operation_started', 'operation_completed'):
            key = (event['plan_id'], event['operation_id'], event['event_type'])
            if key in events:
                raise ValueError(f'Duplicate committed operation boundary: {key}')
            events[key] = event['time_us']
    rows, expected = [], set()
    resources = {}
    gates = {}
    for plan in plans:
        operations = {op.id: op for op in plan.operations}
        for interval in plan.operation_intervals:
            op = operations[interval.operation_id]
            start = plan.initial_time_us + interval.start_us
            end = plan.initial_time_us + interval.end_us
            for kind, at in (('operation_started', start), ('operation_completed', end)):
                key = (plan.id, op.id, kind)
                expected.add(key)
                if key not in events or abs(events[key] - at) > 1e-7:
                    raise ValueError(f'Plan/trace operation boundary mismatch: {key}')
            for resource in interval.resources:
                resources.setdefault(resource, []).append((start, end))
            ids = op.effect_gate_ids
            for gid in ids:
                if gid in gates:
                    raise ValueError(f'Multiple physical intervals for gate {gid}')
                gates[gid] = (start, end)
            rows.append({'plan_id': plan.id, 'operation_id': op.id,
                         'kind': op.operation_type.value, 'label': op.label,
                         'start_us': start, 'end_us': end, 'duration_us': end-start,
                         'gate_ids': ids, 'depends_on': op.depends_on,
                         'atom_ids': interval.atom_ids, 'resources': interval.resources})
    if set(events) != expected:
        raise ValueError('Committed operations do not exactly match accepted plans')
    for resource, intervals in resources.items():
        intervals.sort()
        if any(a[1] > b[0] + 1e-7 for a, b in zip(intervals, intervals[1:])):
            raise ValueError(f'Overlapping physical resource: {resource}')
    return rows, gates


def execute_memory(inputs, output, *, strategy='sparse', wall_budget_s=900,
                   max_decisions=2048, progress=None):
    """Run a complete memory experiment, preserving all evidence on failure."""
    program = inputs.compiled.program
    contract = program.memory_contract
    if contract is None:
        raise ValueError('Physical memory runner requires explicit memory contract')
    if strategy not in ('sparse', 'dense'):
        raise ValueError('Unknown memory placement strategy')
    output = fresh_output(output)
    base = inputs.create_environment()
    plans = []

    class RecordingEnvironment(NeutralAtomEnv):
        def submit(self, plan):
            result = super().submit(plan)
            plans.append(plan)
            return result

    env = RecordingEnvironment(base.state)
    initial = env.snapshot()
    initial_quantum = env.state.quantum_state
    terminal = initial_terminal(env.state)
    recorder = VisualRecorder(env.state)
    binding = dict(inputs.compiled.bindings)
    gates = inputs.circuit.gates
    stages, result, error, audit = [], None, None, {}
    started, last_progress = perf_counter(), 0.
    exits = dict(inputs.compiled.exits)
    closing_exit = set(exits[f'{contract.patch}.r{contract.closing_round}.Z3'])
    destinations = sparse_memory_destinations(inputs) if strategy == 'sparse' else None
    for filename, data in (('compiled.json', inputs.compiled.to_dict()),
                           ('physical_circuit.json', {'gates': [asdict(g) for g in gates]}),
                           ('platform.json', inputs.platform),
                           ('working_destinations.json', destinations)):
        (output / filename).write_text(canonical_json(data), encoding='utf-8')
    (output / 'initial.json').write_text(initial, encoding='utf-8')
    source_root = Path(__file__).resolve().parents[2]
    fingerprints = {str(path.relative_to(source_root)): hashlib.sha256(path.read_bytes()).hexdigest()
                    for package in ('neutral_atom_env', 'neutral_atom_strategies', 'neutral_atom_experiments/qec_pbc')
                    for path in sorted((source_root / package).rglob('*.py'))}
    (output / 'run_metadata.json').write_text(canonical_json({
        'python': platform.python_version(), 'source_sha256': fingerprints,
        'compiled_sha256': hashlib.sha256(canonical_json(inputs.compiled.to_dict()).encode()).hexdigest(),
        'platform_sha256': hashlib.sha256(canonical_json(inputs.platform).encode()).hexdigest(),
        'search': {'max_decisions': max_decisions, 'candidate_budget': 256, 'route_expansions': 50000},
        'wall_budget_s': wall_budget_s}), encoding='utf-8')

    def observe(state, event):
        nonlocal last_progress
        recorder.observe(state, event)
        # At gadget exit, every ancilla has already been measured and reset.
        if not stages and all(state.dag.nodes[g].status == GateStatus.COMPLETED for g in closing_exit):
            products = stabilizers(contract.patch) + (logical_product(
                PauliProduct(((contract.patch, contract.basis),))),)
            expectations = [p.sign * state.quantum_state.expectation(
                {binding[r]: basis for r, basis in p.factors}) for p in products]
            stages.append({'stage': 'closing_round_before_destructive_readout',
                           'time_us': state.time_us, 'expectations': expectations,
                           'codespace_and_logical_verified': expectations == [1]*9})
        elapsed = perf_counter() - started
        if event.event_type.value == 'plan_completed' and (elapsed-last_progress >= 10 or state.dag.completed):
            item = {'plans': len(plans), 'completed_gates': state.metrics()['completed_gate_count'],
                    'total_gates': len(gates), 'simulation_time_us': state.time_us,
                    'wall_seconds': elapsed}
            (output / 'progress.json').write_text(canonical_json(item), encoding='utf-8')
            if progress:
                progress(item)
            last_progress = elapsed
        if elapsed > wall_budget_s:
            raise TimeoutError(f'Physical execution exceeded {wall_budget_s}s wall budget')

    try:
        runner = run_qec
        kwargs = {}
        if strategy == 'sparse':
            from neutral_atom_strategies.scheduling.qec_sparse import run_qec_sparse
            runner = run_qec_sparse
            kwargs['working_destinations'] = destinations
        result = runner(env, terminal=terminal, on_event=observe, max_decisions=max_decisions,
                        candidate_budget=256, route_expansions=50000, **kwargs)
        if result.status != 'completed':
            raise AssertionError(f'Physical execution {result.status}: {result.diagnostics}')
        validate_target(terminal, env.state)
        trace = [json.loads(row) for row in env.state.trace.records]
        counts = Counter(g for row in trace if row.get('effect_completed') for g in
            (row.get('effect_gate_ids') or ([row['effect_gate_id']] if row.get('effect_gate_id') else [])))
        reset_bits = {g: bit for row in trace for g, bit in row.get('reset_projection_results', {}).items()}
        from .verification import verify_native_quantum
        reference = verify_native_quantum(inputs.circuit, initial_quantum,
            env.state.quantum_state, env.state.measurement_results, reset_bits)
        semantic = inputs.compiled.semantic_results(env.state.measurement_results)
        outputs = inputs.compiled.classical_outputs(env.state.measurement_results)
        schedule, gate_times = operation_schedule(plans, trace)
        dependencies_ok = all(g.id in gate_times and all(
            gate_times[parent][1] <= gate_times[g.id][0] + 1e-7 for parent in g.depends_on) for g in gates)
        actual_applied = [g for row in trace if row.get('effect_completed') for g in row.get('applied_gate_ids', ())]
        data = [binding[r.id] for r in program.roles if r.kind == 'data']
        ancillas = [binding[r.id] for r in program.roles if r.kind == 'syndrome_ancilla']
        final_bindings = {m.result_id: m.raw_gate_id for m in inputs.compiled.measurements}
        data_matches = all(env.state.quantum_state.expectation({binding[f'{contract.patch}.d{i}']: 'Z'}) ==
                           (-1)**env.state.measurement_results[final_bindings[f'{contract.patch}.final.m{i}']]
                           for i in range(9))
        spectators = set(env.state.atoms) - set(binding.values())
        audit = {'dag_complete': env.state.dag.completed, 'terminal_verified': True,
                 'event_queue_empty': not env.pending, 'effects_exactly_once': counts == Counter(g.id for g in gates),
                 'dependency_timing_verified': dependencies_ok, 'operation_timing_and_resources_verified': True,
                 'quantum_reference': reference,
                 'applied_effects_match_reference': Counter(actual_applied) == Counter(reference['applied_gate_ids']),
                 'closing_codespace_verified': bool(stages) and stages[0]['codespace_and_logical_verified'],
                 'data_measured': all(env.state.atoms[q].measured for q in data),
                 'final_data_matches_readout': data_matches,
                 'ancillas_reset_zero': all(not env.state.atoms[q].measured and
                     env.state.quantum_state.expectation({q:'Z'}) == 1 for q in ancillas),
                 'spectators_unchanged': all(not env.state.atoms[q].measured and
                     env.state.quantum_state.expectation({q:'Z'}) == 1 for q in spectators),
                 'measurement_sidecar_complete': len(semantic) == 8*(contract.closing_round+1)+9,
                 'detector_sidecar_complete': len(outputs['detectors']) == 8*contract.closing_round+8,
                 'detectors_zero': all(v == 0 for v in outputs['detectors'].values()),
                 'decoded_logical_zero': decode_ideal_memory(program, semantic) == 0,
                 'semantic_results': semantic, 'classical_outputs': outputs,
                 'raw_measurements': dict(env.state.measurement_results), 'reset_projection_bits': reset_bits}
        checks = [v for key, v in audit.items() if isinstance(v, bool)] + [reference['reference_state_equal']]
        if not all(checks):
            raise AssertionError('Physical memory audit failed: ' + str({k:v for k,v in audit.items() if v is False}))
        (output / 'schedule.json').write_text(canonical_json(schedule), encoding='utf-8')
        gate_rows = [{**asdict(g), 'start_us': gate_times[g.id][0], 'end_us': gate_times[g.id][1],
                      'applied': g.id in reference['applied_gate_ids']} for g in gates]
        (output / 'gate_schedule.json').write_text(canonical_json(gate_rows), encoding='utf-8')
    except Exception as exc:
        error = {'type': type(exc).__name__, 'message': str(exc)}

    # This replay reuses actual plans against an independently restored world.
    try:
        replay = NeutralAtomEnv.restore(initial)
        for plan in plans:
            replay.submit(plan)
            replay.run()
        audit['independent_plan_replay_equal'] = replay.snapshot() == env.snapshot()
        if not audit['independent_plan_replay_equal']:
            raise AssertionError('Independent physical plan replay differs')
    except Exception as exc:
        audit['independent_plan_replay_equal'] = False
        audit['replay_error'] = {'type': type(exc).__name__, 'message': str(exc)}
        if error is None:
            error = audit['replay_error']
    evidence = {'status': 'failed' if error else 'completed', 'error': error,
                'output_directory': str(output.resolve()), 'seed': inputs.seed, 'strategy': strategy,
                'basis': contract.basis, 'storage_rounds': contract.closing_round,
                'scope': 'Complete ideal d3 memory, physical Executor, unchanged platform constraints; no circuit-noise FT claim',
                'native_gate_count': len(gates), 'gate_counts': dict(Counter(g.gate_type for g in gates)),
                'physical_atom_count': len(env.state.atoms), 'bound_role_count': len(binding),
                'plans': len(plans), 'wall_seconds': perf_counter()-started,
                'metrics': env.state.metrics(), 'audit': audit, 'stages': stages,
                'diagnostics': getattr(result, 'diagnostics', ()),
                'candidate_rejections': getattr(result, 'candidate_rejections', ())}
    # Even a failed attempt keeps the actual executed prefix inspectable.
    try:
        trace_rows = [json.loads(row) for row in env.state.trace.records]
        schedule, gate_times = operation_schedule(plans, trace_rows)
        applied = {g for row in trace_rows if row.get('effect_completed') for g in row.get('applied_gate_ids', ())}
        gate_rows = [{**asdict(g), 'start_us': gate_times[g.id][0], 'end_us': gate_times[g.id][1],
                      'applied': g.id in applied} for g in gates if g.id in gate_times]
        (output / 'schedule.json').write_text(canonical_json(schedule), encoding='utf-8')
        (output / 'gate_schedule.json').write_text(canonical_json(gate_rows), encoding='utf-8')
        from .circuit_view import write_circuit_view
        write_circuit_view(output / 'physical_circuit.html', inputs.compiled, gate_rows, evidence)
    except Exception as exc:
        evidence['schedule_export_error'] = {'type': type(exc).__name__, 'message': str(exc)}
        if error is None:
            evidence['status'] = 'failed'
            evidence['error'] = evidence['schedule_export_error']
    for filename, value in (('result.json', evidence), ('plans.json', plans),
                            ('recording.json', recorder.payload()),
                            ('decisions.json', getattr(result, 'decision_log', ()))):
        (output / filename).write_text(canonical_json(value), encoding='utf-8')
    (output / 'checkpoint.json').write_text(env.snapshot(), encoding='utf-8')
    env.state.trace.write(output / 'trace.jsonl')
    recorder.write(output / 'animation.html')
    return evidence
