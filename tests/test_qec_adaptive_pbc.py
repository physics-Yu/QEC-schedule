"""Independent dense instrument/channel oracles for resource measurement IR."""
from itertools import product
from dataclasses import replace

import numpy as np
import pytest

from neutral_atom_experiments.qec_pbc.adaptive_pbc import audit_adaptive_pbc, compile_adaptive_pbc, execute_reference
from neutral_atom_experiments.qec_pbc.logical_pauli import LogicalGate, LogicalPauliProgram, PauliRotation, compile_logical_pauli
from neutral_atom_experiments.qec_pbc.pauli import PauliProduct
from neutral_atom_experiments.qec_pbc.shor15 import ShorGate, apply_gates, arithmetic_prefix
from neutral_atom_experiments.qec_pbc.shor_frontend import compile_arithmetic


M = {'I': np.eye(2), 'X': np.array([[0, 1], [1, 0]]),
     'Y': np.array([[0, -1j], [1j, 0]]), 'Z': np.diag([1, -1]),
     'H': np.array([[1, 1], [1, -1]]) / np.sqrt(2),
     'S': np.diag([1, 1j]), 'Sdg': np.diag([1, -1j]),
     'T': np.diag([1, np.exp(1j * np.pi / 4)]), 'Tdg': np.diag([1, np.exp(-1j * np.pi / 4)])}


def pmatrix(observable, wires):
    result = np.array([[observable.sign]], dtype=complex)
    for wire in wires:
        result = np.kron(result, M[dict(observable.factors).get(wire, 'I')])
    return result


def gmatrix(gate, wires):
    if len(gate.wires) == 1:
        result = np.array([[1]], dtype=complex)
        for wire in wires:
            result = np.kron(result, M[gate.name] if wire == gate.wires[0] else M['I'])
        return result
    n = len(wires)
    result = np.zeros((1 << n, 1 << n), dtype=complex)
    c, t = (wires.index(w) for w in gate.wires)
    for source in range(1 << n):
        bits = [(source >> (n - 1 - i)) & 1 for i in range(n)]
        phase = -1 if gate.name == 'CZ' and bits[c] and bits[t] else 1
        if gate.name == 'CX' and bits[c]:
            bits[t] ^= 1
        target = sum(b << (n - 1 - i) for i, b in enumerate(bits))
        result[target, source] = phase
    return result


def source_unitary(source):
    result = np.eye(1 << len(source.wires), dtype=complex)
    for rotation in source.rotations:
        angle = np.pi * rotation.quarter_turns / 8
        result = (np.cos(angle) * np.eye(len(result)) - 1j * np.sin(angle) * pmatrix(rotation.observable, source.wires)) @ result
    for gate in source.residual_clifford:
        result = gmatrix(gate, source.wires) @ result
    return np.exp(1j * np.pi * source.global_phase_eighth_turns / 8) * result


PAULIS = (PauliProduct((('a', 'X'),)), PauliProduct((('a', 'Y'),)),
          PauliProduct((('a', 'Y'),), -1), PauliProduct((('a', 'Z'),)),
          PauliProduct((('a', 'Y'), ('b', 'X')), -1),
          PauliProduct((('a', 'X'), ('b', 'Z'))), PauliProduct(()), PauliProduct((), -1))


@pytest.mark.parametrize('observable', PAULIS)
@pytest.mark.parametrize('sign', (1, -1))
def test_all_four_measurement_branches_signed_paulis_and_reference(observable, sign):
    wires = ('b', 'a')
    source = LogicalPauliProgram(wires, (PauliRotation(observable, sign, 5),), (), sign % 16)
    program = compile_adaptive_pbc(source, resource_quality='ideal_reference')
    assert program.global_phase_eighth_turns == 0  # T global phase is already included in source
    p = pmatrix(observable, wires)
    identity = np.eye(4)
    plus, minus = (identity + p) / 2, (identity - p) / 2
    w = np.exp(sign * 1j * np.pi / 4)
    target = plus + w * minus
    correction = plus + sign * 1j * minus
    # Dense oracle directly constructs tensor embedding and both projectors.
    resource = np.array([[1], [w]], dtype=complex) / np.sqrt(2)
    embedding = np.kron(identity, resource)
    rng = np.random.default_rng(478)
    psi = rng.normal(size=8) + 1j * rng.normal(size=8)
    psi /= np.linalg.norm(psi)
    expected = np.kron(target, M['I']) @ psi
    output_density = np.zeros((8, 8), dtype=complex)
    for m, r in product((0, 1), repeat=2):
        projector = (np.eye(8) + (-1) ** m * np.kron(p, M['Z'])) / 2
        xbra = np.array([[1, (-1) ** r]]) / np.sqrt(2)
        raw_kraus = np.kron(identity, xbra) @ projector @ embedding
        corrected_kraus = np.linalg.matrix_power(p, r) @ np.linalg.matrix_power(correction, m) @ raw_kraus
        branch_phase = 1 if m == 0 else (-1) ** r * w
        assert np.allclose(raw_kraus.conj().T @ raw_kraus, identity / 4, atol=1e-12)
        assert np.allclose(corrected_kraus, branch_phase * target / 2, atol=1e-12)
        actual = execute_reference(program, psi, reference_qubits=1, outcomes=((m, r),))
        assert np.allclose(actual.state, branch_phase * expected, atol=1e-12)
        assert np.isclose(actual.branch_probability, 1 / 4)
        assert [record['outcome'] for record in actual.measurement_records] == [m, r]
        assert all(np.isclose(record['conditional_probability'], 0.5) for record in actual.measurement_records)
        assert actual.resource_lifecycle[0]['final_status'] == 'consumed'
        output_density += actual.branch_probability * np.outer(actual.state, actual.state.conj())
    assert np.allclose(output_density, np.outer(expected, expected.conj()), atol=1e-12)


def test_noncommuting_sequence_all_branches_and_residual_global_phase():
    wires = ('a', 'b')
    rotations = (PauliRotation(PauliProduct((('a', 'X'),)), 1, 0),
                 PauliRotation(PauliProduct((('a', 'Y'), ('b', 'Z')), -1), -1, 2),
                 PauliRotation(PauliProduct((('a', 'Z'),)), 1, 7))
    residual = (LogicalGate('H', ('b',)), LogicalGate('CX', ('b', 'a')),
                LogicalGate('Sdg', ('a',)), LogicalGate('CZ', ('a', 'b')))
    source = LogicalPauliProgram(wires, rotations, residual, 7)
    program = compile_adaptive_pbc(source, resource_quality='ideal_reference')
    assert program.global_phase_eighth_turns == 6
    assert not rotations[0].observable.commutes_with(rotations[1].observable)
    rng = np.random.default_rng(714)
    psi = rng.normal(size=8) + 1j * rng.normal(size=8)
    psi /= np.linalg.norm(psi)
    expected = np.kron(source_unitary(source), M['I']) @ psi
    density = np.zeros((8, 8), dtype=complex)
    for bits in product((0, 1), repeat=6):
        branches = tuple(zip(bits[::2], bits[1::2]))
        result = execute_reference(program, psi, reference_qubits=1, outcomes=branches)
        phase = np.exp(1j * np.pi * result.branch_global_phase_eighth_turns / 8)
        assert np.allclose(result.state, phase * expected, atol=1e-12)
        assert np.isclose(result.branch_probability, 1 / 64)
        density += result.branch_probability * np.outer(result.state, result.state.conj())
    assert np.allclose(density, np.outer(expected, expected.conj()), atol=1e-12)
    reversed_source = LogicalPauliProgram(wires, tuple(reversed(rotations)), residual, 7)
    assert not np.allclose(source_unitary(reversed_source), source_unitary(source))


def test_frontend_signed_y_and_global_phase_matches_original_unitary():
    wires = ('a', 'b')
    gates = tuple(LogicalGate(name, qs) for name, qs in (
        ('S', ('a',)), ('H', ('a',)), ('T', ('a',)), ('CX', ('a', 'b')),
        ('Tdg', ('b',)), ('Sdg', ('a',)), ('T', ('a',)), ('Y', ('b',))))
    source = compile_logical_pauli(gates, wires=wires)
    assert source.rotations[0].observable == PauliProduct((('a', 'Y'),), -1)
    target = np.eye(4, dtype=complex)
    for gate in gates:
        target = gmatrix(gate, wires) @ target
    rng = np.random.default_rng(91)
    state = rng.normal(size=8) + 1j * rng.normal(size=8)
    state /= np.linalg.norm(state)
    program = compile_adaptive_pbc(source, resource_quality='ideal_reference')
    assert program.global_phase_eighth_turns == 0
    result = execute_reference(program, state, reference_qubits=1, outcomes=((1, 1), (1, 0), (0, 1)))
    phase = np.exp(1j * np.pi * result.branch_global_phase_eighth_turns / 8)
    assert np.allclose(result.state, phase * np.kron(target, M['I']) @ state, atol=1e-12)


def test_shor15_prefix_35_resource_integration_arbitrary_coherent_input():
    arithmetic = arithmetic_prefix()
    logical = compile_arithmetic(arithmetic)
    program = compile_adaptive_pbc(logical, resource_quality='ideal_reference')
    assert len(program.injections) == 35
    assert program.global_phase_eighth_turns == 0
    rng = np.random.default_rng(634)
    size = 1 << len(arithmetic.wires)
    psi = rng.normal(size=size) + 1j * rng.normal(size=size)
    psi /= np.linalg.norm(psi)
    # Independent original X/H/CX/CCX circuit, with bit order explicitly converted.
    original = tuple(ShorGate(name, tuple(len(arithmetic.wires) - 1 - q for q in qs), 'oracle') for name, qs in arithmetic.gates)
    expected = apply_gates(psi, original)
    outcomes = tuple((int(rng.integers(2)), int(rng.integers(2))) for _ in range(35))
    result = execute_reference(program, psi, outcomes=outcomes)
    phase = np.exp(1j * np.pi * result.branch_global_phase_eighth_turns / 8)
    assert np.allclose(result.state, phase * expected, atol=2e-12)
    assert len(result.measurement_records) == 70
    assert len(result.resource_lifecycle) == 35
    assert all(resource['final_status'] == 'consumed' for resource in result.resource_lifecycle)
    assert len({resource['wire'] for resource in result.resource_lifecycle}) == 35
    assert np.isclose(result.branch_probability, 0.25 ** 35, rtol=1e-12, atol=0)
    audit = audit_adaptive_pbc(logical, input_state=psi, outcomes=outcomes, expected_state=expected)
    assert audit['passed'] and audit['max_statevector_error'] < 2e-12
    assert audit['source_oracle'] == 'caller-supplied original-circuit state'
    assert audit['largest_resource_state_dimension'] == 8192
    payload = program.to_dict()
    assert payload['resource_consumptions'] == 35
    assert payload['physical_atom_peak'] is None
    assert payload['implementation_status']['physical_circuit'] is False


def test_operation_order_conditions_resources_and_colliding_data_name():
    source = compile_logical_pauli((LogicalGate('T', ('magic.r00000',)),), wires=('magic.r00000',))
    program = compile_adaptive_pbc(source, resource_quality='ideal_reference')
    injection = program.injections[0]
    assert injection.resource.wire != source.wires[0]
    operations = injection.to_dict()['operations']
    assert [op['kind'] for op in operations] == ['RESOURCE_INPUT', 'PAULI_MEASURE', 'PAULI_MEASURE',
                                               'CONDITIONAL_CLIFFORD', 'CONDITIONAL_PAULI', 'CONSUME_RESOURCE']
    assert operations[3]['condition'] == {'bit': injection.joint_measurement_id, 'equals': 1}
    assert operations[4]['condition'] == {'bit': injection.resource_measurement_id, 'equals': 1}
    assert operations[2]['depends_on'] == [injection.joint_measurement_id]


def test_stochastic_reference_is_reproducible():
    source = compile_logical_pauli((LogicalGate('T', ('a',)), LogicalGate('Tdg', ('a',))), wires=('a',))
    program = compile_adaptive_pbc(source, resource_quality='ideal_reference')
    psi = np.array([1, 1j]) / np.sqrt(2)
    first = execute_reference(program, psi, seed=83)
    second = execute_reference(program, psi, seed=83)
    assert first.to_dict() == second.to_dict()
    assert np.array_equal(first.state, second.state)
    phase = np.exp(1j * np.pi * first.branch_global_phase_eighth_turns / 8)
    assert np.allclose(first.state, phase * psi, atol=1e-12)


def test_unknown_quality_requires_explicit_ideal_assumption():
    program = compile_adaptive_pbc(compile_logical_pauli((LogicalGate('T', ('a',)),), wires=('a',)))
    psi = np.array([1, 0], dtype=complex)
    with pytest.raises(ValueError, match='explicit ideal-resource assumption'):
        execute_reference(program, psi)
    result = execute_reference(program, psi, assume_ideal_resources=True)
    assert result.assumed_ideal_resources is True
    assert program.injections[0].resource.quality == 'unknown'


def test_clifford_only_program_retains_global_phase_and_reference():
    source = LogicalPauliProgram(('a',), (), (LogicalGate('H', ('a',)), LogicalGate('X', ('a',))), 5)
    program = compile_adaptive_pbc(source)
    psi = np.array([1, 0, 0, 1j]) / np.sqrt(2)
    result = execute_reference(program, psi, reference_qubits=1, outcomes=())
    expected = np.kron(source_unitary(source), M['I']) @ psi
    assert np.allclose(result.state, expected)
    assert result.measurement_records == () and result.branch_probability == 1


@pytest.mark.parametrize('turns', (0, 2, -2, 3, 4))
def test_unsupported_turns_are_rejected(turns):
    source = LogicalPauliProgram(('a',), (PauliRotation(PauliProduct((('a', 'Z'),)), turns, 0),), (), 0)
    with pytest.raises(ValueError, match='only .*/-1 magic injections'):
        compile_adaptive_pbc(source)


@pytest.mark.parametrize('outcomes', ((), ((2, 0),), ((1, True),), ((0,),), ((0, 0), (1, 1))))
def test_bad_outcome_replay_is_rejected(outcomes):
    program = compile_adaptive_pbc(compile_logical_pauli((LogicalGate('T', ('a',)),), wires=('a',)), resource_quality='ideal_reference')
    with pytest.raises(ValueError, match='pair of integer bits'):
        execute_reference(program, np.array([1, 0], dtype=complex), outcomes=outcomes)


def test_reject_invalid_source_and_reference_state():
    with pytest.raises(TypeError):
        compile_adaptive_pbc({'wires': ['a']})
    with pytest.raises(ValueError, match='declared'):
        compile_adaptive_pbc(LogicalPauliProgram(('a',), (PauliRotation(PauliProduct((('b', 'Z'),)), 1, 0),), (), 0))
    with pytest.raises(ValueError, match='Clifford'):
        compile_adaptive_pbc(LogicalPauliProgram(('a',), (), (LogicalGate('T', ('a',)),), 0))
    program = compile_adaptive_pbc(compile_logical_pauli([], wires=('a',)))
    with pytest.raises(ValueError, match='normalized'):
        execute_reference(program, np.zeros(2))


def test_audit_rejects_wrong_original_circuit_oracle():
    source = compile_logical_pauli((LogicalGate('T', ('a',)),), wires=('a',))
    assert audit_adaptive_pbc(source, reference_qubits=1, seed=35)['passed']
    with pytest.raises(AssertionError, match='source unitary audit'):
        audit_adaptive_pbc(source, input_state=np.array([1, 0]), expected_state=np.array([0, 1]), outcomes=((0, 0),))


def test_program_refuses_resource_reuse_measurement_alias_and_double_phase():
    source = compile_logical_pauli((LogicalGate('T', ('a',)), LogicalGate('Tdg', ('a',))), wires=('a',))
    program = compile_adaptive_pbc(source, resource_quality='ideal_reference')
    first, second = program.injections
    with pytest.raises(ValueError, match='cannot be reused'):
        replace(program, injections=(first, replace(second, resource=replace(second.resource, wire=first.resource.wire))))
    with pytest.raises(ValueError, match='globally unique'):
        replace(program, injections=(first, replace(second, joint_measurement_id=first.joint_measurement_id)))
    with pytest.raises(ValueError, match='exactly once'):
        replace(program, global_phase_eighth_turns=1)


def test_compilation_snapshots_caller_sequences():
    wires = ['a']
    rotations = [PauliRotation(PauliProduct((('a', 'Z'),)), 1, 0)]
    residual = [LogicalGate('H', ('a',))]
    source = LogicalPauliProgram(wires, rotations, residual, 1)
    program = compile_adaptive_pbc(source, resource_quality='ideal_reference')
    wires.append('b')
    rotations.clear()
    residual.clear()
    assert program.wires == ('a',)
    assert len(program.injections) == 1
    assert program.residual_clifford == (LogicalGate('H', ('a',)),)
