"""Deterministic campaign coverage and conditional seed statistics."""

import csv
import json
from copy import deepcopy

import pytest
from nadit_physical_compiler.provenance import canonical_hash

from experiments.msd.campaign_plan import expand_single_level
from experiments.msd.campaign_report import summarize_campaign
from experiments.msd.production_metrics import summarize_production
from experiments.msd.tests.test_production_metrics import fixture as activity_fixture


def test_supply_window_diagnostics_use_history_not_empty_final_inventory():
    from experiments.msd.campaign_report import _supply_diagnostics
    from experiments.msd.tests.test_supply_metrics import fixture as supply_fixture

    result = supply_fixture()
    result["supply"]["schema"] = "nadit.factory_supply/1"
    result["metrics"] = {"requested_window_us": [5, 10]}
    diagnostics = _supply_diagnostics(result, 2)
    assert diagnostics["buffer_occupied"] == 0
    window = diagnostics["window"]
    assert window["buffer"]["peak_occupied_slots"] == 2
    assert window["buffer"]["mean_occupied_slots"] == 1.6
    assert window["buffer"]["token_time_weighted_mean_age_us"] == 3.875


def test_supply_window_metrics_reach_seed_statistics_and_csv(tmp_path, monkeypatch):
    import experiments.msd.campaign_report as report_module

    plan, results = two_level_fixture()
    seen = []

    def summary(result, *, warmup_us, stop_us):
        seen.append((warmup_us, stop_us))
        return {
            "buffer": {"peak_occupied_slots": 1, "mean_occupied_slots": 0.5},
            "waits": {"consumer_starvation": {"factory_sum_us": 8}},
        }

    monkeypatch.setattr(
        report_module, "summarize_supply_window", summary, raising=False
    )
    for result in results.values():
        result["supply"]["buffer"]["audit"] = []
    report = summarize_campaign(
        plan,
        {identity: "complete" for identity in results},
        results,
        output_dir=tmp_path,
    )
    assert seen == [(5000, 25000)] * len(results)
    for row in report["layouts"]:
        assert row["statistics"]["buffer_mean_occupancy"]["mean"] == 0.5
        assert row["statistics"]["l2_starvation_factory_time_us"]["mean"] == 8
    with (tmp_path / "trajectory-status.csv").open(newline="") as stream:
        assert all(
            row["buffer_peak_occupancy"] == "1.0" for row in csv.DictReader(stream)
        )


def two_level_fixture(*, arrivals=(32, 31), changes=None, evidence=None):
    from experiments.msd.campaign_plan import expand_two_level
    from experiments.msd.tests.test_campaign_plan import (
        arrival_evidence,
        two_level_configuration,
    )

    evidence = arrival_evidence(arrivals) if evidence is None else evidence
    config = two_level_configuration(evidence)
    config.update(level2_counts=[1], grid_columns=[1], layout_families=["centralized"])
    config.update(changes or {})
    plan = expand_two_level(
        config, evidence, source_identity={"fixture": "two-level-report"}
    )
    plan["observation_policy"] = {"by_layout": {}}
    _, old_results = fixture(seeds=(1,))
    template = next(iter(old_results.values()))
    results = {}
    for layout in plan["layouts"]:
        selected = [
            f"factory{i}"
            for i in range(layout["level1_count"], layout["factory_count"])
        ]
        policy = {"warmup_us": 5000, "stop_us": 25000, "output_factory_ids": selected}
        plan["observation_policy"]["by_layout"][layout["layout_id"]] = policy
        for task in plan["tasks"]:
            if (
                task["layout_id"] != layout["layout_id"]
                or layout["budget_exclusions"]
                or layout["supply_exclusions"]
                or layout.get("selection_exclusions")
            ):
                continue
            row = deepcopy(template)
            count = layout["buffer_capacity"] * task["seed"]
            row.update(
                {
                    key: task[key]
                    for key in (
                        "layout_id",
                        "seed",
                        "config_sha256",
                        "source_sha256",
                        "buffer_capacity",
                        "arrival_evidence_sha256",
                    )
                }
            )
            row.update(
                trajectory_id=task["task_id"],
                geometry_layout_id=layout["geometry_layout_id"],
                observation_policy_sha256=canonical_hash(policy),
            )
            metrics = row["metrics"]
            metrics.update(
                configured_atoms=layout["configured_atoms"],
                occupied_footprint_area_um2=layout["home_occupied_bounding_area_um2"],
                accepted_outputs=count,
                delivered_outputs=count,
                delivered_outputs_per_second=count * 50,
                output_factory_ids=selected,
                configured_atom_time_us=layout["configured_atoms"] * 20000,
                outputs=[
                    {"token_id": f"output-{i}", "factory_id": selected[0]}
                    for i in range(count)
                ],
            )
            metrics["per_accepted_output"]["configured_atom_time_us"] = (
                metrics["configured_atom_time_us"] / count
            )
            row["case"]["seed"] = task["seed"]
            row["case_sha256"] = canonical_hash(row["case"])
            row["supply"] = {
                "schema": "nadit.factory_supply/1",
                "buffer": {
                    "capacity": layout["buffer_capacity"],
                    "occupied": 1,
                    "items": [{"token_id": "queued", "queued_at_us": 24000}],
                },
                "waiting_producer_outputs": ["waiting-source"],
                "pending_consumer_requests": [],
            }
            results[task["task_id"]] = row
    return plan, results


def test_two_level_candidate_cap_preserves_excluded_coverage():
    plan, results = two_level_fixture(changes={"max_candidate_layouts": 1})
    report = summarize_campaign(plan, {key: "complete" for key in results}, results)
    assert report["coverage"] == {"complete": 2, "selection_excluded": 2}
    assert report["expected_trajectories"] == 4
    assert report["candidate_selection"] == plan["candidate_selection"]
    assert report["campaign_complete"] is True


@pytest.mark.parametrize(
    "fault", ["score", "layout_exclusions", "task_exclusions", "completed"]
)
def test_two_level_report_rejects_forged_candidate_selection(fault):
    plan, results = two_level_fixture(changes={"max_candidate_layouts": 1})
    excluded = next(row for row in plan["layouts"] if row["selection_exclusions"])
    task = next(
        row for row in plan["tasks"] if row["layout_id"] == excluded["layout_id"]
    )
    status = {}
    if fault == "score":
        plan["candidate_selection"]["pair_priorities"][0]["score"] *= 2
    elif fault == "layout_exclusions":
        excluded["selection_exclusions"] = []
    elif fault == "task_exclusions":
        task["selection_exclusions"] = []
    else:
        status[task["task_id"]] = "complete"
    with pytest.raises(ValueError, match="SELECTION"):
        summarize_campaign(plan, status, results)


def test_two_level_capacity_cells_keep_policies_statistics_and_resource_areas_separate(
    tmp_path,
):
    plan, results = two_level_fixture()
    status = {key: "complete" for key in results}
    report = summarize_campaign(plan, status, results, output_dir=tmp_path)
    assert report["campaign_complete"] is True
    cells = {row["buffer_capacity"]: row for row in report["layouts"]}
    assert len(cells) == 2
    assert cells[1]["geometry_layout_id"] == cells[2]["geometry_layout_id"]
    assert cells[1]["layout_id"] != cells[2]["layout_id"]
    assert cells[1]["statistics"]["steady_deliverable_throughput_per_s"]["mean"] == 575
    assert cells[2]["statistics"]["steady_deliverable_throughput_per_s"]["mean"] == 1150
    allocated = cells[1]["total_slm_bounding_area_um2"] * 20000
    assert cells[1]["statistics"]["allocated_slm_area_time_um2_us"]["mean"] == allocated
    assert cells[2]["statistics"]["allocated_slm_area_time_um2_us"]["mean"] == allocated
    assert cells[1]["statistics"]["allocated_slm_area_time_per_accepted_output_um2_us"][
        "mean"
    ] == pytest.approx((allocated / 11 + allocated / 12) / 2)
    trajectory = report["trajectories"][0]
    assert trajectory["allocated_slm_area_time_um2_us"] == allocated
    assert (
        trajectory["allocated_slm_area_time_per_delivered_output_um2_us"]
        == allocated / trajectory["delivered_outputs"]
    )
    for cell in cells.values():
        assert cell["level1_count"] == 2 and cell["level2_count"] == 1
        assert (
            cell["home_occupied_bounding_area_um2"]
            == cell["occupied_bounding_area_um2"]
        )
        assert (
            cell["total_slm_bounding_area_um2"]
            > cell["home_occupied_bounding_area_um2"]
        )
        assert cell["configured_atoms"] == 306
        assert cell["layout_families"] == ["centralized"]
    diagnostic = report["trajectories"][0]["supply_diagnostics"]
    assert diagnostic["snapshot_at_us"] == 26000
    assert diagnostic["source_backlog_count"] == 1
    assert diagnostic["maximum_buffer_age_us"] == 2000
    assert diagnostic["window_maximum_source_backlog"] is None
    assert report["actual_output_error"] is None
    with (tmp_path / "layout-summary.csv").open(newline="") as stream:
        exported = list(csv.DictReader(stream))
    assert {row["buffer_capacity"] for row in exported} == {"1", "2"}
    assert all(
        row["level1_count"] == "2" and row["total_slm_bounding_area_um2"]
        for row in exported
    )


@pytest.mark.parametrize(
    "fault", ("capacity", "geometry", "output_scope", "home_area", "all_layer_cost")
)
def test_two_level_report_rejects_mixed_capacity_scope_or_resource_results(fault):
    plan, results = two_level_fixture()
    identity = plan["tasks"][0]["task_id"]
    row = results[identity]
    if fault == "capacity":
        row["buffer_capacity"] += 1
    elif fault == "geometry":
        row["geometry_layout_id"] = "wrong"
    elif fault == "output_scope":
        row["metrics"]["output_factory_ids"] = ["factory0"]
    elif fault == "home_area":
        row["metrics"]["occupied_footprint_area_um2"] = plan["layouts"][0][
            "total_slm_bounding_area_um2"
        ]
    else:
        row["metrics"]["configured_atom_time_us"] /= 3
    reason = {
        "capacity": "TWO_LEVEL_RESULT_CONTEXT_MISMATCH",
        "geometry": "TWO_LEVEL_RESULT_CONTEXT_MISMATCH",
        "output_scope": "TWO_LEVEL_OUTPUT_SCOPE_MISMATCH",
        "home_area": "CAMPAIGN_RESULT_RESOURCE_BUDGET_MISMATCH",
        "all_layer_cost": "TWO_LEVEL_ALL_LAYER_COST_MISMATCH",
    }[fault]
    with pytest.raises(ValueError, match=reason):
        summarize_campaign(plan, {identity: "complete"}, results)


def test_two_level_report_uses_allocated_slm_budget_and_keeps_supply_exclusions_explicit():
    baseline, _ = two_level_fixture()
    layout = baseline["layouts"][0]
    limit = (
        layout["home_occupied_bounding_area_um2"]
        + layout["total_slm_bounding_area_um2"]
    ) / 2
    plan, results = two_level_fixture(
        changes={"budget": {"max_atoms": 10000, "max_footprint_um2": limit}}
    )
    report = summarize_campaign(plan, {}, results)
    assert report["coverage"] == {"budget_excluded": 4}
    assert all(not row["within_footprint_budget"] for row in report["layouts"])
    plan, results = two_level_fixture(arrivals=(14, 14))
    report = summarize_campaign(plan, {}, results)
    assert report["coverage"] == {"supply_excluded": 4}
    assert report["status"] == "supply_excluded"


def test_two_level_report_preserves_unsupported_protocols_and_unavailable_sources():
    plan, results = two_level_fixture(changes={"distance_pairs": [[3, 5], [7, 7]]})
    report = summarize_campaign(plan, {}, results)
    assert report["campaign_complete"] is False
    assert report["protocol_dependencies"][0]["status"] == "unsupported_protocol"
    assert report["unavailable_sources"] == [
        {"distance": 7, "reason": "no_frozen_arrival_trajectories"}
    ]


def test_two_level_zero_output_keeps_allocated_area_time_but_null_unit_cost():
    plan, results = two_level_fixture()
    identity = plan["tasks"][0]["task_id"]
    metrics = results[identity]["metrics"]
    metrics.update(
        accepted_outputs=0,
        delivered_outputs=0,
        delivered_outputs_per_second=0,
        outputs=[],
        per_accepted_output={},
    )
    report = summarize_campaign(plan, {identity: "complete"}, results)
    row = next(
        row for row in report["trajectories"] if row["trajectory_id"] == identity
    )
    assert row["status"] == "zero_output"
    assert row["allocated_slm_area_time_um2_us"] > 0
    assert row["allocated_slm_area_time_per_accepted_output_um2_us"] is None
    assert row["allocated_slm_area_time_per_delivered_output_um2_us"] is None


@pytest.mark.parametrize("fault", ("capacity_cell", "allocated_area"))
def test_two_level_report_rejects_incomplete_cells_or_forged_allocated_resources(fault):
    plan, results = two_level_fixture()
    if fault == "capacity_cell":
        removed = plan["layouts"].pop()["layout_id"]
        plan["tasks"] = [task for task in plan["tasks"] if task["layout_id"] != removed]
        reason = "INCOMPLETE_TWO_LEVEL_LAYOUT_CAPACITY_GRID"
    else:
        plan["layouts"][0]["total_slm_bounding_area_um2"] += 10
        reason = "STALE_TWO_LEVEL_LAYOUT_RESOURCES"
    with pytest.raises(ValueError, match=reason):
        summarize_campaign(plan, {}, results)


def test_two_level_optional_plots_export_separate_capacity_cells_without_execution(
    tmp_path, monkeypatch
):
    from experiments.msd import standard

    plan, results = two_level_fixture()
    monkeypatch.setattr(
        standard, "build_world", lambda *a, **k: pytest.fail("report rebuilt world")
    )
    summarize_campaign(
        plan,
        {identity: "complete" for identity in results},
        results,
        output_dir=tmp_path,
        plots=True,
    )
    for axis in ("distance", "level1_count", "level2_count", "buffer_capacity"):
        assert (tmp_path / f"scaling-{axis}.png").stat().st_size > 1000
    assert len(list((tmp_path / "representatives").glob("*/layout.png"))) == 2


@pytest.mark.parametrize(
    "family,is_default", (("local_groups", True), ("boundary", False))
)
def test_two_level_report_validates_actual_default_and_explicit_slm_allocations(
    monkeypatch, family, is_default
):
    from experiments.msd import campaign_plan, standard
    from experiments.msd.tests.test_campaign_plan import (
        arrival_evidence,
        two_level_configuration,
    )
    from modules.logical_compiler.src.placement import (
        PlacementPlan,
        VerticalFactoryPlacement,
        place,
    )

    evidence = arrival_evidence(factories=1)
    config = two_level_configuration(evidence)
    config.update(
        level2_counts=[1],
        buffer_capacities=[1],
        grid_columns=[1],
        layout_families=[family],
    )
    plan = campaign_plan.expand_two_level(
        config, evidence, source_identity={"fixture": "allocation-branches"}
    )
    assert len(plan["layouts"]) == 1
    layout = plan["layouts"][0]
    spec = standard.ExperimentSpec(**layout["spec"])
    default = place(
        standard.placement_request(spec),
        VerticalFactoryPlacement(
            standard.FACTORY_ROLES, spec.patch_gap_um, spec.factory_gap_um
        ),
    )
    assert (
        PlacementPlan.from_dict(layout["placement"]).placements == default.placements
    ) is is_default
    for module in (standard, campaign_plan):
        monkeypatch.setattr(
            module,
            "build_world",
            lambda *a, **k: pytest.fail("report rebuilt a physical world"),
        )
    report = summarize_campaign(plan, {}, {})
    assert report["coverage"] == {"not_run": 2}
    assert report["layouts"][0]["slm_site_count"] == layout["slm_site_count"]
    assert (
        report["layouts"][0]["total_slm_bounding_area_um2"]
        == layout["total_slm_bounding_area_um2"]
    )


def test_two_level_report_counts_deduplicated_cells_once_and_retains_all_sources():
    from experiments.msd.tests.test_campaign_plan import two_source_evidence

    plan, results = two_level_fixture(evidence=two_source_evidence((32, 31), (8, 8)))
    report = summarize_campaign(plan, {key: "complete" for key in results}, results)
    assert report["expected_trajectories"] == report["valid_trajectories"] == 4
    assert len(report["layouts"]) == 2
    for row in report["layouts"]:
        groups = row["arrival_groups"]
        assert len(groups) == 2
        assert row["statistics"]["steady_deliverable_throughput_per_s"]["n"] == 2
        eligible = [group for group in groups if group["independently_eligible"]]
        assert len(eligible) == 1
        assert row["arrival_group_id"] == eligible[0]["arrival_group_id"]
        assert row["supply_coverage"]["trajectories"] == eligible[0]["trajectories"]
    for row in report["trajectories"]:
        assert len(row["arrival_group_ids"]) == 2
        assert "arrival_groups" not in row


@pytest.mark.parametrize(
    "fault",
    (
        "missing_group",
        "pooled_seeds",
        "eligibility",
        "representative",
        "duplicate_cell",
        "group_order",
    ),
)
def test_two_level_report_rejects_lost_pooled_or_misrepresented_source_groups(fault):
    from experiments.msd.tests.test_campaign_plan import two_source_evidence

    plan, results = two_level_fixture(evidence=two_source_evidence((32, 31), (8, 8)))
    row = plan["layouts"][0]
    if fault == "missing_group":
        row["arrival_groups"].pop()
    elif fault == "pooled_seeds":
        row["arrival_groups"][0]["trajectories"].extend(
            row["arrival_groups"][1]["trajectories"]
        )
    elif fault == "eligibility":
        row["arrival_groups"][0]["independently_eligible"] = not row["arrival_groups"][
            0
        ]["independently_eligible"]
    elif fault == "representative":
        wrong = next(
            group
            for group in row["arrival_groups"]
            if not group["independently_eligible"]
        )
        row.update(
            arrival_group_id=wrong["arrival_group_id"],
            source_layout_id=wrong["source_layout_id"],
            supply_exclusions=wrong["supply_exclusions"],
        )
        row["supply_coverage"]["trajectories"] = wrong["trajectories"]
    elif fault == "duplicate_cell":
        plan["layouts"].append(deepcopy(row))
    else:
        row["arrival_groups"].reverse()
    with pytest.raises(ValueError, match="TWO_LEVEL_(ARRIVAL|LAYOUT_IDENTITY)"):
        summarize_campaign(plan, {}, results)


@pytest.mark.parametrize("counts", ((8, 8), (16,)))
def test_two_level_report_never_pools_ineligible_arrival_counts_or_seeds(counts):
    from experiments.msd.tests.test_campaign_plan import two_source_evidence

    plan, results = two_level_fixture(evidence=two_source_evidence(counts, counts))
    report = summarize_campaign(plan, {}, results)
    assert report["coverage"] == {"supply_excluded": 4}
    for row in report["layouts"]:
        assert len(row["arrival_groups"]) == 2
        assert not any(
            group["independently_eligible"] for group in row["arrival_groups"]
        )


def fixture(*, seeds=(1, 3, 9), counts=(1,), max_atoms=1000):
    plan = expand_single_level(
        {
            "standard": "nadit.msd.standard/2",
            "aod_count": 1,
            "distances": [3],
            "factory_counts": list(counts),
            "production_seeds": list(seeds),
            "budget": {"max_atoms": max_atoms, "max_footprint_um2": None},
        },
        source_identity={"commit": "synthetic-report-fixture"},
    )
    plan["observation_policy"] = {
        "rule": "fixed synthetic pilot rule",
        "by_layout": {
            row["layout_id"]: {
                "warmup_us": 5000,
                "stop_us": 25000,
                "resolved_by": "test_fixture",
            }
            for row in plan["layouts"]
            if not row["budget_exclusions"]
        },
    }
    results = {}
    layouts = {row["layout_id"]: row for row in plan["layouts"]}
    for task in plan["tasks"]:
        layout = layouts[task["layout_id"]]
        if layout["budget_exclusions"]:
            continue
        count = 2 * task["seed"]
        metrics = {
            "schema": "nadit.production_metrics/1",
            "case_id": f"synthetic-case-{task['seed']}",
            "actual_output_error": None,
            "requested_window_us": [5000, 25000],
            "configured_atoms": layout["configured_atoms"],
            "occupied_footprint_area_um2": layout["occupied_bounding_area_um2"],
            "requested_window_complete": True,
            "window_status": "complete",
            "actual_observation_us": 20000,
            "all_loaded_traces_validated": True,
            "accepted_outputs": count,
            "delivered_outputs": count,
            "delivered_outputs_per_second": count * 50,
            "startup_deliverable_latency_us": 1000 * task["seed"],
            "outputs": [{"token_id": f"synthetic-output-{i}"} for i in range(count)],
            "per_accepted_output": {
                "configured_atom_time_us": 100 / count,
                "occupied_bbox_area_time_um2_us": 200 / count,
                "idle_atom_time_us": 80 / count,
                "transport_elapsed_us": 3 / count,
                "movement_distance_atom_um": 7 / count,
            },
        }
        case = {
            "case_id": metrics["case_id"],
            "seed": task["seed"],
            "duration_us": 26000,
            "execution": {
                "calls": [
                    {
                        "invocation_id": "synthetic-call",
                        "component_id": "synthetic.component",
                        "participant_blocks": ["factory0/W1"],
                        "start_us": 0,
                        "action_end_us": 100,
                        "results_ready_us": 100,
                        "shared_resources": ["aod:transport"],
                        "joint_group_key": "synthetic-group",
                        "joint_trace_sha256": "1" * 64,
                    }
                ]
            },
        }
        policy = plan["observation_policy"]["by_layout"][task["layout_id"]]
        results[task["task_id"]] = {
            **{
                key: task[key]
                for key in ("layout_id", "seed", "config_sha256", "source_sha256")
            },
            "trajectory_id": task["task_id"],
            "observation_policy_sha256": canonical_hash(policy),
            "metrics": metrics,
            "case": case,
            "case_sha256": canonical_hash(case),
            "software_times_seconds": {
                "cold_calibration": 10,
                "cache_load": 2,
                "fast_execution": 0.1,
                "validation": 0.2,
                "export": 0.3,
            },
            "artifacts": {
                "scope": "test_fixture",
                "trace": "saved-synthetic-trace-reference.json",
            },
        }
    return plan, results


def test_partial_campaign_reports_conditional_seed_ci_and_explicit_coverage(tmp_path):
    plan, results = fixture()
    tasks = plan["tasks"]
    states = {task["task_id"]: {"status": "complete"} for task in tasks[:2]}
    report = summarize_campaign(plan, states, results, output_dir=tmp_path)
    assert report["status"] == "partial"
    assert report["campaign_complete"] is False
    assert report["coverage"] == {"complete": 2, "not_run": 1}
    layout = report["layouts"][0]
    assert layout["valid_production_seeds"] == [1, 3]
    rate = layout["statistics"]["steady_deliverable_throughput_per_s"]
    assert rate["n"] == 2 and rate["mean"] == 200
    # df=1 Student-t 97.5% quantile is 12.706204736; SEM of [100,300] is 100.
    assert rate["confidence_interval_95"] == pytest.approx(
        [-1070.6204736, 1470.6204736]
    )
    assert layout["software_times"]["cold_calibration"] == {
        "observed_task_time_sum_seconds": 20,
        "n_recorded": 2,
        "n_missing": 1,
    }
    assert report["actual_output_error"] is None
    folder = tmp_path / "representatives" / layout["layout_id"]
    assert (
        json.loads((folder / "case.json").read_text())
        == results[tasks[0]["task_id"]]["case"]
    )
    assert "synthetic-call" in (folder / "schedule.csv").read_text()
    references = json.loads((folder / "trace-references.json").read_text())
    assert references["joint_trace_sha256"] == ["1" * 64]
    assert references["native_action_schedule"]["status"] == "not_provided"
    assert not (folder / "native-action-schedule.csv").exists()
    saved = (tmp_path / "summary.json").read_bytes()
    summarize_campaign(
        plan, dict(reversed(list(states.items()))), results, output_dir=tmp_path
    )
    assert (tmp_path / "summary.json").read_bytes() == saved


def test_zero_output_seed_is_included_but_missing_startup_is_not_zero_filled():
    plan, results = fixture(seeds=(1, 3))
    row = results[plan["tasks"][1]["task_id"]]["metrics"]
    row.update(
        accepted_outputs=0,
        delivered_outputs=0,
        delivered_outputs_per_second=0,
        outputs=[],
        startup_deliverable_latency_us=None,
        per_accepted_output={},
    )
    report = summarize_campaign(
        plan, {task["task_id"]: "complete" for task in plan["tasks"]}, results
    )
    assert report["campaign_complete"] is True
    assert report["coverage"] == {"complete": 1, "zero_output": 1}
    stats = report["layouts"][0]["statistics"]
    assert stats["steady_deliverable_throughput_per_s"]["mean"] == 50
    assert stats["startup_deliverable_latency_us"]["n"] == 1
    assert stats["startup_deliverable_latency_us"]["missing_values"] == 1
    assert stats["startup_deliverable_latency_us"]["confidence_interval_95"] is None


def test_failed_windows_and_software_failures_do_not_enter_seed_means():
    plan, results = fixture()
    tasks = plan["tasks"]
    metrics = results[tasks[1]["task_id"]]["metrics"]
    metrics.update(
        requested_window_complete=False,
        window_status="failed",
        actual_observation_us=10000,
        delivered_outputs_per_second=None,
    )
    report = summarize_campaign(
        plan,
        {
            tasks[0]["task_id"]: "complete",
            tasks[1]["task_id"]: "complete",
            tasks[2]["task_id"]: {"status": "timeout", "reason": "worker deadline"},
        },
        results,
    )
    assert report["status"] == "completed_with_failures"
    assert report["coverage"] == {"complete": 1, "failed": 2}
    assert (
        report["layouts"][0]["statistics"]["steady_deliverable_throughput_per_s"][
            "mean"
        ]
        == 100
    )


def test_unresolved_pilot_and_budget_exclusions_remain_visible_without_loading():
    plan, _ = fixture(seeds=(1,), counts=(1, 2), max_atoms=150)
    plan.pop("observation_policy")

    def forbidden(task):
        pytest.fail("Pending/budget tasks must not load a result")

    report = summarize_campaign(plan, {}, forbidden)
    assert len(report["layouts"]) == 3
    assert report["coverage"] == {"budget_excluded": 2, "not_run": 1}
    assert all(row["observation_policy"] is None for row in report["layouts"])
    assert all(row["valid_seed_count"] == 0 for row in report["layouts"])
    assert all(
        row["common_budget"] == plan["configuration"]["budget"]
        for row in report["layouts"]
    )


@pytest.mark.parametrize(
    "field",
    (
        "trajectory_id",
        "layout_id",
        "seed",
        "config_sha256",
        "source_sha256",
        "observation_policy_sha256",
    ),
)
def test_stale_result_identity_or_policy_is_rejected(field):
    plan, results = fixture(seeds=(1,))
    identity = plan["tasks"][0]["task_id"]
    results[identity][field] = "stale"
    with pytest.raises(ValueError):
        summarize_campaign(plan, {identity: "complete"}, results)


@pytest.mark.parametrize(
    "problem", ("task", "status", "unknown_status", "window", "rate", "output")
)
def test_duplicate_and_inconsistent_campaign_evidence_rejected(problem):
    plan, results = fixture(seeds=(1,))
    identity = plan["tasks"][0]["task_id"]
    status = {identity: "complete"}
    if problem == "task":
        plan["tasks"].append(deepcopy(plan["tasks"][0]))
    elif problem == "status":
        status = [{"trajectory_id": identity, "status": "complete"}] * 2
    elif problem == "unknown_status":
        status["not-a-trajectory"] = "failed"
    elif problem == "window":
        results[identity]["metrics"]["requested_window_us"] = [5000, 25001]
    elif problem == "rate":
        results[identity]["metrics"]["delivered_outputs_per_second"] = 1
    else:
        metrics = results[identity]["metrics"]
        metrics["outputs"].append(deepcopy(metrics["outputs"][0]))
    with pytest.raises(ValueError):
        summarize_campaign(plan, status, results)


def test_optional_plots_use_saved_layout_and_case_without_physical_execution(tmp_path):
    plan, results = fixture(seeds=(1,))
    identity = plan["tasks"][0]["task_id"]
    summarize_campaign(
        plan, {identity: "complete"}, results, output_dir=tmp_path, plots=True
    )
    assert (tmp_path / "summary.json").is_file()
    assert (tmp_path / "scaling-distance.png").is_file()
    assert (tmp_path / "scaling-factory_count.png").is_file()
    folder = tmp_path / "representatives" / plan["layouts"][0]["layout_id"]
    assert (folder / "layout.png").is_file()
    assert (folder / "schedule.png").is_file()


@pytest.mark.parametrize(
    "problem", ("missing_seed", "missing_layout", "stale_task", "budget")
)
def test_report_cannot_silently_shrink_or_relax_the_frozen_campaign(problem):
    plan, results = fixture(counts=(1, 2))
    if problem == "missing_seed":
        plan["tasks"].pop()
    elif problem == "missing_layout":
        plan["layouts"].pop()
    elif problem == "stale_task":
        plan["tasks"][0]["task_id"] = "stale-id"
    else:
        plan["layouts"][0]["budget_exclusions"] = ["max_atoms"]
    with pytest.raises(ValueError):
        summarize_campaign(plan, {}, results)


def test_completed_schedule_without_actual_trace_references_is_rejected():
    plan, results = fixture(seeds=(1,))
    identity = plan["tasks"][0]["task_id"]
    case = results[identity]["case"]
    case["execution"]["calls"][0].pop("joint_trace_sha256")
    results[identity]["case_sha256"] = canonical_hash(case)
    with pytest.raises(ValueError, match="TRACE_REFERENCES"):
        summarize_campaign(plan, {identity: "complete"}, results)


@pytest.mark.parametrize(
    ("status", "category", "terminal"),
    [
        ("ok", "complete", True),
        ("software_error", "failed", True),
        ("budget_exceeded", "budget_exceeded", True),
        ("blocked", "not_run_dependency", True),
        ("pending", "not_run", False),
    ],
)
def test_native_runner_statuses_preserve_failure_budget_and_dependency_reasons(
    status, category, terminal
):
    plan, results = fixture(seeds=(1,))
    identity = plan["tasks"][0]["task_id"]
    report = summarize_campaign(
        plan,
        {identity: {"status": status, "reason": "original runner reason"}},
        results,
    )
    assert report["coverage"] == {category: 1}
    assert report["all_tasks_terminal"] is terminal
    assert report["trajectories"][0]["reason"] == "original runner reason"
    assert report["campaign_complete"] is (status == "ok")


def test_outer_worker_ok_does_not_override_recorded_trajectory_failure():
    plan, results = fixture(seeds=(1,))
    identity = plan["tasks"][0]["task_id"]
    results[identity]["metrics"]["failures"] = [
        {"code": "input_supply_exhausted", "at_us": 26000}
    ]
    report = summarize_campaign(plan, {identity: "ok"}, results)
    assert report["coverage"] == {"failed": 1}
    assert report["valid_trajectories"] == 0


def native_fixture(tmp_path, *, unique=1, repeats=2):
    """Saved hand-action evidence; no physical compilation or fabricated exporter events."""
    plan, results = fixture(seeds=(1,))
    case, world, source_traces = activity_fixture()
    task = plan["tasks"][0]
    identity = task["task_id"]
    records, traces = {}, {}
    for index in range(unique):
        trace = deepcopy(next(iter(source_traces.values())))
        trace["validation"]["scope"] = f"synthetic-contract-fixture-{index}"
        key = canonical_hash(trace)
        path = tmp_path / f"trace-{index}.json"
        path.write_text(json.dumps(trace), encoding="utf-8")
        records[f"group{index}"] = {"trace_sha256": key, "trace_path": str(path)}
        traces[key] = trace
    keys = list(traces)
    waves, calls = [], []
    for index in range(unique * repeats):
        start, end = index * 12, index * 12 + 8
        invocations = [f"wave{index}/member{member}" for member in range(2)]
        key = keys[index % unique]
        waves.append(
            {
                "batch_id": f"wave{index}",
                "start_us": start,
                "end_us": end,
                "invocations": invocations,
            }
        )
        calls.extend(
            {
                "invocation_id": invocation,
                "component_id": "synthetic.component",
                "participant_blocks": [f"factory0/W{member + 1}"],
                "start_us": start,
                "action_end_us": end,
                "results_ready_us": end,
                "joint_trace_sha256": key,
                "joint_group_key": f"group{index % unique}",
            }
            for member, invocation in enumerate(invocations)
        )
    case["seed"] = task["seed"]
    case["duration_us"] = max(24, unique * repeats * 12)
    case["execution"]["waves"], case["execution"]["calls"], case["calls"] = (
        waves,
        calls,
        calls,
    )
    metrics = summarize_production(case, world, traces, stop_us=24)
    policy = plan["observation_policy"]["by_layout"][task["layout_id"]]
    policy.update(warmup_us=0, stop_us=24)
    result = results[identity]
    result.update(
        case=case,
        case_sha256=canonical_hash(case),
        metrics=metrics,
        observation_policy_sha256=canonical_hash(policy),
        calibration_records=records,
    )
    return plan, results


def test_native_schedule_streams_shared_actions_once_per_wave_and_reuses_trace_templates(
    tmp_path, monkeypatch
):
    from experiments.msd import campaign_report

    plan, results = native_fixture(tmp_path, unique=5, repeats=2)
    identity = plan["tasks"][0]["task_id"]
    original = campaign_report.derive_activity
    derived = []

    def counted(document):
        derived.append(canonical_hash(document))
        return original(document)

    monkeypatch.setattr(campaign_report, "derive_activity", counted)
    output = tmp_path / "report"
    summarize_campaign(plan, {identity: "ok"}, results, output_dir=output)
    folder = output / "representatives" / plan["layouts"][0]["layout_id"]
    with (folder / "native-action-schedule.csv").open(
        encoding="utf-8", newline=""
    ) as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 30  # 3 saved actions x 10 waves, not x 2 member receipts.
    assert len(derived) == len(set(derived)) == 5
    assert [float(row["global_start_us"]) for row in rows[:6]] == [0, 4, 6, 12, 16, 18]
    assert [float(row["global_end_us"]) for row in rows[:3]] == [4, 6, 8]
    assert [row["kind"] for row in rows[:3]] == ["Rotation", "Wait", "Rotation"]
    assert rows[0]["resource"] == "channel:local"
    assert len(json.loads(rows[0]["atom_ids"])) == 2
    assert json.loads(rows[1]["atom_ids"]) == []
    references = json.loads((folder / "trace-references.json").read_text())
    assert references["native_action_schedule"]["row_count"] == 30
    assert set(references["trace_paths"]) == set(derived)
    assert all(paths for paths in references["trace_paths"].values())


@pytest.mark.parametrize("problem", ("hash", "duration"))
def test_native_schedule_rejects_trace_hash_or_wave_duration_mismatch(
    tmp_path, problem
):
    plan, results = native_fixture(tmp_path)
    identity = plan["tasks"][0]["task_id"]
    result = results[identity]
    if problem == "hash":
        path = next(iter(result["calibration_records"].values()))["trace_path"]
        from pathlib import Path

        trace = json.loads(Path(path).read_text())
        trace["validation"]["scope"] = "tampered"
        Path(path).write_text(json.dumps(trace), encoding="utf-8")
    else:
        case = result["case"]
        case["execution"]["waves"][0]["end_us"] += 1
        for call in case["execution"]["calls"][:2]:
            call["action_end_us"] += 1
            call["results_ready_us"] += 1
        result["case_sha256"] = canonical_hash(case)
    with pytest.raises(ValueError, match="NATIVE_TRACE"):
        summarize_campaign(
            plan, {identity: "ok"}, results, output_dir=tmp_path / "report"
        )
    folder = tmp_path / "report" / "representatives" / plan["layouts"][0]["layout_id"]
    assert not (folder / "native-action-schedule.csv").exists()
