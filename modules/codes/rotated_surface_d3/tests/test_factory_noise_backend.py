"""Actual-source noisy preparation hooks must not invent downstream quality."""

import pytest

from modules.codes.contracts.component import InvocationContext
from modules.codes.rotated_surface_d3.protocols.factory_backend import (
    SurfaceFactoryBackend,
)
from modules.codes.rotated_surface_d3.protocols.factory_world import make_factory_world


@pytest.fixture(scope="module")
def setup():
    world = make_factory_world()
    backend = SurfaceFactoryBackend(world.device)
    bound = backend.bind_call("raw_t_postselection", (world.bindings["R"],))
    source = bound.expand(
        InvocationContext("raw-cost", 5600, 900, world.device, world.world_state)
    )
    return world, backend, bound, source


@pytest.fixture(scope="module")
def noisy(setup):
    _, backend, _, source = setup
    parameters = {"noise_model": "noise/v1", "noise_params": {"readout_flip": 0.1}}
    port = backend.preparation_event("raw_t_postselection", source, parameters)
    return parameters, port


def test_actual_source_joint_event_drives_real_correction_without_filling_bits(
    setup, noisy
):
    world, backend, _, source = setup
    _, port = noisy
    # Four deterministic checks require all three reports to be correct; each
    # of four random bulk checks permits either zero flips or three flips.
    acceptance = (0.9**12) * ((0.9**3 + 0.1**3) ** 4)
    assert port.to_dict()["model"]["kind"] == "pauli_exact"
    for outcome in port.outcomes:
        values = dict(outcome.values)
        assert outcome.probability == pytest.approx(
            acceptance / 16 if values["accepted"] else 1 - acceptance
        )
    event = port.outcome("accepted_5")
    decision = backend.correction_decision(
        source,
        event_id="event/raw-cost",
        probability_port=port,
        values=dict(event.values),
        available_at_us=source.results_ready_us,
    )
    corrected = backend.bind_canonicalization(
        "raw_t_postselection", source, decision, port
    ).expand(
        InvocationContext(
            "raw-cost/correct",
            source.results_ready_us,
            924,
            world.device,
            source.exit_state,
        )
    )
    assert corrected.expansion.program.steps
    assert len(corrected.expansion.exit_state.atoms) == 102
    assert all(m.value is None for m in source.measurements)


def test_noisy_accepted_quality_is_explicitly_unsupported(setup, noisy):
    _, backend, _, source = setup
    parameters, port = noisy
    quality = backend.preparation_quality_from_event(
        "raw_t_postselection",
        source,
        port,
        dict(port.outcome("accepted_5").values),
        parameters,
    )
    assert quality["status"] == "unsupported"
    assert quality["consumption_parameters"] is None
    assert quality["source_port_sha256"] == port.content_sha256
    assert quality["logical_success_probability"] is None
    assert quality["raw_rejection_is_input_error"] is False
    assert "syndrome" in " ".join(quality["reasons"])
    with pytest.raises(ValueError, match="accepted"):
        backend.preparation_quality_from_event(
            "raw_t_postselection",
            source,
            port,
            dict(port.outcome("rejected").values),
            parameters,
        )
    with pytest.raises(ValueError, match="accepted"):
        backend.preparation_quality_from_event(
            "raw_t_postselection",
            source,
            port,
            {"accepted": True, "byproduct_class": True},
            parameters,
        )


def test_quality_rejects_a_port_from_another_actual_source(setup, noisy):
    world, backend, bound, _source = setup
    parameters, port = noisy
    other = bound.expand(
        InvocationContext("another-raw", 9000, 2000, world.device, world.world_state)
    )
    with pytest.raises(ValueError, match="source|model"):
        backend.preparation_quality_from_event(
            "raw_t_postselection",
            other,
            port,
            dict(port.outcome("accepted_5").values),
            parameters,
        )


def test_existing_ideal_input_quality_parameter_remains_explicit(setup):
    _, backend, _, source = setup
    parameters = {"input_z_error": 0.01}
    port = backend.preparation_event("raw_t_postselection", source, parameters)
    assert (
        port.content_sha256
        == backend.resolve_event("preparation:raw_t_postselection").content_sha256
    )
    quality = backend.preparation_quality_from_event(
        "raw_t_postselection",
        source,
        port,
        dict(port.outcome("accepted_5").values),
        parameters,
    )
    assert quality["consumption_parameters"] == parameters
    assert quality["status"] == "assumed_reference"


@pytest.mark.parametrize(
    "parameters",
    [
        {"noise_model": "noise/v1"},
        {"noise_params": {}},
        {"noise_model": "other", "noise_params": {}},
        {"noise_model": "noise/v1", "noise_params": {}, "input_z_error": 0.1},
        {"noise_model": "noise/v1", "noise_params": []},
    ],
)
def test_unrecognized_or_mixed_models_do_not_fall_back_to_ideal(setup, parameters):
    _, backend, _, source = setup
    with pytest.raises(ValueError):
        backend.preparation_event("raw_t_postselection", source, parameters)


def test_noise_on_initialize_plus_is_not_implicitly_supported(setup):
    world, backend, _, _ = setup
    source = backend.bind_call("initialize_plus", (world.bindings["W1"],)).expand(
        InvocationContext("plus", 0, 0, world.device, world.world_state)
    )
    with pytest.raises(ValueError, match="raw_t_postselection"):
        backend.preparation_event(
            "initialize_plus", source, {"noise_model": "noise/v1", "noise_params": {}}
        )
