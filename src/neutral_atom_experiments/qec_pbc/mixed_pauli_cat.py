"""Signed X/Y/Z cat instruments: native circuits and exact Clifford reference.

T;T=S is recognized only as an indivisible, verified reference fragment. This
does not extend GateTask, tracked ENV, runtime verification or fault tolerance.
"""
from dataclasses import asdict, dataclass, replace
from itertools import product
from typing import Mapping

from neutral_atom_env.circuit import PhysicalCircuit
from neutral_atom_env.domain.models import PhysicalGate

from .canonical import CanonicalPhase, canonical_memory_program
from .ir import BitExpr, Detector, Observable, PBCProgram, Role
from .lowering import MeasurementBinding, lower_to_physical
from .mixed_xz_cat import CatCoupling, _xor
from .pauli import PauliProduct
from .surface import logical_product as physical_logical_product, patch_roles


@dataclass(frozen=True)
class NativeCatProgram:
    """Experiment-only role-based native gates, NOT a PBCProgram extension."""
    roles: tuple[Role, ...]
    operations: tuple[PhysicalGate, ...]
    measurements: tuple[MeasurementBinding, ...]
    detectors: tuple[Detector, ...]
    observables: tuple[Observable, ...]
    name: str
    memory_contract: object = None

    def __post_init__(self):
        for name in ('roles', 'operations', 'measurements', 'detectors', 'observables'):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        roles = {r.id for r in self.roles}
        if len(roles) != len(self.roles) or any(not set(g.qubit_ids) <= roles for g in self.operations):
            raise ValueError('Native cat roles must be unique and cover every actual gate')
        PhysicalCircuit(self.operations)
        measured = {g.id for g in self.operations if g.gate_type == 'MEASURE'}
        semantic = {m.result_id for m in self.measurements}
        if (len(semantic) != len(self.measurements) or
                any(m.raw_gate_id not in measured or type(m.bit_flip) is not int or m.bit_flip not in (0, 1)
                    for m in self.measurements)):
            raise ValueError('Semantic records require real native measurement IDs and integer sign bits')
        for outputs in (self.detectors, self.observables):
            if len({o.id for o in outputs}) != len(outputs) or any(not set(o.expression.terms) <= semantic for o in outputs):
                raise ValueError('Classical outputs require unique IDs and actual semantic measurements')

    def to_dict(self):
        return {'schema': 'native-cat-experiment/1', 'name': self.name,
                'roles': [asdict(r) for r in self.roles],
                'operations': [asdict(g) for g in self.operations],
                'measurements': [asdict(m) for m in self.measurements],
                'detectors': [asdict(d) for d in self.detectors],
                'observables': [asdict(o) for o in self.observables],
                'memory_contract': None if self.memory_contract is None else asdict(self.memory_contract)}


@dataclass(frozen=True)
class NativeCatCompilation:
    program: NativeCatProgram
    circuit: PhysicalCircuit
    bindings: tuple[tuple[str, str], ...]
    measurements: tuple[MeasurementBinding, ...]

    def semantic_results(self, raw_measurements):
        bits = {}
        for m in self.measurements:
            bit = raw_measurements[m.raw_gate_id]
            if type(bit) is not int or bit not in (0, 1):
                raise ValueError('Raw reports must be integer bits')
            bits[m.result_id] = bit ^ m.bit_flip
        return bits


@dataclass(frozen=True)
class MixedPauliCat:
    program: NativeCatProgram
    prefix_gate_count: int
    namespace: str
    logical_product: PauliProduct
    physical_product: PauliProduct
    data_patches: tuple[str, ...]
    rounds: int
    cat_roles: tuple[str, ...]
    verifier_role: str
    observable_id: str
    incoming_sectors: tuple
    outgoing_sectors: tuple
    verification_measurements: tuple[str, ...]
    cat_measurements: tuple[str, ...]
    coupling_entry_id: str
    phases: tuple[CanonicalPhase, ...]
    couplings: tuple[CatCoupling, ...]
    resource_reused: bool

    @property
    def output_sectors(self):
        return dict(self.outgoing_sectors)

    def compile(self, bindings=None):
        ids = tuple(r.id for r in self.program.roles)
        mapping = dict(bindings) if bindings is not None else {r: f'Q{i:03d}' for i, r in enumerate(ids)}
        if (set(mapping) != set(ids) or len(set(mapping.values())) != len(ids) or
                any(type(q) is not str or not q for q in mapping.values())):
            raise ValueError('Bindings require all roles and distinct nonempty physical IDs')
        gates = tuple(replace(g, qubit_ids=tuple(mapping[q] for q in g.qubit_ids)) for g in self.program.operations)
        return NativeCatCompilation(self.program, PhysicalCircuit(gates), tuple(mapping.items()), self.program.measurements)

    def verification_status(self, semantic_results):
        if any(key not in semantic_results for key in self.verification_measurements):
            raise ValueError('Cat verification pending: actual reports are required')
        bits = tuple(semantic_results[key] for key in self.verification_measurements)
        if any(type(bit) is not int or bit not in (0, 1) for bit in bits):
            raise ValueError('Verification requires integer bits')
        rejected = tuple(k for k, b in zip(self.verification_measurements, bits) if b)
        return {'accepted': not rejected, 'nonzero_reports': rejected,
                'before_operation': self.coupling_entry_id, 'runtime_abort_implemented': False,
                'retry_implemented': False}

    def to_dict(self):
        return {'schema': 'mixed-pauli-cat-ideal-native/1', 'program': self.program.to_dict(),
                'namespace': self.namespace, 'prefix_gate_count': self.prefix_gate_count,
                'logical_product': self.logical_product.to_dict(), 'physical_product': self.physical_product.to_dict(),
                'data_patches': list(self.data_patches), 'cat_roles': list(self.cat_roles),
                'verifier_role': self.verifier_role, 'resource_epoch': self.namespace,
                'resource_reused': self.resource_reused, 'observable_id': self.observable_id,
                'incoming_sectors': [{'key': list(k), 'expression': e.to_dict()} for k, e in self.incoming_sectors],
                'outgoing_sectors': [{'key': list(k), 'expression': e.to_dict()} for k, e in self.outgoing_sectors],
                'cat_measurements': list(self.cat_measurements),
                'verification_measurements': list(self.verification_measurements),
                'coupling_entry_id': self.coupling_entry_id,
                'phases': [p.to_dict() for p in self.phases], 'couplings': [asdict(c) for c in self.couplings],
                'scope': 'experiment-only native producer and exact ideal Clifford reference',
                'native_t_gates': sum(g.gate_type == 'T' for g in self.program.operations[self.prefix_gate_count:]),
                'tt_reference_identity': 'adjacent strictly isolated T;T=S, exact matrix including global phase',
                'tracked_env_t_supported': False, 'pbc_gate_task_extended': False,
                'runtime_abort_implemented': False, 'retry_implemented': False,
                'physical_executed': False, 'fault_tolerance_audited': False,
                'magic_resource_consumed': False, 'complete_algorithm_encoded': False}


def _native_prefix(prefix):
    if isinstance(prefix, NativeCatProgram):
        return prefix
    if isinstance(prefix, MixedPauliCat):
        return prefix.program
    if not isinstance(prefix, PBCProgram):
        raise TypeError('Prefix must be a PBCProgram, NativeCatProgram or prior MixedPauliCat experiment')
    compiled = lower_to_physical(prefix)
    reverse = {q: role for role, q in compiled.bindings}
    gates = tuple(replace(g, qubit_ids=tuple(reverse[q] for q in g.qubit_ids)) for g in compiled.circuit.gates)
    return NativeCatProgram(prefix.roles, gates, compiled.measurements, prefix.detectors,
                            prefix.observables, prefix.name, prefix.memory_contract)


def append_mixed_pauli_cat(prefix, incoming_sectors: Mapping, logical_product: PauliProduct, *,
                           data_patches=('A', 'B'), rounds=3, cat_roles=None, verifier_role=None,
                           namespace='paulicat', resource_reuse=False, pending_operations=()):
    """Append a signed product without resetting or changing encoded inputs.

    A validated NativeCatProgram is accepted as an experiment-only prefix,
    preserving actual non-Clifford producer gates without extending PBC IR.
    Y is CZ→H_d CZ H_d→T_c T_c. Coupling is uninterrupted; only the cat receives
    the phase. Original raw gates and semantic history are retained verbatim.
    """
    native = _native_prefix(prefix)
    if not isinstance(incoming_sectors, Mapping) or not isinstance(logical_product, PauliProduct):
        raise TypeError('Explicit incoming history and a signed logical PauliProduct are required')
    if pending_operations:
        raise ValueError('Pending prefix operations must complete before composition')
    if type(rounds) is not int or rounds < 1 or type(resource_reuse) is not bool:
        raise ValueError('Positive integer rounds and explicit boolean reuse are required')
    patches = tuple(data_patches)
    if (not patches or len(set(patches)) != len(patches) or
            any(type(p) is not str or not p for p in patches)):
        raise ValueError('Distinct standard data patches are required')
    if not logical_product.factors or not set(logical_product.support) <= set(patches):
        raise ValueError('Nontrivial logical product must use the declared patches')
    if type(namespace) is not str or not namespace.strip():
        raise ValueError('Nonempty namespace required')
    roles = {r.id: r for r in native.roles}
    if any(roles.get(r.id) != r for p in patches for r in patch_roles(p)):
        raise ValueError('All canonical data and syndrome roles are required')
    measured = {m.result_id for m in native.measurements}
    keys = tuple((p, kind, i) for p in patches for kind in ('X', 'Z') for i in range(4))
    if set(incoming_sectors) != set(keys) or any(not isinstance(e, BitExpr) or not e.terms or
            not set(e.terms) <= measured for e in incoming_sectors.values()):
        raise ValueError('All incoming sectors must reference real prefix measurements')
    last, last_nonreset = {}, {}
    for g in native.operations:
        for target in g.qubit_ids:
            last[target] = g
            if g.gate_type != 'RESET':
                last_nonreset[target] = g
    def released(role):
        return role in last and last[role].gate_type == 'RESET'
    if any(not released(r.id) for p in patches for r in patch_roles(p) if r.kind == 'syndrome_ancilla'):
        raise ValueError('Syndrome auxiliaries require a real final RESET')
    if any(last.get(r.id) and last[r.id].gate_type in ('RESET', 'MEASURE')
           for p in patches for r in patch_roles(p) if r.kind == 'data'):
        raise ValueError('Encoded data must remain unconsumed')
    physical = physical_logical_product(logical_product)
    occupied = {g.id for g in native.operations} | measured | {o.id for o in (*native.detectors, *native.observables)}
    base, count = namespace, 0
    while any(key == namespace or key.startswith(namespace + '.') for key in occupied):
        count += 1
        namespace = f'{base}.next{count}'
    cat_roles = tuple(cat_roles) if cat_roles is not None else tuple(f'{namespace}.cat{i}' for i in range(len(physical.factors)))
    verifier_role = f'{namespace}.verifier' if verifier_role is None else verifier_role
    resource = (*cat_roles, verifier_role)
    if (len(cat_roles) != len(physical.factors) or len(set(resource)) != len(resource) or
            any(type(r) is not str or not r.strip() for r in resource)):
        raise ValueError('Distinct cat roles must cover all physical factors, plus one verifier')
    expected_roles = tuple(Role(r, 'parity_ancilla') for r in resource)
    if resource_reuse:
        if (any(roles.get(r.id) != r for r in expected_roles) or any(not released(r) or
                r not in last_nonreset or last_nonreset[r].gate_type != 'MEASURE' for r in resource)):
            raise ValueError('Reuse requires complete roles, destructive measurements and final RESET')
    elif set(resource) & set(roles):
        raise ValueError('Resources must be fresh unless reuse is explicit')
    operations, records = list(native.operations), list(native.measurements)
    detectors, observables = list(native.detectors), list(native.observables)
    phases, couplings, sectors = [], [], dict(incoming_sectors)
    depended = {key for g in operations for key in g.depends_on}
    frontier = tuple(g.id for g in operations if g.id not in depended)
    def emit(key, kind, targets, phase):
        nonlocal frontier
        semantic, entry = f'{namespace}.{key}', frontier
        gid = semantic + '__g000'
        operations.append(PhysicalGate(gid, kind, tuple(targets), depends_on=entry))
        phases.append(CanonicalPhase(semantic, None, None, phase, (gid,), entry))
        if kind == 'MEASURE':
            records.append(MeasurementBinding(semantic, gid, 0, phase))
        if kind == 'CZ':
            couplings.append(CatCoupling(gid, *targets, phase))
        frontier = (gid,)
        return semantic, gid
    def cx(key, control, target, phase):
        emit(key + '.h', 'H', (target,), phase)
        emit(key + '.cz', 'CZ', (control, target), phase)
        emit(key + '.restore', 'H', (target,), phase)
    def syndrome(stage):
        nonlocal frontier
        for patch in patches:
            template = canonical_memory_program(patch=patch, rounds=rounds)
            op_map, retained = {o.id: o for o in template.program.operations}, set()
            rename = lambda key: f'{namespace}.{stage}.{key}'
            for phase in template.phases:
                if phase.round_index is None:
                    continue
                entry, ids = frontier, []
                for key in phase.gate_ids:
                    op = op_map[key]
                    deps = tuple(rename(p) + '__g000' for p in op.depends_on if p in retained) or entry
                    gid = rename(key) + '__g000'
                    operations.append(PhysicalGate(gid, op.gate_type, op.targets, depends_on=deps))
                    if op.gate_type == 'MEASURE':
                        records.append(MeasurementBinding(rename(key), gid, 0, 'syndrome'))
                    if op.gate_type == 'CZ':
                        couplings.append(CatCoupling(gid, *op.targets, 'syndrome'))
                    retained.add(key)
                    ids.append(gid)
                phases.append(CanonicalPhase(rename(phase.id), phase.round_index, phase.layer_index,
                                             phase.kind, tuple(ids), entry))
                frontier = tuple(ids)
            for r in range(1, rounds + 1):
                for kind in ('X', 'Z'):
                    for i in range(4):
                        key = patch, kind, i
                        current = BitExpr((rename(f'{patch}.r{r}.{kind}{i}'),))
                        boundary = 'incoming_measured_sector' if stage == 'before' and r == 1 else 'temporal'
                        detectors.append(Detector(rename(f'{patch}.det.r{r}.{kind}{i}'), _xor(sectors[key], current), boundary))
                        sectors[key] = current
    syndrome('before')
    for i, role in enumerate(resource):
        emit(f'prepare.reset{i}', 'RESET', (role,), 'cat_prepare')
    emit('prepare.h', 'H', (cat_roles[0],), 'cat_prepare')
    for i in range(len(cat_roles) - 1):
        cx(f'prepare.cx{i}', cat_roles[i], cat_roles[i + 1], 'cat_prepare')
    verification = []
    for repeat in range(2):
        for i in range(len(cat_roles) - 1):
            key = f'verify.r{repeat + 1}.link{i}'
            emit(key + '.reset', 'RESET', (verifier_role,), 'cat_verification')
            cx(key + '.left', cat_roles[i], verifier_role, 'cat_verification')
            cx(key + '.right', cat_roles[i + 1], verifier_role, 'cat_verification')
            result, _ = emit(key + '.measure', 'MEASURE', (verifier_role,), 'cat_verification')
            verification.append(result)
            detectors.append(Detector(result + '.zero', BitExpr((result,)), 'cat_verification'))
            emit(key + '.release', 'RESET', (verifier_role,), 'cat_verification')
    coupling_entry = None
    for i, (data, basis) in enumerate(physical.factors):
        if basis in ('Z', 'Y'):
            _, gid = emit(f'couple{i}.z', 'CZ', (cat_roles[i], data), 'data_coupling')
        else:
            gid = f'{namespace}.couple{i}.x.h__g000'
        coupling_entry = coupling_entry or gid
        if basis in ('X', 'Y'):
            cx(f'couple{i}.x', cat_roles[i], data, 'data_coupling')
        if basis == 'Y':
            emit(f'couple{i}.s.t0', 'T', (cat_roles[i],), 'data_coupling')
            emit(f'couple{i}.s.t1', 'T', (cat_roles[i],), 'data_coupling')
    cat_measurements = []
    for i, role in enumerate(cat_roles):
        emit(f'readout.cat{i}.h', 'H', (role,), 'cat_readout')
        result, _ = emit(f'readout.cat{i}.measure', 'MEASURE', (role,), 'cat_readout')
        cat_measurements.append(result)
        emit(f'readout.cat{i}.reset', 'RESET', (role,), 'cat_release')
    syndrome('after')
    observable_id = f'{namespace}.logical_product'
    observables.append(Observable(observable_id, BitExpr(tuple(cat_measurements), int(physical.sign == -1)),
                                  'signed ideal X/Y/Z cat parity with retained encoded data'))
    program = NativeCatProgram((*native.roles, *(expected_roles if not resource_reuse else ())),
                               tuple(operations), tuple(records), tuple(detectors), tuple(observables),
                               f'{native.name}+{namespace}', native.memory_contract)
    return MixedPauliCat(program, len(native.operations), namespace, logical_product, physical,
                         patches, rounds, cat_roles, verifier_role, observable_id,
                         tuple((k, incoming_sectors[k]) for k in keys), tuple(sectors.items()),
                         tuple(verification), tuple(cat_measurements), coupling_entry,
                         tuple(phases), tuple(couplings), resource_reuse)


@dataclass(frozen=True)
class CliffordReferenceStep:
    native_gate_ids: tuple[str, ...]
    gate_type: str
    qubit_ids: tuple[str, ...]
    condition: tuple
    readout_flip: bool


def clifford_reference_steps(circuit: PhysicalCircuit):
    """Validate an exact reference grouping without rewriting the native gates.

    Strictly adjacent TT on the same atom must be a direct chain. No competing
    successor can observe/interleave after its first non-Clifford T. Single T,
    Tdg, native S and parametrized gates are rejected by this scoped adapter.
    """
    successors = {}
    for g in circuit.gates:
        for parent in g.depends_on:
            successors.setdefault(parent, set()).add(g.id)
    gates = {g.id: g for g in circuit.gates}
    def descends(gate, parent):
        pending, seen = list(gate.depends_on), set()
        while pending:
            key = pending.pop()
            if key == parent:
                return True
            if key not in seen:
                seen.add(key)
                pending.extend(gates[key].depends_on)
        return False
    steps, i = [], 0
    while i < len(circuit.gates):
        first = circuit.gates[i]
        ids, kind = (first.id,), first.gate_type
        if kind == 'T':
            second = circuit.gates[i + 1] if i + 1 < len(circuit.gates) else None
            if (second is None or second.gate_type != 'T' or second.qubit_ids != first.qubit_ids or
                    first.condition or second.condition or first.parameters or second.parameters or
                    first.readout_flip or second.readout_flip or second.depends_on != (first.id,) or
                    successors.get(first.id) != {second.id} or
                    any(set(g.qubit_ids) & set(first.qubit_ids) and not descends(g, second.id)
                        for g in circuit.gates[i + 2:])):
                raise ValueError('Non-Clifford T requires an adjacent isolated exact TT=S reference pair')
            ids, kind, i = (first.id, second.id), 'S', i + 1
        elif kind not in {'H', 'X', 'Y', 'Z', 'CZ', 'RESET', 'MEASURE'} or first.parameters:
            raise ValueError('Unsupported gate in exact Clifford reference adapter')
        steps.append(CliffordReferenceStep(ids, kind, first.qubit_ids, first.condition, first.readout_flip))
        i += 1
    return tuple(steps)


def _validate_factorization_fragment(item):
    """Reject altered or unaccounted native gates before a whole-gadget proof.

    This qualification is intentionally strict: native-location perturbations
    require another audit. It includes actual DAG edges, measurements, release
    order and canonical boundaries; metadata never makes a missing gate real.
    """
    if (type(item.prefix_gate_count) is not int or not 0 <= item.prefix_gate_count < len(item.program.operations) or
            physical_logical_product(item.logical_product) != item.physical_product or
            len(item.cat_roles) != len(item.physical_product.factors) or
            len(set((*item.cat_roles, item.verifier_role))) != len(item.cat_roles) + 1):
        raise ValueError('Invalid native cat factorization contract')
    prefix, tail = item.program.operations[:item.prefix_gate_count], item.program.operations[item.prefix_gate_count:]
    if tuple(g for phase in item.phases for g in phase.gate_ids) != tuple(g.id for g in tail):
        raise ValueError('Actual native tail must match the complete ordered phase ledger')
    depended = {parent for g in prefix for parent in g.depends_on}
    frontier = tuple(g.id for g in prefix if g.id not in depended)
    expected, measurements = [], []
    def emit(key, kind, targets):
        nonlocal frontier
        semantic = item.namespace + '.' + key
        gid = semantic + '__g000'
        expected.append(PhysicalGate(gid, kind, tuple(targets), depends_on=frontier))
        if kind == 'MEASURE':
            measurements.append((semantic, gid, 0))
        frontier = (gid,)
    def cx(key, control, target):
        emit(key + '.h', 'H', (target,))
        emit(key + '.cz', 'CZ', (control, target))
        emit(key + '.restore', 'H', (target,))
    def syndrome(stage):
        nonlocal frontier
        for patch in item.data_patches:
            template = canonical_memory_program(patch=patch, rounds=item.rounds)
            op_map, retained = {o.id: o for o in template.program.operations}, set()
            rename = lambda key: f'{item.namespace}.{stage}.{key}'
            for phase in template.phases:
                if phase.round_index is None:
                    continue
                entry, ids = frontier, []
                for key in phase.gate_ids:
                    op = op_map[key]
                    gid = rename(key) + '__g000'
                    deps = tuple(rename(p) + '__g000' for p in op.depends_on if p in retained) or entry
                    expected.append(PhysicalGate(gid, op.gate_type, op.targets, depends_on=deps))
                    if op.gate_type == 'MEASURE':
                        measurements.append((rename(key), gid, 0))
                    retained.add(key)
                    ids.append(gid)
                frontier = tuple(ids)
    syndrome('before')
    for i, role in enumerate((*item.cat_roles, item.verifier_role)):
        emit(f'prepare.reset{i}', 'RESET', (role,))
    emit('prepare.h', 'H', (item.cat_roles[0],))
    for i in range(len(item.cat_roles) - 1):
        cx(f'prepare.cx{i}', item.cat_roles[i], item.cat_roles[i + 1])
    verification = []
    for repeat in range(2):
        for i in range(len(item.cat_roles) - 1):
            key = f'verify.r{repeat + 1}.link{i}'
            emit(key + '.reset', 'RESET', (item.verifier_role,))
            cx(key + '.left', item.cat_roles[i], item.verifier_role)
            cx(key + '.right', item.cat_roles[i + 1], item.verifier_role)
            emit(key + '.measure', 'MEASURE', (item.verifier_role,))
            verification.append(item.namespace + '.' + key + '.measure')
            emit(key + '.release', 'RESET', (item.verifier_role,))
    coupling_entry = None
    for i, (data, basis) in enumerate(item.physical_product.factors):
        entry = (f'{item.namespace}.couple{i}.z__g000' if basis in ('Z', 'Y') else
                 f'{item.namespace}.couple{i}.x.h__g000')
        coupling_entry = coupling_entry or entry
        if basis in ('Z', 'Y'):
            emit(f'couple{i}.z', 'CZ', (item.cat_roles[i], data))
        if basis in ('X', 'Y'):
            cx(f'couple{i}.x', item.cat_roles[i], data)
        if basis == 'Y':
            emit(f'couple{i}.s.t0', 'T', (item.cat_roles[i],))
            emit(f'couple{i}.s.t1', 'T', (item.cat_roles[i],))
    readouts = []
    for i, role in enumerate(item.cat_roles):
        emit(f'readout.cat{i}.h', 'H', (role,))
        emit(f'readout.cat{i}.measure', 'MEASURE', (role,))
        readouts.append(f'{item.namespace}.readout.cat{i}.measure')
        emit(f'readout.cat{i}.reset', 'RESET', (role,))
    syndrome('after')
    if tuple(expected) != tuple(tail):
        raise ValueError('Actual native cat fragment differs from its qualified preparation/coupling/readout/release contract')
    raw_ids = {g.id for g in tail if g.gate_type == 'MEASURE'}
    actual_measurements = tuple((m.result_id, m.raw_gate_id, m.bit_flip) for m in item.program.measurements if m.raw_gate_id in raw_ids)
    observable = next((o for o in item.program.observables if o.id == item.observable_id), None)
    if (tuple(measurements) != actual_measurements or tuple(readouts) != item.cat_measurements or
            tuple(verification) != item.verification_measurements or coupling_entry != item.coupling_entry_id or
            observable is None or observable.expression != BitExpr(tuple(readouts), int(item.physical_product.sign == -1))):
        raise ValueError('Actual cat measurement sidecar differs from its signed raw-record contract')


def audit_cat_factorized_kraus(item: MixedPauliCat):
    """Independent dense local matrices and all raw Kraus coefficients (L<=16).

    The factorization is exact: each cat controls one distinct data factor. The
    actual native GHZ preparation and each complete controlled-P fragment are
    simulated, then every actual X-bra string is contracted with both GHZ arms.
    This is a noiseless algebra audit, not an encoded-channel or FT substitute.
    """
    import numpy as np
    from .encoded_resource_reference import apply_native_unitaries
    if not isinstance(item, MixedPauliCat) or len(item.cat_roles) > 16:
        raise ValueError('All-raw factorized audit requires a MixedPauliCat with at most 16 cat atoms')
    _validate_factorization_fragment(item)
    identity = np.eye(2, dtype=complex)
    paulis = {'X': np.array([[0, 1], [1, 0]], dtype=complex),
              'Y': np.array([[0, -1j], [1j, 0]], dtype=complex),
              'Z': np.diag([1, -1]).astype(complex)}
    n = len(item.cat_roles)
    tail = item.program.operations[item.prefix_gate_count:]
    preparation = PhysicalCircuit(tuple(replace(g, depends_on=()) for g in tail
        if g.id.startswith(item.namespace + '.prepare.') and g.gate_type != 'RESET'))
    initial = np.zeros(1 << n, dtype=complex)
    initial[0] = 1
    ghz = apply_native_unitaries(preparation, initial, item.cat_roles)
    target = initial / np.sqrt(2)
    target[-1] = 1 / np.sqrt(2)
    ghz_error = float(np.linalg.norm(ghz - target))
    arm_ratios, errors = [], []
    for i, (data, basis) in enumerate(item.physical_product.factors):
        gates = PhysicalCircuit(tuple(replace(g, depends_on=()) for g in tail
            if g.id.startswith(f'{item.namespace}.couple{i}.')))
        actual = np.column_stack([apply_native_unitaries(gates, v, (item.cat_roles[i], data))
                                  for v in np.eye(4, dtype=complex).T])
        expected = np.zeros((4, 4), dtype=complex)
        expected[:2, :2], expected[2:, 2:] = identity, paulis[basis]
        errors.append(float(np.linalg.norm(actual - expected, ord=2)))
        arm_ratios.append(np.trace(paulis[basis].conj().T @ actual[2:, 2:]) / 2)
    readout_bras = []
    for i, role in enumerate(item.cat_roles):
        gates = PhysicalCircuit(tuple(replace(g, depends_on=()) for g in tail
            if g.id.startswith(f'{item.namespace}.readout.cat{i}.') and g.gate_type not in ('MEASURE', 'RESET')))
        readout_bras.append(np.column_stack([apply_native_unitaries(gates, v, (role,))
                                            for v in np.eye(2, dtype=complex).T]))
    error, probabilities = 0.0, [0.0, 0.0]
    # Maximally entangled logical/reference input gives probability 1/2 for
    # each signed projector. Each raw record has probability 2^-L.
    for bits in product((0, 1), repeat=n):
        q = sum(bits) % 2
        semantic = q ^ int(item.physical_product.sign == -1)
        bras = np.array([np.prod([readout_bras[i][bit, arm] for i, bit in enumerate(bits)])
                         for arm in (0, 1)])
        native_coeff = np.array([ghz[0] * bras[0], ghz[-1] * bras[1] * np.prod(arm_ratios)])
        expected_coeff = np.array([1, item.physical_product.sign * (-1) ** semantic]) / np.sqrt(1 << (n + 1))
        error = max(error, float(np.linalg.norm(native_coeff - expected_coeff)))
        probabilities[semantic] += float(np.vdot(native_coeff, native_coeff).real)
    passed = ghz_error < 1e-12 and max(errors) < 1e-12 and error < 1e-12
    if not passed:
        raise AssertionError('Actual native cat preparation/coupling failed exact signed Kraus factorization')
    return {'passed': True, 'scope': 'native local matrices and all-raw noiseless Kraus factorization',
            'cat_length': n, 'raw_branches_checked': 1 << n, 'controlled_factor_matrix_error': max(errors),
            'ghz_preparation_error': ghz_error, 'kraus_coefficient_error': error,
            'actual_complete_fragment_qualified': True, 'actual_native_readout_bras_contracted': True,
            'signed_projector_probabilities_on_choi_input': probabilities,
            'complete_raw_record_reveals_only_joint_parity': True,
            'physical_executed': False, 'fault_tolerance_audited': False}


def verify_mixed_pauli_instruments(instruments, *, reference_roles=(), seeds=(0, 7), forced_cat_bits=None):
    """Execute actual native prefix/reference fragments and compare full Pauli channels.

    Stim provides the exact Clifford oracle only after strict TT qualification.
    Forced branches are reference-only postselection, never emitted controls.
    """
    from .canonical_audit import _stim
    from neutral_atom_experiments.surface_ghz import LOGICAL_X, LOGICAL_Z, X_CHECKS, Z_CHECKS
    stim = _stim()
    instruments, refs, seeds = tuple(instruments), tuple(reference_roles), tuple(seeds)
    if not instruments or any(not isinstance(item, MixedPauliCat) for item in instruments):
        raise ValueError('At least one MixedPauliCat instrument is required')
    if not seeds or any(type(seed) is not int or seed < 0 for seed in seeds):
        raise ValueError('Nonnegative integer seeds required')
    for before, after in zip(instruments, instruments[1:]):
        p, q = before.program, after.program
        if (q.operations[:after.prefix_gate_count] != p.operations or q.roles[:len(p.roles)] != p.roles or
                q.measurements[:len(p.measurements)] != p.measurements or
                q.detectors[:len(p.detectors)] != p.detectors or q.observables[:len(p.observables)] != p.observables or
                q.memory_contract != p.memory_contract or after.data_patches != before.data_patches):
            raise ValueError('Instrument chain must preserve the complete native prefix contract')
    compiled = instruments[-1].compile()
    index = {role: i for i, (role, _) in enumerate(compiled.bindings)}
    qindex = {q: index[role] for role, q in compiled.bindings}
    role_map = {r.id: r for r in compiled.program.roles}
    data = {r.id for p in instruments[0].data_patches for r in patch_roles(p)}
    if (len(refs) > 3 or len(set(refs)) != len(refs) or not set(refs) <= set(index) or set(refs) & data or
            any(role_map[r].kind != 'data' for r in refs)):
        raise ValueError('References require up to three distinct external data roles')
    if len(instruments[0].data_patches) + len(refs) > 6:
        raise ValueError('Exhaustive ideal channel audit is limited to six logical/reference qubits')
    forced = {} if forced_cat_bits is None else dict(forced_cat_bits)
    cat_ids = {key for item in instruments for key in item.cat_measurements}
    if not set(forced) <= cat_ids or any(type(b) is not int or b not in (0, 1) for b in forced.values()):
        raise ValueError('Forced audit outcomes require actual cat report IDs and integer bits')
    semantic_map = {m.result_id: (m.raw_gate_id, m.bit_flip) for m in compiled.measurements}
    forced_raw = {semantic_map[k][0]: b ^ semantic_map[k][1] for k, b in forced.items()}
    first = compiled.circuit.gates[instruments[0].prefix_gate_count].id
    entries = {item.coupling_entry_id: item for item in instruments}
    ends = {item.program.operations[-1].id: item for item in instruments}
    steps = clifford_reference_steps(compiled.circuit)
    n = len(index)
    def logical(patch, kind):
        x, z = stim.PauliString(n), stim.PauliString(n)
        for q in LOGICAL_X:
            x[index[f'{patch}.d{q}']] = 'X'
        for q in LOGICAL_Z:
            z[index[f'{patch}.d{q}']] = 'Z'
        return x if kind == 'X' else z if kind == 'Z' else 1j * x * z
    def sector_word(patch, kind, check):
        word = stim.PauliString(n)
        for q in (X_CHECKS if kind == 'X' else Z_CHECKS)[check]:
            word[index[f'{patch}.d{q}']] = kind
        return word
    reports = []
    for seed in seeds:
        actual = stim.TableauSimulator(seed=seed)
        actual.set_num_qubits(n)
        raw, expected, branches, forced_probability = {}, None, [], 1.0
        def semantic():
            return {k: raw[g] ^ flip for k, (g, flip) in semantic_map.items() if g in raw}
        for step in steps:
            gid = step.native_gate_ids[0]
            if gid == first:
                bits = semantic()
                for (patch, kind, check), expr in instruments[0].incoming_sectors:
                    if actual.peek_observable_expectation(sector_word(patch, kind, check)) != (-1) ** expr.evaluate(bits):
                        raise AssertionError('Input differs from its actual incoming signed sector codespace')
                expected = actual.copy()
            if gid in entries and not entries[gid].verification_status(semantic())['accepted']:
                raise AssertionError('Cat verification rejected before data coupling')
            if step.condition and not all(raw[k] == bit for k, bit in step.condition):
                continue
            qs = [qindex[q] for q in step.qubit_ids]
            if step.gate_type == 'MEASURE':
                if gid in forced_raw:
                    bit = forced_raw[gid]
                    truth = bit ^ int(step.readout_flip)
                    probability = (1 + (-1) ** truth * actual.peek_z(qs[0])) / 2
                    if probability <= 0:
                        raise AssertionError('Forced native branch has zero probability')
                    forced_probability *= probability
                    actual.postselect_z(qs[0], desired_value=bool(truth))
                    raw[gid] = bit
                else:
                    raw[gid] = int(actual.measure(qs[0])) ^ int(step.readout_flip)
            else:
                fragment = stim.Circuit()
                fragment.append({'RESET': 'R'}.get(step.gate_type, step.gate_type), qs)
                actual.do(fragment)
            if step.native_gate_ids[-1] in ends:
                item, bits = ends[step.native_gate_ids[-1]], semantic()
                observable = next(o for o in item.program.observables if o.id == item.observable_id)
                branch = observable.expression.evaluate(bits)
                parity = stim.PauliString(n)
                for patch, kind in item.logical_product.factors:
                    parity *= logical(patch, kind)
                parity *= item.logical_product.sign
                probability = (1 + (-1) ** branch * expected.peek_observable_expectation(parity)) / 2
                if probability <= 0:
                    raise AssertionError('Native branch has zero ideal projector probability')
                expected.postselect_observable(parity, desired_value=bool(branch))
                checked = 0
                for kinds in product('IXYZ', repeat=len(item.data_patches) + len(refs)):
                    word = stim.PauliString(n)
                    for j, kind in enumerate(kinds):
                        if kind == 'I':
                            continue
                        if j < len(item.data_patches):
                            word *= logical(item.data_patches[j], kind)
                        else:
                            ref = stim.PauliString(n)
                            ref[index[refs[j - len(item.data_patches)]]] = kind
                            word *= ref
                    if actual.peek_observable_expectation(word) != expected.peek_observable_expectation(word):
                        raise AssertionError('Native instrument changed the logical/reference density operator')
                    checked += 1
                detectors = [d for d in item.program.detectors if d.id.startswith(item.namespace + '.')]
                if any(d.expression.evaluate(bits) for d in detectors):
                    raise AssertionError('Clean detector disagrees with actual incoming history')
                for (patch, kind, check), expr in item.outgoing_sectors:
                    if actual.peek_observable_expectation(sector_word(patch, kind, check)) != (-1) ** expr.evaluate(bits):
                        raise AssertionError('Retained stabilizer differs from actual closing report')
                branches.append({'namespace': item.namespace, 'semantic_branch': branch,
                    'physical_branch': branch ^ int(item.physical_product.sign == -1),
                    'branch_probability_given_prefix': probability,
                    'logical_reference_paulis_checked': checked, 'retained_sector_checks': 8 * len(item.data_patches),
                    'verification': item.verification_status(bits), 'passed': True})
        if expected is None or len(branches) != len(instruments):
            raise AssertionError('Reference failed to execute every instrument boundary')
        reports.append({'seed': seed, 'branches': branches, 'forced_native_probability': forced_probability, 'passed': True})
    return {'passed': True, 'scope': 'actual native prefix plus strict TT Clifford reference instrument',
            'shots': reports, 'declared_role_count': n, 'native_gates': len(compiled.circuit.gates),
            'prefix_state_replayed': True, 'input_state_replaced': False, 'incoming_codespace_verified': True,
            'outcome_forcing_is_audit_only': bool(forced), 'tt_reference_pairs': sum(s.gate_type == 'S' for s in steps),
            'tracked_env_t_supported': False, 'pbc_gate_task_extended': False, 'runtime_abort_implemented': False,
            'retry_implemented': False, 'physical_executed': False, 'fault_tolerance_audited': False,
            'magic_resource_consumed': False, 'complete_algorithm_encoded': False}
