"""Independent hand-computed block-center accounting; no atom actions."""

from copy import deepcopy

import pytest

from experiments.msd.center_metrics import (
    summarize_center_case,
    summarize_center_samples,
)
from experiments.msd.fast_guard import no_atom_execution
from modules.codes.rotated_surface.geometry import geometry
from modules.logical_compiler.src.placement import (
    BlockSpec,
    PlacementRequest,
    VerticalFactoryPlacement,
    place,
)


def _plan():
    roles = ("W1", "W2", "W3", "W4", "W5", "R")
    return place(
        PlacementRequest(
            tuple(
                BlockSpec(f"factory0/{role}", "rotated_surface_d3", 3, "factory0", role)
                for role in roles
            ),
            {"rotated_surface_d3": geometry("rotated_surface_d3", 3)},
        ),
        VerticalFactoryPlacement(roles),
    )


def _segment(start, end, category, resource, atoms, distance=0, counts=None):
    return {
        "start_offset_us": start,
        "end_offset_us": end,
        "category": category,
        "resource": resource,
        "atom_count": atoms,
        "movement_distance_atom_um": distance,
        "primitive_counts": counts or {},
        "basis": "block_center_transport" if distance else "calibration_intrinsic",
    }


def _case(output=True):
    carrier = "factory0/W1"
    token = {
        "token_id": "output0",
        "carrier_id": carrier,
        "epoch": 1,
        "ready_at_us": 8,
        "exit_at_us": 8,
        "quality": {"model": "fixture"},
        "status": "consumed",
        "consumer": "external",
        "consumed_at_us": 8,
        "usage_kind": "consume",
    }
    delivery = {
        "token_id": "output0",
        "carrier_id": carrier,
        "consumer": "external",
        "deliverable_at_us": 8,
        "consumed_at_us": 8,
        "released_at_us": 8,
        "evidence": {"kind": "test_fixture"},
    }
    produced = {
        key: token[key]
        for key in ("token_id", "carrier_id", "epoch", "ready_at_us", "quality")
    }
    produced.update(
        deliverable_at_us=8, consumed_at_us=8, released_at_us=8, delivery=delivery
    )
    calls = [
        {
            "invocation_id": "call0",
            "component_id": "se_round",
            "participant_blocks": [carrier],
            "start_us": 0,
            "action_end_us": 6,
            "estimate_segments": [
                _segment(0, 4, "movement", "aod:transport", 3, 12),
                _segment(4, 6, "gate", "local", 2, counts={"X": 2}),
            ],
        },
        {
            "invocation_id": "call1",
            "component_id": "logical_mz",
            "participant_blocks": ["factory0/W2"],
            "start_us": 0,
            "action_end_us": 6,
            "estimate_segments": [
                _segment(0, 2, "measurement", "camera", 1, counts={"Measure": 1})
            ],
        },
    ]
    audit = [
        {"action": "begin_preparation", "at_us": 0, "carrier_id": carrier, "epoch": 1},
        {
            "action": "consume",
            "at_us": 8,
            "token_id": "output0",
            "consumer": "external",
            "safe_exit_at_us": 8,
            "usage_kind": "consume",
        },
        {
            "action": "complete_use",
            "at_us": 8,
            "carrier_id": carrier,
            "epoch": 1,
            "owner": "external",
        },
    ]
    return {
        "case_id": "center-metric-hand-check",
        "seed": 0,
        "duration_us": 10,
        "status": "complete",
        "physical": None,
        "events": [],
        "factories": {
            "factory0": {
                "outputs": [produced] if output else [],
                "failure": None,
                "milestones": [],
            }
        },
        "resources": {
            "tokens": [token] if output else [],
            "audit": audit if output else [],
        },
        "execution": {
            "calls": calls,
            "waves": [
                {
                    "batch_id": "wave0",
                    "invocations": ["call0", "call1"],
                    "start_us": 0,
                    "end_us": 6,
                }
            ],
        },
    }


def test_whole_window_conserves_atom_time_and_checks_output_lifecycle():
    with no_atom_execution() as audit:
        result = summarize_center_case(_case(), _plan())
    assert audit.to_dict()["passed"]
    assert result["configured_atoms"] == 102
    assert result["configured_atom_time_us"] == 1020
    assert result["busy_atom_time_us"] == 3 * 4 + 2 * 2 + 1 * 2
    assert result["idle_atom_time_us"] == 1002
    assert result["movement_distance_atom_um"] == 12
    assert result["transport_elapsed_us"] == 4
    assert result["startup_deliverable_latency_us"] == 8
    assert result["accepted_outputs"] == result["delivered_outputs"] == 1
    assert result["accepted_outputs_per_second"] == 100_000
    assert result["primitive_counts"] == {"X": 2, "Measure": 1}
    assert result["per_accepted_output"]["configured_atom_time_us"] == 1020
    assert result["outputs"][0]["delivery_lifecycle_verified"]
    assert result["actual_output_error"] is None


def test_clipped_move_uses_declared_constant_speed_and_counts_start_events():
    result = summarize_center_case(_case(), _plan(), warmup_us=1, stop_us=5)
    assert result["configured_atom_time_us"] == 102 * 4
    assert result["busy_atom_time_us"] == 3 * 3 + 2 * 1 + 1 * 1
    assert result["idle_atom_time_us"] == 396
    assert result["movement_distance_atom_um"] == 9
    assert result["transport_elapsed_us"] == 3
    assert result["primitive_counts"] == {"X": 2}
    assert result["exposure_by_category"]["measurement"]["active_atom_time_us"] == 1
    assert result["exposure_by_category"]["measurement"]["macro_segment_starts"] == 0
    assert result["accepted_outputs"] == 0
    assert result["accepted_outputs_per_second"] == 0
    assert result["per_accepted_output"]["movement_distance_atom_um"] is None


def test_aggregate_busy_integral_is_preserved_and_uniformly_clipped():
    case = _case()
    case["execution"]["calls"][0]["estimate_segments"][0]["busy_atom_us"] = 6
    whole = summarize_center_case(case, _plan())
    clipped = summarize_center_case(case, _plan(), warmup_us=1, stop_us=5)
    assert whole["busy_atom_time_us"] == 6 + 4 + 2
    assert clipped["busy_atom_time_us"] == 6 * 3 / 4 + 2 + 1
    assert clipped["idle_atom_time_us"] == 408 - 7.5
    assert whole["aggregate_exposure_segments"] == 1
    assert "uniform aggregate exposure" in whole["atom_time_basis"]
    assert whole["primitive_counts"] == {"X": 2, "Measure": 1}
    assert clipped["primitive_counts"] == {"X": 2}
    for bad in (12.1, -1, float("nan")):
        case["execution"]["calls"][0]["estimate_segments"][0]["busy_atom_us"] = bad
        with pytest.raises(ValueError):
            summarize_center_case(case, _plan())


def test_zero_output_is_not_a_missing_rate_or_zero_startup():
    result = summarize_center_case(_case(False), _plan())
    assert result["startup_deliverable_latency_us"] is None
    assert result["accepted_outputs_per_second"] == 0
    assert result["per_accepted_output"]["busy_atom_time_us"] is None


def test_output_on_stop_boundary_is_retained_but_not_counted_in_window():
    result = summarize_center_case(_case(), _plan(), stop_us=8)
    assert result["accepted_outputs"] == result["delivered_outputs"] == 0
    assert result["accepted_outputs_total"] == result["delivered_outputs_total"] == 1
    assert result["startup_deliverable_latency_us"] == 8


@pytest.mark.parametrize("failed", [False, True])
def test_incomplete_or_failed_windows_keep_cost_but_have_no_throughput(failed):
    case = _case()
    if failed:
        case["status"] = "partial_failure"
        case["factories"]["factory0"]["failure"] = {"at_us": 9, "code": "raw_exhausted"}
    result = summarize_center_case(case, _plan(), stop_us=20)
    assert result["window_status"] == ("failed" if failed else "incomplete")
    assert not result["requested_window_complete"]
    assert result["actual_observation_us"] == 10
    assert result["accepted_outputs"] == 1
    assert result["accepted_outputs_per_second"] is None
    assert result["configured_atom_time_us"] == 1020


@pytest.mark.parametrize(
    "damage", ["overlap", "atoms", "missing_segments", "alias", "delivery"]
)
def test_malformed_accounting_cannot_create_cost_or_output_evidence(damage):
    case = _case()
    if damage == "overlap":
        case["execution"]["calls"][0]["estimate_segments"][1]["start_offset_us"] = 3
    elif damage == "atoms":
        case["execution"]["calls"][0]["estimate_segments"][0]["atom_count"] = 18
    elif damage == "missing_segments":
        del case["execution"]["calls"][0]["estimate_segments"]
    elif damage == "alias":
        case["execution"]["calls"][1]["participant_blocks"] = ["factory0/W1"]
    else:
        case["resources"]["audit"].pop()
    with pytest.raises(ValueError):
        summarize_center_case(case, _plan())


def test_seed_statistics_include_zero_rates_and_mark_missing_startup():
    first = summarize_center_case(_case(), _plan())
    second = summarize_center_case(_case(False), _plan())
    second["seed"] = 1
    third = deepcopy(first)
    third.update(seed=2, requested_window_complete=False, window_status="failed")
    result = summarize_center_samples([first, second, third])
    assert result["seed_count"] == 3
    assert result["complete_seed_count"] == 2
    rate = result["statistics"]["accepted_outputs_per_second"]
    assert rate["mean"] == 50_000
    half = 12.706204736432095 * 50_000
    assert rate["confidence_interval_95"] == pytest.approx(
        [50_000 - half, 50_000 + half]
    )
    startup = result["statistics"]["startup_deliverable_latency_us"]
    assert startup["n"] == 1
    assert startup["missing_values"] == 1
    assert startup["confidence_interval_95"] is None
    assert result["excluded_seeds"] == [{"seed": 2, "window_status": "failed"}]
    with pytest.raises(ValueError, match="DUPLICATE"):
        summarize_center_samples([first, first])


def test_pooled_cost_includes_zero_output_windows_and_reports_failed_cost_separately():
    positive = summarize_center_case(_case(), _plan())
    zero = summarize_center_case(_case(False), _plan())
    zero["seed"] = 1
    failed = deepcopy(zero)
    failed.update(seed=2, requested_window_complete=False, window_status="failed")
    for record, cost in ((positive, 100), (zero, 100), (failed, 30)):
        record["busy_atom_time_us"] = cost
        record["per_accepted_output"]["busy_atom_time_us"] = (
            cost if record["accepted_outputs"] else None
        )
    result = summarize_center_samples([positive, zero, failed])
    assert result["pooled_cost_per_accepted_output"]["busy_atom_time_us"] == 200
    assert result["pooled_accepted_outputs_per_second"] == 50_000
    ratio = result["statistics"]["busy_atom_time_us_per_accepted_output"]
    assert ratio["mean"] == 100
    assert "positive accepted output" in ratio["conditioning"]
    assert result["all_seed_incurred_costs"]["costs"]["busy_atom_time_us"] == 230
    assert (
        result["all_seed_incurred_costs"]["per_accepted_output"]["busy_atom_time_us"]
        == 230
    )
    assert "diagnostic" in result["all_seed_incurred_costs"]["basis"]
