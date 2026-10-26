"""Exact finite raw-T acceptance tables and explicit noise-model boundaries."""

from dataclasses import replace

import pytest
from nadit_physical_compiler.atom_ir import AtomStep, Rotation
from nadit_physical_compiler.device import Position

from modules.codes.contracts.component import ComponentBinding, InvocationContext
from modules.codes.rotated_surface_d3.definition import REFERENCE_HOMES
from modules.codes.rotated_surface_d3.probabilities.raw_t import (
    raw_t_ideal_port,
    raw_t_pauli_port,
)
from modules.codes.rotated_surface_d3.probabilities.raw_t_detectors import (
    xor_distribution,
)
from modules.codes.rotated_surface_d3.protocols.raw_t_postselection import (
    RawTPostselection,
)
from modules.codes.rotated_surface_d3.tests.test_components import (  # fixture export
    device as device,  # noqa: PLC0414
)
from modules.codes.rotated_surface_d3.tests.test_components import world


@pytest.fixture(scope="module")
def sequence(device):
    template = RawTPostselection(
        extra_rounds=1, round_policy="explicit_control"
    ).compile(
        device, home_sites=REFERENCE_HOMES, origin=Position(0, 0), aod_id="transport"
    )
    return template.bind(
        ComponentBinding("offline-patch", Position(0, 0), tuple(range(17)), "transport")
    ).expand(InvocationContext("offline-probability", 2100, 900, device, world(device)))


def test_ideal_table_and_explicit_retry_semantics():
    port = raw_t_ideal_port()
    assert port.port_id == "rotated_surface_d3.raw_t_postselection.acceptance"
    assert port.outcome("accepted").probability == 1
    assert port.outcome("rejected").probability == 0
    assert port.branch("deliver").transition == "deliver"
    assert port.branch("retry").transition == "retry"
    assert port.to_dict()["model"]["kind"] == "ideal_exact"
    assert (
        raw_t_ideal_port(1, round_policy="explicit_control").content_sha256
        != port.content_sha256
    )
    for invalid in (0, -1, True, 1.5):
        with pytest.raises(ValueError):
            raw_t_ideal_port(invalid)


def test_exact_xor_preserves_exclusive_branches_and_cancellations():
    assert xor_distribution(1, (((1, 0.1),), ((1, 0.2),))) == pytest.approx(
        (0.74, 0.26)
    )
    assert xor_distribution(1, (((1, 0.2), (1, 0.3)),)) == pytest.approx((0.5, 0.5))
    assert xor_distribution(2, (((1, 0.5), (2, 0.5)),)) == pytest.approx(
        (0, 0.5, 0.5, 0)
    )
    assert xor_distribution(1, (((1, 1.0),), ((1, 1.0),))) == pytest.approx((1, 0))
    assert xor_distribution(1, (((0, 0.9),),)) == pytest.approx((1, 0))


@pytest.mark.parametrize(
    "channels",
    (
        (((2, 0.1),),),
        (((1, -0.1),),),
        (((1, float("nan")),),),
        (((1, 0.6), (1, 0.6)),),
        (((True, 0.2),),),
        (((1, True),),),
    ),
)
def test_invalid_channel_inputs_rejected(channels):
    with pytest.raises(ValueError):
        xor_distribution(1, channels)


def test_detector_memory_bound():
    with pytest.raises(ValueError):
        xor_distribution(21, ())


def test_actual_raw_t_noiseless_proof_and_joined_timeline(sequence, device):
    port = raw_t_pauli_port(sequence, device, noise_params={})
    assert port.outcome("accepted").probability == pytest.approx(1)
    evidence = port.to_dict()["model"]["evidence"]
    assert evidence["detector_count"] == 12
    assert evidence["center_t_identity_checks"] == 12
    assert evidence["non_clifford_seed_gates"] == 1
    assert evidence["activity_duration_us"] == pytest.approx(
        sequence.results_ready_us - sequence.parts[0].start_us
    )
    assert evidence["scope"] == "pauli_readout_only"
    assert evidence["terminal_boundary"] == "open_after_last_se"
    assert evidence["result_hash"] and evidence["noise_params_hash"]
    assert evidence["sampling"] is None


def test_readout_only_probability_matches_independent_closed_form(sequence, device):
    p = 0.1
    port = raw_t_pauli_port(sequence, device, noise_params={"readout_flip": p})
    expected = (1 - p) ** 8 * ((1 - p) ** 2 + p**2) ** 4
    assert port.outcome("accepted").probability == pytest.approx(expected, abs=1e-12)
    assert port.outcome("rejected").probability == pytest.approx(
        1 - expected, abs=1e-12
    )


def test_loss_remains_separate_from_detector_acceptance(sequence, device):
    port = raw_t_pauli_port(
        sequence, device, noise_params={"transport": {"load_loss": 0.1}}
    )
    evidence = port.to_dict()["model"]["evidence"]
    assert port.outcome("accepted").probability == 1
    assert evidence["physical_loss"]["all_atoms_survive_probability"] < 1
    assert "physical_atom_loss" in evidence["excluded_effects"]


def test_nonpauli_native_models_are_not_silently_twirled(sequence, device):
    with pytest.raises(ValueError, match="Pauli"):
        raw_t_pauli_port(
            sequence,
            device,
            noise_params={
                "single": {
                    "backend": "coherent_overrotation",
                    "parameters": {"fractional_angle_error": 0.01},
                }
            },
        )


def test_tampered_real_t_action_fails_semantic_admission(sequence, device):
    first = sequence.parts[0]
    changed = False
    steps = []
    for step in first.program.steps:
        actions = []
        for action in step.actions:
            if isinstance(action, Rotation) and action.axis == "Z" and not changed:
                action = replace(action, angle=action.angle + 0.01)
                changed = True
            actions.append(action)
        steps.append(replace(step, actions=tuple(actions)))
    assert changed
    altered = replace(
        sequence,
        parts=(
            replace(first, program=replace(first.program, steps=tuple(steps))),
            *sequence.parts[1:],
        ),
    )
    with pytest.raises(ValueError):
        raw_t_pauli_port(altered, device, noise_params={})


@pytest.mark.parametrize("location", ("seed", "first_cz", "cz_cancel"))
def test_actual_fault_signature_agrees_with_true_t_dense_branches(
    location, sequence, device
):
    from itertools import product
    from math import pi

    from nadit_physical_compiler.cost import prepare
    from nadit_physical_compiler.cost.noise.report import PAULI_2_ORDER

    from modules.codes.rotated_surface_d3.definition import CHECKS
    from modules.codes.rotated_surface_d3.probabilities.raw_t import _joint_document
    from modules.codes.rotated_surface_d3.probabilities.raw_t_detectors import (
        detector_fault_channels,
    )
    from modules.codes.rotated_surface_d3.tests.dense_quantum import (
        action_state,
        data_branch,
        expectation,
    )
    from modules.codes.rotated_surface_d3.tests.injection_sequence_checks import (
        action_extraction,
        extract,
    )

    first, second = sequence.parts
    activity = prepare(_joint_document(sequence, device))
    if location == "seed":
        event_id, event = next(
            (index, event)
            for index, event in enumerate(activity.events)
            if event.kind == "Rotation"
            and event.parameters.get("axis") == "Z"
            and event.atoms == (first.wire_atoms[4],)
            and abs(event.parameters["angle"] - pi / 4) < 1e-12
        )
        assert event.atoms == (first.wire_atoms[4],)
        assert event.parameters["angle"] == pytest.approx(pi / 4)
        faults_to_insert = [("before", event.atoms, "X")]
    else:
        event_id, event = next(
            (index, event)
            for index, event in enumerate(activity.events)
            if event.kind == "CZPulse"
        )
        faults_to_insert = (
            [("before", event.pairs[0], "XI"), ("after", event.pairs[0], "XZ")]
            if location == "cz_cancel"
            else [("before", event.pairs[0], "YX")]
        )
    channels = []
    for placement, atoms, label in faults_to_insert:
        probabilities = [0.0] * (3 if len(atoms) == 1 else 15)
        labels = ["X", "Y", "Z"] if len(atoms) == 1 else PAULI_2_ORDER
        probabilities[labels.index(label)] = 1.0
        channels.append(
            {
                "instruction": f"PAULI_CHANNEL_{len(atoms)}",
                "atoms": list(atoms),
                "probabilities": probabilities,
                "placement": placement,
                "event_id": event_id,
            }
        )
    detector_ids = tuple(
        tuple(m.result.measurement_id for m in d.measurements)
        for d in sequence.detectors
    )
    signatures, proof = detector_fault_channels(
        activity, channels, detector_ids, wire_atoms=first.wire_atoms
    )
    expected_mask = 0
    for channel_signature in signatures:
        expected_mask ^= next(
            mask for mask, probability in channel_signature if probability == 1
        )
    if location == "cz_cancel":
        assert expected_mask == 0
    assert proof["center_t_identity_checks"] == 12
    before, after = [], []
    for placement, atoms, label in faults_to_insert:
        destination = before if placement == "before" else after
        destination.extend(
            Rotation(channel="local", atoms=(atom,), axis=axis, angle=pi, duration_us=0)
            for atom, axis in zip(atoms, label, strict=True)
            if axis != "I"
        )
    steps = []
    for index, step in enumerate(first.program.steps):
        if index == event.step_index and before:
            steps.append(AtomStep(tuple(before)))
        steps.append(step)
        if index == event.step_index and after:
            steps.append(AtomStep(tuple(after)))
    faulty_first = replace(first, program=replace(first.program, steps=tuple(steps)))
    dense = action_state(faulty_first, device)
    se = action_extraction(second, device)
    mass = 0.0
    for bits in product((0, 1), repeat=8):
        values = {
            m.result.measurement_id: bit
            for m, bit in zip(first.measurements, bits, strict=True)
        }
        data, probability = data_branch(dense, values)
        if data is None:
            continue
        mass += probability
        next_bits = []
        for basis, support in CHECKS:
            value = expectation(data, [(wire, basis) for wire in support])
            assert abs(value) == pytest.approx(1)
            next_bits.append(int(value < 0))
        after_values = {
            m.result.measurement_id: bit
            for m, bit in zip(second.measurements, next_bits, strict=True)
        }
        _, p_second = data_branch(extract(se, data), after_values)
        assert p_second == pytest.approx(1)
        observed = sequence.with_results(values | after_values)
        mask = sum(
            detector.value << index for index, detector in enumerate(observed.detectors)
        )
        assert mask == expected_mask
    assert mass == pytest.approx(1)


def test_random_first_bulk_result_is_not_admitted_as_deterministic_detector(
    sequence, device
):
    from nadit_physical_compiler.cost import prepare

    from modules.codes.rotated_surface_d3.probabilities.raw_t import _joint_document
    from modules.codes.rotated_surface_d3.probabilities.raw_t_detectors import (
        detector_fault_channels,
    )

    first = sequence.parts[0]
    activity = prepare(_joint_document(sequence, device))
    random_measurement = first.measurements[1].result.measurement_id
    with pytest.raises(ValueError, match="Detector"):
        detector_fault_channels(
            activity, [], ((random_measurement,),), wire_atoms=first.wire_atoms
        )


@pytest.mark.parametrize("invalid_location", ("unknown_event", "duplicate_readout"))
def test_every_noise_channel_must_be_consumed_once(invalid_location, sequence, device):
    from nadit_physical_compiler.cost import prepare

    from modules.codes.rotated_surface_d3.probabilities.raw_t import _joint_document
    from modules.codes.rotated_surface_d3.probabilities.raw_t_detectors import (
        detector_fault_channels,
    )

    activity = prepare(_joint_document(sequence, device))
    first = sequence.parts[0]
    if invalid_location == "unknown_event":
        channels = [
            {
                "instruction": "X_ERROR",
                "atoms": [first.wire_atoms[0]],
                "probabilities": [0.1],
                "placement": "before",
                "event_id": 999999,
            }
        ]
    else:
        record = first.measurements[0]
        channel = {
            "instruction": "M",
            "atoms": [record.atom_id],
            "probabilities": [0.1],
            "placement": "measurement_argument",
            "measurement_id": record.result.measurement_id,
        }
        channels = [channel, channel.copy()]
    detectors = tuple(
        tuple(m.result.measurement_id for m in d.measurements)
        for d in sequence.detectors
    )
    with pytest.raises(ValueError, match="exactly one timeline"):
        detector_fault_channels(
            activity, channels, detectors, wire_atoms=first.wire_atoms
        )
