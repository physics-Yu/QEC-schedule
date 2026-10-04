"""Accepted reports must remain bound to their audited committed recording."""
import hashlib
from html.parser import HTMLParser
import json

import pytest

from neutral_atom_experiments.qec_pbc.native_parallel_report import render_report


def report_inputs(directory, *, replay=True, replace_recording=False):
    original = b'{"operations":[]}'
    (directory/'recording.json').write_bytes(original + (b'\n' if replace_recording else b''))
    (directory/'summary.json').write_text(json.dumps({
        'status': 'completed', 'audit': {'independent_plan_replay_equal': replay}}))
    (directory/'independent-audit.json').write_text(json.dumps({
        'passed': True, 'artifact_sha256': {'recording.json': hashlib.sha256(original).hexdigest()}}))


def test_completed_label_cannot_hide_skipped_original_state_replay(tmp_path):
    report_inputs(tmp_path, replay=None)
    with pytest.raises(ValueError, match='original-state replay'):
        render_report(tmp_path)


def test_recording_replacement_cannot_reuse_stale_independent_acceptance(tmp_path):
    report_inputs(tmp_path, replace_recording=True)
    with pytest.raises(ValueError, match='independently audited artifact'):
        render_report(tmp_path)


@pytest.mark.parametrize('passed,hash_matches', ((False, True), (True, False)))
def test_interleaved_label_requires_matching_independent_layout_acceptance(tmp_path, passed, hash_matches):
    report_inputs(tmp_path)
    summary = json.loads((tmp_path/'summary.json').read_text())
    summary['placement_layout'] = 'interleaved'
    (tmp_path/'summary.json').write_text(json.dumps(summary))
    audit = json.loads((tmp_path/'independent-audit.json').read_text())
    (tmp_path/'patch-parallel-audit.json').write_text(json.dumps({
        'passed': passed, 'artifact_sha256': {
            'recording.json': audit['artifact_sha256']['recording.json'] if hash_matches else '0'*64}}))
    with pytest.raises(ValueError, match='recording-bound independent patch audit'):
        render_report(tmp_path)


@pytest.mark.parametrize('layout', ('legacy', 'interleaved', 'enola'))
def test_experiment_cards_and_audit_details_start_collapsed_with_all_bookmarks(tmp_path, monkeypatch, layout):
    """The wrapper keeps verified experiment context without competing with the main summary."""
    operations = []
    for i, (kind, gate_type) in enumerate([
            ('reset', 'RESET'), ('raman_rotation', 'H'),
            ('entangling_pulse', 'CZ'), ('measurement', 'MEASURE')]):
        operations.append({'kind': kind, 'gate_type': gate_type,
                           'gate_ids': [f'{gate_type}_0', f'{gate_type}_1'],
                           'start': 10*i, 'end': 10*i+1})
    operations += [
        {'kind': 'aod_move', 'aod_id': 'AOD_0', 'moving_count': 1, 'start': 40, 'end': 50},
        {'kind': 'aod_move', 'aod_id': 'AOD_MAGIC', 'moving_count': 1, 'start': 45, 'end': 55},
    ]
    if layout != 'legacy':
        operations += [{'kind': 'entangling_pulse', 'gate_type': 'CZ',
                        'gate_ids': [f'p0.check.round0.layer{layer}.cz.0'],
                        'start': layer*10+0.2, 'end': layer*10+0.3}
                       for layer in range(1, 5)]
    recording = {'operations': operations, 'start_time': 0, 'duration': 60,
                 'frames': [{'aods': {'AOD_0': {}, 'AOD_MAGIC': {}}}]}
    recording_bytes = json.dumps(recording).encode('utf-8')
    (tmp_path/'recording.json').write_bytes(recording_bytes)
    (tmp_path/'summary.json').write_text(json.dumps({
        'status': 'completed', 'audit': {'independent_plan_replay_equal': True},
        'patch_count': 2, 'physical_atom_count': 34,
        'placement_layout': layout, 'intra_patch_enabled': True,
        'pair_search_enabled': layout == 'enola'}), encoding='utf-8')
    (tmp_path/'independent-audit.json').write_text(json.dumps({
        'passed': True, 'artifact_sha256': {
            'recording.json': hashlib.sha256(recording_bytes).hexdigest()},
        'source_native_gate_count': 8, 'max_cz_batch': 2, 'physical_time_us': 60}),
        encoding='utf-8')
    if layout != 'legacy':
        (tmp_path/'patch-parallel-audit.json').write_text(json.dumps({
            'passed': True, 'artifact_sha256': {
                'recording.json': hashlib.sha256(recording_bytes).hexdigest()}}))
    monkeypatch.setattr('neutral_atom_env.visualization.viewer.write_bundle', lambda _directory: None)

    class ReportHierarchy(HTMLParser):
        def __init__(self):
            super().__init__()
            self.details = {}
            self.stack = []
            self.metric_parents = []

        def handle_starttag(self, tag, attrs):
            attributes = dict(attrs)
            if tag == 'details':
                self.stack.append(attributes.get('id'))
                self.details[attributes.get('id')] = attributes
            if tag == 'div' and attributes.get('class') == 'metrics':
                self.metric_parents.append(tuple(self.stack))

        def handle_endtag(self, tag):
            if tag == 'details':
                self.stack.pop()

    page = render_report(tmp_path).read_text(encoding='utf-8')
    hierarchy = ReportHierarchy()
    hierarchy.feed(page)
    assert hierarchy.metric_parents == [('experiment-metrics',)]
    assert set(hierarchy.details) == {'experiment-metrics', 'report-evidence'}
    assert all('open' not in attributes for attributes in hierarchy.details.values())
    assert '模型总耗时 / μs（含归还）' in page
    assert '<small>实际物理原子</small><strong>34</strong>' in page
    assert '<small>d=3 算法码块</small><strong>2</strong>' in page
    encoded_bookmarks = page.split('const bookmarks=', 1)[1].split(';let viewer;', 1)[0]
    bookmarks = json.loads(encoded_bookmarks)
    assert len(bookmarks) == (7 if layout == 'legacy' else 11)
    assert bookmarks[5] == {'label': '两台 AOD 同时运输', 'time': 47.5}
    assert bookmarks[-1] == {'label': '实际提交终态', 'time': 60}
    if layout != 'legacy':
        assert [b['label'] for b in bookmarks[6:10]] == [
            f'稳定子第 {layer} 层 · 1 个实际脉冲' for layer in range(1, 5)]
        assert '一轮稳定子提取 4 个真实 CZ 脉冲' in page
        assert '<tr><td>CZ</td><td>6</td><td>5</td></tr>' in page
