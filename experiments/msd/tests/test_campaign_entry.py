"""Campaign entry never expands budgets or ignores frozen result identities."""

import json
import sys

import pytest
from nadit_physical_compiler.provenance import canonical_hash

from experiments.msd import campaign


def resolved_plan():
    task = {
        "kind": "msd.witness",
        "payload": {},
        "dependencies": [],
        "timeout_s": 1,
        "max_attempts": 1,
        "memory_bytes": 1024,
    }
    task["task_id"] = canonical_hash(task)
    configuration = {"budget": {"workers": 2}}
    return {
        "schema": "nadit.task_plan/1",
        "tasks": [task],
        "budget": {"campaign_timeout_s": 10, "max_storage_bytes": 1000000},
        "campaign": {
            "schema": "nadit.msd.campaign_context/1",
            "runnable": True,
            "configuration": configuration,
            "configuration_sha256": canonical_hash(configuration),
            "source_identity": {"commit": "fixture", "source_hash": "fixture"},
        },
    }


def test_entry_uses_frozen_worker_budget(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        campaign,
        "code_version",
        lambda **kw: resolved_plan()["campaign"]["source_identity"],
    )
    monkeypatch.setattr(
        campaign,
        "run_task_plan",
        lambda plan, path, **kw: calls.append(kw) or {"test_fixture": True},
    )
    assert campaign.run_resolved(resolved_plan(), tmp_path) == {"test_fixture": True}
    assert calls == [{"workers": 2}]


def test_output_directory_cannot_relocate_frozen_task_artifacts(tmp_path, monkeypatch):
    plan = resolved_plan()
    plan["campaign"]["campaign_directory"] = str(tmp_path / "frozen")
    monkeypatch.setattr(
        campaign, "code_version", lambda **kw: plan["campaign"]["source_identity"]
    )
    monkeypatch.setattr(
        campaign, "run_task_plan", lambda *a, **k: pytest.fail("unexpected dispatch")
    )
    with pytest.raises(ValueError, match="OUTPUT_LOCATION_CHANGED"):
        campaign.run_resolved(plan, tmp_path / "different")


@pytest.mark.parametrize("change", ("workers", "configuration", "readiness", "source"))
def test_unresolved_or_changed_campaign_never_dispatches(tmp_path, monkeypatch, change):
    monkeypatch.setattr(
        campaign, "run_task_plan", lambda *a, **kw: pytest.fail("unexpected dispatch")
    )
    plan = resolved_plan()
    monkeypatch.setattr(
        campaign,
        "code_version",
        lambda **kw: (
            plan["campaign"]["source_identity"]
            if change != "source"
            else {"commit": "changed"}
        ),
    )
    if change == "configuration":
        plan["campaign"]["configuration"]["budget"]["workers"] = 3
    if change == "readiness":
        plan["campaign"]["runnable"] = False
    with pytest.raises(ValueError):
        campaign.run_resolved(
            plan, tmp_path, workers=3 if change == "workers" else None
        )


def test_saved_summary_maps_trajectory_and_policy_and_checks_result_bytes(
    tmp_path, monkeypatch
):
    policy = {"warmup_us": 10, "stop_us": 20}
    task = {
        "kind": "msd.produce",
        "payload": {
            "trajectory_id": "t0",
            "layout_id": "l0",
            "observation_policy": policy,
        },
        "dependencies": [],
        "timeout_s": 1,
        "max_attempts": 1,
        "memory_bytes": 1024,
    }
    task["task_id"] = canonical_hash(task)
    (tmp_path / "task_definitions").mkdir()
    (tmp_path / "task_definitions" / f"{task['task_id']}.json").write_text(
        json.dumps(task), encoding="utf-8"
    )
    result = {"trajectory_id": "t0", "test_fixture": True}
    path = tmp_path / "result.json"
    path.write_text(json.dumps(result), encoding="utf-8")
    snapshot = {
        "tasks": {
            task["task_id"]: {
                "status": "ok",
                "result_path": "result.json",
                "result_sha256": canonical_hash(result),
            }
        }
    }
    monkeypatch.setattr(campaign, "status", lambda directory: snapshot)
    received = []
    monkeypatch.setattr(
        campaign,
        "summarize_campaign",
        lambda *args, **kwargs: received.append(args) or {"summary": True},
    )
    plan = {"campaign": {"layout_plan": {"tasks": [{"task_id": "t0"}]}}}
    assert campaign.summarize_saved(plan, tmp_path) == {"summary": True}
    actual_plan, statuses, results = received[0]
    assert actual_plan["observation_policy"] == {"by_layout": {"l0": policy}}
    assert statuses["t0"]["status"] == "ok"
    assert results["t0"] == result
    path.write_text(json.dumps({**result, "changed": True}), encoding="utf-8")
    with pytest.raises(ValueError, match="CAMPAIGN_RESULT_HASH_MISMATCH"):
        campaign.summarize_saved(plan, tmp_path)


def test_missing_production_retains_pilot_failure_cause(tmp_path, monkeypatch):
    task = {
        "kind": "msd.layout_driver",
        "payload": {"layout_id": "l0"},
        "dependencies": [],
        "timeout_s": 1,
        "max_attempts": 1,
        "memory_bytes": 1024,
    }
    task["task_id"] = canonical_hash(task)
    (tmp_path / "task_definitions").mkdir()
    (tmp_path / "task_definitions" / f"{task['task_id']}.json").write_text(
        json.dumps(task), encoding="utf-8"
    )
    monkeypatch.setattr(
        campaign,
        "status",
        lambda path: {
            "tasks": {
                task["task_id"]: {
                    "status": "blocked",
                    "reason": "pilot exceeded memory budget",
                }
            }
        },
    )
    captured = []
    monkeypatch.setattr(
        campaign, "summarize_campaign", lambda *a, **k: captured.append(a) or {}
    )
    campaign.summarize_saved(
        {
            "campaign": {
                "layout_plan": {"tasks": [{"task_id": "trajectory", "layout_id": "l0"}]}
            }
        },
        tmp_path,
    )
    row = captured[0][1]["trajectory"]
    assert row["status"] == "blocked"
    assert row["reason"]["cause"] == "pilot exceeded memory budget"


def test_summary_does_not_parse_unrelated_calibration_worlds(tmp_path, monkeypatch):
    monkeypatch.setattr(
        campaign,
        "status",
        lambda _: {"tasks": {"calibration": {"kind": "msd.calibrate", "status": "ok"}}},
    )
    monkeypatch.setattr(
        campaign, "summarize_campaign", lambda *a, **k: {"complete": True}
    )
    assert campaign.summarize_saved(
        {"campaign": {"layout_plan": {"tasks": []}}}, tmp_path
    ) == {"complete": True}


def test_multistage_summary_keeps_missing_stage_visible(tmp_path, monkeypatch):
    monkeypatch.setattr(campaign, "status", lambda _: {"tasks": {}})
    monkeypatch.setattr(
        campaign,
        "summarize_campaign",
        lambda *a, **k: {"campaign_complete": True, "status": "complete"},
    )
    report = campaign.summarize_saved(
        {
            "campaign": {
                "scope": "single_and_two_level",
                "layout_plan": {"tasks": []},
                "configuration": {"two_level": {}},
                "source_identity": {"fixture": True},
            }
        },
        tmp_path,
    )
    assert report["campaign_complete"] is False
    assert report["single_level"]["campaign_complete"] is True
    assert report["two_level"]["status"] == "not_run"


def test_multistage_summary_routes_capacity_cells_separately(tmp_path, monkeypatch):
    monkeypatch.setattr(campaign, "status", lambda _: {"tasks": {}})
    cells = {
        "tasks": [
            {"task_id": "a", "layout_id": "cap1"},
            {"task_id": "b", "layout_id": "cap2"},
        ]
    }
    monkeypatch.setattr(
        campaign, "_frozen_two_level_plan", lambda *a: cells, raising=False
    )
    seen = []

    def export(plan, statuses, results, *, output_dir, plots):
        seen.append((plan, output_dir))
        return {"campaign_complete": True, "status": "complete"}

    monkeypatch.setattr(campaign, "summarize_campaign", export)
    result = campaign.summarize_saved(
        {
            "campaign": {
                "scope": "single_and_two_level",
                "layout_plan": {"tasks": []},
                "configuration": {"two_level": {}},
                "source_identity": {"fixture": True},
            }
        },
        tmp_path,
    )
    assert result["campaign_complete"]
    assert seen[1][0]["tasks"] == cells["tasks"]
    assert [folder.relative_to(tmp_path).as_posix() for _, folder in seen] == [
        "report/single-level",
        "report/two-level",
    ]


def test_saved_arrivals_freeze_candidates_and_export_supply_exclusions(
    tmp_path, monkeypatch
):
    from experiments.msd.campaign_driver import _task
    from experiments.msd.tests.test_campaign_arrivals import save_result, saved_campaign
    from experiments.msd.tests.test_campaign_driver import multistage_configuration
    from experiments.msd.two_level_campaign import advance_two_level

    single, saved = saved_campaign(tmp_path)
    # The activity fixture omits display-only carrier bindings. Supply them for
    # this additional real export path without weakening the export contract.
    for _task_record, result, completion in saved:
        for call in result["case"]["execution"]["calls"]:
            member = int(call["invocation_id"].rsplit("member", 1)[1])
            call["participant_blocks"] = [f"factory0/W{member + 1}"]
        result["case_sha256"] = canonical_hash(result["case"])
        save_result(tmp_path, result, completion)
    config = multistage_configuration()
    stage = _task(
        "msd.two_level_driver",
        {
            "campaign_directory": str(tmp_path),
            "single_level_plan": single,
            "configuration": config,
            "source_identity": single["source_identity"],
            "dependencies": {
                "actions": {"fixture": True},
                "probabilities": {"fixture": True},
            },
            "allocation": {"stage_worker_seconds": 1000},
        },
        config["budget"],
        "export_timeout_s",
        terminal=True,
    )
    frozen = advance_two_level(stage, tmp_path)
    assert frozen["status"] == "ok" and not frozen.get("dependency_requests")
    # The real reader validates two delivered fixture outputs per seed. No N
    # multiplication or mixing seeds can turn those into fifteen available inputs.
    assert {row["status"] for row in frozen["result"]["two_level_plan"]["tasks"]} == {
        "supply_excluded"
    }
    plan = {
        "tasks": [stage],
        "campaign": {
            "scope": "single_and_two_level",
            "layout_plan": single,
            "configuration": config,
            "source_identity": single["source_identity"],
        },
    }
    monkeypatch.setattr(
        campaign,
        "status",
        lambda _: {
            "tasks": {task["task_id"]: completion for task, _, completion in saved}
        },
    )
    summary = campaign.summarize_saved(plan, tmp_path)
    assert summary["single_level"]["campaign_complete"] is True
    assert summary["two_level"]["status"] == "supply_excluded"
    assert summary["campaign_complete"] is False
    assert (tmp_path / "report/two-level/trajectory-status.csv").exists()
    candidate_path = tmp_path / "two-level/candidate-plan.json"
    corrupt = json.loads(candidate_path.read_text())
    corrupt["configuration"]["production_seeds"].append(500)
    candidate_path.write_text(json.dumps(corrupt))
    with pytest.raises(ValueError, match="FROZEN_TWO_LEVEL_SUMMARY_INPUT_MISMATCH"):
        campaign._frozen_two_level_plan(plan, tmp_path)


def test_resolve_cli_preserves_target_paths_and_refuses_overwriting_plan(
    tmp_path, monkeypatch, capsys
):
    from experiments.msd import campaign_driver, joint_cache

    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({"source_paths": [], "test_fixture": True}), encoding="utf-8"
    )
    output = tmp_path / "resolved.json"
    calls = []
    value = {"resolved_fixture": True}
    monkeypatch.setattr(
        campaign_driver, "resolve_campaign", lambda *a, **k: calls.append(k) or value
    )
    monkeypatch.setattr(
        campaign, "code_version", lambda **k: {"source_hash": "fixture"}
    )
    monkeypatch.setattr(
        joint_cache, "action_dependency_fingerprints", lambda: {"actions": "fixture"}
    )
    monkeypatch.setattr(
        joint_cache,
        "probability_dependency_fingerprints",
        lambda: {"probabilities": "fixture"},
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "campaign",
            "resolve",
            "--config",
            str(config),
            "--output",
            "/home/fixture/msd",
            "--resolved-plan",
            str(output),
        ],
    )
    campaign.main()
    assert json.loads(output.read_text()) == value
    assert calls[0]["campaign_directory"] == "/home/fixture/msd"
    campaign.main()
    value["changed"] = True
    with pytest.raises(ValueError, match="RESOLVED_PLAN_ALREADY_EXISTS"):
        campaign.main()
    assert "changed" not in json.loads(output.read_text())
