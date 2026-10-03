"""Independent CSS-projector codewords and native-circuit isometry tests."""
from collections import Counter

import numpy as np
import pytest

from neutral_atom_env.circuit import PhysicalCircuit
from neutral_atom_env.domain.models import PhysicalGate
from neutral_atom_env.quantum.stabilizer import StabilizerState
from neutral_atom_experiments.qec_pbc.encoded_resource_reference import (
    apply_native_unitaries, audit_code_distance, build_css_isometry, build_encoded_resource,
    execute_resource_reference, gf2_rank)
from neutral_atom_experiments.qec_pbc.pauli import PauliProduct
from neutral_atom_experiments.qec_pbc.surface import logical_product, patch_roles, stabilizers


M = {'I': np.eye(2), 'X': np.array([[0, 1], [1, 0]]),
     'Y': np.array([[0, -1j], [1j, 0]]), 'Z': np.diag([1, -1])}


def matrix(p, data):
    result = np.array([[p.sign]], dtype=complex)
    factors = dict(p.factors)
    for wire in data:
        result = np.kron(result, M[factors.get(wire, 'I')])
    return result


@pytest.fixture(scope='module')
def projector_codewords():
    data = tuple(f'A.d{i}' for i in range(9))
    psi = np.zeros(512, dtype=complex)
    psi[0] = 1
    checks = tuple(matrix(p, data) for p in stabilizers('A'))
    # Direct eight CSS projectors, without a GF(2) transform or encoder gates.
    for check in checks:
        psi = (psi + check @ psi) / 2
    psi /= np.linalg.norm(psi)
    lx = matrix(logical_product(PauliProduct((('A', 'X'),))), data)
    return np.column_stack((psi, lx @ psi)), checks


def embedded_input(logical_reference):
    logical_reference = np.asarray(logical_reference)
    refs = (len(logical_reference) // 2).bit_length() - 1
    result = np.zeros((2, 256, 1 << refs), dtype=complex)
    result[:, 0, :] = logical_reference.reshape(2, 1 << refs)
    return result.ravel(), refs


def test_gf2_columns_and_native_cnot_network_all_512_computational_inputs():
    encoder = build_css_isometry()
    a = np.array(encoder.matrix_rows, dtype=int)
    assert a.shape == (9, 9) and gf2_rank(encoder.column_masks) == 9
    assert len(encoder.completion_basis_indices) == 4
    for i in range(512):
        bits = np.array([(i >> (8 - q)) & 1 for q in range(9)], dtype=int)
        transformed = a @ bits % 2
        target = sum(int(bit) << (8 - q) for q, bit in enumerate(transformed))
        psi = np.zeros(512, dtype=complex)
        psi[i] = 1
        actual = apply_native_unitaries(encoder.linear_circuit, psi, encoder.data_qubits)
        expected = np.zeros(512, dtype=complex)
        expected[target] = 1
        assert np.max(abs(actual - expected)) < 2e-13
    assert {g.gate_type for g in encoder.linear_circuit.gates} == {'H', 'CZ'}


def test_native_zero_one_isometry_equals_independent_css_projector_oracle(projector_codewords):
    codewords, checks = projector_codewords
    encoder = build_css_isometry()
    actual = []
    for bit in range(2):
        psi = np.zeros(512, dtype=complex)
        psi[bit << 8] = 1
        actual.append(apply_native_unitaries(encoder.isometry_circuit, psi, encoder.data_qubits))
    v = np.column_stack(actual)
    assert np.max(abs(v - codewords)) < 2e-13  # complex phase, not overlap only
    assert np.allclose(v.conj().T @ v, np.eye(2), atol=1e-13)
    for check in checks:
        assert np.max(abs(check @ v - v)) < 2e-13
    for kind in 'XYZ':
        encoded = matrix(logical_product(PauliProduct((('A', kind),))), encoder.data_roles)
        assert np.allclose(encoded @ v, v @ M[kind], atol=2e-13)


@pytest.mark.parametrize('seed', (2, 19, 744))
def test_arbitrary_complex_input_entangled_with_reference_keeps_exact_logical_isometry(seed, projector_codewords):
    v, checks = projector_codewords
    encoder = build_css_isometry()
    rng = np.random.default_rng(seed)
    logical_reference = rng.normal(size=4) + 1j * rng.normal(size=4)
    logical_reference /= np.linalg.norm(logical_reference)
    initial, refs = embedded_input(logical_reference)
    actual = apply_native_unitaries(encoder.isometry_circuit, initial, encoder.data_qubits, reference_qubits=refs)
    expected = np.kron(v, np.eye(2)) @ logical_reference
    assert np.max(abs(actual - expected)) < 2e-13
    for check in checks:
        assert np.allclose(np.kron(check, np.eye(2)) @ actual, actual, atol=2e-13)


@pytest.mark.parametrize('sign', (1, -1))
@pytest.mark.parametrize('syndrome', (False, True))
def test_native_t_resources_actual_preparation_and_optional_real_syndrome(sign, syndrome, projector_codewords):
    v, checks = projector_codewords
    prepared = build_encoded_resource(sign=sign, syndrome_round=syndrome)
    result = execute_resource_reference(prepared, seed=7)
    expected_data = v @ (np.array([1, np.exp(1j * sign * np.pi / 4)]) / np.sqrt(2))
    data_aux = result.state.reshape(512, 256)
    assert np.max(abs(data_aux[:, 0] - expected_data)) < 2e-13
    assert np.max(abs(data_aux[:, 1:])) < 2e-13
    for check in checks:
        assert np.max(abs(check @ data_aux[:, 0] - data_aux[:, 0])) < 2e-13
    for kind in 'XYZ':
        p = matrix(logical_product(PauliProduct((('A', kind),))), tuple(f'A.d{i}' for i in range(9)))
        expected = 0 if kind == 'Z' else 1 / np.sqrt(2) * (sign if kind == 'Y' else 1)
        assert abs(np.vdot(data_aux[:, 0], p @ data_aux[:, 0]) - expected) < 2e-13
    assert len(result.measurement_records) == (8 if syndrome else 0)
    assert all(r['outcome'] == 0 and abs(r['conditional_probability'] - 1) < 2e-13 for r in result.measurement_records)
    assert {r['id'] for r in result.measurement_records} == {gid for _, gid in prepared.syndrome_measurements}
    assert len(result.reset_records) == (25 if syndrome else 17)
    assert result.to_dict()['resource_lifecycle']['status'] == 'prepared'
    assert result.to_dict()['resource_lifecycle']['consumed'] is False
    assert result.to_dict()['physical_execution'] is False and not result.state.flags.writeable


def test_reset_gates_really_project_and_reset_every_atom_from_nonzero_native_input(projector_codewords):
    v, _ = projector_codewords
    initial = np.zeros(1 << 17, dtype=complex)
    initial[-1] = 1
    prepared = build_encoded_resource(sign=-1, syndrome_round=False)
    result = execute_resource_reference(prepared, initial_state=initial, seed=18)
    assert [r['projected_bit'] for r in result.reset_records] == [1] * 17
    expected = v @ (np.array([1, np.exp(-1j * np.pi / 4)]) / np.sqrt(2))
    assert np.max(abs(result.state.reshape(512, 256)[:, 0] - expected)) < 2e-13
    assert np.array_equal(initial[-1:], [1])  # input snapshot is not modified


def test_native_menu_cost_ids_role_mapping_and_dependency_frontier():
    plus = build_encoded_resource(sign=1)
    minus = build_encoded_resource(sign=-1)
    allowed = {'RESET', 'H', 'T', 'CZ', 'MEASURE'}
    assert {g.gate_type for g in plus.circuit.gates} <= allowed
    assert Counter(g.gate_type for g in plus.circuit.gates)['T'] == 1
    assert Counter(g.gate_type for g in minus.circuit.gates)['T'] == 7
    assert len(minus.circuit.gates) == len(plus.circuit.gates) + 6
    assert len(plus.bindings) == 17
    assert {g.qubit_ids[0] for g in plus.circuit.gates[:17]} == set(plus.qubits)
    assert all(g.gate_type == 'RESET' for g in plus.circuit.gates[:17])
    before = set()
    for gate in plus.circuit.gates:
        assert set(gate.depends_on) <= before
        assert not gate.condition and not gate.parameters
        before.add(gate.id)
    metadata = plus.to_dict()
    assert metadata['resource_lifecycle']['status'] == 'preparation_circuit_defined'
    assert metadata['complete_algorithm_encoded'] is False and metadata['magic_factory'] is False
    custom = {r.id: f'atom-{i}' for i, r in enumerate(patch_roles('magic'))}
    renamed = build_encoded_resource(patch='magic', namespace='another', bindings=custom, syndrome_round=False)
    assert set(renamed.qubits) == set(custom.values())
    assert all(g.id.startswith('another.') for g in renamed.circuit.gates)


def test_static_code_distance_three_and_nontrivial_logical_witness():
    audit = audit_code_distance()
    assert audit['code_distance'] == 3 and audit['stabilizer_group_size'] == 256
    witness = PauliProduct(tuple(tuple(pair) for pair in audit['logical_witness']['factors']))
    assert len(witness.support) == 3
    assert all(witness.commutes_with(check) for check in stabilizers('A'))
    lx = logical_product(PauliProduct((('A', 'X'),)))
    lz = logical_product(PauliProduct((('A', 'Z'),)))
    assert not (witness.commutes_with(lx) and witness.commutes_with(lz))


def test_tracked_env_still_rejects_native_t_and_no_new_representation_is_installed():
    state = StabilizerState.zero(('Q000',))
    with pytest.raises(ValueError, match='Non-Clifford'):
        state.apply_gate('T', ('Q000',))
    assert state == StabilizerState.zero(('Q000',))


@pytest.mark.parametrize('bad', ('boolean_sign', 'zero_sign', 'syndrome_flag', 'missing_role', 'alias', 'namespace', 'data_count'))
def test_invalid_resource_and_encoder_inputs_are_rejected(bad):
    kwargs = {}
    if bad == 'boolean_sign':
        kwargs['sign'] = True
    elif bad == 'zero_sign':
        kwargs['sign'] = 0
    elif bad == 'syndrome_flag':
        kwargs['syndrome_round'] = 1
    elif bad in ('missing_role', 'alias'):
        mapping = {r.id: f'Q{i:03d}' for i, r in enumerate(patch_roles('A'))}
        if bad == 'missing_role':
            del mapping['A.d0']
        else:
            mapping['A.d1'] = mapping['A.d0']
        kwargs['bindings'] = mapping
    elif bad == 'namespace':
        kwargs['namespace'] = ''
    else:
        with pytest.raises(ValueError):
            build_css_isometry(data_qubits=('only-one',))
        return
    with pytest.raises(ValueError):
        build_encoded_resource(**kwargs)


def test_reference_never_silently_treats_reset_measurement_or_condition_as_unitary():
    psi = np.array([1, 0], dtype=complex)
    with pytest.raises(ValueError, match='unitary'):
        apply_native_unitaries(PhysicalCircuit((PhysicalGate('m', 'MEASURE', ('q',)),)), psi, ('q',))
    with pytest.raises(ValueError, match='shape'):
        apply_native_unitaries(PhysicalCircuit(()), psi, ('a', 'b'))
    prepared = build_encoded_resource(syndrome_round=False)
    with pytest.raises(ValueError, match='normalized'):
        execute_resource_reference(prepared, initial_state=np.zeros(1 << 17))


@pytest.mark.parametrize('bad', (-1, True))
def test_invalid_gf2_masks_cannot_enter_nonterminating_rank_reduction(bad):
    with pytest.raises(ValueError, match='integer masks'):
        gf2_rank((1, bad))
