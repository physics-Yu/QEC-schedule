"""Phase-sensitive operator validation, including inactive Shor branches."""
import math
import numpy as np
import pytest

pytest.importorskip('pygridsynth', reason='optional pinned QFT synthesis dependency')
from neutral_atom_experiments.qec_pbc.qft_synthesis import (
    _rz_synthesis, apply_synthesized, audit_complete_shor_pbc, audit_qft_synthesis, synthesize_shor15)
from neutral_atom_experiments.qec_pbc.shor15 import build_shor15


@pytest.mark.parametrize('theta', (-math.pi / 4, math.pi / 4, math.pi / 16, -math.pi / 128))
def test_rz_approximation_keeps_phase_and_operator_budget(theta):
    names, phase, error = _rz_synthesis(theta, 1e-5, 7)
    matrix = np.eye(2, dtype=complex)
    matrices = {'H': np.array([[1, 1], [1, -1]]) / np.sqrt(2),
                'X': np.array([[0, 1], [1, 0]]), 'S': np.diag([1, 1j]),
                'T': np.diag([1, np.exp(1j * np.pi / 4)]),
                'Tdg': np.diag([1, np.exp(-1j * np.pi / 4)])}
    for name in names:
        matrix = matrices[name] @ matrix
    target = np.diag([np.exp(-1j * theta / 2), np.exp(1j * theta / 2)])
    measured = np.linalg.norm(np.exp(1j * phase) * matrix - target, ord=2)
    assert measured < 1e-5 and np.isclose(measured, error, atol=1e-14)
    if abs(theta) == math.pi / 4:
        assert len(names) == 1  # analytic exact case, not long approximations
        assert measured < 1e-14


def test_cp_rz_identity_phase_on_every_basis():
    theta = -math.pi / 64
    rz = lambda a: np.diag([np.exp(-1j * a / 2), np.exp(1j * a / 2)])
    cx = np.array([[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 0, 1], [0, 0, 1, 0]])
    actual = np.exp(1j * theta / 4) * cx @ np.kron(np.eye(2), rz(-theta / 2)) @ cx @ np.kron(rz(theta / 2), rz(theta / 2))
    assert np.allclose(actual, np.diag([1, 1, 1, np.exp(1j * theta)]), atol=1e-14)
    assert not np.allclose(actual * np.exp(-1j * theta / 4), np.diag([1, 1, 1, np.exp(1j * theta)]))


@pytest.fixture(scope='module')
def complete():
    return synthesize_shor15(total_error_budget=1e-3, seed=7)


def test_full_qft_operator_general_entangled_input_and_source_provenance(complete):
    audit = audit_qft_synthesis(complete)
    assert audit['passed'] and audit['qft_operator_columns_checked'] == 256
    assert audit['qft_operator_error'] < 1e-3
    assert audit['full_shor_probe_l2_error'] < 1e-3
    payload = complete.to_dict()
    assert payload['rz_synthesis_count'] == 84
    assert payload['qft_cp_count'] == 28
    assert payload['t_resource_consumptions'] == 3500
    assert payload['telescoping_design_bound'] <= 1e-3
    assert payload['measured_local_error_sum'] <= payload['telescoping_design_bound'] + 1e-12
    assert len(payload['source_gate_spans']) == 72
    for certificate in complete.rz_certificates:
        source = complete.source.gates[certificate['source_gate_index']]
        assert source.name == 'CP'
        assert certificate['source_cp_angle_radians'] == source.angle_radians
    assert payload['encoded'] is False and payload['physical_executed'] is False


def test_complete_circuit_can_reach_existing_pauli_frontend(complete):
    pauli = complete.compile_pauli()
    assert len(pauli.rotations) == 3500
    assert all(rotation.quarter_turns in (-1, 1) for rotation in pauli.rotations)
    assert pauli.wires == complete.wires


def test_shor_distribution_after_full_qft_synthesis(complete):
    initial = np.zeros(4096, dtype=complex)
    initial[0] = 1
    result = apply_synthesized(complete, initial)
    distribution = np.sum(abs(result.reshape(16, 256)) ** 2, axis=0)
    expected = np.zeros(256)
    expected[[0, 64, 128, 192]] = 0.25
    assert np.linalg.norm(distribution - expected, ord=1) < 2 * complete.total_error_budget
    assert np.isclose(distribution.sum(), 1, atol=1e-12)


def test_complete_shor_resource_measurements_zero_and_entangled_probe(complete):
    report = audit_complete_shor_pbc(complete, seed=7)
    assert report['passed'] and report['source_cp_gates_retained'] == 28
    assert report['resource_consumptions'] == 3500
    assert report['measurement_count_per_execution'] == 7000
    assert [case['name'] for case in report['cases']] == ['algorithm_zero_input', 'generic_entangled_probe']
    for case in report['cases']:
        assert case['instrument_l2_error'] < 2e-11
        assert case['exact_shor_l2_error'] < complete.total_error_budget
        assert case['all_resources_consumed']
        assert case['log2_branch_probability'] == -7000
        assert case['external_global_phase_radians_applied'] == complete.global_phase_radians
    assert report['encoded'] is False and report['physical_executed'] is False


@pytest.mark.parametrize('epsilon', (0, -1, 1, float('nan'), 1e-12))
def test_bad_error_budgets_are_rejected(epsilon):
    with pytest.raises(ValueError):
        synthesize_shor15(build_shor15(phase_bits=4), total_error_budget=epsilon)
