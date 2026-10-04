"""MZ selection display uses real pulse IDs and distinguishes parallel costs."""
from copy import deepcopy
import hashlib
from html.parser import HTMLParser
import json

import pytest

from neutral_atom_experiments.qec_pbc.native_parallel_report import render_report


class Report(HTMLParser):
    def __init__(self, page):
        super().__init__()
        self.details = []
        self.buttons = []
        self.tables = []
        self.table = None
        self.row = None
        self.cell = None
        self.feed(page)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'details':
            self.details.append(attrs)
        elif tag == 'button':
            self.buttons.append(attrs)
        elif tag == 'table':
            self.table = []
            self.tables.append(self.table)
        elif tag == 'tr':
            self.row = []
            self.table.append(self.row)
        elif tag in ('td', 'th'):
            self.cell = ''

    def handle_data(self, data):
        if self.cell is not None:
            self.cell += data

    def handle_endtag(self, tag):
        if tag in ('td', 'th'):
            self.row.append(self.cell)
            self.cell = None
        elif tag == 'table':
            self.table = None


def inputs(directory, monkeypatch, *, routing=False):
    operations = [
        {'kind': 'reset', 'gate_type': 'RESET', 'gate_ids': ['r0', 'rmagic'], 'start': 10, 'end': 20},
        {'kind': 'raman_rotation', 'gate_type': 'H', 'gate_ids': ['h0'], 'start': 21, 'end': 22},
        {'kind': 'entangling_pulse', 'gate_type': 'CZ', 'gate_ids': ['cz0'], 'start': 30, 'end': 30.3},
        {'kind': 'measurement', 'gate_type': 'MEASURE', 'gate_ids': ['m0'], 'start': 50, 'end': 550},
        {'kind': 'aod_move', 'aod_id': 'AOD_0', 'moving_count': 1, 'start': 560, 'end': 580,
         'target_axes': {'x_um': [2.5 if routing else 5], 'y_um': [-20]}},
        {'kind': 'aod_move', 'aod_id': 'AOD_MAGIC', 'moving_count': 1, 'start': 570, 'end': 590},
    ]
    recording = {'operations': operations, 'start_time': 0, 'duration': 650,
                 'frames': [{'aods': {'AOD_0': {}, 'AOD_MAGIC': {}}}]}
    raw = json.dumps(recording).encode('utf-8')
    (directory/'recording.json').write_bytes(raw)
    summary = {'status': 'completed', 'audit': {'independent_plan_replay_equal': True},
               'patch_count': 1, 'physical_atom_count': 34, 'placement_layout': 'legacy'}
    if routing:
        summary['routing_policy'] = 'shortest-direct-or-halfgrid-v1'
    (directory/'summary.json').write_text(json.dumps(summary), encoding='utf-8')
    audit = {'passed': True, 'artifact_sha256': {'recording.json': hashlib.sha256(raw).hexdigest()},
             'source_native_gate_count': 5, 'max_cz_batch': 1, 'physical_time_us': 650}
    (directory/'independent-audit.json').write_text(json.dumps(audit), encoding='utf-8')
    monkeypatch.setattr('neutral_atom_env.visualization.viewer.write_bundle', lambda _directory: None)
    return audit


def selection(*, kind='MEASURE', aod='AOD_0', gate='m0', x=0, cost=610, policy='nearest_mz'):
    chosen = {'aod_id': aod, 'zone_id': 'MZ', 'target_pose_um': [x, -62.5],
              'positions': [['Q000', [x+10, -42.5]]], 'proxy_distance_um': 62.5,
              'estimated_us': 180, 'status': 'accepted', 'actual_us': cost,
              'actual_distance_um': 125}
    rejected = {'aod_id': aod, 'zone_id': 'MZ', 'target_pose_um': [x, -60],
                'positions': [['Q000', [x+10, -40]]], 'proxy_distance_um': 60,
                'estimated_us': 175, 'status': 'rejected', 'code': 'PATH_BLOCKED',
                'message': 'A nearby spectator blocks this route'}
    alternative = deepcopy(chosen)
    alternative.update(target_pose_um=[x, -65], actual_us=cost+40, actual_distance_um=130)
    return {'schema': 'rigid-readout-placement-decision/1', 'policy': policy,
            'aod_id': aod, 'source_origin_um': [x, 0], 'atom_ids': ['Q000'], 'support': 'aod',
            'generated': 15, 'generation_rejections': {'AOD_ENVELOPE_EXCEEDED': 2},
            'candidate_budget': 16, 'top_k': 2, 'candidates': [rejected, chosen, alternative],
            'selected': chosen, 'accepted': 2, 'status': 'selected', 'optimality_claim': False,
            'selection_scope': 'bounded legal complete services ranked by actual duration and distance',
            'kind': kind, 'gate_ids': [gate], 'included_reset_gate_ids': ['reset_after_m']}


def decisions(directory, selections, *, start=40, end=650):
    rows = [{'decision': 4, 'plan_id': 'readout-plan', 'kind': selections[0]['kind'],
             'start_us': start, 'end_us': end, 'duration_us': end-start,
             'readout_placement': selections[0]['policy'], 'readout_placement_decisions': selections}]
    (directory/'decisions.json').write_text(json.dumps(rows), encoding='utf-8')


def bookmarks(page):
    return json.loads(page.split('const bookmarks=', 1)[1].split(';let viewer;', 1)[0])


@pytest.mark.parametrize('routing', (False, True))
def test_historical_reports_without_placement_metadata_keep_bookmarks_and_hierarchy(tmp_path, monkeypatch, routing):
    inputs(tmp_path, monkeypatch, routing=routing)
    (tmp_path/'decisions.json').write_text(json.dumps([{'kind': 'MEASURE', 'gate_ids': ['m0']}]))
    page = render_report(tmp_path).read_text(encoding='utf-8')
    parsed = Report(page)
    assert {d.get('id') for d in parsed.details} == {'experiment-metrics', 'report-evidence'}
    assert all('open' not in d for d in parsed.details)
    assert len(bookmarks(page)) == (8 if routing else 7)
    assert bookmarks(page)[4] == {'label': 'MZ 综合征读出 × 1', 'time': 300}
    assert 'readout-locate' not in page


def test_real_mz_selection_details_are_collapsed_and_link_to_existing_measurement(tmp_path, monkeypatch):
    inputs(tmp_path, monkeypatch)
    decisions(tmp_path, [selection()])
    page = render_report(tmp_path).read_text(encoding='utf-8')
    parsed = Report(page)
    assert all('open' not in d for d in parsed.details)
    assert parsed.tables[0][1] == ['4', 'MEASURE × 1', 'AOD_0', 'nearest_mz', '(0.000, 0.000)',
        '(0.000, -62.500)', 'MZ', '15 / 3 / 2', '610.000', '610.000', '定位实际 MEASURE']
    assert parsed.tables[1][1][0] == '拒绝'
    assert parsed.tables[1][2][:6] == ['已选', '(0.000, -62.500)', '62.500', '180.000', '610.000', '125.000']
    assert parsed.tables[1][3][0] == '合法备选'
    assert parsed.tables[2][1] == ['Q000', '10.000', '-42.500']
    assert 'AOD_ENVELOPE_EXCEEDED: 2' in page and 'reset_after_m' in page
    assert '不证明连续空间或整个线路的全局最优' in page
    assert len(bookmarks(page)) == 7  # Reuse the actual M bookmark, no duplicate shortcut.
    locate = [b for b in parsed.buttons if b.get('class') == 'readout-locate']
    assert len(locate) == 1 and locate[0]['data-readout-time'] == '300.0'
    assert 'disabled' in locate[0]
    assert 'button.disabled=false' in page and 'button.dataset.readoutTime' in page
    assert page.index('id="physical-viewer"') < page.index('id="readout-placement"')
    assert 'overflow-x:auto;max-width:100%' in page


def test_dual_reset_keeps_independent_lane_cost_and_shared_committed_interval(tmp_path, monkeypatch):
    inputs(tmp_path, monkeypatch)
    decisions(tmp_path, [selection(kind='RESET', gate='r0', cost=38),
                        selection(kind='RESET', aod='AOD_MAGIC', gate='rmagic', x=100, cost=36)],
              start=0, end=40)
    page = render_report(tmp_path).read_text(encoding='utf-8')
    parsed = Report(page)
    assert [(row[2], row[8], row[9]) for row in parsed.tables[0][1:]] == [
        ('AOD_0', '38.000', '40.000'), ('AOD_MAGIC', '36.000', '40.000')]
    assert parsed.tables[0][2][5] == '(100.000, -62.500)'
    assert '两个单设备成本与重复区间均不能相加作总耗时' in page
    assert [b['data-readout-time'] for b in parsed.buttons if b.get('class') == 'readout-locate'] == ['15.0', '15.0']
    assert len(bookmarks(page)) == 7


def test_fixed_translation_metadata_is_labelled_as_a_control_not_automatic(tmp_path, monkeypatch):
    inputs(tmp_path, monkeypatch)
    entry = selection(policy='fixed_translation')
    entry.update(candidates=[entry['selected']], generated=1, candidate_budget=1, top_k=1)
    entry['selected'].pop('estimated_us')
    decisions(tmp_path, [entry])
    parsed = Report(render_report(tmp_path).read_text(encoding='utf-8'))
    assert parsed.tables[0][1][3] == 'fixed_translation'
    assert parsed.tables[0][1][7] == '1 / 1 / 1'
    assert parsed.tables[1][1][3] == '—'


def test_candidate_and_device_diagnostics_are_escaped_as_text(tmp_path, monkeypatch):
    inputs(tmp_path, monkeypatch)
    entry = selection(aod='<script>device</script>')
    entry['candidates'][0]['message'] = '<img src=x onerror=alert(1)>'
    decisions(tmp_path, [entry])
    page = render_report(tmp_path).read_text(encoding='utf-8')
    assert '&lt;script&gt;device&lt;/script&gt;' in page
    assert '&lt;img src=x onerror=alert(1)&gt;' in page
    assert '<img src=x' not in page and '<script>device' not in page


@pytest.mark.parametrize('invalid', ('missing', 'rejected', 'unlisted'))
def test_incomplete_or_unvalidated_selection_cannot_be_presented_as_a_chosen_target(tmp_path, monkeypatch, invalid):
    inputs(tmp_path, monkeypatch)
    entry = selection()
    if invalid == 'missing':
        entry['selected'] = None
    elif invalid == 'rejected':
        entry['selected'] = entry['candidates'][0]
    else:
        entry['selected'] = dict(entry['selected'], target_pose_um=[999, -60])
    decisions(tmp_path, [entry])
    with pytest.raises(ValueError, match='selected validated candidate'):
        render_report(tmp_path)


def test_placement_metadata_cannot_invent_a_readout_bookmark(tmp_path, monkeypatch):
    inputs(tmp_path, monkeypatch)
    decisions(tmp_path, [selection(gate='uncommitted_measure')])
    with pytest.raises(ValueError, match='corresponding committed pulse'):
        render_report(tmp_path)


def test_recording_bound_report_rejects_replaced_audited_decision_bytes(tmp_path, monkeypatch):
    audit = inputs(tmp_path, monkeypatch)
    decisions(tmp_path, [selection()])
    path = tmp_path/'decisions.json'
    audit['artifact_sha256']['decisions.json'] = hashlib.sha256(path.read_bytes()).hexdigest()
    (tmp_path/'independent-audit.json').write_text(json.dumps(audit), encoding='utf-8')
    path.write_bytes(path.read_bytes()+b'\n')
    with pytest.raises(ValueError, match='MZ decisions differ'):
        render_report(tmp_path)
