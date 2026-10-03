"""Exact-byte streaming and verification-only real-physical recovery.

The short physical fixture exercises native RESET/H/MEASURE, transport,
projection, effects, timing and full plan replay. Its retained encoded-output
audit is explicitly replaced; the full d3 output audit is a separate run.
"""
from dataclasses import dataclass, replace
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from neutral_atom_env.circuit import PhysicalCircuit
from neutral_atom_env.domain.models import PhysicalGate
from neutral_atom_env.replay.serializer import canonical_json
from neutral_atom_experiments.qec_pbc import encoded_export_recovery as recovery
from neutral_atom_experiments.qec_pbc import encoded_physical as runner
from neutral_atom_experiments.qec_pbc.encoded_ppm import encoded_parity_program
from neutral_atom_experiments.qec_pbc.lowering import MeasurementBinding


@dataclass(frozen=True)
class Value:
    text: str
    scalar: float


@pytest.mark.parametrize('trace', [(), ('',), ('中文🙂', 'quote"\nslash\\'),
                                  tuple('x'*i for i in (1, 7, 65535, 65536, 65537))])
def test_snapshot_stream_matches_independent_whole_canonical_utf8_oracle(tmp_path, trace):
    payload = {'trace':trace, 'z':{'b':{3, 1, 2}, 'a':Value('é', -0.0)},
               'a':[True, None, 0.125, {'nested':'\t\b\r\f'}]}
    oracle = canonical_json(payload).encode('utf-8')
    assert ''.join(recovery.exact_snapshot_chunks(payload)).encode('utf-8') == oracle
    output = tmp_path/'checkpoint.json'
    assert recovery.write_exact_snapshot(output, payload) == hashlib.sha256(oracle).hexdigest()
    assert output.read_bytes() == oracle
    assert recovery.exact_snapshot_equal(payload, dict(payload))


@pytest.mark.parametrize('change', ['first', 'middle', 'last', 'append', 'truncate', 'field'])
def test_snapshot_comparison_requires_all_exact_content_and_eof(change):
    left = {'trace':('a', '中', 'last'), 'field':{'x':1}}
    right = {'trace':left['trace'], 'field':{'x':1}}
    if change == 'field':
        right['field']['x'] = 2
    elif change == 'append':
        right['trace'] += ('extra',)
    elif change == 'truncate':
        right['trace'] = right['trace'][:-1]
    else:
        records = list(right['trace'])
        records[{'first':0, 'middle':1, 'last':2}[change]] += '!'
        right['trace'] = tuple(records)
    assert not recovery.exact_snapshot_equal(left, right)


@pytest.mark.parametrize('chunk_size', [1, 7, 65536])
def test_json_array_stream_all_element_and_numeric_boundaries(tmp_path, chunk_size):
    values = [1e2, 0.12, -3.25e-7, {'nested':['é🙂', [1, True, None]]}, '"\\', {}, []]
    path = tmp_path/'plans.json'
    recovery.write_json_array(path, values)
    assert path.read_bytes() == canonical_json(values).encode()
    assert list(recovery.iter_json_array(path, chunk_size=chunk_size)) == values
    # Scientific notation is deliberately preserved in a separate input.
    path.write_text('[1e2,0.12,-3.25e-7]', encoding='utf-8')
    assert list(recovery.iter_json_array(path, chunk_size=1)) == [100, .12, -3.25e-7]


@pytest.mark.parametrize('raw', ['[1,]', '[1 2]', '[{"x":', '[1', '[1]x', '[] []', '{}'])
def test_json_array_stream_rejects_truncation_separators_and_extra_content(tmp_path, raw):
    path = tmp_path/'bad.json'
    path.write_text(raw, encoding='utf-8')
    with pytest.raises(ValueError):
        list(recovery.iter_json_array(path, chunk_size=1))


def test_json_array_declared_element_and_chunk_bounds(tmp_path):
    path = tmp_path/'bounded.json'
    path.write_text('["'+'x'*100+'"]', encoding='utf-8')
    for chunk in (1, 65536):
        with pytest.raises(ValueError, match='buffer bound'):
            list(recovery.iter_json_array(path, chunk_size=chunk, max_value_chars=16))
    with pytest.raises(ValueError, match='Positive'):
        list(recovery.iter_json_array(path, chunk_size=0))
    path.write_text('[1'+'e'*40+']', encoding='utf-8')
    with pytest.raises(ValueError, match='buffer bound'):
        list(recovery.iter_json_array(path, chunk_size=2, max_value_chars=8))


def _launch_and_manifest(crashed, parent, protocol, seed):
    metadata = json.loads((crashed/'run_metadata.json').read_text(encoding='utf-8'))
    keys = ('neutral_atom_experiments/qec_pbc/encoded_physical.py', 'neutral_atom_env/replay/trace.py',
            'neutral_atom_env/replay/snapshot_encoding.py', 'neutral_atom_env/simulation/runtime_validation.py')
    selected = {'src/'+key:metadata['source_sha256'][key] for key in keys}
    selected['examples/run_encoded_parity.py'] = recovery.file_sha256(
        Path(recovery.__file__).resolve().parents[3]/'examples/run_encoded_parity.py')
    launch = {'seed':seed, 'basis':protocol.basis, 'rounds':protocol.rounds,
              'output_expected':str(crashed), 'resume_from':str(parent),
              'sha256_raw_at_process_start':selected}
    (crashed/'loaded_runtime_provenance.json').write_text(canonical_json(launch), encoding='utf-8')
    names = ('checkpoint.json','plans.json','trace.jsonl','initial.json','protocol.json',
             'compiled.json','platform.json','working_destinations.json','initial_placement.json',
             'run_metadata.json','loaded_runtime_provenance.json')
    manifest = {'original_directory':str(crashed), 'raw_artifact_fingerprints':{
        name:{'sha256':recovery.file_sha256(crashed/name), 'bytes':(crashed/name).stat().st_size}
        for name in names}}
    path = crashed.parent/(crashed.name+'-manifest.json')
    path.write_text(canonical_json(manifest), encoding='utf-8')
    return path


@pytest.fixture(scope='module')
def real_short_run(tmp_path_factory):
    root = tmp_path_factory.mktemp('encoded-recovery-real-native')
    protocol = encoded_parity_program(basis='X', rounds=1)
    original_factory = runner.encoded_parity_inputs
    def short_inputs(protocol, *, seed=0):
        inputs, destinations = original_factory(protocol, seed=seed)
        q = dict(inputs.compiled.bindings)['A.X0']
        circuit = PhysicalCircuit((PhysicalGate('short.reset','RESET',(q,)),
            PhysicalGate('short.h','H',(q,),depends_on=('short.reset',)),
            PhysicalGate('short.m','MEASURE',(q,),depends_on=('short.h',))))
        compiled = replace(inputs.compiled, circuit=circuit,
            measurements=(MeasurementBinding('short.result','short.m',0,'syndrome'),),
            provenance=tuple((g.id,g.id,'short_native_fixture') for g in circuit.gates), exits=())
        return replace(inputs, circuit=circuit, compiled=compiled), destinations
    patch = pytest.MonkeyPatch()
    patch.setattr(runner, 'encoded_parity_inputs', short_inputs)
    patch.setattr(recovery, 'encoded_parity_inputs', short_inputs)
    patch.setattr(runner, 'encoded_output_audit', lambda *_:{'short_native_fixture_scope':True})
    parent, complete = root/'parent', root/'complete'
    failed = runner.execute_encoded_parity(protocol, parent, seed=7, wall_budget_s=1e-12)
    assert failed['status'] == 'failed' and failed['plans'] == 1
    success = runner.execute_encoded_parity(protocol, complete, seed=7, wall_budget_s=120,
                                           resume_from=parent)
    assert success['status'] == 'completed', success['error']
    crashed = root/'interrupted-export-copy'
    shutil.copytree(complete, crashed)
    for name in ('evidence.json','decisions.json','recording.json','animation.html','schedule.json'):
        (crashed/name).unlink()
    manifest = _launch_and_manifest(crashed, parent, protocol, 7)
    yield protocol, parent, crashed, manifest, root, success
    patch.undo()


def test_real_complete_state_recovery_has_no_forward_and_full_byte_exact_replay(real_short_run):
    protocol, parent, crashed, manifest, root, baseline = real_short_run
    old = {p.name:recovery.file_sha256(p) for p in crashed.iterdir() if p.is_file()}
    output = root/'recovered'
    result = recovery.recover_encoded_export(protocol, crashed, parent, output, seed=7,
                                             crash_manifest=manifest)
    assert result['status'] == 'completed' and result['metrics'] == baseline['metrics']
    assert result['native_gate_count'] == result['metrics']['completed_gate_count'] == 3
    assert all(value for value in result['audit'].values() if isinstance(value, bool))
    assert result['recovery']['forward_gates_executed'] == 0
    assert result['recovery']['crashed_total_wall_seconds'] is None
    assert result['candidate_rejections'] is None and not result['scheduler_decisions_available']
    assert not (output/'decisions.json').exists()
    assert json.loads((output/'decisions_unavailable.json').read_text())['available'] is False
    for name in ('checkpoint.json','plans.json','trace.jsonl','initial.json'):
        assert (output/name).read_bytes() == (crashed/name).read_bytes()
    recording = json.loads((output/'recording.json').read_text(encoding='utf-8'))
    assert recording['frames'][0]['time'] == 0
    assert recording['frames'][-1]['time'] == result['metrics']['simulation_time_us']
    assert old == {p.name:recovery.file_sha256(p) for p in crashed.iterdir() if p.is_file()}


@pytest.mark.parametrize('filename', ['protocol.json','compiled.json','platform.json'])
def test_changed_experiment_rejected_before_new_output(real_short_run, filename):
    protocol, parent, crashed, manifest, root, _ = real_short_run
    altered = root/('altered-'+filename)
    shutil.copytree(crashed, altered)
    data = json.loads((altered/filename).read_text(encoding='utf-8'))
    data['tampered'] = True
    (altered/filename).write_text(canonical_json(data), encoding='utf-8')
    output = root/('reject-'+filename)
    with pytest.raises(ValueError, match='differs from current experiment'):
        recovery.recover_encoded_export(protocol, altered, parent, output, seed=7, crash_manifest=manifest)
    assert not output.exists()


def test_frozen_manifest_tampering_rejected(real_short_run):
    protocol, parent, crashed, manifest, root, _ = real_short_run
    altered = root/'altered-raw-trace'
    shutil.copytree(crashed, altered)
    path = _launch_and_manifest(altered, parent, protocol, 7)
    with (altered/'trace.jsonl').open('a', encoding='utf-8') as stream:
        stream.write('{}\n')
    output = root/'reject-raw-trace'
    with pytest.raises(ValueError, match='Frozen crash artifact differs'):
        recovery.recover_encoded_export(protocol, altered, parent, output, seed=7, crash_manifest=path)
    assert not output.exists()


def test_same_id_current_plan_contents_and_parent_trace_rejected(real_short_run):
    protocol, parent, crashed, manifest, root, _ = real_short_run
    altered = root/'same-id-current'
    shutil.copytree(crashed, altered)
    plans = json.loads((altered/'plans.json').read_text(encoding='utf-8'))
    plans[0]['operations'][0]['duration_us'] += 1
    (altered/'plans.json').write_text(canonical_json(plans), encoding='utf-8')
    path = _launch_and_manifest(altered, parent, protocol, 7)
    with pytest.raises(ValueError, match='Complete accepted-plan contents differ'):
        recovery.recover_encoded_export(protocol, altered, parent, root/'reject-current', seed=7, crash_manifest=path)
    altered_parent = root/'tampered-parent-trace'
    shutil.copytree(parent, altered_parent)
    altered = root/'parent-trace-child'
    shutil.copytree(crashed, altered)
    metadata = json.loads((altered/'run_metadata.json').read_text(encoding='utf-8'))
    metadata['resume']['prefix_directory'] = str(altered_parent)
    (altered/'run_metadata.json').write_text(canonical_json(metadata), encoding='utf-8')
    trace = (altered_parent/'trace.jsonl').read_text(encoding='utf-8')
    (altered_parent/'trace.jsonl').write_text(trace.replace('plan_started','altered_start',1), encoding='utf-8')
    path = _launch_and_manifest(altered, altered_parent, protocol, 7)
    with pytest.raises(ValueError, match='Parent committed trace'):
        recovery.recover_encoded_export(protocol, altered, altered_parent, root/'reject-parent-trace', seed=7, crash_manifest=path)


def test_incomplete_saved_checkpoint_rejected_without_forward(real_short_run):
    protocol, parent, crashed, _, root, _ = real_short_run
    altered = root/'incomplete-checkpoint'
    shutil.copytree(crashed, altered)
    shutil.copyfile(parent/'checkpoint.json', altered/'checkpoint.json')
    path = _launch_and_manifest(altered, parent, protocol, 7)
    with pytest.raises(ValueError, match='complete native gates and no pending'):
        recovery.recover_encoded_export(protocol, altered, parent, root/'reject-incomplete', seed=7, crash_manifest=path)
    assert not (root/'reject-incomplete').exists()


def test_compact_audit_fields_produce_the_identical_complete_operation_schedule(real_short_run):
    _, _, crashed, _, _, _ = real_short_run
    from neutral_atom_env import NeutralAtomEnv
    from neutral_atom_env.replay.operation_codec import plan_from_dict
    from neutral_atom_experiments.qec_pbc.physical import operation_schedule
    state = NeutralAtomEnv.restore((crashed/'checkpoint.json').read_text(encoding='utf-8')).state
    plans = [plan_from_dict(value) for value in recovery.iter_json_array(crashed/'plans.json')]
    full = [json.loads(raw) for raw in state.trace.records]
    compact = list(runner.compact_audit_trace(state.trace.records))
    assert operation_schedule(plans, full) == operation_schedule(plans, compact)
    assert all('plan' not in row['event'] for row in compact)
    assert [row.get('reset_projection_results', {}) for row in full] == [row['reset_projection_results'] for row in compact]


def test_reviewed_runner_pair_is_exact_and_other_source_changes_rejected(real_short_run):
    _, _, crashed, _, _, _ = real_short_run
    metadata = json.loads((crashed/'run_metadata.json').read_text(encoding='utf-8'))
    key = 'neutral_atom_experiments/qec_pbc/encoded_physical.py'
    current = metadata['source_sha256'][key]
    metadata['source_sha256'][key] = '0'*64
    with pytest.raises(ValueError, match='Unreviewed recovery source change'):
        recovery._validate_sources(metadata, None)
    assert recovery._validate_sources(metadata, ('0'*64,current))[key] == {'original':'0'*64,'recovery':current}
    metadata['source_sha256']['neutral_atom_env/replay/trace.py'] = '0'*64
    with pytest.raises(ValueError, match='Unreviewed recovery source change'):
        recovery._validate_sources(metadata, ('0'*64,current))


def test_seed_and_source_hash_structure_rejected(real_short_run):
    protocol, parent, crashed, manifest, root, _ = real_short_run
    with pytest.raises(ValueError, match='initial checkpoint'):
        recovery.recover_encoded_export(protocol, crashed, parent, root/'wrong-seed', seed=8, crash_manifest=manifest)
    metadata = json.loads((crashed/'run_metadata.json').read_text(encoding='utf-8'))
    metadata['source_sha256']['neutral_atom_env/replay/trace.py'] = 'g'*64
    with pytest.raises(ValueError, match='invalid structure'):
        recovery._validate_crash_provenance(crashed, metadata, manifest, protocol, 7)


def test_same_id_parent_plan_operation_tampering_rejected(real_short_run):
    protocol, parent, crashed, manifest, root, _ = real_short_run
    altered_parent, altered = root/'same-id-parent', root/'same-id-child'
    shutil.copytree(parent, altered_parent)
    shutil.copytree(crashed, altered)
    metadata = json.loads((altered/'run_metadata.json').read_text(encoding='utf-8'))
    metadata['resume']['prefix_directory'] = str(altered_parent)
    (altered/'run_metadata.json').write_text(canonical_json(metadata), encoding='utf-8')
    plans = json.loads((altered_parent/'plans.json').read_text(encoding='utf-8'))
    plans[0]['operations'][0]['duration_us'] += 1
    (altered_parent/'plans.json').write_text(canonical_json(plans), encoding='utf-8')
    path = _launch_and_manifest(altered, altered_parent, protocol, 7)
    output = root/'reject-parent-operation'
    with pytest.raises(ValueError, match='Parent accepted-plan prefix contents differ'):
        recovery.recover_encoded_export(protocol, altered, altered_parent, output, seed=7, crash_manifest=path)
    assert not output.exists()


@pytest.mark.parametrize('key', ['../escape.py','/absolute.py','C:/escape.py','neutral_atom_env/./x.py'])
def test_source_guard_rejects_noncanonical_keys_before_file_access(real_short_run, key):
    _, _, crashed, _, _, _ = real_short_run
    metadata = json.loads((crashed/'run_metadata.json').read_text(encoding='utf-8'))
    metadata['source_sha256'][key] = '0'*64
    with pytest.raises(ValueError, match='canonical relative paths'):
        recovery._validate_sources(metadata, None)


def test_replay_failure_preserves_new_prefix_without_completed_evidence(real_short_run, monkeypatch):
    protocol, parent, crashed, manifest, root, _ = real_short_run
    def fail(_):
        raise RuntimeError('Injected recovery observer failure')
    output = root/'failed-new-recovery'
    with pytest.raises(RuntimeError, match='observer failure'):
        recovery.recover_encoded_export(protocol, crashed, parent, output, seed=7,
                                       crash_manifest=manifest, progress=fail)
    failed = json.loads((output/'recovery_failure.json').read_text(encoding='utf-8'))
    assert failed['status'] == 'failed' and not failed['completed_claim']
    assert (output/'checkpoint.json').exists() and not (output/'evidence.json').exists()


@pytest.mark.parametrize('subpath', ['evidence.json','new-output','nested/new.log'])
def test_output_and_diagnostic_paths_cannot_write_inside_original_archives(real_short_run, subpath):
    protocol, parent, crashed, manifest, _, _ = real_short_run
    for archive in (parent, crashed):
        path = archive/subpath
        with pytest.raises(ValueError, match='outside original archives'):
            recovery.require_outside_archives(path, crashed, parent)
        with pytest.raises(ValueError, match='outside original archives'):
            recovery.recover_encoded_export(protocol, crashed, parent, path, seed=7, crash_manifest=manifest)


def test_resolved_directory_alias_cannot_write_to_original_archive(real_short_run):
    _, parent, crashed, _, root, _ = real_short_run
    alias = root/'archive-alias'
    if os.name == 'nt':
        result = subprocess.run(['cmd','/c','mklink','/J',str(alias),str(crashed)], capture_output=True, text=True)
        assert result.returncode == 0, result.stdout+result.stderr
    else:
        alias.symlink_to(crashed, target_is_directory=True)
    assert alias.resolve() == crashed.resolve()
    with pytest.raises(ValueError, match='outside original archives'):
        recovery.require_outside_archives(alias/'missing-evidence.json', crashed, parent)
    assert not (crashed/'missing-evidence.json').exists()


@pytest.mark.parametrize('inside', ['fault_log','output'])
def test_cli_rejects_original_archive_paths_before_creating_missing_file(real_short_run, monkeypatch, inside):
    _, parent, crashed, manifest, root, _ = real_short_run
    fault = crashed/'evidence.json' if inside == 'fault_log' else root/'fresh-fault.log'
    output = crashed/'new-output' if inside == 'output' else root/'new-cli-result'
    assert not fault.exists() and not output.exists()
    monkeypatch.setattr(sys, 'argv', ['encoded_export_recovery', '--basis','X','--rounds','1','--seed','7',
        '--crashed',str(crashed),'--parent',str(parent),'--output',str(output),
        '--crash-manifest',str(manifest),'--fault-log',str(fault)])
    with pytest.raises(ValueError, match='outside original archives'):
        recovery.main()
    assert not fault.exists() and not output.exists()
