"""Audit/export recovery of a complete checkpoint after process interruption.

There is no scheduler or forward execution path. Original artifacts remain
unchanged, missing decision logs are disclosed, and all completion/quantum/
timing/physical replay checks must actually pass in a fresh process.
"""
from collections import Counter
from itertools import zip_longest
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys
from time import perf_counter

from neutral_atom_env import NeutralAtomEnv
from neutral_atom_env.replay.operation_codec import plan_from_dict
from neutral_atom_env.replay.serializer import canonical_json
from neutral_atom_env.visualization import VisualRecorder
from neutral_atom_strategies.scheduling.m3 import initial_terminal

from .encoded_physical import audit_completed_encoded_state, encoded_parity_inputs
from .physical import fresh_output


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def require_outside_archives(path, *archives):
    """Resolve aliases before any write into the immutable source archives."""
    resolved = Path(path).resolve()
    if any(resolved == Path(root).resolve() or Path(root).resolve() in resolved.parents
           for root in archives):
        raise ValueError('New output and diagnostic files must be outside original archives')
    return resolved


def exact_snapshot_chunks(payload):
    """Canonical bytes with at most one escaped trace record allocated.

    The public payload/serializer are unchanged. The ordinary trace encoding
    cache materializes all escaped records even with a zero retention budget;
    this local exporter yields them individually instead.
    """
    if type(payload) is not dict or any(type(key) is not str for key in payload):
        raise TypeError('Snapshot export requires an exact dict with exact string keys')
    records = payload.get('trace')
    if type(records) is not tuple or any(type(row) is not str for row in records):
        raise TypeError('Snapshot export requires the public immutable exact-string trace')
    yield '{'
    for i, key in enumerate(sorted(payload)):
        if i:
            yield ','
        yield canonical_json(key)
        yield ':'
        if key == 'trace':
            yield '['
            for j, row in enumerate(records):
                if j:
                    yield ','
                yield canonical_json(row)
            yield ']'
        else:
            yield canonical_json(payload[key])
    yield '}'


def exact_snapshot_equal(left, right):
    missing = object()
    return all(a == b for a, b in zip_longest(exact_snapshot_chunks(left),
                                              exact_snapshot_chunks(right), fillvalue=missing))


def write_exact_snapshot(path, payload):
    digest = hashlib.sha256()
    with Path(path).open('xb') as stream:
        for fragment in exact_snapshot_chunks(payload):
            encoded = fragment.encode('utf-8')
            stream.write(encoded)
            digest.update(encoded)
    return digest.hexdigest()


def write_json_array(path, values):
    with Path(path).open('x', encoding='utf-8', newline='') as stream:
        stream.write('[')
        for i, value in enumerate(values):
            if i:
                stream.write(',')
            stream.write(canonical_json(value))
        stream.write(']')


def iter_json_array(path, *, chunk_size=65536, max_value_chars=64 * 1024 * 1024):
    """Read one complete JSON-array element at a time, with a finite buffer."""
    if type(chunk_size) is not int or chunk_size < 1 or type(max_value_chars) is not int or max_value_chars < 1:
        raise ValueError('Positive stream chunk and element bounds are required')
    with Path(path).open('r', encoding='utf-8') as stream:
        buffer, eof = '', False
        decoder = json.JSONDecoder()
        def fill():
            nonlocal buffer, eof
            block = stream.read(chunk_size)
            eof = not block
            buffer += block
        def peek():
            nonlocal buffer
            while True:
                buffer = buffer.lstrip()
                if buffer or eof:
                    return buffer[:1]
                fill()
        if peek() != '[':
            raise ValueError('Expected a JSON array')
        buffer = buffer[1:]
        allow_end = True
        while True:
            token = peek()
            if token == ']':
                if not allow_end:
                    raise ValueError('Trailing comma in JSON array')
                buffer = buffer[1:]
                if peek():
                    raise ValueError('Trailing content after JSON array')
                return
            if not token:
                raise ValueError('Incomplete JSON array')
            while True:
                try:
                    value, end = decoder.raw_decode(buffer)
                    if end > max_value_chars:
                        raise ValueError('JSON array element exceeds the declared memory buffer bound')
                    # A number can decode as a shorter valid prefix, e.g.
                    # raw_decode('1e') -> (1, 1). Await its real delimiter.
                    if not eof and (end == len(buffer) or buffer[end] not in ' \t\r\n,]'):
                        if len(buffer) > max_value_chars:
                            raise ValueError('JSON array element exceeds the declared memory buffer bound')
                        fill()
                        continue
                    break
                except json.JSONDecodeError:
                    if eof:
                        raise ValueError('Invalid or incomplete JSON array element')
                    fill()
                if len(buffer) > max_value_chars:
                    raise ValueError('JSON array element exceeds the declared memory buffer bound')
            buffer = buffer[end:]
            token = peek()
            if token not in (',', ']'):
                raise ValueError('Missing JSON-array element separator')
            yield value
            if token == ',':
                buffer = buffer[1:]
                allow_end = False
            else:
                allow_end = True


def _check_trace_and_plans(state, plans, trace_path):
    """Compare all saved trace bytes and complete plan bodies, one row at a time."""
    started, rows = 0, 0
    with Path(trace_path).open('r', encoding='utf-8') as stream:
        for i, line in enumerate(stream):
            raw = line.rstrip('\n')
            if i >= len(state.trace.records) or raw != state.trace.records[i]:
                raise ValueError('Saved trace bytes differ from the checkpoint')
            row = json.loads(raw)
            event = row['event']
            if event['event_type'] == 'plan_started':
                if (started >= len(plans) or event['plan_id'] != plans[started].id or
                        canonical_json(event.get('plan')) != canonical_json(plans[started])):
                    raise ValueError('Complete accepted-plan contents differ from committed plan_started trace')
                started += 1
            rows += 1
    if (rows != len(state.trace.records) or started != len(plans) or
            state.metrics()['completed_plan_count'] != len(plans) or
            len({p.id for p in plans}) != len(plans)):
        raise ValueError('Complete saved trace and accepted-plan history differ')


def _check_parent(state, plans, parent, metadata, initial, expected_files):
    """Require the frozen hash/content-verified prefix, retaining failed audits."""
    resume = metadata.get('resume')
    if not resume or Path(resume['prefix_directory']).resolve() != parent:
        raise ValueError('Recovery parent does not match recorded strict-resume provenance')
    for name, expected in expected_files.items():
        if canonical_json(json.loads((parent/name).read_text(encoding='utf-8'))) != canonical_json(expected):
            raise ValueError(f'Parent {name} differs from the current experiment')
    if (parent/'initial.json').read_text(encoding='utf-8') != initial:
        raise ValueError('Parent original initial checkpoint differs from current inputs or seed')
    if (file_sha256(parent/'checkpoint.json') != resume['prefix_checkpoint_sha256'] or
            file_sha256(parent/'run_metadata.json') != resume['prefix_run_metadata_sha256'] or
            hashlib.sha256(initial.encode()).hexdigest() != resume['original_initial_sha256']):
        raise ValueError('Parent/original-initial provenance fingerprint differs')
    parent_metadata = json.loads((parent/'run_metadata.json').read_text(encoding='utf-8'))
    parent_evidence = json.loads((parent/'evidence.json').read_text(encoding='utf-8'))
    if parent_metadata['seed'] != metadata['seed'] or parent_evidence['status'] != resume['prefix_status'] or parent_evidence.get('error') != resume['prefix_error']:
        raise ValueError('Parent seed/status/error differs from strict-resume provenance')
    count = 0
    for value in iter_json_array(parent/'plans.json'):
        old = plan_from_dict(value)
        if count >= len(plans) or canonical_json(old) != canonical_json(plans[count]):
            raise ValueError('Parent accepted-plan prefix contents differ')
        count += 1
    if count != resume['inherited_accepted_plans']:
        raise ValueError('Parent accepted-plan count differs from strict-resume provenance')
    rows, started = 0, 0
    with (parent/'trace.jsonl').open('r', encoding='utf-8') as stream:
        for i, line in enumerate(stream):
            raw = line.rstrip('\n')
            if i >= len(state.trace.records) or raw != state.trace.records[i]:
                raise ValueError('Parent committed trace is not the exact recovered prefix')
            event = json.loads(raw)['event']
            if event['event_type'] == 'plan_started':
                if (started >= count or event['plan_id'] != plans[started].id or
                        canonical_json(event.get('plan')) != canonical_json(plans[started])):
                    raise ValueError('Parent plan_started contents differ from accepted-plan prefix')
                started += 1
            rows += 1
    if len(plans) < count or count != started:
        raise ValueError('Recovery requires a parent with every accepted plan already started')
    metrics = parent_evidence['metrics']
    if (metrics['completed_gate_count'] != resume['inherited_completed_gates'] or
            metrics['simulation_time_us'] != resume['inherited_simulation_time_us']):
        raise ValueError('Parent metrics differ from strict-resume provenance')
    return {'source_sha256': parent_metadata['source_sha256'], 'committed_prefix_events': rows,
            'accepted_plan_count': count, 'raw_evidence': parent_evidence}, json.loads((parent/'decisions.json').read_text(encoding='utf-8'))


def _validate_sources(metadata, reviewed_runner_change):
    root = Path(__file__).resolve().parents[2]
    # Only the recorded environment/strategy files and selected frontend
    # dependencies have old preimages; uncaptured experiments stay unknown.
    qec = {'canonical.py', 'encoded_ppm.py', 'encoded_physical.py', 'ir.py', 'lowering.py',
           'neutral_atom.py', 'pauli.py', 'physical.py', 'surface.py', 'verification.py'}
    required = {'neutral_atom_experiments/qec_pbc/'+name for name in qec}
    required |= {str(path.relative_to(root)).replace('\\', '/')
                 for package in ('neutral_atom_env', 'neutral_atom_strategies')
                 for path in (root/package).rglob('*.py')}
    captured = metadata['source_sha256']
    if any(type(key) is not str or ':' in key or '\\' in key or
           PurePosixPath(key).is_absolute() or str(PurePosixPath(key)) != key or
           any(part in ('.', '..') for part in PurePosixPath(key).parts)
           for key in captured):
        raise ValueError('Recovery source metadata paths must be canonical relative paths')
    if not required <= set(captured):
        raise ValueError('Recovery source provenance is incomplete')
    checked = {}
    for key in sorted(required):
        old = captured[key]
        current = file_sha256(root/key)
        if current != old:
            if (key != 'neutral_atom_experiments/qec_pbc/encoded_physical.py' or
                    reviewed_runner_change != (old, current)):
                raise ValueError(f'Unreviewed recovery source change: {key}')
        checked[key] = {'original': old, 'recovery': current}
    return checked


def _validate_crash_provenance(crashed, metadata, manifest_path, protocol, seed):
    if (not isinstance(metadata.get('source_sha256'), dict) or
            any(type(key) is not str or type(value) is not str or len(value) != 64 or
                any(char not in '0123456789abcdef' for char in value)
                for key, value in metadata['source_sha256'].items())):
        raise ValueError('Recovery source metadata has invalid structure')
    manifest = json.loads(Path(manifest_path).read_text(encoding='utf-8'))
    if Path(manifest['original_directory']).resolve() != crashed:
        raise ValueError('Frozen crash manifest refers to a different directory')
    required = {'checkpoint.json','plans.json','trace.jsonl','initial.json','protocol.json',
                'compiled.json','platform.json','working_destinations.json','initial_placement.json',
                'run_metadata.json','loaded_runtime_provenance.json'}
    fingerprints = manifest['raw_artifact_fingerprints']
    if not required <= set(fingerprints):
        raise ValueError('Frozen crash artifact fingerprints are incomplete')
    for name in required:
        path, expected = crashed/name, fingerprints[name]
        if path.stat().st_size != expected['bytes'] or file_sha256(path) != expected['sha256']:
            raise ValueError(f'Frozen crash artifact differs: {name}')
    launch = json.loads((crashed/'loaded_runtime_provenance.json').read_text(encoding='utf-8'))
    if (launch['seed'] != seed or launch['basis'] != protocol.basis or launch['rounds'] != protocol.rounds or
            Path(launch['output_expected']).resolve() != crashed or
            Path(launch['resume_from']).resolve() != Path(metadata['resume']['prefix_directory']).resolve()):
        raise ValueError('Launch provenance seed/basis/rounds/directory differs')
    selected = launch['sha256_raw_at_process_start']
    keys = ('neutral_atom_experiments/qec_pbc/encoded_physical.py', 'neutral_atom_env/replay/trace.py',
            'neutral_atom_env/replay/snapshot_encoding.py', 'neutral_atom_env/simulation/runtime_validation.py')
    if any(selected.get('src/'+key) != metadata['source_sha256'].get(key) for key in keys):
        raise ValueError('Launch source bytes disagree with initialization source metadata')
    cli = Path(__file__).resolve().parents[3]/'examples/run_encoded_parity.py'
    if selected.get('examples/run_encoded_parity.py') != file_sha256(cli):
        raise ValueError('Launch CLI source differs from the independently preserved entry point')
    return {'manifest_sha256':file_sha256(manifest_path), 'original_artifact_fingerprints':fingerprints,
            'launch_provenance':launch, 'source_capture_scope':'Only originally captured environment/strategy and ten selected physical QEC frontend files; uncaptured experiment dependencies are unknown'}


def recover_encoded_export(protocol, crashed, parent, output, *, seed=0,
                           crash_manifest, reviewed_runner_change=None, progress=None):
    """Reaudit a complete saved state and replay/export, without forward work."""
    started = perf_counter()
    crashed, parent = Path(crashed).resolve(), Path(parent).resolve()
    output = require_outside_archives(output, crashed, parent)
    if protocol.close_data_basis is not None:
        raise ValueError('Recovery requires the retained encoded instrument')
    inputs, destinations = encoded_parity_inputs(protocol, seed=seed)
    expected = {'protocol.json': protocol.to_dict(), 'compiled.json': inputs.compiled.to_dict(),
                'platform.json': inputs.platform, 'working_destinations.json': destinations,
                'initial_placement.json': dict(inputs.placement)}
    for name, value in expected.items():
        if canonical_json(json.loads((crashed/name).read_text(encoding='utf-8'))) != canonical_json(value):
            raise ValueError(f'Recovery {name} differs from current experiment inputs')
    initial = inputs.create_environment().snapshot()
    if (crashed/'initial.json').read_text(encoding='utf-8') != initial:
        raise ValueError('Recovery original initial checkpoint differs from current inputs or seed')
    metadata = json.loads((crashed/'run_metadata.json').read_text(encoding='utf-8'))
    if metadata['seed'] != seed:
        raise ValueError('Recovery seed differs')
    crash_provenance = _validate_crash_provenance(crashed, metadata, crash_manifest, protocol, seed)
    sources = _validate_sources(metadata, reviewed_runner_change)
    env = NeutralAtomEnv.restore((crashed/'checkpoint.json').read_text(encoding='utf-8'))
    if env.state.seed != seed or env.state.dag.circuit != inputs.circuit or env.state.hardware != inputs.platform.hardware:
        raise ValueError('Recovered state seed/circuit/hardware differs from inputs')
    if not env.state.dag.completed or env.pending or env.state.metrics()['completed_gate_count'] != len(inputs.circuit.gates):
        raise ValueError('Export-only recovery requires complete native gates and no pending events')
    plans = [plan_from_dict(value) for value in iter_json_array(crashed/'plans.json')]
    _check_trace_and_plans(env.state, plans, crashed/'trace.jsonl')
    parent_provenance, parent_decisions = _check_parent(env.state, plans, parent, metadata, initial, expected)
    original = NeutralAtomEnv.restore(initial)
    terminal = initial_terminal(original.state)
    decisions_path = crashed/'decisions.json'
    decisions = json.loads(decisions_path.read_text(encoding='utf-8')) if decisions_path.exists() else None
    audit, operations = audit_completed_encoded_state(protocol, inputs, env.state, plans,
        original.state.quantum_state, terminal, decision_logs=(*parent_decisions, *(decisions or ())))
    output = fresh_output(output)
    recovery = {'schema': 'encoded-export-recovery-provenance/1', 'crashed_directory': str(crashed),
        'parent_directory': str(parent), 'forward_gates_executed': 0, 'source_compatibility': sources,
        'original_source_compatibility_complete': False,
        'uncaptured_original_dependencies': {
            'neutral_atom_experiments/'+name: {'original':None,
                'recovery':file_sha256(Path(__file__).resolve().parents[1]/name)}
            for name in ('surface_ghz.py','surface_qec.py','qec_layout.py')},
        'recovery_source_sha256': {
            'neutral_atom_experiments/qec_pbc/encoded_export_recovery.py': file_sha256(__file__),
            'neutral_atom_experiments/qec_pbc/encoded_physical.py': file_sha256(Path(__file__).with_name('encoded_physical.py')),
            'examples/run_encoded_parity.py': file_sha256(Path(__file__).resolve().parents[3]/'examples/run_encoded_parity.py')},
        'recovery_entry_point': 'python -m neutral_atom_experiments.qec_pbc.encoded_export_recovery',
        'recovery_python': {'version':sys.version, 'executable':sys.executable},
        'run_metadata_scope': 'Original interrupted process metadata, preserved exactly as a separate producer record',
        'crash_provenance': crash_provenance,
        'parent_provenance': parent_provenance, 'strict_resume': metadata['resume'],
        'scheduler_decisions_available': decisions is not None,
        'missing_original_artifacts': [name for name in ('evidence.json','decisions.json','recording.json','animation.html','schedule.json') if not (crashed/name).exists()],
        'crashed_total_wall_seconds': None,
        'original_process_exit': 'Windows python312.dll 0xc0000005; mechanism unknown; not established OOM',
        'wall_seconds_scope': 'This independent recovery audit/replay/export only',
        'recording_scope': 'complete_committed_prefix_from_original_initial'}
    try:
        for name, value in (*expected.items(), ('run_metadata.json', metadata), ('recovery_provenance.json', recovery)):
            (output/name).write_text(canonical_json(value), encoding='utf-8')
        (output/'initial.json').write_text(initial, encoding='utf-8')
        saved_sha = write_exact_snapshot(output/'checkpoint.json', env.state.snapshot_data())
        if saved_sha != file_sha256(crashed/'checkpoint.json'):
            raise AssertionError('Recovered checkpoint export bytes differ from original saved bytes')
        write_json_array(output/'plans.json', plans)
        if file_sha256(output/'plans.json') != file_sha256(crashed/'plans.json'):
            raise AssertionError('Recovered plan export bytes differ from original accepted-plan bytes')
        env.state.trace.write(output/'trace.jsonl')
        replay = NeutralAtomEnv.restore(initial)
        recorder = VisualRecorder(replay.state)
        for i, plan in enumerate(plans):
            replay.submit(plan)
            replay.run(on_event=recorder.observe)
            if i % 16 == 0 or i + 1 == len(plans):
                item = {'stage': 'independent_replay', 'plans_replayed': i + 1, 'total_plans': len(plans),
                        'completed_gates': replay.state.metrics()['completed_gate_count'],
                        'physical_time_us': replay.state.time_us, 'recovery_wall_seconds': perf_counter()-started}
                (output/'recovery_progress.json').write_text(canonical_json(item), encoding='utf-8')
                if progress:
                    progress(item)
        audit['independent_plan_replay_equal'] = exact_snapshot_equal(replay.state.snapshot_data(), env.state.snapshot_data())
        if not audit['independent_plan_replay_equal']:
            raise AssertionError('Independent original-initial replay differs byte-for-byte from recovered state')
        # Full animation comes from the actual replay, never the old suffix alone.
        (output/'recording.json').write_text(canonical_json(recorder.payload()), encoding='utf-8')
        recorder.write(output/'animation.html')
        (output/'schedule.json').write_text(canonical_json(operations), encoding='utf-8')
        if decisions is not None:
            (output/'decisions.json').write_text(canonical_json(decisions), encoding='utf-8')
        else:
            (output/'decisions_unavailable.json').write_text(canonical_json({'available': False,
                'reason':'Original process interrupted before scheduler log export; no suffix decisions reconstructed',
                'no_layout_staging_audit':'All accepted plan intents plus available parent decisions'}), encoding='utf-8')
        pulses = [len(row['gate_ids']) for row in operations if row['kind'] == 'entangling_pulse']
        evidence = {'schema':'qec-encoded-parity-physical/1', 'status':'completed', 'error':None,
            'basis':protocol.basis, 'seed':seed, 'rounds_before_and_after':protocol.rounds,
            'output_directory':str(output.resolve()), 'physical_atom_count':len(env.state.atoms),
            'native_gate_count':len(inputs.circuit.gates), 'gate_counts':dict(Counter(g.gate_type for g in inputs.circuit.gates)),
            'plans':len(plans), 'metrics':env.state.metrics(), 'audit':audit,
            'physical_pulse_count':len(pulses), 'max_parallel_cz':max(pulses,default=0),
            'schedule_complete':True, 'recording_scope':recovery['recording_scope'],
            'wall_seconds':perf_counter()-started, 'wall_seconds_scope':recovery['wall_seconds_scope'],
            'recovery':recovery, 'resume':metadata['resume'], 'scheduler_decisions_available':decisions is not None,
            'scope':'Ideal retained encoded parity, saved complete physical state independently reaudited/replayed/exported',
            'full_fault_tolerance_claim':False, 'initial_placement':'prearranged',
            'layout_preparation_time_included':False, 'upstream_layout_preparation_time_us':None,
            'diagnostics':('Original scheduler decision log unavailable',) if decisions is None else (),
            'candidate_rejections':None}
        (output/'evidence.json').write_text(canonical_json(evidence), encoding='utf-8')
        return evidence
    except Exception as exc:
        (output/'recovery_failure.json').write_text(canonical_json({
            'schema':'encoded-export-recovery-failure/1', 'status':'failed',
            'error':{'type':type(exc).__name__, 'message':str(exc)},
            'wall_seconds':perf_counter()-started,
            'wall_seconds_scope':recovery['wall_seconds_scope'],
            'forward_gates_executed':0, 'original_artifacts_unchanged':True,
            'completed_claim':False}), encoding='utf-8')
        raise


def main():
    """A verification-only CLI; no scheduler, budget, or forward-run switch."""
    import argparse
    import faulthandler
    from .encoded_ppm import encoded_parity_program
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--basis', choices=('X', 'Z'), required=True)
    parser.add_argument('--rounds', type=int, default=3)
    parser.add_argument('--seed', type=int, default=7)
    parser.add_argument('--crashed', required=True)
    parser.add_argument('--parent', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--crash-manifest', required=True)
    parser.add_argument('--reviewed-runner-old-sha')
    parser.add_argument('--reviewed-runner-new-sha')
    parser.add_argument('--fault-log', required=True,
                        help='Fresh diagnostic file outside the original archives')
    args = parser.parse_args()
    pair = (args.reviewed_runner_old_sha, args.reviewed_runner_new_sha)
    if any(pair) and not all(pair):
        parser.error('Both reviewed runner hashes must be supplied together')
    fault_log = require_outside_archives(args.fault_log, args.crashed, args.parent)
    require_outside_archives(args.output, args.crashed, args.parent)
    # The explicitly named fresh fault log survives an interpreter crash.
    with fault_log.open('x', encoding='utf-8') as stream:
        faulthandler.enable(stream, all_threads=True)
        try:
            evidence = recover_encoded_export(encoded_parity_program(basis=args.basis, rounds=args.rounds),
                args.crashed, args.parent, args.output, seed=args.seed,
                crash_manifest=args.crash_manifest,
                reviewed_runner_change=pair if all(pair) else None,
                progress=lambda row: print(canonical_json(row), flush=True))
            print(canonical_json({'status':evidence['status'], 'plans':evidence['plans'],
                                  'output_directory':evidence['output_directory']}), flush=True)
        finally:
            faulthandler.disable()


if __name__ == '__main__':
    main()
