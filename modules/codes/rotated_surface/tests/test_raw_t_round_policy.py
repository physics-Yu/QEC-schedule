"""Normal postselection lasts d total rounds; short histories require a label."""

from dataclasses import replace
from math import sqrt

import pytest

from experiments.msd.standard import ExperimentSpec, build_world
from modules.codes._support.raw_t_round_policy import (
    RAW_T_PROTOCOL_VERSION,
    resolve_postselection_rounds,
)
from modules.codes.contracts.component import InvocationContext
from modules.codes.rotated_surface import DirectRawTPostselection as RawTPostselection
from modules.codes.rotated_surface import definition, get_component
from modules.codes.rotated_surface.raw_t_postselection import RawTPostselectionTemplate
from modules.codes.rotated_surface_d3.protocols.raw_t_postselection import (
    RawTPostselection as LegacyRawTPostselection,
)


@pytest.mark.parametrize("distance", (3, 5, 7, 9))
def test_default_and_explicit_matching_rounds_use_distance_policy(distance):
    assert resolve_postselection_rounds(distance) == distance - 1
    for protocol in (
        RawTPostselection(distance),
        RawTPostselection(distance, distance - 1),
    ):
        assert protocol.extra_rounds == distance - 1
        assert protocol.total_rounds == distance
        assert protocol.round_policy == "distance"
    assert RAW_T_PROTOCOL_VERSION == "2"
    if distance == 3:
        legacy = LegacyRawTPostselection()
        assert legacy.extra_rounds == 2 and legacy.total_rounds == 3
        assert legacy.round_policy == "distance"


@pytest.mark.parametrize("distance", (3, 5, 7))
def test_short_history_requires_explicit_control_policy(distance):
    with pytest.raises(ValueError, match="explicit_control"):
        RawTPostselection(distance, extra_rounds=1)
    protocol = RawTPostselection(
        distance, extra_rounds=1, round_policy="explicit_control"
    )
    assert protocol.extra_rounds == 1 and protocol.total_rounds == 2
    assert protocol.round_policy == "explicit_control"
    with pytest.raises(ValueError, match="explicit"):
        RawTPostselection(distance, round_policy="explicit_control")
    if distance == 3:
        with pytest.raises(ValueError, match="explicit_control"):
            LegacyRawTPostselection(extra_rounds=1)
        assert (
            LegacyRawTPostselection(
                extra_rounds=1, round_policy="explicit_control"
            ).total_rounds
            == 2
        )


@pytest.mark.parametrize(
    "distance,extra,policy",
    (
        (True, None, "distance"),
        (2, None, "distance"),
        (3, 0, "explicit_control"),
        (3, True, "explicit_control"),
        (3, 1.5, "explicit_control"),
        (3, 3, "distance"),
        (3, None, "unknown"),
    ),
)
def test_invalid_round_policy_inputs_rejected(distance, extra, policy):
    with pytest.raises(ValueError):
        resolve_postselection_rounds(distance, extra, round_policy=policy)


@pytest.fixture(scope="module", params=(3, 5, 7))
def normal_sequence(request):
    distance = request.param
    world = build_world(ExperimentSpec(distance=distance))
    patch = world.patch(0, "W1")
    protocol = RawTPostselection(distance)
    template = protocol.compile(
        world.device,
        home_sites=patch.home_sites,
        origin=patch.binding.origin,
        aod_id=patch.binding.aod_id,
    )
    sequence = template.bind(patch.binding).expand(
        InvocationContext(f"normal-d{distance}", 0, 1000, world.device, world.state)
    )
    return world, patch, protocol, template, sequence


def test_normal_physical_sequence_has_total_d_rounds_and_distinct_policy_cache(
    normal_sequence,
):
    world, patch, protocol, template, sequence = normal_sequence
    distance = world.spec.distance
    code = definition(distance)
    assert sequence.version == "2"
    assert template.distance == sequence.distance == distance
    assert (
        protocol.total_rounds
        == template.total_rounds
        == sequence.total_rounds
        == distance
    )
    assert template.extra_rounds == sequence.extra_rounds == distance - 1
    assert template.round_policy == sequence.round_policy == "distance"
    assert len(sequence.measurements) == distance * code.check_count
    assert (
        len(sequence.detectors)
        == len(get_component("raw_t_direct_control", distance).acceptance_ports)
        + (distance - 1) * code.check_count
    )
    assert [p.description.component_id for p in sequence.parts] == ["raw_t"] + [
        "se_round"
    ] * (distance - 1)
    assert sequence.exit_state == world.state
    assert all(
        p.template_content_sha256 == template.se_round.content_sha256
        for p in sequence.parts[1:]
    )
    assert (
        template.raw_t.source_qasm
        == get_component("raw_t_direct_control", distance).source_qasm
    )
    assert not sequence.ready_for_use(sequence.results_ready_us)
    assert all(m.value is None for m in sequence.measurements)
    # An equal physical round count deliberately labeled a control is a distinct cache.
    control = RawTPostselectionTemplate(
        template.raw_t, template.se_round, distance - 1, round_policy="explicit_control"
    )
    assert control.content_sha256 != template.content_sha256
    control_sequence = control.bind(patch.binding).expand(
        InvocationContext("control", 0, 1000, world.device, world.state)
    )
    with pytest.raises(ValueError, match="round policy"):
        protocol.acceptance_port(control_sequence, world.device, noise_params={})
    with pytest.raises(ValueError, match="explicit_control"):
        RawTPostselectionTemplate(template.raw_t, template.se_round, 1)
    with pytest.raises(ValueError, match="explicit_control"):
        replace(sequence, parts=sequence.parts[:2])


@pytest.mark.parametrize("distance", (3, 5))
def test_normal_probability_metadata_and_readout_reference_use_total_d(distance):
    world = build_world(ExperimentSpec(distance=distance))
    patch = world.patch(0, "R")
    protocol = RawTPostselection(distance)
    template = protocol.compile(
        world.device,
        home_sites=patch.home_sites,
        origin=patch.binding.origin,
        aod_id=patch.binding.aod_id,
    )
    sequence = template.bind(patch.binding).expand(
        InvocationContext(f"prob-d{distance}", 0, 2000, world.device, world.state)
    )
    p, shots = 0.01, 16384
    port = protocol.acceptance_port(
        sequence,
        world.device,
        noise_params={"readout_flip": p},
        shots=shots,
        seed=31,
        batch_size=2048,
    )
    data = port.to_dict()
    assert data["protocol_version"] == "2"
    for metadata in (data["model"]["parameters"], data["model"]["evidence"]):
        assert metadata["distance"] == distance
        assert metadata["extra_rounds"] == distance - 1
        assert metadata["total_rounds"] == distance
        assert metadata["round_policy"] == "distance"
    first = len(get_component("raw_t_direct_control", distance).acceptance_ports)
    random = definition(distance).check_count - first
    expected = (1 - p) ** (distance * first) * (
        (1 - p) ** distance + p**distance
    ) ** random
    actual = port.outcome("accepted").probability
    if distance == 3:
        assert actual == pytest.approx(expected, abs=1e-12)
    else:
        assert abs(actual - expected) < 6 * sqrt(expected * (1 - expected) / shots)
    assert data["model"]["evidence"]["accepted_output_quality"] == "not_estimated"
