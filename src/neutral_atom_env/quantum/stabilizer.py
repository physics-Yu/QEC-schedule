"""Immutable pure stabilizer states with exact signed Pauli arithmetic.

Generators are (x_mask, z_mask, phase), representing i**phase X**x Z**z.
No external RNG or physical backend is accessed. Measurement's supplied bit is
used only for a genuinely random outcome; deterministic outcomes ignore it.
"""
from dataclasses import dataclass
from typing import Mapping


def _multiply(a, b):
    x, z, p = a
    xx, zz, pp = b
    return x ^ xx, z ^ zz, (p + pp + 2 * ((z & xx).bit_count() % 2)) % 4


def _anti(a, b):
    return ((a[0] & b[1]).bit_count() + (a[1] & b[0]).bit_count()) % 2


def _basis(generators, n):
    result = {}
    for value in generators:
        for bit in range(2 * n):
            if (value[0] | value[1] << n) >> bit & 1:
                if bit in result:
                    value = _multiply(value, result[bit])
                else:
                    result[bit] = value
                    break
        else:
            if value != (0, 0, 0):
                raise ValueError('Inconsistent signed stabilizers')
    return result


@dataclass(frozen=True)
class StabilizerState:
    qubit_ids: tuple[str, ...]
    generators: tuple[tuple[int, int, int], ...]

    def __post_init__(self):
        object.__setattr__(self, 'qubit_ids', tuple(self.qubit_ids))
        object.__setattr__(self, 'generators', tuple(tuple(g) for g in self.generators))
        n = len(self.qubit_ids)
        if not n or len(set(self.qubit_ids)) != n or any(not isinstance(q, str) or not q for q in self.qubit_ids):
            raise ValueError('Distinct nonempty qubit IDs required')
        if len(self.generators) != n:
            raise ValueError('Pure state requires n independent stabilizers')
        for generator in self.generators:
            if len(generator) != 3 or any(type(v) is not int for v in generator):
                raise ValueError('Invalid Pauli generator')
            x, z, phase = generator
            if not (0 <= x < 1 << n and 0 <= z < 1 << n and 0 <= phase < 4):
                raise ValueError('Pauli out of range')
            if (phase - (x & z).bit_count()) % 2:
                raise ValueError('Stabilizer must be Hermitian')
        if any(_anti(a, b) for i, a in enumerate(self.generators) for b in self.generators[i+1:]):
            raise ValueError('Stabilizers must commute')
        if len(_basis(self.generators, n)) != n:
            raise ValueError('Dependent stabilizers')

    @classmethod
    def zero(cls, qubit_ids):
        ids = tuple(qubit_ids)
        return cls(ids, tuple((0, 1 << i, 0) for i in range(len(ids))))

    def apply_gate(self, gate_type, qubit_ids, parameters=()):
        if tuple(parameters):
            raise ValueError('Parameterized gates are not supported by exact Clifford tracking')
        kind = str(gate_type).upper()
        targets = tuple(qubit_ids)
        if kind not in {'H', 'X', 'Y', 'Z', 'CZ', 'CX', 'CNOT'}:
            raise ValueError(f'Non-Clifford or unsupported gate: {kind}; no approximation is made')
        if len(targets) != (2 if kind in {'CZ', 'CX', 'CNOT'} else 1) or len(set(targets)) != len(targets):
            raise ValueError('Incorrect gate arity')
        bits = tuple(1 << self.qubit_ids.index(q) for q in targets)
        result = []
        for x, z, phase in self.generators:
            a = bits[0]
            if kind == 'H':
                xa, za = bool(x & a), bool(z & a)
                phase = (phase + 2 * (xa and za)) % 4
                if xa != za:
                    x ^= a
                    z ^= a
            elif kind in {'X', 'Y', 'Z'}:
                flip = bool(z & a) if kind == 'X' else bool(x & a) if kind == 'Z' else bool(x & a) != bool(z & a)
                phase = (phase + 2 * flip) % 4
            elif kind == 'CZ':
                b = bits[1]
                xa, xb = bool(x & a), bool(x & b)
                phase = (phase + 2 * (xa and xb)) % 4
                if xa:
                    z ^= b
                if xb:
                    z ^= a
            else:
                b = bits[1]
                if x & a:
                    x ^= b
                if z & b:
                    z ^= a
            result.append((x, z, phase))
        return type(self)(self.qubit_ids, tuple(result))

    def expectation(self, pauli_mapping: Mapping[str, str]):
        x = z = phase = 0
        for q, kind in pauli_mapping.items():
            bit = 1 << self.qubit_ids.index(q)
            if kind not in {'I', 'X', 'Y', 'Z'}:
                raise ValueError('Observable must be a Pauli product')
            if kind in {'X', 'Y'}:
                x |= bit
            if kind in {'Z', 'Y'}:
                z |= bit
            if kind == 'Y':
                phase = (phase + 1) % 4
        value = (x, z, phase)
        if any(_anti(value, g) for g in self.generators):
            return 0
        basis = _basis(self.generators, len(self.qubit_ids))
        for bit in range(2 * len(self.qubit_ids)):
            if (value[0] | value[1] << len(self.qubit_ids)) >> bit & 1:
                if bit not in basis:
                    raise ValueError('Incomplete stabilizer basis')
                value = _multiply(value, basis[bit])
        return 1 if value == (0, 0, 0) else -1 if value == (0, 0, 2) else 0

    def measure_z(self, qubit_id, random_bit):
        if type(random_bit) is not int or random_bit not in (0, 1):
            raise ValueError('random_bit must be integer 0 or 1')
        bit = 1 << self.qubit_ids.index(qubit_id)
        anti = [i for i, g in enumerate(self.generators) if g[0] & bit]
        if not anti:
            return self, int(self.expectation({qubit_id: 'Z'}) == -1)
        pivot = anti[0]
        previous = self.generators[pivot]
        result = list(self.generators)
        for i in anti[1:]:
            result[i] = _multiply(result[i], previous)
        result[pivot] = (0, bit, 2 * random_bit)
        return type(self)(self.qubit_ids, tuple(result)), random_bit

    def reset_zero(self, qubit_id, random_bit):
        state, outcome = self.measure_z(qubit_id, random_bit)
        return (state.apply_gate('X', (qubit_id,)) if outcome else state), outcome

    def to_dict(self):
        return {'schema': 'pure-stabilizer/1', 'qubit_ids': list(self.qubit_ids),
                'generators': [list(g) for g in self.generators]}

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or value.get('schema') != 'pure-stabilizer/1':
            raise ValueError('Unknown stabilizer schema')
        return cls(tuple(value['qubit_ids']), tuple(tuple(g) for g in value['generators']))
