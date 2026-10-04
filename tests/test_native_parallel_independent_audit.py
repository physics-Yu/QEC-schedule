"""Counterexamples for the independent global-pair acceptance calculation."""
import importlib.util
import hashlib
import json
from pathlib import Path

import pytest


spec = importlib.util.spec_from_file_location('prefix_audit',
    Path(__file__).resolve().parents[1]/'tools/audit_native_parallel_physical.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)
ZONES = [{'zone_type': 'entanglement', 'bounds': {
    'lower': {'x_um': -100, 'y_um': -100}, 'upper': {'x_um': 100, 'y_um': 100}}}]


def p(x, y):
    return {'x_um': x, 'y_um': y}


def test_dense_five_um_occupied_grid_cannot_hide_static_spectator_pair():
    with pytest.raises(ValueError, match='extra'):
        audit.pair_geometry({'a': p(0, 0), 'b': p(-3, -3), 'spectator': p(5, 0)},
                            ZONES, 6, [('a', 'b')])


def test_diagonal_approach_on_sparse_ten_um_sublattice_is_isolated():
    assert audit.pair_geometry({'a': p(0, 0), 'b': p(-3, -3), 'spectator': p(10, 0)},
                               ZONES, 6, [('a', 'b')]) == 1


def test_arbitrary_logical_pair_still_requires_finite_cz_distance():
    with pytest.raises(ValueError, match='missing'):
        audit.pair_geometry({'a': p(0, 0), 'b': p(20, 0)}, ZONES, 6, [('a', 'b')])


def test_mask_phase_conversion_preserves_signed_y():
    assert audit.pauli_text((1, 1, 1), 1) == '+Y'
    assert audit.pauli_text((1, 1, 3), 1) == '-Y'
    assert audit.pauli_text((3, 3, 0), 2) == '-YY'


def test_independent_stim_refuses_forced_random_projection():
    import stim
    sim = stim.TableauSimulator()
    sim.h(0)
    with pytest.raises(ValueError, match='random projection'):
        audit.apply_stim(sim, {'gate_type': 'MEASURE', 'qubit_ids': ['a']}, {'a': 0})


def test_canceling_extra_gates_cannot_masquerade_as_source_prefix(tmp_path):
    original = [{'id': 'source-h', 'gate_type': 'H', 'qubit_ids': ['a']}]
    raw = b''.join((json.dumps(g, sort_keys=True, separators=(',', ':'))+'\n').encode()
                   for g in original)
    (tmp_path/'summary.json').write_text(json.dumps({'status': 'completed'}))
    (tmp_path/'source-prefix.json').write_text(json.dumps({
        'original_native_gates': original,
        'selected_native_prefix_sha256': hashlib.sha256(raw).hexdigest()}))
    extra = [{'id': f'extra-h-{i}', 'gate_type': 'H', 'qubit_ids': ['a']} for i in range(2)]
    (tmp_path/'prefix-circuit.json').write_text(json.dumps({'gates': original+extra}))
    with pytest.raises(ValueError, match='exact source gate identities'):
        audit.audit(tmp_path)


def test_disguised_cz_pulse_cannot_skip_global_geometry_audit():
    with pytest.raises(ValueError, match='effect kind'):
        audit.check_effect_kinds([{'kind': 'wait', 'gate_ids': ['cz']}],
            {'cz': {'gate_type': 'CZ', 'qubit_ids': ['a', 'b']}})


def test_disjoint_qubit_barrier_cannot_be_silently_overlapped():
    gates = [{'id': 'first', 'qubit_ids': ['a']},
             {'id': 'second', 'qubit_ids': ['b'], 'depends_on': ['first']}]
    effects = [{'gate_ids': ['first'], 'start': 0, 'end': 1},
               {'gate_ids': ['second'], 'start': 0, 'end': 1}]
    with pytest.raises(ValueError, match='circuit dependency'):
        audit.check_dependency_times(gates, effects)


def test_observer_pulse_cannot_be_moved_to_a_different_geometry_frame():
    effect = {'gate_ids': ['cz'], 'kind': 'entangling_pulse', 'start': 5, 'end': 6}
    boundaries = {('cz', 'operation_started'): (10, 'entangling_pulse'),
                  ('cz', 'operation_completed'): (11, 'entangling_pulse')}
    with pytest.raises(ValueError, match='committed operation trace'):
        audit.check_committed_intervals([effect], boundaries)


def test_hidden_foreign_spectator_cannot_escape_geometry_acceptance():
    with pytest.raises(ValueError, match='every live carrier'):
        audit.check_complete_positions({'a': p(0, 0), 'b': p(-3, -3)}, ['a', 'b', 'magic'])
