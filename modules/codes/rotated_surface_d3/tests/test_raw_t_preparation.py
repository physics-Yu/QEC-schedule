"""Joint noisy preparation events, seed isometry, and the quality boundary."""

from dataclasses import replace
from itertools import product
from math import pi, sqrt

import numpy as np
import pytest
from nadit_physical_compiler.atom_ir import AtomStep, Rotation

from modules.codes.rotated_surface_d3.components.circuits import source_qasm
from modules.codes.rotated_surface_d3.components.injection import (
    CORRECTIONS,
    RawTComponent,
)
from modules.codes.rotated_surface_d3.definition import CHECKS, ROLES
from modules.codes.rotated_surface_d3.probabilities.preparation import preparation_port
from modules.codes.rotated_surface_d3.probabilities.raw_t import raw_t_pauli_port
from modules.codes.rotated_surface_d3.probabilities.raw_t_preparation import (
    raw_t_preparation_port,
)
from modules.codes.rotated_surface_d3.tests.dense_quantum import (
    action_state,
    apply_pauli,
    data_branch,
    expectation,
    source_state,
)
from modules.codes.rotated_surface_d3.tests.injection_sequence_checks import (
    action_extraction,
    extract,
    source_extraction,
)
from modules.codes.rotated_surface_d3.tests.test_components import (  # fixture export
    device as device,  # noqa: PLC0414
)
from modules.codes.rotated_surface_d3.tests.test_event_raw_t import (  # fixture export
    sequence as sequence,  # noqa: PLC0414
)


def _bits(value):
    bulk = tuple((value >> i) & 1 for i in range(4))
    return (0, *bulk[:2], 0, 0, *bulk[2:], 0)


def _values(part, bits):
    return {
        m.result.measurement_id: bit
        for m, bit in zip(part.measurements, bits, strict=True)
    }


def _seed_data(seed):
    """Construct the fixed product envelope around an arbitrary central qubit."""
    plus, zero = np.array([1, 1]) / sqrt(2), np.array([1, 0])
    vector = np.ones(1, dtype=complex)
    for q in reversed(range(9)):
        local = seed if q == 4 else plus if q in (0, 1, 7, 8) else zero
        vector = np.kron(vector, local)
    return vector


def _canonical(vector, bits):
    """Apply only the fixed local relation, inside the quantum verification oracle."""
    for term in CORRECTIONS:
        if bits[ROLES[9:].index(term.measurement_port)]:
            vector = apply_pauli(
                vector, [(ROLES.index(role), basis) for role, basis in term.pauli_roles]
            )
    return vector


def test_noiseless_joint_matches_existing_ideal_and_preserves_fingerprint(
    sequence, device
):
    port = raw_t_preparation_port(sequence, device, noise_params={})
    ideal = preparation_port(
        "raw_t_postselection", extra_rounds=1, round_policy="explicit_control"
    )
    assert port.port_id == ideal.port_id
    assert port.protocol_id == ideal.protocol_id
    assert port.outcomes == ideal.outcomes
    assert port.branches == ideal.branches
    document = port.to_dict()
    model = document["model"]
    assert model["parameters"]["extra_rounds"] == 1
    assert model["parameters"]["preparation"] == "raw_t_postselection"
    evidence = model["evidence"]
    assert evidence["template_content_sha256"] == sequence.template_content_sha256
    assert evidence["class_bit_order"] == ["X1", "X2", "Z1", "Z2"]
    assert evidence["class_encoding"] == "little_endian"
    assert evidence["accepted_quality"]["status"] == "unsupported"
    assert evidence["joint_estimator_source_sha256"]
    assert (
        evidence["acceptance_port_sha256"]
        == raw_t_pauli_port(sequence, device, noise_params={}).content_sha256
    )


def test_readout_only_joint_matches_closed_form_and_counterexample(sequence, device):
    p = 0.1
    port = raw_t_preparation_port(sequence, device, noise_params={"readout_flip": p})
    pair_pass = (1 - p) ** 2 + p**2
    accepted = (1 - p) ** 8 * pair_pass**4
    assert len(port.outcomes) == 17
    for index in range(16):
        outcome = port.outcome(f"accepted_{index}")
        assert outcome.probability == pytest.approx(accepted / 16)
        assert dict(outcome.values) == {"accepted": True, "byproduct_class": index}
    rejected = port.outcome("rejected")
    assert rejected.probability == pytest.approx(1 - accepted)
    assert dict(rejected.values) == {"accepted": False, "byproduct_class": None}
    # Among accepted readout histories, a bulk pair can have two flipped bits.
    # The resulting wrong correction changes its code sector, not just logical Z.
    q = p**2 / pair_pass
    direct_wrong_mass = 0.0
    for double_flips in product((0, 1), repeat=4):
        weight = (1 - p) ** 8
        for flipped in double_flips:
            weight *= p**2 if flipped else (1 - p) ** 2
        if any(double_flips):
            direct_wrong_mass += weight
    assert direct_wrong_mass / accepted == pytest.approx(1 - (1 - q) ** 4)
    assert direct_wrong_mass > 0


def test_source_and_actual_se_are_sixteen_arbitrary_seed_isometries(sequence, device):
    second = sequence.parts[1]
    source = source_extraction(source_qasm("se_round"))
    actual = action_extraction(second, device)
    source_basis = [extract(source, _seed_data(np.eye(2)[i])) for i in range(2)]
    actual_basis = [extract(actual, _seed_data(np.eye(2)[i])) for i in range(2)]
    reference = None
    for value in range(16):
        bits = _bits(value)
        columns = []
        for outputs, identities in (
            (source_basis, dict(enumerate(bits))),
            (actual_basis, _values(second, bits)),
        ):
            unnormalized = []
            for output in outputs:
                data, probability = data_branch(output, identities)
                assert data is not None and probability == pytest.approx(1 / 16)
                unnormalized.append(sqrt(probability) * _canonical(data, bits))
            matrix = np.column_stack(unnormalized)
            np.testing.assert_allclose(
                matrix.conj().T @ matrix, np.eye(2) / 16, atol=1e-11
            )
            columns.append(matrix)
        phase = 16 * np.trace(columns[0].conj().T @ columns[1]) / 2
        assert abs(phase) == pytest.approx(1)
        np.testing.assert_allclose(columns[1], phase * columns[0], atol=1e-11)
        if reference is None:
            reference = columns[0]
        overlap = 16 * reference.conj().T @ columns[0]
        phase = np.trace(overlap) / 2
        np.testing.assert_allclose(overlap, phase * np.eye(2), atol=1e-11)
        assert abs(phase) == pytest.approx(1)
    assert reference is not None
    # Fix the logical axes/phases, not merely an arbitrary two-dimensional image.
    for seed, axis in (
        (np.array([1, 0]), "Z"),
        (np.array([1, 1]) / sqrt(2), "X"),
        (np.array([1, 1j]) / sqrt(2), "Y"),
    ):
        encoded = 4 * reference @ seed
        for basis, support in CHECKS:
            assert expectation(encoded, [(q, basis) for q in support]) == pytest.approx(
                1
            )
        logical = {
            "X": ((0, "X"), (3, "X"), (6, "X")),
            "Y": ((0, "Y"), (1, "Z"), (2, "Z"), (3, "X"), (6, "X")),
            "Z": ((0, "Z"), (1, "Z"), (2, "Z")),
        }[axis]
        assert expectation(encoded, logical) == pytest.approx(1)


@pytest.mark.parametrize("pauli", ("X", "Y", "Z"))
def test_real_t_seed_fault_keeps_joint_class_uniform_source_and_atoms(
    sequence, device, pauli
):
    first = sequence.parts[0]
    source = RawTComponent().source_qasm.replace(
        "\nt q[4];\n", f"\n{pauli.lower()} q[4];\nt q[4];\n"
    )
    steps = []
    inserted = 0
    for step in first.program.steps:
        if any(
            isinstance(a, Rotation)
            and a.atoms == (first.wire_atoms[4],)
            and a.axis == "Z"
            and abs(a.angle - pi / 4) < 1e-12
            for a in step.actions
        ):
            steps.append(
                AtomStep(
                    (
                        Rotation(
                            channel="local",
                            atoms=(first.wire_atoms[4],),
                            axis=pauli,
                            angle=pi,
                            duration_us=0,
                        ),
                    )
                )
            )
            inserted += 1
        steps.append(step)
    assert inserted == 1
    changed = replace(first, program=replace(first.program, steps=tuple(steps)))
    source_output, atom_output = source_state(source), action_state(changed, device)
    for value in range(16):
        bits = _bits(value)
        a, pa = data_branch(source_output, dict(enumerate(bits)))
        b, pb = data_branch(atom_output, _values(first, bits))
        assert a is not None and b is not None
        assert pa == pytest.approx(1 / 16)
        assert pb == pytest.approx(1 / 16)
        assert abs(np.vdot(a, b)) == pytest.approx(1)
        corrected = _canonical(b, bits)
        expected = (1 if pauli == "X" else -1) / sqrt(2)
        assert expectation(corrected, ((0, "X"), (3, "X"), (6, "X"))) == pytest.approx(
            expected
        )


def test_real_t_double_readout_flip_passes_and_miscanonicalizes_each_class(
    sequence, device
):
    first, second = sequence.parts
    output = action_state(first, device)
    se = action_extraction(second, device)
    probabilities = [0.0] * 16
    for value in range(16):
        truth = _bits(value)
        data, probability = data_branch(output, _values(first, truth))
        assert data is not None and probability == pytest.approx(1 / 16)
        final, p2 = data_branch(extract(se, data), _values(second, truth))
        assert final is not None and p2 == pytest.approx(1)
        recorded = list(truth)
        recorded[1] ^= 1
        first_values = _values(first, recorded)
        assert (
            sequence.with_results(
                first_values | _values(second, truth)
            ).acceptance_status
            == "rejected"
        )
        assert (
            sequence.with_results(
                first_values | _values(second, recorded)
            ).acceptance_status
            == "accepted"
        )
        probabilities[value ^ 1] += probability
        wrong = _canonical(final, recorded)
        assert expectation(wrong, [(q, "X") for q in CHECKS[1][1]]) == pytest.approx(-1)
    assert probabilities == pytest.approx([1 / 16] * 16)


def test_joint_rejects_incompatible_correction_relation(sequence, device):
    first = sequence.parts[0]
    relation = replace(
        first.correction_relations[0], pauli_atoms=((first.wire_atoms[4], "Z"),)
    )
    changed = replace(
        sequence,
        parts=(
            replace(
                first, correction_relations=(relation, *first.correction_relations[1:])
            ),
            *sequence.parts[1:],
        ),
    )
    with pytest.raises(ValueError, match="correction"):
        raw_t_preparation_port(changed, device, noise_params={})
