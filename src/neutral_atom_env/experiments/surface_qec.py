"""Two rotated d=3 patches with measured syndrome and classical correction.

34 qubits: 18 data + 16 dedicated check ancillas. Perfect-readout recovery of
single data Pauli faults is verified; this is not a full circuit-noise decoder.
"""
from functools import lru_cache
import json
from random import Random

from neutral_atom_env.quantum.stabilizer import StabilizerState
from .surface_ghz import X_CHECKS, Z_CHECKS, LOGICAL_X, LOGICAL_Z

QUBIT_IDS = tuple(f'Q{q:03d}' for q in range(34))
DATA_IDS = QUBIT_IDS[:18]
FAULT_GATE_ID = 'QEC_FAULT'
X_ORDER = ((0, 1, 3, 4), (4, 5, 7, 8), (1, 2), (6, 7))
Z_ORDER = ((1, 4, 2, 5), (3, 6, 4, 7), (0, 3), (5, 8))


def data(block, local):
    return QUBIT_IDS[9 * block + local]


def ancilla(block, kind, check):
    return QUBIT_IDS[18 + 8 * block + (0 if kind == 'X' else 4) + check]


def atom_roles():
    roles = {data(b, q): {'role': 'data', 'patch': b, 'local': q}
             for b in range(2) for q in range(9)}
    roles.update({ancilla(b, k, i): {'role': 'ancilla', 'patch': b,
                                  'check_type': k, 'check_index': i}
                  for b in range(2) for k in ('X', 'Z') for i in range(4)})
    return roles


def correction_table(check_type):
    """Minimum-weight pure Pauli correction from four measured check bits.

    X checks detect Z components; Z checks detect X components. This lookup
    includes all 16 outcomes so random initialization syndromes are covered.
    Tie-breaking selects a fixed stabilizer-equivalent representative.
    """
    checks = X_CHECKS if check_type == 'X' else Z_CHECKS if check_type == 'Z' else None
    if checks is None:
        raise ValueError('Unknown check type')
    result = {}
    for value in sorted(range(512), key=lambda v: (v.bit_count(), v)):
        syndrome = tuple(sum(value >> q & 1 for q in check) % 2 for check in checks)
        result.setdefault(syndrome, tuple(q for q in range(9) if value >> q & 1))
    assert len(result) == 16
    return result


class _Builder:
    def __init__(self):
        self.gates = []
        self.readouts = []
        self.stages = []
        self.cursor = 0
        self.last = {}
        self.previous = ()
        self.stage_start = 0
        self.stage_name = ''

    def start(self, name):
        if self.gates:
            stage_gates = self.gates[self.stage_start:]
            if stage_gates:
                exits = {}
                for gate in stage_gates:
                    for qubit in gate['qubit_ids']:
                        exits[qubit] = gate['id']
                self.previous = tuple(dict.fromkeys(exits.values()))
            self.cursor = max(self.cursor, max(g['column'] for g in self.gates) + 1)
        self.stage_start = len(self.gates)
        self.stage_name = name

    def add(self, kind, qs, *, gate_id=None, condition=()):
        qs = tuple(qs)
        column = max((self.last.get(q, -1) + 1 for q in qs), default=self.cursor)
        column = max(column, self.cursor)
        gate = {'id': gate_id or f'QEC{len(self.gates):04d}', 'gate_type': kind,
                'qubit_ids': list(qs), 'parameters': [], 'column': column}
        if condition:
            gate['condition'] = [list(item) for item in condition]
        if self.previous:
            gate['depends_on'] = list(self.previous)
        self.gates.append(gate)
        self.stages.append({'gate_id': gate['id'], 'stage': self.stage_name})
        for q in qs:
            self.last[q] = column
        return gate['id']

    def cnot_layer(self, pairs):
        for _, target in pairs:
            self.add('H', (target,))
        for control, target in pairs:
            self.add('CZ', (control, target))
        for _, target in pairs:
            self.add('H', (target,))
        self.cursor = max(g['column'] for g in self.gates) + 1


def _syndrome(builder, round_name):
    for kind, order in (('X', X_ORDER), ('Z', Z_ORDER)):
        builder.start(f'{round_name}-{kind}-checks')
        if kind == 'X':
            for block in range(2):
                for i in range(4):
                    builder.add('H', (ancilla(block, kind, i),))
            builder.cursor += 1
        for layer in range(4):
            pairs = []
            for block in range(2):
                for i, check in enumerate(order):
                    if layer < len(check):
                        a, d = ancilla(block, kind, i), data(block, check[layer])
                        pairs.append((a, d) if kind == 'X' else (d, a))
            builder.cnot_layer(pairs)
        if kind == 'X':
            for block in range(2):
                for i in range(4):
                    builder.add('H', (ancilla(block, kind, i),))
            builder.cursor = max(g['column'] for g in builder.gates) + 1
        for block in range(2):
            for i in range(4):
                q = ancilla(block, kind, i)
                measurement = builder.add('MEASURE', (q,), gate_id=f'{round_name}_{kind}{block}_{i}')
                builder.readouts.append({'gate_id': measurement, 'qubit_id': q,
                                         'round': round_name, 'patch': block,
                                         'check_type': kind, 'check_index': i})
                builder.add('RESET', (q,))


def _corrections(builder, round_name):
    builder.start(f'{round_name}-correction')
    for block in range(2):
        for kind in ('X', 'Z'):
            for bits, locals_ in sorted(correction_table(kind).items()):
                if not any(bits):
                    continue
                condition = tuple((f'{round_name}_{kind}{block}_{i}', bit) for i, bit in enumerate(bits))
                for q in locals_:
                    builder.add('Z' if kind == 'X' else 'X', (data(block, q),), condition=condition)


def optimize_h_pairs(gates):
    """Cancel consecutive unconditional H on a wire, preserving dependencies.

    Measurement, reset, conditional gates, and every intervening operation on
    that wire stop cancellation. Gates on disjoint wires commute exactly.
    """
    by_id = {gate['id']: gate for gate in gates}
    wires = {}
    parents = {}
    removed = set()
    for gate in gates:
        previous = {wires[q][-1] for q in gate['qubit_ids'] if wires.get(q)}
        parents[gate['id']] = tuple(set(gate.get('depends_on', ())) | previous)
        qs = gate['qubit_ids']
        if gate['gate_type'] == 'H' and not gate.get('condition') and len(qs) == 1:
            wire = wires.setdefault(qs[0], [])
            if wire and by_id[wire[-1]]['gate_type'] == 'H' and not by_id[wire[-1]].get('condition'):
                removed.update((wire.pop(), gate['id']))
                continue
        for q in qs:
            wires.setdefault(q, []).append(gate['id'])

    @lru_cache(maxsize=None)
    def expand(ref):
        if ref not in removed:
            return {ref}
        result = set()
        for parent in parents[ref]:
            result.update(expand(parent))
        return result

    result = []
    for gate in gates:
        if gate['id'] in removed:
            continue
        updated = dict(gate)
        deps = set()
        for ref in gate.get('depends_on', ()):
            deps.update(expand(ref))
        if deps:
            updated['depends_on'] = sorted(deps)
        else:
            updated.pop('depends_on', None)
        result.append(updated)
    return result


def reduce_dependencies(gates):
    """Remove explicit edges already implied by wires, conditions, or ancestors.

    Gate IDs, columns, operations and conditions are unchanged. Exact ancestor
    bitsets are retained for every gate, including after previous reductions.
    """
    ordered = sorted(gates, key=lambda g: (g['column'], g['id']))
    index = {gate['id']: i for i, gate in enumerate(ordered)}
    ancestors = {}
    last = {}
    updated = {}

    def reach(parents):
        value = 0
        for parent in parents:
            value |= ancestors[parent] | (1 << index[parent])
        return value

    for gate in ordered:
        implicit = {last[q] for q in gate['qubit_ids'] if q in last}
        implicit.update(ref for ref, _ in gate.get('condition', ()))
        explicit = set(gate.get('depends_on', ()))
        original = reach(implicit | explicit)
        covered = reach(implicit)
        kept = []
        for ref in sorted(explicit, key=index.__getitem__, reverse=True):
            if not covered & (1 << index[ref]):
                kept.append(ref)
                covered |= ancestors[ref] | (1 << index[ref])
        if original != covered:
            raise ValueError('Dependency reduction changed reachability')
        ancestors[gate['id']] = covered
        value = dict(gate)
        if kept:
            value['depends_on'] = sorted(kept, key=index.__getitem__)
        else:
            value.pop('depends_on', None)
        updated[gate['id']] = value
        for q in gate['qubit_ids']:
            last[q] = gate['id']
    return [updated[gate['id']] for gate in gates]


def protocol(fault=None, *, optimize=True, reduce_edges=True):
    builder = _Builder()
    builder.start('initial-product-state')
    for q in range(9):
        builder.add('H', (data(0, q),))
    _syndrome(builder, 'prepare')
    _corrections(builder, 'prepare')
    builder.start('logical-cnot')
    builder.cnot_layer([(data(0, q), data(1, q)) for q in range(9)])
    builder.start('fault')
    fault_column = builder.cursor
    if fault is not None:
        if fault.get('pauli') not in {'X', 'Y', 'Z'} or fault.get('qubit_id') not in DATA_IDS:
            raise ValueError('Fault must be X/Y/Z on one of the 18 data atoms')
        builder.add(fault['pauli'], (fault['qubit_id'],), gate_id=FAULT_GATE_ID)
    else:
        # Reserve an editable column without inserting a hidden physical error.
        builder.cursor += 1
    _syndrome(builder, 'final')
    _corrections(builder, 'final')
    gates = optimize_h_pairs(builder.gates) if optimize else builder.gates
    original_edges = sum(len(g.get('depends_on', ())) for g in gates)
    if reduce_edges:
        gates = reduce_dependencies(gates)
    kept_ids = {gate['id'] for gate in gates}
    return {'gates': gates, 'readouts': builder.readouts,
            'stages': [stage for stage in builder.stages if stage['gate_id'] in kept_ids],
            'optimization': {'raw_gate_slots': len(builder.gates), 'optimized_gate_slots': len(gates),
                             'cancelled_H_pairs': (len(builder.gates) - len(gates)) // 2},
            'dependency_reduction': {'before': original_edges,
                                     'after': sum(len(g.get('depends_on', ())) for g in gates)},
            'atom_roles': atom_roles(), 'fault_gate_id': FAULT_GATE_ID,
            'fault_column': fault_column, 'fault_targets': list(DATA_IDS)}


def experiment_input(fault=None, compiler='qec_ghz2'):
    definition = protocol(fault)
    return {'compiler': compiler, 'atom_count': 34, 'layout': 'surface_qec_ghz2',
            'seed': 0, 'qec_enabled': True, 'ez_policy': 'adaptive',
            'aod_traps': 98, 'aod_rows': 7, 'aod_columns': 14,
            'aod_row_offsets_um': list(range(0, 31, 5)),
            'aod_column_offsets_um': list(range(0, 31, 5)) + list(range(40, 71, 5)),
            'ez_neighbor_guard_enabled': False,
            'gates': definition['gates'], 'compile_timeout_s': 3600,
            'qec_fault': fault, 'qec_protocol': {k: v for k, v in definition.items() if k != 'gates'}}


def decode(readout_bits, round_name='final'):
    """Return corrections from measured bits alone; no injected-error access."""
    corrections = []
    for block in range(2):
        for kind in ('X', 'Z'):
            bits = tuple(readout_bits[f'{round_name}_{kind}{block}_{i}'] for i in range(4))
            if any(type(bit) is not int or bit not in (0, 1) for bit in bits):
                raise ValueError('Measured syndrome bits must be 0/1')
            corrections.extend({'gate_type': 'Z' if kind == 'X' else 'X',
                                'qubit_ids': [data(block, q)]}
                               for q in correction_table(kind)[bits])
    return corrections


def quantum_summary(quantum_state, readout_bits, applied_corrections=(), *, measurement_protocol_complete=None):
    expectations = {f'{kind}{block}_{i}': quantum_state.expectation({data(block, q): kind for q in check})
                    for block in range(2) for kind, checks in (('X', X_CHECKS), ('Z', Z_CHECKS))
                    for i, check in enumerate(checks)}
    xx = quantum_state.expectation({data(b, q): 'X' for b in range(2) for q in LOGICAL_X})
    zz = quantum_state.expectation({data(b, q): 'Z' for b in range(2) for q in LOGICAL_Z})
    complete = {round_name: all(f'{round_name}_{kind}{block}_{i}' in readout_bits
                               for block in range(2) for kind in ('X', 'Z') for i in range(4))
                for round_name in ('prepare', 'final')}
    return {'code': 'two rotated [[9,1,3]] patches', 'data_qubits': 18, 'ancilla_qubits': 16,
            'syndrome_bits': dict(readout_bits), 'corrections': list(applied_corrections),
            'syndrome_rounds_complete': complete,
            'measurement_protocol_complete': measurement_protocol_complete,
            'stabilizer_expectations': expectations, 'logical_xx': xx, 'logical_zz': zz,
            'verified_logical_ghz2': all(v == 1 for v in expectations.values()) and xx == zz == 1,
            'scope': 'ideal projective measurement; perfect-readout single-data-Pauli recovery',
            'fault_tolerant_circuit_noise_claim': False}


def simulate_ideal(gates=None, *, seed=0, fault=None):
    """Execute the actual static gate list and its measured-bit conditions."""
    gates = protocol(fault)['gates'] if gates is None else gates
    quantum = StabilizerState.zero(QUBIT_IDS)
    rng = Random(seed)
    bits = {}
    applied = []
    executed = []
    for gate in sorted(gates, key=lambda g: (g['column'], g['id'])):
        condition = gate.get('condition', ())
        if condition and not all(bits[ref] == bit for ref, bit in condition):
            continue
        executed.append(gate['id'])
        kind, qs = gate['gate_type'], gate['qubit_ids']
        if kind == 'MEASURE':
            quantum, result = quantum.measure_z(qs[0], rng.randrange(2))
            bits[gate['id']] = result
        elif kind == 'RESET':
            quantum, _ = quantum.reset_zero(qs[0], rng.randrange(2))
        else:
            quantum = quantum.apply_gate(kind, qs, gate.get('parameters', ()))
            if condition:
                applied.append({'gate_id': gate['id'], 'gate_type': kind, 'qubit_ids': list(qs)})
    complete = _measurement_protocol_complete({g['id']: g for g in gates}, executed)
    return quantum, quantum_summary(quantum, bits, applied, measurement_protocol_complete=complete)


def _measurement_protocol_complete(gates, executed):
    index = {gid: i for i, gid in enumerate(executed)}
    for round_name in ('prepare', 'final'):
        for block in range(2):
            for kind in ('X', 'Z'):
                for i in range(4):
                    gid = f'{round_name}_{kind}{block}_{i}'
                    q = ancilla(block, kind, i)
                    if gid not in index or gid not in gates:
                        return False
                    gate = gates[gid]
                    if gate['gate_type'] != 'MEASURE' or list(gate['qubit_ids']) != [q]:
                        return False
                    preceding = [gates[key] for key in executed[:index[gid]]
                                 if q in gates[key]['qubit_ids']]
                    reset_index = max((j for j, item in enumerate(preceding)
                                       if item['gate_type'] == 'RESET'), default=-1)
                    preparation = preceding[reset_index+1:]
                    reduced = []
                    for item in preparation:
                        if item['gate_type'] == 'H' and reduced and reduced[-1]['gate_type'] == 'H':
                            reduced.pop()
                        else:
                            reduced.append(item)
                    preparation = reduced
                    check = (X_CHECKS if kind == 'X' else Z_CHECKS)[i]
                    if [item['gate_type'] for item in preparation] != ['H'] + ['CZ']*len(check) + ['H']:
                        return False
                    partners = [other for item in preparation if item['gate_type'] == 'CZ'
                                for other in item['qubit_ids'] if other != q]
                    if sorted(partners) != sorted(data(block, local) for local in check):
                        return False
                    following = (gates[key] for key in executed[index[gid]+1:]
                                 if q in gates[key]['qubit_ids'])
                    next_gate = next(following, None)
                    if next_gate is None or next_gate['gate_type'] != 'RESET':
                        return False
    return True


def summarize(state):
    """Adapter for core state; caller may use quantum_summary for explicit data."""
    quantum = getattr(state, 'quantum_state', None)
    if quantum is None:
        raise ValueError('Quantum tracking is not enabled')
    outcomes = getattr(state, 'measurement_results', None)
    if outcomes is None:
        outcomes = getattr(state, 'classical_bits', {})
    applied = []
    executed = []
    gates = {gid: {'id': gid, 'gate_type': node.gate.gate_type,
                   'qubit_ids': list(node.gate.qubit_ids), 'condition': node.gate.condition}
             for gid, node in state.dag.nodes.items()}
    for line in state.trace.records:
        record = json.loads(line)
        if not record.get('effect_completed'):
            continue
        for gid in record.get('applied_gate_ids', ()):
            if gid not in gates:
                continue
            executed.append(gid)
            gate = gates[gid]
            if gate['condition']:
                applied.append({'gate_id': gid, 'gate_type': gate['gate_type'],
                                'qubit_ids': gate['qubit_ids']})
    return quantum_summary(quantum, outcomes, applied,
                           measurement_protocol_complete=_measurement_protocol_complete(gates, executed))
