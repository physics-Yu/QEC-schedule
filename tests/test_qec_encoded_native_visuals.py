"""Independent artifact binding and bounded response checks for native views."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from neutral_atom_experiments.qec_pbc.encoded_native_visuals import EncodedNativeView, render_viewer


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode()


def fixture_run(path):
    """Hand-authored stream, independent of the production native generator."""
    path.mkdir()
    fid = 'function.0000000'
    gates = [{'index': i, 'id': 'native.' + str(i), 'gate_type': 'MEASURE' if i % 2 else 'RESET',
              'qubit_ids': ['Q000'], 'depends_on': ['native.' + str(i-1)] if i else [],
              'condition': [], 'epoch': 'resource.0', 'function_id': fid, 'source': 'independent_fixture'}
             for i in range(70)]
    projections = [{'index': i, 'native_gate_id': 'native.' + str(i),
                    'kind': g['gate_type'], 'outcome': i % 2,
                    'conditional_probability': .5 if i % 2 else 1.0,
                    'function_id': fid, 'source': 'fixture_native_born'} for i, g in enumerate(gates)]
    native = b''.join(map(encoded, gates))
    reports = b''.join(map(encoded, projections))
    before, after = {'sha256': 'a'*64, 'wires': ['phase0'], 'inverse_generator_images': [], 'ledger_length': 0}, {
        'sha256': 'b'*64, 'wires': ['phase0'], 'inverse_generator_images': [], 'ledger_length': 1,
        'last_correction': {'m': 1, 'r': 0}}
    row = {'index': 0, 'function_id': fid, 'kind': 'resource_readout_reset', 'shot_index': 0,
           'injection_index': 0, 'namespace': 'native', 'epoch': 'resource.0',
           'gate_start': 0, 'gate_end': 70, 'gate_count': 70, 'gate_byte_start': 0, 'gate_byte_end': len(native),
           'projection_start': 0, 'projection_count': 70, 'projection_byte_start': 0, 'projection_byte_end': len(reports),
           'native_sha256': hashlib.sha256(native).hexdigest(), 'projection_sha256': hashlib.sha256(reports).hexdigest(),
           'certificate_ids': ['kernel.native'], 'depends_on': [], 'frame_before_sha256': before['sha256'],
           'frame_after_sha256': after['sha256'], 'logical_result': 1, 'conditional_probability': .5,
           'raw_parity': {'keys': ['native.1', 'native.3'], 'constant': 0, 'bit': 1},
           'context': {'all_nine_data_reset': True, 'environment_committed': False}}
    values = {'summary.json': {'logical_width': 12, 'native_gate_count': 70, 'native_projection_count': 70,
                              'attempts': [{'shot_index': 0, 'phase_outcome': 128, 'classical_postprocessing': {'success': False}}]},
              'roles.json': {'roles': [{'id': 'Q000', 'role': 'phase0.d0', 'kind': 'data', 'patch': 'phase0'}],
                             'algorithm_patches': ['phase0'], 'code_checks': {'X': [[0, 1, 3, 4]]}},
              'certificates.json': {'certificates': {'kernel.native': {'kind': 'qualified_actual_native', 'passed': True}}}}
    for name, value in values.items():
        (path/name).write_bytes(encoded(value))
    (path/'functions.jsonl').write_bytes(encoded(row))
    (path/'native_gates.jsonl').write_bytes(native)
    (path/'native_projections.jsonl').write_bytes(reports)
    (path/'frames.jsonl').write_bytes(encoded(before)+encoded(after))
    rebind_manifest(path)
    return fid


def rebind_manifest(path):
    descriptors = {p.name: {'sha256': hashlib.sha256(p.read_bytes()).hexdigest(), 'bytes': p.stat().st_size}
                   for p in path.iterdir() if p.name != 'manifest.json'}
    (path/'manifest.json').write_bytes(encoded({'complete': True, 'physical_executed': False,
                                               'scope': 'reference_only', 'artifacts': descriptors}))


def change_function(path, **fields):
    p = path/'functions.jsonl'
    row = json.loads(p.read_bytes())
    row.update(fields)
    p.write_bytes(encoded(row))
    rebind_manifest(path)


def test_exact_paged_native_and_projection_identity_probability_and_frames(tmp_path):
    path = tmp_path/'run'
    fid = fixture_run(path)
    view = EncodedNativeView(path)
    overview = view.overview()
    assert overview['axis'] == 'native_gate_index'
    assert overview['native_time_us'] is None and overview['physical_executed'] is False
    assert overview['summary']['attempts'][0]['classical_postprocessing']['success'] is False
    listing = view.list_functions(shot=0, injection=0, kind='resource_readout_reset', count=12)
    assert listing['total'] == 1 and listing['functions'][0]['function_id'] == fid
    detail = view.function_detail(fid, gate_page=1, projection_page=1)
    assert [g['index'] for g in detail['gates']['records']] == list(range(12, 24))
    assert [p['index'] for p in detail['projections']['records']] == list(range(64, 70))
    assert detail['projections']['records'][1]['conditional_probability'] == .5
    assert detail['gates']['records'][0]['depends_on'] == ['native.11']
    assert detail['gates']['span_verified'] is True
    assert [p['native_gate_id'] for p in detail['projections']['related_records']] == ['native.'+str(i) for i in range(12, 24)]
    assert detail['frame_after']['last_correction'] == {'m': 1, 'r': 0}
    assert detail['certificates']['kernel.native']['kind'] == 'qualified_actual_native'
    assert view.list_functions(shot=1)['total'] == 0
    assert not view.function_detail(fid, gate_page=6)['gates']['records']


@pytest.mark.parametrize('name', ['native_gates.jsonl', 'native_projections.jsonl', 'functions.jsonl',
                                  'frames.jsonl', 'roles.json', 'certificates.json', 'summary.json'])
def test_any_unbound_byte_mutation_is_rejected(tmp_path, name):
    path = tmp_path/'run'
    fixture_run(path)
    with (path/name).open('ab') as stream:
        stream.write(b' ')
    with pytest.raises(ValueError, match='bytes/hash differ'):
        EncodedNativeView(path)


@pytest.mark.parametrize('fields,reason', [
    ({'native_sha256': '0'*64}, 'count/hash'),
    ({'projection_sha256': '0'*64}, 'count/hash'),
    ({'gate_byte_start': 1}, 'JSON'),
    ({'gate_byte_end': 1}, 'align'),
    ({'gate_start': 1, 'gate_end': 71}, 'index/identity'),
    ({'projection_count': 69}, 'count/hash'),
    ({'certificate_ids': ['missing.kernel']}, 'missing bound kernel'),
    ({'frame_after_sha256': 'c'*64}, 'missing bound frame'),
])
def test_rebound_global_manifest_cannot_hide_wrong_local_binding(tmp_path, fields, reason):
    path = tmp_path/'run'
    fid = fixture_run(path)
    change_function(path, **fields)
    view = EncodedNativeView(path)
    with pytest.raises((ValueError, json.JSONDecodeError), match=reason):
        view.function_detail(fid)


def test_mutation_after_initial_verification_never_reuses_cached_pass(tmp_path):
    path = tmp_path/'run'
    fid = fixture_run(path)
    view = EncodedNativeView(path)
    assert view.function_detail(fid)['gates']['span_verified']
    p = path/'native_gates.jsonl'
    p.write_bytes(p.read_bytes().replace(b'native.0', b'forged.0'))
    with pytest.raises(ValueError, match='changed after verification'):
        view.function_detail(fid, gate_page=1)


def test_rebound_report_cannot_alias_an_unemitted_native_gate(tmp_path):
    path = tmp_path/'run'
    fid = fixture_run(path)
    reports = path/'native_projections.jsonl'
    reports.write_bytes(reports.read_bytes().replace(b'"native_gate_id":"native.0"', b'"native_gate_id":"forged.0"'))
    change_function(path, projection_sha256=hashlib.sha256(reports.read_bytes()).hexdigest())
    with pytest.raises(ValueError, match='emitted M/RESET'):
        EncodedNativeView(path).function_detail(fid)


def test_cat_stage_controls_bind_exact_id_prefix_and_indices(tmp_path):
    path = tmp_path/'run'
    fid = fixture_run(path)
    gates = path/'native_gates.jsonl'
    payload = gates.read_bytes().replace(b'"id":"native.0"', b'"id":"actual.prepare.reset0"')
    gates.write_bytes(payload)
    projections = path/'native_projections.jsonl'
    projections.write_bytes(projections.read_bytes().replace(b'"native_gate_id":"native.0"', b'"native_gate_id":"actual.prepare.reset0"'))
    change_function(path, kind='cat_joint', gate_byte_end=len(payload), native_sha256=hashlib.sha256(payload).hexdigest(),
                    projection_byte_end=projections.stat().st_size, projection_sha256=hashlib.sha256(projections.read_bytes()).hexdigest())
    detail = EncodedNativeView(path).function_detail(fid)
    first = detail['gates']['native_stages'][0]
    assert first == {'kind': 'cat_prepare', 'gate_start': 0, 'gate_offset': 0, 'gate_count': 1,
                     'first_native_id': 'actual.prepare.reset0', 'last_native_id': 'actual.prepare.reset0'}


@pytest.mark.parametrize('argument', [{'count': 101}, {'start': -1}, {'shot': True}, {'injection': -1}])
def test_function_query_bounds(tmp_path, argument):
    path = tmp_path/'run'
    fixture_run(path)
    with pytest.raises(ValueError):
        EncodedNativeView(path).list_functions(**argument)


def test_incomplete_or_physical_claim_and_path_escape_are_rejected(tmp_path):
    path = tmp_path/'run'
    fixture_run(path)
    manifest = json.loads((path/'manifest.json').read_bytes())
    for field, value in [('complete', False), ('physical_executed', True)]:
        changed = dict(manifest, **{field: value})
        (path/'manifest.json').write_bytes(encoded(changed))
        with pytest.raises(ValueError):
            EncodedNativeView(path)
    manifest['artifacts']['../escape.json'] = {'sha256': 'a'*64, 'bytes': 1}
    (path/'manifest.json').write_bytes(encoded(manifest))
    with pytest.raises(ValueError, match='single filenames'):
        EncodedNativeView(path)


def test_renderer_has_no_source_data_injection_and_requires_local_api(tmp_path):
    destination = render_viewer(tmp_path/'viewer.html', api_base='/api/test')
    html = destination.read_text(encoding='utf-8')
    assert '__ENCODED_NATIVE_CONFIG__' not in html
    assert json.loads(html.split('<script id="config" type="application/json">')[1].split('</script>')[0])['api_base'] == '/api/test'
    assert 'fetch(CFG.api_base' in html
    assert '复用已验证原生核' in html and '尚未物理执行' in html
    assert 'native_gate_index' not in html or '运输或μs' in html
    with pytest.raises(ValueError):
        render_viewer(destination, api_base='https://external.example/run')


def test_next_saved_axis_navigation_synchronizes_filters_and_selected_function(tmp_path):
    """Exercise the maintained JS navigation against independent API/UI doubles."""
    node = shutil.which('node')
    if node is None:
        pytest.skip('Node is required for the viewer navigation contract')
    html = render_viewer(tmp_path/'viewer.html').read_text(encoding='utf-8')
    navigation = html.split('async function navigateBoundFunction(id)', 1)[1].split('async function loadDetail', 1)[0]
    script = r'''
const assert=require('assert');
const controls={shot:{value:'0'},kind:{value:'frame_update'},injection:{value:'0'}};
const $=id=>controls[id];
const state={detail:{function:{function_id:'old.frame'}}};
const calls=[];
function stop(){calls.push('stop')}
async function api(name,params){assert.equal(name,'function');assert.equal(params.id,'next.cat');return {function:{function_id:'next.cat',shot_index:1,kind:'cat_joint',injection_index:3}}}
async function loadFunctions(reset){assert.equal(reset,true);assert.deepEqual(Object.fromEntries(Object.entries(controls).map(([k,v])=>[k,v.value])),{shot:'1',kind:'cat_joint',injection:'3'});calls.push('filtered_list');state.detail={function:{function_id:'next.cat'}}}
async function selectFunction(id){calls.push('selected:'+id);state.detail={function:{function_id:id}}}
'''+ 'async function navigateBoundFunction(id)' + navigation + r'''
(async()=>{await navigateBoundFunction('next.cat');assert.equal(state.detail.function.function_id,'next.cat');assert.deepEqual(calls,['stop','filtered_list']);console.log('next saved axis navigation verified')})().catch(e=>{console.error(e);process.exit(1)});
'''
    result = subprocess.run([node, '-e', script], text=True, capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert 'next saved axis navigation verified' in result.stdout
