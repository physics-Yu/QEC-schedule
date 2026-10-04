"""Actual canonical d=3 QMAP compilation on the independent scheduling kernel.

Protocol templates are reused once. The hot execution path imports no legacy
Environment, ProgramBuilder, SimulationState, router, or trace validator.
"""
from dataclasses import replace
from hashlib import sha256
import json
from math import ceil, sqrt
from pathlib import Path
from time import perf_counter

from neutral_atom_kernel import DeclaredReportSource, GateSpec, KernelExecutor, Operation
from neutral_atom_kernel.model import thaw
from neutral_atom_strategies.native_kernel.compiler import compile_native
from neutral_atom_strategies.native_kernel.lowering import lower_native
from .canonical import canonical_memory_program


def profile():
    """Explicit experimental geometry, distinct from the historical rigid one."""
    architecture = {
        'name': 'native-kernel-d3-paired5-sz10/v1',
        'operation_duration': {'rydberg_gate': .36, 'single_qubit_gate': 1, 'atom_transfer': 15},
        'operation_fidelity': {'rydberg_gate': .995, 'single_qubit_gate': .9997, 'atom_transfer': .999},
        'qubit_spec': {'T': 1.5e6},
        'storage_zones': [{'zone_id': 0, 'slms': [
            {'id': 0, 'site_separation': [10, 10], 'r': 1, 'c': 17, 'location': [0, 0]}],
            'offset': [0, 0], 'dimension': [160, 0]}],
        'entanglement_zones': [{'zone_id': 0, 'slms': [
            {'id': 1, 'site_separation': [20, 10], 'r': 2, 'c': 8, 'location': [0, 60]},
            {'id': 2, 'site_separation': [20, 10], 'r': 2, 'c': 8, 'location': [5, 60]}],
            'offset': [0, 60], 'dimension': [145, 10]}],
        'aods': [{'id': 0, 'site_separation': 2, 'r': 8, 'c': 16}],
        'arch_range': [[-20, -30], [200, 200]],
        'rydberg_range': [[[-10, 50], [155, 80]]],
    }
    return {
        'id': architecture['name'], 'architecture': architecture,
        'bounds_um': (-20, -30, 200, 200), 'slm_grid_um': 5,
        'slm_origin_um': (0, 0), 'measurement_zone_um': (0, 130, 180, 180),
        'cz_zone_um': (-10, 50, 155, 80), 'cz_zones_um': {'zone_cz0': (-10, 50, 155, 80)},
        'aod_rows': 8, 'aod_columns': 16, 'aod_axis_spacing_um': 2,
        'cz_radius_um': 6, 'cz_nonpartner_um': 10, 'raman_separation_um': 5,
        'transport_clearance_um': 1,
        'initial_axes': {'AOD_0': {'rows': tuple(2 * i for i in range(8)),
                                  'columns': tuple(2 * i for i in range(16))}},
        'initial_placement_scope': 'declared t=0; external preparation cost unknown',
        'model': 'ordered row/column with selective transfer; single native AOD',
    }


def protocol(rounds=2):
    canonical = canonical_memory_program(basis='Z', rounds=rounds)
    role_to_atom = {role.id: f'Q{i:03d}' for i, role in enumerate(canonical.program.roles)}
    specs, previous = [], {}
    for task in canonical.program.operations:
        atoms = tuple(role_to_atom[r] for r in task.targets)
        parents = tuple(dict.fromkeys((*(f'{p}__g000' for p in task.depends_on),
                                      *(previous[q] for q in atoms if q in previous))))
        spec = GateSpec(f'{task.id}__g000', task.gate_type, atoms, parents)
        specs.append(spec)
        for q in atoms:
            previous[q] = spec.id
    return canonical, role_to_atom, tuple(specs)


def duration(a, b):
    return 200 * sqrt(max(abs(b[0]-a[0]), abs(b[1]-a[1])) / 110)


def transport(atom, source, target, key):
    """Fixed 2.5 um off-grid corridor; no search or hidden relocation."""
    source, target = tuple(source), tuple(target)
    if source == target:
        return ()
    corners = [(source[0]+2.5, source[1]+2.5),
               (source[0]+2.5, target[1]+2.5),
               (target[0]+2.5, target[1]+2.5), target]
    out = [Operation(key+'.load', 'LOAD', (atom,), 15)]
    current = source
    for i, point in enumerate(corners):
        if current != point:
            out.append(Operation(f'{key}.move{i}', 'MOVE', (atom,), duration(current, point),
                                 positions=((atom, point),),
                                 metadata={'origin': 'local-service', 'route': 'offset-2.5um'}))
            current = point
    out.append(Operation(key+'.store', 'STORE', (atom,), 15))
    return tuple(out)


def alignment(positions, targets, key):
    """Execute an explicit two-stage permutation via disjoint empty SLM slots."""
    current = dict(positions)
    moved = [q for q in targets if current[q] != tuple(targets[q])]
    ops = []
    buffers = {}
    for i, q in enumerate(moved):
        # Odd SLM columns, above native EZ and below readout; unique stable sites.
        buffer = (5 + 10 * i, 100)
        if buffer in current.values():
            raise ValueError('Declared alignment buffer is occupied')
        ops.extend(transport(q, current[q], buffer, f'{key}.park.{q}'))
        current[q] = buffer
        buffers[q] = buffer
    for q in moved:
        target = tuple(targets[q])
        if any(p == target for other, p in current.items() if other != q):
            raise ValueError('Alignment target still occupied')
        ops.extend(transport(q, current[q], target, f'{key}.restore.{q}'))
        current[q] = target
    return tuple(ops)


def service(measure_or_reset, positions, key, resets=()):
    current = dict(positions)
    reset_by_atom = {g.atoms[0]: g for g in resets}
    ops = []
    for gate in measure_or_reset:
        q = gate.atoms[0]
        source = current[q]
        # Nearest legal 5 um MZ site in the declared empty readout strip.
        target = (min(180, max(0, round(source[0]/5)*5)), 130)
        if any(p == target for other, p in current.items() if other != q):
            raise ValueError('Nearest declared measurement site is occupied')
        ops.extend(transport(q, source, target, f'{key}.{q}.out'))
        ops.append(Operation(f'{key}.{q}.effect', gate.kind, (q,),
            500 if gate.kind == 'MEASURE' else 100, gate_ids=(gate.id,),
            report_ids=(gate.id,) if gate.kind == 'MEASURE' else (),
            metadata={'origin': 'local-service', 'basis': 'Z'}))
        if q in reset_by_atom:
            reset = reset_by_atom[q]
            ops.append(Operation(f'{key}.{q}.reset', 'RESET', (q,), 100,
                                 gate_ids=(reset.id,), metadata={'origin': 'local-service'}))
        ops.extend(transport(q, target, source, f'{key}.{q}.back'))
    return tuple(ops)


def serialize_operation(op):
    return {'id': op.id, 'kind': op.kind, 'atoms': list(op.atoms), 'duration_us': op.duration_us,
            'positions': [[q, list(p)] for q, p in op.positions], 'gate_ids': list(op.gate_ids),
            'report_ids': list(op.report_ids), 'aod_id': op.aod_id, 'metadata': thaw(op.metadata)}


def _semantic(observation):
    return {'time_us': observation.time_us, 'positions': dict(observation.positions),
            'holders': dict(observation.holders), 'completed_gate_ids': sorted(observation.completed_gate_ids),
            'measurement_results': dict(observation.measurement_results),
            'report_source_cursor': observation.report_source_cursor,
            'measurement_completion_times_us': dict(observation.measurement_completion_times_us),
            'aod_axes': thaw(observation.aod_axes), 'completed': observation.completed,
            'pending_events': observation.pending_events}


def run(output, *, rounds=2, wall_budget=120):
    from neutral_atom_strategies.native_kernel.axes import finalize_operations
    from neutral_atom_kernel.audit import audit_operations

    started = perf_counter()
    directory = Path(output); directory.mkdir(parents=True, exist_ok=True)
    config = profile()
    canonical, role_to_atom, specs = protocol(rounds)
    atom_ids = tuple(role_to_atom.values())
    initial = {q: (10*i, 0) for i, q in enumerate(atom_ids)}
    reports = {g.id: 0 for g in specs if g.kind == 'MEASURE'}
    source = DeclaredReportSource(source_id='canonical-scheduling-zero/v1', reports=reports)
    executor = KernelExecutor(initial, specs, initial_aod_axes=config['initial_axes'],
                              report_source=source, recording=True)
    ops_all, blocks, timings = [], [], {'native': 0., 'lowering': 0., 'axes': 0., 'advance_with_recovery_probe': 0.}
    resume_proof = None

    def execute(key, operations, provenance):
        nonlocal executor, resume_proof
        if perf_counter()-started > wall_budget:
            raise TimeoutError('Native kernel demonstration exceeded its declared wall budget')
        before = executor.observe()
        t = perf_counter()
        finalized = finalize_operations(operations, before.positions,
            initial_axes=before.aod_axes, initial_holders=before.holders,
            bounds=config['bounds_um'], minimum_axis_spacing_um=2)
        timings['axes'] += perf_counter()-t
        ops_all.extend(finalized)
        block = executor.bind_block(key, finalized, native_provenance=provenance)
        blocks.append({'id': key, 'expected_version': block.expected_version,
                       'starting_state_hash': block.starting_state_hash,
                       'native_provenance': thaw(block.native_provenance)})
        t = perf_counter()
        if resume_proof is None and any(op.kind == 'MEASURE' for op in finalized):
            index = next(i for i, op in enumerate(finalized) if op.kind == 'MEASURE')
            measurement = finalized[index]
            cut = before.time_us + sum(op.duration_us for op in finalized[:index]) + measurement.duration_us/2
            executor.run(block, until_us=cut)
            mid = executor.observe()
            if any(r in mid.measurement_results for r in measurement.report_ids):
                raise AssertionError('Report appeared before readout completion')
            checkpoint = executor.checkpoint(include_journal=True)
            (directory/'inflight-checkpoint.json').write_text(json.dumps(checkpoint, indent=2), encoding='utf-8')
            restored = KernelExecutor.restore(checkpoint)
            executor.run(); restored.run()
            if _semantic(executor.observe()) != _semantic(restored.observe()):
                raise AssertionError('In-flight recovery diverged')
            executor = restored
            resume_proof = {'passed': True, 'cut_us': cut, 'report_not_ready': True,
                            'measurement_id': measurement.report_ids[0],
                            'report_completion_us': executor.observe().measurement_completion_times_us[measurement.report_ids[0]]}
        else:
            executor.run(block)
        timings['advance_with_recovery_probe'] += perf_counter()-t

    i, chunk = 0, 0
    while i < len(specs):
        kind = specs[i].kind
        if kind in {'H', 'X', 'Y', 'Z', 'T', 'CZ'}:
            end = i
            while end < len(specs) and specs[end].kind in {'H', 'X', 'Y', 'Z', 'T', 'CZ'}:
                end += 1
            gates = specs[i:end]; chunk += 1; key = f'unitary-{chunk}'
            boundaries = {phase.native_gate_ids[0] for phase in canonical.phases
                          if phase.native_gate_ids and phase.native_gate_ids[0] in {g.id for g in gates}}
            boundaries.discard(gates[0].id)
            t = perf_counter()
            result = compile_native(gates, atom_ids=atom_ids, architecture=config['architecture'],
                block_id=key, completed_dependencies=executor.observe().completed_gate_ids,
                barrier_before=boundaries, reuse_level=0.)
            timings['native'] += perf_counter()-t
            (directory/f'{key}.native.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
            (directory/f'{key}.naviz').write_text(result['code'], encoding='utf-8')
            if dict(executor.observe().positions) != {q: tuple(p) for q, p in result['initial_positions'].items()}:
                execute(key+'.align', alignment(executor.observe().positions, result['initial_positions'], key+'.align'),
                        {'engine': 'explicit-state-alignment', 'initial_placement_overwrite': False})
            t = perf_counter()
            lowered = lower_native(result, gates, initial_positions=executor.observe().positions,
                                    completed_dependencies=executor.observe().completed_gate_ids)
            timings['lowering'] += perf_counter()-t
            execute(key, lowered.operations, lowered.provenance)
            i = end
        else:
            end = i
            while end < len(specs) and specs[end].kind == kind:
                end += 1
            following = end
            resets = ()
            if kind == 'MEASURE':
                while following < len(specs) and specs[following].kind == 'RESET':
                    following += 1
                resets = specs[end:following]
            key = f'service-{i}-{kind.lower()}'
            execute(key, service(specs[i:end], executor.observe().positions, key, resets),
                    {'engine': 'explicit-MZ-service', 'routing_protocol': 'offset-2.5um',
                     'report_model': 'canonical-scheduling-zero/v1'})
            i = following if resets else end
    final = executor.observe()
    if not final.completed or set(final.completed_gate_ids) != {g.id for g in specs} or final.pending_events:
        raise AssertionError('Canonical native protocol incomplete')
    t = perf_counter()
    recorded = KernelExecutor(initial, specs, initial_aod_axes=config['initial_axes'],
                              report_source=source, recording=True)
    recorded.run(recorded.bind_block('recording-on-equivalence', ops_all))
    timings['advance_recording_on'] = perf_counter()-t
    if _semantic(final) != _semantic(recorded.observe()):
        raise AssertionError('Clean recording-on run differs from recovered execution')
    t = perf_counter()
    quiet = KernelExecutor(initial, specs, initial_aod_axes=config['initial_axes'],
                           report_source=source, recording=False)
    quiet.run(quiet.bind_block('recording-off-equivalence', ops_all))
    timings['advance_recording_off'] = perf_counter()-t
    equivalent = _semantic(final) == _semantic(quiet.observe())
    if not equivalent:
        raise AssertionError('Recording changes kernel results')
    t = perf_counter()
    audit = audit_operations(initial, ops_all, config, gates=specs,
                             initial_axes=config['initial_axes']['AOD_0'])
    timings['offline_audit'] = perf_counter()-t
    (directory/'offline-audit.json').write_text(json.dumps(audit, indent=2), encoding='utf-8')
    (directory/'initial.json').write_text(json.dumps({'profile': config, 'positions': initial,
        'gates': [{'id': g.id, 'kind': g.kind, 'atoms': g.atoms, 'depends_on': g.depends_on} for g in specs],
        'report_source': source.checkpoint()}, indent=2), encoding='utf-8')
    (directory/'operations.json').write_text(json.dumps([serialize_operation(o) for o in ops_all], indent=2), encoding='utf-8')
    (directory/'blocks.json').write_text(json.dumps(blocks, indent=2), encoding='utf-8')
    (directory/'checkpoint.json').write_text(executor.checkpoint_json(include_journal=True), encoding='utf-8')
    journal = [thaw(e) for e in executor.journal]
    (directory/'journal.json').write_text(json.dumps(journal, indent=2), encoding='utf-8')
    result = {'schema': 'native-kernel-memory/1', 'runtime_status': 'completed',
        'offline_physical_status': audit['status'], 'profile': config['id'],
        'engine': 'mqt.qmap.native.C++', 'runtime': 'neutral_atom_kernel',
        'legacy_env_execution_calls': 0, 'legacy_candidate_search_calls': 0,
        'atoms': len(atom_ids), 'rounds': rounds, 'gates': len(specs),
        'cz_pairs': sum(g.kind == 'CZ' for g in specs),
        'cz_pulses': sum(o.kind == 'CZ' for o in ops_all),
        'max_parallel_cz': max((len(o.gate_ids) for o in ops_all if o.kind == 'CZ'), default=0),
        'operations': len(ops_all), 'journal_events': len(journal), 'reports': len(final.measurement_results),
        'physical_time_us': final.time_us, 'recording_equivalent': equivalent,
        'inflight_recovery': resume_proof, 'timings_seconds': timings,
        'factory_integrated': False, 'full_shor': False, 'fidelity': None,
        'wall_seconds_before_export': perf_counter()-started}
    (directory/'summary.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result, {'initial': initial, 'profile': config, 'gates': specs, 'operations': ops_all,
                    'journal': journal, 'role_to_atom': role_to_atom, 'final': _semantic(final),
                    'report_source': source.checkpoint(), 'summary': result}
