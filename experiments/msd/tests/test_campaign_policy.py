"""Pilot-derived windows freeze before production and include cold work budgets."""

from copy import deepcopy

import pytest

from experiments.msd.campaign_policy import resolve_observation_policy


def inputs():
    outputs = [
        {
            "cycle": i,
            "token_id": f"fixture/{i}",
            "ready_at_us": end - 2,
            "deliverable_at_us": end - 1,
            "consumed_at_us": end - 1,
            "released_at_us": end,
            "delivery": {"test_fixture": True},
        }
        for i, end in enumerate((120, 220))
    ]
    return (
        {
            "case": {
                "status": "complete",
                "factories": {"f0": {"status": "complete", "outputs": outputs}},
            }
        },
        {
            "pilot_cycles": 2,
            "warmup_cycles": 2,
            "target_observation_cycles": 8,
            "minimum_observation_cycles": 2,
            "max_total_simulated_us": 10000,
            "software_safety_factor": 2,
        },
    )


def test_fixed_rule_uses_cold_worker_cost_and_safe_cycle_scale():
    pilot, rule = inputs()
    resolved = resolve_observation_policy(
        pilot, rule, available_worker_seconds=120, pilot_worker_seconds=20
    )
    assert resolved["cycle_scale_us"] == 120
    assert resolved["software_budget_cycles"] == 6
    assert resolved["observation_cycles"] == 4
    assert resolved["warmup_us"] == 240
    assert resolved["stop_us"] == 720
    assert resolved == resolve_observation_policy(
        pilot, rule, available_worker_seconds=120, pilot_worker_seconds=20
    )


@pytest.mark.parametrize(
    "change", ("failed", "undelivered", "duplicate", "single_cycle")
)
def test_inadequate_pilot_cannot_start_formal_statistics(change):
    pilot, rule = inputs()
    rows = pilot["case"]["factories"]["f0"]["outputs"]
    if change == "failed":
        pilot["case"]["status"] = "partial_failure"
    elif change == "undelivered":
        rows[-1]["released_at_us"] = None
    elif change == "duplicate":
        rows[-1]["token_id"] = rows[0]["token_id"]
    else:
        rows.pop()
    with pytest.raises(ValueError):
        resolve_observation_policy(
            pilot, rule, available_worker_seconds=120, pilot_worker_seconds=20
        )


def test_too_small_budget_fails_instead_of_changing_the_minimum_rule():
    pilot, rule = inputs()
    original = deepcopy(rule)
    with pytest.raises(ValueError, match="PILOT_BUDGET_CANNOT_SUPPORT"):
        resolve_observation_policy(
            pilot, rule, available_worker_seconds=20, pilot_worker_seconds=20
        )
    assert rule == original


def two_level_inputs():
    """Synthetic L1 surplus and L2 terminal cycles; no physical output claim."""
    pilot, rule = inputs()
    pilot["case"]["factories"]["L1"] = {
        "status": "complete",
        "failure": None,
        "outputs": [
            {
                "cycle": 0,
                "token_id": "upstream/0",
                "ready_at_us": 5000,
                "deliverable_at_us": None,
                "consumed_at_us": None,
                "released_at_us": None,
                "delivery": None,
                "retention": {"reason": "downstream_completed"},
            }
        ],
    }
    return pilot, rule


def test_selected_l2_windows_keep_whole_run_software_cost_and_full_pilot_hash():
    from nadit_physical_compiler.provenance import canonical_hash

    pilot, rule = two_level_inputs()
    original = deepcopy(pilot)
    resolved = resolve_observation_policy(
        pilot,
        rule,
        available_worker_seconds=240,
        pilot_worker_seconds=40,
        output_factory_ids={"f0"},
    )
    assert resolved["cycle_scale_us"] == 120
    assert resolved["warmup_us"] == 240 and resolved["stop_us"] == 720
    assert resolved["pilot_worker_seconds"] == 40
    assert resolved["software_budget_cycles"] == 6
    assert resolved["output_factory_ids"] == ["f0"]
    assert resolved["pilot_sha256"] == canonical_hash(pilot)
    assert pilot == original
    # Default continues to require delivered cycles on every factory line.
    with pytest.raises(ValueError, match="PILOT_REQUIRES_CONTINUOUS_DELIVERED_CYCLES"):
        resolve_observation_policy(
            pilot, rule, available_worker_seconds=240, pilot_worker_seconds=40
        )


def test_selected_multiple_l2_lines_use_slowest_terminal_cycle():
    pilot, rule = two_level_inputs()
    second = deepcopy(pilot["case"]["factories"]["f0"])
    for index, end in enumerate((180, 350)):
        second["outputs"][index].update(
            token_id=f"second/{index}",
            ready_at_us=end - 2,
            deliverable_at_us=end - 1,
            consumed_at_us=end - 1,
            released_at_us=end,
        )
    pilot["case"]["factories"]["f1"] = second
    resolved = resolve_observation_policy(
        pilot,
        rule,
        available_worker_seconds=120,
        pilot_worker_seconds=20,
        output_factory_ids=frozenset({"f1", "f0"}),
    )
    assert resolved["output_factory_ids"] == ["f0", "f1"]
    assert resolved["cycle_scale_us"] == 180
    assert resolved["warmup_us"] == 360 and resolved["stop_us"] == 1080


@pytest.mark.parametrize(
    "selected", (set(), {"absent"}, {"f0", "absent"}, "f0", ["f0"], {1})
)
def test_invalid_output_factory_filter_is_rejected(selected):
    pilot, rule = two_level_inputs()
    with pytest.raises(ValueError, match="INVALID_PILOT_OUTPUT_FACTORY_FILTER"):
        resolve_observation_policy(
            pilot,
            rule,
            available_worker_seconds=120,
            pilot_worker_seconds=20,
            output_factory_ids=selected,
        )


@pytest.mark.parametrize(
    "damage", ("failed_case", "failed_line", "line_failure", "case_failure")
)
def test_selecting_l2_cannot_hide_an_upstream_failure(damage):
    pilot, rule = two_level_inputs()
    if damage == "failed_case":
        pilot["case"]["status"] = "partial_failure"
    elif damage == "failed_line":
        pilot["case"]["factories"]["L1"]["status"] = "input_supply_exhausted"
    elif damage == "line_failure":
        pilot["case"]["factories"]["L1"]["failure"] = {"label": "failed"}
    else:
        pilot["case"]["failure"] = {"label": "failed"}
    with pytest.raises(ValueError, match="PILOT_INCOMPLETE"):
        resolve_observation_policy(
            pilot,
            rule,
            available_worker_seconds=120,
            pilot_worker_seconds=20,
            output_factory_ids={"f0"},
        )


@pytest.mark.parametrize("damage", ("missing", "retained", "missing_delivery"))
def test_selected_l2_still_requires_every_terminal_pilot_output(damage):
    pilot, rule = two_level_inputs()
    outputs = pilot["case"]["factories"]["f0"]["outputs"]
    if damage == "missing":
        outputs.pop()
    elif damage == "retained":
        outputs[-1]["released_at_us"] = None
    else:
        outputs[-1]["delivery"] = None
    with pytest.raises(ValueError):
        resolve_observation_policy(
            pilot,
            rule,
            available_worker_seconds=120,
            pilot_worker_seconds=20,
            output_factory_ids={"f0"},
        )


def test_default_policy_output_shape_has_no_new_selector_field():
    pilot, rule = inputs()
    resolved = resolve_observation_policy(
        pilot, rule, available_worker_seconds=120, pilot_worker_seconds=20
    )
    assert "output_factory_ids" not in resolved


def test_explicit_warm_cost_changes_only_slope_not_preparation_cost_or_cycle_rule():
    pilot, rule = inputs()
    with pytest.raises(ValueError, match="PILOT_BUDGET_CANNOT_SUPPORT"):
        resolve_observation_policy(
            pilot, rule, available_worker_seconds=120, pilot_worker_seconds=2000
        )
    resolved = resolve_observation_policy(
        pilot,
        rule,
        available_worker_seconds=120,
        pilot_worker_seconds=2000,
        warm_replay_worker_seconds=20,
    )
    assert resolved["pilot_worker_seconds"] == 2000
    assert resolved["software_budget_cycles"] == 6
    assert resolved["observation_cycles"] == 4 and resolved["cycle_scale_us"] == 120
    assert resolved["software_cost_model"]["warm_replay_worker_seconds"] == 20
    assert resolved["software_cost_model"]["work_per_cycle_seconds"] == 10


@pytest.mark.parametrize("value", [0, -1, float("nan"), True])
def test_explicit_warm_slope_requires_positive_measurement(value):
    pilot, rule = inputs()
    with pytest.raises(ValueError, match="warm_replay_worker_seconds"):
        resolve_observation_policy(
            pilot,
            rule,
            available_worker_seconds=120,
            pilot_worker_seconds=2000,
            warm_replay_worker_seconds=value,
        )
