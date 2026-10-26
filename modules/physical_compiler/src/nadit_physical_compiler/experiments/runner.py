"""Bounded subprocess execution, content locks, and resumable JSONL results."""

import json
import os
import platform
import signal
import subprocess
import sys
import time
from collections import Counter
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..provenance import canonical_hash
from .costs import evaluate_models
from .journal import append, directory_lock, read_records, read_text, write_json
from .spec import Experiment, runs
from .task_plan import (
    MEMORY_POLL_S,
    TaskPlanState,
    resident_bytes,
    task_status,
    validate_plan,
)
from .version import check_version, code_version


def run_experiment(
    spec: Experiment,
    directory: Path,
    *,
    workers: int = 1,
    allow_dirty: bool = False,
    new_version: bool = False,
) -> dict[str, Any]:
    """Run each cell once with an enforced timeout; resume every completed status.

    Code changes stop the run and terminate active children. A new code version
    requires a separate version directory. Cost evaluation stays in the parent.
    """
    if workers < 1:
        raise ValueError("workers must be positive.")
    version = code_version(allow_dirty=allow_dirty)
    directory = directory.resolve()
    if new_version:
        directory = directory / "versions" / canonical_hash(version)[:16]
    with directory_lock(directory):
        expanded = runs(spec, version)
        manifest_path = directory / "manifest.json"
        spec_hash = canonical_hash(spec.document)
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest["code"] != version:
                raise ValueError("Experiment code version differs; use --new-version.")
            if manifest["spec_hash"] != spec_hash:
                raise ValueError(
                    "Experiment spec changed; use another directory "
                    "or experiment cost for new noise."
                )
        else:
            manifest = {
                "schema": "nadit.experiment-manifest/1",
                "code": version,
                "spec_hash": spec_hash,
                "suite_hash": spec.suite.sha256,
                "machine": platform.platform(),
                "cpu": platform.processor(),
                "started_at": datetime.now(UTC).isoformat(),
                "workers": workers,
                "run_count": len(expanded),
            }
            write_json(directory / "experiment.json", spec.document)
            write_json(manifest_path, manifest)
        journal = directory / "runs.jsonl"
        old = read_records(journal, repair=True)
        completed = {row["run_id"] for row in old}
        if len(completed) != len(old):
            raise ValueError("runs.jsonl contains duplicate completed run IDs.")
        pending = [run for run in expanded if run["run_id"] not in completed]
        _execute_pending(pending, spec, directory, version, workers)
        return status(directory)


def _execute_pending(
    pending: list[dict[str, Any]],
    spec: Experiment | None,
    directory: Path,
    version: dict[str, Any],
    workers: int,
    task_state: TaskPlanState | None = None,
) -> None:
    active: dict[
        str, tuple[subprocess.Popen[bytes], float, dict[str, Any], Path, Any]
    ] = {}
    costing: dict[
        Future[list[dict[str, Any]]], tuple[dict[str, Any], dict[str, Any], Path]
    ] = {}
    evaluator = (
        None
        if task_state
        else ThreadPoolExecutor(max_workers=1, thread_name_prefix="nadit-cost")
    )
    observed: dict[str, tuple[float, int]] = {}
    cursor = 0
    try:
        while (
            cursor < len(pending)
            or active
            or costing
            or (task_state is not None and task_state.unfinished)
        ):
            if task_state is None:
                check_version(version)
            else:
                if task_state.check_budgets(
                    {item[2]["task_id"] for item in active.values()}
                ):
                    cursor = len(pending)
                else:
                    pending.extend(task_state.ready_runs())
            while (
                cursor < len(pending)
                and len(active) < workers
                and len(costing) < workers
            ):
                run = pending[cursor]
                cursor += 1
                if task_state:
                    if run["task_id"] in task_state.completed:
                        continue
                    if task_state.check_budgets(
                        {item[2]["task_id"] for item in active.values()}, force=True
                    ):
                        cursor = len(pending)
                        break
                    if run["task_id"] in task_state.completed:
                        continue
                    task_state.dispatched(run)
                else:
                    job_path = directory / "jobs" / f"{run['run_id']}.json"
                    write_json(job_path, run["job"])
                request = directory / ".work" / f"{run['run_id']}.input.json"
                output = request.with_suffix(".output.json")
                if task_state:
                    output.unlink(missing_ok=True)
                write_json(request, run)
                log = request.with_suffix(".log").open("wb")
                environment = {
                    **os.environ,
                    "OMP_NUM_THREADS": "1",
                    "OPENBLAS_NUM_THREADS": "1",
                    "MKL_NUM_THREADS": "1",
                }
                launch_started = time.monotonic()
                try:
                    process = subprocess.Popen(
                        [
                            sys.executable,
                            "-m",
                            "nadit_physical_compiler.experiments.worker",
                            str(request),
                            str(output),
                        ],
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        env=environment,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                        start_new_session=task_state is not None
                        and sys.platform != "win32",
                    )
                except OSError as error:
                    log.close()
                    if task_state is None:
                        raise
                    task_state.finish(
                        run,
                        _task_failure(
                            "software_error",
                            str(error),
                            time.monotonic() - launch_started,
                            "launch",
                        ),
                        output,
                    )
                    continue
                active[run["run_id"]] = (
                    process,
                    launch_started if task_state is not None else time.monotonic(),
                    run,
                    output,
                    log,
                )
                observed[run["run_id"]] = (float("-inf"), 0)
            for run_id, (process, started, run, output, log) in tuple(active.items()):
                elapsed = time.monotonic() - started
                if task_state:
                    timeout = run["task"]["timeout_s"]
                else:
                    assert spec is not None
                    timeout = spec.budget["timeout_s"]
                timed_out = process.poll() is None and elapsed >= timeout
                budget_failure = (
                    task_state.termination_reason(run["task_id"])
                    if task_state
                    else None
                )
                if task_state and process.poll() is None:
                    sampled_at, peak = observed[run_id]
                    if time.monotonic() - sampled_at >= MEMORY_POLL_S:
                        pid = process.pid
                        handshake = output.with_suffix(".started.json")
                        if handshake.exists():
                            started_doc = json.loads(
                                read_text(handshake, deadline=started + timeout)
                            )
                            if (
                                started_doc.get("run_id") == run_id
                                and type(started_doc.get("pid")) is int
                            ):
                                pid = started_doc["pid"]
                        usage = resident_bytes(pid)
                        peak = max(peak, usage or 0)
                        observed[run_id] = (time.monotonic(), peak)
                        if peak > run["task"]["memory_bytes"]:
                            budget_failure = (
                                "memory_bytes exceeded by observed worker RSS"
                            )
                    # I/O retry time spends the existing budget; never restart or
                    # extend the worker clock after reading its PID handshake.
                    elapsed = time.monotonic() - started
                    timed_out = timed_out or elapsed >= timeout
                if timed_out or budget_failure:
                    _terminate_worker(process, tree=task_state is not None)
                if process.poll() is None:
                    continue
                log.close()
                if task_state:
                    if budget_failure:
                        record = _task_failure(
                            "budget_exceeded",
                            budget_failure,
                            elapsed,
                            "resource_budget",
                        )
                    elif timed_out:
                        record = _task_failure(
                            "software_error",
                            "Worker exceeded timeout_s",
                            elapsed,
                            "timeout",
                        )
                    elif process.returncode or not output.exists():
                        record = _task_failure(
                            "software_error",
                            f"Worker exited {process.returncode}; see .work log",
                            elapsed,
                            "worker_exit",
                        )
                    else:
                        try:
                            record = json.loads(read_text(output))
                            if not isinstance(record, dict):
                                raise ValueError("Worker record must be an object")
                        except (OSError, ValueError) as error:
                            record = _task_failure(
                                "software_error", str(error), elapsed, "invalid_record"
                            )
                    record["process_wall_s"] = time.monotonic() - started
                    record.setdefault("worker_wall_s", None)
                    record["resource_usage"] = {
                        **record.get("resource_usage", {}),
                        "peak_observed_worker_rss_bytes": max(
                            observed[run_id][1],
                            record.get("resource_usage", {}).get(
                                "peak_observed_worker_rss_bytes", 0
                            ),
                        ),
                        "termination_reason": budget_failure
                        or ("timeout_s" if timed_out else None),
                    }
                    task_state.finish(run, record, output)
                    del active[run_id]
                    continue
                check_version(version)
                if timed_out:
                    record = _failure(
                        run, "timeout", "Worker exceeded timeout_s", elapsed
                    )
                elif process.returncode or not output.exists():
                    record = _failure(
                        run,
                        "compile_error",
                        f"Worker exited {process.returncode}; see .work log",
                        elapsed,
                    )
                else:
                    record = json.loads(read_text(output))
                document = record.pop("result", None)
                if document is not None and record["status"] == "ok":
                    assert evaluator is not None and spec is not None
                    future = evaluator.submit(evaluate_models, document, spec.cost)
                    costing[future] = record, document, output
                else:
                    assert spec is not None
                    _finish(record, document, output, spec, directory, version)
                del active[run_id]
            for future, (record, document, output) in tuple(costing.items()):
                if not future.done():
                    continue
                try:
                    record["cost"] = future.result()
                except Exception as error:
                    record["cost"] = [{"status": "cost_error", "reason": str(error)}]
                assert spec is not None
                _finish(record, document, output, spec, directory, version)
                del costing[future]
            if active or costing or (task_state is not None and task_state.unfinished):
                time.sleep(0.05)
    finally:
        for process, _, _, _, log in active.values():
            _terminate_worker(process, tree=task_state is not None)
            log.close()
        if evaluator is not None:
            evaluator.shutdown(wait=True, cancel_futures=True)


def _terminate_worker(process: subprocess.Popen[bytes], *, tree: bool) -> None:
    """Stop only a process/group created by this runner and reap its handle."""
    if process.poll() is None:
        if tree:
            if sys.platform == "win32":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            else:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        else:
            process.kill()
    process.wait()


def _task_failure(
    status_name: str, reason: str, elapsed: float, kind: str
) -> dict[str, Any]:
    return {
        "status": status_name,
        "reason": reason,
        "worker_wall_s": None,
        "process_wall_s": elapsed,
        "failure_kind": kind,
    }


def run_task_plan(
    document: dict[str, Any],
    directory: Path,
    *,
    workers: int = 1,
    allow_dirty: bool = False,
    task_executor: str = "experiments.msd.campaign_worker:execute_task",
) -> dict[str, Any]:
    """Execute resumable dependency tasks using the existing isolated worker loop.

    Task IDs hash immutable definitions; discovered dependencies live in a separate
    durable graph. Deferrals/misses do not spend software retry budgets. The
    executor is an explicit importable module:function adapter, retained in the
    frozen manifest. Source checks occur at dispatch/publication, not idle polls.
    Memory/storage limits are sampled, not hard quotas. Campaign wall time starts
    at first launch and includes downtime. Raises ValueError for input/source drift.
    """
    if type(workers) is not int or workers < 1:
        raise ValueError("workers must be positive")
    if (
        not isinstance(task_executor, str)
        or task_executor.count(":") != 1
        or not all(
            part and all(name.isidentifier() for name in part.split("."))
            for part in task_executor.split(":")
        )
    ):
        raise ValueError("task_executor must be an importable module:function")
    document = validate_plan(document)
    version = code_version(
        allow_dirty=allow_dirty, scope="msd", source_paths=document["source_paths"]
    )
    directory = directory.resolve()
    with directory_lock(directory):
        state = TaskPlanState(
            document,
            directory,
            version,
            workers,
            task_executor,
            lambda: check_version(version),
        )
        try:
            _execute_pending([], None, directory, version, workers, task_state=state)
        except BaseException as error:
            state.close(interrupted=f"{type(error).__name__}: {error}")
            raise
        else:
            state.close()
        return task_status(directory)


def _finish(
    record: dict[str, Any],
    document: dict[str, Any] | None,
    output: Path,
    spec: Experiment,
    directory: Path,
    version: dict[str, Any],
) -> None:
    failed = record["status"] != "ok" or any(
        cost.get("status") != "ok" for cost in record["cost"]
    )
    keep = spec.store == "all" or (spec.store == "failures" and failed)
    run_id = record["run_id"]
    if document is not None and keep:
        relative = f"results/{run_id}.json"
        document["cost"] = record["cost"]
        write_json(directory / relative, document)
        record["provenance"]["result_path"] = relative
    record["provenance"]["job_path"] = f"jobs/{run_id}.json"
    check_version(version)
    append(directory / "runs.jsonl", record)
    output.unlink(missing_ok=True)
    (directory / ".work" / f"{run_id}.input.json").unlink(missing_ok=True)


def _failure(
    run: dict[str, Any], status_name: str, reason: str, elapsed: float
) -> dict[str, Any]:
    return {
        **{key: value for key, value in run.items() if key != "job"},
        "status": status_name,
        "reason": reason,
        "worker_wall_s": elapsed,
        "metrics": {},
        "hardware": {},
        "cost": [],
        "validation": None,
        "compile": {
            "wall_s": None,
            "peak_rss_mb": None,
            "search_nodes": None,
            "budget_hit": status_name == "timeout",
        },
        "provenance": {"job_hash": None, "result_path": None},
    }


def status(directory: Path) -> dict[str, Any]:
    """Report completed statuses, pending count, and a wall-time-based ETA."""
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema") == "nadit.task_manifest/1":
        return task_status(directory)
    records = read_records(directory / "runs.jsonl")
    pending = manifest["run_count"] - len(records)
    average = (
        sum(row["worker_wall_s"] for row in records) / len(records) if records else None
    )
    return {
        "directory": str(directory),
        "planned": manifest["run_count"],
        "completed": len(records),
        "pending": pending,
        "statuses": dict(Counter(row["status"] for row in records)),
        "estimated_remaining_s": None
        if average is None
        else average * pending / manifest["workers"],
    }
