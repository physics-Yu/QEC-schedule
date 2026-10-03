"""Independent, bounded circuit-fault audit of canonical d=3 CSS memory.

Stim is an optional audit dependency, loaded lazily and pinned independently of
the project's physical kernel. This module evaluates the *ordered native gate
circuit*, including every H in a CX-to-H/CZ/H decomposition. It does not assign
transport/idle/loss errors, fit a logical error rate, or use the legacy
perfect-final-syndrome decoder.

Each CZ Pauli product is one faulty operation, including two-qubit products.
The pair enumeration and three-report-flip witness establish circuit fault
distance for the explicitly enumerated mechanisms. The decoder accepts only
syndromes present in the zero-or-one-fault dictionary, not arbitrary noise.
"""
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from itertools import combinations, product
from random import Random
from typing import Mapping

from neutral_atom_env.quantum.stabilizer import StabilizerState


STIM_VERSION = '1.15.0'
STIM_COMMIT = '42e0b9e099180e8570407c33f87b4683cac00d81'
STIM_SOURCE_SHA256 = '3b17c5442c14045b4332b8f69701d115276a1936edd5cab39842019f55a8589e'
STIM_SOURCE_URL = (
    'https://github.com/quantumlib/Stim/blob/' + STIM_COMMIT +
    '/src/stim/gen/gen_surface_code.cc')


def _stim():
    try:
        import stim
    except ImportError as error:
        raise RuntimeError(
            'Canonical audit requires isolated stim==1.15.0; install '
            'requirements-qec-baseline.txt into the supplied audit dependency directory') from error
    if stim.__version__ != STIM_VERSION:
        raise RuntimeError(f'Canonical reference is pinned to Stim {STIM_VERSION}, '
                           f'found {stim.__version__}')
    return stim


@dataclass(frozen=True)
class NativeFault:
    id: str
    gate_id: str
    kind: str
    paulis: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class FaultSignature:
    fault: NativeFault
    detector_mask: int
    observable_mask: int

    def to_dict(self, detector_ids, observable_ids):
        return dict(asdict(self.fault), detector_mask=self.detector_mask,
                    observable_mask=self.observable_mask,
                    detectors=[key for i, key in enumerate(detector_ids)
                               if self.detector_mask >> i & 1],
                    observables=[key for i, key in enumerate(observable_ids)
                                 if self.observable_mask >> i & 1])


def enumerate_native_faults(compiled):
    """All Pauli faults after native 1Q/CZ, reset flips, and reported-bit flips.

    RESET's X flip represents erroneous |1> preparation. Y has the same effect
    on the newly reset |0>, while Z has no effect; these are not counted again.
    A report fault flips the stored bit without changing the true projection.
    Initial |0> assumptions are covered by explicit initial RESET locations.
    """
    faults = []
    for gate in compiled.circuit.gates:
        if gate.condition:
            raise ValueError('Canonical fault audit does not accept adaptive gates')
        if gate.gate_type in ('H', 'X', 'Y', 'Z'):
            for pauli in 'XYZ':
                faults.append(NativeFault(f'{gate.id}:after:{pauli}', gate.id,
                                          'after_pauli', ((gate.qubit_ids[0], pauli),)))
        elif gate.gate_type == 'CZ':
            for kinds in product('IXYZ', repeat=2):
                if kinds == ('I', 'I'):
                    continue
                factors = tuple((q, p) for q, p in zip(gate.qubit_ids, kinds) if p != 'I')
                faults.append(NativeFault(f'{gate.id}:after:{"".join(kinds)}', gate.id,
                                          'after_pauli', factors))
        elif gate.gate_type == 'RESET':
            faults.append(NativeFault(f'{gate.id}:reset_flip', gate.id, 'reset_flip',
                                      ((gate.qubit_ids[0], 'X'),)))
        elif gate.gate_type == 'MEASURE':
            faults.append(NativeFault(f'{gate.id}:report_flip', gate.id, 'measurement_report'))
        else:
            raise ValueError(f'Unsupported native audit gate {gate.gate_type}')
    return tuple(faults)


def _terms(expression):
    return frozenset(key for key, count in Counter(expression.terms).items() if count % 2)


def _validate_fault(compiled, fault):
    gate = next((gate for gate in compiled.circuit.gates if gate.id == fault.gate_id), None)
    valid = gate is not None
    if valid and fault.kind == 'measurement_report':
        valid = gate.gate_type == 'MEASURE' and not fault.paulis and fault.id == f'{gate.id}:report_flip'
    elif valid and fault.kind == 'reset_flip':
        valid = gate.gate_type == 'RESET' and fault.paulis == ((gate.qubit_ids[0], 'X'),) and (
            fault.id == f'{gate.id}:reset_flip')
    elif valid and fault.kind == 'after_pauli':
        factors = dict(fault.paulis)
        word = ''.join(factors.get(q, 'I') for q in gate.qubit_ids)
        valid = (gate.gate_type in ('H', 'X', 'Y', 'Z', 'CZ') and bool(fault.paulis)
                 and len(factors) == len(fault.paulis)
                 and all(q in gate.qubit_ids and p in ('X', 'Y', 'Z') for q, p in fault.paulis)
                 and fault.id == f'{gate.id}:after:{word}')
    else:
        valid = False
    if not valid:
        raise ValueError('Fault is not in the declared native location model')


def _native_circuit(compiled, faults, probability):
    stim = _stim()
    qindex = {q: i for i, (_, q) in enumerate(compiled.bindings)}
    native_ids = {gate.id for gate in compiled.circuit.gates}
    by_gate = defaultdict(list)
    for fault in faults:
        _validate_fault(compiled, fault)
        if fault.gate_id not in native_ids:
            raise ValueError(f'Unknown fault gate {fault.gate_id}')
        if fault.kind not in ('after_pauli', 'reset_flip', 'measurement_report'):
            raise ValueError('Unsupported audit fault kind')
        by_gate[fault.gate_id].append(fault)
    circuit, measurement_positions = stim.Circuit(), {}
    for gate in compiled.circuit.gates:
        if gate.condition:
            raise ValueError('Canonical Stim adapter rejects adaptive gates')
        kind = {'RESET': 'R', 'MEASURE': 'M'}.get(gate.gate_type, gate.gate_type)
        if kind not in ('H', 'X', 'Y', 'Z', 'CZ', 'R', 'M'):
            raise ValueError(f'Unsupported native audit gate {gate.gate_type}')
        targets = [qindex[q] for q in gate.qubit_ids]
        current_faults = by_gate[gate.id]
        reports = [fault for fault in current_faults if fault.kind == 'measurement_report']
        if reports and (kind != 'M' or len(reports) != 1):
            raise ValueError('Exactly one report-flip mechanism is valid per measurement')
        if kind == 'M':
            measurement_positions[gate.id] = circuit.num_measurements
            circuit.append(kind, targets, probability if reports else 0,
                           tag=reports[0].id if reports else gate.id)
        else:
            circuit.append(kind, targets, tag=gate.id)
        for fault in current_faults:
            if fault.kind == 'measurement_report':
                continue
            if fault.kind == 'reset_flip' and kind != 'R':
                raise ValueError('Reset fault must follow a RESET')
            if not fault.paulis or any(q not in gate.qubit_ids or p not in 'XYZ'
                                       for q, p in fault.paulis):
                raise ValueError('Pauli fault must act on the faulty native gate operands')
            circuit.append('CORRELATED_ERROR',
                [getattr(stim, f'target_{p.lower()}')(qindex[q]) for q, p in fault.paulis],
                probability, tag=fault.id)
    semantic = {m.result_id: (measurement_positions[m.raw_gate_id], m.bit_flip)
                for m in compiled.measurements}
    if len(semantic) != len(compiled.measurements):
        raise ValueError('Semantic measurement IDs must be unique')
    # MPAD is an audit-only classical constant, never a native physical task.
    expressions = [d.expression for d in compiled.program.detectors]
    expressions += [o.expression for o in compiled.program.observables]
    need_constant = any(expression.constant ^ sum(semantic[t][1] for t in expression.terms) % 2
                        for expression in expressions)
    constant_position = circuit.num_measurements
    if need_constant:
        circuit.append('MPAD', [1])
    total = circuit.num_measurements
    for kind, items in (('DETECTOR', compiled.program.detectors),
                        ('OBSERVABLE_INCLUDE', compiled.program.observables)):
        for index, item in enumerate(items):
            targets = [stim.target_rec(semantic[key][0] - total) for key in sorted(_terms(item.expression))]
            if item.expression.constant ^ sum(semantic[t][1] for t in item.expression.terms) % 2:
                targets.append(stim.target_rec(constant_position - total))
            circuit.append(kind, targets, index if kind == 'OBSERVABLE_INCLUDE' else [])
    return circuit


def native_to_stim(compiled, *, fault=None, faults=()):
    """Export the exact native circuit and semantic detector/observable sidecar.

    A selected fault is deterministic, for replay and counterexample evidence.
    The no-fault form is suitable for an independent .stim reference artifact.
    """
    faults = tuple(faults)
    if fault is not None:
        if faults:
            raise ValueError('Provide one fault or a fault tuple, not both')
        faults = (fault,)
    if len({event.gate_id for event in faults}) != len(faults):
        raise ValueError('Replay faults must occupy distinct native operations')
    return _native_circuit(compiled, faults, 1)


def official_reference_stim(canonical):
    """Fresh circuit from the pinned official generator, not project templates."""
    contract = canonical.program.memory_contract
    if contract is None or contract.decoder != 'canonical_detector_memory':
        raise ValueError('Canonical detector-memory contract is required')
    return _stim().Circuit.generated(
        f'surface_code:rotated_memory_{contract.basis.lower()}',
        distance=3, rounds=contract.closing_round)


def compare_official_reference(canonical, compiled):
    """Check independently generated layers, detector parities and native CXs.

    Stim's logical-X representative is the opposite edge after our x
    reflection. The difference is required to be a product of measured
    same-basis stabilizers; it is recorded rather than silently renamed.
    """
    stim = _stim()
    if compiled.program != canonical.program:
        raise ValueError('Compiled sidecar is not this canonical protocol')
    if canonical.source_commit != STIM_COMMIT or canonical.source_version != 'v' + STIM_VERSION:
        raise ValueError('Canonical protocol source pin differs from independent reference')
    official = official_reference_stim(canonical).flattened()
    coordinates = {int(q): tuple(int(x) for x in xy[:2])
                   for q, xy in official.get_final_qubit_coordinates().items()}
    by_coord = {coord: q for q, coord in coordinates.items()}
    role_coords = dict(canonical.role_coordinates)
    if len(set(role_coords.values())) != 17 or set(role_coords.values()) != set(by_coord):
        raise ValueError('Canonical roles do not cover the official 17-qubit geometry')
    role_for_q = {by_coord[coord]: role for role, coord in role_coords.items()}
    roles = {role.id: role for role in canonical.program.roles}
    role_to_native = dict(compiled.bindings)
    native_index = {q: i for i, (_, q) in enumerate(compiled.bindings)}
    native_by_id = {g.id: g for g in compiled.circuit.gates}
    if set(native_by_id) != {f'{op.id}__g000' for op in canonical.program.operations}:
        raise ValueError('Native circuit must contain exactly the canonical primitive gates')
    earlier = set()
    for op, gate in zip(canonical.program.operations, compiled.circuit.gates):
        if (gate.id != f'{op.id}__g000' or gate.gate_type != op.gate_type
                or gate.qubit_ids != tuple(role_to_native[r] for r in op.targets)
                or gate.condition):
            raise ValueError('Native primitive differs from the canonical protocol operation')
        required = {f'{parent}__g000' for parent in op.depends_on}
        if not required <= set(gate.depends_on) or not set(gate.depends_on) <= earlier:
            raise ValueError('Native circuit does not preserve canonical dependency barriers')
        earlier.add(gate.id)
    reference_layers = []
    records, rounds_seen, detector_terms, reference_observables = [], Counter(), [], []
    contract = canonical.program.memory_contract
    for instruction in official:
        targets = instruction.targets_copy()
        if instruction.name == 'CX':
            reference_layers.append(frozenset((role_for_q[a.value], role_for_q[b.value])
                                               for a, b in zip(targets[::2], targets[1::2])))
        elif instruction.name in ('M', 'MX', 'MR', 'MRX'):
            for target in targets:
                role = role_for_q[target.value]
                if roles[role].kind == 'data':
                    key = f'{contract.patch}.final.m{roles[role].local}'
                else:
                    rounds_seen[role] += 1
                    key = f'{contract.patch}.r{rounds_seen[role]}.{role.rsplit(".", 1)[1]}'
                records.append(key)
        elif instruction.name in ('DETECTOR', 'OBSERVABLE_INCLUDE'):
            terms = frozenset(records[len(records) + t.value] for t in targets)
            (detector_terms if instruction.name == 'DETECTOR' else reference_observables).append(terms)
    actual_layers = []
    for round_index in range(1, contract.closing_round + 1):
        for layer in range(1, 5):
            pairs = [p for p in canonical.couplings if p.round_index == round_index
                     and p.layer_index == layer]
            actual_layers.append(frozenset((p.control_role, p.target_role) for p in pairs))
            if len(pairs) != 6:
                raise ValueError('Canonical interaction layer must have six couplings')
            phases = [phase for phase in canonical.phases if phase.round_index == round_index
                      and phase.layer_index == layer]
            if [phase.kind for phase in phases] != ['cx_target_h', 'cx_cz', 'cx_target_restore']:
                raise ValueError('Native interaction phases must explicitly implement H/CZ/H')
            actual, expected = stim.Circuit(), stim.Circuit()
            for phase in phases:
                for gid in phase.native_gate_ids:
                    gate = native_by_id[gid]
                    actual.append(gate.gate_type, [native_index[q] for q in gate.qubit_ids])
            for pair in pairs:
                gate = native_by_id[pair.native_cz_id]
                if gate.gate_type != 'CZ' or gate.qubit_ids != (
                        role_to_native[pair.control_role], role_to_native[pair.target_role]):
                    raise ValueError('Native CZ operands differ from the coupling sidecar')
                expected.append('CX', [native_index[role_to_native[pair.control_role]],
                                       native_index[role_to_native[pair.target_role]]])
            actual.append('I', [16])
            expected.append('I', [16])
            if actual.to_tableau() != expected.to_tableau():
                raise ValueError('Native H/CZ/H phase does not implement the official CNOT layer')
    if actual_layers != reference_layers:
        raise ValueError('Four-layer interaction order differs from the official generator')
    if Counter(_terms(d.expression) for d in canonical.program.detectors) != Counter(detector_terms):
        raise ValueError('Detector parity equations differ from the official generator')
    if any(d.expression.constant for d in canonical.program.detectors):
        raise ValueError('Canonical detectors have no constant offsets')
    if len(reference_observables) != 1 or len(canonical.program.observables) != 1:
        raise ValueError('Exactly one canonical memory observable is required')
    project_observable = canonical.program.observables[0].expression
    if project_observable.constant:
        raise ValueError('Canonical observable has no constant offset')
    difference = _terms(project_observable) ^ reference_observables[0]
    terminal = [d for d in canonical.program.detectors if d.boundary == 'destructive_readout']
    final_ids = {f'{contract.patch}.final.m{i}' for i in range(9)}
    data_supports = [_terms(d.expression) & final_ids for d in terminal]
    equivalent_via = None
    for subset in product((0, 1), repeat=len(terminal)):
        support = frozenset()
        for flag, values in zip(subset, data_supports):
            if flag:
                support ^= values
        if support == difference:
            equivalent_via = [d.id for flag, d in zip(subset, terminal) if flag]
            break
    if equivalent_via is None:
        raise ValueError('Logical representative is not stabilizer-equivalent to the official observable')
    return {'passed': True, 'interaction_layers': len(reference_layers),
            'detector_equations': len(detector_terms),
            'logical_representative_equivalent_via_data_checks': equivalent_via,
            'official_observable_terms': sorted(reference_observables[0]),
            'project_observable_terms': sorted(_terms(project_observable))}


def _assert_equal_states(project_state, simulator, stim):
    n = len(project_state.qubit_ids)
    for x, z, phase in project_state.generators:
        symbols = ''.join('Y' if x >> i & 1 and z >> i & 1 else
                          'X' if x >> i & 1 else 'Z' if z >> i & 1 else 'I'
                          for i in range(n))
        sign = '-' if (phase - (x & z).bit_count()) % 4 == 2 else '+'
        if simulator.peek_observable_expectation(stim.PauliString(sign + symbols)) != 1:
            raise AssertionError('Native project and independent Stim quantum states differ')


def verify_native_instrument(compiled, *, seeds=(0, 1, 7, 19), fault=None):
    """Verify true projections, reset channels and full states with paired outcomes.

    Both simulators are checked to permit each chosen measurement outcome. The
    test then conditions both states on that same outcome to compare quantum
    instruments. This is test coupling of random branches, not postselection
    of execution shots. Every branch from every supplied seed is retained.
    A report fault changes classical bits only; the quantum projection agrees.
    """
    stim = _stim()
    qids = tuple(q for _, q in compiled.bindings)
    qindex = {q: i for i, q in enumerate(qids)}
    if fault is not None:
        _validate_fault(compiled, fault)
    results = []
    for seed in seeds:
        state, simulator, rng, raw = StabilizerState.zero(qids), stim.TableauSimulator(), Random(seed), {}
        simulator.set_num_qubits(len(qids))
        for gate in compiled.circuit.gates:
            if gate.condition:
                raise ValueError('Instrument audit rejects adaptive circuits')
            if gate.gate_type in ('MEASURE', 'RESET'):
                q = gate.qubit_ids[0]
                if gate.gate_type == 'MEASURE':
                    state, outcome = state.measure_z(q, rng.getrandbits(1))
                else:
                    state, outcome = state.reset_zero(q, rng.getrandbits(1))
                expected = simulator.peek_z(qindex[q])
                if expected and outcome != int(expected == -1):
                    raise AssertionError('Independent simulator forbids the chosen readout outcome')
                simulator.postselect_z(qindex[q], desired_value=bool(outcome))
                if gate.gate_type == 'RESET' and outcome:
                    simulator.x(qindex[q])
                if gate.gate_type == 'MEASURE':
                    raw[gate.id] = outcome ^ int(fault is not None and fault.gate_id == gate.id
                                                and fault.kind == 'measurement_report')
                _assert_equal_states(state, simulator, stim)
            else:
                state = state.apply_gate(gate.gate_type, gate.qubit_ids)
                primitive = stim.Circuit()
                primitive.append(gate.gate_type, [qindex[q] for q in gate.qubit_ids])
                simulator.do(primitive)
            if fault is not None and fault.gate_id == gate.id and fault.kind != 'measurement_report':
                for q, kind in fault.paulis:
                    state = state.apply_gate(kind, (q,))
                    primitive = stim.Circuit()
                    primitive.append(kind, [qindex[q]])
                    simulator.do(primitive)
        _assert_equal_states(state, simulator, stim)
        outputs = compiled.classical_outputs(raw)
        results.append({'seed': seed, 'raw_measurements': raw, **outputs})
    return results


def native_fault_signatures(compiled):
    """Exact signatures for every location, traced by independent Stim DEM.

    Tiny tagged probabilities are only symbolic markers to request error
    propagation. No noisy shots are sampled and the values are not a hardware
    error model. No-effect locations missing from a DEM are explicitly retained
    as the zero signature. Correlated CZ products remain single mechanisms.
    """
    faults = enumerate_native_faults(compiled)
    circuit = _native_circuit(compiled, faults, 0.001)
    signatures = {fault.id: (0, 0) for fault in faults}
    seen = set()
    for explanation in circuit.explain_detector_error_model_errors():
        dmask = omask = 0
        for term in explanation.dem_error_terms:
            target = term.dem_target
            if target.is_relative_detector_id():
                dmask ^= 1 << target.val
            elif target.is_logical_observable_id():
                omask ^= 1 << target.val
            elif not target.is_separator():
                raise ValueError('Unexpected detector error model term')
        for location in explanation.circuit_error_locations:
            key = location.noise_tag
            if key not in signatures:
                raise ValueError('Independent DEM contains an unrecognized fault tag')
            if key in seen and signatures[key] != (dmask, omask):
                raise ValueError('One fault mechanism has inconsistent independent signatures')
            seen.add(key)
            signatures[key] = dmask, omask
    return tuple(FaultSignature(fault, *signatures[fault.id]) for fault in faults)


def propagate_native_fault_signature(compiled, fault):
    """Independent binary Pauli-frame propagation for one declared fault.

    This uses no Stim objects and no project quantum-state simulator. It is a
    second exact propagation of the ordered native gate list. RESET discards
    the local frame, MEASURE observes its X component, and report flips affect
    only the classical delta. It returns changes relative to the no-fault
    record, including signed semantic bindings and affine classical outputs.
    """
    _validate_fault(compiled, fault)
    qindex = {q: i for i, (_, q) in enumerate(compiled.bindings)}
    x = z = 0
    raw = {}
    for gate in compiled.circuit.gates:
        if gate.condition:
            raise ValueError('Pauli-frame audit rejects adaptive circuits')
        bits = tuple(1 << qindex[q] for q in gate.qubit_ids)
        a = bits[0]
        if gate.gate_type == 'H':
            if bool(x & a) != bool(z & a):
                x ^= a
                z ^= a
        elif gate.gate_type == 'CZ':
            b = bits[1]
            if x & a:
                z ^= b
            if x & b:
                z ^= a
        elif gate.gate_type == 'RESET':
            x &= ~a
            z &= ~a
        elif gate.gate_type == 'MEASURE':
            raw[gate.id] = int(bool(x & a)) ^ int(
                fault.gate_id == gate.id and fault.kind == 'measurement_report')
        elif gate.gate_type not in ('X', 'Y', 'Z'):
            raise ValueError('Unsupported Pauli-frame audit gate')
        if fault.gate_id == gate.id and fault.kind != 'measurement_report':
            for q, p in fault.paulis:
                bit = 1 << qindex[q]
                if p in 'XY':
                    x ^= bit
                if p in 'YZ':
                    z ^= bit
    delta = compiled.classical_outputs(raw)
    baseline = compiled.classical_outputs({key: 0 for key in raw})
    masks = [sum((delta[kind][key] ^ baseline[kind][key]) << i
                 for i, key in enumerate(delta[kind])) for kind in ('detectors', 'observables')]
    return FaultSignature(fault, *masks)


@dataclass(frozen=True)
class SingleFaultDecoder:
    """Detector-only logical frame for a validated zero-or-one-fault model."""
    detector_ids: tuple[str, ...]
    observable_ids: tuple[str, ...]
    entries: tuple[tuple[int, int], ...]

    def decode(self, detectors: Mapping[str, int]):
        if set(detectors) != set(self.detector_ids):
            raise ValueError('Decoder requires exactly its full detector history')
        if any(type(bit) is not int or bit not in (0, 1) for bit in detectors.values()):
            raise ValueError('Decoder detector values must be integer bits')
        mask = sum(detectors[key] << i for i, key in enumerate(self.detector_ids))
        entries = dict(self.entries)
        if mask not in entries:
            raise ValueError('Syndrome is outside the validated zero-or-one-fault dictionary')
        logical = entries[mask]
        return {key: logical >> i & 1 for i, key in enumerate(self.observable_ids)}

    def correct_outputs(self, outputs):
        predicted = self.decode(outputs['detectors'])
        observed = outputs['observables']
        if set(observed) != set(self.observable_ids) or any(
                type(bit) is not int or bit not in (0, 1) for bit in observed.values()):
            raise ValueError('Decoder requires exactly its integer-bit observables')
        return {key: observed[key] ^ predicted[key] for key in self.observable_ids}


def build_single_fault_decoder(compiled, signatures=None):
    """Fail closed if one observed detector history has different logical frames."""
    signatures = native_fault_signatures(compiled) if signatures is None else signatures
    entries, representative = {0: 0}, {0: 'no_fault'}
    conflicts = []
    for signature in signatures:
        d, o = signature.detector_mask, signature.observable_mask
        if d in entries and entries[d] != o:
            conflicts.append({'detector_mask': d,
                              'faults': [representative[d], signature.fault.id],
                              'observable_masks': [entries[d], o]})
        else:
            entries[d], representative[d] = o, signature.fault.id
    if conflicts:
        raise ValueError(f'Conflicting zero-or-one-fault logical frames: {conflicts[:5]}')
    return SingleFaultDecoder(tuple(d.id for d in compiled.program.detectors),
                              tuple(o.id for o in compiled.program.observables),
                              tuple(sorted(entries.items())))


def _distance_report(signatures, compiled):
    single = [s.fault.id for s in signatures if s.detector_mask == 0 and s.observable_mask]
    pairs, pair_count = [], 0
    for a, b in combinations(signatures, 2):
        if a.fault.gate_id == b.fault.gate_id:
            continue  # mutually exclusive Pauli mechanisms at the same operation
        pair_count += 1
        if a.detector_mask == b.detector_mask and a.observable_mask != b.observable_mask:
            if len(pairs) < 10:
                pairs.append([a.fault.id, b.fault.id])
    contract = compiled.program.memory_contract
    final_ids = {f'{contract.patch}.final.m{i}' for i in range(9)}
    terminal_raw = {m.raw_gate_id for m in compiled.measurements if m.result_id in final_ids}
    terminal_reports = [s for s in signatures if s.fault.kind == 'measurement_report'
                        and s.fault.gate_id in terminal_raw]
    witness = None
    for triple in combinations(terminal_reports, 3):
        if (triple[0].detector_mask ^ triple[1].detector_mask ^ triple[2].detector_mask == 0
                and triple[0].observable_mask ^ triple[1].observable_mask ^ triple[2].observable_mask):
            witness = [s.fault.id for s in triple]
            break
    proved = 1 if single else 2 if pairs else 3 if witness else None
    return {'distance': proved, 'no_undetectable_single_fault': not single,
            'no_undetectable_fault_pair': not pairs, 'enumerated_distinct_operation_pairs': pair_count,
            'single_counterexamples': single[:10], 'pair_counterexamples': pairs,
            'weight_three_terminal_report_witness': witness,
            'scope': 'Enumerated native mechanisms only; each faulty operation counts once. '
                     'No transport/idle/loss/leakage or general noisy-decoder claim.'}


def audit_canonical_memory(canonical, compiled, *, seeds=(0, 1, 7, 19),
                           reference_shots=128, include_faults=True):
    """Return reproducible protocol, quantum-instrument, fault and decoder evidence.

    A failure is returned with counterexamples; installation/version failures
    raise clearly before any physical compilation should be started.
    """
    stim = _stim()
    seeds = tuple(seeds)
    if not seeds or any(type(seed) is not int or seed < 0 for seed in seeds):
        raise ValueError('Audit requires at least one nonnegative integer instrument seed')
    if type(reference_shots) is not int or reference_shots < 1:
        raise ValueError('Audit requires positive integer official-reference shots')
    report = {'schema': 'qec-canonical-fault-audit/1', 'passed': False, 'status': 'failed',
              'source': {'stim_version': stim.__version__, 'commit': STIM_COMMIT,
                         'url': STIM_SOURCE_URL, 'sha256': STIM_SOURCE_SHA256},
              'counterexamples': [],
              'fault_model': {'one_qubit': 'X/Y/Z immediately after every native H/X/Y/Z',
                              'cz': 'All 15 nonidentity Pauli products after every native CZ; one fault each',
                              'reset': 'X immediately after every RESET (wrong |1> preparation)',
                              'measurement': 'Stored-report bit flip at every ancilla and final data MEASURE; '
                                             'true quantum projection unchanged',
                              'interval': 'Discrete native gate boundaries; transport and idle intervals excluded',
                              'symbolic_probability': '0.001 tags for exact DEM propagation, not hardware rates',
                              'sampling': 'No noisy Monte Carlo or postselection'},
              'decoder_scope': 'Exact detector-history dictionary for zero or one declared fault; '
                               'unknown histories reject; arbitrary multi-fault noise is not decoded'}
    try:
        report['official_reference'] = compare_official_reference(canonical, compiled)
        instrument = verify_native_instrument(compiled, seeds=seeds)
        report['ideal_instrument'] = {'seeds': list(seeds), 'measurements_per_seed': len(compiled.measurements),
                                     'full_state_and_projection_comparisons_passed': True,
                                     'classical_outputs': [{k: v for k, v in item.items() if k != 'raw_measurements'}
                                                           for item in instrument]}
        if any(any(item['detectors'].values()) or any(item['observables'].values()) for item in instrument):
            raise AssertionError('Noiseless native memory has a nonzero detector or observable')
        reference = official_reference_stim(canonical)
        detectors, observables = reference.compile_detector_sampler(seed=0).sample(
            reference_shots, separate_observables=True)
        report['official_noiseless_samples'] = {'shots': reference_shots, 'seed': 0,
                                               'detector_events': int(detectors.sum()),
                                               'observable_flips': int(observables.sum())}
        if detectors.any() or observables.any():
            raise AssertionError('Pinned official reference has nonzero noiseless outputs')
        signatures = native_fault_signatures(compiled)
        detector_ids = tuple(d.id for d in compiled.program.detectors)
        observable_ids = tuple(o.id for o in compiled.program.observables)
        report['native_fault_count'] = len(signatures)
        report['fault_counts'] = dict(Counter(s.fault.kind for s in signatures))
        report['zero_signature_faults'] = sum(not s.detector_mask and not s.observable_mask for s in signatures)
        if include_faults:
            report['faults'] = [s.to_dict(detector_ids, observable_ids) for s in signatures]
        disagreements = []
        for signature in signatures:
            independent = propagate_native_fault_signature(compiled, signature.fault)
            if (independent.detector_mask, independent.observable_mask) != (
                    signature.detector_mask, signature.observable_mask):
                disagreements.append({'fault': signature.fault.id,
                                      'stim': [signature.detector_mask, signature.observable_mask],
                                      'binary_pauli_frame': [independent.detector_mask, independent.observable_mask]})
        report['independent_pauli_frame'] = {'mechanisms_checked': len(signatures),
                                             'passed': not disagreements,
                                             'counterexamples': disagreements[:10]}
        if disagreements:
            raise AssertionError(f'Independent native fault propagation disagrees: {disagreements[:5]}')
        report['fault_distance'] = _distance_report(signatures, compiled)
        decoder = build_single_fault_decoder(compiled, signatures)
        report['single_fault_decoder'] = {'passed': True, 'detector_ids': list(decoder.detector_ids),
                                         'observable_ids': list(decoder.observable_ids),
                                         'entries': {str(d): o for d, o in decoder.entries}}
        report['all_single_faults_corrected'] = all(dict(decoder.entries)[s.detector_mask] == s.observable_mask
                                                    for s in signatures)
        report['passed'] = report['all_single_faults_corrected'] and report['fault_distance']['distance'] == 3
        report['status'] = 'passed' if report['passed'] else 'failed'
        if not report['passed']:
            report['counterexamples'].append(report['fault_distance'])
    except (AssertionError, ValueError, KeyError) as error:
        report['counterexamples'].append({'type': type(error).__name__, 'message': str(error)})
    return report
