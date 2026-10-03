"""Independent encoded/raw-branch oracles; no ENV or physical execution."""
from copy import deepcopy
from dataclasses import replace
from itertools import product
import math

import numpy as np
import pytest

from neutral_atom_env.circuit import PhysicalCircuit
from neutral_atom_env.domain.models import PhysicalGate
from neutral_atom_experiments.qec_pbc.adaptive_pbc import compile_adaptive_pbc
from neutral_atom_experiments.qec_pbc.conditional_clifford_frame import FrameController
from neutral_atom_experiments.qec_pbc.encoded_injection_reference import (
    _append_resource, _hash, audit_encoded_reference_result, commit_encoded_receipt, execute_encoded_injections)
from neutral_atom_experiments.qec_pbc.encoded_resource_reference import build_encoded_resource
from neutral_atom_experiments.qec_pbc.logical_pauli import LogicalGate, LogicalPauliProgram, PauliRotation
from neutral_atom_experiments.qec_pbc.mixed_pauli_cat import verify_mixed_pauli_instruments
from neutral_atom_experiments.qec_pbc.pauli import PauliProduct
from neutral_atom_experiments.qec_pbc.surface import logical_product, stabilizers


PAULI = {'X': np.array([[0, 1], [1, 0]], complex),
         'Y': np.array([[0, -1j], [1j, 0]], complex),
         'Z': np.diag([1, -1]).astype(complex)}
I = np.eye(2, dtype=complex)
INPUT = np.array([1, 2j, -0.5j, 0.3], complex)
INPUT /= np.linalg.norm(INPUT)


def program(*rotations, residual=(), phase=0, quality='ideal_reference'):
    source = LogicalPauliProgram(('A',), tuple(PauliRotation(PauliProduct((('A', basis),), sign), turns, i)
        for i, (basis, sign, turns) in enumerate(rotations)), tuple(residual), phase)
    return compile_adaptive_pbc(source, resource_quality=quality, resource_provenance='Actual native reference test')


def css_columns():
    """Independent binary-X orbit enumeration, with no vector Pauli helper."""
    masks = [sum(1 << (8 - int(w.split('.d')[1])) for w, b in s.factors)
             for s in stabilizers('R')[:4]]
    zero = np.zeros(512, complex)
    for choice in product((0, 1), repeat=4):
        index = 0
        for bit, mask in zip(choice, masks):
            if bit:
                index ^= mask
        zero[index] = 1 / 4
    logical_mask = sum(1 << (8 - int(w.split('.d')[1])) for w, b in logical_product(PauliProduct((('R', 'X'),))).factors)
    one = zero[np.arange(512) ^ logical_mask]
    return np.column_stack((zero, one))


def raw_bras():
    # <b|H^tensor9|x>, computed from bit-string parity, independently of the
    # native gate emulator, selected native outcomes and encoder network.
    fourier = np.array([[(-1) ** (b & x).bit_count() / math.sqrt(512) for x in range(512)] for b in range(512)])
    return fourier @ css_columns()


BRAS = raw_bras()
RAW_PARITY = np.array([((v >> 8) ^ (v >> 5) ^ (v >> 2)) & 1 for v in range(512)])


def instrument_matrix(q, sign, m, r):
    # Joint PZ projector then actual single-logical-X resource bra; NO correction.
    c, w = (-1) ** m, np.exp(1j * sign * math.pi / 4)
    return ((I + c * q) + (-1) ** r * w * (I - c * q)) / 4


def correction(q, sign, m, r):
    s = (I + q) / 2 + sign * 1j * (I - q) / 2
    return (q if r else I) @ (s if m else I)


def source_rotation(q, sign):
    return math.cos(math.pi / 8) * I - 1j * sign * math.sin(math.pi / 8) * q


def compare_raw_distribution(audit, state, q, sign, m):
    physical = np.asarray(audit['raw_x_distribution'])
    expected = []
    for bra in BRAS:
        k = (bra[0] * (I + (-1) ** m * q) + np.exp(1j * sign * math.pi / 4) * bra[1] * (I - (-1) ** m * q)) / (2 * math.sqrt(2))
        # Normalize by the actual joint probability 1/2, before raw readout.
        value = np.kron(k, I) @ state
        expected.append(2 * float(np.vdot(value, value).real))
    np.testing.assert_allclose(physical, expected, atol=3e-13, rtol=0)
    assert abs(sum(expected) - 1) < 2e-13
    np.testing.assert_allclose(audit['logical_x_group_probabilities'], [sum(physical[RAW_PARITY == b]) for b in (0, 1)], atol=3e-13)
    assert np.count_nonzero(physical > 1e-12) == 32
    # In this +X-stabilizer resource sector, all-nine X happens to be the same
    # logical representative modulo checks. This mathematical degeneracy is
    # not used to define r: receipt tests explicitly reject the wrong xor9
    # contract. General report strings distinguish them (e.g. bit-string 1).
    assert RAW_PARITY[1] != 1


@pytest.mark.parametrize('basis,word_sign,resource_sign', product(('X', 'Y', 'Z'), (-1, 1), (-1, 1)))
def test_all_four_native_encoded_branches_preserve_complex_reference_and_raw512(basis, word_sign, resource_sign):
    p = program((basis, word_sign, resource_sign), phase=3)
    q = word_sign * PAULI[basis]
    target = np.exp(3j * math.pi / 8) * np.kron(source_rotation(q, resource_sign), I) @ INPUT
    for m, r in product((0, 1), repeat=2):
        actual = execute_encoded_injections(p, INPUT, reference_qubits=1, rounds=1, outcomes=((m, r),), seed=7)
        raw = np.kron(instrument_matrix(q, resource_sign, m, r), I) @ INPUT
        raw /= np.linalg.norm(raw)
        np.testing.assert_allclose(actual.logical_data, raw, atol=4e-12, rtol=0)
        phase = np.exp(1j * math.pi * actual.branch_global_phase_eighth_turns / 8)
        np.testing.assert_allclose(actual.realize(), phase * target, atol=4e-12, rtol=0)
        np.testing.assert_allclose(np.kron(correction(q, resource_sign, m, r), I) @ raw *
            np.exp(1j * math.pi * p.global_phase_eighth_turns / 8), phase * target, atol=4e-12, rtol=0)
        compare_raw_distribution(actual.boundary_audits[0]['resource_readout'], INPUT, q, resource_sign, m)
        assert actual.receipts[0]['m'] == m and actual.receipts[0]['r'] == r
        np.testing.assert_allclose([actual.receipts[0]['decoded_joint_probability'], actual.receipts[0]['decoded_resource_x_probability']], [0.5, 0.5], atol=4e-12)


def test_noncommuting_two_resources_all16branches_signed_input_and_true_reprepare():
    p = program(('Y', -1, 1), ('X', 1, -1), residual=(LogicalGate('H', ('A',)),), phase=5)
    h = np.array([[1, 1], [1, -1]], complex) / math.sqrt(2)
    target = np.exp(5j * math.pi / 8) * np.kron(h @ source_rotation(PAULI['X'], -1) @ source_rotation(-PAULI['Y'], 1), I) @ INPUT
    labels_seen = set()
    for bits in product((0, 1), repeat=4):
        pairs = (bits[:2], bits[2:])
        actual = execute_encoded_injections(p, INPUT, reference_qubits=1, rounds=1, outcomes=pairs,
            sector_flip=True, physical_resource_reuse=True, seed=7)
        state, frame = INPUT.copy(), I.copy()
        for index, (m, r) in enumerate(pairs):
            observable = -PAULI['Y'] if index == 0 else PAULI['X']
            sign = 1 if index == 0 else -1
            q = frame.conj().T @ observable @ frame
            compare_raw_distribution(actual.boundary_audits[index]['resource_readout'], state, q, sign, m)
            state = np.kron(instrument_matrix(q, sign, m, r), I) @ state
            state /= np.linalg.norm(state)
            frame = correction(observable, sign, m, r) @ frame
        np.testing.assert_allclose(actual.logical_data, state, atol=5e-12, rtol=0)
        np.testing.assert_allclose(actual.realize(), np.exp(1j * math.pi * actual.branch_global_phase_eighth_turns / 8) * target, atol=5e-12, rtol=0)
        assert [e['physical_patch'] for e in actual.resource_lifecycle] == ['R', 'R']
        assert actual.resource_lifecycle[1]['physical_patch_reprepared_for_reuse']
        ids = [g.id for g in actual.native_program.operations]
        assert len(ids) == len(set(ids))
        assert all(g.id.startswith('data.') for g in actual.native_program.operations if g.gate_type == 'RESET' and g.qubit_ids[0].startswith('A.d'))
        # Only initial syndrome auxiliary RESETs and subsequent real canonical
        # auxiliary releases target A; incoming unknown A.d0 is never reset.
        assert not any(g.gate_type == 'RESET' and g.qubit_ids == ('A.d0',) for g in actual.native_program.operations)
        assert any(bit for gid, bit in actual.raw_reports if gid.startswith('data.check.'))
        labels_seen.add(tuple(actual.qualified_joints[1].logical_product.factors))
    assert len(labels_seen) >= 2


@pytest.fixture(scope='module')
def one_result():
    return execute_encoded_injections(program(('Y', -1, -1)), INPUT, reference_qubits=1, rounds=1,
                                     outcomes=((1, 1),), seed=7)


def test_every_actual_native_projection_singleT_or_7T_prefix_and_physicalcircuit_export(one_result):
    actual = one_result
    gates = actual.native_program.operations
    projection_ids = [g.id for g in gates if g.gate_type in ('MEASURE', 'RESET')]
    assert [r['native_gate_id'] for r in actual.native_records] == projection_ids
    assert len(set(projection_ids)) == len(projection_ids)
    producer = [g for g in gates if g.id.startswith('consume.000.producer.')]
    prepared = build_encoded_resource(sign=-1, patch='R0', namespace='consume.000.producer')
    reverse = {q: role for role, q in prepared.bindings}
    assert [(g.id, g.gate_type, g.qubit_ids) for g in producer] == [
        (g.id, g.gate_type, tuple(reverse[q] for q in g.qubit_ids)) for g in prepared.circuit.gates]
    assert sum(g.gate_type == 'T' for g in producer) == 7
    compiled = actual.compile()
    assert isinstance(compiled.circuit, PhysicalCircuit)
    assert [g.id for g in compiled.circuit.gates] == [g.id for g in gates]
    report = actual.to_dict()
    assert report['native_gate_count'] == len(gates)
    assert report['active_dense_dimension'] == 1 << 19
    assert report['environment_committed_reports'] is False
    assert report['full_declared_register_dense_simulated'] is False
    assert report['complete_algorithm_encoded'] is False
    # The pre-existing Clifford adapter remains strict: 7 real producer Ts
    # are never silently erased or converted into a fabricated GateTask Z.
    with pytest.raises(ValueError, match='T|Clifford'):
        verify_mixed_pauli_instruments((actual.qualified_joints[0],), reference_roles=('ref.0',), seeds=(0,))


def receipt_replay(actual):
    controller = FrameController(actual.program)
    controller.begin(0)
    return controller, deepcopy(actual.receipts[0]), actual.native_program, dict(actual.raw_reports), actual.qualified_joints[0]


@pytest.mark.parametrize('corruption', ['unknown_raw', 'missing_raw', 'bool_raw', 'xor9', 'wrong_sign',
    'wrong_resource', 'wrong_semantic', 'premature', 'nan_probability', 'impossible_probability', 'bit_bool', 'stale_hash',
    'readout_h_z', 'missing_reset', 'dirty_incoming'])
def test_receipt_rejects_missing_unknown_parity_alias_order_and_dirty_native_before_frame_update(one_result, corruption):
    controller, receipt, native, raw, item = receipt_replay(one_result)
    if corruption == 'unknown_raw':
        raw['invented.computed.xor'] = 0
    elif corruption == 'missing_raw':
        raw.pop(receipt['all_resource_readout_gate_ids'][8])
    elif corruption == 'bool_raw':
        raw[receipt['joint_raw_gate_ids'][0]] = True
    elif corruption == 'xor9':
        receipt['resource_x_raw_gate_ids'] = receipt['all_resource_readout_gate_ids']
    elif corruption == 'wrong_sign':
        receipt['joint_sign_constant'] ^= 1
    elif corruption == 'wrong_resource':
        receipt['resource_wire'] = 'magic.fake'
    elif corruption == 'wrong_semantic':
        receipt['joint_semantic_id'] = 'unknown.measurement'
    elif corruption == 'premature':
        controller = FrameController(one_result.program)
    elif corruption == 'nan_probability':
        receipt['decoded_resource_x_probability'] = float('nan')
    elif corruption == 'impossible_probability':
        receipt['decoded_resource_x_probability'] = 0.75
    elif corruption == 'bit_bool':
        receipt['m'] = True
    elif corruption == 'stale_hash':
        receipt['native_circuit_sha256'] = '0' * 64
    elif corruption == 'readout_h_z':
        ops = tuple(replace(g, gate_type='Z') if g.id.endswith('resource_x.h0') else g for g in native.operations)
        native = replace(native, operations=ops)
        receipt['native_circuit_sha256'] = _hash(native.to_dict())
    elif corruption == 'missing_reset':
        native = replace(native, operations=native.operations[:-1])
        receipt['native_circuit_sha256'] = _hash(native.to_dict())
    else:
        raw['data.check.A.r1.X0'] ^= 1
    with pytest.raises((ValueError, TypeError)):
        commit_encoded_receipt(controller, receipt, native, raw, qualified_joint=item)
    assert not controller.measurement_records and not controller.frame.ledger


def test_genuine_receipt_commits_once_and_rejects_reuse_or_unqualified_joint(one_result):
    controller, receipt, native, raw, item = receipt_replay(one_result)
    with pytest.raises(TypeError):
        commit_encoded_receipt(controller, receipt, native, raw, qualified_joint=native)
    commit_encoded_receipt(controller, receipt, native, raw, qualified_joint=item)
    controller.require_complete()
    assert len(controller.frame.ledger) == 1
    assert [r['outcome'] for r in controller.measurement_records] == [1, 1]
    with pytest.raises(ValueError):
        commit_encoded_receipt(controller, receipt, native, raw, qualified_joint=item)


def test_reused_patch_requires_all9measured_and_all17released(one_result):
    native = one_result.native_program
    prepared = build_encoded_resource(sign=1, patch='R0', namespace='consume.next.producer')
    good, sectors = _append_resource(native, prepared, 'R0')
    assert len(good.roles) == len(native.roles)
    assert len(good.measurements) == len(native.measurements) + 8
    assert all('.next.producer.sector.' in key for expr in sectors.values() for key in expr.terms)
    # The last MEASURE followed by a new RESET releases rather than silently
    # discards entanglement; a later Z or an unmeasured ninth data role fails.
    bad = replace(native, operations=(*native.operations, PhysicalGate('dirty.resource.z', 'Z', ('R0.d8',), depends_on=(native.operations[-1].id,))))
    with pytest.raises(ValueError, match='consumed|released'):
        _append_resource(bad, prepared, 'R0')
    ops = tuple(replace(g, gate_type='Z') if g.id.endswith('resource_x.measure8') else g for g in native.operations)
    bindings = tuple(m for m in native.measurements if not m.raw_gate_id.endswith('resource_x.measure8'))
    bad = replace(native, operations=ops, measurements=bindings)
    with pytest.raises(ValueError, match='consumed|released'):
        _append_resource(bad, prepared, 'R0')


def test_unsupported_quality_input_references_and_bad_native_bindings_are_explicit(one_result):
    with pytest.raises(ValueError, match='ideal-reference'):
        execute_encoded_injections(program(('Z', 1, 1), quality='unknown'), np.array([1, 0]))
    with pytest.raises(ValueError, match='reference'):
        execute_encoded_injections(program(('Z', 1, 1)), np.ones(8) / math.sqrt(8), reference_qubits=2)
    with pytest.raises(ValueError, match='Normalized'):
        execute_encoded_injections(program(('Z', 1, 1)), np.array([1, 1]))
    with pytest.raises(ValueError, match='integer'):
        execute_encoded_injections(program(('Z', 1, 1)), np.array([1, 0]), outcomes=((True, 0),))
    with pytest.raises(ValueError, match='distinct'):
        one_result.compile({r.id: 'Q000' for r in one_result.native_program.roles})


def test_genuine_born_sampling_three_rounds_fresh_resources_and_choi_input():
    initial = np.array([1, 0, 0, 1], complex) / math.sqrt(2)
    p = program(('Y', -1, 1), ('Z', 1, -1))
    actual = execute_encoded_injections(p, initial, reference_qubits=1, rounds=3, seed=11)
    target = np.kron(source_rotation(PAULI['Z'], -1) @ source_rotation(-PAULI['Y'], 1), I) @ initial
    np.testing.assert_allclose(actual.realize(), np.exp(1j * math.pi * actual.branch_global_phase_eighth_turns / 8) * target, atol=4e-12)
    assert not any(r['audit_only_forced_branch'] for r in actual.receipts)
    assert [r['physical_patch'] for r in actual.resource_lifecycle] == ['R0', 'R1']
    assert all(r['final_status'] == 'consumed' for r in actual.resource_lifecycle)
    assert len({m.result_id for m in actual.native_program.measurements}) == len(actual.native_program.measurements)


def test_portable_matrix_audit_rejects_a_different_input_and_keeps_branch_phase(one_result):
    audit = audit_encoded_reference_result(one_result, INPUT)
    assert audit['passed'] and audit['source_complex_amplitude_l2_error'] < 4e-12
    assert audit['actual_semantic_outcomes'] == [[1, 1]]
    assert audit['physical_executed'] is False
    other = INPUT.copy()
    other[1] *= -1
    with pytest.raises(AssertionError, match='independent source matrix'):
        audit_encoded_reference_result(one_result, other)


def test_no_external_reference_one_nativeT_and_unreset_logical_input():
    initial = np.array([1, 2j], complex) / math.sqrt(5)
    p = program(('Z', 1, 1))
    actual = execute_encoded_injections(p, initial, rounds=1, seed=0)
    target = source_rotation(PAULI['Z'], 1) @ initial
    np.testing.assert_allclose(actual.realize(), np.exp(1j * math.pi * actual.branch_global_phase_eighth_turns / 8) * target, atol=3e-12)
    producer = [g for g in actual.native_program.operations if g.id.startswith('consume.000.producer.')]
    assert sum(g.gate_type == 'T' for g in producer) == 1
    assert not any(g.gate_type == 'RESET' and g.qubit_ids == ('A.d0',) for g in actual.native_program.operations)
    assert len(actual.encoded_data) == 512 and len(actual.logical_data) == 2
    assert actual.to_dict()['active_dense_dimension'] == 1 << 18
    assert audit_encoded_reference_result(actual, initial)['passed']


def test_receipt_probability_tolerance_boundary_both_fields_is_atomic(one_result):
    for field, sign in product(('decoded_joint_probability', 'decoded_resource_x_probability'), (-1, 1)):
        controller, receipt, native, raw, item = receipt_replay(one_result)
        # Closest representable number inside the documented absolute budget.
        receipt[field] = math.nextafter(0.5 + sign * 2e-11, 0.5)
        commit_encoded_receipt(controller, receipt, native, raw, qualified_joint=item)
        controller.require_complete()
        assert len(controller.frame.ledger) == 1
        controller, receipt, native, raw, item = receipt_replay(one_result)
        receipt[field] = 0.5 + sign * 2.1e-11
        with pytest.raises(ValueError, match='1/2'):
            commit_encoded_receipt(controller, receipt, native, raw, qualified_joint=item)
        assert not controller.measurement_records and not controller.frame.ledger
        assert not controller.resource_lifecycle and controller._next == 0
