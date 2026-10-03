"""Actual native preparation circuits for ideal, unverified-fault encoded T.

Only the standalone dense reference accepts non-Clifford vectors. Tracked ENV
still rejects T, and no platform, quantum model, checkpoint or timing changes.
"""
from collections import Counter
from dataclasses import asdict, dataclass
from itertools import combinations, product
import math
from typing import Mapping

import numpy as np

from neutral_atom_env.circuit import PhysicalCircuit
from neutral_atom_env.domain.models import PhysicalGate

from .canonical import canonical_memory_program
from .pauli import PauliProduct
from .surface import logical_product, patch_roles, stabilizers


def gf2_rank(vectors):
    vectors = tuple(vectors)
    if any(type(value) is not int or value < 0 for value in vectors):
        raise ValueError('GF(2) vectors must be nonnegative integer masks')
    pivots = {}
    for value in vectors:
        while value:
            bit = value.bit_length() - 1
            if bit in pivots:
                value ^= pivots[bit]
            else:
                pivots[bit] = value
                break
    return len(pivots)


def _mask(observable, data, basis):
    if observable.sign != 1 or any(b != basis for _, b in observable.factors):
        raise ValueError('CSS encoder requires positive pure-X or pure-Z generators')
    return sum(1 << data.index(wire) for wire, _ in observable.factors)


@dataclass(frozen=True)
class CSSIsometry:
    patch: str
    data_roles: tuple[str, ...]
    data_qubits: tuple[str, ...]
    matrix_rows: tuple[tuple[int, ...], ...]
    column_masks: tuple[int, ...]
    completion_basis_indices: tuple[int, ...]
    cnot_network: tuple[tuple[int, int], ...]
    linear_circuit: PhysicalCircuit
    isometry_circuit: PhysicalCircuit

    def to_dict(self):
        return {'schema': 'd3-css-isometry-reference/1', 'patch': self.patch,
                'data_roles': list(self.data_roles), 'data_qubits': list(self.data_qubits),
                'matrix_rows': [list(row) for row in self.matrix_rows],
                'matrix_convention': 'physical output bit vector = matrix * virtual input vector over GF(2)',
                'virtual_input_order': ['logical input', 'X-check |+> 0', 'X-check |+> 1',
                    'X-check |+> 2', 'X-check |+> 3', '|0> completion 0', '|0> completion 1',
                    '|0> completion 2', '|0> completion 3'],
                'column_masks': list(self.column_masks), 'completion_basis_indices': list(self.completion_basis_indices),
                'cnot_network': [list(pair) for pair in self.cnot_network],
                'native_isometry_gates': [asdict(gate) for gate in self.isometry_circuit.gates],
                'scope': 'ideal isometry with arbitrary logical input; no fault-tolerant encoder claim'}


def build_css_isometry(*, patch='A', data_qubits=None, namespace='resource'):
    roles = tuple(r.id for r in patch_roles(patch) if r.kind == 'data')
    data_qubits = tuple(data_qubits) if data_qubits is not None else tuple(f'Q{i:03d}' for i in range(9))
    if len(data_qubits) != 9 or len(set(data_qubits)) != 9 or any(type(q) is not str or not q.strip() for q in data_qubits):
        raise ValueError('The encoder requires nine distinct physical data qubits')
    if type(namespace) is not str or not namespace.strip():
        raise ValueError('A nonempty resource namespace is required')
    checks = stabilizers(patch)
    x_checks, z_checks = checks[:4], checks[4:]
    columns = [_mask(logical_product(PauliProduct(((patch, 'X'),))), roles, 'X')]
    columns += [_mask(p, roles, 'X') for p in x_checks]
    if gf2_rank(columns) != 5 or any(not x.commutes_with(z) for x in x_checks for z in z_checks):
        raise ValueError('Canonical X checks and logical X must be independent and CSS-compatible')
    completion = []
    for q in range(9):
        candidate = 1 << q
        if gf2_rank((*columns, candidate)) > len(columns):
            columns.append(candidate)
            completion.append(q)
    if len(columns) != 9:
        raise AssertionError('Independent standard-basis completion failed')
    matrix = [[(column >> row) & 1 for column in columns] for row in range(9)]
    reduced = [row[:] for row in matrix]
    reductions = []
    def row_add(control, target):
        reductions.append((control, target))
        reduced[target] = [a ^ b for a, b in zip(reduced[target], reduced[control])]
    for col in range(9):
        pivot = next(row for row in range(col, 9) if reduced[row][col])
        if pivot != col:
            row_add(pivot, col)
            row_add(col, pivot)
            row_add(pivot, col)
        for row in range(9):
            if row != col and reduced[row][col]:
                row_add(col, row)
    if reduced != [[int(i == j) for j in range(9)] for i in range(9)]:
        raise AssertionError('GF(2) row reduction did not produce identity')
    network = tuple(reversed(reductions))
    def native(with_plus):
        gates, frontier = [], ()
        def emit(key, kind, qs):
            nonlocal frontier
            gid = f'{namespace}.encode.{key}'
            gates.append(PhysicalGate(gid, kind, tuple(data_qubits[q] for q in qs), depends_on=frontier))
            frontier = (gid,)
        if with_plus:
            for q in range(1, 5):
                emit(f'plus{q}', 'H', (q,))
        for i, (control, target) in enumerate(network):
            emit(f'cx{i}.h', 'H', (target,))
            emit(f'cx{i}.cz', 'CZ', (control, target))
            emit(f'cx{i}.restore', 'H', (target,))
        return PhysicalCircuit(tuple(gates))
    return CSSIsometry(patch, roles, data_qubits, tuple(tuple(row) for row in matrix), tuple(columns),
                       tuple(completion), network, native(False), native(True))


@dataclass(frozen=True)
class EncodedResourcePreparation:
    patch: str
    sign: int
    bindings: tuple[tuple[str, str], ...]
    encoder: CSSIsometry
    circuit: PhysicalCircuit
    syndrome_measurements: tuple[tuple[str, str], ...]

    @property
    def qubits(self):
        return tuple(qubit for _, qubit in self.bindings)

    def to_dict(self):
        return {'schema': 'encoded-t-native-reference/1', 'patch': self.patch,
                'resource_state': 'T' if self.sign == 1 else 'Tdg', 'sign': self.sign,
                'resource_formula': '(|0_L> + exp(i*sign*pi/4)|1_L>)/sqrt(2)',
                'bindings': dict(self.bindings), 'gates': [asdict(g) for g in self.circuit.gates],
                'gate_counts': dict(Counter(g.gate_type for g in self.circuit.gates)),
                'encoder': self.encoder.to_dict(), 'syndrome_measurements': dict(self.syndrome_measurements),
                'negative_resource_recipe': 'H then 7 native T gates: T^7=Tdg exactly',
                'resource_lifecycle': {'status': 'preparation_circuit_defined', 'consumed': False},
                'non_clifford_representation': 'standalone dense reference only; tracked ENV rejects T',
                'fault_tolerant': False, 'magic_factory': False, 'physical_execution': False,
                'complete_algorithm_encoded': False}


def build_encoded_resource(*, sign=1, patch='A', bindings: Mapping | None = None,
                           namespace='encoded_magic', syndrome_round=True):
    if type(sign) is not int or sign not in (-1, 1) or type(syndrome_round) is not bool:
        raise ValueError('Resource sign must be +1/-1 and syndrome_round an explicit boolean')
    roles = patch_roles(patch)
    mapping = dict(bindings) if bindings is not None else {r.id: f'Q{i:03d}' for i, r in enumerate(roles)}
    if set(mapping) != {r.id for r in roles} or len(set(mapping.values())) != 17 or any(type(q) is not str or not q.strip() for q in mapping.values()):
        raise ValueError('Bindings must cover all canonical nine data and eight syndrome roles without aliases')
    encoder = build_css_isometry(patch=patch, data_qubits=tuple(mapping[f'{patch}.d{i}'] for i in range(9)), namespace=namespace)
    gates, frontier = [], ()
    def emit(key, kind, qubits):
        nonlocal frontier
        gid = f'{namespace}.{key}'
        gates.append(PhysicalGate(gid, kind, tuple(qubits), depends_on=frontier))
        frontier = (gid,)
    for i, role in enumerate(roles):
        emit(f'reset{i}', 'RESET', (mapping[role.id],))
    emit('logical_input.h', 'H', (mapping[f'{patch}.d0'],))
    for i in range(1 if sign == 1 else 7):
        emit(f'logical_input.t{i}', 'T', (mapping[f'{patch}.d0'],))
    for gate in encoder.isometry_circuit.gates:
        gates.append(PhysicalGate(gate.id, gate.gate_type, gate.qubit_ids, depends_on=frontier))
        frontier = (gate.id,)
    measurements = []
    if syndrome_round:
        template = canonical_memory_program(patch=patch, rounds=1)
        kept = {key for phase in template.phases if phase.round_index == 1 for key in phase.gate_ids}
        ids, entry = {}, frontier
        for op in template.program.operations:
            if op.id not in kept:
                continue
            gid = f'{namespace}.check.{op.id}'
            dependencies = tuple(ids[p] for p in op.depends_on if p in ids) or entry
            gates.append(PhysicalGate(gid, op.gate_type, tuple(mapping[r] for r in op.targets), depends_on=dependencies))
            ids[op.id] = gid
            if op.gate_type == 'MEASURE':
                measurements.append((op.id, gid))
    return EncodedResourcePreparation(patch, sign, tuple((r.id, mapping[r.id]) for r in roles), encoder,
                                      PhysicalCircuit(tuple(gates)), tuple(measurements))


def apply_native_unitaries(circuit, state, qubits, *, reference_qubits=0):
    """Standalone big-endian vector emulator; no ENV state or opaque encoding."""
    qubits = tuple(qubits)
    if type(reference_qubits) is not int or reference_qubits < 0 or len(set(qubits)) != len(qubits):
        raise ValueError('Distinct data wires and a nonnegative reference count are required')
    state = np.array(state, dtype=complex, copy=True)
    total = len(qubits) + reference_qubits
    if state.shape != (1 << total,):
        raise ValueError('Vector shape must match data then reference wires')
    indices = np.arange(len(state))
    for gate in circuit.gates:
        if gate.condition or not set(gate.qubit_ids).issubset(qubits):
            raise ValueError('Unitary reference requires unconditional gates on declared wires')
        positions = [total - 1 - qubits.index(q) for q in gate.qubit_ids]
        q = positions[0]
        if gate.gate_type == 'H':
            low = indices[(indices & (1 << q)) == 0]
            high = low | (1 << q)
            a, b = state[low].copy(), state[high].copy()
            state[low], state[high] = (a + b) / math.sqrt(2), (a - b) / math.sqrt(2)
        elif gate.gate_type in ('X', 'Y'):
            phase = np.where((indices >> q) & 1, -1j, 1j) if gate.gate_type == 'Y' else 1
            state = (phase * state)[indices ^ (1 << q)]
        elif gate.gate_type in ('Z', 'T'):
            state[((indices >> q) & 1).astype(bool)] *= -1 if gate.gate_type == 'Z' else np.exp(1j * math.pi / 4)
        elif gate.gate_type == 'CZ':
            state[(((indices >> positions[0]) & (indices >> positions[1])) & 1).astype(bool)] *= -1
        else:
            raise ValueError('Only native H/X/Y/Z/T/CZ unitary gates are supported')
    return state


@dataclass(frozen=True)
class EncodedResourceResult:
    state: np.ndarray
    measurement_records: tuple[dict, ...]
    reset_records: tuple[dict, ...]
    prepared: EncodedResourcePreparation

    def to_dict(self):
        return {'schema': 'encoded-resource-dense-execution/1', 'scope': 'ideal native resource preparation reference',
                'state_dimension': len(self.state), 'state_norm': float(np.linalg.norm(self.state)),
                'measurement_records': list(self.measurement_records), 'reset_records': list(self.reset_records),
                'resource_lifecycle': {'status': 'prepared', 'consumed': False,
                                       'preparation_reference_executed': True, 'consumption_implemented': False},
                'encoded_reference_prepared': True, 'fault_tolerant': False, 'magic_factory': False,
                'physical_execution': False, 'complete_algorithm_encoded': False}


def execute_resource_reference(prepared, *, initial_state=None, seed=0):
    """Execute every emitted native gate, including actual RESET and readout."""
    if not isinstance(prepared, EncodedResourcePreparation):
        raise TypeError('Expected an EncodedResourcePreparation')
    qubits, state = prepared.qubits, np.zeros(1 << 17, dtype=complex)
    state[0] = 1
    if initial_state is not None:
        state = np.array(initial_state, dtype=complex, copy=True)
    if state.shape != (1 << 17,) or not np.isclose(np.linalg.norm(state), 1, atol=1e-12, rtol=0):
        raise ValueError('Initial native reference vector must be normalized on all 17 atoms')
    rng, measurements, resets = np.random.default_rng(seed), [], []
    indices = np.arange(len(state))
    for gate in prepared.circuit.gates:
        if gate.condition:
            raise ValueError('Resource preparation reference does not implement conditional native gates')
        if gate.gate_type not in ('RESET', 'MEASURE'):
            state = apply_native_unitaries(PhysicalCircuit((PhysicalGate(gate.id, gate.gate_type, gate.qubit_ids),)), state, qubits)
            continue
        position = 16 - qubits.index(gate.qubit_ids[0])
        bits = (indices >> position) & 1
        probabilities = np.array([np.sum(abs(state[bits == bit]) ** 2) for bit in (0, 1)])
        bit = int(rng.choice(2, p=probabilities / probabilities.sum()))
        probability = float(probabilities[bit])
        state[bits != bit] = 0
        state /= math.sqrt(probability)
        if gate.gate_type == 'RESET':
            if bit:
                state = state[indices ^ (1 << position)]
            resets.append({'id': gate.id, 'qubit': gate.qubit_ids[0], 'projected_bit': bit,
                           'conditional_probability': probability, 'prepared_basis_state': 0})
        else:
            measurements.append({'id': gate.id, 'qubit': gate.qubit_ids[0], 'outcome': bit,
                                 'conditional_probability': probability})
    state.setflags(write=False)
    return EncodedResourceResult(state, tuple(measurements), tuple(resets), prepared)


def audit_code_distance(*, patch='A'):
    """Independent finite Pauli centralizer search; not a circuit-noise distance."""
    data = tuple(f'{patch}.d{i}' for i in range(9))
    def xz(p):
        return (sum(1 << data.index(w) for w, b in p.factors if b in ('X', 'Y')),
                sum(1 << data.index(w) for w, b in p.factors if b in ('Z', 'Y')))
    generators = tuple(xz(p) for p in stabilizers(patch))
    group = {(0, 0)}
    for x, z in generators:
        group |= {(a ^ x, b ^ z) for a, b in tuple(group)}
    if len(group) != 256:
        raise AssertionError('The code must have eight independent stabilizer generators')
    checked = 0
    for weight in range(1, 4):
        for support in combinations(range(9), weight):
            for bases in product('XYZ', repeat=weight):
                p = PauliProduct(tuple((data[q], b) for q, b in zip(support, bases)))
                x, z = xz(p)
                checked += 1
                if any(((x & b).bit_count() + (z & a).bit_count()) % 2 for a, b in generators) or (x, z) in group:
                    continue
                return {'code_distance': weight, 'logical_witness': p.to_dict(),
                        'pauli_candidates_checked': checked, 'stabilizer_group_size': 256,
                        'scope': 'static code distance modulo Pauli phase; not preparation fault tolerance'}
    raise AssertionError('No nontrivial logical centralizer found through weight three')


def audit_encoded_resource(prepared, *, seed=7):
    """CSS projector oracle versus the actually executed native preparation."""
    from .adaptive_pbc import _apply_pauli
    data = prepared.encoder.data_roles
    zero = np.zeros(512, dtype=complex)
    zero[0] = 1
    for check in stabilizers(prepared.patch):
        zero = (zero + _apply_pauli(zero, check, data)) / 2
    zero /= np.linalg.norm(zero)
    one = _apply_pauli(zero, logical_product(PauliProduct(((prepared.patch, 'X'),))), data)
    expected = (zero + np.exp(1j * prepared.sign * math.pi / 4) * one) / math.sqrt(2)
    result = execute_resource_reference(prepared, seed=seed)
    actual = result.state.reshape(512, 256)
    error = float(np.linalg.norm(actual[:, 0] - expected))
    aux_error = float(np.linalg.norm(actual[:, 1:]))
    stabilizer_error = max(float(np.linalg.norm(_apply_pauli(actual[:, 0], p, data) - actual[:, 0]))
                           for p in stabilizers(prepared.patch))
    if max(error, aux_error, stabilizer_error) > 2e-12 or any(r['outcome'] for r in result.measurement_records):
        raise AssertionError('Actual native preparation differs from the independent encoded-resource oracle')
    return {'passed': True, 'scope': 'ideal native encoded T/Tdg preparation reference only',
            'resource_state': 'T' if prepared.sign == 1 else 'Tdg',
            'phase_sensitive_codeword_l2_error': error, 'syndrome_auxiliary_l2_error': aux_error,
            'max_stabilizer_residual': stabilizer_error, 'syndrome_measurements': list(result.measurement_records),
            'native_state_dimension': len(result.state), 'cnot_count': len(prepared.encoder.cnot_network),
            'gate_counts': dict(Counter(g.gate_type for g in prepared.circuit.gates)),
            'static_code': audit_code_distance(patch=prepared.patch),
            'resource_lifecycle': result.to_dict()['resource_lifecycle'],
            'tracked_env_t_supported': False, 'fault_tolerant': False, 'magic_factory': False,
            'physical_execution': False, 'complete_algorithm_encoded': False}


def main():
    """Export both native circuits plus actual dense preparation audit results."""
    import argparse
    import json
    from pathlib import Path
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='New JSON file; never replace an existing artifact')
    parser.add_argument('--seed', type=int, default=7)
    parser.add_argument('--without-syndrome-round', action='store_true')
    args = parser.parse_args()
    resources = [build_encoded_resource(sign=s, namespace=f'encoded_magic.{"plus" if s == 1 else "minus"}',
                         syndrome_round=not args.without_syndrome_round) for s in (1, -1)]
    result = {'schema': 'encoded-resource-native-audit-bundle/1',
              'resources': [{'preparation': p.to_dict(), 'audit': audit_encoded_resource(p, seed=args.seed)} for p in resources],
              'physical_execution': False, 'fault_tolerant': False, 'magic_factory': False,
              'complete_algorithm_encoded': False}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
        handle.write('\n')
    print(json.dumps({'passed': True, 'output': str(args.output),
                      'resource_audits': [r['audit'] for r in result['resources']]}))


if __name__ == '__main__':
    main()
