"""Compile and physically execute a bounded saved Shor15 Clifford prefix."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))


def main():
    from neutral_atom_env import NeutralAtomEnv
    from neutral_atom_env.replay.serializer import canonical_json
    from neutral_atom_env.visualization import VisualRecorder
    from neutral_atom_experiments.qec_pbc.parallel_prefix import (
        create_parallel_prefix_environment, load_native_parallel_prefix)
    from neutral_atom_strategies.scheduling.parallel_patch import run_parallel_patch

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--patches', type=int, choices=(1, 2, 4, 12), default=12)
    parser.add_argument('--algorithm-only', action='store_true', help='Omit the actual right-side resource Clifford prefix')
    parser.add_argument('--wall-budget', type=float, default=1800.)
    parser.add_argument('--max-decisions', type=int, default=512)
    parser.add_argument('--skip-replay', action='store_true', help='Preserve the run but leave replay explicitly unverified')
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    prefix = load_native_parallel_prefix(args.source, patch_count=args.patches, include_magic=not args.algorithm_only)
    env, platform, placement, metadata = create_parallel_prefix_environment(prefix)
    initial = env.snapshot()
    recorder = VisualRecorder(env.state, scene_metadata=metadata)
    plans, progress = [], []
    def save(name, value):
        (output / name).write_text(canonical_json(value), encoding='utf-8')
    save('source-prefix.json', prefix.source)
    save('prefix-circuit.json', prefix.circuit_dict())
    save('parallel-phases.json', {'schema': 'encoded-native-parallel-phases/1', 'phases': prefix.phases})
    save('platform.json', platform)
    save('initial-placement.json', placement)
    (output / 'initial.json').write_text(initial, encoding='utf-8')
    started = perf_counter()
    def accepted(plan, entry):
        plans.append(plan)
        progress.append(entry)
    def observe(state, event):
        recorder.observe(state, event)
        if event.event_type.value == 'plan_completed':
            row = {'plans': len(plans), 'completed_gates': state.metrics()['completed_gate_count'],
                'total_gates': len(prefix.circuit.gates), 'simulation_time_us': state.time_us,
                'wall_seconds': perf_counter() - started}
            save('progress.json', row)
            print(canonical_json(row), flush=True)
    error, result = None, None
    try:
        result = run_parallel_patch(env, atom_roles=metadata['atom_roles'], on_event=observe,
            on_plan=accepted, max_decisions=args.max_decisions, wall_budget_s=args.wall_budget)
        if result.status != 'completed':
            error = {'type': 'CompilationStalled', 'diagnostics': result.diagnostics}
    except Exception as exc:
        error = {'type': type(exc).__name__, 'message': str(exc)}
    replay_equal = None
    if not args.skip_replay:
        try:
            replay = NeutralAtomEnv.restore(initial)
            for plan in plans:
                replay.submit(plan)
                replay.run()
            replay_equal = replay.snapshot() == env.snapshot()
            if not replay_equal:
                raise AssertionError('Independent original-initial-state plan replay differs')
        except Exception as exc:
            replay_equal = False
            error = error or {'type': type(exc).__name__, 'message': str(exc)}
    records = [json.loads(row) for row in env.state.trace.records]
    effects = Counter(gid for row in records if row.get('effect_completed') for gid in
        (row.get('effect_gate_ids') or ([row['effect_gate_id']] if row.get('effect_gate_id') else [])))
    expected_effects = Counter(g.id for g in prefix.circuit.gates)
    binding = dict(prefix.bindings)
    code = prefix.source['roles']
    expectations = []
    for patch in prefix.patches:
        for kind in ('X', 'Z'):
            for support in code['code_checks'][kind]:
                expectations.append(env.state.quantum_state.expectation({binding[f'{patch}.d{i}']: kind for i in support}))
        expectations.append(env.state.quantum_state.expectation({binding[f'{patch}.d{i}']: 'Z' for i in code['logical_Z']}))
        for kind in ('X', 'Z'):
            for i in range(4):
                expectations.append(env.state.quantum_state.expectation({binding[f'{patch}.{kind}{i}']: 'Z'}))
    audit = {'effects_exactly_once': effects == expected_effects,
        'dag_complete': env.state.dag.completed, 'event_queue_empty': not env.pending,
        'all_output_code_logical_zero_and_aux_checks_plus_one': all(v == 1 for v in expectations),
        'independent_plan_replay_equal': replay_equal,
        'all_saved_report_ids_preserved': set(env.state.measurement_results) ==
            {g.id for g in prefix.circuit.gates if g.gate_type == 'MEASURE'}}
    if prefix.source.get('resource_clifford_prefix_included'):
        audit['same_source_resource_carriers_before_first_t'] = (
            env.state.quantum_state.expectation({binding['resource.d0']: 'X'}) == 1 and
            all(env.state.quantum_state.expectation({binding[f'resource.d{i}']: 'Z'}) == 1 for i in range(1, 9)) and
            all(env.state.quantum_state.expectation({binding[f'resource.{kind}{i}']: 'Z'}) == 1
                for kind in ('X', 'Z') for i in range(4)))
    if not error and not all(value for value in audit.values() if value is not None):
        error = {'type': 'AcceptanceFailure', 'audit': audit}
    summary = {'schema': 'parallel-shor15-prefix-physical-run/1',
        'status': 'failed' if error else 'completed', 'error': error,
        'source_manifest_sha256': prefix.source['source_manifest_sha256'],
        'source_native_prefix_sha256': prefix.source['selected_native_prefix_sha256'],
        'patch_count': len(prefix.patches), 'physical_atom_count': len(env.state.atoms),
        'native_gate_count': len(prefix.circuit.gates), 'native_gate_counts': prefix.source['gate_counts'],
        'native_projection_count': len(prefix.source['original_native_projections']),
        'aod_count': len(env.state.aods), 'declared_research_model': {'slm_grid_um': 5,
            'occupied_subset_pitch_um': 10, 'finite_cz_distance_um': 6,
            'global_actual_pairs_equal_intended': True, 'compute_separate_storage_zone': False,
            'actual_mz_readout_reset': True},
        'plans': len(plans), 'wall_seconds': perf_counter() - started,
        'simulation_time_us': env.state.time_us, 'metrics': env.state.metrics(), 'audit': audit,
        'maximum_batch_size': max((row['batch_size'] for row in progress), default=0),
        'maximum_actual_cz_batch_size': max((row['batch_size'] for row in progress if row['kind'] == 'CZ'), default=0),
        'physical_prefix_executed': not bool(error), 'complete_physical_shor_executed': False,
        'magic_state_preparation_executed': False, 'factory_or_noise_claimed': False,
        'resource_clifford_prefix_included': prefix.source.get('resource_clifford_prefix_included', False),
        'scope': 'Saved all-zero RESET/CSS and first canonical round on selected algorithm patches; optional actual first resource RESET/H prefix stops immediately before its T'}
    save('summary.json', summary)
    save('plans.json', plans)
    save('decisions.json', getattr(result, 'decision_log', progress))
    (output / 'checkpoint-final.json').write_text(env.snapshot(), encoding='utf-8')
    env.state.trace.write(output / 'trace.jsonl')
    save('recording.json', recorder.payload())
    recorder.write(output / 'animation.html')
    print(canonical_json(summary), flush=True)
    return 1 if error else 0


if __name__ == '__main__':
    raise SystemExit(main())
