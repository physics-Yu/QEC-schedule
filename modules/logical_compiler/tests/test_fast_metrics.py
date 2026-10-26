"""Fast experiments distinguish work, occupied resources and elapsed time."""

import pytest

from modules.logical_compiler.src.estimation.metrics import (
    summarize_costs,
    summarize_samples,
)


def segment(start, end, category="movement", resource="aod:transport"):
    return {
        "start_us": start,
        "end_us": end,
        "category": category,
        "resource": resource,
    }


def test_shared_work_is_not_double_counted_as_device_busy_time():
    calls = [
        {
            "component_id": "raw",
            "cost_segments": [segment(0, 10), segment(10, 12, "gate", "local")],
        },
        {
            "component_id": "raw",
            "cost_segments": [segment(0, 10), segment(10, 12, "gate", "local")],
        },
    ]
    result = summarize_costs(calls, [{"start_us": 12, "end_us": 15}], 15)
    assert result["work_by_category_us"] == {"movement": 20, "gate": 4}
    assert result["resource_busy_us"] == {"aod:transport": 10, "local": 2}
    assert result["global_busy_union_us"] == 12
    assert result["makespan_us"] == 15
    assert result["explicit_global_wait_us"] == 3
    assert result["component_counts"] == {"raw": 2}


def test_same_member_overlapping_actions_use_category_union_not_atom_time():
    calls = [
        {
            "component_id": "mixed",
            "cost_segments": [
                segment(0, 5, "gate", "local"),
                segment(0, 5, "gate", "local"),
                segment(3, 8, "measurement", "camera"),
            ],
        }
    ]
    result = summarize_costs(calls, [], 9)
    assert result["work_by_category_us"] == {"gate": 5, "measurement": 5}
    assert result["global_busy_union_us"] == 8
    assert result["unoccupied_timeline_us"] == 1
    assert sum(result["resource_busy_us"].values()) != result["makespan_us"]


def test_identity_has_no_invented_work_or_busy_time():
    result = summarize_costs([{"component_id": "identity", "cost_segments": []}], [], 0)
    assert result["global_busy_union_us"] == result["makespan_us"] == 0
    assert result["component_counts"] == {"identity": 1}
    assert result["resource_busy_us"] == {}


@pytest.mark.parametrize("end", [-1, float("nan"), 11])
def test_invalid_or_out_of_horizon_cost_segments_fail(end):
    with pytest.raises(ValueError):
        summarize_costs(
            [{"component_id": "raw", "cost_segments": [segment(0, end)]}], [], 10
        )


def test_statistics_use_seed_runs_and_zero_outputs_are_not_zero_probability():
    samples = [
        {
            "seed": 0,
            "factory_count": 4,
            "outputs": 0,
            "makespan_us": 100,
            "wall_seconds": 0.1,
        },
        {
            "seed": 1,
            "factory_count": 4,
            "outputs": 0,
            "makespan_us": 200,
            "wall_seconds": 0.2,
        },
    ]
    result = summarize_samples(samples)
    assert result["independent_seed_runs"] == 2
    assert result["mean_makespan_us"] == 150
    assert result["observed_outputs"] == 0
    assert result["probability_unit"] == "seed_run_with_at_least_one_output"
    assert result["any_output_wilson_95"][0] == 0
    assert result["any_output_wilson_95"][1] > 0
    assert result["line_independence_assumed"] is False
    assert result["output_yield_precision"] == "no_outputs_observed"


def test_duplicate_seed_is_not_counted_as_an_independent_replication():
    record = {
        "seed": 0,
        "factory_count": 2,
        "outputs": 1,
        "makespan_us": 100,
        "wall_seconds": 0.1,
    }
    with pytest.raises(ValueError, match="DUPLICATE"):
        summarize_samples([record, record])
