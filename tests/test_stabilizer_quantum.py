import json
import random

import pytest

from neutral_atom_env.quantum.stabilizer import StabilizerState


def test_bell_measurement_collapse_and_reset_are_actual_quantum_operations():
    initial = StabilizerState.zero(('a', 'b'))
    bell = initial.apply_gate('H', ('a',)).apply_gate('H', ('b',)).apply_gate('CZ', ('a', 'b'))
    bell = bell.apply_gate('H', ('b',))
    assert bell.expectation({'a': 'X', 'b': 'X'}) == 1
    assert bell.expectation({'a': 'Z', 'b': 'Z'}) == 1
    assert bell.expectation({'a': 'Y', 'b': 'Y'}) == -1
    assert bell.expectation({'a': 'Z'}) == 0
    for bit in (0, 1):
        measured, outcome = bell.measure_z('a', bit)
        assert outcome == bit
        assert measured.measure_z('b', 1-bit)[1] == bit
        reset, prior = measured.reset_zero('a', 1-bit)
        assert prior == bit and reset.expectation({'a': 'Z'}) == 1
        assert reset.expectation({'b': 'Z'}) == (-1 if bit else 1)
    assert initial.expectation({'a': 'Z'}) == 1
    assert bell.expectation({'a': 'Z'}) == 0  # no mutation through branches


def test_signed_paulis_and_serialization_are_exact_and_reject_t():
    zero = StabilizerState.zero(('q',))
    for kind in ('X', 'Y'):
        one = zero.apply_gate(kind, ('q',))
        assert one.measure_z('q', 0)[1] == 1
        assert StabilizerState.from_dict(json.loads(json.dumps(one.to_dict()))) == one
    assert zero.apply_gate('Z', ('q',)).measure_z('q', 1)[1] == 0
    with pytest.raises(ValueError, match='approximation'):
        zero.apply_gate('T', ('q',))
    with pytest.raises(ValueError):
        StabilizerState(('q',), ((1, 0, 1),))  # anti-Hermitian generator
    with pytest.raises(ValueError):
        StabilizerState(('a', 'b'), ((1, 0, 0), (0, 1, 0)))


def test_random_clifford_against_independent_dense_amplitudes():
    rng = random.Random(329)
    ids = ('a', 'b', 'c')
    quantum = StabilizerState.zero(ids)
    state = [1+0j] + [0j]*7
    for _ in range(80):
        kind = rng.choice(('H', 'X', 'Y', 'Z', 'CZ', 'CX'))
        indices = rng.sample(range(3), 2 if kind in {'CZ', 'CX'} else 1)
        quantum = quantum.apply_gate(kind, tuple(ids[i] for i in indices))
        updated = [0j]*8
        a = 1 << indices[0]
        for value, amplitude in enumerate(state):
            if kind == 'H':
                updated[value & ~a] += amplitude / 2**0.5
                updated[value | a] += amplitude * (-1 if value & a else 1) / 2**0.5
            elif kind in {'X', 'Y'}:
                phase = (1j if not value & a else -1j) if kind == 'Y' else 1
                updated[value ^ a] += phase * amplitude
            elif kind == 'Z':
                updated[value] += (-1 if value & a else 1)*amplitude
            elif kind == 'CZ':
                b = 1 << indices[1]
                updated[value] += (-1 if value & a and value & b else 1)*amplitude
            else:
                updated[value ^ (1 << indices[1]) if value & a else value] += amplitude
        state = updated
        # All Z-products plus mixed Pauli products exercise signs and support.
        for labels in (('X', 'Y', 'Z'), ('Y', 'Y', 'I'), ('Z', 'Z', 'Z'), ('X', 'X', 'X')):
            expectation = 0j
            for value, amplitude in enumerate(state):
                target, phase = value, 1
                for i, label in enumerate(labels):
                    if label in ('X', 'Y'):
                        target ^= 1 << i
                    if label == 'Y':
                        phase *= -1j if value >> i & 1 else 1j
                    elif label == 'Z' and value >> i & 1:
                        phase *= -1
                expectation += state[target].conjugate()*phase*amplitude
            assert abs(expectation - quantum.expectation(dict(zip(ids, labels)))) < 1e-10
