"""Composable ideal X/Z logical measurements using a verified cat resource.

This frontend emits real native operations and measurement history. It does not
implement a physical controller, retries, magic states, Y measurements, or a
noisy fault-tolerant retained channel. Verification is a declared boundary at
which a future controller must stop on a nonzero report before data coupling.
"""
from dataclasses import asdict, dataclass
from itertools import product
from typing import Mapping

from .canonical import CanonicalPhase, canonical_memory_program
from .ir import BitExpr, Detector, GateTask, Observable, PBCProgram, PauliMeasurement, Role
from .lowering import lower_to_physical
from .pauli import PauliProduct
from .surface import logical_product as physical_logical_product, patch_roles


def _xor(left, right):
    return BitExpr(tuple(t for t in (*left.terms, *right.terms)
                         if (t in left.terms) != (t in right.terms)),
                   left.constant ^ right.constant)


@dataclass(frozen=True)
class CatCoupling:
    native_cz_id: str
    control_role: str
    target_role: str
    kind: str


@dataclass(frozen=True)
class MixedXZCat:
    program: PBCProgram
    prefix_operation_count: int
    namespace: str
    logical_product: PauliProduct
    physical_product: PauliProduct
    data_patches: tuple[str, str]
    rounds: int
    cat_roles: tuple[str, ...]
    verifier_role: str
    observable_id: str
    incoming_sectors: tuple[tuple[tuple[str, str, int], BitExpr], ...]
    outgoing_sectors: tuple[tuple[tuple[str, str, int], BitExpr], ...]
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
        return lower_to_physical(self.program, bindings)

    def verification_status(self, semantic_results):
        """Assess actual committed reports at the pre-data boundary.

        A missing bit is pending, never assumed zero. This assessment does not
        execute or stop the static circuit and cannot substitute for a runtime
        controller that submits the resource and data fragments separately.
        """
        missing = [key for key in self.verification_measurements if key not in semantic_results]
        if missing:
            raise ValueError('Cat verification is pending: all real measurement reports are required')
        bits = [semantic_results[key] for key in self.verification_measurements]
        if any(type(bit) is not int or bit not in (0, 1) for bit in bits):
            raise ValueError('Cat verification requires integer measurement bits')
        rejected = tuple(key for key, bit in zip(self.verification_measurements, bits) if bit)
        return {'status': 'rejected' if rejected else 'accepted', 'accepted': not rejected,
                'nonzero_reports': rejected, 'before_operation': self.coupling_entry_id,
                'runtime_abort_implemented': False, 'retry_implemented': False}

    def to_dict(self):
        return {'schema': 'mixed-xz-cat-ideal-native/1', 'program': self.program.to_dict(),
                'prefix_operation_count': self.prefix_operation_count, 'namespace': self.namespace,
                'logical_product': self.logical_product.to_dict(),
                'physical_product': self.physical_product.to_dict(), 'rounds': self.rounds,
                'data_patches': list(self.data_patches), 'cat_roles': list(self.cat_roles),
                'verifier_role': self.verifier_role, 'resource_reused': self.resource_reused,
                'resource_epoch': self.namespace, 'observable_id': self.observable_id,
                'incoming_sectors': [{'key': list(k), 'expression': e.to_dict()} for k, e in self.incoming_sectors],
                'outgoing_sectors': [{'key': list(k), 'expression': e.to_dict()} for k, e in self.outgoing_sectors],
                'cat_measurements': list(self.cat_measurements),
                'verification': {'measurements': list(self.verification_measurements),
                    'expected_bits': [0] * len(self.verification_measurements),
                    'before_operation': self.coupling_entry_id, 'nonzero_policy': 'reject before data coupling',
                    'runtime_abort_implemented': False, 'retry_implemented': False},
                'phases': [p.to_dict() for p in self.phases],
                'couplings': [asdict(c) for c in self.couplings],
                'scope': 'ideal native circuit on declared encoded-input sectors',
                'physical_executed': False, 'fault_tolerance_audited': False,
                'complete_algorithm_encoded': False}


def append_mixed_xz_cat(prefix: PBCProgram, incoming_sectors: Mapping, logical_product: PauliProduct, *,
                        data_patches=('A', 'B'), rounds=3, cat_roles=None, verifier_role=None,
                        namespace='xzcat', resource_reuse=False, pending_operations=()):
    """Append one signed logical X/Z product without repreparing data.

    The standard weight-three representatives are expanded to one cat atom per
    physical factor. Two complete passes measure every neighboring cat ZZ
    check using a genuinely prepared/read/reset verifier. The caller declares
    a completed prefix, released auxiliaries, and its measured sector history;
    an explicitly pending execution frontier is rejected.
    """
    if not isinstance(prefix, PBCProgram) or not isinstance(incoming_sectors, Mapping):
        raise TypeError('Expected a PBCProgram and explicit incoming-sector mapping')
    if not isinstance(logical_product, PauliProduct):
        raise TypeError('Expected a signed logical PauliProduct')
    if pending_operations:
        raise ValueError('Pending prefix operations must complete before cat composition')
    if type(rounds) is not int or rounds < 1:
        raise ValueError('Positive canonical syndrome rounds are required')
    if type(resource_reuse) is not bool:
        raise ValueError('Resource reuse must be an explicit boolean')
    data_patches = tuple(data_patches)
    if (len(data_patches) != 2 or len(set(data_patches)) != 2 or
            any(not isinstance(p, str) or not p for p in data_patches)):
        raise ValueError('Two distinct declared data patches are required')
    if not logical_product.factors or not set(logical_product.support) <= set(data_patches):
        raise ValueError('A nontrivial product on declared data patches is required')
    if any(basis not in ('X', 'Z') for _, basis in logical_product.factors):
        raise ValueError('Y requires an explicit S/Sdg backend; only X/Z products are supported')
    if not isinstance(namespace, str) or not namespace.strip():
        raise ValueError('A nonempty cat namespace is required')
    roles = {role.id: role for role in prefix.roles}
    for patch in data_patches:
        if any(roles.get(role.id) != role for role in patch_roles(patch)):
            raise ValueError('Declared input patches require all canonical data and syndrome roles')
    measured = {op.id for op in prefix.operations if isinstance(op, PauliMeasurement) or op.gate_type == 'MEASURE'}
    keys = tuple((p, kind, i) for p in data_patches for kind in ('X', 'Z') for i in range(4))
    if set(incoming_sectors) != set(keys):
        raise ValueError('All 16 incoming sectors must be declared exactly')
    for key in keys:
        expression = incoming_sectors[key]
        if not isinstance(expression, BitExpr) or not expression.terms or not set(expression.terms) <= measured:
            raise ValueError('Incoming sectors require actual prefix measurements, with explicit signed constants')
    last, last_nonreset = {}, {}
    for op in prefix.operations:
        targets = op.targets if isinstance(op, GateTask) else (op.ancilla, *op.product.support)
        for target in targets:
            last[target] = op
            if not isinstance(op, GateTask) or op.gate_type != 'RESET':
                last_nonreset[target] = op
    def released(role):
        op = last.get(role)
        return ((isinstance(op, GateTask) and op.gate_type == 'RESET') or
                (isinstance(op, PauliMeasurement) and op.ancilla == role))
    for patch in data_patches:
        for role in patch_roles(patch):
            if role.kind == 'syndrome_ancilla' and not released(role.id):
                raise ValueError('Prefix syndrome auxiliaries must be reset/released')
            op = last.get(role.id)
            if role.kind == 'data' and isinstance(op, GateTask) and op.gate_type in ('RESET', 'MEASURE'):
                raise ValueError('Input data must remain encoded and unconsumed')
    physical = physical_logical_product(logical_product)
    occupied = {op.id for op in prefix.operations} | {d.id for d in prefix.detectors} | {o.id for o in prefix.observables}
    base, count = namespace, 0
    while any(key == namespace or key.startswith(namespace + '.') for key in occupied):
        count += 1
        namespace = f'{base}.next{count}'
    cat_roles = tuple(cat_roles) if cat_roles is not None else tuple(f'{namespace}.cat{i}' for i in range(len(physical.factors)))
    verifier_role = verifier_role if verifier_role is not None else f'{namespace}.verifier'
    resource_ids = (*cat_roles, verifier_role)
    if (len(cat_roles) != len(physical.factors) or len(set(resource_ids)) != len(resource_ids) or
            any(not isinstance(role, str) or not role.strip() for role in resource_ids)):
        raise ValueError('One distinct cat role per physical factor and a separate verifier are required')
    expected_roles = tuple(Role(role, 'parity_ancilla') for role in resource_ids)
    if resource_reuse:
        if any(roles.get(role.id) != role for role in expected_roles):
            raise ValueError('Resource reuse requires the complete existing cat/verifier role set')
        if any(not released(role) or not isinstance(last_nonreset.get(role), GateTask) or
               last_nonreset[role].gate_type != 'MEASURE' for role in resource_ids):
            raise ValueError('Resource reuse requires real destructive measurement and final RESET of every cat/verifier')
    elif any(role in roles for role in resource_ids):
        raise ValueError('Cat/verifier roles must be fresh unless reuse is explicitly declared')
    operations, phases, couplings, detectors = [], [], [], list(prefix.detectors)
    depended = {key for op in prefix.operations for key in op.depends_on}
    frontier = tuple(op.id for op in prefix.operations if op.id not in depended)
    sectors = dict(incoming_sectors)
    def emit(key, kind, targets, phase_kind):
        nonlocal frontier
        gid, entry = f'{namespace}.{key}', frontier
        operations.append(GateTask(gid, kind, tuple(targets), entry))
        phases.append(CanonicalPhase(gid, None, None, phase_kind, (gid,), entry))
        if kind == 'CZ':
            couplings.append(CatCoupling(gid + '__g000', targets[0], targets[1], phase_kind))
        frontier = (gid,)
        return gid
    def cx(key, control, target, phase_kind):
        emit(key + '.h', 'H', (target,), phase_kind)
        emit(key + '.cz', 'CZ', (control, target), phase_kind)
        emit(key + '.restore', 'H', (target,), phase_kind)
    def syndrome(stage):
        nonlocal frontier
        for patch in data_patches:
            template = canonical_memory_program(patch=patch, rounds=rounds)
            op_map, retained = {op.id: op for op in template.program.operations}, set()
            rename = lambda key: f'{namespace}.{stage}.{key}'
            for phase in template.phases:
                if phase.round_index is None:
                    continue
                entry, ids = frontier, []
                for key in phase.gate_ids:
                    op = op_map[key]
                    deps = tuple(rename(parent) for parent in op.depends_on if parent in retained) or entry
                    gid = rename(key)
                    operations.append(GateTask(gid, op.gate_type, op.targets, deps))
                    if op.gate_type == 'CZ':
                        couplings.append(CatCoupling(gid + '__g000', *op.targets, 'syndrome'))
                    ids.append(gid)
                    retained.add(key)
                phases.append(CanonicalPhase(rename(phase.id), phase.round_index, phase.layer_index,
                                             phase.kind, tuple(ids), entry))
                frontier = tuple(ids)
            for r in range(1, rounds + 1):
                for kind in ('X', 'Z'):
                    for i in range(4):
                        key = patch, kind, i
                        current = BitExpr((rename(f'{patch}.r{r}.{kind}{i}'),))
                        boundary = 'incoming_measured_sector' if stage == 'before' and r == 1 else 'temporal'
                        detectors.append(Detector(rename(f'{patch}.det.r{r}.{kind}{i}'),
                                                  _xor(sectors[key], current), boundary))
                        sectors[key] = current
    syndrome('before')
    for i, role in enumerate(resource_ids):
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
            result = emit(key + '.measure', 'MEASURE', (verifier_role,), 'cat_verification')
            verification.append(result)
            detectors.append(Detector(result + '.zero', BitExpr((result,)), 'cat_verification'))
            emit(key + '.release', 'RESET', (verifier_role,), 'cat_verification')
    coupling_entry = None
    for i, (data, basis) in enumerate(physical.factors):
        if basis == 'X':
            gid = emit(f'couple{i}.h', 'H', (data,), 'data_coupling')
        else:
            gid = f'{namespace}.couple{i}.cz'
        coupling_entry = coupling_entry or gid
        emit(f'couple{i}.cz', 'CZ', (cat_roles[i], data), 'data_coupling')
        if basis == 'X':
            emit(f'couple{i}.restore', 'H', (data,), 'data_coupling')
    cat_measurements = []
    for i, role in enumerate(cat_roles):
        emit(f'readout.cat{i}.h', 'H', (role,), 'cat_readout')
        cat_measurements.append(emit(f'readout.cat{i}.measure', 'MEASURE', (role,), 'cat_readout'))
        emit(f'readout.cat{i}.reset', 'RESET', (role,), 'cat_release')
    syndrome('after')
    observable_id = f'{namespace}.logical_product'
    observable = Observable(observable_id, BitExpr(tuple(cat_measurements), int(physical.sign == -1)),
                            'signed ideal cat-product parity; retained data, no noisy decoder claim')
    new_roles = () if resource_reuse else expected_roles
    program = PBCProgram((*prefix.roles, *new_roles), (*prefix.operations, *operations),
                         tuple(detectors), (*prefix.observables, observable),
                         f'{prefix.name}+{namespace}', prefix.memory_contract)
    return MixedXZCat(program, len(prefix.operations), namespace, logical_product, physical,
                      data_patches, rounds, cat_roles, verifier_role, observable_id,
                      tuple((key, incoming_sectors[key]) for key in keys), tuple(sectors.items()),
                      tuple(verification), tuple(cat_measurements), coupling_entry,
                      tuple(phases), tuple(couplings), resource_reuse)


def verify_mixed_xz_instruments(instruments, *, reference_roles=(), seeds=(0, 7), forced_cat_bits=None):
    """Independent Stim projector audit; forced outcomes are audit-only.

    Actual native preparation and prefix are always executed. The oracle copies
    that actual encoded state before the first instrument, then applies only
    its ideal signed projectors. All logical/reference Pauli expectations and
    every retained stabilizer are compared. Outcome forcing uses postselection
    only in this test simulator, never in the emitted native circuit.
    """
    from .canonical_audit import _stim
    from neutral_atom_experiments.surface_ghz import LOGICAL_X, LOGICAL_Z, X_CHECKS, Z_CHECKS
    stim = _stim()
    instruments, reference_roles, seeds = tuple(instruments), tuple(reference_roles), tuple(seeds)
    if not instruments or any(not isinstance(item, MixedXZCat) for item in instruments):
        raise ValueError('At least one mixed X/Z cat instrument is required')
    if len(reference_roles) > 2 or len(set(reference_roles)) != len(reference_roles):
        raise ValueError('Up to two distinct external reference roles are supported')
    if not seeds or any(type(seed) is not int or seed < 0 for seed in seeds):
        raise ValueError('Nonnegative integer audit seeds are required')
    for previous, following in zip(instruments, instruments[1:]):
        if (following.program.operations[:following.prefix_operation_count] != previous.program.operations or
                following.data_patches != previous.data_patches):
            raise ValueError('Instrument chain must preserve the complete prefix and declared data patches')
    forced = {} if forced_cat_bits is None else dict(forced_cat_bits)
    cat_ids = {key for item in instruments for key in item.cat_measurements}
    if not set(forced) <= cat_ids or any(type(bit) is not int or bit not in (0, 1) for bit in forced.values()):
        raise ValueError('Forced audit outcomes must be bits of declared cat readouts')
    compiled = instruments[-1].compile()
    index = {role: i for i, (role, _) in enumerate(compiled.bindings)}
    qindex = {qubit: index[role] for role, qubit in compiled.bindings}
    role_map = {role.id: role for role in compiled.program.roles}
    data_role_ids = {r.id for p in instruments[0].data_patches for r in patch_roles(p)}
    if (not set(reference_roles) <= set(index) or set(reference_roles) & data_role_ids or
            any(role_map[role].kind != 'data' for role in reference_roles)):
        raise ValueError('External reference roles must exist outside the declared data patches')
    n = len(index)
    semantic_map = {m.result_id: (m.raw_gate_id, m.bit_flip) for m in compiled.measurements}
    forced_native = {semantic_map[key][0]: bit ^ semantic_map[key][1] for key, bit in forced.items()}
    first = instruments[0].program.operations[instruments[0].prefix_operation_count].id + '__g000'
    entries = {item.coupling_entry_id + '__g000': item for item in instruments}
    ends = {item.program.operations[-1].id + '__g000': item for item in instruments}
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
        raw, expected, branches, forced_probability = {}, None, [], 1.0
        def semantic():
            return {key: raw[native] ^ flip for key, (native, flip) in semantic_map.items() if native in raw}
        def sector_word(patch, kind, check):
            word = stim.PauliString(n)
            for q in (X_CHECKS if kind == 'X' else Z_CHECKS)[check]:
                word[index[f'{patch}.d{q}']] = kind
            return word
        for gate in compiled.circuit.gates:
            if gate.id == first:
                bits = semantic()
                for (patch, kind, check), expression in instruments[0].incoming_sectors:
                    if actual.peek_observable_expectation(sector_word(patch, kind, check)) != (-1) ** expression.evaluate(bits):
                        raise AssertionError('Input is outside its declared incoming measured sector codespace')
                expected = actual.copy()
            if gate.id in entries:
                status = entries[gate.id].verification_status(semantic())
                if not status['accepted']:
                    raise AssertionError('Cat verification rejected before data coupling')
            if gate.condition and not all(raw[key] == bit for key, bit in gate.condition):
                continue
            qs = [qindex[q] for q in gate.qubit_ids]
            if gate.gate_type == 'MEASURE':
                if gate.id in forced_native:
                    bit = forced_native[gate.id]
                    probability = (1 + (-1) ** bit * actual.peek_z(qs[0])) / 2
                    if probability <= 0:
                        raise AssertionError('Forced cat-readout branch has zero native probability')
                    forced_probability *= probability
                    actual.postselect_z(qs[0], desired_value=bool(bit))
                    raw[gate.id] = bit
                else:
                    raw[gate.id] = int(actual.measure(qs[0]))
            else:
                step = stim.Circuit()
                step.append({'RESET': 'R'}.get(gate.gate_type, gate.gate_type), qs)
                actual.do(step)
            if gate.id in ends:
                item, bits = ends[gate.id], semantic()
                observable = next(o for o in item.program.observables if o.id == item.observable_id)
                branch = observable.expression.evaluate(bits)
                parity = stim.PauliString(n)
                for patch, kind in item.logical_product.factors:
                    parity *= logical(patch, kind)
                parity *= item.logical_product.sign
                probability = (1 + (-1) ** branch * expected.peek_observable_expectation(parity)) / 2
                if probability <= 0:
                    raise AssertionError('Native product branch has zero ideal projector probability')
                expected.postselect_observable(parity, desired_value=bool(branch))
                checked = 0
                for kinds in product('IXYZ', repeat=2 + len(reference_roles)):
                    word = stim.PauliString(n)
                    for i, kind in enumerate(kinds):
                        if kind == 'I':
                            continue
                        if i < 2:
                            word *= logical(item.data_patches[i], kind)
                        else:
                            reference = stim.PauliString(n)
                            reference[index[reference_roles[i - 2]]] = kind
                            word *= reference
                    if actual.peek_observable_expectation(word) != expected.peek_observable_expectation(word):
                        raise AssertionError('Native cat instrument changed the logical/reference density operator')
                    checked += 1
                detectors = [d for d in item.program.detectors if d.id.startswith(item.namespace + '.')]
                if any(d.expression.evaluate(bits) for d in detectors):
                    raise AssertionError('Cat clean detector disagrees with incoming measured sector history')
                for (patch, kind, check), expression in item.outgoing_sectors:
                    sector = sector_word(patch, kind, check)
                    if actual.peek_observable_expectation(sector) != (-1) ** expression.evaluate(bits):
                        raise AssertionError('Retained stabilizer differs from real closing sector report')
                branches.append({'namespace': item.namespace, 'semantic_branch': branch,
                    'physical_branch': branch ^ int(item.physical_product.sign == -1),
                    'branch_probability_given_prefix': probability,
                    'logical_reference_paulis_checked': checked, 'retained_sector_checks': 16,
                    'detectors_checked': len(detectors), 'verification': item.verification_status(bits),
                    'passed': True})
        if expected is None or len(branches) != len(instruments):
            raise AssertionError('Audit did not execute every declared instrument boundary')
        reports.append({'seed': seed, 'branches': branches, 'forced_native_probability': forced_probability, 'passed': True})
    return {'passed': True, 'scope': 'ideal native encoded-input signed projector channel audit',
            'shots': reports, 'declared_role_count': n, 'native_gates': len(compiled.circuit.gates),
            'prefix_state_replayed': True, 'input_state_replaced': False,
            'incoming_codespace_verified': True,
            'outcome_forcing_is_audit_only': bool(forced), 'physical_executed': False,
            'fault_tolerance_audited': False, 'runtime_abort_implemented': False,
            'complete_algorithm_encoded': False}
