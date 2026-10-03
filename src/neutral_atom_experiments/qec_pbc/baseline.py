"""Canonical memory executed on the unchanged physical neutral-atom platform.

The protocol has fixed four-layer semantics; the physical backend uses fixed
source-row services and the ordinary Executor. Evidence keeps quantum checks,
physical schedules, exact plan replay, and offline fault audits separate.
"""
from collections import Counter
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import platform
from time import perf_counter

from neutral_atom_env import NeutralAtomEnv
from neutral_atom_env.domain.models import GateStatus, ZoneType
from neutral_atom_env.program.task_validation import validate_target
from neutral_atom_env.replay.serializer import canonical_json
from neutral_atom_env.visualization import VisualRecorder
from neutral_atom_strategies.motion.single_trap import in_zone
from neutral_atom_strategies.scheduling.m3 import initial_terminal
from neutral_atom_strategies.scheduling.qec_baseline import run_qec_baseline

from .neutral_atom import build_native_qec_inputs
from .physical import fresh_output, operation_schedule
from .surface import stabilizers, logical_product
from .pauli import PauliProduct
from .verification import verify_native_quantum


def canonical_native_inputs(memory, *, seed=0, initial_placement='prearranged'):
    """Start with a declared prepared EZ layout, or explicit storage history.

    This constructs the initial input before an environment exists. It does
    not submit a zero-time move or assume an encoded quantum state; all RESET
    and syndrome primitives remain in the caller's circuit.
    """
    if initial_placement not in ('prearranged', 'storage'):
        raise ValueError('initial_placement must be prearranged or storage')
    inputs = build_native_qec_inputs(memory.program, seed=seed)
    syndrome_ids = {key for phase in memory.phases if phase.kind == 'ancilla_measure'
                    for key in phase.gate_ids}
    measurements = tuple(replace(item, purpose='syndrome') if item.result_id in syndrome_ids
                         else item for item in inputs.compiled.measurements)
    inputs = replace(inputs, compiled=replace(inputs.compiled, measurements=measurements))
    if initial_placement == 'prearranged':
        placement = dict(inputs.placement) | baseline_destinations(memory, inputs)
        occupied = set(placement.values())
        # Declare initial support along with the placement; geometry is fixed.
        world = replace(inputs.platform.world, traps={key: replace(trap, enabled=key in occupied)
            for key, trap in inputs.platform.world.traps.items()})
        inputs = replace(inputs, placement=placement, platform=replace(inputs.platform, world=world))
    return inputs


def baseline_destinations(memory, inputs):
    """Embed the canonical mirrored patch at existing, separated EZ sites.

    One integer coordinate unit maps to 10um; neighboring data sites are 20um
    apart. These are placement choices inside the existing finite trap set,
    not changes to hardware capacity, pulse radius, or world geometry.
    """
    state = inputs.create_environment().state
    sites = {(t.position.x_um, t.position.y_um): t.id for t in state.world.traps.values()
             if in_zone(state, t.position, ZoneType.ENTANGLEMENT)}
    binding = dict(inputs.compiled.bindings)
    destinations = {}
    for role, (x, y) in memory.role_coordinates:
        point = (10 * (x - 1), -100 + 10 * (y - 1))
        if point not in sites:
            raise ValueError(f'Canonical working coordinate is not an existing EZ site: {point}')
        destinations[binding[role]] = sites[point]
    if len(set(destinations.values())) != len(destinations):
        raise ValueError('Canonical working holders must be distinct')
    return destinations


def phase_schedule(memory, gate_rows, operation_rows):
    by_id = {row['id']: row for row in gate_rows}
    rows = []
    for phase in memory.phases:
        ids = set(phase.native_gate_ids)
        gates = [by_id[g] for g in phase.native_gate_ids if g in by_id]
        pulses = [row for row in operation_rows if set(row['gate_ids']) & ids
                  and row['kind'] == 'entangling_pulse']
        rows.append({**phase.to_dict(), 'complete': len(gates) == len(ids),
                     'start_us': min((g['start_us'] for g in gates), default=None),
                     'end_us': max((g['end_us'] for g in gates), default=None),
                     'physical_pulse_count': len(pulses),
                     'physical_pulses': [{key: p[key] for key in
                         ('plan_id', 'operation_id', 'start_us', 'end_us', 'gate_ids')}
                         for p in pulses]})
    return rows


def execute_canonical_memory(memory, output, *, seed=0, wall_budget_s=900,
                             max_decisions=1024, fault_audit=None, progress=None,
                             initial_placement='prearranged'):
    """Execute and preserve a full baseline or the failed committed prefix."""
    contract = memory.program.memory_contract
    if contract is None or contract.decoder != 'canonical_detector_memory':
        raise ValueError('Expected the canonical memory contract')
    if wall_budget_s <= 0:
        raise ValueError('Wall budget must be positive')
    inputs = canonical_native_inputs(memory, seed=seed, initial_placement=initial_placement)
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
    # Take an independently restored reference, never a live-state alias.
    initial_quantum = NeutralAtomEnv.restore(initial).state.quantum_state
    terminal = initial_terminal(env.state)
    recorder = VisualRecorder(env.state)
    destinations = baseline_destinations(memory, inputs)
    binding = dict(inputs.compiled.bindings)
    ancillas = [binding[r.id] for r in memory.program.roles if r.kind == 'syndrome_ancilla']
    data = [binding[r.id] for r in memory.program.roles if r.kind == 'data']
    raw_ids = {m.result_id: m.raw_gate_id for m in inputs.compiled.measurements}
    closing = next(p for p in memory.phases if p.kind == 'ancilla_reset'
                   and p.round_index == contract.closing_round)
    stages, audit, result, error = [], {}, None, None
    started, last_progress, logical_progress = perf_counter(), 0., False
    source_root = Path(__file__).resolve().parents[2]
    fingerprints = {str(p.relative_to(source_root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for package in ('neutral_atom_env', 'neutral_atom_strategies', 'neutral_atom_experiments/qec_pbc')
        for p in sorted((source_root / package).rglob('*.py'))}
    for name, value in (
        ('canonical.json', memory.to_dict()), ('compiled.json', inputs.compiled.to_dict()),
        ('physical_circuit.json', {'gates': [asdict(g) for g in inputs.circuit.gates]}),
        ('platform.json', inputs.platform), ('working_destinations.json', destinations),
        ('initial_placement.json', dict(inputs.placement)),
        ('run_metadata.json', {'python': platform.python_version(), 'source_sha256': fingerprints,
            'seed': seed, 'wall_budget_s': wall_budget_s, 'max_decisions': max_decisions,
            'placement': 'canonical coords -> existing 20um data-spacing EZ sites',
            'initial_placement': initial_placement,
            'layout_preparation_time_included': initial_placement == 'storage',
            'upstream_layout_preparation_time_us': None,
            'backend': 'fixed source rows; declared interaction offset; no cost scoring',
            'timing_source': 'unchanged native platform parameters'})):
        (output / name).write_text(canonical_json(value), encoding='utf-8')
    (output / 'initial.json').write_text(initial, encoding='utf-8')
    if fault_audit is not None:
        (output / 'fault_audit.json').write_text(canonical_json(fault_audit), encoding='utf-8')

    def observe(state, event):
        nonlocal last_progress, logical_progress
        recorder.observe(state, event)
        if not stages and all(state.dag.nodes[key].status == GateStatus.COMPLETED
                              for key in closing.native_gate_ids):
            expectations = [product.sign * state.quantum_state.expectation(
                {binding[r]: b for r, b in product.factors})
                for product in stabilizers(contract.patch)]
            expected = [(-1)**state.measurement_results[raw_ids[
                f'{contract.patch}.r{contract.closing_round}.{kind}{i}']]
                for kind in ('X', 'Z') for i in range(4)]
            logical = logical_product(PauliProduct(((contract.patch, contract.basis),)))
            logical_expectation = logical.sign * state.quantum_state.expectation(
                {binding[r]: b for r, b in logical.factors})
            stages.append({'stage': 'closing_syndrome_sector_before_data_readout',
                'time_us': state.time_us, 'stabilizer_expectations': expectations,
                'reported_eigenvalues': expected, 'syndrome_sector_verified': expectations == expected,
                'logical_expectation': logical_expectation, 'logical_verified': logical_expectation == 1})
        elapsed = perf_counter() - started
        if event.event_type.value == 'plan_completed' and (
                elapsed-last_progress >= 10 or (state.dag.completed and not logical_progress)):
            item = {'plans': len(plans), 'completed_gates': state.metrics()['completed_gate_count'],
                    'total_gates': len(inputs.circuit.gates), 'simulation_time_us': state.time_us,
                    'wall_seconds': elapsed}
            (output / 'progress.json').write_text(canonical_json(item), encoding='utf-8')
            if progress:
                progress(item)
            last_progress = elapsed
            logical_progress = state.dag.completed
        if elapsed > wall_budget_s:
            raise TimeoutError(f'Canonical physical run exceeded {wall_budget_s}s')

    try:
        result = run_qec_baseline(env, mobile_atoms=ancillas, working_destinations=destinations,
            terminal=terminal, on_event=observe, max_decisions=max_decisions,
            candidate_budget=256, route_expansions=50000)
        if result.status != 'completed':
            raise AssertionError(f'Physical baseline {result.status}: {result.diagnostics}')
        validate_target(terminal, env.state)
        trace = [json.loads(row) for row in env.state.trace.records]
        reset_bits = {g: bit for row in trace for g, bit in row.get('reset_projection_results', {}).items()}
        reference = verify_native_quantum(inputs.circuit, initial_quantum, env.state.quantum_state,
                                          env.state.measurement_results, reset_bits)
        semantic = inputs.compiled.semantic_results(env.state.measurement_results)
        outputs = inputs.compiled.classical_outputs(env.state.measurement_results)
        operations, gate_times = operation_schedule(plans, trace)
        counts = Counter(g for row in trace if row.get('effect_completed') for g in
            (row.get('effect_gate_ids') or ([row['effect_gate_id']] if row.get('effect_gate_id') else [])))
        actual_applied = [g for row in trace if row.get('effect_completed')
                          for g in row.get('applied_gate_ids', ())]
        spectators = set(env.state.atoms) - set(binding.values())
        pulse_sizes = [len(row['gate_ids']) for row in operations if row['kind'] == 'entangling_pulse']
        audit = {
            'dag_complete': env.state.dag.completed, 'terminal_verified': True,
            'event_queue_empty': not env.pending,
            'effects_exactly_once': counts == Counter(g.id for g in inputs.circuit.gates),
            'dependency_timing_verified': all(g.id in gate_times and all(
                gate_times[parent][1] <= gate_times[g.id][0] + 1e-7 for parent in g.depends_on)
                for g in inputs.circuit.gates),
            'operation_timing_and_resources_verified': True,
            'quantum_reference': reference,
            'applied_effects_match_reference': Counter(actual_applied) == Counter(reference['applied_gate_ids']),
            'closing_syndrome_sector_verified': bool(stages) and stages[0]['syndrome_sector_verified'],
            'closing_logical_verified': bool(stages) and stages[0]['logical_verified'],
            'data_measured': all(env.state.atoms[q].measured for q in data),
            'final_data_matches_readout': all(env.state.quantum_state.expectation({binding[f'{contract.patch}.d{i}']:'Z'}) ==
                (-1)**semantic[f'{contract.patch}.final.m{i}'] for i in range(9)),
            'ancillas_reset_zero': all(not env.state.atoms[q].measured and
                env.state.quantum_state.expectation({q:'Z'}) == 1 for q in ancillas),
            'spectators_unchanged': all(not env.state.atoms[q].measured and
                env.state.quantum_state.expectation({q:'Z'}) == 1 for q in spectators),
            'measurement_sidecar_complete': len(semantic) == 8*contract.closing_round+9,
            'detector_sidecar_complete': len(outputs['detectors']) == 8*contract.closing_round,
            'detectors_zero': all(v == 0 for v in outputs['detectors'].values()),
            'logical_observable_zero': all(v == 0 for v in outputs['observables'].values()),
            'physical_parallel_cz_observed': max(pulse_sizes, default=0) > 1,
            'physical_pulse_count': len(pulse_sizes), 'max_parallel_cz': max(pulse_sizes, default=0),
            'semantic_results': semantic, 'classical_outputs': outputs,
            'raw_measurements': dict(env.state.measurement_results), 'reset_projection_bits': reset_bits}
        if initial_placement == 'prearranged':
            audit['prearranged_initial_holders_verified'] = all(
                inputs.placement[q] == site for q, site in destinations.items())
            audit['no_general_layout_staging'] = not any(
                row['kind'] in ('stage_atom', 'terminal_atom') for row in result.decision_log)
        if not all(v for v in audit.values() if isinstance(v, bool)) or not reference['reference_state_equal']:
            raise AssertionError('Canonical physical audit failed: '+str({k:v for k,v in audit.items() if v is False}))
    except Exception as exc:
        error = {'type': type(exc).__name__, 'message': str(exc)}

    try:
        replay = NeutralAtomEnv.restore(initial)
        for plan in plans:
            replay.submit(plan)
            replay.run()
        audit['independent_plan_replay_equal'] = replay.snapshot() == env.snapshot()
        if not audit['independent_plan_replay_equal']:
            raise AssertionError('Independent baseline plan replay differs')
    except Exception as exc:
        audit['independent_plan_replay_equal'] = False
        audit['replay_error'] = {'type': type(exc).__name__, 'message': str(exc)}
        if error is None:
            error = audit['replay_error']
    evidence = {'status': 'failed' if error else 'completed', 'error': error,
        'output_directory': str(output.resolve()), 'seed': seed, 'basis': contract.basis,
        'syndrome_rounds': contract.closing_round, 'strategy': 'canonical-fixed-source-row',
        'initial_placement': initial_placement,
        'layout_preparation_time_included': initial_placement == 'storage',
        'upstream_layout_preparation_time_us': None,
        'scope': 'Ideal physical memory plus separately bounded circuit-fault audit; no stochastic fidelity or loss simulation',
        'native_gate_count': len(inputs.circuit.gates),
        'gate_counts': dict(Counter(g.gate_type for g in inputs.circuit.gates)),
        'physical_atom_count': len(env.state.atoms), 'bound_role_count': len(binding),
        'plans': len(plans), 'wall_seconds': perf_counter()-started, 'metrics': env.state.metrics(),
        'audit': audit, 'stages': stages,
        'diagnostics': getattr(result, 'diagnostics', ()),
        'candidate_rejections': getattr(result, 'candidate_rejections', ())}
    try:
        trace = [json.loads(row) for row in env.state.trace.records]
        operations, gate_times = operation_schedule(plans, trace)
        applied = {g for row in trace if row.get('effect_completed') for g in row.get('applied_gate_ids', ())}
        gate_rows = [{**asdict(g), 'start_us': gate_times[g.id][0], 'end_us': gate_times[g.id][1],
                      'applied': g.id in applied} for g in inputs.circuit.gates if g.id in gate_times]
        (output / 'schedule.json').write_text(canonical_json(operations), encoding='utf-8')
        (output / 'gate_schedule.json').write_text(canonical_json(gate_rows), encoding='utf-8')
        (output / 'phase_schedule.json').write_text(canonical_json(phase_schedule(memory, gate_rows, operations)), encoding='utf-8')
        from .circuit_view import write_circuit_view
        write_circuit_view(output / 'physical_circuit.html', inputs.compiled, gate_rows, evidence)
    except Exception as exc:
        evidence['schedule_export_error'] = {'type': type(exc).__name__, 'message': str(exc)}
        evidence['status'] = 'failed'
        evidence['error'] = evidence['error'] or evidence['schedule_export_error']
    for name, value in (('result.json', evidence), ('evidence.json', evidence), ('plans.json', plans),
                         ('recording.json', recorder.payload()),
                         ('decisions.json', getattr(result, 'decision_log', ()))):
        (output / name).write_text(canonical_json(value), encoding='utf-8')
    (output / 'checkpoint.json').write_text(env.snapshot(), encoding='utf-8')
    env.state.trace.write(output / 'trace.jsonl')
    recorder.write(output / 'animation.html')
    return evidence
