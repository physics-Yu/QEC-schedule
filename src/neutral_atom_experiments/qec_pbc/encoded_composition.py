"""Append an encoded parity instrument to retained encoded data inputs.

Incoming signed stabilizer sectors are real prefix measurement expressions.
Data are never reset/prepared here; fresh or explicitly consumed resources are
reset/prepared by real native operations for every resource epoch.
Syndrome auxiliaries retain their ordinary measurement/reset reuse protocol.
No existing 51-atom physical initialization runner is invoked by this module.
"""
from dataclasses import asdict, dataclass
from itertools import product
from typing import Mapping

from .canonical import CanonicalCoupling, CanonicalPhase
from .encoded_ppm import encoded_parity_program
from .ir import BitExpr, Detector, GateTask, Observable, PBCProgram, PauliMeasurement
from .lowering import lower_to_physical
from .surface import patch_roles


def _xor(*expressions):
    terms, constant = [], 0
    for expression in expressions:
        constant ^= expression.constant
        for term in expression.terms:
            if term in terms:
                terms.remove(term)
            else:
                terms.append(term)
    return BitExpr(tuple(terms), constant)


@dataclass(frozen=True)
class EncodedComposition:
    program: PBCProgram
    prefix_operation_count: int
    namespace: str
    basis: str
    patches: tuple[str, str, str]
    rounds: int
    parity_sign: int
    observable_id: str
    incoming_sectors: tuple[tuple[tuple[str, str, int], BitExpr], ...]
    outgoing_sectors: tuple[tuple[tuple[str, str, int], BitExpr], ...]
    phases: tuple[CanonicalPhase, ...]
    couplings: tuple[CanonicalCoupling, ...]
    resource_reused: bool = False

    @property
    def output_sectors(self):
        return dict(self.outgoing_sectors)

    def compile(self, bindings=None):
        return lower_to_physical(self.program, bindings)

    def to_dict(self):
        return {'schema': 'encoded-parity-composition-v1', 'program': self.program.to_dict(),
                'prefix_operation_count': self.prefix_operation_count, 'namespace': self.namespace,
                'basis': self.basis, 'patches': list(self.patches), 'rounds': self.rounds,
                'parity_sign': self.parity_sign, 'observable_id': self.observable_id,
                'incoming_sectors': [{'patch': k[0], 'kind': k[1], 'check': k[2], 'expression': v.to_dict()} for k, v in self.incoming_sectors],
                'outgoing_sectors': [{'patch': k[0], 'kind': k[1], 'check': k[2], 'expression': v.to_dict()} for k, v in self.outgoing_sectors],
                'phases': [p.to_dict() for p in self.phases], 'couplings': [asdict(c) for c in self.couplings],
                'retained_output_patches': list(self.patches[:2]),
                'resource_patch': self.patches[2], 'resource_reused': self.resource_reused,
                'resource_epoch': self.namespace,
                'fresh_resource_patch': None if self.resource_reused else self.patches[2],
                'resource_reuse_supported': True, 'magic_factory_reuse': False,
                'scope': 'composable ideal encoded parity native circuit; physical adapter/execution and fault audit are separate',
                'physical_executed': False, 'complete_algorithm_encoded': False}


def append_encoded_parity(prefix: PBCProgram, incoming_sectors: Mapping[tuple[str, str, int], BitExpr], *,
                          basis='Z', rounds=3, data_patches=('A', 'B'), ancilla_patch='C',
                          namespace='ppm', parity_sign=1, resource_reuse=False) -> EncodedComposition:
    """Preserve prefix exactly, consume encoded inputs and prepare C.

    Each incoming expression must contain actual earlier measurement IDs.
    The caller declares how its preceding operations transported sector signs.
    Prefix syndrome auxiliaries must already be reset/released, as they are
    after a canonical round or high-level PauliMeasurement instrument.
    Default C is fresh. Explicit reuse requires all nine C data to have been
    destructively measured/reset and all eight auxiliaries reset/released;
    every reused epoch still emits its complete physical RESET/preparation.
    """
    if not isinstance(prefix, PBCProgram) or not isinstance(incoming_sectors, Mapping):
        raise TypeError('Composition requires PBCProgram and explicit incoming-sector mapping')
    if type(resource_reuse) is not bool:
        raise ValueError('Resource reuse must be an explicit boolean')
    data_patches = tuple(data_patches)
    if len(data_patches) != 2 or len(set(data_patches)) != 2 or ancilla_patch in data_patches:
        raise ValueError('Two distinct data patches and a fresh resource patch are required')
    if not isinstance(namespace, str) or not namespace.strip():
        raise ValueError('A nonempty composition namespace is required')
    template = encoded_parity_program(basis=basis, rounds=rounds,
                                      patches=(*data_patches, ancilla_patch), parity_sign=parity_sign)
    roles = {r.id: r for r in prefix.roles}
    for patch in data_patches:
        if any(roles.get(role.id) != role for role in patch_roles(patch)):
            raise ValueError('Incoming data patches must contain all canonical data and syndrome roles')
    resource_roles = patch_roles(ancilla_patch)
    resource_exists = any(role.id in roles for role in resource_roles) or any(r.patch == ancilla_patch for r in prefix.roles)
    if resource_exists and not resource_reuse:
        raise ValueError('Resource patch must be fresh; consumed-patch reuse needs an explicit preparation contract')
    if resource_reuse and (not resource_exists or any(roles.get(role.id) != role for role in resource_roles)):
        raise ValueError('Resource reuse requires an existing complete canonical patch')
    measured = {op.id for op in prefix.operations if isinstance(op, PauliMeasurement) or op.gate_type == 'MEASURE'}
    keys = tuple((p, kind, i) for p in data_patches for kind in ('X', 'Z') for i in range(4))
    if set(incoming_sectors) != set(keys):
        raise ValueError('All 16 incoming data stabilizer sectors must be declared exactly')
    for key in keys:
        expression = incoming_sectors[key]
        if not isinstance(expression, BitExpr) or not expression.terms or not set(expression.terms) <= measured:
            raise ValueError('Incoming sectors must refer to actual prefix measurements, including signed constants')
    last = {}
    for op in prefix.operations:
        targets = op.targets if isinstance(op, GateTask) else (op.ancilla, *op.product.support)
        for target in targets:
            last[target] = op
    for patch in data_patches:
        for role in patch_roles(patch):
            if role.kind == 'syndrome_ancilla':
                op = last.get(role.id)
                released = isinstance(op, GateTask) and op.gate_type == 'RESET'
                released |= isinstance(op, PauliMeasurement) and op.ancilla == role.id
                if not released:
                    raise ValueError('Prefix syndrome auxiliaries must be explicitly reset/released before composition')
    if resource_reuse:
        for role in resource_roles:
            op = last.get(role.id)
            if role.kind == 'data':
                consumed = isinstance(op, GateTask) and op.gate_type in ('MEASURE', 'RESET')
                if not consumed:
                    raise ValueError('Resource reuse requires explicit destructive MEASURE/RESET of all nine data roles')
            else:
                released = isinstance(op, GateTask) and op.gate_type == 'RESET'
                released |= isinstance(op, PauliMeasurement) and op.ancilla == role.id
                if not released:
                    raise ValueError('Resource reuse requires every syndrome auxiliary to be reset/released')
    occupied = {op.id for op in prefix.operations} | {d.id for d in prefix.detectors} | {o.id for o in prefix.observables}
    base, count = namespace, 0
    while any(key == namespace or key.startswith(namespace + '.') for key in occupied):
        count += 1
        namespace = f'{base}.next{count}'
    rename = lambda key: f'{namespace}.{key}'
    op_map = {op.id: op for op in template.program.operations}
    operations, phases, couplings = [], [], []
    depended = {key for op in prefix.operations for key in op.depends_on}
    frontier = tuple(op.id for op in prefix.operations if op.id not in depended)
    retained_ids = set()
    for phase in template.phases:
        native = [op_map[key] for key in phase.gate_ids]
        if phase.kind in ('initialize_reset', 'data_prepare_h'):
            native = [op for op in native if all(target.startswith(ancilla_patch + '.') for target in op.targets)]
        if not native:
            continue
        entry = frontier
        ids = []
        for op in native:
            dependencies = tuple(rename(key) for key in op.depends_on if key in retained_ids)
            if not dependencies:
                dependencies = entry
            gid = rename(op.id)
            operations.append(GateTask(gid, op.gate_type, op.targets, dependencies, op.condition))
            ids.append(gid)
            retained_ids.add(op.id)
        phases.append(CanonicalPhase(rename(phase.id), phase.round_index, phase.layer_index,
                                     phase.kind, tuple(ids), entry))
        frontier = tuple(ids)
    for coupling in template.couplings:
        couplings.append(CanonicalCoupling(coupling.round_index, coupling.layer_index,
            rename(coupling.check_id), coupling.ancilla_role, coupling.data_role,
            coupling.control_role, coupling.target_role, rename(coupling.native_cz_id)))
    detectors = list(prefix.detectors)
    for detector in template.program.detectors:
        if detector.boundary == 'known_product_preparation' and any(detector.id.startswith(p + '.det.') for p in data_patches):
            continue
        detectors.append(Detector(rename(detector.id), BitExpr(tuple(rename(t) for t in detector.expression.terms), detector.expression.constant), detector.boundary))
    for key in keys:
        patch, kind, check = key
        current = BitExpr((rename(f'{patch}.r1.{kind}{check}'),))
        detectors.append(Detector(rename(f'{patch}.incoming.{kind}{check}'),
                                   _xor(incoming_sectors[key], current), 'incoming_measured_sector'))
    observable = template.program.observables[0]
    observable_id = rename(observable.id)
    observables = (*prefix.observables, Observable(observable_id,
        BitExpr(tuple(rename(t) for t in observable.expression.terms), observable.expression.constant),
        'composed encoded parity; data inputs retained and resource consumed'))
    new_roles = () if resource_reuse else resource_roles
    program = PBCProgram((*prefix.roles, *new_roles), (*prefix.operations, *operations),
                         tuple(detectors), observables, f'{prefix.name}+{namespace}-{basis}{basis}', prefix.memory_contract)
    outgoing = tuple((key, BitExpr((rename(f'{key[0]}.r{2*rounds}.{key[1]}{key[2]}'),))) for key in keys)
    return EncodedComposition(program, len(prefix.operations), namespace, basis,
                              (*data_patches, ancilla_patch), rounds, parity_sign, observable_id,
                              tuple((key, incoming_sectors[key]) for key in keys), outgoing,
                              tuple(phases), tuple(couplings), resource_reuse)


def verify_composed_instruments(compositions, *, reference_roles=(), seeds=(0, 7)):
    """Replay the real prefix; compare logical/reference density operators.

    No expected state is installed in the native simulator.  The ideal oracle
    copies the actually executed prefix state, then applies only ideal logical
    parity projectors at the observed branches. All logical/reference Pauli
    expectations are compared, so coherence and entanglement are retained.
    """
    from .canonical_audit import _stim
    from neutral_atom_experiments.surface_ghz import LOGICAL_X, LOGICAL_Z, X_CHECKS, Z_CHECKS
    stim = _stim()
    compositions, reference_roles, seeds = tuple(compositions), tuple(reference_roles), tuple(seeds)
    if not compositions or any(not isinstance(c, EncodedComposition) for c in compositions):
        raise ValueError('At least one composed encoded instrument is required')
    if len(reference_roles) > 2 or len(set(reference_roles)) != len(reference_roles):
        raise ValueError('Audit supports up to two distinct physical reference roles')
    if not seeds or any(type(s) is not int or s < 0 for s in seeds):
        raise ValueError('Audit seeds must be nonnegative integers')
    for previous, following in zip(compositions, compositions[1:]):
        if following.program.operations[:following.prefix_operation_count] != previous.program.operations:
            raise ValueError('Instrument chain must preserve the complete preceding program')
    compiled = compositions[-1].compile()
    index = {role: i for i, (role, _) in enumerate(compiled.bindings)}
    qindex = {qubit: index[role] for role, qubit in compiled.bindings}
    if not set(reference_roles) <= index.keys():
        raise ValueError('Reference roles must exist in the real prefix')
    n = len(index)
    semantic_map = {m.result_id: (m.raw_gate_id, m.bit_flip) for m in compiled.measurements}
    first = compositions[0].program.operations[compositions[0].prefix_operation_count].id + '__g000'
    ends = {c.program.operations[-1].id + '__g000': c for c in compositions}

    def logical(patch, kind):
        x, z = stim.PauliString(n), stim.PauliString(n)
        for q in LOGICAL_X:
            x[index[f'{patch}.d{q}']] = 'X'
        for q in LOGICAL_Z:
            z[index[f'{patch}.d{q}']] = 'Z'
        return x if kind == 'X' else z if kind == 'Z' else 1j * x * z

    reports = []
    for seed in seeds:
        actual = stim.TableauSimulator(seed=seed)
        actual.set_num_qubits(n)
        raw, expected, branches = {}, None, []
        for gate in compiled.circuit.gates:
            if gate.id == first:
                expected = actual.copy()
            if gate.condition and not all((raw[semantic_map[key][0]] ^ semantic_map[key][1]) == bit for key, bit in gate.condition):
                continue
            qs = [qindex[q] for q in gate.qubit_ids]
            if gate.gate_type == 'MEASURE':
                raw[gate.id] = int(actual.measure(qs[0]))
            else:
                step = stim.Circuit()
                step.append({'RESET': 'R'}.get(gate.gate_type, gate.gate_type), qs)
                actual.do(step)
            if gate.id in ends:
                composition = ends[gate.id]
                semantic = {key: raw[native] ^ flip for key, (native, flip) in semantic_map.items() if native in raw}
                observable = next(o for o in composition.program.observables if o.id == composition.observable_id)
                physical_branch = observable.expression.evaluate(semantic) ^ int(composition.parity_sign == -1)
                parity = logical(composition.patches[0], composition.basis) * logical(composition.patches[1], composition.basis)
                expectation = expected.peek_observable_expectation(parity)
                probability = (1 + (-1) ** physical_branch * expectation) / 2
                if probability <= 0:
                    raise AssertionError('Native parity branch has zero probability in the ideal input instrument')
                expected.postselect_observable(parity, desired_value=bool(physical_branch))
                checked = 0
                for kinds in product('IXYZ', repeat=2 + len(reference_roles)):
                    word = stim.PauliString(n)
                    for i, kind in enumerate(kinds):
                        if kind == 'I':
                            continue
                        if i < 2:
                            word *= logical(composition.patches[i], kind)
                        else:
                            reference = stim.PauliString(n)
                            reference[index[reference_roles[i - 2]]] = kind
                            word *= reference
                    if actual.peek_observable_expectation(word) != expected.peek_observable_expectation(word):
                        raise AssertionError('Composed native parity changed the logical/reference density operator')
                    checked += 1
                detectors = [d for d in composition.program.detectors if d.id.startswith(composition.namespace + '.')]
                if any(d.expression.evaluate(semantic) for d in detectors):
                    raise AssertionError('Composed clean detector disagrees with incoming/transported sector history')
                for (patch, kind, check), expression in composition.outgoing_sectors:
                    sector = stim.PauliString(n)
                    support = (X_CHECKS if kind == 'X' else Z_CHECKS)[check]
                    for q in support:
                        sector[index[f'{patch}.d{q}']] = kind
                    if actual.peek_observable_expectation(sector) != (-1) ** expression.evaluate(semantic):
                        raise AssertionError('Retained output sector differs from real closing measurement')
                branches.append({'namespace': composition.namespace, 'basis': composition.basis,
                                 'physical_branch': physical_branch, 'semantic_branch': observable.expression.evaluate(semantic),
                                 'branch_probability_given_prefix': probability,
                                 'logical_reference_paulis_checked': checked, 'detectors_checked': len(detectors),
                                 'retained_sector_checks': 16, 'passed': True})
        if expected is None or len(branches) != len(compositions):
            raise AssertionError('Composed audit did not execute every declared instrument boundary')
        reports.append({'seed': seed, 'branches': branches, 'passed': True})
    return {'passed': True, 'scope': 'ideal native prefix/composed-instrument logical-reference channel audit',
            'shots': reports, 'prefix_state_replayed': True, 'input_state_replaced': False,
            'declared_role_count': n,
            'resource_epochs': [{'namespace': c.namespace, 'patch': c.patches[2], 'reused': c.resource_reused}
                                for c in compositions],
            'native_gates': len(compiled.circuit.gates), 'physical_executed': False,
            'fault_tolerance_audited': False, 'complete_algorithm_encoded': False}
