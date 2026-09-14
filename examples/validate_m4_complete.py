"""Same-platform M4 comparisons, real execution and compiler-free replay.

Run from the repository root. Partial runs remain explicitly marked running;
no prior PASS is reused. This is a finite regression matrix, not optimality proof.
"""
import argparse
import hashlib
import json
from pathlib import Path
import platform as runtime_platform
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from neutral_atom_env.replay.serializer import canonical_json, primitive
from neutral_atom_env.simulation.m3 import initial_terminal
from neutral_atom_env.simulation.m4 import run_m4
from neutral_atom_env.simulation.pipeline import initialize
from neutral_atom_env.visualization import VisualRecorder
from neutral_atom_env.visualization.workbench import build_inputs, failure_report
from verify_m3 import verify

STRATEGIES = ('basic', 'greedy', 'critical_path', 'lookahead')


def circuit(gates, *, count=4, layout='row', seed=7):
    return {'compiler': 'greedy', 'atom_count': count, 'layout': layout, 'seed': seed,
            'ez_policy': 'adaptive', 'aod_traps': 1, 'anchor_order': 'forward',
            'gates': [{'id': f'G{i:03d}', 'gate_type': kind,
                       'qubit_ids': [f'Q{q:03d}' for q in qubits],
                       'parameters': [], 'column': i}
                      for i, (kind, qubits) in enumerate(gates)]}


def cases():
    return {
        'parallel': circuit([('H', (i,)) for i in range(4)]),
        'reuse': circuit([('CZ', (0, 1)), ('CZ', (0, 1)), ('CZ', (0, 1)), ('H', (3,))]),
        'critical_branch': circuit([('CZ', (2, 3)), ('CZ', (0, 1)), ('H', (0,)),
                                    ('CZ', (0, 1)), ('T', (0,))]),
        'critical_priority': circuit([('CZ', (0, 1)), ('CZ', (2, 3)),
                                      ('CZ', (2, 3)), ('H', (2,))]),
        'occupancy': circuit([('CZ', (0, 1)), ('H', (0,)), ('CZ', (0, 2)), ('T', (0,)),
                              ('CZ', (1, 3)), ('X', (1,)), ('CZ', (4, 5)), ('T', (4,))],
                             count=6, layout='shuffled'),
    }


def digest(value):
    return hashlib.sha256(canonical_json(value).encode('utf-8')).hexdigest()


def source_fingerprint():
    files = sorted((ROOT / 'src' / 'neutral_atom_env').rglob('*.py'))
    return digest({str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files})


def dump(directory, name, value):
    (directory / f'{name}.json').write_text(canonical_json(value), encoding='utf-8')


def run_case(raw, strategy, directory, *, max_decisions=100, site_limit=1,
             ready_limit=8, lookahead_depth=2, beam_width=2, rollout_budget=8):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'verification.json').unlink(missing_ok=True)
    dump(directory, 'result', {'status': 'running'})
    (directory/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>M4 compiling</title>'
                                       '<p>本轮正在编译，尚未验收。</p>', encoding='utf-8')
    value, circuit_value, hardware, placement = build_inputs(raw)
    state = initialize(circuit_value, hardware, placement, seed=value['seed'])
    terminal = initial_terminal(state)
    initial_sha = hashlib.sha256(state.snapshot().encode('utf-8')).hexdigest()
    terminal_sha = digest(terminal)
    options = {'strategy': strategy, 'max_decisions': max_decisions, 'ready_limit': ready_limit,
               'site_limit': site_limit, 'adaptive_sites': value.get('ez_policy') == 'adaptive',
               'lookahead_depth': lookahead_depth, 'beam_width': beam_width, 'rollout_budget': rollout_budget}
    # The exported editor input uses the actual policy; strategy is not geometry.
    value['compiler'] = strategy
    value.update({k: options[k] for k in ('max_decisions', 'ready_limit', 'site_limit',
                                         'lookahead_depth', 'beam_width', 'rollout_budget')})
    dump(directory, 'input', value)
    dump(directory, 'terminal', terminal)
    dump(directory, 'run_options', options)
    recorder = VisualRecorder(state)
    started = perf_counter()
    result = run_m4(state, terminal=terminal, on_event=recorder.observe, **options)
    compile_seconds = perf_counter() - started
    recording = recorder.payload()
    metrics = state.metrics()
    for name, data in [('recording', recording), ('decisions', result.decision_log),
                       ('diagnostics', result.diagnostics), ('candidate_rejections', result.candidate_rejections),
                       ('failure_report', failure_report(result, state, value)),
                       ('result', primitive(result) | {'metrics': metrics, 'compile_seconds': compile_seconds})]:
        dump(directory, name, data)
    (directory / 'checkpoint.json').write_text(state.snapshot(), encoding='utf-8')
    (directory / 'trace.jsonl').write_text('\n'.join(state.trace.records) + '\n', encoding='utf-8')
    recorder.write(directory / 'index.html')
    verify(directory)  # Replays supplied plans; never calls a compiler.
    searches = [s for d in result.decision_log for s in d.get('search', [])]
    policies = [d.get('policy_search', {}) for d in result.decision_log]
    row = {'case': directory.parent.name, 'strategy': strategy, 'status': result.status,
           'initial_sha256': initial_sha, 'terminal_sha256': terminal_sha,
           'compile_seconds': compile_seconds, 'makespan_us': state.time_us,
           'logical_completion_us': metrics['logical_completion_elapsed_us'],
           'completed_gates': metrics['completed_gate_count'], 'loads': metrics['aod_load_count'],
           'offloads': metrics['aod_offload_count'], 'operations': len(recording['operations']),
           'legal_candidates': sum(len(d.get('candidates', [])) for d in result.decision_log),
           'attempted_candidates': sum(s.get('attempted', 0) for s in searches),
           'omitted_candidates': sum(s.get('omitted', 0) for s in searches),
           'rollout_nodes': sum(s.get('nodes_used', 0) for s in policies),
           'rollout_budget_exhausted': any(s.get('budget_exhausted', False) for s in policies),
           'budgets': options, 'metrics': metrics,
           'resource_utilization': {r: busy/state.time_us if state.time_us else 0
                                    for r, busy in recording['summary']['resource_busy_us'].items()},
           'verification': 'verified'}
    dump(directory, 'comparison', row)
    print(canonical_json({k: row[k] for k in ('case', 'strategy', 'status', 'makespan_us',
                                              'loads', 'compile_seconds', 'rollout_nodes')}), flush=True)
    return row


def audit_comparisons(rows, *, require_complete=True):
    grouped = {}
    for row in rows:
        grouped.setdefault(row['case'], {})[row['strategy']] = row
        assert row['verification'] == 'verified'
    for name, group in grouped.items():
        assert len({r['initial_sha256'] for r in group.values()}) == 1, f'{name}: unequal initial state'
        assert len({r['terminal_sha256'] for r in group.values()}) == 1, f'{name}: unequal terminal'
        if require_complete:
            assert set(group) == set(STRATEGIES), f'{name}: incomplete policy matrix'
        assert all(r['status'] == 'completed' for r in group.values()), f'{name}: incomplete physical run'
    evidence = {'reuse_benefits': [], 'greedy_counterexamples': [], 'lookahead_counterexamples': []}
    for name, group in grouped.items():
        if 'parallel' == name:
            assert all(abs(r['makespan_us'] - 1) < 1e-8 for r in group.values()), 'Four H must share 1 us'
        basic, greedy, ahead = (group.get(s) for s in ('basic', 'greedy', 'lookahead'))
        if basic and greedy and greedy['makespan_us'] < basic['makespan_us'] - 1e-8:
            evidence['reuse_benefits'].append(name)
        if greedy:
            better = [s for s, r in group.items() if r['makespan_us'] < greedy['makespan_us'] - 1e-8]
            if better: evidence['greedy_counterexamples'].append({'case': name, 'better': better})
        if ahead:
            better = [s for s, r in group.items() if r['makespan_us'] < ahead['makespan_us'] - 1e-8]
            if better: evidence['lookahead_counterexamples'].append({'case': name, 'better': better})
    return evidence


def terminal_witness(output):
    """Equal local movement may leave a different cost for the next demand.

    Choose two explicit physical plans, execute both plus the same remaining
    gate and exact return, then independently replay each complete trace.
    """
    from neutral_atom_env.domain.operations import TaskIntent
    from neutral_atom_env.motion.greedy import GreedyCompiler
    from neutral_atom_env.simulation import Executor
    raw = circuit([('CZ', (0, 1)), ('CZ', (0, 2))])
    keys = ('G000/Q000/right/EZ_0_25', 'G000/Q000/left/EZ_15_25')
    rows = []
    for index, key in enumerate(keys):
        directory = Path(output) / f'candidate-{index}'
        directory.mkdir(parents=True, exist_ok=True)
        (directory/'verification.json').unlink(missing_ok=True)
        dump(directory, 'result', {'status': 'running'})
        (directory/'index.html').write_text('<!doctype html><meta charset="utf-8"><p>本轮正在编译，尚未验收。</p>', encoding='utf-8')
        value, c, p, h = build_inputs(raw)
        state = initialize(c, p, h, seed=value['seed'])
        terminal = initial_terminal(state)
        recorder = VisualRecorder(state)
        compiler = GreedyCompiler(adaptive_sites=True)
        executor = Executor(state)

        def execute(plan):
            executor.submit(plan)
            while state.event_queue:
                event = executor.step()
                recorder.observe(state, event)

        choices, _, _ = compiler.alternatives('G000', state, site_limit=4)
        first = next(choice for choice in choices if choice.key == key)
        execute(first.plan)
        after_first = initial_terminal(state)
        second_choices, _, _ = compiler.alternatives('G001', state, site_limit=1)
        second = min(second_choices, key=lambda choice: choice.cost)
        execute(second.plan)
        closure = compiler.compile(TaskIntent('witness-exact-exit', terminal), state)
        execute(closure)
        for name, data in [('input', value), ('terminal', terminal), ('recording', recorder.payload()),
                           ('result', {'status': 'completed', 'metrics': state.metrics()})]:
            dump(directory, name, data)
        (directory/'checkpoint.json').write_text(state.snapshot(), encoding='utf-8')
        (directory/'trace.jsonl').write_text('\n'.join(state.trace.records)+'\n', encoding='utf-8')
        recorder.write(directory/'index.html')
        verify(directory)
        rows.append({'candidate': key, 'local_distance_um': first.cost[2], 'local_duration_us': first.cost[0],
                     'end_state': primitive(after_first), 'next_service_us': second.cost[0],
                     'next_candidate': second.key, 'terminal_cleanup_us': closure.estimated_duration_us,
                     'complete_makespan_us': state.time_us, 'verification': 'verified'})
    assert abs(rows[0]['local_distance_um']-rows[1]['local_distance_um']) < 1e-8
    assert abs(rows[0]['local_duration_us']-rows[1]['local_duration_us']) < 1e-8
    assert rows[0]['end_state'] != rows[1]['end_state']
    assert abs(rows[0]['next_service_us']-rows[1]['next_service_us']) > 1e-8
    dump(Path(output), 'witness', rows)
    return rows


def diagnostics_witness(output):
    """A filled node budget is different from an actually truncated search."""
    output = Path(output)
    exact = run_case(circuit([('H', (0,))], count=1), 'lookahead', output/'exact'/'lookahead',
                     beam_width=1, rollout_budget=1)
    cut = run_case(cases()['reuse'], 'lookahead', output/'truncated'/'lookahead',
                   max_decisions=1, beam_width=2, rollout_budget=1)
    read = lambda name: json.loads((output/name/'lookahead'/'decisions.json').read_text(encoding='utf-8'))[0]['policy_search']
    exact_search, cut_search = read('exact'), read('truncated')
    assert exact['status'] == 'completed' and exact_search['limit_reached']
    assert not exact_search['budget_exhausted'], 'Exhausting exactly a complete tree is not truncation'
    assert cut['status'] == 'stalled' and cut_search['budget_exhausted']
    assert cut_search['nodes_used'] <= cut_search['node_budget'] == 1
    report = {'status': 'verified', 'source_sha256': source_fingerprint(),
              'exact': exact_search, 'truncated': cut_search,
              'note': 'Independent complete and truncated runs using the final diagnostic implementation.'}
    dump(output, 'acceptance', report)
    return report


def normalize_exports(output):
    """Synchronize editor search knobs with recorded options, without recompiling.

    This migration only repairs exported metadata from earlier runs of this
    generator. Saved operations, clocks, checkpoints and recordings are untouched.
    """
    changed = []
    for options_path in sorted(Path(output).rglob('run_options.json')):
        directory = options_path.parent
        options = json.loads(options_path.read_text(encoding='utf-8'))
        value = json.loads((directory/'input.json').read_text(encoding='utf-8'))
        corrected = value | {k: options[k] for k in ('max_decisions', 'ready_limit', 'site_limit',
                                                     'lookahead_depth', 'beam_width', 'rollout_budget')}
        if corrected != value:
            dump(directory, 'input', corrected)
            changed.append(str(directory))
    previous = Path(output)/'export_metadata_correction.json'
    earlier = json.loads(previous.read_text(encoding='utf-8')).get('changed', []) if previous.exists() else []
    dump(Path(output), 'export_metadata_correction', {'changed': sorted(set(earlier + changed)),
         'fields': ['ready_limit', 'site_limit'], 'physical_data_changed': False})
    return changed


def finalize_existing(output):
    """Attach final diagnostic evidence and repair old exported search metadata."""
    output = Path(output)
    normalize_exports(output)
    manifest = json.loads((output/'acceptance.json').read_text(encoding='utf-8'))
    assert manifest['status'] == 'verified'
    audit_comparisons(manifest['rows'])
    choices = {policy: json.loads((output/'critical_priority'/policy/'decisions.json').read_text(encoding='utf-8'))[0]['selected']
               for policy in ('greedy', 'critical_path')}
    assert choices['greedy'].startswith('G000/') and choices['critical_path'].startswith('G001/')
    manifest['priority_witness'] = choices
    manifest['diagnostic_witness'] = json.loads((output/'diagnostics-final'/'acceptance.json').read_text(encoding='utf-8'))
    manifest['source_change_note'] = (
        'The physical matrix was compiled by one process at source_sha256. During its run a diagnostic-only '
        'patch separated limit_reached from true budget_exhausted and retained all-root failure reports. '
        'Candidates, scores, quotas, ordering and execution plans were unchanged. Final diagnostics have '
        'a separate source fingerprint and real replay in diagnostic_witness. The matrix was not wholly '
        'recompiled after that patch. Exported ready_limit/site_limit were synchronized from run_options; '
        'checkpoints, traces, recordings and physical timing were not modified.')
    dump(output, 'acceptance', manifest)
    return {'status': manifest['status'], 'rows': len(manifest['rows']), 'priority_witness': choices,
            'source_changed_during_run': manifest['source_changed_during_run']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='artifacts/m4-complete')
    parser.add_argument('--cases', nargs='+', choices=list(cases()), default=list(cases()))
    parser.add_argument('--strategies', nargs='+', choices=STRATEGIES, default=list(STRATEGIES))
    parser.add_argument('--site-limit', type=int, default=1)
    parser.add_argument('--beam-width', type=int, default=2)
    parser.add_argument('--rollout-budget', type=int, default=8)
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    fingerprint = source_fingerprint()
    manifest = {'status': 'running', 'python': runtime_platform.python_version(),
                'source_sha256': fingerprint, 'arguments': vars(args), 'rows': []}
    dump(output, 'acceptance', manifest)
    for name in args.cases:
        for strategy in args.strategies:
            row = run_case(cases()[name], strategy, output/name/strategy,
                           site_limit=args.site_limit, beam_width=args.beam_width, rollout_budget=args.rollout_budget)
            manifest['rows'].append(row)
            dump(output, 'acceptance', manifest)
    full = set(args.strategies) == set(STRATEGIES)
    evidence = audit_comparisons(manifest['rows'], require_complete=full)
    if full and set(args.cases) == set(cases()):
        assert evidence['reuse_benefits'], 'Full acceptance requires measured reuse benefit'
        assert evidence['greedy_counterexamples'], 'Full acceptance must retain a greedy counterexample'
    failure = run_case(cases()['reuse'], 'lookahead', output/'budget_failure'/'lookahead',
                       max_decisions=1, site_limit=args.site_limit, beam_width=args.beam_width,
                       rollout_budget=args.rollout_budget)
    assert failure['status'] == 'stalled' and 0 < failure['completed_gates'] < len(cases()['reuse']['gates'])
    manifest.update(status='verified', evidence=evidence, budget_failure=failure,
                    equal_distance_terminal_witness=terminal_witness(output/'terminal_witness'),
                    diagnostic_witness=diagnostics_witness(output/'diagnostics-final'),
                    source_sha256_end=source_fingerprint(),
                    scope='Finite same-platform matrix. No global optimality or arbitrary-circuit completeness claim.')
    manifest['source_changed_during_run'] = manifest['source_sha256_end'] != fingerprint
    dump(output, 'acceptance', manifest)
    print(canonical_json({'status': manifest['status'], 'rows': len(manifest['rows']), 'evidence': evidence}), flush=True)


if __name__ == '__main__':
    main()
