"""Shared full/fast experiment semantics keep supply, theory and cost distinct."""

from dataclasses import FrozenInstanceError

import pytest

from modules.codes.rotated_surface_d3.probabilities.factory import factory_mx_port
from modules.codes.rotated_surface_d3.protocols.cost_proxy import ROUTING_REFERENCE
from modules.codes.rotated_surface_d3.protocols.factory_experiment import (
    FactoryExperimentModel,
)


@pytest.mark.parametrize("p", [None, True, -0.01, 1.01, float("nan"), float("inf")])
def test_theory_requires_an_explicit_finite_input_quality(p):
    with pytest.raises(ValueError, match="input_z_error"):
        FactoryExperimentModel(input_z_error=p)


def test_proxy_is_explicit_and_cannot_accept_a_theory_quality_parameter():
    with pytest.raises(ValueError, match="mode"):
        FactoryExperimentModel(mode="proxy")
    with pytest.raises(ValueError, match="input_z_error"):
        FactoryExperimentModel(mode="physical_no_fault_proxy", input_z_error=0)
    model = FactoryExperimentModel(mode="physical_no_fault_proxy")
    assert model.recipe().final_event.selector == "factory_cost_proxy"
    assert model.case_id() == "factory-array-cost-proxy-v1"
    assert model.to_dict()["theoretical_acceptance_probability"] is None
    with pytest.raises(ValueError, match="theory"):
        model.final_theory_event()
    with pytest.raises(ValueError, match="theory"):
        model.reference_quality("raw_t_postselection")
    with pytest.raises(ValueError, match="scoped"):
        model.output_quality(factory_mx_port())


@pytest.mark.parametrize("p", [0, 0.001, 0.01, 0.5, 1])
def test_joint_theory_event_uses_original_model_and_formula(p):
    model = FactoryExperimentModel(input_z_error=p)
    assert model.recipe().final_event.selector == "factory_mx"
    assert model.case_id() == "factory-array-theory-v1"
    port = model.final_theory_event()
    assert port.content_sha256 == factory_mx_port(input_z_error=p).content_sha256
    assert len(port.outcomes) == 16
    acceptance = sum(o.probability for o in port.outcomes if dict(o.values)["accepted"])
    assert acceptance == pytest.approx((1 + 15 * (1 - 2 * p) ** 8) / 16)
    for outcome in port.outcomes:
        values = dict(outcome.values)
        assert values["accepted"] == all(values[f"m_w{i}"] == 0 for i in range(2, 6))
        assert "logical_error" not in values
    descriptor = model.to_dict()
    assert descriptor["theoretical_acceptance_probability"] == pytest.approx(acceptance)
    assert descriptor["physical_no_fault_controls_acceptance"] is False
    assert descriptor["actual_logical_quality_established"] is False


def test_noise_parameters_are_separated_from_explicit_input_quality():
    model = FactoryExperimentModel(input_z_error=0.01)
    noise = {"nested": {"rate": 0.2}}
    parameters = model.parameters(noise)
    assert parameters["input_z_error"] == 0.01
    raw = model.raw_preparation_parameters(parameters)
    assert raw == {"noise_model": "noise/v1", "noise_params": noise}
    assert "input_z_error" not in raw
    raw["noise_params"]["nested"]["rate"] = 0.7
    assert noise["nested"]["rate"] == 0.2
    assert parameters["noise_params"]["nested"]["rate"] == 0.2
    assert model.final_theory_event(parameters) == model.final_theory_event(
        {"input_z_error": 0.01}
    )
    proxy = FactoryExperimentModel(mode="physical_no_fault_proxy")
    assert proxy.raw_preparation_parameters(proxy.parameters(noise)) == {
        "noise_model": "noise/v1",
        "noise_params": noise,
    }
    with pytest.raises(FrozenInstanceError):
        model.input_z_error = 0.2


@pytest.mark.parametrize(
    "parameters",
    [
        None,
        {},
        {"input_z_error": 0.02},
        {"noise_model": "other", "noise_params": {}, "input_z_error": 0.01},
        {"noise_model": "noise/v1", "noise_params": [], "input_z_error": 0.01},
        {
            "noise_model": "noise/v1",
            "noise_params": {},
            "input_z_error": 0.01,
            "unused": 1,
        },
    ],
)
def test_raw_model_rejects_ambiguous_or_mismatched_parameters(parameters):
    with pytest.raises(ValueError):
        FactoryExperimentModel(input_z_error=0.01).raw_preparation_parameters(
            parameters
        )


def test_reference_quality_preserves_raw_assumption_and_distilled_consumer_quality():
    model = FactoryExperimentModel(input_z_error=0.01)
    raw = model.reference_quality("raw_t_postselection", source_port_sha256="a" * 64)
    assert raw["consumption_parameters"] == {"input_z_error": 0.01}
    assert raw["status"] == "assumed_reference"
    assert raw["actual_quantum_quality_status"] == "unsupported"
    assert raw["raw_acceptance_does_not_determine_p"] is True
    assert raw["preparation_acceptance_port_sha256"] == "a" * 64
    output = model.output_quality(model.final_theory_event())
    assert output["consumption_parameters"]["input_z_error"] == pytest.approx(
        3.60876839653233e-5
    )
    for quality in (raw, output):
        port = model.consumption_event(quality["consumption_parameters"])
        assert [o.probability for o in port.outcomes] == [0.5, 0.5]
        assert (
            port.to_dict()["model"]["parameters"]["input_z_error"]
            == quality["consumption_parameters"]["input_z_error"]
        )
        assert "routing_reference" not in port.to_dict()["model"]["parameters"]
    with pytest.raises(ValueError, match="preparation"):
        model.reference_quality("initialize_plus")
    with pytest.raises(ValueError, match="SHA"):
        model.reference_quality("raw_t_postselection", source_port_sha256="unknown")
    with pytest.raises(ValueError, match="parameter"):
        model.output_quality(factory_mx_port(input_z_error=0.1))


@pytest.mark.parametrize(
    "parameters",
    [
        None,
        {},
        {"input_z_error": True},
        {"input_z_error": 0.01, "routing_reference": "ideal"},
        {"input_z_error": -1},
    ],
)
def test_consumption_requires_exact_reference_quality(parameters):
    with pytest.raises(ValueError):
        FactoryExperimentModel(input_z_error=0.01).consumption_event(parameters)


def test_explicit_legacy_proxy_consumption_stays_separate():
    model = FactoryExperimentModel(mode="physical_no_fault_proxy")
    port = model.consumption_event(
        {
            "routing_reference": ROUTING_REFERENCE,
            "actual_quality_status": "unsupported",
            "actual_quality_source_port_sha256": "a" * 64,
        }
    )
    assert port.to_dict()["model"]["evidence"]["routing_only"] is True
    with pytest.raises(ValueError):
        model.consumption_event({"input_z_error": 0.01})


@pytest.mark.parametrize(
    "parameters",
    [
        {},
        {"input_z_error": 0.02},
        {"input_z_error": True},
        {"input_z_error": 0.01, "raw_rejection": 0.15},
    ],
)
def test_final_event_rejects_missing_or_changed_reference_quality(parameters):
    with pytest.raises(ValueError):
        FactoryExperimentModel(input_z_error=0.01).final_theory_event(parameters)
