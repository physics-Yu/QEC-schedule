"""Scalable exact *ideal* native cat instrument; no physical Executor claim.

The complete native transcript is qualified before exploiting GHZ structure.
The proof is operator-valued, so a data input may retain arbitrary external
entanglement. It does not enumerate 2**L raw outcomes or weaken the old audit.
Canonical syndrome banks and actual runtime acceptance remain caller duties.
"""
from dataclasses import asdict, dataclass
from functools import lru_cache
import hashlib
import json
import math
from collections.abc import Mapping

import numpy as np

from neutral_atom_env.circuit import PhysicalCircuit
from neutral_atom_env.domain.models import PhysicalGate
from .ir import BitExpr, Detector, Observable, Role
from .lowering import MeasurementBinding
from .mixed_pauli_cat import NativeCatProgram
from .pauli import PauliProduct
from .surface import logical_product as physical_logical_product, patch_roles, stabilizers


MAX_CAT_LENGTH = 63
_H = np.array([[1, 1], [1, -1]], dtype=complex) / math.sqrt(2)
_I = np.eye(2, dtype=complex)
_P = {'X': np.array([[0, 1], [1, 0]], dtype=complex),
      'Y': np.array([[0, -1j], [1j, 0]], dtype=complex),
      'Z': np.diag([1, -1]).astype(complex)}


@dataclass(frozen=True)
class WideCatInstrument:
    program: NativeCatProgram
    logical_product: PauliProduct
    physical_product: PauliProduct
    namespace: str
    cat_roles: tuple[str, ...]
    verifier_role: str
    verification_ids: tuple[str, ...]
    cat_measurement_ids: tuple[str, ...]
    coupling_entry_id: str
    observable_id: str

    def to_dict(self):
        return {'schema': 'wide-native-cat-reference/1', 'program': self.program.to_dict(),
                'logical_product': self.logical_product.to_dict(),
                'physical_product': self.physical_product.to_dict(),
                'cat_roles': list(self.cat_roles), 'verifier_role': self.verifier_role,
                'verification_ids': list(self.verification_ids),
                'cat_measurement_ids': list(self.cat_measurement_ids),
                'coupling_entry_id': self.coupling_entry_id, 'observable_id': self.observable_id,
                'physical_executed': False, 'runtime_abort_implemented': False,
                'fault_tolerance_audited': False}


def build_wide_cat(logical_product, *, namespace='widecat', cat_roles=None, verifier_role=None):
    """Emit fresh cat-only native gates, with explicit 2-pass ZZ verification.

    All nine data/eight syndrome roles per participating patch are declared;
    no data is reset and no syndrome bank is silently simulated. The generator
    composes its actual canonical banks outside this fragment.
    """
    if not isinstance(logical_product, PauliProduct) or not logical_product.factors:
        raise ValueError('A nonidentity signed logical Pauli product is required')
    if type(namespace) is not str or not namespace.strip():
        raise ValueError('A nonempty namespace is required')
    physical = physical_logical_product(logical_product)
    n = len(physical.factors)
    if not 1 <= n <= MAX_CAT_LENGTH:
        raise ValueError('Native wide cat requires 1 to 63 physical factors')
    cats = tuple(cat_roles) if cat_roles is not None else tuple(f'{namespace}.cat{i}' for i in range(n))
    verifier = verifier_role if verifier_role is not None else namespace + '.verifier'
    data_roles = tuple(r for patch, _ in logical_product.factors for r in patch_roles(patch))
    resources = (*cats, verifier)
    if (len(cats) != n or len(set(resources)) != n + 1 or
            any(type(r) is not str or not r.strip() for r in resources) or
            set(resources) & {r.id for r in data_roles}):
        raise ValueError('Distinct fresh cat/verifier roles must match the physical product')
    gates, records, detectors, verification, readout = [], [], [], [], []
    frontier = ()
    def emit(key, kind, targets, phase):
        nonlocal frontier
        semantic = namespace + '.' + key
        gid = semantic + '__g000'
        gates.append(PhysicalGate(gid, kind, tuple(targets), depends_on=frontier))
        if kind == 'MEASURE':
            records.append(MeasurementBinding(semantic, gid, 0, phase))
        frontier = (gid,)
        return gid
    def cx(key, c, d, phase):
        emit(key + '.h', 'H', (d,), phase)
        emit(key + '.cz', 'CZ', (c, d), phase)
        emit(key + '.restore', 'H', (d,), phase)
    for i, role in enumerate(resources):
        emit(f'prepare.reset{i}', 'RESET', (role,), 'cat_prepare')
    emit('prepare.h', 'H', (cats[0],), 'cat_prepare')
    for i in range(n - 1):
        cx(f'prepare.cx{i}', cats[i], cats[i + 1], 'cat_prepare')
    for repeat in range(2):
        for i in range(n - 1):
            key = f'verify.r{repeat + 1}.link{i}'
            emit(key + '.reset', 'RESET', (verifier,), 'cat_verification')
            cx(key + '.left', cats[i], verifier, 'cat_verification')
            cx(key + '.right', cats[i + 1], verifier, 'cat_verification')
            gid = emit(key + '.measure', 'MEASURE', (verifier,), 'cat_verification')
            verification.append(gid)
            detectors.append(Detector(namespace + '.' + key + '.zero',
                                      BitExpr((namespace + '.' + key + '.measure',)), 'cat_verification'))
            emit(key + '.release', 'RESET', (verifier,), 'cat_verification')
    coupling_entry = None
    for i, (data, basis) in enumerate(physical.factors):
        start = len(gates)
        if basis in ('Z', 'Y'):
            emit(f'couple{i}.z', 'CZ', (cats[i], data), 'data_coupling')
        if basis in ('X', 'Y'):
            cx(f'couple{i}.x', cats[i], data, 'data_coupling')
        if basis == 'Y':
            # Actual order CZ -> CX -> S_control gives CY, with its i phase.
            emit(f'couple{i}.s.t0', 'T', (cats[i],), 'data_coupling')
            emit(f'couple{i}.s.t1', 'T', (cats[i],), 'data_coupling')
        coupling_entry = coupling_entry or gates[start].id
    for i, cat in enumerate(cats):
        emit(f'readout.cat{i}.h', 'H', (cat,), 'cat_readout')
        readout.append(emit(f'readout.cat{i}.measure', 'MEASURE', (cat,), 'cat_readout'))
        emit(f'readout.cat{i}.reset', 'RESET', (cat,), 'cat_release')
    oid = namespace + '.logical_product'
    semantic_readout = tuple(g[:-6] for g in readout)
    obs = Observable(oid, BitExpr(semantic_readout, int(physical.sign == -1)), 'signed encoded cat parity')
    program = NativeCatProgram((*data_roles, *(Role(r, 'parity_ancilla') for r in resources)),
                               tuple(gates), tuple(records), tuple(detectors), (obs,), namespace)
    return WideCatInstrument(program, logical_product, physical, namespace, cats, verifier,
                             tuple(verification), tuple(readout), coupling_entry, oid)


def _digest(item):
    raw = json.dumps(item.to_dict(), sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def _local_matrix(gates, wires):
    """Contract actual local H/CZ/T matrices in declared chronological order."""
    gates = tuple(gates)
    for g in gates:
        if g.condition or g.parameters or g.readout_flip:
            raise ValueError('Unconditional exact native unitary fragment required')
    signature = tuple((g.gate_type, tuple(wires.index(q) for q in g.qubit_ids)) for g in gates)
    return _local_matrix_signature(signature, len(wires))


@lru_cache(maxsize=64)
def _local_matrix_signature(signature, n):
    result = np.eye(1 << n, dtype=complex)
    for kind, positions in signature:
        if kind == 'CZ':
            a, b = positions
            indices = np.arange(1 << n)
            phase = 1 - 2 * (((indices >> (n - 1 - a)) & (indices >> (n - 1 - b))) & 1)
            result = phase[:, None] * result
        else:
            if kind not in ('H', 'T') or len(positions) != 1:
                raise ValueError('Unrecognized local unitary')
            q = positions[0]
            local = _H if kind == 'H' else np.diag([1, np.exp(1j * np.pi / 4)])
            full = np.array([[1]], dtype=complex)
            for i in range(n):
                full = np.kron(full, local if i == q else _I)
            result = full @ result
    return result


def _apply_word(word, vector, wires):
    """Actual physical Pauli action, retaining its complex Y phase."""
    values = np.asarray(vector, dtype=complex)
    indices = np.arange(len(values))
    flip, phase = 0, np.full(len(values), word.sign, dtype=complex)
    for q, basis in word.factors:
        mask = 1 << (len(wires) - 1 - wires.index(q))
        ones = (indices & mask) != 0
        if basis in ('X', 'Y'):
            flip ^= mask
        if basis == 'Y':
            phase *= np.where(ones, -1j, 1j)
        elif basis == 'Z':
            phase *= np.where(ones, -1, 1)
    return (phase[:, None] * values)[indices ^ flip] if values.ndim == 2 else (phase * values)[indices ^ flip]


@lru_cache(maxsize=1)
def _audit_wide_cat_codespace():
    """Native encoder restriction plus all 256 signed-sector intertwining.

    The ten constraints are the eight stabilizers and both logical operators.
    For every syndrome, solve a physical Pauli E commuting with logical X/Z.
    Then E V is the signed-sector isometry with unchanged logical axes. This
    handles arbitrary external references by operator equality, not samples.
    """
    from .encoded_resource_reference import build_css_isometry, apply_native_unitaries
    patch = 'wide_audit'
    wires = tuple(f'{patch}.d{i}' for i in range(9))
    encoder = build_css_isometry(patch=patch, data_qubits=wires, namespace='widecodespace')
    v = []
    for bit in (0, 1):
        initial = np.zeros(512, dtype=complex)
        initial[bit << 8] = 1
        v.append(apply_native_unitaries(encoder.isometry_circuit, initial, wires))
    v = np.column_stack(v)
    checks = stabilizers(patch)
    logicals = tuple(physical_logical_product(PauliProduct(((patch, b),))) for b in 'XYZ')
    matrix_error = max(float(np.linalg.norm(_apply_word(p, v, wires) - v @ _P[b]))
                       for p, b in zip(logicals, 'XYZ'))
    sector_error = max(float(np.linalg.norm(_apply_word(p, v, wires) - v)) for p in checks)
    if max(matrix_error, sector_error, float(np.linalg.norm(v.conj().T @ v - _I))) > 2e-12:
        raise AssertionError('Actual native CSS encoder does not intertwine the canonical logical operators')
    constraints = (*checks, logicals[0], logicals[2])
    columns = tuple(PauliProduct(((wires[q], kind),)) for kind in ('X', 'Z') for q in range(9))
    rows = [sum((not col.commutes_with(p)) << j for j, col in enumerate(columns)) for p in constraints]
    # RREF includes both logical constraints; no syndrome correction silently
    # applies a logical Pauli. Solve all right sides and check original rows.
    reduced, transform, pivots = rows[:], [1 << i for i in range(10)], []
    rank = 0
    for col in range(18):
        pivot = next((i for i in range(rank, 10) if reduced[i] & (1 << col)), None)
        if pivot is None:
            continue
        reduced[rank], reduced[pivot] = reduced[pivot], reduced[rank]
        transform[rank], transform[pivot] = transform[pivot], transform[rank]
        for i in range(10):
            if i != rank and reduced[i] & (1 << col):
                reduced[i] ^= reduced[rank]
                transform[i] ^= transform[rank]
        pivots.append(col)
        rank += 1
        if rank == 10:
            break
    if rank != 10:
        raise AssertionError('Signed sector and logical-axis constraints are not independent')
    for syndrome in range(256):
        solution = sum(((transform[i] & syndrome).bit_count() % 2) << col for i, col in enumerate(pivots))
        if any(((row & solution).bit_count() % 2) != ((syndrome >> i) & 1) for i, row in enumerate(rows)):
            raise AssertionError('Physical signed-sector intertwiner failed original commutation constraints')
    return {'passed': True, 'native_css_encoder_gates': len(encoder.isometry_circuit.gates),
            'local_intertwining_error': matrix_error, 'positive_sector_error': sector_error,
            'signed_sectors_algebraically_checked': 256, 'syndrome_and_logical_constraint_rank': rank,
            'signed_sector_convention': 'E_s V; E_s commutes with both canonical logical X and Z',
            'arbitrary_external_entanglement_preserved_by_operator_identity': True,
            'physical_executed': False, 'fault_tolerance_audited': False}


def audit_wide_cat_codespace():
    """Return a copy; callers cannot mutate the cached mathematical proof."""
    return dict(_audit_wide_cat_codespace())


def certify_wide_cat(item):
    """Return an independent copy of an exactly keyed immutable proof result."""
    if not isinstance(item, WideCatInstrument):
        raise TypeError('A WideCatInstrument is required')
    # Frozen complete native object is the key, with full dataclass equality;
    # a digest/basis-only cache cannot qualify a modified program.
    return json.loads(_certify_wide_cat_json(item))


@lru_cache(maxsize=64)
def _certify_wide_cat_json(item):
    """Qualify the *complete* actual program and prove its full raw instrument.

    K_b = 2**(-(L+1)/2) [I + (-1)**m P_signed], with m the
    actual XOR of all X reports plus the physical representative sign. Every
    two-pass verifier measurement is deterministically 0 in the ideal model.
    """
    if not isinstance(item, WideCatInstrument):
        raise TypeError('A WideCatInstrument is required')
    expected = build_wide_cat(item.logical_product, namespace=item.namespace,
                              cat_roles=item.cat_roles, verifier_role=item.verifier_role)
    if item != expected:
        raise ValueError('Complete native cat/role/DAG/measurement/phase contract was altered')
    gates = item.program.operations
    ns = item.namespace
    by_prefix = lambda key: tuple(g for g in gates if g.id.startswith(ns + '.' + key))
    errors = []
    # Actual initial H fixes both equal GHZ arm coefficients. Every actual CX
    # maps |00> -> |00>, |10> -> |11>, so induction is exact for any L<=63.
    h = _local_matrix(by_prefix('prepare.h__'), (item.cat_roles[0],))
    errors.append(float(np.linalg.norm(h[:, 0] - np.ones(2) / math.sqrt(2))))
    cx = np.array([[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 0, 1], [0, 0, 1, 0]], dtype=complex)
    for i in range(len(item.cat_roles) - 1):
        matrix = _local_matrix(by_prefix(f'prepare.cx{i}.'), item.cat_roles[i:i + 2])
        errors.append(float(np.linalg.norm(matrix - cx)))
    # Contract each real 3-wire verification circuit with <0|_v and |0>_v.
    # K0 = projector onto equal neighbors, K1 = onto unequal neighbors.
    for repeat in range(2):
        for i in range(len(item.cat_roles) - 1):
            prefix = f'verify.r{repeat + 1}.link{i}.'
            matrix = _local_matrix(tuple(g for g in by_prefix(prefix) if g.gate_type in ('H', 'CZ')),
                                   (*item.cat_roles[i:i + 2], item.verifier_role))
            k0, k1 = matrix[::2, ::2], matrix[1::2, ::2]
            errors.extend((float(np.linalg.norm(k0 - np.diag([1, 0, 0, 1]))),
                           float(np.linalg.norm(k1 - np.diag([0, 1, 1, 0])))))
    for i, (data, basis) in enumerate(item.physical_product.factors):
        matrix = _local_matrix(by_prefix(f'couple{i}.'), (item.cat_roles[i], data))
        expected_matrix = np.zeros((4, 4), dtype=complex)
        expected_matrix[:2, :2], expected_matrix[2:, 2:] = _I, _P[basis]
        errors.append(float(np.linalg.norm(matrix - expected_matrix)))
    for i, cat in enumerate(item.cat_roles):
        matrix = _local_matrix(tuple(g for g in by_prefix(f'readout.cat{i}.') if g.gate_type == 'H'), (cat,))
        errors.append(float(np.linalg.norm(matrix - _H)))
    error = max(errors)
    if error > 2e-12:
        raise AssertionError('Actual native cat local matrix violates the complete instrument proof')
    code = audit_wide_cat_codespace()
    report = {'schema': 'wide-cat-complete-instrument-certificate/1', 'passed': True,
            'native_program_sha256': _digest(item), 'cat_length': len(item.cat_roles),
            'native_gates': len(gates), 'local_matrices_checked': len(errors), 'local_matrix_error': error,
            'raw_branches_symbolically_covered': 1 << len(item.cat_roles),
            'all_raw_enumeration_used': False, 'native_ghz_induction_verified': True,
            'two_pass_actual_verifier_contractions_verified': True,
            'kraus_formula': '2^(-(L+1)/2) * (I + (-1)^m P_signed)',
            'm_formula': 'xor(actual_cat_X_reports) xor int(physical_product.sign == -1)',
            'complete_phase_sensitive_native_order_qualified': True,
            'resource_precondition': 'fresh |0> or previously measured and RESET to |0>; caller audits lifecycle',
            'complete_instrument_identity': 'sum_b K_b^dagger K_b = I; all prefix raw probabilities derived by summing suffixes',
            'canonical_codespace': dict(code), 'physical_executed': False,
            'runtime_abort_implemented': False, 'fault_tolerance_audited': False}
    return json.dumps(report, sort_keys=True, allow_nan=False)


@dataclass(frozen=True)
class WideCatSample:
    raw_results: tuple[tuple[str, int], ...]
    projection_records: tuple[dict, ...]
    semantic_branch: int
    logical_branch_probability: float
    raw_branch_probability: float
    log_raw_branch_probability: float
    certificate_sha256: str
    reset_results: tuple[tuple[str, int], ...]
    coefficient_phase: float = 1.0

    def to_dict(self):
        return asdict(self)


def sample_wide_cat(item, signed_expectation, rng, *, forced_raw=None, certificate=None):
    """Sample every actual native M sequentially using conditional Born rules.

    The expectation is that of the signed logical product on the caller's
    current normalized logical state (including retained resource/reference).
    Earlier cat reports are uniform; the final report uses the actual prefix
    XOR. Forcing is reference postselection only and never emitted controls.
    """
    if type(signed_expectation) not in (int, float) or not math.isfinite(signed_expectation) or not -1 - 2e-12 <= signed_expectation <= 1 + 2e-12:
        raise ValueError('A finite signed Born expectation in [-1,1] is required')
    expectation = max(-1.0, min(1.0, float(signed_expectation)))
    if not hasattr(rng, 'random'):
        raise TypeError('An explicit RNG with random() is required')
    if certificate is None:
        certificate = certify_wide_cat(item)
    elif certificate != certify_wide_cat(item):
        raise ValueError('Certificate differs from the actual complete native program')
    forced = {} if forced_raw is None else dict(forced_raw)
    actual_ids = set((*item.verification_ids, *item.cat_measurement_ids))
    if not set(forced) <= actual_ids or any(type(b) is not int or b not in (0, 1) for b in forced.values()):
        raise ValueError('Forced bits require actual native MEASURE IDs and integer bits')
    raw, resets, records, parity, logp, known_z = [], [], [], 0, 0.0, {}
    cat_index = {gid: i for i, gid in enumerate(item.cat_measurement_ids)}
    for gate in item.program.operations:
        if gate.gate_type == 'RESET':
            target = gate.qubit_ids[0]
            # Initial resources are declared freshly |0> or previously
            # measured-and-reset. During this exact fragment every subsequent
            # reset follows the actual report on its own target.
            bit = known_z.get(target, 0)
            resets.append((gate.id, bit))
            records.append({'native_gate_id': gate.id, 'target': target, 'stage': 'cat_reset',
                            'operation_kind': 'RESET', 'projected_bit': bit,
                            'probability_zero_given_prefix': float(bit == 0),
                            'selected_probability_given_prefix': 1.0, 'reset_output_bit': 0,
                            'reference_postselected': False})
            known_z[target] = 0
            continue
        if gate.gate_type != 'MEASURE':
            continue
        if gate.id in item.verification_ids:
            p0, stage = 1.0, 'cat_verification'
        else:
            i = cat_index[gate.id]
            p0 = .5 if i < len(item.cat_roles) - 1 else (1 + item.physical_product.sign * (-1) ** parity * expectation) / 2
            stage = 'cat_readout'
        bit = forced[gate.id] if gate.id in forced else int(float(rng.random()) >= p0)
        prob = p0 if bit == 0 else 1 - p0
        if prob <= 0:
            raise ValueError('Forced native branch has zero conditional Born probability')
        logp += math.log(prob)
        raw.append((gate.id, bit))
        records.append({'native_gate_id': gate.id, 'target': gate.qubit_ids[0], 'stage': stage,
                        'operation_kind': 'MEASURE',
                        'reported_bit': bit, 'projected_bit': bit, 'probability_zero_given_prefix': p0,
                        'selected_probability_given_prefix': prob, 'reference_postselected': gate.id in forced})
        known_z[gate.qubit_ids[0]] = bit
        if stage == 'cat_readout':
            parity ^= bit
    branch = parity ^ int(item.physical_product.sign == -1)
    return WideCatSample(tuple(raw), tuple(records), branch, (1 + (-1) ** branch * expectation) / 2,
                         math.exp(logp), logp, certificate['native_program_sha256'], tuple(resets))
