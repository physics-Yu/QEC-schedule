"""Step 4A: one sequential, budgeted matrix. A failure never launches a retry."""
import argparse
from collections import Counter
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
CASES = ('edited_clifford', 'fault_x14_seed23', 'staggered_patches')
ATTEMPT = 1


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def input_for(case):
    from neutral_atom_experiments.surface_qec import experiment_input
    if case == 'staggered_patches':
        value = json.loads((ROOT / 'artifacts/qec-roadmap/baseline-input.json').read_text(encoding='utf-8'))
        value.update(compiler='qec_joint', qec_patch_origins=[[0, 0], [45, 5]],
                     aod_rows=8, aod_traps=112, aod_row_offsets_um=list(range(0, 36, 5)),
                     aod_column_offsets_um=list(range(0, 31, 5)) + list(range(45, 76, 5)))
        return value
    value = experiment_input({'pauli': 'X', 'qubit_id': 'Q014'} if case == 'fault_x14_seed23' else None,
                             compiler='qec_joint')
    value['seed'] = 23 if case == 'fault_x14_seed23' else 11
    if case == 'edited_clifford':
        pairs = [('H', ['Q000']), ('H', ['Q009']), ('CZ', ['Q000', 'Q009']),
                 ('H', ['Q009']), ('CZ', ['Q000', 'Q009']), ('X', ['Q001'])]
        value['gates'] = [dict(id=f'EDIT{i}', gate_type=kind, qubit_ids=qs, parameters=[], column=i)
                          for i, (kind, qs) in enumerate(pairs)]
    return value


def sources():
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((ROOT / 'src').rglob('*')) if p.suffix in {'.py', '.js', '.html'}}


def compile_case(case, output):
    from neutral_atom_app.visualization.workbench import build_inputs
    from neutral_atom_env.platform import initialize
    from neutral_atom_strategies.scheduling.qec_joint import run_qec_joint
    from neutral_atom_strategies.scheduling.m3 import initial_terminal
    from neutral_atom_env.program.task_validation import validate_target
    from neutral_atom_env.quantum.stabilizer import StabilizerState
    from neutral_atom_experiments.surface_qec import summarize
    from neutral_atom_env.replay.checkpoint import restore
    from neutral_atom_env.replay.serializer import canonical_json, primitive
    from neutral_atom_env.visualization import VisualRecorder
    from neutral_atom_env.visualization.viewer import write_html

    output.mkdir(parents=True, exist_ok=False)
    dump(output / 'attempt.json', {'stage': '4A', 'case': case, 'attempt': ATTEMPT,
         'started_at': datetime.now(timezone.utc).isoformat(), 'compile_budget_seconds': 600,
         'expected_protocol': 'not_GHZ' if case == 'edited_clifford' else 'GHZ2', 'retry_authorized': False})
    raw = input_for(case)
    dump(output / 'submitted-input.json', raw)
    value, circuit, platform, placement = build_inputs(raw)
    state = initialize(circuit, platform, placement, seed=value['seed'])
    state = replace(state, quantum_state=StabilizerState.zero(tuple(sorted(state.atoms))))
    terminal = initial_terminal(state)
    recorder = VisualRecorder(state)
    before = sources()
    dump(output / 'input.json', value)
    dump(output / 'strategy.json', {'actual_strategy': 'qec_joint', 'attempt': ATTEMPT, 'case': case})
    (output / 'last-committed-checkpoint.json').write_text(state.snapshot(), encoding='utf-8')
    started = perf_counter()
    saved_count = [-1]

    def observe(s, event):
        recorder.observe(s, event)
        if event.event_type.value != 'plan_completed':
            return
        count = s.metrics()['completed_gate_count']
        progress = dict(case=case, completed_gates=count, total_gates=len(circuit.gates),
                        simulation_time_us=s.time_us, elapsed_seconds=perf_counter() - started)
        dump(output / 'progress.json', progress)
        if count - saved_count[0] >= 40 or count == len(circuit.gates):
            (output / 'last-committed-checkpoint.json').write_text(s.snapshot(), encoding='utf-8')
            dump(output / 'last-committed-progress.json', progress)
            saved_count[0] = count

    result = None
    error = None
    try:
        result = run_qec_joint(state, on_event=observe, terminal=terminal)
        assert result.status == 'completed', str(result.diagnostics)
        validate_target(terminal, state)
        report = summarize(state)
        if case == 'edited_clifford':
            expected = StabilizerState.zero(tuple(sorted(state.atoms)))
            for gate in circuit.gates:
                expected = expected.apply_gate(gate.gate_type, gate.qubit_ids, gate.parameters)
            assert state.quantum_state == expected, 'Edited Clifford quantum state differs from independent ordered circuit'
            # H_a H_b CZ H_b CZ prepares Phi-minus; the independent X sets q1=1.
            assert state.quantum_state.expectation({'Q000': 'X', 'Q009': 'X'}) == -1
            assert state.quantum_state.expectation({'Q000': 'Z', 'Q009': 'Z'}) == 1
            assert state.quantum_state.expectation({'Q001': 'Z'}) == -1
            assert all(state.quantum_state.expectation({q: 'Z'}) == 1 for q in state.atoms
                       if q not in {'Q000', 'Q001', 'Q009'})
            assert not report['measurement_protocol_complete'], 'Short edited circuit is not the full protocol'
        else:
            assert report['verified_logical_ghz2'] and report['measurement_protocol_complete'], 'GHZ2/protocol failed'
        effects = Counter(g for raw_record in state.trace.records for r in [json.loads(raw_record)]
                          if r.get('effect_completed') for g in (r.get('effect_gate_ids') or [r['effect_gate_id']]))
        assert effects == Counter(g.id for g in circuit.gates), 'Effects are not exactly once'
        assert restore(state.snapshot()).snapshot() == state.snapshot(), 'Checkpoint differs after restore'
        assert before == sources(), 'Source changed during formal compile'
    except Exception as exc:
        error = {'code': type(exc).__name__, 'message': str(exc)}
    elapsed = perf_counter() - started
    payload = recorder.payload()
    payload['scene']['atom_roles'] = value.get('qec_protocol', {}).get('atom_roles', {})
    (output / 'checkpoint.json').write_text(state.snapshot(), encoding='utf-8')
    (output / 'trace.jsonl').write_text('\n'.join(state.trace.records) + '\n', encoding='utf-8')
    for name, data in [('recording', payload), ('qec_result', summarize(state)),
                       ('result', {'status': 'failed' if error else 'checks_passed_replay_pending',
                         'actual_strategy': 'qec_joint', 'case': case, 'error': error,
                         'compile_seconds': elapsed, 'metrics': state.metrics()}),
                       ('diagnostics', primitive(getattr(result, 'diagnostics', ()))),
                       ('decisions', primitive(getattr(result, 'decision_log', ()))),
                       ('candidate_rejections', primitive(getattr(result, 'candidate_rejections', ()))),
                       ('source-stability', {'changed_during_run': before != sources()})]:
        dump(output / f'{name}.json', data)
    write_html(payload, output / 'index.html')
    print(canonical_json({'case': case, 'error': error, 'compile_seconds': elapsed, 'metrics': state.metrics()}), flush=True)
    return 1 if error else 0


def verify_case(case, output):
    if case != 'edited_clifford':
        from verify_surface_qec import verify
        verify(output)
        return 0
    from neutral_atom_app.visualization.workbench import build_inputs
    from neutral_atom_env.platform import initialize
    from neutral_atom_env.simulation import Executor
    from neutral_atom_env.quantum.stabilizer import StabilizerState
    from neutral_atom_env.replay.operation_codec import event_from_dict
    value, circuit, platform, placement = build_inputs(json.loads((output / 'input.json').read_text(encoding='utf-8')))
    state = initialize(circuit, platform, placement, seed=value['seed'])
    state = replace(state, quantum_state=StabilizerState.zero(tuple(sorted(state.atoms))))
    plans = 0
    for line in (output / 'trace.jsonl').read_text(encoding='utf-8').splitlines():
        event = event_from_dict(json.loads(line)['event'])
        if event.event_type.value == 'plan_started':
            Executor(state).submit(event.plan)
            Executor(state).run()
            plans += 1
    assert state.snapshot() == (output / 'checkpoint.json').read_text(encoding='utf-8')
    dump(output / 'verification.json', {'compiler_free_replay': 'PASS', 'plans': plans,
         'exact_snapshot': True, 'expected_non_GHZ_protocol': True})
    return 0


def matrix(output):
    from qec_roadmap_status import update
    output.mkdir(parents=True, exist_ok=False)
    results = []
    for case in CASES:
        directory = output / case
        for mode in ('compile', 'verify'):
            print(json.dumps({'case': case, 'phase': mode, 'status': 'started'}), flush=True)
            try:
                run = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--mode', mode,
                                      '--case', case, '--output', str(directory), '--attempt', str(ATTEMPT)], cwd=ROOT,
                                     capture_output=True, text=True, encoding='utf-8', timeout=600)
                text = run.stdout + run.stderr
                code = run.returncode
            except subprocess.TimeoutExpired as exc:
                text = 'DECLARED_600_SECOND_BUDGET_EXCEEDED\n'
                for chunk in (exc.stdout, exc.stderr):
                    text += chunk.decode('utf-8', errors='replace') if isinstance(chunk, bytes) else chunk or ''
                code = 124
            directory.mkdir(parents=True, exist_ok=True)
            (directory / f'{mode}-output.txt').write_text(text, encoding='utf-8')
            if code:
                progress = json.loads((directory / 'progress.json').read_text()) if (directory / 'progress.json').exists() else {}
                failure = {'facts': [f'第四步4A首次矩阵 {case} / {mode} 未通过，exit={code}。',
                           '实际最后进度：' + json.dumps(progress, ensure_ascii=False),
                           '未自动修复或重试；后续矩阵、重复纠错及四逻辑扩展停止。'],
                           'hypotheses': ['待只读诊断错误记录，区分几何/有限搜索、量子协议、输入或实现一致性；预算失败不证明物理无解。'],
                           'proposed_retry_scope': ['保留本次证据，提出具体修正与复验范围后，由用户在对话批准下一attempt。']}
                dump(output / 'failure.json', failure)
                update(ROOT / 'artifacts/qec-roadmap/status.json', 'step4', 'fail', failure=failure,
                       evidence=[{'label': f'矩阵失败：{case}/{mode}', 'path': str((directory / f'{mode}-output.txt').relative_to(ROOT / 'artifacts/qec-roadmap')).replace('\\','/')}])
                print(json.dumps({'status': 'failed', 'case': case, 'phase': mode, 'exit_code': code}), flush=True)
                return 1
            print(json.dumps({'case': case, 'phase': mode, 'status': 'passed'}), flush=True)
        results.append({'case': case, 'status': 'passed', 'result': str(directory / 'result.json')})
        dump(output / 'matrix.json', {'status': 'running', 'cases': results})
    dump(output / 'matrix.json', {'status': 'passed', 'cases': results})
    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=('matrix', 'compile', 'verify'), default='matrix')
    parser.add_argument('--case', choices=CASES)
    parser.add_argument('--attempt', type=int, default=1)
    parser.add_argument('--output', default=str(ROOT / 'artifacts/qec-roadmap/step4-attempt1-matrix'))
    args = parser.parse_args()
    ATTEMPT = args.attempt
    function = matrix if args.mode == 'matrix' else compile_case if args.mode == 'compile' else verify_case
    raise SystemExit(function(Path(args.output)) if args.mode == 'matrix' else function(args.case, Path(args.output)))
