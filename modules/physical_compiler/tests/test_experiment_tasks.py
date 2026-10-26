"""Dependency tasks reuse isolated workers, durable journals and bounded retries."""

import errno
import json
import sys
import time
from pathlib import Path

import pytest

from nadit_physical_compiler.experiments import journal, runner
from nadit_physical_compiler.provenance import canonical_hash


def task(mode: str, **payload: object) -> dict:
    body = {
        "kind": "msd.fixture",
        "payload": {"mode": mode, **payload},
        "dependencies": [],
        "timeout_s": 5,
        "max_attempts": 2,
        "memory_bytes": 512 * 1024**2,
    }
    return {"task_id": canonical_hash(body), **body}


def plan(*tasks: dict) -> dict:
    return {
        "schema": "nadit.task_plan/1",
        "tasks": list(tasks),
        "source_paths": [],
        "budget": {"campaign_timeout_s": 20, "max_storage_bytes": 20_000_000},
    }


def windows_denied(path, code=5):
    error = PermissionError(
        errno.EACCES, "synthetic Windows file sharing denial", str(path)
    )
    if code is not None:
        error.winerror = code
    return error


def test_atomic_replace_retains_complete_old_target_until_transient_denial_clears(
    tmp_path, monkeypatch
):
    path = tmp_path / "campaign_status.json"
    path.write_text('{"old":true}', encoding="utf-8")
    original = Path.replace
    calls, sleeps = [], []

    def replace_temporary(temporary, target):
        calls.append(temporary.read_bytes())
        assert json.loads(path.read_text()) == {"old": True}
        if len(calls) < 3:
            raise windows_denied(path)
        return original(temporary, target)

    monkeypatch.setattr(journal, "_WINDOWS", True, raising=False)
    monkeypatch.setattr(Path, "replace", replace_temporary)
    monkeypatch.setattr(time, "sleep", sleeps.append)
    journal.write_json(path, {"new": [1, 2]})
    assert len(calls) == 3 and len(set(calls)) == 1
    assert sleeps == [0.01, 0.02]
    assert json.loads(path.read_text()) == {"new": [1, 2]}
    assert not path.with_suffix(".json.tmp").exists()


def test_atomic_replace_releases_existing_reader_without_nonatomic_delete(
    tmp_path, monkeypatch
):
    """A real Windows reader lacks delete sharing; POSIX may replace immediately."""
    path = tmp_path / "campaign_status.json"
    path.write_text('{"old":true}', encoding="utf-8")
    held_reader = path.open("rb")
    sleeps = []

    def release_reader(delay):
        sleeps.append(delay)
        assert json.loads(path.read_text()) == {"old": True}
        assert json.loads(path.with_suffix(".json.tmp").read_text()) == {"new": True}
        held_reader.close()

    monkeypatch.setattr(time, "sleep", release_reader)
    try:
        journal.write_json(path, {"new": True})
        assert json.loads(path.read_text()) == {"new": True}
        assert sleeps == ([0.01] if sys.platform == "win32" else [])
    finally:
        held_reader.close()


@pytest.mark.parametrize("winerror", [5, 32, 33, None])
def test_persistent_windows_permission_error_is_bounded_and_preserves_old_publication(
    tmp_path, monkeypatch, winerror
):
    path = tmp_path / "campaign_status.json"
    path.write_text('{"old":true}', encoding="utf-8")
    error = windows_denied(path, winerror)
    calls, sleeps = [], []

    def deny(*args):
        calls.append(True)
        raise error

    monkeypatch.setattr(journal, "_WINDOWS", True, raising=False)
    monkeypatch.setattr(Path, "replace", deny)
    monkeypatch.setattr(time, "sleep", sleeps.append)
    with pytest.raises(PermissionError) as caught:
        journal.write_json(path, {"new": True})
    assert caught.value is error and len(calls) == 6
    assert sleeps == [0.01, 0.02, 0.04, 0.08, 0.16]
    assert sum(sleeps) == pytest.approx(0.31)
    assert json.loads(path.read_text()) == {"old": True}
    assert json.loads(path.with_suffix(".json.tmp").read_text()) == {"new": True}


@pytest.mark.parametrize("windows,code", [(False, errno.EACCES), (True, errno.ENOSPC)])
def test_nonwindows_or_other_io_errors_are_not_retried(
    tmp_path, monkeypatch, windows, code
):
    calls, sleeps = [], []
    error = OSError(code, "synthetic permanent I/O failure")

    def fail(*args, **kwargs):
        calls.append(True)
        raise error

    monkeypatch.setattr(journal, "_WINDOWS", windows, raising=False)
    monkeypatch.setattr(Path, "read_text", fail)
    monkeypatch.setattr(time, "sleep", sleeps.append)
    with pytest.raises(OSError) as caught:
        journal.read_text(tmp_path / "file.json")
    assert caught.value is error and calls == [True] and sleeps == []


def test_read_retry_preserves_worker_deadline_and_does_not_retry_bad_json(
    tmp_path, monkeypatch
):
    path = tmp_path / "worker.started.json"
    original = Path.read_text
    calls, sleeps = [], []

    def deny(*args, **kwargs):
        calls.append(True)
        raise windows_denied(path, None)

    monkeypatch.setattr(journal, "_WINDOWS", True, raising=False)
    monkeypatch.setattr(Path, "read_text", deny)
    monkeypatch.setattr(time, "sleep", sleeps.append)
    monkeypatch.setattr(time, "monotonic", lambda: 10.0)
    with pytest.raises(PermissionError):
        journal.read_text(path, deadline=10.005)
    assert calls == [True] and sleeps == []
    monkeypatch.setattr(Path, "read_text", original)
    path.write_text('{"broken":', encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        json.loads(journal.read_text(path))
    assert sleeps == []


def test_handshake_read_transient_permission_denial_does_not_abort_or_retry_task(
    tmp_path, executor, monkeypatch
):
    original = Path.read_text
    denied = []

    def read_handshake(path, *args, **kwargs):
        if path.name.endswith(".started.json") and not denied:
            denied.append(str(path))
            raise windows_denied(path, None)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(journal, "_WINDOWS", True, raising=False)
    monkeypatch.setattr(Path, "read_text", read_handshake)
    one = task("sleep", seconds=0.3)
    report = runner.run_task_plan(
        plan(one), tmp_path / "campaign", task_executor=executor
    )
    assert len(denied) == 1
    assert report["statuses"] == {"ok": 1}
    assert report["tasks"][one["task_id"]]["attempts"] == 1
    assert report["tasks"][one["task_id"]]["software_failures"] == 0


@pytest.fixture
def executor(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    module = tmp_path / "fixture_task_executor.py"
    module.write_text(
        """
import hashlib
import json
import os
import time
from pathlib import Path
from nadit_physical_compiler.provenance import canonical_hash

def execute_task(task):
    p=task["payload"]
    mode=p["mode"]
    if mode=="dependent" and not Path(p["marker"]).exists():
        return {"status":"needs_dependencies", "dependency_requests":[p["request"]],
                "software_seconds":{"lookup":0.01}}
    if mode in ("create", "drift"):
        Path(p["marker"]).write_text("done", encoding="utf-8")
    if mode=="create":
        return {"status":"ok", "result":{"cached":True}, "artifacts":[{
            "path":p["marker"], "hash_kind":"bytes",
            "sha256":hashlib.sha256(Path(p["marker"]).read_bytes()).hexdigest()}]}
    if mode=="late_miss" and not Path(p["once"]).exists():
        Path(p["once"]).write_text("missed", encoding="utf-8")
        return {"status":"needs_dependencies", "dependency_requests":[p["request"]]}
    if mode=="defer_once" and not Path(p["marker"]).exists():
        Path(p["marker"]).write_text("deferred", encoding="utf-8")
        return {"status":"deferred", "retry_after_s":0.01}
    if mode=="sleep":
        time.sleep(p["seconds"])
    if mode=="error":
        raise RuntimeError("fixture failure")
    if mode=="partial":
        return {"status":"software_error", "reason":"later cycle failed",
                "result":{"prior_outputs":[{"cycle":0}]}}
    if mode=="crash":
        os._exit(7)
    if mode=="large":
        return {"status":"ok", "result":{"bytes":"x"*1000000}}
    if mode=="fill":
        Path(p["marker"]).write_bytes(b"x"*p["bytes"])
        return {"status":"ok", "result":{"filled":True}}
    return {"status":"ok", "result":{"value":p.get("value", 1)},
            "software_seconds":{"execution":0.02}}
""",
        encoding="utf-8",
    )
    monkeypatch.setenv(
        "PYTHONPATH",
        str(tmp_path)
        + __import__("os").pathsep
        + __import__("os").environ.get("PYTHONPATH", ""),
    )
    monkeypatch.setattr(
        runner,
        "code_version",
        lambda **kwargs: {
            "commit": "fixture",
            "dirty": False,
            "source_hash": "fixture",
        },
    )
    monkeypatch.setattr(runner, "check_version", lambda expected: None)
    return "fixture_task_executor:execute_task"


def test_dependency_misses_deduplicate_and_resume_without_counting_twice(
    tmp_path: Path, executor: str
) -> None:
    output = tmp_path / "campaign"
    marker = str(output / "calibrated")
    child = task("create", marker=marker)
    first = task("dependent", marker=marker, request=child, value=1)
    second = task("dependent", marker=marker, request=child, value=2)
    doc = plan(first, second)
    report = runner.run_task_plan(doc, output, workers=2, task_executor=executor)
    assert report["statuses"] == {"ok": 3}
    assert report["tasks"][child["task_id"]]["attempts"] == 1
    assert report["tasks"][first["task_id"]]["software_failures"] == 0
    records = [
        json.loads(line)
        for line in (output / "task_attempts.jsonl").read_text().splitlines()
    ]
    assert any(
        record.get("software_seconds", {}).get("lookup") == 0.01 for record in records
    )
    assert all(
        record["process_wall_s"] >= record["worker_wall_s"] >= 0 for record in records
    )
    before = (output / "task_attempts.jsonl").read_bytes()
    resumed = runner.run_task_plan(doc, output, workers=2, task_executor=executor)
    assert resumed["statuses"] == report["statuses"]
    assert (output / "task_attempts.jsonl").read_bytes() == before
    for identity, row in report["tasks"].items():
        result = json.loads((output / row["result_path"]).read_text())
        assert row["result_sha256"] == canonical_hash(result)
        assert identity in (first["task_id"], second["task_id"], child["task_id"])


def test_terminal_dependency_report_runs_after_failures_without_unblocking_science(
    tmp_path: Path, executor: str
) -> None:
    failed = task("error")
    blocked = task("value", value="must_not_run")
    blocked["dependencies"] = [failed["task_id"]]
    blocked["task_id"] = canonical_hash(
        {k: v for k, v in blocked.items() if k != "task_id"}
    )
    report = task("value", value="failure_report")
    report.update(
        dependencies=[failed["task_id"], blocked["task_id"]], dependency_mode="terminal"
    )
    report["task_id"] = canonical_hash(
        {k: v for k, v in report.items() if k != "task_id"}
    )
    output = tmp_path / "campaign"
    result = runner.run_task_plan(
        plan(failed, blocked, report), output, task_executor=executor
    )
    assert result["tasks"][failed["task_id"]]["status"] == "software_error"
    assert result["tasks"][blocked["task_id"]]["status"] == "blocked"
    assert result["tasks"][report["task_id"]]["status"] == "ok"
    assert result["campaign_status"] == "failed"
    rows = [
        json.loads(row)
        for row in (output / "task_attempts.jsonl").read_text().splitlines()
    ]
    final_index = {row["task_id"]: i for i, row in enumerate(rows)}
    assert (
        final_index[report["task_id"]]
        > final_index[blocked["task_id"]]
        > final_index[failed["task_id"]]
    )


@pytest.mark.parametrize("mode", ("error", "crash", "sleep"))
def test_software_failures_retry_with_bound_and_block_only_dependents(
    tmp_path: Path, executor: str, mode: str
) -> None:
    bad = task(mode, seconds=2)
    if mode == "sleep":
        bad["timeout_s"] = 0.05
        bad["task_id"] = canonical_hash(
            {key: value for key, value in bad.items() if key != "task_id"}
        )
    dependent = task("ok", value="blocked")
    dependent["dependencies"] = [bad["task_id"]]
    dependent["task_id"] = canonical_hash(
        {key: value for key, value in dependent.items() if key != "task_id"}
    )
    good = task("ok", value="independent")
    report = runner.run_task_plan(
        plan(bad, dependent, good),
        tmp_path / "campaign",
        workers=2,
        task_executor=executor,
    )
    assert report["tasks"][bad["task_id"]]["status"] == "software_error"
    assert report["tasks"][bad["task_id"]]["software_failures"] == 2
    assert report["tasks"][dependent["task_id"]]["status"] == "blocked"
    assert report["tasks"][good["task_id"]]["status"] == "ok"


def test_deferred_work_does_not_spend_software_attempt_budget(
    tmp_path: Path, executor: str
) -> None:
    work = task("defer_once", marker=str(tmp_path / "once"))
    report = runner.run_task_plan(
        plan(work), tmp_path / "campaign", task_executor=executor
    )
    row = report["tasks"][work["task_id"]]
    assert row["status"] == "ok" and row["attempts"] == 2
    assert row["software_failures"] == 0


def test_non_ok_result_is_retained_while_dependents_are_blocked(
    tmp_path: Path, executor: str
) -> None:
    partial = task("partial")
    partial["max_attempts"] = 1
    partial["task_id"] = canonical_hash(
        {key: value for key, value in partial.items() if key != "task_id"}
    )
    dependent = task("ok", value="must not run")
    dependent["dependencies"] = [partial["task_id"]]
    dependent["task_id"] = canonical_hash(
        {key: value for key, value in dependent.items() if key != "task_id"}
    )
    output = tmp_path / "campaign"
    report = runner.run_task_plan(
        plan(partial, dependent), output, task_executor=executor
    )
    row = report["tasks"][partial["task_id"]]
    assert row["status"] == "software_error"
    assert json.loads((output / row["result_path"]).read_text())["prior_outputs"] == [
        {"cycle": 0}
    ]
    assert report["tasks"][dependent["task_id"]]["status"] == "blocked"
    assert report["campaign_status"] == "failed"


@pytest.mark.parametrize("limit", ("memory", "storage", "campaign"))
def test_resource_limits_never_publish_success(
    tmp_path: Path, executor: str, limit: str
) -> None:
    work = task("large" if limit == "storage" else "sleep", seconds=2)
    if limit == "memory":
        work["memory_bytes"] = 1
        work["task_id"] = canonical_hash(
            {key: value for key, value in work.items() if key != "task_id"}
        )
    doc = plan(work)
    if limit == "storage":
        doc["budget"]["max_storage_bytes"] = 50_000
    elif limit == "campaign":
        doc["budget"]["campaign_timeout_s"] = 0.05
    report = runner.run_task_plan(doc, tmp_path / "campaign", task_executor=executor)
    row = report["tasks"][work["task_id"]]
    assert row["status"] == "budget_exceeded"
    assert row["result_path"] is None
    assert row["reason"]


def test_source_drift_stops_before_completion_publication(
    tmp_path: Path, executor: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = tmp_path / "drift"

    def check(expected):
        if marker.exists():
            raise ValueError("Code changed during experiment")

    monkeypatch.setattr(runner, "check_version", check)
    output = tmp_path / "campaign"
    with pytest.raises(ValueError, match="Code changed"):
        runner.run_task_plan(
            plan(task("drift", marker=str(marker))), output, task_executor=executor
        )
    report = runner.status(output)
    assert report["statuses"].get("ok", 0) == 0
    assert report["campaign_status"] == "interrupted"


@pytest.mark.parametrize("damage", ("removed", "corrupt"))
def test_completed_dependency_artifacts_refresh_once_with_audit(
    tmp_path: Path,
    executor: str,
    damage: str,
) -> None:
    output = tmp_path / "campaign"
    marker = output / "cached"
    work = task("create", marker=str(marker))
    doc = plan(work)
    report = runner.run_task_plan(doc, output, task_executor=executor)
    assert report["statuses"] == {"ok": 1}
    if damage == "removed":
        marker.unlink()
    else:
        marker.write_text("corrupt", encoding="utf-8")
    refreshed = runner.run_task_plan(doc, output, task_executor=executor)
    assert refreshed["statuses"] == {"ok": 1}
    assert refreshed["tasks"][work["task_id"]]["attempts"] == 2
    audit = [
        json.loads(line)
        for line in (output / "task_invalidations.jsonl").read_text().splitlines()
    ]
    assert audit[0]["requeued"] is True
    assert (output / audit[0]["previous_completion"]["result_path"]).is_file()
    marker.unlink()
    exhausted = runner.run_task_plan(doc, output, task_executor=executor)
    assert exhausted["statuses"] == {"budget_exceeded": 1}
    assert exhausted["tasks"][work["task_id"]]["attempts"] == 2
    assert "max_artifact_refreshes" in exhausted["tasks"][work["task_id"]]["reason"]


def test_late_healthy_dependency_miss_replays_parent_without_recalibration(
    tmp_path: Path,
    executor: str,
) -> None:
    output = tmp_path / "campaign"
    child = task("create", marker=str(output / "cached"))
    parent = task("late_miss", once=str(output / "once"), request=child)
    parent["dependencies"] = [child["task_id"]]
    parent["task_id"] = canonical_hash(
        {key: value for key, value in parent.items() if key != "task_id"}
    )
    report = runner.run_task_plan(plan(child, parent), output, task_executor=executor)
    assert report["statuses"] == {"ok": 2}
    assert report["tasks"][child["task_id"]]["attempts"] == 1
    assert report["tasks"][parent["task_id"]]["attempts"] == 2


def test_discovered_dependency_does_not_rewrite_existing_large_payload(
    tmp_path: Path,
    executor: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nadit_physical_compiler.experiments import task_plan

    output = tmp_path / "campaign"
    child = task("create", marker=str(output / "cached"))
    parent = task(
        "dependent", marker=str(output / "cached"), request=child, data="x" * 100_000
    )
    written = []
    original = task_plan.write_json

    def capture(path, document):
        if path.parent.name == "task_definitions":
            written.append(path.name)
        return original(path, document)

    monkeypatch.setattr(task_plan, "write_json", capture)
    doc = plan(parent)
    first = runner.run_task_plan(doc, output, task_executor=executor)
    assert first["statuses"] == {"ok": 2}
    runner.run_task_plan(doc, output, task_executor=executor)
    assert written.count(f"{parent['task_id']}.json") == 1
    assert written.count(f"{child['task_id']}.json") == 1
    assert not (output / "task_definitions.json").exists()
    assert (output / "task_edges.jsonl").is_file()


def test_running_status_publishes_latest_storage_sample_without_rescanning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import datetime, timedelta

    from nadit_physical_compiler.experiments import task_plan

    work = task("ok")
    state = task_plan.TaskPlanState(
        task_plan.validate_plan(plan(work)),
        tmp_path,
        {"commit": "fixture", "dirty": False, "source_hash": "fixture"},
        1,
        "fixture:execute",
        lambda: None,
    )
    state.dispatched(state.ready_runs()[0])
    sampled = state.storage_bytes(force=True)
    assert sampled > 0
    monkeypatch.setattr(
        task_plan.os,
        "walk",
        lambda *args, **kwargs: pytest.fail("publication rescanned storage"),
    )
    state._record(work["task_id"], {"status": "ok"}, terminal=True)
    report = task_plan.task_status(tmp_path)
    assert report["campaign_status"] == "running"
    assert report["peak_observed_storage_bytes"] == sampled
    assert report["observed_storage_bytes"] == sampled
    assert datetime.fromisoformat(
        report["storage_observed_at"]
    ).utcoffset() == timedelta(0)


def reserved_plan(*work):
    summary = task("ok", value="finalized")
    summary.update(
        kind="msd.summarize",
        dependency_mode="terminal",
        dependencies=[item["task_id"] for item in work],
    )
    summary["task_id"] = canonical_hash(
        {key: value for key, value in summary.items() if key != "task_id"}
    )
    document = plan(*work, summary)
    document["budget"]["campaign_timeout_s"] = 60
    document["finalization"] = {
        "task_ids": [summary["task_id"]],
        "reserve_seconds": 30,
        "reserve_bytes": 18_000_000,
    }
    return document, summary


@pytest.mark.parametrize(
    "damage",
    ("unknown_id", "success_gate", "work_kind", "time", "storage", "ordinary_consumer"),
)
def test_finalization_reserve_requires_terminal_export_tasks_inside_total_budget(
    damage,
):
    from nadit_physical_compiler.experiments.task_plan import validate_plan

    work = task("ok")
    document, summary = reserved_plan(work)
    if damage == "unknown_id":
        document["finalization"]["task_ids"] = ["absent"]
    elif damage == "time":
        document["finalization"]["reserve_seconds"] = 60
    elif damage == "storage":
        document["finalization"]["reserve_bytes"] = 20_000_000
    elif damage == "ordinary_consumer":
        follower = task("ok", value=99)
        follower["dependencies"] = [summary["task_id"]]
        follower["task_id"] = canonical_hash(
            {k: v for k, v in follower.items() if k != "task_id"}
        )
        document["tasks"].append(follower)
    else:
        if damage == "success_gate":
            summary["dependency_mode"] = "success"
        else:
            summary["kind"] = "msd.calibrate"
        summary["task_id"] = canonical_hash(
            {k: v for k, v in summary.items() if k != "task_id"}
        )
        document["finalization"]["task_ids"] = [summary["task_id"]]
    with pytest.raises(ValueError, match="[Ff]inaliz"):
        validate_plan(document)


def test_work_deadline_stops_production_but_preserves_bounded_finalizer(
    tmp_path, monkeypatch
):
    from nadit_physical_compiler.experiments import task_plan

    work = task("ok")
    document, summary = reserved_plan(work)
    state = task_plan.TaskPlanState(
        task_plan.validate_plan(document),
        tmp_path,
        {"commit": "fixture", "dirty": False, "source_hash": "fixture"},
        1,
        "fixture:execute",
        lambda: None,
    )
    monkeypatch.setattr(task_plan.time, "monotonic", lambda: state.deadline - 15)
    assert state.check_budgets(set()) is False
    assert state.completed[work["task_id"]]["status"] == "budget_exceeded"
    assert state.stop_reason is None
    assert state.work_stop_reason is not None
    ready = state.ready_runs()
    assert [row["task_id"] for row in ready] == [summary["task_id"]]
    assert state.termination_reason(summary["task_id"]) is None
    assert state.termination_reason(work["task_id"]) == state.work_stop_reason
    monkeypatch.setattr(task_plan.time, "monotonic", lambda: state.deadline + 1)
    assert state.check_budgets(set()) is True
    assert state.completed[summary["task_id"]]["status"] == "budget_exceeded"


def test_storage_reserve_finishes_summary_and_resume_does_not_repeat_work(
    tmp_path, executor, monkeypatch
):
    from nadit_physical_compiler.experiments import task_plan

    output = tmp_path / "campaign"
    fill = task("fill", marker=str(output / "payload.bin"), bytes=3_000_000)
    active = task("sleep", seconds=20)
    later = task("ok", value="must_not_run")
    later["dependencies"] = [fill["task_id"]]
    later["task_id"] = canonical_hash(
        {k: v for k, v in later.items() if k != "task_id"}
    )
    document, summary = reserved_plan(fill, active, later)
    storage_bytes = task_plan.TaskPlanState.storage_bytes

    def observe_after_publication(state, *, force=False):
        # Observe the soft crossing after the first durable completion, rather
        # than depending on OS process-exit timing. Worker I/O remains real.
        actual = storage_bytes(state, force=force)
        if fill["task_id"] not in state.completed:
            return min(actual, 2_000_000)
        return actual

    monkeypatch.setattr(
        task_plan.TaskPlanState, "storage_bytes", observe_after_publication
    )
    report = runner.run_task_plan(document, output, workers=2, task_executor=executor)
    assert report["campaign_status"] == "budget_exceeded"
    assert report["tasks"][fill["task_id"]]["status"] == "ok"
    assert report["tasks"][later["task_id"]]["status"] == "budget_exceeded"
    assert report["tasks"][active["task_id"]]["status"] == "budget_exceeded"
    assert report["tasks"][active["task_id"]]["attempts"] == 1
    assert report["tasks"][summary["task_id"]]["status"] == "ok"
    assert report["work_stop_reason"] is not None
    assert report["finalization"]["completed"] == 1
    before = (output / "task_dispatches.jsonl").read_bytes()
    resumed = runner.run_task_plan(document, output, workers=2, task_executor=executor)
    assert resumed["statuses"] == report["statuses"]
    assert (output / "task_dispatches.jsonl").read_bytes() == before
