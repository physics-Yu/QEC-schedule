"""Explicit proxy routing must never turn unknown quantum quality into ideal truth."""

from dataclasses import replace

import pytest

from modules.codes.contracts.component import InvocationContext
from modules.codes.rotated_surface_d3.probabilities.factory import factory_mx_port
from modules.codes.rotated_surface_d3.protocols.cost_proxy import (
    SurfaceCostProxyBackend,
    factory_proxy_recipe,
)
from modules.codes.rotated_surface_d3.protocols.factory import factory_recipe
from modules.codes.rotated_surface_d3.protocols.factory_world import make_factory_world
from modules.codes.rotated_surface_d3.tests.test_cost_proxy import scoped_report


@pytest.fixture(scope="module")
def setup():
    world = make_factory_world()
    backend = SurfaceCostProxyBackend(world.device)
    source = backend.bind_call("raw_t_postselection", (world.bindings["R"],)).expand(
        InvocationContext("proxy/raw", 1000, 300, world.device, world.world_state)
    )
    parameters = {"noise_model": "noise/v1", "noise_params": {"readout_flip": 0.1}}
    port = backend.preparation_event("raw_t_postselection", source, parameters)
    return world, backend, source, parameters, port


def test_proxy_recipe_preserves_all_quantum_calls_and_only_changes_final_route():
    original, proxy = factory_recipe(), factory_proxy_recipe()
    assert proxy.protocol_id == "rotated_surface_d3.factory_15_to_1.cost_proxy"
    assert proxy.final_event.selector == "factory_cost_proxy"
    assert (
        replace(
            proxy, protocol_id=original.protocol_id, final_event=original.final_event
        )
        == original
    )
    assert proxy.accepted_output_calls[0].component_id == "logical_x"


def test_actual_noisy_raw_is_retained_with_explicit_reference_mz_routing(setup):
    _, backend, source, parameters, port = setup
    selected = dict(port.outcome("accepted_5").values)
    quality = backend.preparation_quality_from_event(
        "raw_t_postselection", source, port, selected, parameters
    )
    assert quality["actual_quality"]["status"] == "unsupported"
    assert quality["actual_quality"]["source_port_sha256"] == port.content_sha256
    assert quality["routing_reference"]["id"] == "ideal_cost_proxy.v1"
    assert quality["logical_success_probability"] is None
    assert "input_z_error" not in quality["consumption_parameters"]
    routing = backend.resolve_event("t_consumption", quality["consumption_parameters"])
    assert [o.probability for o in routing.outcomes] == [0.5, 0.5]
    assert (
        routing.to_dict()["model"]["evidence"]["physical_measurement_values_claimed"]
        is False
    )
    assert (
        routing.to_dict()["model"]["parameters"]["actual_quality_status"]
        == "unsupported"
    )
    assert all(m.value is None for m in source.measurements)


@pytest.mark.parametrize(
    "parameters", [None, {}, {"input_z_error": 0}, {"routing_reference": "ideal"}]
)
def test_consumption_without_exact_proxy_marker_does_not_fall_back(setup, parameters):
    _, backend, _, _, _ = setup
    with pytest.raises(ValueError, match="routing"):
        backend.resolve_event("t_consumption", parameters)


def test_raw_proxy_mode_requires_actual_noise_source(setup):
    _, backend, source, _, _ = setup
    with pytest.raises(ValueError, match="noise"):
        backend.preparation_event("raw_t_postselection", source)
    with pytest.raises(ValueError, match="source"):
        backend.preparation_quality("raw_t_postselection")


def test_unscoped_factory_and_old_reference_output_are_rejected(setup):
    _, backend, _, _, _ = setup
    for selector in ("factory_mx", "factory_cost_proxy"):
        with pytest.raises(ValueError, match="scope"):
            backend.resolve_event(selector)
    with pytest.raises(ValueError, match="proxy"):
        backend.output_quality(factory_mx_port())


def test_plus_preparation_remains_explicit_reference_with_pending_physical_values(
    setup,
):
    world, backend, _, _, _ = setup
    source = backend.bind_call("initialize_plus", (world.bindings["W1"],)).expand(
        InvocationContext("proxy/plus", 0, 0, world.device, world.world_state)
    )
    port = backend.preparation_event("initialize_plus", source)
    assert port.to_dict()["model"]["kind"] == "ideal_exact"
    assert all(m.value is None for m in source.measurements)


def test_output_keeps_unknown_quality_and_defers_output_x_to_downstream_scope(setup):
    _, backend, _, _, _ = setup
    report, scope = scoped_report()
    port = backend.factory_proxy_event(report, scope)
    quality = backend.output_quality(port)
    assert quality["actual_quality"]["status"] == "unsupported"
    assert quality["actual_quality"]["source_proxy_port_sha256"] == port.content_sha256
    assert quality["delivery_assessment"]["start_us"] == scope["window_us"][1]
    assert quality["delivery_assessment"]["status"] == "pending"
    assert quality["delivery_assessment"]["includes"][0] == "accepted_output_x"
    assert quality["logical_success_probability"] is None
    routing = backend.resolve_event("t_consumption", quality["consumption_parameters"])
    assert routing.to_dict()["model"]["evidence"]["routing_only"] is True
    report, scope = scoped_report(stage="algorithm")
    terminal = backend.algorithm_proxy_event(report, scope)
    assert all(
        dict(o.values)["proxy_success"] == dict(o.values)["no_fault"]
        for o in terminal.outcomes
    )
    assert (
        terminal.to_dict()["model"]["evidence"]["logical_success_probability"] is None
    )
    with pytest.raises(ValueError, match="proxy"):
        backend.output_quality(terminal)
