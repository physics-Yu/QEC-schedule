"""Queue a source-pinned L2 scan after an existing L1 campaign releases its workers.

The existing planner, dependency runner, calibration workers and statistics are
reused. Historical arrivals retain their original source; acceptance is checked
against the unchanged core source bytes, while this adapter/configuration are
also included in the execution freeze. No existing run or failure is rewritten.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
import time
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from nadit_physical_compiler.experiments.journal import (
    directory_lock,
    read_records,
    write_json,
)
from nadit_physical_compiler.experiments.runner import run_task_plan
from nadit_physical_compiler.experiments.task_plan import (
    TERMINAL,
    validate_plan,
    validate_task,
)
from nadit_physical_compiler.experiments.version import check_version, code_version
from nadit_physical_compiler.provenance import canonical_hash

from experiments.msd import campaign_report as reporting
from experiments.msd.campaign_arrivals import freeze_arrival_evidence
from experiments.msd.campaign_driver import _read, _task, _validate_configuration
from experiments.msd.campaign_plan import expand_two_level
from experiments.msd.campaign_worker import execute_task as execute_msd_task
from experiments.msd.joint_cache import (
    action_dependency_fingerprints,
    probability_dependency_fingerprints,
)
from experiments.msd.two_level_campaign import _children

ADAPTER = "experiments/analysis/msd_two_level_scan.py"
EXECUTOR = "experiments.analysis.msd_two_level_scan:execute_task"
_CLOSED = {"complete", "failed", "budget_exceeded"}


def _sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _size(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def acceptance_matches_core(gate: dict[str, Any], core: dict[str, Any]) -> bool:
    """Reuse physical evidence only for byte-identical core source, not labels."""
    old = gate.get("source_identity", {})
    return bool(
        gate.get("passed") is True
        and gate.get("evidence_kind") == "physical_two_level_delivery"
        and gate.get("checks")
        and core.get("dirty") is False
        and old.get("dirty") is False
        and old.get("source_scope") == core.get("source_scope") == "msd"
        and old.get("source_paths") == core.get("source_paths")
        and old.get("source_hash") == core.get("source_hash")
        and core.get("source_hash")
    )


def remaining_budget(
    config: dict[str, Any],
    upstream_manifest: dict[str, Any],
    *,
    now: datetime,
    upstream_bytes: int,
) -> dict[str, Any]:
    """Charge upstream wall time/storage once; never grant a second full quota."""
    budget = deepcopy(config["budget"])
    started = datetime.fromisoformat(upstream_manifest["started_at"])
    if started.tzinfo is None or now.tzinfo is None or now < started:
        raise ValueError("INVALID_SHARED_CAMPAIGN_CLOCK")
    budget["campaign_timeout_s"] -= (now - started).total_seconds()
    budget["max_storage_bytes"] -= upstream_bytes
    if (
        budget["campaign_timeout_s"] <= budget["export_reserve_s"]
        or budget["max_storage_bytes"] <= budget["export_reserve_bytes"]
    ):
        raise ValueError("SHARED_BUDGET_EXHAUSTED")
    return budget


def timeout_queries(upstream: Path) -> list[dict[str, Any]]:
    """Read only timeout completions and their exact original definitions."""
    rows = []
    for path in sorted((upstream / "task_completions").glob("*.json")):
        record = _read(path)
        if record["kind"] != "msd.calibrate" or record.get("failure_kind") != "timeout":
            continue
        task = validate_task(_read(upstream / "task_definitions" / path.name))
        if task["task_id"] != path.stem or record["task_id"] != path.stem:
            raise ValueError("UPSTREAM_TIMEOUT_IDENTITY_CHANGED")
        rows.append({"task": task, "completion_sha256": canonical_hash(record)})
    return rows


def resolve_scan(
    config: dict[str, Any],
    arrivals: dict[str, Any],
    *,
    directory: Path,
    source_identity: dict[str, Any],
    dependencies: dict[str, Any],
    budget: dict[str, Any],
    rechecks: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build frozen candidates and native tasks without executing any worker."""
    _validate_configuration(config)
    if not directory.is_absolute() or config["budget"]["calibration_timeout_s"] != 3600:
        raise ValueError("EXPLICIT_3600S_SCAN_REQUIRED")
    rule = deepcopy(config["two_level"]["candidate_rule"])
    rule.update(
        arrival_evidence_sha256=canonical_hash(arrivals),
        arrival_source_sha256=arrivals["source_sha256"],
    )
    candidates = expand_two_level(rule, arrivals, source_identity=source_identity)
    retries, lineage = [], []
    for row in rechecks:
        old = validate_task(row["task"])
        if (
            old["kind"] != "msd.calibrate"
            or old["payload"]["dependencies"] != dependencies
        ):
            raise ValueError("CALIBRATION_RECHECK_SCIENTIFIC_DEPENDENCIES_CHANGED")
        payload = deepcopy(old["payload"])
        payload["cache_root"] = str(directory / "cache")
        payload["retry_origin"] = {
            "task_id": old["task_id"],
            "completion_sha256": row["completion_sha256"],
        }
        new = _task("msd.calibrate", payload, budget, "calibration_timeout_s")
        retries.append(new)
        lineage.append({"original_task_id": old["task_id"], "task_id": new["task_id"]})
    stage_seconds = (
        budget["campaign_timeout_s"] - budget["export_reserve_s"]
    ) * budget["workers"] - sum(t["timeout_s"] for t in retries)
    if stage_seconds <= 0:
        raise ValueError("SHARED_BUDGET_EXHAUSTED_BY_CALIBRATION_RESERVE")
    effective = deepcopy(config)
    effective["budget"] = deepcopy(budget)
    drivers, allocation = _children(
        {
            "configuration": effective,
            "source_identity": source_identity,
            "dependencies": dependencies,
            "allocation": {"stage_worker_seconds": stage_seconds},
        },
        candidates,
        directory,
    )
    summary = _task(
        "msd.export",
        {"directory": str(directory), "plots": True},
        budget,
        "export_timeout_s",
        [t["task_id"] for t in [*retries, *drivers]],
        terminal=True,
    )
    plan = validate_plan(
        {
            "schema": "nadit.task_plan/1",
            "tasks": [*retries, *drivers, summary],
            "source_paths": config["source_paths"],
            "budget": {
                k: budget[k]
                for k in (
                    "campaign_timeout_s",
                    "max_storage_bytes",
                    "max_artifact_refreshes",
                )
            },
            "finalization": {
                "task_ids": [summary["task_id"]],
                "reserve_seconds": budget["export_reserve_s"],
                "reserve_bytes": budget["export_reserve_bytes"],
            },
            "scan": {
                "source_identity": source_identity,
                "configuration": effective,
                "candidate_plan_sha256": canonical_hash(candidates),
                "allocation": allocation,
                "calibration_rechecks": lineage,
            },
        }
    )
    return dict(plan), candidates


def compact_snapshot(directory: Path) -> dict[str, Any]:
    """Avoid parsing every large calibration payload merely to count task states."""
    rows = {}
    invalidations = {
        r["task_id"]: r["previous_completion"]["attempts"]
        for r in read_records(directory / "task_invalidations.jsonl")
    }
    for path in (directory / "task_completions").glob("*.json"):
        row = _read(path)
        if path.stem != row["task_id"]:
            raise ValueError("SCAN_COMPLETION_FILENAME_MISMATCH")
        state = row["status"]
        if state not in TERMINAL or (
            state == "ok" and row.get("attempts", 0) <= invalidations.get(path.stem, -1)
        ):
            state = "pending"
        rows[path.stem] = {
            k: row.get(k) for k in ("kind", "result_path", "result_sha256", "reason")
        }
        rows[path.stem]["status"] = state
    for item in read_records(directory / "task_registry.jsonl"):
        identity = item["task_id"]
        if identity not in rows:
            definition = validate_task(
                _read(directory / "task_definitions" / f"{identity}.json")
            )
            rows[identity] = {"kind": definition["kind"], "status": "pending"}
    return {"tasks": rows}


def report_scan(directory: Path, *, plots: bool) -> dict[str, Any]:
    """Validate one result at a time, keep metrics, and export representatives singly."""
    plan = _read(directory / "task_plan.json")
    candidates = _read(directory / "candidate-plan.json")
    if canonical_hash(candidates) != plan["scan"]["candidate_plan_sha256"]:
        raise ValueError("SCAN_CANDIDATE_PLAN_CHANGED")
    snapshot = compact_snapshot(directory)
    inventory, tasks = reporting._plan_inventory(candidates)
    indexed = {reporting._trajectory(t): t for t in tasks}
    statuses: dict[str, Any] = {}
    compact: dict[str, Any] = {}
    diagnostics: dict[str, Any] = {}
    files: dict[str, Any] = {}
    policies: dict[str, Any] = {}
    drivers: dict[str, Any] = {}
    for identity, row in snapshot["tasks"].items():
        if row["kind"] not in ("msd.two_level_layout_driver", "msd.two_level_produce"):
            continue
        task = validate_task(_read(directory / "task_definitions" / f"{identity}.json"))
        payload = task["payload"]
        layout = payload["layout_id"]
        if row["kind"] == "msd.two_level_layout_driver":
            if layout in drivers:
                raise ValueError("DUPLICATE_SCAN_LAYOUT_DRIVER")
            drivers[layout] = row
            continue
        trajectory = payload["trajectory_id"]
        if trajectory not in indexed or trajectory in statuses:
            raise ValueError("UNKNOWN_OR_DUPLICATE_SCAN_PRODUCTION")
        statuses[trajectory] = {**row, "trajectory_id": trajectory}
        policy = payload.get("observation_policy")
        if policy is not None:
            if layout in policies and policies[layout] != policy:
                raise ValueError("SCAN_POLICY_CHANGED")
            policies[layout] = policy
        if not row.get("result_path"):
            continue
        path = (directory / row["result_path"]).resolve()
        if not path.is_relative_to(directory.resolve()):
            raise ValueError("SCAN_RESULT_OUTSIDE_DIRECTORY")
        result = _read(path)
        if canonical_hash(result) != row["result_sha256"]:
            raise ValueError("SCAN_RESULT_HASH_MISMATCH")
        if "metrics" not in result:
            continue
        reporting._load_result(
            indexed[trajectory], inventory[layout], policy, {trajectory: result}
        )
        diagnostics[trajectory] = reporting._supply_diagnostics(
            result, inventory[layout]["buffer_capacity"]
        )
        compact[trajectory] = {
            k: result[k]
            for k in (
                "trajectory_id",
                "layout_id",
                "geometry_layout_id",
                "buffer_capacity",
                "seed",
                "config_sha256",
                "source_sha256",
                "arrival_evidence_sha256",
                "observation_policy_sha256",
                "metrics",
                "software_times_seconds",
                "artifacts",
            )
            if k in result
        }
        files[trajectory] = {
            "path": str(path),
            "sha256": row["result_sha256"],
            "has_case": result.get("case") is not None,
        }
        statuses[trajectory]["result_available"] = True
        del result
    for planned in tasks:
        identity = reporting._trajectory(planned)
        if identity not in statuses and planned["layout_id"] in drivers:
            driver = drivers[planned["layout_id"]]
            statuses[identity] = {
                "status": "blocked"
                if driver["status"] in ("software_error", "blocked", "budget_exceeded")
                else "pending",
                "reason": {"phase": "pilot", "driver": driver},
            }
    candidates["observation_policy"] = {"by_layout": policies}
    report = reporting.summarize_campaign(candidates, statuses, compact)
    for row in report["trajectories"]:
        identity = row["trajectory_id"]
        if identity in diagnostics:
            row["supply_diagnostics"] = diagnostics[identity]
            window = diagnostics[identity].get("window") or {}
            for metric, path in reporting._SUPPLY_WINDOW_METRICS.items():
                row[metric] = reporting._value(window, path)
            row["source_result"] = files[identity]
    for row in report["layouts"]:
        eligible = [
            r
            for r in report["trajectories"]
            if r["layout_id"] == row["layout_id"] and r["valid_complete_window"]
        ]
        for metric in reporting._SUPPLY_WINDOW_METRICS:
            row["statistics"][metric] = reporting._mean_ci(
                [r[metric] for r in eligible if r[metric] is not None], len(eligible)
            )
    output = directory / "report"
    reporting._export(report, candidates, {}, output)
    if plots:
        reporting.export_plots(report, candidates, {}, output)
    selected: set[str] = set()
    for row in sorted(
        report["trajectories"],
        key=lambda r: (r["status"] != "complete", r["seed"], r["trajectory_id"]),
    ):
        identity, layout = row["trajectory_id"], row["layout_id"]
        if (
            layout in selected
            or not row["valid_complete_window"]
            or not files.get(identity, {}).get("has_case")
        ):
            continue
        selected.add(layout)
        result = _read(Path(files[identity]["path"]))
        if canonical_hash(result) != files[identity]["sha256"]:
            raise ValueError("SCAN_REPRESENTATIVE_CHANGED")
        target = output / "representatives" / layout
        if target.exists():
            publication = _read(target / "publication.json")
            if publication["result_sha256"] != files[identity]["sha256"]:
                raise ValueError("SCAN_PUBLISHED_REPRESENTATIVE_CHANGED")
            for name, digest in publication["files"].items():
                saved = target / name
                if (
                    not saved.resolve().is_relative_to(target.resolve())
                    or _sha(saved) != digest
                ):
                    raise ValueError("SCAN_PUBLISHED_REPRESENTATIVE_CHANGED")
            del result
            continue
        one = {
            **report,
            "layouts": [r for r in report["layouts"] if r["layout_id"] == layout],
            "trajectories": [row],
        }
        with tempfile.TemporaryDirectory(
            prefix=".representative-", dir=output
        ) as temporary:
            temporary_path = Path(temporary)
            reporting._export(one, candidates, {identity: result}, temporary_path)
            if plots:
                reporting.export_plots(
                    one, candidates, {identity: result}, temporary_path
                )
            source = temporary_path / "representatives" / layout
            if not source.resolve().is_relative_to(
                output.resolve()
            ) or not target.resolve().is_relative_to(output.resolve()):
                raise ValueError("SCAN_REPRESENTATIVE_PATH_ESCAPES_OUTPUT")
            target.parent.mkdir(exist_ok=True)
            write_json(
                source / "publication.json",
                {
                    "result_sha256": files[identity]["sha256"],
                    "files": {
                        p.relative_to(source).as_posix(): _sha(p)
                        for p in source.rglob("*")
                        if p.is_file()
                    },
                },
            )
            source.rename(target)
        del result
    report["calibration_rechecks"] = [
        {**r, "completion": snapshot["tasks"].get(r["task_id"])}
        for r in plan["scan"]["calibration_rechecks"]
    ]
    report["report_memory_scope"] = (
        "one original result at a time; retained metrics only; representatives loaded singly"
    )
    write_json(output / "summary.json", report)
    return report


def execute_task(task: dict[str, Any]) -> dict[str, Any]:
    """Delegate all physics unchanged; add one bounded terminal report task."""
    if task["kind"] != "msd.export":
        return execute_msd_task(task)
    validate_task(task)
    started = time.perf_counter()
    directory = Path(task["payload"]["directory"])
    result = report_scan(directory, plots=task["payload"]["plots"])
    return {
        "status": "ok",
        "result": result,
        "artifacts": [
            {"path": str(p), "sha256": _sha(p), "hash_kind": "bytes"}
            for p in sorted((directory / "report").rglob("*"))
            if p.is_file()
        ],
        "software_seconds": {"export": time.perf_counter() - started},
    }


def _upstream_alive(upstream: Path) -> bool:
    pid_path = upstream / "launcher.pid"
    if not pid_path.exists():
        return False
    if not sys.platform.startswith("linux"):
        raise ValueError("SERVER_SCAN_QUEUE_REQUIRES_LINUX_PROCESS_INSPECTION")
    pid = int(pid_path.read_text().strip())
    if pid <= 0:
        raise ValueError("INVALID_UPSTREAM_LAUNCHER_PID")
    process = Path("/proc") / str(pid)
    try:
        arguments = process.joinpath("cmdline").read_bytes().split(b"\0")
        state = process.joinpath("stat").read_text().rpartition(")")[2].split()[0]
        return state != "Z" and str(upstream).encode() in arguments
    except FileNotFoundError:
        return False


def run_queue(
    config_path: Path,
    upstream: Path,
    upstream_plan_path: Path,
    output: Path,
    gate_path: Path,
) -> dict[str, Any]:
    """Wait without worker competition, freeze actual arrivals, then run the scan."""
    config, original, gate = (
        _read(config_path),
        _read(upstream_plan_path),
        _read(gate_path),
    )
    _validate_configuration(config)
    root = Path(__file__).resolve().parents[2]
    if (
        ADAPTER not in config["source_paths"]
        or config_path.resolve().relative_to(root).as_posix()
        not in config["source_paths"]
    ):
        raise ValueError("SCAN_ADAPTER_AND_CONFIG_MUST_BE_SOURCE_PINNED")
    core = code_version(
        allow_dirty=False,
        scope="msd",
        source_paths=config["server_scan"]["core_source_paths"],
    )
    if not acceptance_matches_core(gate, core):
        raise ValueError("SCAN_REQUIRES_BYTE_IDENTICAL_ACCEPTED_CORE")
    version = code_version(
        allow_dirty=False, scope="msd", source_paths=config["source_paths"]
    )
    manifest = _read(upstream / "manifest.json")
    if manifest["code"] != original["campaign"]["source_identity"] or manifest[
        "spec_hash"
    ] != canonical_hash(original):
        raise ValueError("UPSTREAM_PLAN_OR_SOURCE_CHANGED")
    for key in (
        "workers",
        "memory_bytes",
        "max_storage_bytes",
        "campaign_timeout_s",
        "max_atoms",
    ):
        if (
            config["budget"][key]
            != original["campaign"]["configuration"]["budget"][key]
        ):
            raise ValueError("SCAN_SHARED_BUDGET_CHANGED")
    identity = {
        "source_identity": version,
        "accepted_core_identity": core,
        "acceptance_sha256": canonical_hash(gate),
        "configuration_sha256": canonical_hash(config),
        "upstream_manifest_sha256": canonical_hash(manifest),
        "upstream_plan_sha256": canonical_hash(original),
        "output": str(output),
    }
    control = output.with_name(output.name + "-control")
    with directory_lock(control):
        identity_path = control / "identity.json"
        if identity_path.exists() and _read(identity_path) != identity:
            raise ValueError("SCAN_QUEUE_IDENTITY_CHANGED")
        write_json(identity_path, identity)
        status_path = control / "status.json"
        while True:
            elapsed = (
                datetime.now(UTC) - datetime.fromisoformat(manifest["started_at"])
            ).total_seconds()
            if (
                elapsed
                >= config["budget"]["campaign_timeout_s"]
                - config["budget"]["export_reserve_s"]
            ):
                state = {
                    "status": "budget_exceeded",
                    "reason": "Shared wall budget exhausted before handoff",
                }
                write_json(status_path, state)
                return state
            state = _read(upstream / "campaign_status.json")["status"]
            if state in _CLOSED and not _upstream_alive(upstream):
                break
            write_json(
                status_path,
                {
                    "status": "waiting_for_upstream",
                    "upstream_status": state,
                    "workers_started": 0,
                    "calibration_timeout_s": 3600,
                },
            )
            time.sleep(config["server_scan"]["poll_seconds"])
            check_version(version)
        resolved = output / "task_plan.json"
        if not resolved.exists():
            if output.exists():
                raise ValueError("PRESERVE_PARTIAL_SCAN_FREEZE")
            write_json(status_path, {"status": "freezing_arrivals"})
            arrivals = freeze_arrival_evidence(
                original["campaign"]["layout_plan"], upstream
            )
            dependencies = {
                "actions": action_dependency_fingerprints(),
                "probabilities": probability_dependency_fingerprints(),
            }
            rechecks = (
                timeout_queries(upstream)
                if config["server_scan"]["recheck_timed_out_calibrations"]
                else []
            )
            try:
                budget = remaining_budget(
                    config,
                    manifest,
                    now=datetime.now(UTC),
                    upstream_bytes=_size(upstream),
                )
                plan, candidates = resolve_scan(
                    config,
                    arrivals,
                    directory=output,
                    source_identity=version,
                    dependencies=dependencies,
                    budget=budget,
                    rechecks=rechecks,
                )
                final_budget = remaining_budget(
                    config,
                    manifest,
                    now=datetime.now(UTC),
                    upstream_bytes=_size(upstream),
                )
            except ValueError as error:
                if not str(error).startswith("SHARED_BUDGET"):
                    raise
                state = {"status": "budget_exceeded", "reason": str(error)}
                write_json(status_path, state)
                return state
            # Preparation spends the shared wall budget. Pilot allocation is a
            # frozen heuristic; this actual runner cap can only be tighter.
            plan["budget"]["campaign_timeout_s"] = final_budget["campaign_timeout_s"]
            plan["budget"]["max_storage_bytes"] = final_budget["max_storage_bytes"]
            output.mkdir(parents=True)
            write_json(output / "arrivals.json", arrivals)
            write_json(output / "candidate-plan.json", candidates)
            write_json(output / "requested-plan.json", plan)
        else:
            plan = _read(output / "requested-plan.json")
            if plan["scan"]["source_identity"] != version:
                raise ValueError("SCAN_RESUME_SOURCE_CHANGED")
        check_version(version)
        write_json(
            status_path,
            {
                "status": "running",
                "workers": config["budget"]["workers"],
                "calibration_timeout_s": 3600,
            },
        )
        result = run_task_plan(
            plan, output, workers=config["budget"]["workers"], task_executor=EXECUTOR
        )
        summary_path = output / "report/summary.json"
        summary = _read(summary_path) if summary_path.exists() else {}
        state = {
            "status": result["campaign_status"],
            "statuses": result["statuses"],
            "report_status": summary.get("status", "unavailable"),
            "scan_complete": summary.get("campaign_complete", False),
            "report": str(output / "report/summary.json"),
        }
        write_json(status_path, state)
        return state


def main() -> None:
    """Run a pinned queue; no implicit server paths, quotas or mixed protocols."""
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("config", "upstream", "upstream-plan", "output", "gate"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    try:
        result = run_queue(
            args.config.resolve(),
            args.upstream.resolve(),
            args.upstream_plan.resolve(),
            args.output.resolve(),
            args.gate.resolve(),
        )
    except Exception as error:
        control = args.output.resolve().with_name(args.output.name + "-control")
        write_json(
            control / "status.json",
            {"status": "interrupted", "reason": f"{type(error).__name__}: {error}"},
        )
        raise
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
