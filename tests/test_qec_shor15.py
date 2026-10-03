"""Full Shor reference checked independently of its Fourier/multiplier recipes."""
from dataclasses import replace
import math

import numpy as np
import pytest

from neutral_atom_experiments.qec_pbc.shor15 import (
    ShorGate, apply_gates, arithmetic_prefix, audit_shor15, basis_permutation_output,
    build_shor15, continued_fraction_convergents, controlled_modmul15,
    inverse_qft_gates, postprocess_sample, run_shor15, simulate_shor15, validate_order)
from neutral_atom_experiments.qec_pbc.shor_frontend import resource_report


@pytest.mark.parametrize('constant', (1, 2, 4, 8))
def test_controlled_multiplier_full_domain_and_inverse(constant):
    gates = controlled_modmul15(constant, 4, (0, 1, 2, 3))
    # All 16 work values, including invalid encoding 15, and both control values.
    matrix = np.zeros((32, 32), dtype=complex)
    for basis in range(32):
        control, work = basis >> 4, basis & 15
        target_work = constant * work % 15 if control and work < 15 else work
        target = (control << 4) | target_work
        assert basis_permutation_output(gates, basis) == target
        assert basis_permutation_output(reversed(gates), target) == basis
        matrix[target, basis] = 1
    # Verify coherent, entangled spectator input as well as classical truth tables.
    rng = np.random.default_rng(63 + constant)
    state = rng.normal(size=64) + 1j * rng.normal(size=64)
    state /= np.linalg.norm(state)
    expected = (state.reshape(2, 32) @ matrix.T).ravel()
    assert np.allclose(apply_gates(state, gates), expected, atol=1e-12)
    assert np.allclose(apply_gates(expected, reversed(gates)), state, atol=1e-12)


@pytest.mark.parametrize('bits', (1, 2, 3, 8))
def test_inverse_qft_matches_independent_fourier_on_entangled_input(bits):
    size = 1 << bits
    rng = np.random.default_rng(bits)
    # Four spectator states ensure transform acts only on declared phase wires.
    state = rng.normal(size=4 * size) + 1j * rng.normal(size=4 * size)
    state /= np.linalg.norm(state)
    expected = (np.fft.fft(state.reshape(4, size), axis=1) / math.sqrt(size)).ravel()
    actual = apply_gates(state, inverse_qft_gates(range(bits)))
    assert np.allclose(actual, expected, atol=1e-12)


def test_complete_circuit_amplitudes_distribution_and_bit_order():
    circuit = build_shor15()
    assert circuit.qubit_count == 12
    assert circuit.modular_constants == tuple(pow(2, 1 << i, 15) for i in range(8))
    assert len(circuit.gates) == 72
    # No opaque permutation, order oracle or placeholder operation is exported.
    assert {g.name for g in circuit.gates} == {'X', 'H', 'CX', 'CCX', 'CP'}
    reversible = [g for g in circuit.gates if g.stage in ('initialize', 'modexp')]
    for exponent in range(256):
        actual = basis_permutation_output(reversible, exponent)
        assert actual == exponent | (pow(2, exponent, 15) << 8)
    audit = audit_shor15(circuit)
    assert audit['statevector_amplitudes_checked'] == 4096
    assert audit['full_circuit_amplitude_max_error'] < 1e-12
    state, probabilities = simulate_shor15(circuit)
    expected = np.zeros(256)
    expected[[0, 64, 128, 192]] = 0.25
    assert np.allclose(probabilities, expected, atol=1e-12)
    assert np.isclose(np.linalg.norm(state), 1)
    export = circuit.to_dict()
    assert export['measurement_integer'] == 'sum(phase[i] * 2**i)'
    assert [m['qubit'] for m in export['measurements']] == list(range(8))
    assert all(export[k] is False for k in ('clifford_t_compiled', 'pbc_compiled', 'encoded', 'physical_executed'))


def test_arithmetic_prefix_can_use_existing_exact_frontend():
    prefix = arithmetic_prefix()
    report = resource_report(prefix)
    assert report['arithmetic_counts']['CCX'] == 5
    assert report['t_resource_consumptions'] == 35
    assert report['complete_shor'] is False
    assert report['qft_included'] is False
    assert all(kind != 'CP' for kind, _ in prefix.gates)


def test_audit_detects_phase_sign_error():
    circuit = build_shor15()
    gates = list(circuit.gates)
    index = next(i for i, g in enumerate(gates) if g.name == 'CP')
    gates[index] = replace(gates[index], angle_radians=-gates[index].angle_radians)
    with pytest.raises(AssertionError, match='amplitude/distribution'):
        audit_shor15(replace(circuit, gates=tuple(gates)))


@pytest.mark.parametrize('outcome,success,reason', (
    (0, False, 'zero_outcome'), (64, True, 'factored'),
    (128, False, 'order_not_recovered'), (192, True, 'factored')))
def test_measured_sample_and_continued_fractions(outcome, success, reason):
    result = postprocess_sample(outcome)
    assert result['success'] is success
    assert result['reason'] == reason
    assert result['phase_bits_little_endian'] == [(outcome >> i) & 1 for i in range(8)]
    if success:
        assert result['order'] == 4
        assert result['factors'] == [3, 5]
        assert pow(2, result['order'], 15) == 1
    else:
        assert result['factors'] is None
    assert continued_fraction_convergents(64, 256) == ((0, 1), (1, 4))


def test_wrong_order_and_period_multiple_are_rejected():
    assert validate_order(2, 15, 4)
    assert not validate_order(2, 15, 2)
    assert not validate_order(2, 15, 8)  # verified period but not the minimal order
    assert not validate_order(3, 15, 4)
    assert not validate_order(2, 15, 0)
    assert postprocess_sample(1)['reason'] == 'order_not_recovered'
    assert postprocess_sample(128, base=14)['reason'] == 'trivial_half_power'


def test_retry_is_visible_and_not_replaced_by_known_answer():
    result = run_shor15(outcomes=(0, 128, 64), max_attempts=3)
    assert [a['reason'] for a in result['attempts']] == ['zero_outcome', 'order_not_recovered', 'factored']
    assert result['factors'] == [3, 5]
    exhausted = run_shor15(outcomes=(0, 128, 64), max_attempts=2)
    assert exhausted['success'] is False
    assert exhausted['factors'] is None
    assert exhausted['order'] is None


def test_seeded_sampling_is_reproducible_and_can_fail_then_retry():
    result = run_shor15(seed=7)
    assert result == run_shor15(seed=7)
    assert [a['outcome'] for a in result['attempts']] == [128, 192]
    assert result['success'] and result['factors'] == [3, 5]
    assert run_shor15(seed=7, max_attempts=1)['success'] is False
    assert result['encoding_target']['base_patch_atoms'] == 204
    assert result['encoding_target']['magic_and_bus_atoms'] is None


def test_construction_has_no_order_or_factor_input():
    with pytest.raises(TypeError):
        build_shor15(order=4)
    with pytest.raises(TypeError):
        build_shor15(factors=(3, 5))
    circuit = build_shor15(phase_bits=10)
    assert circuit.modular_constants == tuple(pow(2, 1 << i, 15) for i in range(10))
    with pytest.raises(ValueError, match='computed'):
        replace(circuit, modular_constants=(2,) * 10)


@pytest.mark.parametrize('function,args', (
    (build_shor15, {'phase_bits': 3}), (build_shor15, {'phase_bits': True}),
    (controlled_modmul15, {'constant': 3, 'control': 4, 'work': range(4)}),
    (controlled_modmul15, {'constant': 2, 'control': 0, 'work': range(4)}),
    (postprocess_sample, {'outcome': 256}), (postprocess_sample, {'outcome': -1}),
    (postprocess_sample, {'outcome': 64, 'base': 3}),
    (run_shor15, {'max_attempts': 0}), (inverse_qft_gates, {'qubits': (0, 0)})))
def test_invalid_inputs(function, args):
    with pytest.raises(ValueError):
        function(**args)


def test_gate_validation():
    with pytest.raises(ValueError):
        ShorGate('CP', (0, 1), 'test', float('nan'))
    with pytest.raises(ValueError):
        ShorGate('CX', (0, 0), 'test')
    with pytest.raises(ValueError):
        ShorGate('PERMUTATION', (0,), 'test')
