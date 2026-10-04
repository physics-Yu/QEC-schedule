"""Placement proposals preserve protocol inputs and require independent physics."""
import importlib.util
import json
from pathlib import Path
import random
import sys

import pytest


SPEC = importlib.util.spec_from_file_location(
    'enola_patch_proposal', Path(__file__).parents[1] / 'tools/propose_enola_patch_layout.py')
PROPOSAL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROPOSAL)

DIAMOND = [(0, 2), (1, 3), (2, 4), (1, 1), (2, 2), (3, 3), (2, 0),
           (3, 1), (4, 2), (1, 2), (3, 2), (1, 4), (3, 0), (2, 3),
           (2, 1), (0, 1), (4, 3)]


def test_canonical_inputs_keep_four_hook_order_layers_and_role_identity():
    roles, layers, protocol = PROPOSAL.protocol_input('sample')
    assert roles == [f'sample.d{i}' for i in range(9)] + [
        f'sample.{basis}{i}' for basis in ('X', 'Z') for i in range(4)]
    assert layers == [
        [(9, 3), (10, 7), (11, 1), (13, 4), (14, 6), (16, 8)],
        [(9, 4), (10, 8), (11, 2), (13, 1), (14, 3), (16, 5)],
        [(9, 0), (10, 4), (12, 6), (13, 5), (14, 7), (15, 3)],
        [(9, 1), (10, 5), (12, 7), (13, 2), (14, 4), (15, 0)],
    ]
    assert protocol['protocol_reordered'] is False
    assert protocol['source']['commit'] == '42e0b9e099180e8570407c33f87b4683cac00d81'
    assert 'CSS encoder excluded' in protocol['scope']


def test_weighted_proxy_has_independent_known_value_and_no_time_or_fidelity():
    _, layers, _ = PROPOSAL.protocol_input()
    score = PROPOSAL.distance_proxy(DIAMOND, layers)
    # Every one of the 24 declared edges has length 1 at this diamond placement.
    assert score['weighted_site_distance'] == pytest.approx(6 * (1 + .9 + .8 + .7))
    assert score['unweighted_pair_distance_um'] == 240
    assert score['physical_execution_time_us'] is None
    assert score['fidelity'] is None


@pytest.mark.parametrize('kind', ['missing', 'overlap', 'outside', 'float'])
def test_mapping_rejects_incomplete_overlapping_or_nonlattice_homes(kind):
    mapping = list(DIAMOND)
    if kind == 'missing':
        mapping.pop()
    elif kind == 'overlap':
        mapping[-1] = mapping[0]
    elif kind == 'outside':
        mapping[-1] = (5, 0)
    else:
        mapping[-1] = (4., 3)
    with pytest.raises(ValueError):
        PROPOSAL.validate_mapping(mapping, 5, 5)


def test_native_import_and_failure_restore_rng_and_bytecode_state(tmp_path):
    # Test the import/call boundary with an intentionally failing external module.
    source = tmp_path / 'placer.py'
    source.write_text('import random\nrandom.seed(0)\n'
        'def place_qubit(*args):\n random.seed(75)\n raise RuntimeError("native-failure")\n')
    rng_before = random.getstate()
    bytecode_before = sys.dont_write_bytecode
    path_before = list(sys.path)
    modules_before = set(sys.modules)
    with pytest.raises(RuntimeError, match='native-failure'):
        PROPOSAL._run_native_placer(source, 5, 5, [], 17)
    assert random.getstate() == rng_before
    assert sys.dont_write_bytecode == bytecode_before
    assert sys.path == path_before
    assert '_enola_frozen_patch_sa' not in set(sys.modules) - modules_before
    assert not (tmp_path / '__pycache__').exists()


def test_wrong_official_bytes_rejected_before_any_native_call(tmp_path, monkeypatch):
    source = tmp_path / 'enola/placer/placer.py'
    source.parent.mkdir(parents=True)
    source.write_text('def place_qubit(*a): return []\n')
    monkeypatch.setattr(PROPOSAL, '_run_native_placer',
        lambda *args: pytest.fail('Untrusted native code must not run'))
    with pytest.raises(ValueError, match='pinned official source'):
        PROPOSAL.propose_layout(tmp_path)


def _mock_author_boundary(monkeypatch, tmp_path, mapping=DIAMOND):
    source = tmp_path / 'placer.py'
    source.write_bytes(b'unit-test-fixture')
    monkeypatch.setattr(PROPOSAL, '_frozen_source', lambda unused: (
        source, b'unit-test-fixture', {'fixture_only': True}))
    monkeypatch.setattr(PROPOSAL, '_run_native_placer',
        lambda *args: (mapping, .1, 'unit-test fixture; not official execution'))
    return source


def test_conversion_keeps_ten_um_homes_on_five_um_slm_grid(tmp_path, monkeypatch):
    _mock_author_boundary(monkeypatch, tmp_path)
    result = PROPOSAL.propose_layout(tmp_path, patch='work0')
    assert result['coordinates_um']['work0.d0'] == [0, 20]
    assert result['slm_grid_coordinates']['work0.d0'] == [0, 4]
    assert result['minimum_home_distance_um'] == 10
    assert len(result['coordinates_um']) == 17
    for role, point in result['coordinates_um'].items():
        assert point == [5 * value for value in result['slm_grid_coordinates'][role]]
    assert result['placement_sha256'] == PROPOSAL._sha(
        PROPOSAL._canonical_bytes(result['coordinates_um']))
    assert 'no routing, Executor' in result['scope']
    assert result['comparison']['enola_sa']['physical_execution_time_us'] is None
    assert result['protocol']['protocol_reordered'] is False
    json.dumps(result, allow_nan=False)


def test_source_changes_during_call_are_not_silently_accepted(tmp_path, monkeypatch):
    source = _mock_author_boundary(monkeypatch, tmp_path)
    def changed(*args):
        source.write_bytes(b'changed')
        return DIAMOND, 0., ''
    monkeypatch.setattr(PROPOSAL, '_run_native_placer', changed)
    with pytest.raises(RuntimeError, match='source changed'):
        PROPOSAL.propose_layout(tmp_path)


def test_existing_attempt_directory_is_preserved(tmp_path):
    output = tmp_path / 'attempt'
    output.mkdir()
    receipt = output / 'proposal.json'
    receipt.write_text('previous evidence')
    with pytest.raises(FileExistsError):
        PROPOSAL.main(['--source', str(tmp_path), '--output', str(output)])
    assert receipt.read_text() == 'previous evidence'


def test_invalid_rectangle_and_seed_reject_without_import(tmp_path, monkeypatch):
    monkeypatch.setattr(PROPOSAL, '_frozen_source',
        lambda *args: pytest.fail('Configuration rejected before reading source'))
    for options in ({'width': 4, 'height': 4}, {'width': True}, {'seed': -1}):
        with pytest.raises(ValueError):
            PROPOSAL.propose_layout(tmp_path, **options)
