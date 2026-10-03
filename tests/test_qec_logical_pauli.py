"""Dense matrix oracle independent of signed symbolic conjugation."""
from itertools import product
import numpy as np
import pytest

from neutral_atom_experiments.qec_pbc.logical_pauli import LogicalGate, compile_logical_pauli, conjugate_pauli
from neutral_atom_experiments.qec_pbc.pauli import PauliProduct

M = {'I': np.eye(2), 'X': np.array([[0, 1], [1, 0]]),
     'Y': np.array([[0, -1j], [1j, 0]]), 'Z': np.diag([1, -1]),
     'H': np.array([[1, 1], [1, -1]]) / np.sqrt(2),
     'S': np.diag([1, 1j]), 'Sdg': np.diag([1, -1j]),
     'T': np.diag([1, np.exp(1j*np.pi/4)]), 'Tdg': np.diag([1, np.exp(-1j*np.pi/4)])}


def pauli_matrix(p, wires):
    result = np.array([[p.sign]], dtype=complex)
    for w in wires:
        result = np.kron(result, M[dict(p.factors).get(w, 'I')])
    return result


def gate_matrix(g, wires):
    n = len(wires)
    if len(g.wires) == 1:
        result = np.array([[1]], dtype=complex)
        for w in wires:
            result = np.kron(result, M[g.name] if w == g.wires[0] else M['I'])
        return result
    result = np.zeros((2**n, 2**n), dtype=complex)
    c, t = [wires.index(w) for w in g.wires]
    for col in range(2**n):
        bits = [(col >> (n-1-i)) & 1 for i in range(n)]
        phase = -1 if g.name == 'CZ' and bits[c] and bits[t] else 1
        if g.name == 'CX' and bits[c]:
            bits[t] ^= 1
        row = sum(b << (n-1-i) for i, b in enumerate(bits))
        result[row, col] = phase
    return result


def unitary(gates, wires):
    result = np.eye(2**len(wires), dtype=complex)
    for g in gates:
        result = gate_matrix(g, wires) @ result
    return result


def compiled_unitary(p):
    result = np.eye(2**len(p.wires), dtype=complex)
    for r in p.rotations:
        angle = np.pi*r.quarter_turns/8
        result = (np.cos(angle)*np.eye(len(result)) - 1j*np.sin(angle)*pauli_matrix(r.observable, p.wires)) @ result
    return np.exp(1j*np.pi*p.global_phase_eighth_turns/8)*unitary(p.residual_clifford, p.wires) @ result


@pytest.mark.parametrize('name', ['H', 'S', 'Sdg', 'X', 'Y', 'Z', 'CX', 'CZ'])
def test_all_signed_paulis_against_dense_conjugation(name):
    wires = ('a', 'b')
    g = LogicalGate(name, ('a', 'b') if name in ('CX', 'CZ') else ('a',))
    u = gate_matrix(g, wires)
    for bases in product('IXYZ', repeat=2):
        for sign in (-1, 1):
            p = PauliProduct(tuple((w,b) for w,b in zip(wires,bases) if b != 'I'), sign)
            pm = pauli_matrix(p, wires)
            assert np.allclose(pauli_matrix(conjugate_pauli(p,g),wires), u@pm@u.conj().T)
            assert np.allclose(pauli_matrix(conjugate_pauli(p,g,inverse=True),wires), u.conj().T@pm@u)


def test_sign_order_phase_and_entangled_reference():
    gates = [LogicalGate(n,w) for n,w in [('H',('a',)), ('CX',('a','b')), ('S',('a',)),
             ('T',('a',)), ('X',('b',)), ('Tdg',('b',)), ('CZ',('a','b')), ('T',('b',)), ('Sdg',('a',))]]
    p = compile_logical_pauli(gates, wires=('b','a','idle'))
    assert [r.source_index for r in p.rotations] == [3,5,7]
    assert p.rotations[0].observable == PauliProduct((('a','X'),))
    actual, expected = compiled_unitary(p), unitary(gates,p.wires)
    assert np.allclose(actual,expected)
    psi = np.zeros(8,complex); psi[0]=1/np.sqrt(2); psi[6]=1j/np.sqrt(2)
    assert np.allclose(actual@psi,expected@psi)
    assert p.to_dict()['schema'] == 'logical-pauli-unitary-v1'


def test_random_three_wire_unitaries_arbitrary_input():
    rng = np.random.default_rng(734)
    wires = ('q2','q0','q1')
    names = tuple(M.keys())[1:] + ('CX','CZ')
    for _ in range(60):
        gates = []
        for _ in range(35):
            name = str(rng.choice(names))
            ws = tuple(str(w) for w in rng.choice(wires,2 if name in ('CX','CZ') else 1,replace=False))
            gates.append(LogicalGate(name,ws))
        assert np.allclose(compiled_unitary(compile_logical_pauli(gates,wires=wires)),unitary(gates,wires),atol=1e-12)


def test_empty_clifford_only_and_nonunitary_rejection():
    assert compile_logical_pauli([],wires=('idle',)).rotations == ()
    for name in ('MEASURE','RESET','CCX','RZ'):
        with pytest.raises(ValueError): LogicalGate(name,('a',))
    with pytest.raises(TypeError): compile_logical_pauli([{'name':'H'}])
    with pytest.raises(ValueError): compile_logical_pauli([LogicalGate('T',('a',))],wires=('b',))
    with pytest.raises(ValueError): LogicalGate('CX',('a','a'))
    with pytest.raises(ValueError): compile_logical_pauli([],wires=('a','a'))
    with pytest.raises(ValueError): conjugate_pauli(PauliProduct(()),LogicalGate('T',('a',)))


def test_long_frame_against_history_and_dense_matrix():
    rng = np.random.default_rng(61002)
    wires = ('a','b','c')
    names = ('H','S','Sdg','X','Y','Z','CX','CZ','T','Tdg')
    gates = []
    for _ in range(400):
        name = str(rng.choice(names))
        ws = tuple(str(w) for w in rng.choice(wires,2 if name in ('CX','CZ') else 1,replace=False))
        gates.append(LogicalGate(name,ws))
    program = compile_logical_pauli(gates,wires=wires)
    history = []
    expected = []
    for gate in gates:
        if gate.name in ('T','Tdg'):
            p = PauliProduct(((gate.wires[0],'Z'),))
            for previous in reversed(history):
                p = conjugate_pauli(p,previous,inverse=True)
            expected.append(p)
        else:
            history.append(gate)
    assert [r.observable for r in program.rotations] == expected
    assert np.allclose(compiled_unitary(program),unitary(gates,wires),atol=1e-12)
