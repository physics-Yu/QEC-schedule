"""Physical execution of the three-patch encoded parity instrument.

This experiment declares a finite 51-atom platform before initialization. It
uses the ordinary hardware defaults and validators, a 98-cell single AOD,
20 um data spacing, and prearranged EZ holders. Layout preparation is excluded;
every circuit RESET, MEASURE, transport, and quantum effect is executed.
"""
from collections import Counter, defaultdict
from dataclasses import asdict, replace
import json
import hashlib
from pathlib import Path
from time import perf_counter

from neutral_atom_env import NeutralAtomEnv
from neutral_atom_env.domain.models import (GridCoord, Position2D, Rectangle,
    StaticTrap, Zone, ZoneType)
from neutral_atom_env.domain.operations import HardwareConfig
from neutral_atom_env.platform import Platform
from neutral_atom_env.program.task_validation import validate_target
from neutral_atom_env.replay.serializer import canonical_json
from neutral_atom_env.visualization import VisualRecorder
from neutral_atom_env.world import AODRuntimeState, WorldState
from neutral_atom_strategies.scheduling.m3 import initial_terminal
from neutral_atom_strategies.scheduling.qec_sparse import run_qec_sparse

from .canonical import canonical_memory_program
from .encoded_ppm import EncodedParity, compile_encoded_parity, retained_output_expectations
from .neutral_atom import NativeQECInputs
from .pauli import PauliProduct
from .physical import fresh_output, operation_schedule
from .surface import logical_product, stabilizers
from .verification import verify_native_quantum


def encoded_parity_inputs(protocol, *, seed=0):
    """Declare this bounded experiment; do not modify the two-patch platform."""
    if not isinstance(protocol, EncodedParity):
        raise TypeError('EncodedParity required')
    if type(seed) is not int or seed < 0:
        raise ValueError('Seed must be a nonnegative integer')
    bindings = {r.id: f'Q{i:03d}' for i, r in enumerate(protocol.program.roles)}
    compiled = compile_encoded_parity(protocol, bindings)
    syndrome_ids = {key for p in protocol.phases if p.kind == 'ancilla_measure'
                    for key in p.gate_ids}
    compiled = replace(compiled, measurements=tuple(
        replace(m, purpose='syndrome') if m.result_id in syndrome_ids else m
        for m in compiled.measurements))
    def rect(x1, y1, x2, y2):
        return Rectangle(Position2D(x1, y1), Position2D(x2, y2))
    coordinates = {}
    for patch, offset in zip(protocol.patches, (0, 70, 140)):
        template = canonical_memory_program(patch=patch, rounds=1)
        for role, (x, y) in template.role_coordinates:
            coordinates[role] = (offset + 10 * (x - 1), -100 + 10 * (y - 1))
    traps = {}
    # All finite sites exist before the environment and strategy are created.
    for y in range(-115, -30, 5):
        for x in range(-15, 211, 5):
            key = f'EZ_{x}_{-y}'
            traps[key] = StaticTrap(key, GridCoord(x//5, y//5), Position2D(x, y), False)
    placement, destinations = {}, {}
    for role, atom in bindings.items():
        x, y = coordinates[role]
        site = f'EZ_{x}_{-y}'
        traps[site] = replace(traps[site], enabled=True)
        placement[atom] = destinations[atom] = site
        index = int(atom[1:])
        key = f'M{index:03d}'
        traps[key] = StaticTrap(key, GridCoord(x//5, (y-140)//5),
                                Position2D(x, y-140), False)
    world = WorldState(rect(-30, -270, 240, 100), traps, (
        Zone('SZ', ZoneType.STORAGE, rect(-20, 0, 215, 80)),
        Zone('EZ', ZoneType.ENTANGLEMENT, rect(-20, -120, 215, -30)),
        Zone('MZ', ZoneType.MEASUREMENT, rect(-20, -260, 215, -160))), 5)
    # No interaction, clearance, timing, capacity, or optical rule override.
    platform = Platform(world, HardwareConfig(ez_neighbor_guard_enabled=False),
        AODRuntimeState(rows=7, columns=14, spacing_um=5,
            pose=Position2D(-5, -5), column_offsets_um=(
                *range(0, 35, 5), *range(40, 75, 5))))
    inputs = NativeQECInputs(compiled, compiled.circuit, platform, placement, seed)
    return inputs, destinations


def encoded_cz_groups(state, gates, compiled, ancilla_patch):
    """Select carriers per interaction, rather than one global mobile set.

    A syndrome ancilla carries local checks; ancilla-patch data carries the
    transversal interpatch interactions. Equal-shift/source-row/patch groups
    are attempted in circuit order, followed by singleton fallbacks.
    """
    roles = {q: r for r in compiled.program.roles
             for key, q in compiled.bindings if key == r.id}
    buckets = defaultdict(list)
    offset = state.hardware.interaction_offset
    for gate in gates:
        if gate.gate_type != 'CZ':
            raise ValueError('CZ gates required')
        candidates = [q for q in gate.qubit_ids if roles[q].kind == 'syndrome_ancilla']
        if not candidates:
            candidates = [q for q in gate.qubit_ids if roles[q].patch == ancilla_patch]
        if len(candidates) != 1:
            raise ValueError('Each encoded interaction needs one unambiguous carrier')
        mobile = candidates[0]
        anchor = next(q for q in gate.qubit_ids if q != mobile)
        pm = state.placement.position(mobile, state.world, state.aod)
        pa = state.placement.position(anchor, state.world, state.aod)
        shift = (pa.x_um + offset.x_um - pm.x_um,
                 pa.y_um + offset.y_um - pm.y_um)
        buckets[(shift, pm.y_um, roles[mobile].patch)].append((gate.id, anchor, mobile))
    for (shift, _, _), members in buckets.items():
        yield shift, tuple(members)
        if len(members) > 1:
            for member in members:
                yield shift, (member,)


def encoded_readout_groups(state, gates, compiled):
    patch_of = {q: r.patch for r in compiled.program.roles
                for key, q in compiled.bindings if key == r.id}
    buckets = defaultdict(list)
    for gate in gates:
        q = gate.qubit_ids[0]
        p = state.placement.position(q, state.world, state.aod)
        buckets[(patch_of[q], p.y_um)].append(gate)
    for members in buckets.values():
        yield tuple(members)
        if len(members) > 1:
            for gate in members:
                yield (gate,)


def encoded_output_audit(protocol, inputs, state):
    """Check retained code sectors and the branch-dependent logical parity."""
    binding = dict(inputs.compiled.bindings)
    semantic = inputs.compiled.semantic_results(state.measurement_results)
    outputs = inputs.compiled.classical_outputs(state.measurement_results)
    parity_bit = outputs['observables'][protocol.observable_id]
    def expectation(product):
        return product.sign * state.quantum_state.expectation(
            {binding[r]: b for r, b in product.factors})
    sectors = []
    for patch in protocol.output_patches:
        for i, product in enumerate(stabilizers(patch)):
            kind, check = ('X' if i < 4 else 'Z'), i % 4
            key = f'{patch}.r{2*protocol.rounds}.{kind}{check}'
            sectors.append({'patch': patch, 'check': f'{kind}{check}',
                'actual': expectation(product), 'expected': (-1)**semantic[key]})
    signed_parity = logical_product(PauliProduct(tuple(
        (p, protocol.basis) for p in protocol.output_patches), protocol.parity_sign))
    correlation = expectation(signed_parity)
    retained = all(not state.atoms[binding[f'{p}.d{i}']].measured
                   for p in protocol.output_patches for i in range(9))
    expected_words = retained_output_expectations(protocol, semantic)
    logical_checks = [{'product': word.to_dict(), 'actual_signed_expectation': expectation(word)}
                      for word in expected_words]
    return {'semantic_results': semantic, 'classical_outputs': outputs,
        'reported_parity_bit': parity_bit, 'output_sectors': sectors,
        'output_code_sectors_verified': all(s['actual'] == s['expected'] for s in sectors),
        'retained_data_unmeasured': retained,
        'retained_logical_parity_expectation': correlation,
        'branch_logical_parity_verified': correlation == (-1)**parity_bit,
        'retained_output_constraints': logical_checks,
        'retained_output_coherence_verified': all(row['actual_signed_expectation'] == 1
                                                 for row in logical_checks),
        'detectors_zero': all(v == 0 for v in outputs['detectors'].values())}


def execute_encoded_parity(protocol, output, *, seed=0, wall_budget_s=1800,
                           max_decisions=4096, progress=None):
    """Execute a full ideal instrument and preserve failed prefixes as evidence."""
    if protocol.close_data_basis is not None:
        raise ValueError('This physical runner requires the retained-output instrument')
    if wall_budget_s <= 0:
        raise ValueError('Positive wall budget required')
    inputs, destinations = encoded_parity_inputs(protocol, seed=seed)
    output = fresh_output(output)
    plans = []
    class RecordingEnvironment(NeutralAtomEnv):
        def submit(self, plan):
            answer = super().submit(plan)
            plans.append(plan)
            return answer
    env = RecordingEnvironment(inputs.create_environment().state)
    initial = env.snapshot()
    initial_quantum = NeutralAtomEnv.restore(initial).state.quantum_state
    terminal = initial_terminal(env.state)
    recorder = VisualRecorder(env.state)
    source_root = Path(__file__).resolve().parents[2]
    source_hashes = {str(p.relative_to(source_root)).replace('\\', '/'):
        hashlib.sha256(p.read_bytes()).hexdigest()
        for package in ('neutral_atom_env', 'neutral_atom_strategies', 'neutral_atom_experiments/qec_pbc')
        for p in sorted((source_root/package).rglob('*.py'))}
    for name, value in (('protocol.json', protocol.to_dict()),
                        ('compiled.json', inputs.compiled.to_dict()),
                        ('platform.json', inputs.platform),
                        ('working_destinations.json', destinations),
                        ('initial_placement.json', dict(inputs.placement)),
                        ('run_metadata.json', {'seed': seed, 'source_sha256': source_hashes,
                            'wall_budget_s': wall_budget_s, 'max_decisions': max_decisions,
                            'hardware_source': 'native HardwareConfig defaults; only authorized EZ neighbor guard disabled',
                            'geometry_scope': 'declared finite 51-atom experiment; original two-patch platform unchanged',
                            'initial_placement': 'prearranged; all quantum preparations remain circuit tasks',
                            'upstream_layout_preparation_time_us': None})):
        (output/name).write_text(canonical_json(value), encoding='utf-8')
    (output/'initial.json').write_text(initial, encoding='utf-8')
    started, last_progress = perf_counter(), 0.
    def observe(state, event):
        nonlocal last_progress
        recorder.observe(state, event)
        elapsed = perf_counter() - started
        if elapsed - last_progress >= 10:
            item = {'plans': len(plans), 'completed_gates': state.metrics()['completed_gate_count'],
                    'total_gates': len(inputs.circuit.gates),
                    'simulation_time_us': state.time_us, 'wall_seconds': elapsed}
            (output/'progress.json').write_text(canonical_json(item), encoding='utf-8')
            if progress:
                progress(item)
            last_progress = elapsed
        if elapsed > wall_budget_s:
            raise TimeoutError(f'Encoded parity exceeded {wall_budget_s}s')
    result, audit, error = None, {}, None
    try:
        result = run_qec_sparse(env, working_destinations=destinations, terminal=terminal,
            on_event=observe, max_decisions=max_decisions, route_expansions=50000,
            candidate_budget=256,
            cz_groups_factory=lambda s, g: encoded_cz_groups(s, g, inputs.compiled, protocol.patches[2]),
            readout_groups_factory=lambda s, g: encoded_readout_groups(s, g, inputs.compiled))
        if result.status != 'completed':
            raise AssertionError(f'Encoded physical execution {result.status}: {result.diagnostics}')
        validate_target(terminal, env.state)
        trace = [json.loads(row) for row in env.state.trace.records]
        resets = {g: bit for row in trace for g, bit in row.get('reset_projection_results', {}).items()}
        reference = verify_native_quantum(inputs.circuit, initial_quantum, env.state.quantum_state,
                                          env.state.measurement_results, resets)
        operations, gate_times = operation_schedule(plans, trace)
        counts = Counter(g for row in trace if row.get('effect_completed') for g in
            (row.get('effect_gate_ids') or ([row['effect_gate_id']] if row.get('effect_gate_id') else [])))
        audit = encoded_output_audit(protocol, inputs, env.state) | {
            'dag_complete': env.state.dag.completed, 'terminal_verified': True,
            'event_queue_empty': not env.pending,
            'effects_exactly_once': counts == Counter(g.id for g in inputs.circuit.gates),
            'dependency_timing_verified': all(all(
                gate_times[p][1] <= gate_times[g.id][0] + 1e-7 for p in g.depends_on)
                for g in inputs.circuit.gates),
            'quantum_reference': reference,
            'reference_state_equal': reference['reference_state_equal'],
            'operation_timing_and_resources_verified': True,
            'no_layout_staging': not any(row['kind'] in ('stage_atom', 'terminal_atom')
                                        for row in result.decision_log)}
        if not all(v for v in audit.values() if isinstance(v, bool)):
            raise AssertionError('Encoded output audit failed: '+str({k:v for k,v in audit.items() if v is False}))
    except Exception as exc:
        error = {'type': type(exc).__name__, 'message': str(exc)}
    try:
        replay = NeutralAtomEnv.restore(initial)
        for plan in plans:
            replay.submit(plan)
            replay.run()
        audit['independent_plan_replay_equal'] = replay.snapshot() == env.snapshot()
        if not audit['independent_plan_replay_equal']:
            raise AssertionError('Encoded physical plan replay differs')
    except Exception as exc:
        audit['independent_plan_replay_equal'] = False
        audit['replay_error'] = {'type': type(exc).__name__, 'message': str(exc)}
        error = error or audit['replay_error']
    # Preserve the committed prefix before attempting a complete-plan timing
    # export. An interrupted accepted plan legitimately lacks future operation
    # boundaries, so operation_schedule may reject it even though the prefix
    # is valuable failure evidence.
    (output/'checkpoint.json').write_text(env.snapshot(), encoding='utf-8')
    env.state.trace.write(output/'trace.jsonl')
    (output/'recording.json').write_text(canonical_json(recorder.payload()), encoding='utf-8')
    recorder.write(output/'animation.html')
    trace = [json.loads(row) for row in env.state.trace.records]
    try:
        operations, gate_times = operation_schedule(plans, trace)
        schedule_complete = True
    except Exception as exc:
        operations, gate_times = [], {}
        schedule_complete = False
        audit['schedule_export_error'] = {'type': type(exc).__name__, 'message': str(exc)}
        error = error or audit['schedule_export_error']
    pulse_sizes = [len(row['gate_ids']) for row in operations if row['kind'] == 'entangling_pulse']
    evidence = {'schema': 'qec-encoded-parity-physical/1',
        'status': 'failed' if error else 'completed', 'error': error,
        'output_directory': str(output.resolve()), 'basis': protocol.basis,
        'seed': seed, 'rounds_before_and_after': protocol.rounds,
        'scope': 'ideal encoded nondestructive X/Z parity on a declared finite experiment platform',
        'full_fault_tolerance_claim': False, 'physical_atom_count': len(env.state.atoms),
        'native_gate_count': len(inputs.circuit.gates),
        'gate_counts': dict(Counter(g.gate_type for g in inputs.circuit.gates)),
        'plans': len(plans), 'wall_seconds': perf_counter()-started,
        'schedule_complete': schedule_complete,
        'physical_pulse_count': len(pulse_sizes) if schedule_complete else None,
        'max_parallel_cz': max(pulse_sizes, default=0) if schedule_complete else None,
        'initial_placement': 'prearranged', 'layout_preparation_time_included': False,
        'upstream_layout_preparation_time_us': None,
        'metrics': env.state.metrics(), 'audit': audit,
        'diagnostics': getattr(result, 'diagnostics', ()),
        'candidate_rejections': getattr(result, 'candidate_rejections', ())}
    for name, value in (('evidence.json', evidence), ('plans.json', plans),
                        ('schedule.json', operations),
                        ('decisions.json', getattr(result, 'decision_log', ()))):
        (output/name).write_text(canonical_json(value), encoding='utf-8')
    return evidence
