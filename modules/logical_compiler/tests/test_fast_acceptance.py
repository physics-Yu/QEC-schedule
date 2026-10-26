"""Readback comparison fixtures are data shapes, not physical-validity evidence."""

from copy import deepcopy

import pytest

from modules.logical_compiler.examples.fast_acceptance import compare_fast_physical


def _pair():
    identity = "factory0/batch[0]/prepare/attempt[0]/body"
    parts = [identity + "/round[0]", identity + "/round[1]"]
    token = {
        "token_id": "out",
        "epoch": 1,
        "status": "offered",
        "ready_at_us": 4,
        "quality": {"kind": "physical-reference"},
        "provenance": {"hash": "p"},
    }
    carrier = {
        "carrier_id": "factory0/W1",
        "code_id": "fixture",
        "distance": 3,
        "atom_ids": [1],
        "epoch": 1,
        "safe_exit_at_us": 2,
    }
    physical = {
        "case_id": "same-case",
        "seed": 17,
        "status": "complete",
        "duration_us": 5,
        "factories": {
            "factory0": {
                "code": "fixture",
                "recipe": {"version": "1"},
                "limits": {},
                "reference_parameters": {},
                "role_bindings": {"W1": "factory0/W1"},
                "status": "complete",
                "output_token_id": "out",
                "algorithm_consumed_token_id": None,
                "completed_at_us": 5,
            }
        },
        "calls": [
            {
                "factory_id": "factory0",
                "invocation_id": identity,
                "component_id": "raw",
                "participant_roles": ["W1"],
                "start_us": 0,
                "end_us": 2,
                "after_calls": [],
                "event_dependencies": [],
                "consumed_token_id": None,
                "part_invocations": parts,
            }
        ],
        "physical": {
            "parts": [
                {"invocation_id": parts[0], "results_ready_us": 3},
                {"invocation_id": parts[1], "results_ready_us": 4},
            ],
            "validation": {"ok": None},
        },
        "events": [
            {
                "occurrence": {
                    "case_id": "same-case",
                    "invocation_id": "prepare",
                    "attempt": 0,
                    "port_id": "fixture",
                },
                "outcome_key": "accepted",
                "values": {"accepted": True},
                "branch_id": "accept",
                "transition": "deliver",
                "available_at_us": 4,
                "released_at_us": 4,
                "port_sha256": "p",
            }
        ],
        "probability_models": {
            "p": {
                "outcomes": [
                    {"key": "accepted", "probability": 0.8},
                    {"key": "rejected", "probability": 0.2},
                ]
            }
        },
        "component_schedule": {
            "admissions": [
                {
                    "nodes": [{"id": identity}],
                    "start_us": 0,
                    "batch_id": "physical-hash",
                }
            ]
        },
        "resources": {
            "carriers": [carrier],
            "tokens": [token],
            "audit": [{"action": "register", "at_us": 0, "carrier": carrier}],
        },
    }
    fast = deepcopy(physical)
    fast["physical"] = None
    fast["execution_representation"] = "logical_estimate"
    fast["execution"] = {"calls": [{"invocation_id": identity, "results_ready_us": 4}]}
    fast["calls"][0]["part_invocations"] = [identity]
    fast["resources"]["carriers"][0].pop("atom_ids")
    fast["resources"]["carriers"][0]["representation"] = "logical_estimate"
    fast["resources"]["tokens"][0]["quality"] = {"kind": "estimate"}
    fast["resources"]["tokens"][0]["provenance"] = {"profile": "q"}
    fast["component_schedule"]["admissions"][0]["batch_id"] = "logical-hash"
    return fast, physical


def test_comparison_ignores_atom_part_split_but_keeps_full_semantic_clock():
    fast, physical = _pair()
    before = deepcopy((fast, physical))
    report = compare_fast_physical(fast, physical)
    assert report["semantic_schedule_matches"] is True
    assert report["fast_physical_validation"] == "not_run"
    assert report["physical_baseline_validation_ok"] is None
    assert report["logical_success"] is None
    assert (fast, physical) == before


def test_probability_delta_is_separate_from_schedule_and_cost_metrics():
    fast, physical = _pair()
    fast["probability_models"]["p"]["outcomes"][0]["probability"] = 0.81
    fast["probability_models"]["p"]["outcomes"][1]["probability"] = 0.19
    report = compare_fast_physical(
        fast,
        physical,
        fast_cost_reports={"factory": {"metrics": {"no_fault_probability": 0.7}}},
        physical_cost_reports={"factory": {"metrics": {"no_fault_probability": 0.69}}},
    )
    assert report["semantic_schedule_matches"] is True
    event = next(iter(report["event_probability_comparison"]["events"].values()))
    assert event["max_abs_delta"] == pytest.approx(0.01)
    assert report["cost_probability_comparison"]["max_abs_delta"] == pytest.approx(0.01)
    assert report["probability_agreement_included_in_schedule_verdict"] is False


def test_timing_tolerance_is_explicit_and_never_silently_selected():
    fast, physical = _pair()
    fast["calls"][0]["end_us"] += 2e-8
    exact = compare_fast_physical(fast, physical)
    assert exact["semantic_schedule_matches"] is False
    assert exact["comparisons"]["calls"]["max_abs_timing_delta_us"] == pytest.approx(
        2e-8
    )
    tolerant = compare_fast_physical(fast, physical, timing_tolerance_us=1e-7)
    assert tolerant["semantic_schedule_matches"] is True
    assert tolerant["timing_tolerance_us"] == 1e-7


def test_changed_seed_or_missing_readiness_cannot_generate_a_fallback():
    fast, physical = _pair()
    fast["seed"] += 1
    with pytest.raises(ValueError, match="IDENTITY"):
        compare_fast_physical(fast, physical)
    fast["seed"] = physical["seed"]
    fast["execution"]["calls"] = []
    with pytest.raises(KeyError):
        compare_fast_physical(fast, physical)


@pytest.mark.parametrize("field", ["outcome_key", "released_at_us"])
def test_event_outcome_and_release_are_semantic_requirements(field):
    fast, physical = _pair()
    fast["events"][0][field] = "rejected" if field == "outcome_key" else 5
    report = compare_fast_physical(fast, physical)
    assert report["semantic_schedule_matches"] is False
    assert report["comparisons"]["events"]["matches"] is False


def test_exported_uniform_is_compared_and_missing_evidence_stays_explicit():
    fast, physical = _pair()
    report = compare_fast_physical(fast, physical)
    assert report["uniform_evidence"]["fast_missing"] == 1
    assert report["uniform_evidence"]["reconstructed"] is False
    fast["events"][0]["uniform"] = 0.4
    assert compare_fast_physical(fast, physical)["semantic_schedule_matches"] is False
    physical["events"][0]["uniform"] = 0.4
    assert compare_fast_physical(fast, physical)["semantic_schedule_matches"] is True
    fast["events"][0]["uniform"] = 0.41
    assert (
        compare_fast_physical(fast, physical)["comparisons"]["events"]["matches"]
        is False
    )


def test_noise_defaults_are_audited_and_nonzero_changes_remain_differences():
    fast, physical = _pair()
    for case in (fast, physical):
        case["factories"]["factory0"]["reference_parameters"] = {
            "noise_model": "noise/v1",
            "noise_params": {"transport": {"move_loss": 0.01}},
        }
    fast_params = fast["factories"]["factory0"]["reference_parameters"]["noise_params"]
    fast_params["transport"]["load_pauli"] = [0, 0, 0]
    before = deepcopy((fast, physical))
    report = compare_fast_physical(fast, physical)
    assert report["input_compatibility"]["matches"] is False
    assert report["semantic_input_compatibility"]["matches"] is True
    assert report["semantic_schedule_matches"] is True
    additions = report["noise_parameter_normalization"]["physical"]["factory0"][
        "defaults_added"
    ]
    assert {
        "path": "noise_params.transport.load_pauli",
        "value": [0, 0, 0],
    } in additions
    assert (fast, physical) == before
    fast_params["transport"]["load_pauli"] = [0.001, 0, 0]
    report = compare_fast_physical(fast, physical)
    assert report["semantic_input_compatibility"]["matches"] is False
    assert report["semantic_schedule_matches"] is False


def test_invalid_noise_input_is_rejected_by_real_config_resolver():
    fast, physical = _pair()
    fast["factories"]["factory0"]["reference_parameters"] = {
        "noise_model": "noise/v1",
        "noise_params": {"transport": {"load_pauli": [-1, 0, 0]}},
    }
    with pytest.raises(ValueError, match="probability"):
        compare_fast_physical(fast, physical)
