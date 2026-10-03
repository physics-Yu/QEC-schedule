"""Independent dense instrument/frame matrices and classical dependency failures."""
from itertools import product

import numpy as np
import pytest

from neutral_atom_experiments.qec_pbc.adaptive_pbc import compile_adaptive_pbc, execute_reference
from neutral_atom_experiments.qec_pbc.conditional_clifford_frame import (
    CorrectionRecord, FrameController, SignedCliffordFrame, execute_deferred_reference,
    execute_terminal_z, framed_inventory)
from neutral_atom_experiments.qec_pbc.logical_pauli import LogicalGate, LogicalPauliProgram, PauliRotation
from neutral_atom_experiments.qec_pbc.pauli import PauliProduct


M = {'I': np.eye(2), 'X': np.array([[0, 1], [1, 0]]),
     'Y': np.array([[0, -1j], [1j, 0]]), 'Z': np.diag([1, -1]),
     'H': np.array([[1, 1], [1, -1]]) / np.sqrt(2),
     'S': np.diag([1, 1j]), 'Sdg': np.diag([1, -1j])}


def matrix(p, wires):
    result = np.array([[p.sign]], dtype=complex)
    factors = dict(p.factors)
    for wire in wires:
        result = np.kron(result, M[factors.get(wire, 'I')])
    return result


def correction_matrix(p, sign, m, r, wires):
    p = matrix(p, wires)
    ident = np.eye(len(p))
    s = (ident + p) / 2 + 1j * sign * (ident - p) / 2
    return np.linalg.matrix_power(p, r) @ np.linalg.matrix_power(s, m)


def gmatrix(gate, wires):
    if len(gate.wires) == 1:
        result = np.eye(1, dtype=complex)
        for w in wires:
            result = np.kron(result, M[gate.name] if w == gate.wires[0] else M['I'])
        return result
    result = np.zeros((1 << len(wires), 1 << len(wires)), dtype=complex)
    c, t = (len(wires) - 1 - wires.index(w) for w in gate.wires)
    for i in range(len(result)):
        target = i ^ (((i >> c) & 1) << t) if gate.name == 'CX' else i
        result[target, i] = -1 if gate.name == 'CZ' and (i >> c) & (i >> t) & 1 else 1
    return result


def source():
    wires = ('a', 'b')
    rotations = (PauliRotation(PauliProduct((('a', 'X'),)), 1, 0),
                 PauliRotation(PauliProduct((('a', 'Y'), ('b', 'Z')), -1), -1, 1),
                 PauliRotation(PauliProduct((('a', 'Z'), ('b', 'X'))), 1, 2))
    residual = (LogicalGate('H', ('b',)), LogicalGate('CX', ('b', 'a')),
                LogicalGate('Sdg', ('a',)), LogicalGate('CZ', ('a', 'b')))
    return LogicalPauliProgram(wires, rotations, residual, 7)


def source_unitary(src):
    result = np.eye(1 << len(src.wires), dtype=complex)
    for rotation in src.rotations:
        angle = np.pi * rotation.quarter_turns / 8
        result = (np.cos(angle) * np.eye(len(result)) - 1j * np.sin(angle) * matrix(rotation.observable, src.wires)) @ result
    for gate in src.residual_clifford:
        result = gmatrix(gate, src.wires) @ result
    return np.exp(1j * np.pi * src.global_phase_eighth_turns / 8) * result


PAULIS = (PauliProduct((('a', 'Y'),), -1), PauliProduct((('a', 'Y'), ('b', 'X'))),
          PauliProduct((('a', 'X'), ('b', 'Z')), -1), PauliProduct((('b', 'Z'),)),
          PauliProduct(()), PauliProduct((), -1))


@pytest.mark.parametrize('p', PAULIS)
@pytest.mark.parametrize('sign', (1, -1))
def test_all_signed_generator_pullbacks_against_independent_correction_matrix(p, sign):
    wires = ('b', 'a')
    all_paulis = [PauliProduct(tuple((w, b) for w, b in zip(wires, word) if b != 'I'), s)
                  for word in product('IXYZ', repeat=2) for s in (-1, 1)]
    for m, r in product((0, 1), repeat=2):
        entry = CorrectionRecord(0, p, sign, m, r, 'magic', 'joint', 'resource_x')
        frame = SignedCliffordFrame.identity(wires).corrected(entry)
        c = correction_matrix(p, sign, m, r, wires)
        for a in all_paulis:
            assert np.allclose(matrix(frame.pullback(a), wires), c.conj().T @ matrix(a, wires) @ c, atol=1e-12)
        # Ledger preserves the exact complex phase, even for signed identity.
        psi = np.array([1, 2j, 3 + 4j, -1j], dtype=complex)
        assert np.allclose(frame.realize(psi), c @ psi, atol=1e-12)


def test_three_noncommuting_injections_all_64_branches_on_entangled_reference():
    src = source()
    program = compile_adaptive_pbc(src, resource_quality='ideal_reference')
    rng = np.random.default_rng(914)
    psi = rng.normal(size=8) + 1j * rng.normal(size=8)
    psi /= np.linalg.norm(psi)
    expected = np.kron(source_unitary(src), M['I']) @ psi
    density = np.zeros((8, 8), dtype=complex)
    for bits in product((0, 1), repeat=6):
        outcomes = tuple(zip(bits[::2], bits[1::2]))
        actual = execute_deferred_reference(program, psi, reference_qubits=1, outcomes=outcomes)
        eager = execute_reference(program, psi, reference_qubits=1, outcomes=outcomes)
        # Independent instrument: conjugate by a dense accumulated F, project
        # data/reference/resource together, and never correct the live vector.
        f, raw = np.eye(4, dtype=complex), psi.copy()
        for index, (injection, (m, r)) in enumerate(zip(program.injections, outcomes)):
            p = matrix(injection.observable, src.wires)
            q = f.conj().T @ p @ f
            label = actual.measurement_records[2 * index]['observable']
            stored = PauliProduct(tuple(tuple(pair) for pair in label['factors'] if pair[0] in src.wires), label['sign'])
            assert np.allclose(matrix(stored, src.wires), q, atol=1e-12)
            resource = np.array([1, np.exp(1j * injection.quarter_turns * np.pi / 4)]) / np.sqrt(2)
            joined = np.kron(raw, resource)
            projected = (np.eye(16) + (-1) ** m * np.kron(np.kron(q, M['I']), M['Z'])) @ joined / 2
            contracted = np.kron(np.eye(8), np.array([[1, (-1) ** r]]) / np.sqrt(2)) @ projected
            raw = contracted / np.linalg.norm(contracted)
            f = correction_matrix(injection.observable, injection.quarter_turns, m, r, src.wires) @ f
        assert np.allclose(actual.unrealized_state, raw, atol=1e-12)
        assert np.allclose(actual.frame.realize(raw, reference_qubits=1), np.kron(f, M['I']) @ raw, atol=1e-12)
        assert np.allclose(actual.realize(), eager.state, atol=1e-12)
        branch_phase = np.exp(1j * np.pi * actual.branch_global_phase_eighth_turns / 8)
        assert np.allclose(actual.realize(), branch_phase * expected, atol=1e-12)
        assert abs(actual.log2_branch_probability + 6) < 1e-12
        density += np.outer(actual.realize(), actual.realize().conj()) / 64
        assert all(r['final_status'] == 'consumed' for r in actual.resource_lifecycle)
        assert len(actual.frame.ledger) == 3
    assert np.allclose(density, np.outer(expected, expected.conj()), atol=1e-12)


def test_all_24_images_keep_independent_binary_symplectic_form():
    wires = tuple(f'q{i}' for i in range(12))
    frame = SignedCliffordFrame.identity(wires)
    rng = np.random.default_rng(441)
    for step in range(30):
        word = rng.choice(list('IXYZ'), size=12)
        p = PauliProduct(tuple((w, b) for w, b in zip(wires, word) if b != 'I'), int(rng.choice([-1, 1])))
        frame = frame.corrected(CorrectionRecord(step, p, int(rng.choice([-1, 1])),
                    int(rng.integers(2)), int(rng.integers(2)), f'm{step}', f'j{step}', f'r{step}'))
        xz = np.array([[(dict(p.factors).get(w) in ('X', 'Y')) for w in wires] +
                       [(dict(p.factors).get(w) in ('Z', 'Y')) for w in wires]
                      for p in frame.generator_images], dtype=int)
        form = (xz[:, :12] @ xz[:, 12:].T + xz[:, 12:] @ xz[:, :12].T) % 2
        expected = np.zeros((24, 24), dtype=int)
        for i in range(12):
            expected[2 * i, 2 * i + 1] = expected[2 * i + 1, 2 * i] = 1
        assert np.array_equal(form, expected)
    assert max(len(p.factors) for p in frame.generator_images) > 1


def test_terminal_labels_and_retained_quantum_projection_include_residual_frame_and_phase():
    src = source()
    program = compile_adaptive_pbc(src, resource_quality='ideal_reference')
    rng = np.random.default_rng(21)
    psi = rng.normal(size=8) + 1j * rng.normal(size=8)
    psi /= np.linalg.norm(psi)
    result = execute_deferred_reference(program, psi, reference_qubits=1, outcomes=((1, 1), (1, 0), (1, 1)))
    f, residual = np.eye(4, dtype=complex), np.eye(4, dtype=complex)
    for r in result.frame.ledger:
        f = correction_matrix(r.observable, r.sign, r.joint_bit, r.resource_bit, src.wires) @ f
    for g in src.residual_clifford:
        residual = gmatrix(g, src.wires) @ residual
    labels = result.terminal_z_labels(('b', 'a'))
    for wire, label in zip(('b', 'a'), labels):
        z = matrix(PauliProduct(((wire, 'Z'),)), src.wires)
        assert np.allclose(matrix(label, src.wires), f.conj().T @ residual.conj().T @ z @ residual @ f, atol=1e-12)
    external = 0.371
    assert np.allclose(result.realize(external_global_phase_radians=external), np.exp(1j * external) * result.realize())
    for outputs in product((0, 1), repeat=2):
        measured, records = execute_terminal_z(result, ('b', 'a'), outcomes=outputs)
        expected = result.realize()
        probabilities = []
        for wire, bit in zip(('b', 'a'), outputs):
            p = np.kron(matrix(PauliProduct(((wire, 'Z'),)), src.wires), M['I'])
            expected = (expected + (-1) ** bit * p @ expected) / 2
            probability = np.linalg.norm(expected) ** 2
            probabilities.append(probability)
            expected /= np.sqrt(probability)
        assert np.allclose(measured.realize(), expected, atol=1e-12)
        assert [r['outcome'] for r in records] == list(outputs)
        assert np.allclose([r['conditional_probability'] for r in records], probabilities)
        assert records[0]['depends_on'] == [result.measurement_records[-1]['id']]
        assert records[1]['depends_on'] == [records[0]['id']]
    inventory = framed_inventory(result)
    assert inventory['generator_count'] == 4 and inventory['branch_specific']
    assert inventory['joint_measurements'] == 3
    assert result.to_dict()['physical_executed'] is False
    assert not result.unrealized_state.flags.writeable


@pytest.mark.parametrize('bad_bit', (None, True, -1, 2, '1'))
def test_unknown_bits_are_rejected_before_controller_or_frame_mutation(bad_bit):
    program = compile_adaptive_pbc(source(), resource_quality='ideal_reference')
    control = FrameController(program)
    control.begin(0)
    frame = control.frame
    with pytest.raises(ValueError, match='known integer bit'):
        control.commit_joint(program.injections[0].joint_measurement_id, bad_bit, 0.5)
    assert control.frame is frame and not control.measurement_records


def test_dependency_order_unknown_ids_repeat_results_and_consumed_resources_fail_closed():
    program = compile_adaptive_pbc(source(), resource_quality='ideal_reference')
    control = FrameController(program)
    first = program.injections[0]
    with pytest.raises(ValueError):
        control.begin(1)
    control.begin(0)
    with pytest.raises(ValueError, match='depends'):
        control.commit_resource_x(first.resource_measurement_id, 0, 0.5)
    with pytest.raises(ValueError, match='both committed'):
        control.update()
    with pytest.raises(ValueError, match='Unknown'):
        control.commit_joint('future.result', 0, 0.5)
    class String(str):
        pass
    with pytest.raises(ValueError, match='Unknown'):
        control.commit_joint(String(first.joint_measurement_id), 0, 0.5)
    control.commit_joint(first.joint_measurement_id, 1, 0.5)
    with pytest.raises(ValueError, match='repeated'):
        control.commit_joint(first.joint_measurement_id, 0, 0.5)
    with pytest.raises(ValueError):
        control.begin(1)
    control.commit_resource_x(first.resource_measurement_id, 1, 0.5)
    control.update()
    with pytest.raises(ValueError):
        control.update()
    with pytest.raises(ValueError):
        control.begin(0)
    with pytest.raises(ValueError):
        control.require_complete()
    with pytest.raises(ValueError, match='already been applied'):
        control.frame.corrected(control.frame.ledger[0])
    repeated = CorrectionRecord(1, first.observable, 1, 0, 0, first.resource.wire, 'new.joint', 'new.resource')
    with pytest.raises(ValueError, match='cannot be reused'):
        control.frame.corrected(repeated)


def test_invalid_full_generator_table_and_ideal_executor_contracts_rejected():
    with pytest.raises(ValueError, match='every signed'):
        SignedCliffordFrame(('a',), (PauliProduct((('a', 'X'),)),))
    with pytest.raises(ValueError, match='symplectic'):
        SignedCliffordFrame(('a',), (PauliProduct((('a', 'X'),)),) * 2)
    program = compile_adaptive_pbc(source())
    psi = np.array([1, 0, 0, 0], dtype=complex)
    with pytest.raises(ValueError, match='quality'):
        execute_deferred_reference(program, psi)
    with pytest.raises(ValueError, match='normalized'):
        execute_deferred_reference(program, 2 * psi, assume_ideal_resources=True)
    with pytest.raises(ValueError, match='per resource'):
        execute_deferred_reference(program, psi, outcomes=((0, 1),), assume_ideal_resources=True)
    result = execute_deferred_reference(program, psi, assume_ideal_resources=True)
    with pytest.raises(ValueError, match='unique'):
        result.terminal_z_labels(('a', 'a'))
    with pytest.raises(ValueError, match='finite'):
        result.realize(external_global_phase_radians=float('nan'))


def test_public_constructor_rejects_valid_symplectic_tableau_without_matching_exact_ledger():
    wires = ('a',)
    images = (PauliProduct((('a', 'X'),)), PauliProduct((('a', 'Z'),), -1))
    with pytest.raises(ValueError, match='empty correction ledger'):
        SignedCliffordFrame(wires, images)
    record = CorrectionRecord(0, PauliProduct((('a', 'Z'),)), 1, 1, 0, 'magic', 'joint', 'resource')
    frame = SignedCliffordFrame.identity(wires).corrected(record)
    copied = SignedCliffordFrame(wires, frame.generator_images, frame.ledger)
    assert copied == frame
    forged = tuple(PauliProduct(p.factors, -p.sign) for p in frame.generator_images)
    with pytest.raises(ValueError, match='exact correction ledger'):
        SignedCliffordFrame(wires, forged, frame.ledger)


def test_controller_report_copies_cannot_mutate_committed_projection_history():
    program = compile_adaptive_pbc(source(), resource_quality='ideal_reference')
    control = FrameController(program)
    control.begin(0)
    injection = program.injections[0]
    control.commit_joint(injection.joint_measurement_id, 1, 0.5)
    exported = control.measurement_records
    exported[0]['observable']['sign'] *= -1
    exported[0]['observable']['factors'].clear()
    assert control.measurement_records[0]['observable']['factors']
    assert control.measurement_records[0]['observable']['sign'] != exported[0]['observable']['sign']
    control.commit_resource_x(injection.resource_measurement_id, 0, 0.5)
    control.update()
    exported = control.resource_lifecycle
    exported[0]['statuses'].clear()
    assert control.resource_lifecycle[0]['statuses'][-1] == 'consumed'


def test_zero_resource_program_preserves_quantum_input_and_residual_and_global_phase():
    src = LogicalPauliProgram(('a',), (), (LogicalGate('H', ('a',)), LogicalGate('S', ('a',))), 3)
    program = compile_adaptive_pbc(src, resource_quality='ideal_reference')
    psi = np.array([1, 2j], dtype=complex) / np.sqrt(5)
    result = execute_deferred_reference(program, psi)
    assert np.array_equal(result.unrealized_state, psi)
    assert not result.frame.ledger and not result.measurement_records
    assert np.allclose(result.realize(), np.exp(3j * np.pi / 8) * M['S'] @ M['H'] @ psi)
    assert framed_inventory(result)['max_joint_weight'] == 0


def test_actual_terminal_shor_projectors_feed_failure_and_successful_order_gcd():
    from neutral_atom_experiments.qec_pbc.shor15 import apply_gates, build_shor15, postprocess_sample
    circuit = build_shor15()
    psi = np.zeros(4096, dtype=complex)
    psi[0] = 1
    # Gate-level circuit constructs the complete Fourier output; its period or
    # factors are never used to construct this input or either projector.
    psi = apply_gates(psi, circuit.gates).reshape((2,) * 12).transpose(tuple(reversed(range(12)))).reshape(-1)
    wires = tuple(f'phase{i}' for i in range(8)) + tuple(f'work{i}' for i in range(4))
    program = compile_adaptive_pbc(LogicalPauliProgram(wires, (), (), 0), resource_quality='ideal_reference')
    result = execute_deferred_reference(program, psi)
    for outcome, success in ((128, False), (192, True)):
        outputs = tuple((outcome >> i) & 1 for i in range(8))
        _, records = execute_terminal_z(result, wires[:8], outcomes=outputs)
        assert np.isclose(np.prod([r['conditional_probability'] for r in records]), 0.25)
        recovered_integer = sum(r['outcome'] << i for i, r in enumerate(records))
        classical = postprocess_sample(recovered_integer)
        assert classical['success'] is success
        if success:
            assert classical['order'] == 4 and classical['factors'] == [3, 5]
        else:
            assert classical['reason'] == 'order_not_recovered' and classical['factors'] is None


def test_split_eight_terminal_projections_keep_full_history_ids_dependencies_and_state():
    wires = tuple(f'phase{i}' for i in range(8))
    rotations = (PauliRotation(PauliProduct((('phase2', 'Y'),), -1), 1, 0),
                 PauliRotation(PauliProduct((('phase0', 'X'), ('phase2', 'Z'))), -1, 1),
                 PauliRotation(PauliProduct((('phase0', 'Y'), ('phase3', 'Y'))), 1, 2))
    residual = (LogicalGate('H', ('phase1',)), LogicalGate('Sdg', ('phase4',)),
                LogicalGate('CX', ('phase6', 'phase0')), LogicalGate('CZ', ('phase2', 'phase7')))
    program = compile_adaptive_pbc(LogicalPauliProgram(wires, rotations, residual, 5), resource_quality='ideal_reference')
    rng = np.random.default_rng(738)
    psi = rng.normal(size=512) + 1j * rng.normal(size=512)
    psi /= np.linalg.norm(psi)
    original = execute_deferred_reference(program, psi, reference_qubits=1, outcomes=((1, 0), (1, 1), (0, 1)))
    outcomes = (1, 0, 1, 1, 0, 0, 1, 0)
    single, single_records = execute_terminal_z(original, wires, outcomes=outcomes)
    first, first_records = execute_terminal_z(original, wires[:4], outcomes=outcomes[:4])
    split, last_records = execute_terminal_z(first, wires[4:], outcomes=outcomes[4:])
    assert np.allclose(split.unrealized_state, single.unrealized_state, atol=1e-12)
    assert np.allclose(split.realize(), single.realize(), atol=1e-12)
    assert split.terminal_measurement_records == first_records + last_records == single_records
    assert len({r['id'] for r in split.terminal_measurement_records}) == 8
    assert last_records[0]['depends_on'] == [first_records[-1]['id']]
    assert len(split.to_dict()['terminal_measurements']) == 8
    assert len(split.measurement_records) == 6 and framed_inventory(split)['joint_measurements'] == 3
    assert not original.terminal_measurement_records
