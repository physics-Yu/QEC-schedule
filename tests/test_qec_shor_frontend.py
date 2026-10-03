"""Phase-sensitive arithmetic adapter verification independent of PPR compiler."""
import cmath
import math
import numpy as np
import pytest

from neutral_atom_experiments.qec_pbc.shor_frontend import (
    ArithmeticProgram, expand_clifford_t, import_gidney_modexp, resource_report)


def apply(gates, state, wires):
    state = state.copy()
    for gate in gates:
        qs = tuple(wires.index(w) for w in gate.wires)
        if gate.name == 'CX':
            a, b = qs
            for i in range(len(state)):
                if i >> a & 1 and not i >> b & 1:
                    j = i ^ (1 << b)
                    state[i], state[j] = state[j], state[i]
        elif gate.name in ('H', 'X'):
            mask = 1 << qs[0]
            for i in range(len(state)):
                if not i & mask:
                    a, b = state[i], state[i | mask]
                    state[i], state[i | mask] = ((a+b)/math.sqrt(2), (a-b)/math.sqrt(2)) if gate.name == 'H' else (b, a)
        else:
            assert gate.name in ('T', 'Tdg')
            phase = cmath.exp((1 if gate.name == 'T' else -1)*1j*math.pi/4)
            for i in range(len(state)):
                if i >> qs[0] & 1:
                    state[i] *= phase
    return state


@pytest.mark.parametrize('qs', [(0,1,2), (2,0,1), (1,2,0)])
def test_ccx_exact_on_entangled_spectator(qs):
    wires = ('a','b','c','spectator')
    p = ArithmeticProgram(wires, (('CCX', qs),), 'unit-test')
    gates = expand_clifford_t(p)
    for basis in range(16):
        state = np.eye(16, dtype=complex)[:,basis]
        target = basis ^ (1 << qs[2]) if all(basis >> q & 1 for q in qs[:2]) else basis
        assert np.allclose(apply(gates,state,wires), np.eye(16)[:,target], atol=1e-12)
    rng = np.random.default_rng(2026)
    state = rng.normal(size=16) + 1j*rng.normal(size=16)
    expected = np.zeros(16, complex)
    for i, value in enumerate(state):
        target = i ^ (1 << qs[2]) if all(i >> q & 1 for q in qs[:2]) else i
        expected[target] = value
    assert np.allclose(apply(gates,state,wires),expected,atol=1e-12)
    assert resource_report(p)['t_resource_consumptions'] == 7
    assert resource_report(p)['magic_buffer_peak'] is None


@pytest.mark.parametrize('gates', [(('CCX',(0,0,1)),), (('T',(0,)),), (('CX',(0,4)),)])
def test_reject_bad_arithmetic(gates):
    with pytest.raises(ValueError):
        ArithmeticProgram(('a','b','c'),gates,'test')


def test_qasm_fingerprint_is_mandatory(tmp_path):
    path = tmp_path / 'unknown.qasm'
    path.write_text('OPENQASM 2.0;')
    with pytest.raises(ValueError,match='fingerprint'):
        import_gidney_modexp(path)


def test_program_snapshots_caller_sequences():
    wires = ['a', 'b', 'c']
    operands = [0, 1, 2]
    gates = [('CCX', operands)]
    program = ArithmeticProgram(wires, gates, 'explicit test fixture')
    operands[0] = 2
    wires[0] = 'changed'
    gates.clear()
    assert program.wires == ('a', 'b', 'c')
    assert program.gates == (('CCX', (0, 1, 2)),)
