"""Actual encoded producer/consumer with qualified native boundary contractions.

One data patch, one active resource and optional reference: at most 2^19 complex
amplitudes. Cats/syndromes use independently executed small native kernels,
not a 44-qubit dense simulation. No ENV, PBC IR or physical model is changed.
"""
from collections import Counter
from dataclasses import asdict, dataclass, replace
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path

import numpy as np

from neutral_atom_env.circuit import PhysicalCircuit
from neutral_atom_env.domain.models import PhysicalGate

from .adaptive_pbc import AdaptivePBCProgram, _apply_clifford, _apply_pauli
from .canonical import canonical_memory_program
from .conditional_clifford_frame import FrameController
from .encoded_resource_reference import build_css_isometry, build_encoded_resource, execute_resource_reference, apply_native_unitaries
from .ir import BitExpr, Role
from .lowering import MeasurementBinding
from .mixed_pauli_cat import MixedPauliCat, NativeCatCompilation, NativeCatProgram, append_mixed_pauli_cat, audit_cat_factorized_kraus
from .pauli import PauliProduct
from .surface import logical_product, patch_roles, stabilizers


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _native_execute(circuit, state, qubits, rng, *, forced=None):
    """Small dense native execution with actual Born M/RESET branches."""
    state = np.array(state, dtype=complex, copy=True)
    if state.shape != (1 << len(qubits),) or not np.isclose(np.linalg.norm(state), 1, atol=1e-11, rtol=0):
        raise ValueError('Native dense input must be normalized on every declared wire')
    indices, records, reports = np.arange(len(state)), [], {}
    forced = {} if forced is None else dict(forced)
    for g in circuit.gates:
        if g.condition and not all(reports[key] == bit for key, bit in g.condition):
            continue
        if g.gate_type not in ('MEASURE', 'RESET'):
            state = apply_native_unitaries(PhysicalCircuit((replace(g, depends_on=(), condition=()),)), state, qubits)
            continue
        position = len(qubits) - 1 - qubits.index(g.qubit_ids[0])
        mask = (indices >> position) & 1
        probabilities = np.array([np.sum(abs(state[mask == b]) ** 2) for b in (0, 1)])
        probabilities /= probabilities.sum()
        report = forced.get(g.id)
        truth = ((report ^ int(g.readout_flip)) if report is not None else
                 int(rng.choice(2, p=probabilities)))
        if type(truth) is not int or truth not in (0, 1) or probabilities[truth] <= 1e-15:
            raise ValueError('Selected native measurement branch has zero probability')
        probability = float(probabilities[truth])
        state[mask != truth] = 0
        state /= math.sqrt(probability)
        if g.gate_type == 'RESET':
            if truth:
                state = state[indices ^ (1 << position)]
            bit = truth
        else:
            bit = truth ^ int(g.readout_flip)
            reports[g.id] = bit
        records.append({'native_gate_id': g.id, 'kind': g.gate_type, 'outcome': bit,
                        'conditional_probability': probability,
                        'source': 'native_dense_reference_projection'})
    return state, tuple(records), reports


def _codewords(patch, sector_flip=False):
    roles = tuple(r.id for r in patch_roles(patch) if r.kind == 'data')
    zero = np.zeros(512, complex)
    zero[0] = 1
    for word in stabilizers(patch):
        zero = (zero + _apply_pauli(zero, word, roles)) / 2
    zero /= np.linalg.norm(zero)
    one = _apply_pauli(zero, logical_product(PauliProduct(((patch, 'X'),))), roles)
    columns = np.column_stack((zero, one))
    if sector_flip:
        # X8 commutes with the fixed logical X/Z and only flips signed sectors.
        error = PauliProduct(((f'{patch}.d8', 'X'),))
        columns = np.column_stack([_apply_pauli(columns[:, i], error, roles) for i in (0, 1)])
    return roles, columns


@lru_cache(maxsize=16)
def _canonical_kernel(rounds, sector_flip):
    """Native 17+one-reference Choi certificate of the entire canonical bank.

    Agreement on the two-dimensional encoded/reference Bell state proves the
    identity boundary channel on that complete signed code sector, including
    phase. No replacement state is installed in any environment.
    """
    patch = 'kernel'
    roles, columns = _codewords(patch, sector_flip)
    all_roles = tuple(r.id for r in patch_roles(patch)) + ('kernel.ref',)
    state = np.zeros((512, 256, 2), complex)
    state[:, 0, :] = columns / math.sqrt(2)
    template = canonical_memory_program(patch=patch, rounds=rounds)
    selected = {key for phase in template.phases if phase.round_index is not None for key in phase.gate_ids}
    gates = tuple(PhysicalGate(o.id, o.gate_type, o.targets) for o in template.program.operations if o.id in selected)
    initial = state.ravel()
    actual, records, _ = _native_execute(PhysicalCircuit(gates), initial, all_roles, np.random.default_rng(0))
    error = float(np.linalg.norm(actual - initial))
    if error > 1e-11 or any(abs(r['conditional_probability'] - 1) > 1e-11 for r in records):
        raise AssertionError('Actual native canonical bank is not the identity channel on its signed code sector')
    return tuple((r['native_gate_id'].removeprefix('kernel.'), r['kind'], r['outcome'], r['conditional_probability'])
                 for r in records), error


def _frontier(gates):
    used = {key for g in gates for key in g.depends_on}
    return tuple(g.id for g in gates if g.id not in used)


def _data_prefix(input_state, reference_qubits, rounds, sector_flip):
    """Actual CSS encoder on an external unencoded logical/reference input."""
    if type(reference_qubits) is not int or reference_qubits not in (0, 1) or type(sector_flip) is not bool:
        raise ValueError('At most one external reference and explicit signed-sector choice are supported')
    state = np.array(input_state, complex, copy=True)
    if state.shape != (1 << (1 + reference_qubits),) or not np.isclose(np.linalg.norm(state), 1, atol=1e-12, rtol=0):
        raise ValueError('Normalized one-logical-qubit input with the declared reference is required')
    roles = (*patch_roles('A'), *(Role(f'ref.{i}', 'data') for i in range(reference_qubits)))
    gates, measurements = [], []
    def add(gid, kind, targets, parents=None):
        gates.append(PhysicalGate(gid, kind, tuple(targets), depends_on=_frontier(gates) if parents is None else parents))
    # The unknown logical input and external reference are preserved. Every
    # other data/syndrome role is genuinely reset in the emitted prefix.
    for r in patch_roles('A'):
        if r.id != 'A.d0':
            add('data.reset.' + r.id, 'RESET', (r.id,))
    encoder = build_css_isometry(patch='A', data_qubits=tuple(f'A.d{i}' for i in range(9)), namespace='data')
    for g in encoder.isometry_circuit.gates:
        add(g.id, g.gate_type, g.qubit_ids)
    if sector_flip:
        add('data.sector.x8', 'X', ('A.d8',))
    template, retained = canonical_memory_program(patch='A', rounds=rounds), set()
    entry = _frontier(gates)
    for phase in template.phases:
        if phase.round_index is None:
            continue
        for key in phase.gate_ids:
            op = next(o for o in template.program.operations if o.id == key)
            parents = tuple('data.check.' + p for p in op.depends_on if p in retained) or entry
            add('data.check.' + key, op.gate_type, op.targets, parents)
            if op.gate_type == 'MEASURE':
                measurements.append(MeasurementBinding(key, 'data.check.' + key, 0, 'data_input_sector'))
            retained.add(key)
    # Execute all 16 emitted RESETs on the complete 17+reference input. The
    # caller boundary explicitly supplies zero on noninput data/auxiliaries.
    complete = np.zeros((2, 1 << 16, 1 << reference_qubits), complex)
    complete[:, 0, :] = state.reshape(2, -1)
    reset_circuit = PhysicalCircuit(tuple(g for g in gates if g.id.startswith('data.reset.')))
    complete, resets, _ = _native_execute(reset_circuit, complete.ravel(), tuple(r.id for r in roles), np.random.default_rng(0))
    physical = complete.reshape(512, 256, 1 << reference_qubits)[:, 0, :].ravel()
    # Execute the actual 9-data encoder, preserving the untouched reference.
    physical = apply_native_unitaries(encoder.isometry_circuit, physical, encoder.data_qubits, reference_qubits=reference_qubits)
    if sector_flip:
        physical = apply_native_unitaries(PhysicalCircuit((PhysicalGate('data.sector.x8', 'X', ('A.d8',)),)), physical,
                                         encoder.data_qubits, reference_qubits=reference_qubits)
    _, columns = _codewords('A', sector_flip)
    decoded = columns.conj().T @ physical.reshape(512, -1)
    if np.linalg.norm(decoded.ravel() - state) > 1e-12:
        raise AssertionError('Actual native data encoder disagrees with the independent CSS projector oracle')
    kernel, error = _canonical_kernel(rounds, sector_flip)
    records = [*resets, *[{'native_gate_id': 'data.check.A.' + key, 'kind': kind, 'outcome': bit,
                'conditional_probability': probability, 'source': 'native_18q_canonical_choi_kernel'}
               for key, kind, bit, probability in kernel]]
    reports = {r['native_gate_id']: r['outcome'] for r in records if r['kind'] == 'MEASURE'}
    sectors = {(p, kind, i): BitExpr((f'{p}.r{rounds}.{kind}{i}',)) for p in ('A',) for kind in ('X', 'Z') for i in range(4)}
    native = NativeCatProgram(roles, tuple(gates), tuple(measurements), (), (), 'encoded-data-native-prefix')
    return native, physical, sectors, records, reports, error


def _append_resource(prefix, prepared, resource_patch):
    reverse = {q: role for role, q in prepared.bindings}
    roles = {r.id: r for r in prefix.roles}
    fresh = not any(r.id in roles for r in patch_roles(resource_patch))
    if not fresh:
        last, last_nonreset = {}, {}
        for g in prefix.operations:
            for role in g.qubit_ids:
                last[role] = g
                if g.gate_type != 'RESET':
                    last_nonreset[role] = g
        if (any(roles.get(r.id) != r for r in patch_roles(resource_patch)) or
                any(last.get(r.id) is None or last[r.id].gate_type != 'RESET' for r in patch_roles(resource_patch)) or
                any(last_nonreset.get(f'{resource_patch}.d{i}') is None or
                    last_nonreset[f'{resource_patch}.d{i}'].gate_type != 'MEASURE' for i in range(9))):
            raise ValueError('Physical resource reuse requires complete consumed data and released syndrome roles')
    gates = list(prefix.operations)
    for g in prepared.circuit.gates:
        gates.append(replace(g, qubit_ids=tuple(reverse[q] for q in g.qubit_ids),
                             depends_on=g.depends_on or _frontier(prefix.operations)))
    epoch = prepared.circuit.gates[0].id.rsplit('.', 1)[0]
    records = (*prefix.measurements, *(MeasurementBinding(epoch + '.sector.' + key, raw, 0, 'encoded_resource_sector')
                                      for key, raw in prepared.syndrome_measurements))
    native = NativeCatProgram((*prefix.roles, *(patch_roles(resource_patch) if fresh else ())), tuple(gates), records,
                              prefix.detectors, prefix.observables, prefix.name + '+resource')
    sectors = {(resource_patch, kind, i): BitExpr((epoch + f'.sector.{resource_patch}.r1.{kind}{i}',))
               for kind in ('X', 'Z') for i in range(4)}
    return native, sectors


def _record_kernel(item, stage, sector_flip, records, raw):
    for patch in item.data_patches:
        kernel, error = _canonical_kernel(item.rounds, sector_flip if patch == 'A' else False)
        for key, kind, bit, probability in kernel:
            gid = f'{item.namespace}.{stage}.{patch}.{key}__g000'
            records.append({'native_gate_id': gid, 'kind': kind, 'outcome': bit,
                            'conditional_probability': probability, 'source': 'native_18q_canonical_choi_kernel'})
            if kind == 'MEASURE':
                raw[gid] = bit


def _joint_reference(item, state, wires, rng, forced_m, records, raw):
    proof = audit_cat_factorized_kraus(item)
    tail = item.program.operations[item.prefix_gate_count:]
    resource = (*item.cat_roles, item.verifier_role)
    prepare = PhysicalCircuit(tuple(replace(g, depends_on=()) for g in tail
        if g.id.startswith(item.namespace + '.prepare.') or g.id.startswith(item.namespace + '.verify.')))
    initial = np.zeros(1 << len(resource), complex)
    initial[0] = 1
    cat, verification_records, verification_raw = _native_execute(prepare, initial, resource, rng)
    records.extend(verification_records)
    raw.update(verification_raw)
    semantic = {m.result_id: raw[m.raw_gate_id] ^ m.bit_flip for m in item.program.measurements if m.raw_gate_id in raw}
    if not item.verification_status(semantic)['accepted']:
        raise ValueError('Actual reference cat rejected before data coupling')
    cat = cat.reshape(1 << len(item.cat_roles), 2)[:, 0]
    ghz_bras = []
    for i, role in enumerate(item.cat_roles):
        gates = PhysicalCircuit(tuple(replace(g, depends_on=()) for g in tail
                                      if g.id == f'{item.namespace}.readout.cat{i}.h__g000'))
        ghz_bras.append(np.column_stack([apply_native_unitaries(gates, v, (role,)) for v in np.eye(2).T]))
    q = PauliProduct(item.physical_product.factors)
    acted = _apply_pauli(state, q, wires, int(math.log2(len(state))) - len(wires))
    overlap = np.vdot(state, acted)
    coefficients, probabilities, parities = [], [], []
    n = len(item.cat_roles)
    for value in range(1 << n):
        bits = tuple((value >> (n - 1 - i)) & 1 for i in range(n))
        a = cat[0] * np.prod([ghz_bras[i][b, 0] for i, b in enumerate(bits)])
        b = cat[-1] * np.prod([ghz_bras[i][bit, 1] for i, bit in enumerate(bits)])
        probability = float((abs(a) ** 2 + abs(b) ** 2 + 2 * np.real(np.conj(a) * b * overlap)))
        coefficients.append((a, b, bits))
        probabilities.append(max(0.0, probability))
        parities.append((sum(bits) % 2) ^ int(item.physical_product.sign == -1))
    probabilities = np.array(probabilities)
    probabilities /= probabilities.sum()
    allowed = np.array([True if forced_m is None else parity == forced_m for parity in parities])
    if not probabilities[allowed].sum():
        raise ValueError('Requested joint branch has zero Born probability')
    selection = probabilities * allowed
    value = int(rng.choice(len(selection), p=selection / selection.sum()))
    a, b, bits = coefficients[value]
    projected = a * state + b * acted
    projected /= np.linalg.norm(projected)
    for i, bit in enumerate(bits):
        gid = f'{item.namespace}.readout.cat{i}.measure__g000'
        prefix = bits[:i]
        numerator = sum(p for (_, _, bs), p in zip(coefficients, probabilities) if bs[:i + 1] == bits[:i + 1])
        denominator = sum(p for (_, _, bs), p in zip(coefficients, probabilities) if bs[:i] == prefix)
        records.append({'native_gate_id': gid, 'kind': 'MEASURE', 'outcome': bit,
                        'conditional_probability': float(numerator / denominator), 'source': 'qualified_native_cat_kraus_projection'})
        raw[gid] = bit
        records.append({'native_gate_id': f'{item.namespace}.readout.cat{i}.reset__g000', 'kind': 'RESET',
                        'outcome': bit, 'conditional_probability': 1.0, 'source': 'actual_measured_cat_release'})
    return projected, parities[value], float(sum(p for p, parity in zip(probabilities, parities) if parity == parities[value])), proof


def _resource_x(prefix, resource_patch, namespace):
    gates, measurements = list(prefix.operations), list(prefix.measurements)
    for kind, label in (('H', 'h'), ('MEASURE', 'measure'), ('RESET', 'reset')):
        for i in range(9):
            gid = f'{namespace}.resource_x.{label}{i}'
            gates.append(PhysicalGate(gid, kind, (f'{resource_patch}.d{i}',), depends_on=_frontier(gates)))
            if kind == 'MEASURE':
                measurements.append(MeasurementBinding(gid, gid, 0, 'destructive_resource_x'))
    return NativeCatProgram(prefix.roles, tuple(gates), tuple(measurements), prefix.detectors, prefix.observables,
                            prefix.name + '+destructive-resource-x'), PhysicalCircuit(tuple(
                                replace(g, depends_on=()) for g in gates[len(prefix.operations):]))


def _resource_readout(circuit, state, wires, resource_patch, rng, forced_r, records, raw):
    # Independent aggregate distribution BEFORE any raw bit is used by frame.
    hadamards = PhysicalCircuit(tuple(replace(g, depends_on=()) for g in circuit.gates if g.gate_type == 'H'))
    transformed = apply_native_unitaries(hadamards, state, wires,
                                        reference_qubits=int(math.log2(len(state))) - len(wires))
    reference_dim = len(state) // (512 * 512)
    probabilities = np.sum(abs(transformed.reshape(512, 512, reference_dim)) ** 2, axis=(0, 2))
    probabilities /= probabilities.sum()
    parity = np.array([((value >> 8) ^ (value >> 5) ^ (value >> 2)) & 1 for value in range(512)])
    forced = None
    if forced_r is not None:
        allowed = probabilities * (parity == forced_r)
        if allowed.sum() <= 1e-15:
            raise ValueError('Requested resource-X branch has zero Born probability')
        value = int(rng.choice(512, p=allowed / allowed.sum()))
        forced = {f'{g.id}': (value >> (8 - i)) & 1 for i, g in enumerate(g for g in circuit.gates if g.gate_type == 'MEASURE')}
    actual, executed, reports = _native_execute(circuit, state, (*wires, *(f'ref.{i}' for i in range(int(math.log2(reference_dim))))), rng, forced=forced)
    records.extend(executed)
    raw.update(reports)
    readouts = tuple(g.id for g in circuit.gates if g.gate_type == 'MEASURE')
    # Fixed logical X is X0 X3 X6, NOT the XOR of all nine readout bits.
    r = reports[readouts[0]] ^ reports[readouts[3]] ^ reports[readouts[6]]
    matrix = actual.reshape(512, 512, reference_dim)
    retained = matrix[:, 0, :].ravel()
    if np.linalg.norm(matrix[:, 1:, :]) > 1e-12 or not np.isclose(np.linalg.norm(retained), 1, atol=1e-11):
        raise AssertionError('Actual destructive readout/reset did not release the resource to zero')
    return retained, r, float(probabilities[parity == r].sum()), {
        'raw_x_distribution': probabilities.tolist(), 'logical_x_raw_gate_ids': [readouts[i] for i in (0, 3, 6)],
        'all_nine_actual_readouts': list(readouts), 'raw_probability_sum': float(probabilities.sum()),
        'logical_x_group_probabilities': [float(probabilities[parity == b].sum()) for b in (0, 1)],
        'resource_data_reset_zero': True}


@dataclass(frozen=True)
class EncodedInjectionResult:
    program: AdaptivePBCProgram
    native_program: NativeCatProgram
    encoded_data: np.ndarray
    logical_data: np.ndarray
    frame: object
    raw_reports: tuple
    native_records: tuple
    receipts: tuple
    resource_lifecycle: tuple
    branch_global_phase_eighth_turns: int
    boundary_audits: tuple
    reference_qubits: int
    qualified_joints: tuple[MixedPauliCat, ...]

    def realize(self):
        state = self.frame.realize(self.logical_data, reference_qubits=self.reference_qubits)
        for g in self.program.residual_clifford:
            state = _apply_clifford(state, g, self.program.wires, self.reference_qubits)
        return state * np.exp(1j * math.pi * self.program.global_phase_eighth_turns / 8)

    def compile(self, bindings=None):
        """Return the complete actual native PhysicalCircuit, without timing."""
        roles = tuple(r.id for r in self.native_program.roles)
        mapping = dict(bindings) if bindings is not None else {role: f'Q{i:03d}' for i, role in enumerate(roles)}
        if (set(mapping) != set(roles) or len(set(mapping.values())) != len(roles) or
                any(type(q) is not str or not q.strip() for q in mapping.values())):
            raise ValueError('Native bindings must cover every role with a distinct physical ID')
        circuit = PhysicalCircuit(tuple(replace(g, qubit_ids=tuple(mapping[q] for q in g.qubit_ids)) for g in self.native_program.operations))
        return NativeCatCompilation(self.native_program, circuit, tuple(mapping.items()), self.native_program.measurements)

    def to_dict(self):
        compiled = self.compile()
        mapping = dict(compiled.bindings)
        gates = [asdict(g) for g in compiled.circuit.gates]
        return {'schema': 'encoded-injection-native-factorized-reference/1', 'native_program': self.native_program.to_dict(),
            'input_adaptive_program': self.program.to_dict(),
            'bindings': mapping, 'native_gates': gates, 'native_gate_counts': dict(Counter(g['gate_type'] for g in gates)),
            'native_gate_count': len(gates), 'declared_role_count': len(mapping),
            'active_dense_dimension': 1 << (18 + self.reference_qubits),
            'input_boundary': 'Caller-supplied arbitrary logical state on A.d0 and declared reference; other A data/aux start zero and execute RESET, followed by actual native CSS encoder',
            'quantum_output': 'retained encoded data with exact logical Clifford frame; realize is semantic reference only',
            'logical_unrealized_state': [[v.real, v.imag] for v in self.logical_data],
            'frame': self.frame.to_dict(), 'raw_reports': dict(self.raw_reports), 'native_projection_records': list(self.native_records),
            'committed_reference_receipts': list(self.receipts), 'resource_lifecycle': list(self.resource_lifecycle),
            'branch_global_phase_eighth_turns': self.branch_global_phase_eighth_turns,
            'boundary_audits': list(self.boundary_audits), 'encoded_injection_reference_executed': True,
            'scope': 'native factorized encoded instrument with actual producer, cat and destructive resource projections',
            'environment_committed_reports': False, 'full_declared_register_dense_simulated': False,
            'physical_executed': False, 'fault_tolerant': False, 'magic_factory': False, 'complete_algorithm_encoded': False}


def execute_encoded_injections(program, input_state, *, reference_qubits=0, rounds=3, seed=0,
                               outcomes=None, sector_flip=False, physical_resource_reuse=False):
    """Consume genuinely prepared resources; never apply live eager S/P gates."""
    if not isinstance(program, AdaptivePBCProgram) or program.wires != ('A',):
        raise ValueError('This bounded reference requires exactly the declared logical wire A')
    if type(rounds) is not int or rounds < 1 or type(seed) is not int or seed < 0 or type(physical_resource_reuse) is not bool:
        raise ValueError('Positive rounds, nonnegative seed and explicit reuse flag required')
    if any(i.resource.quality != 'ideal_reference' for i in program.injections):
        raise ValueError('Producer/consumer reference requires an explicit ideal-reference resource contract')
    pairs = None if outcomes is None else tuple(tuple(p) for p in outcomes)
    if pairs is not None and (len(pairs) != len(program.injections) or any(len(p) != 2 or
            any(type(b) is not int or b not in (0, 1) for b in p) for p in pairs)):
        raise ValueError('Exactly one integer audit-only joint/resource outcome pair per injection required')
    native, data, sectors, records, raw, input_error = _data_prefix(input_state, reference_qubits, rounds, sector_flip)
    controller, rng = FrameController(program), np.random.default_rng(seed)
    receipts, lifecycle, audits, joints, branch_phase = [], [], [], [], 0
    _, columns = _codewords('A', sector_flip)
    for index, injection in enumerate(program.injections):
        pulled = controller.begin(index)
        patch = 'R' if physical_resource_reuse else f'R{index}'
        namespace = f'consume.{index:03d}'
        prepared = build_encoded_resource(sign=injection.quarter_turns, patch=patch, namespace=namespace + '.producer')
        resource = execute_resource_reference(prepared, seed=seed + index)
        resource_matrix = resource.state.reshape(512, 256)
        if np.linalg.norm(resource_matrix[:, 1:]) > 1e-12:
            raise ValueError('Resource producer did not release all eight syndrome auxiliaries')
        native, incoming_resource = _append_resource(native, prepared, patch)
        for record in (*resource.reset_records, *resource.measurement_records):
            g = record['id']
            bit = record.get('outcome', record.get('projected_bit'))
            kind = 'MEASURE' if 'outcome' in record else 'RESET'
            records.append({'native_gate_id': g, 'kind': kind, 'outcome': bit,
                            'conditional_probability': record['conditional_probability'], 'source': 'actual_native_17q_resource_producer'})
            if kind == 'MEASURE':
                raw[g] = bit
        history = dict(sectors) | incoming_resource
        product_word = PauliProduct(pulled.factors + ((patch, 'Z'),), pulled.sign)
        item = append_mixed_pauli_cat(native, history, product_word, data_patches=('A', patch), rounds=rounds, namespace=namespace + '.joint')
        data_roles = tuple(f'A.d{i}' for i in range(9))
        resource_roles = tuple(f'{patch}.d{i}' for i in range(9))
        state = np.einsum('ar,b->abr', data.reshape(512, -1), resource_matrix[:, 0]).ravel()
        wires = data_roles + resource_roles
        for p in ('A', patch):
            for check in stabilizers(p):
                expectation = np.vdot(state, _apply_pauli(state, check, wires, reference_qubits)).real
                expression = history[(p, 'X' if check.factors[0][1] == 'X' else 'Z', stabilizers(p).index(check) % 4)]
                semantic = {m.result_id: raw[m.raw_gate_id] ^ m.bit_flip for m in native.measurements if m.raw_gate_id in raw}
                if abs(expectation - (-1) ** expression.evaluate(semantic)) > 1e-11:
                    raise ValueError('Actual encoded input differs from its signed measured sector history')
        _record_kernel(item, 'before', sector_flip, records, raw)
        state, m, pm, proof = _joint_reference(item, state, wires, rng, None if pairs is None else pairs[index][0], records, raw)
        _record_kernel(item, 'after', sector_flip, records, raw)
        native, readout_circuit = _resource_x(item.program, patch, namespace)
        data, r, pr, readout = _resource_readout(readout_circuit, state, wires, patch, rng, None if pairs is None else pairs[index][1], records, raw)
        logical = (columns.conj().T @ data.reshape(512, -1)).ravel()
        if np.linalg.norm(data.reshape(512, -1) - columns @ logical.reshape(2, -1)) > 1e-11:
            raise AssertionError('Retained data has left its measured encoded sector')
        native_hash = _hash(native.to_dict())
        joint_ids = tuple(next(mb.raw_gate_id for mb in native.measurements if mb.result_id == key) for key in item.cat_measurements)
        receipt = {'index': index, 'resource_wire': injection.resource.wire, 'physical_patch': patch, 'epoch': namespace,
            'native_circuit_sha256': native_hash, 'joint_semantic_id': injection.joint_measurement_id,
            'resource_semantic_id': injection.resource_measurement_id, 'm': m, 'r': r,
            'joint_raw_gate_ids': list(joint_ids), 'joint_sign_constant': int(item.physical_product.sign == -1),
            'resource_x_raw_gate_ids': readout['logical_x_raw_gate_ids'],
            'all_resource_readout_gate_ids': readout['all_nine_actual_readouts'],
            'reference_committed': True, 'environment_committed': False, 'audit_only_forced_branch': pairs is not None,
            'decoded_joint_probability': pm, 'decoded_resource_x_probability': pr}
        commit_encoded_receipt(controller, receipt, native, raw, qualified_joint=item)
        joints.append(item)
        receipts.append(receipt)
        lifecycle.append({'resource_wire': injection.resource.wire, 'physical_patch': patch, 'epoch': namespace,
            'sign': injection.quarter_turns, 'statuses': ['prepared', 'joint_measured', 'destructively_read_out', 'consumed', 'reset_released'],
            'final_status': 'consumed', 'all_nine_data_measured': True, 'all_eight_syndrome_released': True,
            'physical_patch_reprepared_for_reuse': physical_resource_reuse and index > 0, 'magic_factory_reuse_claim': False})
        audits.append({'joint_native_kraus': proof, 'resource_readout': readout, 'input_encoder_error': input_error})
        sectors = {key: expr for key, expr in item.outgoing_sectors if key[0] == 'A'}
        branch_phase = (branch_phase + (2 * injection.quarter_turns + 8 * r if m else 0)) % 16
    controller.require_complete()
    logical = (columns.conj().T @ data.reshape(512, -1)).ravel()
    data.setflags(write=False)
    logical.setflags(write=False)
    positions = {g.id: i for i, g in enumerate(native.operations)}
    if ({r['native_gate_id'] for r in records} != {g.id for g in native.operations if g.gate_type in ('MEASURE', 'RESET')} or
            len({r['native_gate_id'] for r in records}) != len(records)):
        raise AssertionError('Every emitted native projection must have exactly one execution/kernel record')
    records.sort(key=lambda record: positions[record['native_gate_id']])
    return EncodedInjectionResult(program, native, data, logical, controller.frame, tuple(raw.items()),
        tuple(records), tuple(receipts), tuple(lifecycle), branch_phase, tuple(audits), reference_qubits, tuple(joints))


def commit_encoded_receipt(controller, receipt, native, raw_reports, *, qualified_joint):
    """Bind frame input to actual reference gate IDs/reports, never fake native bits."""
    if not isinstance(controller, FrameController) or not isinstance(native, NativeCatProgram) or not isinstance(qualified_joint, MixedPauliCat):
        raise TypeError('Frame controller and validated native experiment program are required')
    if receipt.get('native_circuit_sha256') != _hash(native.to_dict()) or receipt.get('reference_committed') is not True or receipt.get('environment_committed') is not False:
        raise ValueError('Receipt has no matching native-reference execution provenance')
    if receipt.get('index') != controller._next or controller._active is None:
        raise ValueError('Receipt resource is consumed, out of order or unavailable')
    injection = controller._active
    if (receipt.get('resource_wire') != injection.resource.wire or
            receipt.get('joint_semantic_id') != injection.joint_measurement_id or
            receipt.get('resource_semantic_id') != injection.resource_measurement_id):
        raise ValueError('Receipt aliases an unknown resource or measurement dependency')
    item, epoch, patch = qualified_joint, receipt.get('epoch'), receipt.get('physical_patch')
    pulled = controller.frame.pullback(injection.observable)
    expected_word = PauliProduct(pulled.factors + ((patch, 'Z'),), pulled.sign)
    if (type(epoch) is not str or epoch != f'consume.{injection.index:03d}' or type(patch) is not str or
            item.namespace != epoch + '.joint' or item.data_patches != ('A', patch) or item.logical_product != expected_word or
            native.operations[:len(item.program.operations)] != item.program.operations or
            native.roles != item.program.roles or native.measurements[:len(item.program.measurements)] != item.program.measurements or
            native.detectors != item.program.detectors or native.observables != item.program.observables):
        raise ValueError('Receipt qualified joint differs from its actual native prefix, labels or sidecars')
    audit_cat_factorized_kraus(item)
    expected_joint = [next(b.raw_gate_id for b in item.program.measurements if b.result_id == key) for key in item.cat_measurements]
    expected_reads = [f'{epoch}.resource_x.measure{i}' for i in range(9)]
    if (receipt.get('joint_raw_gate_ids') != expected_joint or receipt.get('all_resource_readout_gate_ids') != expected_reads or
            receipt.get('resource_x_raw_gate_ids') != [expected_reads[i] for i in (0, 3, 6)] or
            type(receipt.get('joint_sign_constant')) is not int or receipt['joint_sign_constant'] != int(item.physical_product.sign == -1)):
        raise ValueError('Receipt must use the qualified signed cat parity and the actual X0 X3 X6 resource representative')
    expected_suffix = []
    frontier = _frontier(item.program.operations)
    for kind, label in (('H', 'h'), ('MEASURE', 'measure'), ('RESET', 'reset')):
        for i in range(9):
            gid = f'{epoch}.resource_x.{label}{i}'
            expected_suffix.append(PhysicalGate(gid, kind, (f'{patch}.d{i}',), depends_on=frontier))
            frontier = (gid,)
    if (native.operations[len(item.program.operations):] != tuple(expected_suffix) or
            native.measurements[len(item.program.measurements):] != tuple(MeasurementBinding(k, k, 0, 'destructive_resource_x') for k in expected_reads)):
        raise ValueError('Resource must have the complete ordered native H/MEASURE/RESET release fragment')
    for key in ('m', 'r'):
        if type(receipt.get(key)) is not int or receipt[key] not in (0, 1):
            raise ValueError('Receipt semantic values must be integer measurement bits')
    for key in ('decoded_joint_probability', 'decoded_resource_x_probability'):
        if (type(receipt.get(key)) not in (int, float) or not math.isfinite(receipt[key]) or
                not math.isclose(receipt[key], 0.5, abs_tol=2e-11, rel_tol=0)):
            raise ValueError('This ideal encoded T/Tdg instrument requires both actual semantic branch probabilities to be 1/2')
    measured = {g.id: g for g in native.operations if g.gate_type == 'MEASURE'}
    if (set(raw_reports) != set(measured) or any(type(bit) is not int or bit not in (0, 1) for bit in raw_reports.values())):
        raise ValueError('Reference receipt requires the complete actual native measurement history without unknown reports')
    semantic = {b.result_id: raw_reports[b.raw_gate_id] ^ b.bit_flip for b in native.measurements}
    if not item.verification_status(semantic)['accepted'] or any(d.expression.evaluate(semantic) for d in item.program.detectors):
        raise ValueError('Reference receipt has rejected verification or inconsistent incoming/boundary syndrome history')
    ids = (*receipt['joint_raw_gate_ids'], *receipt['all_resource_readout_gate_ids'])
    if (len(set(ids)) != len(ids) or any(key not in measured or key not in raw_reports or
            type(raw_reports[key]) is not int or raw_reports[key] not in (0, 1) for key in ids)):
        raise ValueError('Receipt depends on missing, aliased or noninteger actual measurement reports')
    if len(receipt['all_resource_readout_gate_ids']) != 9 or not set(receipt['resource_x_raw_gate_ids']) <= set(receipt['all_resource_readout_gate_ids']):
        raise ValueError('Resource consumption requires all nine actual destructive X readouts')
    positions = {g.id: i for i, g in enumerate(native.operations)}
    if max(positions[k] for k in receipt['joint_raw_gate_ids']) >= min(positions[k] for k in receipt['all_resource_readout_gate_ids']):
        raise ValueError('Resource readout precedes its joint measurement dependency')
    m, r = receipt['joint_sign_constant'], 0
    for key in receipt['joint_raw_gate_ids']:
        m ^= raw_reports[key]
    for key in receipt['resource_x_raw_gate_ids']:
        r ^= raw_reports[key]
    if (m, r) != (receipt['m'], receipt['r']):
        raise ValueError('Receipt semantic parity disagrees with the actual raw reports')
    controller.commit_joint(injection.joint_measurement_id, m, receipt['decoded_joint_probability'])
    controller.commit_resource_x(injection.resource_measurement_id, r, receipt['decoded_resource_x_probability'])
    controller.update()


def audit_encoded_reference_result(result, input_state):
    """Independent one-qubit matrix oracle for the completed complex output.

    The oracle never prepares a resource, samples or replaces native vectors.
    Raw 512-branch contraction is separately tested using binary CSS/Fourier
    bras; this portable summary retains the actual raw distributions/proofs.
    """
    if not isinstance(result, EncodedInjectionResult):
        raise TypeError('An executed encoded native-factorized reference is required')
    initial = np.asarray(input_state, complex)
    if initial.shape != result.logical_data.shape or not np.isclose(np.linalg.norm(initial), 1, atol=1e-12, rtol=0):
        raise ValueError('Oracle input must match the declared normalized logical/reference boundary')
    identity = np.eye(2, dtype=complex)
    matrices = {'X': np.array([[0, 1], [1, 0]], complex),
                'Y': np.array([[0, -1j], [1j, 0]], complex), 'Z': np.diag([1, -1]).astype(complex),
                'H': np.array([[1, 1], [1, -1]], complex) / math.sqrt(2),
                'S': np.diag([1, 1j]), 'Sdg': np.diag([1, -1j])}
    operator = identity.copy()
    for injection in result.program.injections:
        q = injection.observable.sign * (matrices[injection.observable.factors[0][1]] if injection.observable.factors else identity)
        operator = (math.cos(math.pi / 8) * identity - 1j * injection.quarter_turns * math.sin(math.pi / 8) * q) @ operator
    for gate in result.program.residual_clifford:
        operator = matrices[gate.name] @ operator
    target = np.kron(operator, np.eye(1 << result.reference_qubits)) @ initial
    target *= np.exp(1j * math.pi * (result.program.source_global_phase_eighth_turns + result.branch_global_phase_eighth_turns) / 8)
    result.frame.validate_ledger()
    error = float(np.linalg.norm(result.realize() - target))
    probability_error = max((abs(r[key] - 0.5) for r in result.receipts for key in
                            ('decoded_joint_probability', 'decoded_resource_x_probability')), default=0)
    distributions = [a['resource_readout']['raw_x_distribution'] for a in result.boundary_audits]
    normalization_error = max((abs(sum(d) - 1) for d in distributions), default=0)
    if max(error, probability_error, normalization_error) > 2e-11:
        raise AssertionError('Encoded reference differs from the independent source matrix or raw probability normalization')
    return {'passed': True, 'source_complex_amplitude_l2_error': error,
            'max_semantic_branch_probability_error': probability_error,
            'max_raw512_normalization_error': normalization_error,
            'actual_semantic_outcomes': [[r['m'], r['r']] for r in result.receipts],
            'input_logical_reference_amplitudes': [[v.real, v.imag] for v in initial],
            'source_and_injection_branch_global_phases_preserved': True,
            'all_native_projections_recorded': True, 'all_resources_consumed': all(
                r['final_status'] == 'consumed' for r in result.resource_lifecycle),
            'oracle_scope': 'independent logical source matrix and exact deferred ledger; native factorized reference, not full-register native dense',
            'physical_executed': False, 'fault_tolerant': False, 'complete_algorithm_encoded': False}


def main():
    import argparse
    from .adaptive_pbc import compile_adaptive_pbc
    from .logical_pauli import LogicalPauliProgram, PauliRotation
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--seed', type=int, default=7)
    parser.add_argument('--rounds', type=int, default=3)
    parser.add_argument('--reuse-resource-patch', action='store_true')
    args = parser.parse_args()
    source = LogicalPauliProgram(('A',), (PauliRotation(PauliProduct((('A', 'Y'),), -1), 1, 0),
                                        PauliRotation(PauliProduct((('A', 'X'),)), -1, 1)), (), 0)
    program = compile_adaptive_pbc(source, resource_quality='ideal_reference', resource_provenance='Actual native encoded producer')
    initial = np.array([1, 2j, -0.5j, 0.3], complex)
    initial /= np.linalg.norm(initial)
    result = execute_encoded_injections(program, initial, reference_qubits=1, rounds=args.rounds,
                                       seed=args.seed, physical_resource_reuse=args.reuse_resource_patch)
    report = result.to_dict()
    report['independent_reference_audit'] = audit_encoded_reference_result(result, initial)
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2)
    print(json.dumps({'status': 'native_factorized_encoded_reference_executed', 'output': str(path),
                      'resources_consumed': len(result.resource_lifecycle), 'native_gates': len(result.native_program.operations),
                      'physical_executed': False}))


if __name__ == '__main__':
    main()
