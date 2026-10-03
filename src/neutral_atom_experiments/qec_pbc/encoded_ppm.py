"""Three-patch encoded X/Z parity instruments, with explicit QEC history.

The ancilla is a complete [[9,1,3]] patch, never a bare parity bus. The two
same-orientation transversal CNOTs are expanded into native H/CZ/H primitives.
Syndrome sectors are allowed to be signed and are propagated through CNOT;
their random preparation bits are not mistaken for detector events.

This frontend makes no motion or general fault-tolerance claim. Its bounded
native-location audit is separate from physical Executor acceptance.
"""
from collections import Counter
from dataclasses import asdict, dataclass
from itertools import combinations

from neutral_atom_experiments.surface_ghz import (
    LOGICAL_X, LOGICAL_Z, X_CHECKS, Z_CHECKS)

from .canonical import CanonicalCoupling, CanonicalPhase, canonical_memory_program
from .ir import BitExpr, Detector, GateTask, Observable, PBCProgram
from .lowering import lower_to_physical


@dataclass(frozen=True)
class EncodedParity:
    program: PBCProgram
    phases: tuple[CanonicalPhase, ...]
    couplings: tuple[CanonicalCoupling, ...]
    basis: str
    patches: tuple[str, str, str]
    rounds: int
    input_bases: tuple[str, str]
    input_signs: tuple[int, int]
    parity_sign: int
    observable_id: str
    close_data_basis: str | None = None

    @property
    def output_patches(self):
        return self.patches[:2]

    def to_dict(self):
        return {'schema': 'qec-encoded-parity/1',
                'program': self.program.to_dict(),
                'phases': [p.to_dict() for p in self.phases],
                'couplings': [asdict(c) for c in self.couplings],
                'basis': self.basis, 'patches': list(self.patches),
                'rounds_before_and_after': self.rounds,
                'input_bases': list(self.input_bases),
                'input_signs': list(self.input_signs), 'parity_sign': self.parity_sign,
                'observable_id': self.observable_id,
                'close_data_basis': self.close_data_basis,
                'resources': {'data_atoms': 27, 'syndrome_atoms': 24,
                              'total_atoms': 51, 'encoded_ancilla_patches': 1},
                'claim': 'ideal encoded nondestructive parity instrument; '
                         'bounded native-fault audit and physical execution are separate'}


def encoded_parity_program(*, basis='Z', rounds=3, patches=('A', 'B', 'C'),
                           input_bases=None, input_signs=(0, 0), parity_sign=1,
                           close_data_basis=None):
    """Prepare two inputs and an encoded ancilla, measure logical ZZ or XX.

    ``rounds`` canonical syndrome rounds occur before and after the CNOTs.
    C is |0_L> for ZZ and |+_L> for XX. A/B default to the complementary
    eigenbasis, so the instrument produces entanglement rather than a trivial
    known parity. ``input_signs`` denotes negative input logical eigenvalues.

    The production instrument retains A/B. ``close_data_basis`` adds explicit
    destructive A/B readout as a diagnostic extension and therefore changes
    the output contract; it is never implicitly part of a nondestructive PPM.
    """
    patches, input_signs = tuple(patches), tuple(input_signs)
    input_bases = tuple(input_bases) if input_bases is not None else (
        ('X', 'X') if basis == 'Z' else ('Z', 'Z'))
    if (basis not in ('X', 'Z') or type(rounds) is not int or rounds < 1
            or len(patches) != 3 or len(set(patches)) != 3
            or any(not isinstance(p, str) or not p for p in patches)
            or len(input_bases) != 2 or any(b not in ('X', 'Z') for b in input_bases)
            or len(input_signs) != 2 or any(type(s) is not int or s not in (0, 1)
                                         for s in input_signs)
            or type(parity_sign) is not int or parity_sign not in (-1, 1)
            or close_data_basis not in (None, 'X', 'Z')):
        raise ValueError('Encoded parity requires three distinct patches, X/Z bases and valid bits')
    a, b, c = patches
    templates = tuple(canonical_memory_program(basis='Z', rounds=2 * rounds, patch=p)
                      for p in patches)
    roles = tuple(role for template in templates for role in template.program.roles)
    operations, phases, couplings, detectors = [], [], [], []
    frontier = ()

    def phase(key, kind, gate_type, targets, *, ids=None, round_index=None,
              layer_index=None, dependencies=None):
        nonlocal frontier
        previous = frontier
        ids = tuple(ids) if ids is not None else tuple(f'{key}.{i}' for i in range(len(targets)))
        if len(ids) != len(targets):
            raise ValueError('Phase IDs and targets must agree')
        if not ids:
            return ()
        for i, (gid, support) in enumerate(zip(ids, targets)):
            deps = previous if dependencies is None else tuple(dependencies[i])
            operations.append(GateTask(gid, gate_type, tuple(support), deps))
        phases.append(CanonicalPhase(key, round_index, layer_index, kind, ids, previous))
        frontier = ids
        return ids

    phase('ppm.prepare.reset', 'initialize_reset', 'RESET', tuple((r.id,) for r in roles))
    preparation_bases = dict(zip(patches, (*input_bases, basis)))
    phase('ppm.prepare.plus', 'data_prepare_h', 'H',
          tuple((f'{p}.d{q}',) for p in patches if preparation_bases[p] == 'X' for q in range(9)))
    for p, input_basis, sign in zip(patches[:2], input_bases, input_signs):
        if sign:
            support = LOGICAL_Z if input_basis == 'X' else LOGICAL_X
            phase(f'{p}.prepare.negative', 'logical_input_sign',
                  'Z' if input_basis == 'X' else 'X', tuple((f'{p}.d{q}',) for q in support))

    def transversal(control, target, index):
        key = f'ppm.cx{index}.{control}.to.{target}'
        targets = tuple((f'{target}.d{q}',) for q in range(9))
        phase(f'{key}.h', 'encoded_cx_target_h', 'H', targets)
        ids = phase(f'{key}.cz', 'encoded_cx_cz', 'CZ',
                    tuple((f'{control}.d{q}', f'{target}.d{q}') for q in range(9)))
        for q, gid in enumerate(ids):
            couplings.append(CanonicalCoupling(rounds, index,
                f'{key}.d{q}', f'{target}.d{q}', f'{control}.d{q}',
                f'{control}.d{q}', f'{target}.d{q}', f'{gid}__g000'))
        phase(f'{key}.restore', 'encoded_cx_target_restore', 'H', targets)

    def previous_sector(p, kind, check):
        # Heisenberg pullback through both transversal CXs. The two CXs
        # commute, but the native sequence preserves the shared-wire order.
        sources = [p]
        if basis == 'Z':
            if kind == 'X' and p in (a, b):
                sources += [c]
            elif kind == 'Z' and p == c:
                sources += [a, b]
        else:
            if kind == 'Z' and p in (a, b):
                sources += [c]
            elif kind == 'X' and p == c:
                sources += [a, b]
        return tuple(f'{source}.r{rounds}.{kind}{check}' for source in sources)

    op_maps = [{op.id: op for op in t.program.operations} for t in templates]
    for r in range(1, 2 * rounds + 1):
        if r == rounds + 1:
            pairs = ((a, c), (b, c)) if basis == 'Z' else ((c, a), (c, b))
            for i, (control, target) in enumerate(pairs, 1):
                transversal(control, target, i)
        groups = [[p for p in t.phases if p.round_index == r] for t in templates]
        for grouped_phases in zip(*groups):
            representative = grouped_phases[0]
            native_ops = [op_maps[i][gid] for i, p in enumerate(grouped_phases) for gid in p.gate_ids]
            deps = None
            if representative.kind == 'ancilla_reset':
                deps = tuple((op.depends_on[0],) for op in native_ops)
            phase(f'ppm.r{r}.{representative.kind}' + (
                      f'.layer{representative.layer_index}' if representative.layer_index is not None else ''),
                  representative.kind, native_ops[0].gate_type,
                  tuple(op.targets for op in native_ops), ids=tuple(op.id for op in native_ops),
                  round_index=r, layer_index=representative.layer_index, dependencies=deps)
        for t in templates:
            couplings.extend(pair for pair in t.couplings if pair.round_index == r)
        for p in patches:
            for kind in (preparation_bases[p],) if r == 1 else ('X', 'Z'):
                for check in range(4):
                    current = f'{p}.r{r}.{kind}{check}'
                    if r == 1:
                        terms, boundary = (current,), 'known_product_preparation'
                    elif r == rounds + 1:
                        terms = (*previous_sector(p, kind, check), current)
                        boundary = 'transversal_check_sector_transfer'
                    else:
                        terms = (f'{p}.r{r-1}.{kind}{check}', current)
                        boundary = 'temporal'
                    detectors.append(Detector(f'{p}.det.r{r}.{kind}{check}', BitExpr(terms), boundary))

    def readout(patch, read_basis):
        if read_basis == 'X':
            phase(f'{patch}.final.h', 'data_readout_h', 'H',
                  tuple((f'{patch}.d{q}',) for q in range(9)))
        phase(f'{patch}.final.measure', 'data_measure', 'MEASURE',
              tuple((f'{patch}.d{q}',) for q in range(9)),
              ids=tuple(f'{patch}.final.m{q}' for q in range(9)))
        for check_index, support in enumerate(X_CHECKS if read_basis == 'X' else Z_CHECKS):
            detectors.append(Detector(f'{patch}.terminal.{read_basis}{check_index}',
                BitExpr((f'{patch}.r{2*rounds}.{read_basis}{check_index}',
                         *(f'{patch}.final.m{q}' for q in support))), 'destructive_readout'))
        logical_support = LOGICAL_X if read_basis == 'X' else LOGICAL_Z
        return tuple(f'{patch}.final.m{q}' for q in logical_support)

    parity_terms = readout(c, basis)
    observable_id = f'ppm.logical_{basis}{basis}'
    observables = [Observable(observable_id, BitExpr(parity_terms, int(parity_sign == -1)),
        'encoded ancilla logical parity; detector decoder required for native faults')]
    if close_data_basis is not None:
        for p in (a, b):
            terms = readout(p, close_data_basis)
            observables.append(Observable(f'{p}.logical_{close_data_basis}', BitExpr(terms),
                                          'diagnostic destructive logical output'))
    program = PBCProgram(roles, tuple(operations), tuple(detectors), tuple(observables),
                         f'd3-encoded-{basis.lower()}{basis.lower()}-{rounds}-before-after')
    return EncodedParity(program, tuple(phases), tuple(couplings), basis, patches,
                         rounds, input_bases, input_signs, parity_sign, observable_id,
                         close_data_basis)


def compile_encoded_parity(protocol, bindings=None):
    """Use the existing primitive lowering, preserving every explicit barrier."""
    if not isinstance(protocol, EncodedParity):
        raise TypeError('EncodedParity protocol required')
    return lower_to_physical(protocol.program, bindings)


def _validate_compiled_protocol(protocol, compiled):
    """Reject edited primitives, missing barriers and mismatched sidecars."""
    if compiled.program != protocol.program:
        raise ValueError('Compiled circuit is not this encoded parity protocol')
    mapping = dict(compiled.bindings)
    if (set(mapping) != {r.id for r in protocol.program.roles}
            or len(set(mapping.values())) != len(mapping)):
        raise ValueError('Encoded primitive bindings must cover distinct roles exactly')
    if len(compiled.circuit.gates) != len(protocol.program.operations):
        raise ValueError('Encoded native primitive count differs from protocol')
    for op, gate in zip(protocol.program.operations, compiled.circuit.gates):
        if (gate.id != f'{op.id}__g000' or gate.gate_type != op.gate_type
                or gate.qubit_ids != tuple(mapping[r] for r in op.targets)
                or gate.condition != op.condition):
            raise ValueError('Encoded native primitive differs from protocol')
        if not {f'{parent}__g000' for parent in op.depends_on} <= set(gate.depends_on):
            raise ValueError('Encoded native dependency barrier is missing')
    cz = {g.id: g.qubit_ids for g in compiled.circuit.gates if g.gate_type == 'CZ'}
    pairs = {p.native_cz_id: (mapping[p.control_role], mapping[p.target_role])
             for p in protocol.couplings}
    if len(pairs) != len(protocol.couplings) or pairs != cz:
        raise ValueError('Encoded coupling sidecar does not cover exact native CZ operands')


def retained_output_expectations(protocol, semantic_results):
    """Signed physical Pauli constraints for the prepared-input clean output.

    Every returned PauliProduct must have expectation +1. A/B check signs
    come from their actual closing syndrome histories; logical constraints
    preserve the coherence that separate A/B measurements would destroy.
    This helper is an ideal output contract, not a noisy state decoder.
    """
    from .pauli import PauliProduct
    from .surface import logical_product
    if protocol.close_data_basis is not None:
        raise ValueError('Retained output expectations require nondestructive data output')
    result = []
    for p in protocol.patches[:2]:
        for kind, checks in (('X', X_CHECKS), ('Z', Z_CHECKS)):
            for i, support in enumerate(checks):
                bit = semantic_results[f'{p}.r{2*protocol.rounds}.{kind}{i}']
                if type(bit) is not int or bit not in (0, 1):
                    raise ValueError('Output contract requires integer measurement bits')
                result.append(PauliProduct(tuple((f'{p}.d{q}', kind) for q in support),
                                           -1 if bit else 1))
    parity = next(o for o in protocol.program.observables if o.id == protocol.observable_id)
    physical_branch = parity.expression.evaluate(semantic_results) ^ int(protocol.parity_sign == -1)
    result.append(logical_product(PauliProduct(tuple((p, protocol.basis) for p in protocol.patches[:2]),
                                              -1 if physical_branch else 1)))
    anticommuting = []
    for p, kind, bit in zip(protocol.patches[:2], protocol.input_bases, protocol.input_signs):
        if kind == protocol.basis:
            result.append(logical_product(PauliProduct(((p, kind),), -1 if bit else 1)))
        else:
            anticommuting.append((p, kind, bit))
    if len(anticommuting) == 2:
        bit = anticommuting[0][2] ^ anticommuting[1][2]
        result.append(logical_product(PauliProduct(tuple((p, kind) for p, kind, _ in anticommuting),
                                                  -1 if bit else 1)))
    return tuple(result)


def verify_encoded_parity_instrument(protocol, compiled=None, *, seeds=(0, 7)):
    """Independent Stim Choi test of both parity branches and retained A/B.

    At the declared encoded-input boundary, A and B are each entangled with
    an untouched external reference. Their syndrome sectors remain whatever
    the real preparation measured. The expected two-input instrument uses
    one ideal logical MPP, and every expected output/reference stabilizer is
    checked on the actual native output. A Choi state fixes the branch map on
    arbitrary inputs, including inputs entangled with other systems.

    Forced logical branches are audit-only conditional instruments. Their
    probability is checked to be exactly 1/2 before forcing; production shots
    are never postselected. No audit MPP is emitted as a physical gate.
    """
    from .canonical_audit import _stim
    stim = _stim()
    if protocol.close_data_basis is not None:
        raise ValueError('Nondestructive instrument audit rejects destructive data closure')
    seeds = tuple(seeds)
    if not seeds or any(type(seed) is not int or seed < 0 for seed in seeds):
        raise ValueError('Instrument audit requires nonnegative integer seeds')
    compiled = compile_encoded_parity(protocol) if compiled is None else compiled
    _validate_compiled_protocol(protocol, compiled)
    qindex = {q: i for i, (_, q) in enumerate(compiled.bindings)}
    roles = {r: qindex[q] for r, q in compiled.bindings}
    n = len(qindex)
    first_cx = next(p.native_gate_ids[0] for p in protocol.phases
                    if p.kind == 'encoded_cx_target_h')
    first_readout = next(p.native_gate_ids[0] for p in protocol.phases
                         if p.kind in ('data_readout_h', 'data_measure'))

    def logical(patch, kind):
        x, z = stim.PauliString(n + 2), stim.PauliString(n + 2)
        for q in LOGICAL_X:
            x[roles[f'{patch}.d{q}']] = 'X'
        for q in LOGICAL_Z:
            z[roles[f'{patch}.d{q}']] = 'Z'
        return x if kind == 'X' else z if kind == 'Z' else 1j * x * z

    def mapped_observable(word):
        result = stim.PauliString(n + 2)
        result.sign = word.sign
        for i in range(4):
            kind = '_XYZ'[word[i]]
            if kind == '_':
                continue
            if i < 2:
                result *= logical(protocol.patches[i], kind)
            else:
                single = stim.PauliString(n + 2)
                single[n + i - 2] = kind
                result *= single
        return result

    reports = []
    for seed in seeds:
        for branch in (0, 1):
            actual = stim.TableauSimulator(seed=seed)
            actual.set_num_qubits(n + 2)
            expected = stim.TableauSimulator(seed=seed)
            expected.set_num_qubits(4)
            expected.h(0, 1)
            expected.cnot(0, 2)
            expected.cnot(1, 3)
            expected_parity = stim.PauliString(4)
            expected_parity[0] = expected_parity[1] = protocol.basis
            expected.postselect_observable(expected_parity, desired_value=bool(branch))
            raw = {}
            inserted_input = inserted_branch = False
            for gate in compiled.circuit.gates:
                if gate.condition:
                    raise ValueError('Independent instrument audit rejects adaptive gates')
                if gate.id == first_cx:
                    for i, p in enumerate(protocol.patches[:2]):
                        # Complementary reference preparation makes both Bell
                        # stabilizer projections possible for every input sign.
                        if protocol.input_bases[i] == 'Z':
                            actual.h(n + i)
                        for kind in ('Z', 'X'):
                            joint = logical(p, kind)
                            joint[n + i] = kind
                            actual.postselect_observable(joint, desired_value=False)
                    inserted_input = True
                if gate.id == first_readout:
                    parity = logical(protocol.patches[2], protocol.basis)
                    if actual.peek_observable_expectation(parity) != 0:
                        raise AssertionError('Choi parity branch probability is not 1/2')
                    actual.postselect_observable(parity, desired_value=bool(branch))
                    inserted_branch = True
                indices = tuple(qindex[q] for q in gate.qubit_ids)
                if gate.gate_type == 'MEASURE':
                    raw[gate.id] = int(actual.measure(indices[0]))
                else:
                    operation = stim.Circuit()
                    operation.append({'RESET': 'R'}.get(gate.gate_type, gate.gate_type), indices)
                    actual.do(operation)
            outputs = compiled.classical_outputs(raw)
            if (not inserted_input or not inserted_branch or any(outputs['detectors'].values())
                    or outputs['observables'][protocol.observable_id] != branch ^ int(protocol.parity_sign == -1)):
                raise AssertionError('Native instrument classical branch or detectors disagree')
            generators = expected.canonical_stabilizers()
            if any(actual.peek_observable_expectation(mapped_observable(g)) != 1 for g in generators):
                raise AssertionError('Native retained-data/reference channel differs from logical MPP')
            reports.append({'seed': seed, 'physical_branch': branch,
                            'semantic_branch': branch ^ int(protocol.parity_sign == -1),
                            'branch_probability': 0.5,
                            'output_reference_generators': [str(g) for g in generators],
                            'passed': True})
    return {'schema': 'qec-encoded-parity-instrument-audit/1', 'passed': True,
            'contract': 'Both Choi branches equal (I + (-1)^b P_A P_B)/2; '
                        'A/B retained, two external references untouched; '
                        'random syndrome sectors explicitly retained',
            'audit_only_operations': 'Encoded-input Bell projection and forced branch; '
                                     'no hardware MPP and no production postselection',
            'branches': reports}


def audit_encoded_parity(protocol, compiled=None, *, include_faults=False):
    """Audit parity-only single native faults in an eigenbasis calibration.

    Random logical measurements cannot be treated as deterministic DEM
    observables. The calibration uses both inputs in the measured eigenbasis;
    its gate locations, checks and propagation are otherwise the same protocol.
    The result certifies only the decoded classical parity in this model.
    Nondestructive output quantum errors require the separate instrument audit.
    """
    from .canonical_audit import (build_single_fault_decoder, native_fault_signatures,
        propagate_native_fault_signature, native_to_stim)
    if compiled is None:
        compiled = compile_encoded_parity(protocol)
    _validate_compiled_protocol(protocol, compiled)
    if protocol.input_bases != (protocol.basis, protocol.basis):
        raise ValueError('Fault DEM calibration requires parity-eigenbasis inputs')
    report = {'schema': 'qec-encoded-parity-fault-audit/1', 'passed': False,
              'scope': 'decoded classical parity for zero or one native H/X/Z/CZ '
                       'Pauli, RESET error or measurement report error; '
                       'transport/idle/loss and arbitrary noisy decoding excluded',
              'counterexamples': []}
    try:
        ideal = native_to_stim(compiled)
        ds, _ = ideal.compile_detector_sampler(seed=0).sample(32, separate_observables=True)
        if ds.any():
            raise ValueError('Noiseless sector-transfer detectors are nonzero')
        signatures = native_fault_signatures(compiled)
        disagreements = [s.fault.id for s in signatures if
            propagate_native_fault_signature(compiled, s.fault) != s]
        if disagreements:
            raise ValueError(f'Independent fault propagation disagrees: {disagreements[:5]}')
        decoder = build_single_fault_decoder(compiled, signatures)
        single = [s.fault.id for s in signatures if not s.detector_mask and s.observable_mask]
        by_mask = {}
        pairs = []
        # Equal signatures are equivalent to an undetected pair. Grouping
        # avoids a quadratic scan while retaining explicit counterexamples.
        for s in signatures:
            for other in by_mask.get(s.detector_mask, {}).values():
                if other.observable_mask != s.observable_mask and other.fault.gate_id != s.fault.gate_id:
                    pairs.append([other.fault.id, s.fault.id])
            by_mask.setdefault(s.detector_mask, {})[s.observable_mask] = s
        terminal = {m.raw_gate_id for m in compiled.measurements
                    if m.result_id.startswith(f'{protocol.patches[2]}.final.m')}
        reports = [s for s in signatures if s.fault.kind == 'measurement_report'
                   and s.fault.gate_id in terminal]
        witness = next(([s.fault.id for s in triple] for triple in combinations(reports, 3)
                        if not (triple[0].detector_mask ^ triple[1].detector_mask ^ triple[2].detector_mask)
                        and (triple[0].observable_mask ^ triple[1].observable_mask ^ triple[2].observable_mask)), None)
        report.update(native_fault_count=len(signatures),
                      gate_counts=dict(Counter(g.gate_type for g in compiled.circuit.gates)),
                      detector_count=len(compiled.program.detectors),
                      independent_pauli_frame_passed=True,
                      all_single_faults_corrected=all(dict(decoder.entries)[s.detector_mask] == s.observable_mask
                                                      for s in signatures),
                      undetected_single_faults=single[:10], undetected_pairs=pairs[:10],
                      weight_three_terminal_report_witness=witness,
                      decoder={'detector_ids': list(decoder.detector_ids),
                               'observable_ids': list(decoder.observable_ids),
                               'entries': {str(d): o for d, o in decoder.entries}})
        if include_faults:
            report['faults'] = [s.to_dict(decoder.detector_ids, decoder.observable_ids) for s in signatures]
        report['passed'] = not single and not pairs and witness is not None
    except (ValueError, AssertionError) as error:
        report['counterexamples'].append({'type': type(error).__name__, 'message': str(error)})
    return report
