"""Resume an explicitly reviewed 4C run; independently replay its entire trace.

This driver never recompiles a committed prefix, retries a failed phase, or
modifies the parent evidence. Source changes between attempts are recorded;
source changes during this attempt are rejected. Run only after the parent
process has stopped and its failure has been classified.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import shutil
from time import perf_counter

from run_qec_temporal_four_acceptance import ROOT, check_final, dump, sources

PHASE_BUDGET_SECONDS = 3600
PARSED_EVENT_BUDGET = 16384
TOTAL_PLAN_BUDGET = 10000


def digest(data):
    return hashlib.sha256(data).hexdigest()


def file_digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write_trace(path, records):
    with path.open('w', encoding='utf-8', newline='\n') as stream:
        for record in records:
            stream.write(record)
            stream.write('\n')


def cache_stats():
    from neutral_atom_env.replay.snapshot_encoding import TRACE_CACHE
    from neutral_atom_env.replay.trace import _event_data
    result = {'parser': _event_data.cache_info()._asdict(), 'encoding': TRACE_CACHE.stats()}
    if sys.platform == 'win32':
        import ctypes
        from ctypes import wintypes
        class MemoryCounters(ctypes.Structure):
            _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD)] + [
                (name, ctypes.c_size_t) for name in ('PeakWorkingSetSize', 'WorkingSetSize',
                'QuotaPeakPagedPoolUsage', 'QuotaPagedPoolUsage', 'QuotaPeakNonPagedPoolUsage',
                'QuotaNonPagedPoolUsage', 'PagefileUsage', 'PeakPagefileUsage')]
        counter = MemoryCounters()
        counter.cb = ctypes.sizeof(counter)
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        psapi = ctypes.WinDLL('psapi', use_last_error=True)
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(MemoryCounters), wintypes.DWORD]
        if psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counter), counter.cb):
            result['process_memory'] = {'working_set_bytes': counter.WorkingSetSize,
                                       'peak_working_set_bytes': counter.PeakWorkingSetSize}
    return result


def boundary(state):
    return (not state.event_queue and state.active_plan is None
            and state.transfer is None and not state.reservations
            and (not state.trace.records or
                 json.loads(state.trace.records[-1])['event']['event_type'] == 'plan_completed'))


def original_input(parent):
    from neutral_atom_app.visualization.workbench import build_inputs, initialize_input
    raw = read_json(parent / 'input.json')
    value, circuit, platform, placement = build_inputs(raw)
    assert value == raw, 'Original normalized input changed under the current API'
    assert value['compiler'] == 'qec_temporal_four'
    state = initialize_input(value, circuit, platform, placement)
    return value, circuit, state


def static_identity(state):
    from neutral_atom_env.replay.serializer import primitive
    configuration = state.aod.configuration()
    # The rigid array may have moved; its relative geometry must not change.
    return primitive({
        'world': state.world, 'hardware': state.hardware,
        'circuit': state.dag.circuit, 'atom_ids': tuple(sorted(state.atoms)),
        'seed': state.seed,
        'aod_x_offsets': tuple(x - configuration.x_um[0] for x in configuration.x_um),
        'aod_y_offsets': tuple(y - configuration.y_um[0] for y in configuration.y_um),
        'quantum_ids': state.quantum_state.qubit_ids if state.quantum_state else None,
    })


def select_checkpoint(parent):
    from neutral_atom_env.replay.checkpoint import restore
    rejected = []
    for name in ('checkpoint.json', 'last-committed-checkpoint.json'):
        path = parent / name
        if not path.exists():
            rejected.append({'file': name, 'reason': 'not present'})
            continue
        # A malformed checkpoint is not silently bypassed as an ordinary timeout.
        state = restore(path.read_text(encoding='utf-8'))
        if boundary(state):
            return path, state, rejected
        rejected.append({'file': name, 'reason': 'not a complete plan boundary'})
    raise AssertionError(f'No committed plan boundary: {rejected}')


def inputs_unchanged(output):
    provenance = read_json(output / 'resume-provenance.json')
    for entry in provenance['parent_files']:
        assert file_digest(Path(entry['path'])) == entry['sha256'], entry['path']
    assert file_digest(output / 'input.json') == provenance['input_sha256']


def resume_case(output, parent, attempt, classification, review_note):
    from neutral_atom_strategies.scheduling.m3 import initial_terminal
    from neutral_atom_env.program.task_validation import validate_target
    from neutral_atom_experiments.runners.qec_temporal_four import run_qec_temporal_four
    from neutral_atom_env.replay.serializer import primitive
    from neutral_atom_env.replay.trace import _event_data
    from neutral_atom_experiments.surface_qec_temporal_four import summarize
    from neutral_atom_env.domain.errors import ValidationError

    value, circuit, initial = original_input(parent)
    terminal = initial_terminal(initial)
    checkpoint_path, state, skipped = select_checkpoint(parent)
    assert static_identity(state) == static_identity(initial), 'Checkpoint input/platform identity mismatch'
    prefix = tuple(state.trace.records)
    prefix_plans = sum(json.loads(line)['event']['event_type'] == 'plan_started' for line in prefix)
    remaining_plans = TOTAL_PLAN_BUDGET - prefix_plans
    assert remaining_plans > 0, 'No remaining declared plan budget'
    terminal_satisfied = True
    try:
        validate_target(terminal, state)
    except ValidationError:
        terminal_satisfied = False
    already_finished = state.dag.completed and terminal_satisfied
    prefix_snapshot_sha256 = digest(state.snapshot().encode('utf-8'))
    before = sources()
    old_sources = read_json(parent / 'source-start.json')
    source_delta = {name: {'parent': old_sources.get(name), 'resume': before.get(name)}
                    for name in sorted(set(old_sources) | set(before))
                    if old_sources.get(name) != before.get(name)}
    provenance_paths = [p for p in (parent / 'input.json', checkpoint_path,
                        parent / 'source-start.json', parent / 'result.json',
                        parent / 'failure.json', parent / 'last-committed-progress.json') if p.exists()]
    (output / 'input.json').write_bytes((parent / 'input.json').read_bytes())
    write_trace(output / 'prefix-trace.jsonl', prefix)
    dump(output / 'source-start.json', before)
    dump(output / 'initial-terminal.json', primitive(terminal))
    dump(output / 'strategy.json', {'actual_strategy': 'qec_temporal_four', 'stage': '4C',
                                   'attempt': attempt, 'resumed': True})
    dump(output / 'resume-provenance.json', {
        'parent_output': str(parent), 'selected_checkpoint': str(checkpoint_path),
        'skipped_checkpoints': skipped, 'classification': classification, 'review_note': review_note,
        'parent_files': [{'path': str(p), 'sha256': file_digest(p)} for p in provenance_paths],
        'input_sha256': file_digest(parent / 'input.json'),
        'prefix_trace_sha256': file_digest(output / 'prefix-trace.jsonl'), 'prefix_trace_records': len(prefix),
        'prefix_canonical_snapshot_sha256': prefix_snapshot_sha256,
        'prefix_plans': prefix_plans, 'prefix_time_us': state.time_us,
        'prefix_completed_gates': state.metrics()['completed_gate_count'],
        'prefix_all_gates_complete': state.dag.completed, 'prefix_terminal_satisfied': terminal_satisfied,
        'parent_result': read_json(parent / 'result.json') if (parent / 'result.json').exists() else None,
        'parent_progress': read_json(parent / 'last-committed-progress.json')
                           if (parent / 'last-committed-progress.json').exists() else None,
        'parent_source_delta': source_delta, 'same_source_as_parent': not source_delta,
        'remaining_plan_budget': remaining_plans, 'parsed_event_budget': PARSED_EVENT_BUDGET,
        'timing_scope': 'Suffix compilation only; parent timing is separately preserved, not repeated',
    })
    shutil.copyfile(checkpoint_path, output / 'last-committed-checkpoint.json')
    dump(output / 'cache-start.json', cache_stats())
    started = perf_counter()
    saved_count = [state.metrics()['completed_gate_count']]

    def observe(current, event):
        if event.event_type.value != 'plan_completed':
            return
        assert tuple(current.trace.records[:len(prefix)]) == prefix, 'Committed prefix changed'
        count = current.metrics()['completed_gate_count']
        progress = {'completed_gates': count, 'total_gates': len(circuit.gates),
                    'simulation_time_us': current.time_us, 'elapsed_seconds': perf_counter() - started,
                    'trace_records': len(current.trace.records), 'prefix_records': len(prefix)}
        dump(output / 'progress.json', progress)
        if count - saved_count[0] >= 40 or current.dag.completed:
            (output / 'last-committed-checkpoint.json').write_text(current.snapshot(), encoding='utf-8')
            dump(output / 'last-committed-progress.json', progress)
            dump(output / 'cache-progress.json', cache_stats())
            saved_count[0] = count
            print(json.dumps(progress), flush=True)

    result = None
    error = None
    try:
        assert _event_data.cache_info().maxsize == PARSED_EVENT_BUDGET, 'Parser cache capacity is not the declared 16384'
        result = run_qec_temporal_four(state, terminal=terminal, on_event=observe,
            resume=True, max_decisions=remaining_plans,
            candidate_budget=value.get('row_candidate_budget', 4096),
            route_expansions=value.get('route_expansions', 100000))
        assert result.status == 'completed', str(result.diagnostics)
        assert tuple(state.trace.records[:len(prefix)]) == prefix, 'Committed prefix changed'
        if already_finished:
            assert digest(state.snapshot().encode('utf-8')) == prefix_snapshot_sha256, 'Already-terminal input generated new physical events'
        assert len(state.trace.records) < PARSED_EVENT_BUDGET, 'Full trace exceeds declared parsed-event working set'
        check_final(state, circuit, terminal)
        observed_cache = cache_stats()
        dump(output / 'cache-final.json', observed_cache)
        assert observed_cache['encoding']['records'] == len(state.trace.records), 'Full final encoding prefix is not retained'
        assert before == sources(), 'Source changed during continuation'
        inputs_unchanged(output)
    except Exception as exc:
        error = {'code': type(exc).__name__, 'message': str(exc)}
    (output / 'checkpoint.json').write_text(state.snapshot(), encoding='utf-8')
    write_trace(output / 'trace.jsonl', state.trace.records)
    dump(output / 'cache-final.json', cache_stats())
    dump(output / 'qec_result.json', summarize(state))
    dump(output / 'result.json', {'status': 'failed' if error else 'checks_passed_replay_pending',
        'actual_strategy': 'qec_temporal_four', 'error': error,
        'compile_seconds': perf_counter() - started, 'compile_timing_scope': 'suffix_only',
        'metrics': state.metrics(), 'trace_records': len(state.trace.records),
        'prefix_records': len(prefix), 'new_trace_records': len(state.trace.records) - len(prefix),
        'prefix_unchanged': tuple(state.trace.records[:len(prefix)]) == prefix,
        'already_terminal_at_resume': already_finished, 'recording_pending_full_replay': True})
    for name in ('diagnostics', 'candidate_rejections', 'decision_log'):
        dump(output / ('decisions.json' if name == 'decision_log' else name + '.json'),
             primitive(getattr(result, name, ())))
    dump(output / 'decisions-provenance.json', {'scope': 'suffix_only', 'parent_output': str(parent),
          'note': 'Parent decision log may extend beyond selected checkpoint; not merged as executed evidence'})
    dump(output / 'source-stability.json', {'changed_during_run': before != sources(), 'files': before})
    print(json.dumps({'resume_status': 'failed' if error else 'passed', 'error': error}), flush=True)
    return 1 if error else 0


def verify_case(output):
    from neutral_atom_env.simulation import Executor
    from neutral_atom_strategies.scheduling.m3 import initial_terminal
    from neutral_atom_env.replay.operation_codec import event_from_dict
    from neutral_atom_experiments.surface_qec_temporal_four import HISTORY_IDS, validate_history
    from neutral_atom_env.visualization import VisualRecorder
    from neutral_atom_app.visualization.workbench import recording_payload
    from neutral_atom_env.visualization.viewer import write_html

    inputs_unchanged(output)
    value, circuit, state = original_input(output)
    terminal = initial_terminal(state)
    recorder = VisualRecorder(state)
    before = sources()
    assert before == read_json(output / 'source-start.json'), 'Source changed between resume and full replay'
    provenance = read_json(output / 'resume-provenance.json')
    assert file_digest(output / 'prefix-trace.jsonl') == provenance['prefix_trace_sha256']
    with (output / 'prefix-trace.jsonl').open('rb') as prefix_stream, (output / 'trace.jsonl').open('rb') as full_stream:
        for index, line in enumerate(prefix_stream):
            assert full_stream.readline() == line, f'Prefix changed at {index}'
    started = perf_counter()
    plans = 0
    cursor = 0
    checked = False
    with (output / 'trace.jsonl').open(encoding='utf-8') as stream:
        while first_line := stream.readline():
            expected = first_line.removesuffix('\n')
            event = event_from_dict(json.loads(expected)['event'])
            assert event.event_type.value == 'plan_started', f'Expected plan at trace record {cursor}'
            executor = Executor(state)
            executor.submit(event.plan)
            plans += 1
            first_event = True
            while state.event_queue:
                if not first_event:
                    line = stream.readline()
                    assert line, f'Unexpected end of trace at {cursor}'
                    expected = line.removesuffix('\n')
                committed = executor.step()
                assert state.trace.records[-1] == expected, f'Trace mismatch at {cursor}'
                first_event = False
                cursor += 1
                recorder.observe(state, committed)
                if not checked and all(g in state.measurement_results for g in HISTORY_IDS):
                    validate_history(state.measurement_results)
                    checked = True
            if plans % 20 == 0:
                progress = {'replayed_plans': plans, 'trace_records': cursor,
                    'completed_gates': state.metrics()['completed_gate_count'], 'elapsed_seconds': perf_counter() - started}
                dump(output / 'replay-progress.json', progress)
                print(json.dumps(progress), flush=True)
    assert state.snapshot() == (output / 'checkpoint.json').read_text(encoding='utf-8')
    report = check_final(state, circuit, terminal)
    assert checked
    assert before == sources(), 'Source changed during full replay'
    inputs_unchanged(output)
    payload = recording_payload(recorder, value)
    dump(output / 'recording.json', payload)
    write_html(payload, output / 'index.html')
    dump(output / 'replay-cache-final.json', cache_stats())
    dump(output / 'verification.json', {'compiler_free_replay': 'PASS', 'checkpoint_restore': 'PASS',
        'exact_snapshot': True, 'exact_trace_records': True, 'history_guard': True,
        'prefix_unchanged': True, 'full_prefix_and_suffix_recording': True,
        'replayed_plans': plans, 'replayed_prefix_plans': provenance['prefix_plans'],
        'final': report, 'verification_seconds': perf_counter() - started, 'source_changed': False})
    return 0


def main(args):
    output = Path(args.output).resolve()
    parent = Path(args.parent_output).resolve()
    if args.mode == 'resume':
        return resume_case(output, parent, args.attempt, args.classification, args.review_note)
    if args.mode == 'verify':
        return verify_case(output)
    assert args.classification and args.review_note, 'Parent failure classification and review note are required'
    assert output != parent and parent not in output.parents, 'Use an independent sibling evidence directory'
    output.mkdir(parents=True, exist_ok=False)
    dump(output / 'attempt.json', {'stage': '4C', 'attempt': args.attempt,
        'started_at': datetime.now(timezone.utc).isoformat(), 'parent_output': str(parent),
        'classification': args.classification, 'review_note': args.review_note,
        'resume_budget_seconds': PHASE_BUDGET_SECONDS, 'verify_budget_seconds': PHASE_BUDGET_SECONDS,
        'plan_budget_including_prefix': TOTAL_PLAN_BUDGET, 'parsed_event_budget': PARSED_EVENT_BUDGET,
        'full_result_recompiled': False, 'automatic_retry': False})
    for mode in ('resume', 'verify'):
        print(json.dumps({'phase': mode, 'status': 'started'}), flush=True)
        command = [sys.executable, __file__, '--mode', mode, '--output', str(output),
            '--parent-output', str(parent), '--attempt', str(args.attempt),
            '--classification', args.classification, '--review-note', args.review_note]
        try:
            with (output / (mode + '-output.txt')).open('w', encoding='utf-8') as log:
                code = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                                      timeout=PHASE_BUDGET_SECONDS).returncode
        except subprocess.TimeoutExpired:
            code = 124
        print(json.dumps({'phase': mode, 'status': 'passed' if not code else 'failed', 'exit_code': code}), flush=True)
        if code:
            dump(output / 'failure.json', {'phase': mode, 'exit_code': code,
                'action': 'Preserved for diagnosis; no automatic retry or subsequent phase'})
            return code
    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--parent-output', default='artifacts/qec-roadmap/step4C-attempt2')
    parser.add_argument('--output', default='artifacts/qec-roadmap/step4C-resumed-attempt3')
    parser.add_argument('--mode', choices=('all', 'resume', 'verify'), default='all')
    parser.add_argument('--attempt', type=int, default=3)
    parser.add_argument('--classification', choices=('timeout', 'cache_bound', 'completed', 'reviewed_engineering'))
    parser.add_argument('--review-note', default='')
    sys.exit(main(parser.parse_args()))
