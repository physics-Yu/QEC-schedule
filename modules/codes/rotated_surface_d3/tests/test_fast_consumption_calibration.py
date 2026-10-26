"""Keep the declared consumption model when calibrating theory or proxy sources."""

from copy import deepcopy

import pytest

from modules.codes.rotated_surface_d3.protocols.cost_proxy import ROUTING_REFERENCE
from modules.codes.rotated_surface_d3.protocols.factory_experiment import (
    FactoryExperimentModel,
)
from modules.codes.rotated_surface_d3.protocols.fast_calibration import (
    _consumption_reference,
)


@pytest.mark.parametrize("mode", ("theory", "physical_no_fault_proxy"))
def test_calibration_keeps_actual_declared_consumption_port(mode):
    model = FactoryExperimentModel(mode, 0.01 if mode == "theory" else None)
    parameters = (
        {"input_z_error": 0.01}
        if mode == "theory"
        else {
            "routing_reference": ROUTING_REFERENCE,
            "actual_quality_status": "unsupported",
            "actual_quality_source_port_sha256": "a" * 64,
        }
    )
    original = model.consumption_event(parameters).to_dict()
    case = {"probability_models": {"actual": original}}
    manifest = {"experiment_model": model.to_dict()}
    selected = _consumption_reference(case, manifest)
    assert selected == original
    assert selected is not original
    assert selected["port_id"].endswith(
        ".logical_z" if mode == "theory" else ".reference_routing"
    )
    selected["model"]["parameters"].clear()
    assert case["probability_models"]["actual"] == original


@pytest.mark.parametrize(
    "fault", ("missing", "wrong_mode", "wrong_p", "renamed", "changed_probability")
)
def test_calibration_rejects_missing_or_mismatched_consumption_semantics(fault):
    model = FactoryExperimentModel("theory", 0.01)
    port = model.consumption_event({"input_z_error": 0.01}).to_dict()
    case = {"probability_models": {"actual": deepcopy(port)}}
    manifest = {"experiment_model": model.to_dict()}
    if fault == "missing":
        case["probability_models"] = {}
    elif fault == "wrong_mode":
        manifest["experiment_model"] = FactoryExperimentModel(
            "physical_no_fault_proxy"
        ).to_dict()
    elif fault == "wrong_p":
        manifest["experiment_model"] = FactoryExperimentModel("theory", 0.02).to_dict()
    elif fault == "renamed":
        case["probability_models"]["actual"]["protocol_id"] = "invented.proxy"
    else:
        case["probability_models"]["actual"]["outcomes"][0]["probability"] = 0.4
        case["probability_models"]["actual"]["outcomes"][1]["probability"] = 0.6
    with pytest.raises(ValueError, match="CALIBRATION_CONSUMPTION"):
        _consumption_reference(case, manifest)


def test_calibration_preserves_raw_and_distilled_consumption_models():
    model = FactoryExperimentModel("theory", 0.01)
    raw = model.consumption_event({"input_z_error": 0.01}).to_dict()
    distilled = model.consumption_event(
        {"input_z_error": model.to_dict()["conditional_output_z_error"]}
    ).to_dict()
    case = {"probability_models": {"raw": raw, "distilled": distilled}}
    before = deepcopy(case)
    assert _consumption_reference(case, {"experiment_model": model.to_dict()}) == raw
    assert case == before
