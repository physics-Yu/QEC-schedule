"""Reject stale temporal calibration rather than relabeling two-round costs."""

from copy import deepcopy

import pytest

from modules.codes.rotated_surface_d3.protocols.fast_profile import FastProfile
from modules.codes.rotated_surface_d3.tests.test_fast_profile import profile_document


def test_previous_profile_schema_cannot_silently_supply_normal_raw_t():
    document = profile_document()
    document["schema"] = "nadit.fast_surface_factory_profile/1"
    with pytest.raises(ValueError, match="UNSUPPORTED_FAST_PROFILE"):
        FastProfile.from_dict(document)


def test_theory_consumption_cache_cannot_be_used_as_proxy_routing():
    from modules.codes.rotated_surface_d3.protocols.factory_experiment import (
        FactoryExperimentModel,
    )
    from modules.codes.rotated_surface_d3.protocols.fast_calibration import (
        _compact_port,
    )

    document = profile_document()
    theory = FactoryExperimentModel("theory", 0.01)
    document["consumption_port"] = _compact_port(
        theory.consumption_event({"input_z_error": 0.01}).to_dict()
    )
    profile = FastProfile.from_dict(document)
    with pytest.raises(ValueError, match="PROXY_ROUTING"):
        profile.consumption_port()


def canonical_port():
    """A declared R3 toy distribution, not a physical probability claim."""
    return {
        "schema": "nadit.event_probability/1",
        "port_id": "rotated_surface_d3.raw_t_postselection.canonical_preparation",
        "protocol_id": "rotated_surface_d3.raw_t_postselection",
        "protocol_version": "2",
        "model": {
            "id": "round-fixture",
            "kind": "test_fixture",
            "assumptions": ["Synthetic metadata validation fixture"],
            "parameters": {
                "distance": 3,
                "round_policy": "distance",
                "total_rounds": 3,
                "extra_rounds": 2,
            },
            "evidence": {},
        },
        "outcomes": [
            {
                "key": "keep",
                "probability": 1,
                "values": {"accepted": True, "byproduct_class": 0},
                "branch_id": "keep",
            }
        ],
        "branches": [{"key": "keep", "transition": "deliver", "steps": []}],
    }


def calibration_case():
    parts = [
        {
            "invocation_id": f"raw/{index}",
            "description": {"component_id": component, "code_id": "rotated_surface_d3"},
        }
        for index, component in enumerate(("raw_t", "se_round", "se_round"))
    ]
    return {
        "calls": [
            {
                "invocation_id": "raw",
                "component_id": "raw_t_postselection",
                "parameters": {"extra_rounds": 2},
                "part_invocations": [part["invocation_id"] for part in parts],
            }
        ],
        "physical": {
            "parts": parts,
            "invocations": [{"invocation_id": "raw", "result_count": 24}],
        },
        "component_schedule": {"nodes": [{"id": "raw", "spec": {"result_count": 24}}]},
        "probability_models": {"raw": canonical_port()},
    }


@pytest.mark.parametrize(
    "fault",
    (
        "parameters",
        "parts",
        "results",
        "port_version",
        "port_rounds",
        "acceptance_only",
    ),
)
def test_calibration_cannot_relabel_old_calls_or_probability_tables(fault):
    from modules.codes.rotated_surface_d3.protocols.fast_calibration import (
        _validate_raw_rounds,
    )

    case = calibration_case()
    _validate_raw_rounds(case)
    if fault == "parameters":
        case["calls"][0]["parameters"] = {"extra_rounds": 1}
    elif fault == "parts":
        case["calls"][0]["part_invocations"].pop()
    elif fault == "results":
        case["physical"]["invocations"][0]["result_count"] = 16
    elif fault == "port_version":
        case["probability_models"]["raw"]["protocol_version"] = "1"
    elif fault == "port_rounds":
        case["probability_models"]["raw"]["model"]["parameters"]["total_rounds"] = 2
    else:
        case["probability_models"]["raw"]["port_id"] = (
            "rotated_surface_d3.raw_t_postselection.acceptance"
        )
        del case["probability_models"]["raw"]["outcomes"][0]["values"][
            "byproduct_class"
        ]
    with pytest.raises(ValueError, match="RAW_T"):
        _validate_raw_rounds(case)


def test_compact_cache_retains_round_metadata_and_rejects_wrong_cached_table():
    from modules.codes.rotated_surface_d3.protocols.fast_calibration import (
        _compact_port,
    )
    from modules.codes.rotated_surface_d3.protocols.fast_profile import (
        validate_raw_t_port,
    )

    port = canonical_port()
    compact = _compact_port(port)
    validate_raw_t_port(compact)
    for key, value in port["model"]["parameters"].items():
        assert compact["model"]["parameters"][key] == value
    document = profile_document()
    document["preparation_ports"]["raw_t_postselection"] = compact
    profile = FastProfile.from_dict(document)
    cached = profile.preparation_port("raw_t_postselection")
    assert cached.to_dict()["model"]["parameters"]["extra_rounds"] == 2
    compact["model"]["parameters"]["extra_rounds"] = 1
    with pytest.raises(ValueError, match="RAW_T"):
        FastProfile.from_dict(document)


def test_new_raw_profile_accepts_explicit_distance_rounds_and_rejects_r2_lookup():
    document = profile_document()
    raw = deepcopy(document["entries"]["logical_mz"])
    raw.update(
        component_id="raw_t_postselection",
        measurement_phases=[[1, 500]] * 24,
        result_ready_offsets_us=[530] * 24,
    )
    raw["claim"]["result_count"] = 24
    document["entries"]["raw"] = raw
    from modules.codes.rotated_surface_d3.protocols.fast_profile import make_fast_layout

    profile = FastProfile.from_dict(document)
    patch = make_fast_layout(profile, 1).factories[0].bindings["W1"]
    assert (
        profile.lookup(
            "raw_t_postselection", (patch,), parameters=(("extra_rounds", 2),)
        ).claim["result_count"]
        == 24
    )
    for parameters in (
        {"extra_rounds": 1},
        {"extra_rounds": 1, "round_policy": "explicit_control"},
    ):
        with pytest.raises(ValueError, match="PARAMETERS"):
            profile.lookup("raw_t_postselection", (patch,), parameters=parameters)


@pytest.mark.parametrize(
    "field,value",
    (
        ("total_rounds", 2),
        ("extra_rounds", 1),
        ("round_policy", "explicit_control"),
        ("protocol_version", "1"),
    ),
)
def test_current_profile_rejects_wrong_raw_temporal_identity(field, value):
    document = profile_document()
    document["raw_t_protocol"] = {
        "protocol_version": "2",
        "round_policy": "distance",
        "distance": 3,
        "total_rounds": 3,
        "extra_rounds": 2,
    }
    document["raw_t_protocol"][field] = value
    with pytest.raises(ValueError, match="RAW_T"):
        FastProfile.from_dict(document)


def test_raw_entry_cannot_relabel_sixteen_results_as_three_rounds():
    document = profile_document()
    raw = deepcopy(document["entries"]["logical_mz"])
    raw.update(
        component_id="raw_t_postselection",
        measurement_phases=[[1, 500]] * 16,
        result_ready_offsets_us=[530] * 16,
    )
    raw["claim"]["result_count"] = 16
    document["entries"]["raw_t_postselection"] = raw
    with pytest.raises(ValueError, match="RAW_T"):
        FastProfile.from_dict(document)
