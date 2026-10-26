"""Staged scan orchestration and bounded reporting; no physical compilation."""

import json
import weakref
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from nadit_physical_compiler.experiments.journal import append, write_json
from nadit_physical_compiler.provenance import canonical_hash

from experiments.analysis import msd_two_level_scan as scan
from experiments.msd.campaign_driver import _task
from experiments.msd.campaign_report import summarize_campaign
from experiments.msd.tests.test_campaign_plan import arrival_evidence
from experiments.msd.tests.test_campaign_report import two_level_fixture


def config():
    document = json.loads(
        Path("experiments/analysis/msd-two-level-3600s.json").read_text()
    )
    document["two_level"]["candidate_rule"].update(
        distance_pairs=[[3, 3]],
        minimum_arrival_seeds=2,
        level2_counts=[1],
        grid_columns=[1],
        layout_families=["centralized"],
        production_seeds=[0, 1],
        max_candidate_layouts=1,
    )
    return document


def test_remaining_budget_does_not_grant_second_quota():
    cfg = config()
    start = datetime(2026, 1, 1, tzinfo=UTC)
    result = scan.remaining_budget(
        cfg,
        {"started_at": start.isoformat()},
        now=start + timedelta(hours=2),
        upstream_bytes=12 * 1024**3,
    )
    assert result["campaign_timeout_s"] == 22 * 3600
    assert result["max_storage_bytes"] == 38 * 1024**3
    assert result["workers"] == 4 and result["calibration_timeout_s"] == 3600
    assert cfg["budget"]["campaign_timeout_s"] == 24 * 3600
    with pytest.raises(ValueError, match="SHARED_BUDGET"):
        scan.remaining_budget(
            cfg,
            {"started_at": start.isoformat()},
            now=start + timedelta(hours=23),
            upstream_bytes=0,
        )


def test_acceptance_checks_core_bytes_and_paths_instead_of_commit_label():
    original = {
        "commit": "old",
        "dirty": False,
        "source_scope": "msd",
        "source_paths": ["reference.json"],
        "source_hash": "a" * 64,
    }
    gate = {
        "passed": True,
        "evidence_kind": "physical_two_level_delivery",
        "checks": [{"passed": True}],
        "source_identity": original,
    }
    core = {**original, "commit": "new-adapter-commit"}
    assert scan.acceptance_matches_core(gate, core)
    for change in ({"source_hash": "b" * 64}, {"dirty": True}, {"source_paths": []}):
        assert not scan.acceptance_matches_core(gate, {**core, **change})
    assert not scan.acceptance_matches_core({**gate, "passed": False}, core)


def test_scan_uses_real_planner_existing_drivers_and_3600s_rechecks(tmp_path):
    cfg = config()
    deps = {"actions": {"synthetic": "a"}, "probabilities": {"synthetic": "p"}}
    old_budget = {**cfg["budget"], "calibration_timeout_s": 300}
    old = _task(
        "msd.calibrate",
        {"dependencies": deps, "members": ["synthetic"], "cache_root": "old-cache"},
        old_budget,
        "calibration_timeout_s",
    )
    rechecks = [{"task": old, "completion_sha256": "f" * 64}]
    plan, candidates = scan.resolve_scan(
        cfg,
        arrival_evidence(),
        directory=tmp_path,
        source_identity={"synthetic": "execution"},
        dependencies=deps,
        budget=cfg["budget"],
        rechecks=rechecks,
    )
    retry, driver, summary = plan["tasks"]
    assert old["timeout_s"] == 300 and retry["timeout_s"] == 3600
    assert retry["task_id"] != old["task_id"]
    assert retry["payload"]["retry_origin"]["task_id"] == old["task_id"]
    assert driver["kind"] == "msd.two_level_layout_driver"
    assert driver["payload"]["common"]["calibration_budget"]["timeout_s"] == 3600
    assert driver["payload"]["common"]["noise_params"] == cfg["noise_params"]
    assert summary["kind"] == "msd.export"
    assert summary["dependency_mode"] == "terminal"
    assert summary["task_id"] in plan["finalization"]["task_ids"]
    assert len(candidates["layouts"]) == 2
    assert sum(t["status"] == "selection_excluded" for t in candidates["tasks"]) == 2
    assert (
        plan["scan"]["allocation"]["stage_worker_seconds"] == (86400 - 3600) * 4 - 3600
    )
    changed = deepcopy(rechecks)
    changed[0]["task"]["payload"]["dependencies"] = {"actions": {"drift": True}}
    with pytest.raises(ValueError):
        scan.resolve_scan(
            cfg,
            arrival_evidence(),
            directory=tmp_path,
            source_identity={"synthetic": "execution"},
            dependencies=deps,
            budget=cfg["budget"],
            rechecks=changed,
        )


def test_non_summary_execution_is_delegated_without_payload_edits(monkeypatch):
    seen = []
    original = {"kind": "msd.pilot", "payload": {"synthetic": True}}

    def delegate(task):
        seen.append(task)
        return {"status": "synthetic"}

    monkeypatch.setattr(scan, "execute_msd_task", delegate)
    assert scan.execute_task(original) == {"status": "synthetic"}
    assert seen == [original] and seen[0] is original


def _saved_report_fixture(folder):
    plan, results = two_level_fixture()
    budget = config()["budget"]
    native_tasks = []
    for identity, result in results.items():
        policy = plan["observation_policy"]["by_layout"][result["layout_id"]]
        task = _task(
            "msd.two_level_produce",
            {
                "layout_id": result["layout_id"],
                "trajectory_id": identity,
                "observation_policy": policy,
            },
            budget,
            "production_timeout_s",
        )
        write_json(folder / "task_definitions" / f"{task['task_id']}.json", task)
        path = f"results/{task['task_id']}.json"
        write_json(folder / path, result)
        write_json(
            folder / "task_completions" / f"{task['task_id']}.json",
            {
                "task_id": task["task_id"],
                "kind": task["kind"],
                "status": "ok",
                "attempts": 1,
                "result_path": path,
                "result_sha256": canonical_hash(result),
                "reason": None,
            },
        )
        append(folder / "task_registry.jsonl", {"task_id": task["task_id"]})
        native_tasks.append(task)
    write_json(folder / "candidate-plan.json", plan)
    write_json(
        folder / "task_plan.json",
        {
            "tasks": native_tasks,
            "scan": {
                "candidate_plan_sha256": canonical_hash(plan),
                "calibration_rechecks": [],
            },
        },
    )
    return plan, results, native_tasks


def test_bounded_report_matches_full_reference_and_exports_original_schedule(
    tmp_path, monkeypatch
):
    plan, results, _ = _saved_report_fixture(tmp_path)
    expected = summarize_campaign(plan, {key: "ok" for key in results}, results)
    original_read = scan._read
    references = []

    class TrackedResult(dict):
        pass

    def read(path):
        value = original_read(path)
        if path.parent.name == "results":
            assert not any(reference() is not None for reference in references)
            value = TrackedResult(value)
            references.append(weakref.ref(value))
        return value

    monkeypatch.setattr(scan, "_read", read)
    actual = scan.report_scan(tmp_path, plots=False)
    assert actual["coverage"] == expected["coverage"]
    assert actual["layouts"] == expected["layouts"]
    for left, right in zip(
        actual["trajectories"], expected["trajectories"], strict=True
    ):
        assert left["supply_diagnostics"] == right["supply_diagnostics"]
        assert left["valid_complete_window"] == right["valid_complete_window"]
        assert left["source_result"]["sha256"] == canonical_hash(
            results[left["trajectory_id"]]
        )
    assert len(list((tmp_path / "report/representatives").glob("*/schedule.csv"))) == 2
    assert scan.report_scan(tmp_path, plots=False) == actual
    saved = next((tmp_path / "report/representatives").glob("*/schedule.csv"))
    saved.write_text("corrupt")
    with pytest.raises(ValueError, match="PUBLISHED_REPRESENTATIVE_CHANGED"):
        scan.report_scan(tmp_path, plots=False)


def test_compaction_does_not_hide_case_hash_corruption(tmp_path):
    _, _, tasks = _saved_report_fixture(tmp_path)
    path = tmp_path / "results" / f"{tasks[0]['task_id']}.json"
    result = json.loads(path.read_text())
    result["case"]["duration_us"] += 1
    write_json(path, result)
    completion = tmp_path / "task_completions" / path.name
    record = json.loads(completion.read_text())
    record["result_sha256"] = canonical_hash(result)
    write_json(completion, record)
    with pytest.raises(ValueError, match="HASH_MISMATCH"):
        scan.report_scan(tmp_path, plots=False)


def test_live_upstream_never_starts_a_second_worker_pool(tmp_path, monkeypatch):
    config_path = Path("experiments/analysis/msd-two-level-3600s.json").resolve()
    cfg = json.loads(config_path.read_text())
    core = {
        "commit": "fixture",
        "dirty": False,
        "source_scope": "msd",
        "source_paths": sorted(cfg["server_scan"]["core_source_paths"]),
        "source_hash": "a" * 64,
    }
    original = {
        "campaign": {
            "source_identity": core,
            "configuration": {"budget": cfg["budget"]},
        }
    }
    upstream, output = tmp_path / "upstream", tmp_path / "followup"
    write_json(upstream / "plan.json", original)
    write_json(
        upstream / "manifest.json",
        {
            "code": core,
            "spec_hash": canonical_hash(original),
            "started_at": datetime.now(UTC).isoformat(),
        },
    )
    write_json(upstream / "campaign_status.json", {"status": "running"})
    gate = tmp_path / "gate.json"
    write_json(
        gate,
        {
            "passed": True,
            "evidence_kind": "physical_two_level_delivery",
            "checks": [{"synthetic": True}],
            "source_identity": core,
        },
    )
    monkeypatch.setattr(scan, "code_version", lambda **kwargs: core)
    monkeypatch.setattr(scan, "_upstream_alive", lambda path: True)

    def forbidden(*args, **kwargs):
        pytest.fail("Live upstream must not freeze arrivals or dispatch scan workers")

    monkeypatch.setattr(scan, "run_task_plan", forbidden)
    monkeypatch.setattr(scan, "freeze_arrival_evidence", forbidden)

    def stop_after_wait(seconds):
        assert seconds == 30
        state = json.loads((tmp_path / "followup-control/status.json").read_text())
        assert (
            state["status"] == "waiting_for_upstream" and state["workers_started"] == 0
        )
        raise RuntimeError("fixture ends bounded wait")

    monkeypatch.setattr(scan.time, "sleep", stop_after_wait)
    with pytest.raises(RuntimeError, match="fixture ends bounded wait"):
        scan.run_queue(config_path, upstream, upstream / "plan.json", output, gate)
    assert not output.exists()
