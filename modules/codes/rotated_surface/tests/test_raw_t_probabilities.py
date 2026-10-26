"""Distance-aware raw-T acceptance from actual admitted operations and noise."""

from dataclasses import replace
from math import sqrt

import pytest

from experiments.msd.standard import ExperimentSpec, build_world
from modules.codes.contracts.component import InvocationContext
from modules.codes.rotated_surface import DirectRawTPostselection as RawTPostselection
from modules.codes.rotated_surface import definition, get_component
from modules.codes.rotated_surface.probabilities.raw_t import raw_t_acceptance_port
from modules.codes.rotated_surface_d3.probabilities.raw_t import raw_t_pauli_port


@pytest.fixture(scope="module", params=(3, 5, 7))
def prepared_sequence(request):
    distance = request.param
    world = build_world(ExperimentSpec(distance=distance))
    patch = world.patch(0, "R")
    # Preserve the historical R=2 analytic/legacy comparison as an explicit control.
    protocol = RawTPostselection(
        distance, extra_rounds=1, round_policy="explicit_control"
    )
    template = protocol.compile(
        world.device,
        home_sites=patch.home_sites,
        origin=patch.binding.origin,
        aod_id=patch.binding.aod_id,
    )
    sequence = template.bind(patch.binding).expand(
        InvocationContext(f"raw-d{distance}", 3500, 700, world.device, world.state)
    )
    return distance, world, protocol, sequence


def test_explicit_zero_noise_is_admitted_exact_model_not_implicit_ideal(
    prepared_sequence,
):
    distance, world, protocol, sequence = prepared_sequence
    port = protocol.acceptance_port(sequence, world.device, noise_params={})
    data = port.to_dict()
    assert port.port_id == f"rotated_surface_d{distance}.raw_t_postselection.acceptance"
    assert len(port.outcomes) == 2
    assert port.outcome("accepted").probability == 1
    assert data["model"]["kind"] == "pauli_exact"
    evidence = data["model"]["evidence"]
    assert evidence["detector_count"] == len(sequence.detectors)
    assert evidence["center_t_identity_checks"] == len(sequence.detectors)
    assert evidence["world_atom_count"] == 6 * definition(distance).atom_count
    assert evidence["participant_atom_ids"] == list(sequence.parts[0].wire_atoms)
    assert evidence["logical_error_rate_claimed"] is False
    assert evidence["structural_validation_bits_are_samples"] is False
    assert evidence["quality_horizon"]["quality_estimated"] is False
    assert evidence["activity_duration_us"] == pytest.approx(
        sequence.results_ready_us - 3500
    )
    assert evidence["source_qasm_sha256"] and evidence["noise_params_hash"]
    assert data["model"]["parameters"]["distance"] == distance
    assert data["protocol_version"] == "2"
    assert data["model"]["parameters"]["extra_rounds"] == 1
    assert data["model"]["parameters"]["total_rounds"] == 2
    assert data["model"]["parameters"]["round_policy"] == "explicit_control"
    with pytest.raises(TypeError, match="noise_params"):
        protocol.acceptance_port(sequence, world.device)


def test_readout_only_matches_actual_distance_detector_closed_form(prepared_sequence):
    distance, world, _, sequence = prepared_sequence
    p = 0.01
    initial = len(get_component("raw_t_direct_control", distance).acceptance_ports)
    checks = definition(distance).check_count
    exact = (1 - p) ** (2 * initial) * ((1 - p) ** 2 + p**2) ** (checks - initial)
    port = raw_t_acceptance_port(
        sequence,
        world.device,
        distance=distance,
        noise_params={"readout_flip": p},
        shots=32768,
        seed=19,
        batch_size=4096,
    )
    model = port.to_dict()["model"]
    probability = port.outcome("accepted").probability
    if distance == 3:
        assert model["kind"] == "pauli_exact"
        assert probability == pytest.approx(exact, abs=1e-12)
        legacy = raw_t_pauli_port(
            sequence, world.device, noise_params={"readout_flip": p}
        )
        assert probability == pytest.approx(
            legacy.outcome("accepted").probability, abs=1e-12
        )
    else:
        assert model["kind"] == "estimated"
        assert abs(probability - exact) < 6 * sqrt(exact * (1 - exact) / 32768)
        sampling = model["evidence"]["sampling"]
        assert sampling["shots"] == 32768 and sampling["seed"] == 19
        assert model["evidence"]["statistical_uncertainty"]["ci95"] is not None


def test_distance_round_count_and_acceptance_tampering_rejected(prepared_sequence):
    distance, world, protocol, sequence = prepared_sequence
    with pytest.raises(ValueError, match="distance|code"):
        raw_t_acceptance_port(
            sequence, world.device, distance=distance + 2, noise_params={}
        )
    with pytest.raises(ValueError, match="round"):
        RawTPostselection(
            distance, extra_rounds=2, round_policy="explicit_control"
        ).acceptance_port(sequence, world.device, noise_params={})
    first = sequence.parts[0]
    altered = replace(
        sequence,
        parts=(
            replace(first, acceptance_conditions=first.acceptance_conditions[1:]),
            *sequence.parts[1:],
        ),
    )
    with pytest.raises(ValueError, match="acceptance|detector"):
        protocol.acceptance_port(altered, world.device, noise_params={})
    changed = replace(
        sequence,
        parts=(
            replace(
                first,
                dag=replace(first.dag, global_phase=first.dag.global_phase + 0.01),
            ),
            *sequence.parts[1:],
        ),
    )
    with pytest.raises(ValueError, match="source"):
        protocol.acceptance_port(changed, world.device, noise_params={})


def test_observed_bits_and_nonpauli_models_are_rejected(prepared_sequence):
    _, world, protocol, sequence = prepared_sequence
    with pytest.raises(ValueError, match="unobserved"):
        protocol.acceptance_port(
            sequence.with_results({sequence.measurements[0].result.measurement_id: 0}),
            world.device,
            noise_params={},
        )
    with pytest.raises(ValueError, match="Pauli"):
        protocol.acceptance_port(
            sequence,
            world.device,
            noise_params={
                "single": {
                    "backend": "coherent_overrotation",
                    "parameters": {"fractional_angle_error": 0.01},
                }
            },
        )


@pytest.fixture(scope="module")
def position_sequences():
    world = build_world(ExperimentSpec(distance=3, pipelines=2))
    protocol = RawTPostselection(3, extra_rounds=1, round_policy="explicit_control")
    sequences = []
    for index in range(2):
        patch = world.patch(index, "W1")
        template = protocol.compile(
            world.device,
            home_sites=patch.home_sites,
            origin=patch.binding.origin,
            aod_id=patch.binding.aod_id,
        )
        sequences.append(
            template.bind(patch.binding).expand(
                InvocationContext(
                    f"position-{index}",
                    1e7,
                    1000 + 100 * index,
                    world.device,
                    world.state,
                )
            )
        )
    return world, protocol, tuple(sequences)


def test_actual_layout_and_explicit_noise_change_acceptance(position_sequences):
    world, protocol, sequences = position_sequences
    params = {
        "exposure": {"slm_t2_us": 20000, "aod_t2_us": 20000, "include_transport": True}
    }
    ports = [
        protocol.acceptance_port(sequence, world.device, noise_params=params)
        for sequence in sequences
    ]
    near, far = (port.to_dict()["model"]["evidence"] for port in ports)
    assert near["device_sha256"] == far["device_sha256"]
    assert near["source_qasm_sha256"] == far["source_qasm_sha256"]
    assert near["result_hash"] != far["result_hash"]
    assert near["activity_duration_us"] < far["activity_duration_us"]
    assert (
        ports[1].outcome("accepted").probability
        < ports[0].outcome("accepted").probability
    )
    changed_noise = protocol.acceptance_port(
        sequences[0], world.device, noise_params=params | {"readout_flip": 0.05}
    )
    assert (
        changed_noise.to_dict()["model"]["evidence"]["noise_params_hash"]
        != near["noise_params_hash"]
    )
    assert (
        changed_noise.outcome("accepted").probability
        < ports[0].outcome("accepted").probability
    )


def test_round_gap_and_delivery_tail_preserve_true_segment_boundary(position_sequences):
    world, protocol, sequences = position_sequences
    sequence = sequences[0]
    params = {
        "exposure": {"slm_t2_us": 20000, "aod_t2_us": 20000, "include_transport": True}
    }
    baseline = protocol.acceptance_port(sequence, world.device, noise_params=params)
    first, second = sequence.parts
    gap, tail = 400.0, 300.0
    delayed = replace(
        sequence,
        parts=(
            first,
            replace(
                second,
                start_us=second.start_us + gap,
                measurements=tuple(
                    replace(m, available_at_us=m.available_at_us + gap)
                    for m in second.measurements
                ),
            ),
        ),
    )
    later_results = replace(
        sequence,
        parts=(
            first,
            replace(
                second,
                measurements=tuple(
                    replace(m, available_at_us=m.available_at_us + tail)
                    for m in second.measurements
                ),
            ),
        ),
    )
    gap_port = protocol.acceptance_port(delayed, world.device, noise_params=params)
    tail_port = protocol.acceptance_port(
        later_results, world.device, noise_params=params
    )
    assert (
        gap_port.outcome("accepted").probability
        < baseline.outcome("accepted").probability
    )
    assert tail_port.outcome("accepted").probability == pytest.approx(
        baseline.outcome("accepted").probability
    )
    base_time = baseline.to_dict()["model"]["evidence"]["activity_duration_us"]
    assert gap_port.to_dict()["model"]["evidence"][
        "activity_duration_us"
    ] == pytest.approx(base_time + gap)
    # With zero feedback latency, some delivery delay overlaps return movement.
    # The horizon is max(action end, all result-ready times), not duration+delay.
    assert tail_port.to_dict()["model"]["evidence"][
        "activity_duration_us"
    ] == pytest.approx(later_results.results_ready_us - first.start_us)
    assert sequence.parts[0].start_us == 1e7
