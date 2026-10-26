"""Durable dependency state for the existing bounded experiment worker loop."""

import ctypes
import hashlib
import json
import os
import sys
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..provenance import canonical_hash
from .journal import append, read_records, write_json

SCHEMA = "nadit.task_plan/1"
TERMINAL = frozenset({"ok", "software_error", "blocked", "budget_exceeded"})
WORKER_STATUSES = frozenset(
    {"ok", "software_error", "deferred", "needs_dependencies", "budget_exceeded"}
)
STORAGE_POLL_S = 1.0
MEMORY_POLL_S = 0.1


def validate_task(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate one immutable content-addressed task and its explicit budgets."""
    required = {
        "task_id",
        "kind",
        "payload",
        "dependencies",
        "timeout_s",
        "max_attempts",
        "memory_bytes",
    }
    if (
        not isinstance(value, Mapping)
        or not required <= value.keys()
        or value.keys() - required - {"dependency_mode"}
    ):
        raise ValueError(
            "Task requires task_id, kind, payload, dependencies and budgets"
        )
    task: dict[str, Any] = json.loads(json.dumps(dict(value), allow_nan=False))
    if task.get("dependency_mode", "success") not in ("success", "terminal"):
        raise ValueError("Task dependency_mode must be success or terminal")
    if not isinstance(task["kind"], str) or not task["kind"].startswith("msd."):
        raise ValueError("Unsupported task kind; an msd handler is required")
    if not isinstance(task["payload"], dict) or not isinstance(
        task["dependencies"], list
    ):
        raise ValueError("Invalid task payload or dependencies")
    deps = task["dependencies"]
    if any(not isinstance(item, str) for item in deps) or len(set(deps)) != len(deps):
        raise ValueError("Task dependencies must be distinct task IDs")
    for name in ("max_attempts", "memory_bytes"):
        if type(task[name]) is not int or task[name] < 1:
            raise ValueError(f"Task {name} must be a positive integer")
    if type(task["timeout_s"]) not in (int, float) or task["timeout_s"] <= 0:
        raise ValueError("Task timeout_s must be positive")
    body = {key: item for key, item in task.items() if key != "task_id"}
    if task["task_id"] != canonical_hash(body):
        raise ValueError("Task ID must hash its complete immutable definition")
    return task


def validate_plan(document: Mapping[str, Any]) -> dict[str, Any]:
    """Check a task plan before filesystem changes or worker launch."""
    value: dict[str, Any] = json.loads(json.dumps(dict(document), allow_nan=False))
    if value.get("schema") != SCHEMA or not isinstance(value.get("tasks"), list):
        raise ValueError("Expected nadit.task_plan/1 with a tasks list")
    if not value["tasks"]:
        raise ValueError("Task plan cannot be empty")
    value["tasks"] = [validate_task(task) for task in value["tasks"]]
    ids = [task["task_id"] for task in value["tasks"]]
    if len(set(ids)) != len(ids):
        raise ValueError("Task plan has duplicate task IDs")
    budget = value.get("budget", {})
    budget.setdefault("max_artifact_refreshes", 1)
    if (
        type(budget.get("campaign_timeout_s")) not in (int, float)
        or budget["campaign_timeout_s"] <= 0
    ):
        raise ValueError("campaign_timeout_s must be positive")
    if (
        type(budget.get("max_storage_bytes")) is not int
        or budget["max_storage_bytes"] < 1
    ):
        raise ValueError("max_storage_bytes must be a positive integer")
    if (
        type(budget["max_artifact_refreshes"]) is not int
        or budget["max_artifact_refreshes"] < 0
    ):
        raise ValueError("max_artifact_refreshes must be a nonnegative integer")
    value.setdefault("source_paths", [])
    _check_dependencies(
        {task["task_id"]: set(task["dependencies"]) for task in value["tasks"]}
    )
    _validate_finalization(value)
    return value


def _validate_finalization(document: Mapping[str, Any]) -> None:
    reserve = document.get("finalization")
    if reserve is None:
        return
    if not isinstance(reserve, dict) or set(reserve) != {
        "task_ids",
        "reserve_seconds",
        "reserve_bytes",
    }:
        raise ValueError("Finalization requires explicit task IDs, seconds and bytes")
    ids = reserve["task_ids"]
    tasks = {task["task_id"]: task for task in document["tasks"]}
    if (
        not isinstance(ids, list)
        or not ids
        or any(not isinstance(item, str) for item in ids)
        or len(set(ids)) != len(ids)
        or not set(ids) <= tasks.keys()
    ):
        raise ValueError("Finalization task IDs must identify distinct initial tasks")
    if (
        type(reserve["reserve_seconds"]) not in (int, float)
        or not 0 < reserve["reserve_seconds"] < document["budget"]["campaign_timeout_s"]
        or type(reserve["reserve_bytes"]) is not int
        or not 0 < reserve["reserve_bytes"] < document["budget"]["max_storage_bytes"]
    ):
        raise ValueError(
            "Finalization reserve must remain inside total campaign budgets"
        )
    for identity, task in tasks.items():
        if identity in ids:
            if task.get("dependency_mode") != "terminal" or task["kind"] not in {
                "msd.summarize",
                "msd.export",
                "msd.audit",
            }:
                raise ValueError(
                    "Finalization requires terminal-gated export/audit tasks"
                )
        elif set(task["dependencies"]) & set(ids):
            raise ValueError("Ordinary tasks cannot depend on finalization tasks")


def _check_dependencies(edges: Mapping[str, set[str]]) -> None:
    remaining = {key: set(values) for key, values in edges.items()}
    if any(not values <= remaining.keys() for values in remaining.values()):
        raise ValueError("Task dependency is not defined")
    while remaining:
        ready = {key for key, values in remaining.items() if not values}
        if not ready:
            raise ValueError("Task dependencies contain a cycle")
        remaining = {
            key: values - ready for key, values in remaining.items() if key not in ready
        }


def _read_definitions(
    directory: Path, *, repair: bool = False
) -> dict[str, dict[str, Any]]:
    """Read each registered immutable payload once; ignore unpublished files."""
    result = {}
    for row in read_records(directory / "task_registry.jsonl", repair=repair):
        identity = row["task_id"]
        if identity in result:
            raise ValueError("Duplicate task registry identity")
        path = directory / "task_definitions" / f"{identity}.json"
        task = validate_task(json.loads(path.read_text(encoding="utf-8")))
        if task["task_id"] != identity:
            raise ValueError("Task definition path and identity disagree")
        result[identity] = task
    return result


def resident_bytes(pid: int) -> int | None:
    """Read resident memory for an owned worker; unsupported/dead PIDs return None."""
    if sys.platform == "win32":
        from ctypes import wintypes

        class MemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("faults", wintypes.DWORD),
                *[
                    (name, ctypes.c_size_t)
                    for name in (
                        "peak",
                        "resident",
                        "peak_paged",
                        "paged",
                        "peak_nonpaged",
                        "nonpaged",
                        "pagefile",
                        "peak_pagefile",
                    )
                ],
            ]

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        handle = kernel.OpenProcess(0x0410, False, pid)
        if not handle:
            return None
        try:
            counters = MemoryCounters()
            counters.cb = ctypes.sizeof(counters)
            if not psapi.GetProcessMemoryInfo(
                handle, ctypes.byref(counters), counters.cb
            ):
                return None
            return int(counters.resident)
        finally:
            kernel.CloseHandle(handle)
    if sys.platform.startswith("linux"):
        try:
            pages = int(Path(f"/proc/{pid}/statm").read_text().split()[1])
            return pages * int(os.sysconf("SC_PAGE_SIZE"))
        except (OSError, ValueError, IndexError):
            return None
    return None


class TaskPlanState:
    """Single-writer task/dependency ledger; subprocess ownership stays in runner."""

    def __init__(
        self,
        document: dict[str, Any],
        directory: Path,
        version: dict[str, Any],
        workers: int,
        executor: str,
        verify: Callable[[], None],
    ) -> None:
        self.document, self.directory, self.version = document, directory, version
        self.executor, self.verify = executor, verify
        self.stop_reason: str | None = None
        self.work_stop_reason: str | None = None
        self.finalizer_ids = frozenset(
            document.get("finalization", {}).get("task_ids", ())
        )
        self.peak_storage_bytes = 0
        self.artifact_validation_s = 0.0
        self._storage_at, self._storage_bytes = float("-inf"), 0
        self._storage_observed_at: str | None = None
        previous_status = directory / "campaign_status.json"
        if previous_status.exists():
            previous = json.loads(previous_status.read_text(encoding="utf-8"))
            self.peak_storage_bytes = previous.get("peak_observed_storage_bytes", 0)
            self._storage_bytes = previous.get("observed_storage_bytes") or 0
            self._storage_observed_at = previous.get("storage_observed_at")
            self.work_stop_reason = previous.get("work_stop_reason")
        self.inflight: set[str] = set()
        self.not_before: dict[str, float] = {}
        manifest_path = directory / "manifest.json"
        if manifest_path.exists():
            self.manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if (
                self.manifest.get("schema") != "nadit.task_manifest/1"
                or self.manifest["code"] != version
                or self.manifest["spec_hash"] != canonical_hash(document)
                or self.manifest["executor"] != executor
            ):
                raise ValueError(
                    "Task plan/source/executor differs from the frozen campaign"
                )
        else:
            self.manifest = {
                "schema": "nadit.task_manifest/1",
                "code": version,
                "spec_hash": canonical_hash(document),
                "executor": executor,
                "started_at": datetime.now(UTC).isoformat(),
                "workers": workers,
                "resource_monitor": {
                    "memory_poll_s": MEMORY_POLL_S,
                    "storage_poll_s": STORAGE_POLL_S,
                    "mode": "sampled worker RSS and directory bytes; not a hard quota",
                    "overshoot": (
                        "usage may grow between samples; publication checks reject "
                        "over-budget success"
                    ),
                },
            }
            write_json(directory / "task_plan.json", document)
            write_json(manifest_path, self.manifest)
        self.tasks = {task["task_id"]: task for task in document["tasks"]}
        self.replays: dict[str, set[str]] = {}
        self.edges = {
            identity: set(task["dependencies"]) for identity, task in self.tasks.items()
        }
        previous = _read_definitions(directory, repair=True)
        self._persisted_ids = set(previous)
        for key, task in previous.items():
            if key in self.tasks and self.tasks[key] != task:
                raise ValueError("Persisted task definitions changed")
            self.tasks[key] = task
            self.edges[key] = set(task["dependencies"])
        for row in read_records(directory / "task_edges.jsonl", repair=True):
            identity = row["task_id"]
            if identity not in self.tasks:
                raise ValueError("Persisted edge names an unknown task")
            self.edges[identity].update(row.get("add", ()))
            if "replay" in row:
                self.replays.setdefault(identity, set()).add(row["replay"])
        self._saved_edges = {key: set(values) for key, values in self.edges.items()}
        self._saved_replays = {key: set(values) for key, values in self.replays.items()}
        _check_dependencies(self.edges)
        self._save_definitions()
        starts = read_records(directory / "task_dispatches.jsonl", repair=True)
        records = read_records(directory / "task_attempts.jsonl", repair=True)
        if len({row["run_id"] for row in records}) != len(records):
            raise ValueError("Duplicate task attempt completion records")
        self.attempts = Counter[str]()
        self.failures = Counter[str]()
        for row in starts:
            self.attempts[row["task_id"]] = max(
                self.attempts[row["task_id"]], row["attempt"]
            )
        for row in records:
            self.failures[row["task_id"]] += row["status"] == "software_error"
            if row.get("not_before"):
                self.not_before[row["task_id"]] = row["not_before"]
        self.completed: dict[str, dict[str, Any]] = {}
        invalidations = read_records(
            directory / "task_invalidations.jsonl", repair=True
        )
        self.refreshes = Counter[str]()
        invalidated_generations = {}
        for row in invalidations:
            self.refreshes[row["task_id"]] += row["requeued"]
            invalidated_generations[row["task_id"]] = row["previous_completion"][
                "attempts"
            ]
        for path in (directory / "task_completions").glob("*.json"):
            row = json.loads(path.read_text(encoding="utf-8"))
            identity = row["task_id"]
            if (
                identity not in self.tasks
                or path.stem != identity
                or row["status"] not in TERMINAL | {"invalidated"}
            ):
                raise ValueError("Invalid task completion record")
            if row["status"] == "invalidated" or (
                row["status"] == "ok"
                and row["attempts"] <= invalidated_generations.get(identity, -1)
            ):
                write_json(path, {**row, "status": "invalidated"})
                continue
            if row.get("result_path"):
                result = json.loads(
                    (directory / row["result_path"]).read_text(encoding="utf-8")
                )
                if canonical_hash(result) != row["result_sha256"]:
                    raise ValueError("Completed task result hash differs")
            self.completed[identity] = row
        started = datetime.fromisoformat(self.manifest["started_at"]).timestamp()
        self.deadline = time.monotonic() + max(
            0, document["budget"]["campaign_timeout_s"] - (time.time() - started)
        )
        self.work_deadline = self.deadline - document.get("finalization", {}).get(
            "reserve_seconds", 0
        )
        for identity, row in tuple(self.completed.items()):
            if row["status"] == "ok":
                failure = self._artifact_failure(row.get("artifacts", []))
                if failure:
                    self._invalidate(identity, failure)
        self._campaign(
            "finalizing" if self.work_stop_reason else "running", self.work_stop_reason
        )

    def _save_definitions(
        self, identities: Sequence[str] | None = None, *, edge_id: str | None = None
    ) -> None:
        for identity in self.tasks if identities is None else identities:
            if identity in self._persisted_ids:
                continue
            path = self.directory / "task_definitions" / f"{identity}.json"
            if path.exists():
                if json.loads(path.read_text(encoding="utf-8")) != self.tasks[identity]:
                    raise ValueError("Immutable task definition changed")
            else:
                write_json(path, self.tasks[identity])
            append(self.directory / "task_registry.jsonl", {"task_id": identity})
            self._persisted_ids.add(identity)
            self._saved_edges.setdefault(
                identity, set(self.tasks[identity]["dependencies"])
            )
        if edge_id is not None:
            additions = self.edges[edge_id] - self._saved_edges[edge_id]
            if additions:
                append(
                    self.directory / "task_edges.jsonl",
                    {"task_id": edge_id, "add": sorted(additions)},
                )
                self._saved_edges[edge_id].update(additions)
            old = self._saved_replays.setdefault(edge_id, set())
            for generation in sorted(self.replays.get(edge_id, set()) - old):
                append(
                    self.directory / "task_edges.jsonl",
                    {"task_id": edge_id, "replay": generation},
                )
                old.add(generation)

    def _campaign(self, status_name: str, reason: str | None = None) -> None:
        write_json(
            self.directory / "campaign_status.json",
            {
                "status": status_name,
                "reason": reason,
                "peak_observed_storage_bytes": self.peak_storage_bytes,
                "observed_storage_bytes": self._storage_bytes
                if self._storage_observed_at is not None
                else None,
                "storage_observed_at": self._storage_observed_at,
                "artifact_validation_s": self.artifact_validation_s,
                "work_stop_reason": self.work_stop_reason,
                "finalization": {
                    "configured": len(self.finalizer_ids),
                    "completed": sum(
                        identity in self.completed for identity in self.finalizer_ids
                    ),
                    "succeeded": sum(
                        self.completed.get(identity, {}).get("status") == "ok"
                        for identity in self.finalizer_ids
                    ),
                    "reserve_is_part_of_total_budget": True,
                },
            },
        )

    @property
    def unfinished(self) -> bool:
        """Whether tasks remain nonterminal, including deferred/dependent work."""
        return len(self.completed) != len(self.tasks)

    def storage_bytes(self, *, force: bool = False) -> int:
        """Sample the campaign tree at bounded cadence and publication boundaries."""
        now = time.monotonic()
        if force or now - self._storage_at >= STORAGE_POLL_S:
            count = 0
            for root, _, names in os.walk(self.directory):
                for name in names:
                    try:
                        count += (Path(root) / name).stat().st_size
                    except FileNotFoundError:
                        pass
            self._storage_at, self._storage_bytes = now, count
            self._storage_observed_at = datetime.now(UTC).isoformat()
            self.peak_storage_bytes = max(self.peak_storage_bytes, count)
        return self._storage_bytes

    def budget_reason(self, *, force: bool = False) -> str | None:
        """Report sampled campaign limits without hashing source on idle polls."""
        if time.monotonic() >= self.deadline:
            return "campaign_timeout_s exceeded (elapsed time includes downtime)"
        if (
            self.storage_bytes(force=force)
            > self.document["budget"]["max_storage_bytes"]
        ):
            return "max_storage_bytes exceeded in campaign directory"
        return None

    def check_budgets(self, active: set[str], *, force: bool = False) -> bool:
        """Stop ordinary work at the reserve boundary; never exceed the hard cap.

        Returns True only when all work, including finalizers, must stop. A
        sampled storage overshoot or downtime can exhaust the hard cap before
        finalization; this remains an explicit budget failure, not a guarantee
        that a report can always be written.
        """
        reason = self.stop_reason or self.budget_reason(force=force)
        if reason:
            self.expire_pending(reason, active)
            return True
        reason = self.work_stop_reason
        if self.finalizer_ids and any(
            identity not in self.completed and identity not in self.finalizer_ids
            for identity in self.tasks
        ):
            reserve = self.document["finalization"]
            if reason is None and time.monotonic() >= self.work_deadline:
                reason = (
                    "work time budget exhausted; reserved finalization time retained"
                )
            if (
                reason is None
                and self.storage_bytes()
                > self.document["budget"]["max_storage_bytes"]
                - reserve["reserve_bytes"]
            ):
                reason = "work storage exhausted; reserved finalization bytes retained"
        if reason:
            newly_stopped = self.work_stop_reason is None
            self.work_stop_reason = reason
            for identity in self.tasks:
                if (
                    identity not in self.completed
                    and identity not in active
                    and identity not in self.finalizer_ids
                ):
                    self._record(
                        identity,
                        {"status": "budget_exceeded", "reason": reason},
                        terminal=True,
                    )
            if newly_stopped:
                self._campaign("finalizing", reason)
        return False

    def termination_reason(self, identity: str) -> str | None:
        """Return the applicable global stop reason for one running worker."""
        return self.stop_reason or (
            self.work_stop_reason if identity not in self.finalizer_ids else None
        )

    def ready_runs(self) -> list[dict[str, Any]]:
        """Reserve each currently ready task once for the shared worker loop."""
        ready = []
        for identity in sorted(self.tasks):
            if identity in self.completed or identity in self.inflight:
                continue
            failed = [
                dep
                for dep in self.edges[identity]
                if dep in self.completed and self.completed[dep]["status"] != "ok"
            ]
            if (
                failed
                and self.tasks[identity].get("dependency_mode", "success") == "success"
            ):
                self._record(
                    identity,
                    {
                        "status": "blocked",
                        "reason": {"failed_dependencies": sorted(failed)},
                    },
                    terminal=True,
                )
                continue
            if (
                self.stop_reason
                or (self.work_stop_reason and identity not in self.finalizer_ids)
                or not self.edges[identity] <= self.completed.keys()
                or time.time() < self.not_before.get(identity, 0)
            ):
                continue
            attempt = self.attempts[identity] + 1
            self.inflight.add(identity)
            ready.append(
                {
                    "schema": "nadit.experiment_task/1",
                    "run_id": f"{identity}.a{attempt}",
                    "task_id": identity,
                    "attempt": attempt,
                    "task": self.tasks[identity],
                    "executor": self.executor,
                }
            )
        return ready

    def dispatched(self, run: dict[str, Any]) -> None:
        """Persist dispatch identity before starting the isolated child."""
        self.verify()
        self.attempts[run["task_id"]] = run["attempt"]
        append(
            self.directory / "task_dispatches.jsonl",
            {
                "task_id": run["task_id"],
                "run_id": run["run_id"],
                "attempt": run["attempt"],
            },
        )

    def expire_pending(self, reason: str, active: set[str]) -> None:
        """Stop new work and mark nondispatched tasks without inventing success."""
        self.stop_reason = reason
        for identity in self.tasks:
            if identity not in self.completed and identity not in active:
                self._record(
                    identity,
                    {"status": "budget_exceeded", "reason": reason},
                    terminal=True,
                )

    def _artifact_failure(self, descriptors: Any) -> str | None:
        started = time.perf_counter()
        try:
            if not isinstance(descriptors, list):
                return "artifacts must be a list of file descriptors"
            for item in descriptors:
                if not isinstance(item, dict) or set(item) != {
                    "path",
                    "sha256",
                    "hash_kind",
                }:
                    return "Invalid artifact descriptor"
                path = (self.directory / item["path"]).resolve()
                if not path.is_relative_to(self.directory):
                    return "Task artifacts must remain inside the campaign directory"
                try:
                    content = path.read_bytes()
                    if item["hash_kind"] == "canonical_json":
                        digest = canonical_hash(json.loads(content))
                    elif item["hash_kind"] == "bytes":
                        digest = hashlib.sha256(content).hexdigest()
                    else:
                        return "Unsupported artifact hash_kind"
                except (OSError, ValueError) as error:
                    return f"Artifact unavailable: {path}: {error}"
                if digest != item["sha256"]:
                    return f"Artifact hash mismatch: {path}"
            return None
        except (TypeError, KeyError) as error:
            return f"Invalid artifact descriptor: {error}"
        finally:
            self.artifact_validation_s += time.perf_counter() - started

    def _invalidate(self, identity: str, reason: str) -> None:
        self.verify()
        previous = dict(self.completed[identity])
        if previous.get("result_path"):
            history = f"results/{identity}.a{previous['attempts']}.previous.json"
            result = json.loads(
                (self.directory / previous["result_path"]).read_text(encoding="utf-8")
            )
            write_json(self.directory / history, result)
            previous["result_path"] = history
        requeue = (
            self.refreshes[identity] < self.document["budget"]["max_artifact_refreshes"]
        )
        append(
            self.directory / "task_invalidations.jsonl",
            {
                "task_id": identity,
                "reason": reason,
                "requeued": requeue,
                "previous_completion": previous,
            },
        )
        self.completed.pop(identity)
        if requeue:
            self.refreshes[identity] += 1
            write_json(
                self.directory / "task_completions" / f"{identity}.json",
                {**previous, "status": "invalidated", "reason": reason},
            )
        else:
            self._record(
                identity,
                {
                    "status": "budget_exceeded",
                    "reason": f"max_artifact_refreshes exhausted: {reason}",
                    "run_id": f"{identity}.refresh_exhausted",
                },
                terminal=True,
            )

    def _dependencies(self, identity: str, requests: Any) -> None:
        if identity in self.finalizer_ids:
            raise ValueError(
                "Finalization cannot request new calibration or production work"
            )
        if not isinstance(requests, list) or not requests:
            raise ValueError("needs_dependencies requires complete dependency_requests")
        requested = [validate_task(task) for task in requests]
        tasks, edges = (
            dict(self.tasks),
            {key: set(values) for key, values in self.edges.items()},
        )
        for task in requested:
            key = task["task_id"]
            if key in tasks and tasks[key] != task:
                raise ValueError("Conflicting dependency task definition")
            tasks[key] = task
            edges.setdefault(key, set(task["dependencies"]))
            edges[identity].add(key)
        _check_dependencies(edges)
        self.tasks, self.edges = tasks, edges
        for task in requested:
            key = task["task_id"]
            if key in self.completed and self.completed[key]["status"] == "ok":
                failure = self._artifact_failure(
                    self.completed[key].get("artifacts", [])
                )
                if failure:
                    self._invalidate(key, failure)
        if all(
            task["task_id"] in self.completed
            and self.completed[task["task_id"]]["status"] == "ok"
            for task in requested
        ):
            generation = canonical_hash(
                {
                    task["task_id"]: self.completed[task["task_id"]]["attempts"]
                    for task in requested
                }
            )
            replayed = self.replays.setdefault(identity, set())
            if generation in replayed:
                raise ValueError(
                    "Requested healthy dependencies still miss after replay"
                )
            replayed.add(generation)
        self._save_definitions(
            [task["task_id"] for task in requested], edge_id=identity
        )

    def finish(self, run: dict[str, Any], record: dict[str, Any], output: Path) -> None:
        """Persist telemetry, dynamic edges and terminal results exactly once."""
        identity = run["task_id"]
        self.inflight.discard(identity)
        if identity in self.completed:
            return
        self.verify()
        record = dict(record)
        record.update(run_id=run["run_id"], attempt=run["attempt"])
        reason = self.budget_reason(force=True)
        if reason:
            self.stop_reason = reason
            record.update(status="budget_exceeded", reason=reason)
            if "result" in record and "max_storage_bytes" in reason:
                record["artifact_omitted"] = {
                    "reason": reason,
                    "result_sha256": canonical_hash(record.pop("result")),
                }
        try:
            if record.get("status") not in WORKER_STATUSES:
                raise ValueError("Worker returned an unsupported task status")
            if record["status"] == "ok":
                started = self.artifact_validation_s
                failure = self._artifact_failure(record.get("artifacts", []))
                record["runner_software_seconds"] = {
                    "artifact_validation": self.artifact_validation_s - started
                }
                if failure:
                    raise ValueError(failure)
            if record["status"] == "needs_dependencies":
                self._dependencies(identity, record.get("dependency_requests"))
            if record["status"] == "deferred":
                delay = record.get("retry_after_s", 0.25)
                if (
                    type(delay) not in (int, float)
                    or not 0 < delay <= self.document["budget"]["campaign_timeout_s"]
                ):
                    raise ValueError("Invalid deferred retry_after_s")
                self.not_before[identity] = time.time() + delay
                record["not_before"] = self.not_before[identity]
        except (ValueError, TypeError, KeyError) as error:
            record.update(
                status="software_error", reason=f"Invalid worker task result: {error}"
            )
        if record["status"] == "software_error":
            self.failures[identity] += 1
        terminal = record["status"] in ("ok", "budget_exceeded") or (
            record["status"] == "software_error"
            and self.failures[identity] >= self.tasks[identity]["max_attempts"]
        )
        output.unlink(missing_ok=True)
        self._record(identity, record, terminal=terminal)
        input_path = self.directory / ".work" / f"{run['run_id']}.input.json"
        input_path.unlink(missing_ok=True)
        output.with_suffix(".started.json").unlink(missing_ok=True)

    def _record(self, identity: str, record: dict[str, Any], *, terminal: bool) -> None:
        self.verify()
        row = dict(record)
        result = row.pop("result", None)
        row.update(
            task_id=identity,
            kind=self.tasks[identity]["kind"],
            attempts=self.attempts[identity],
            software_failures=self.failures[identity],
            result_path=None,
            result_sha256=None,
        )
        row.setdefault("run_id", f"{identity}.terminal")
        row.setdefault("worker_wall_s", 0.0)
        if result is not None:
            relative = (
                f"results/{identity}.json"
                if row["status"] == "ok"
                else f"results/{row['run_id']}.json"
            )
            write_json(self.directory / relative, result)
            reason = (
                self.budget_reason(force=True)
                if row["status"] == "ok"
                else "max_storage_bytes exceeded in campaign directory"
                if self.storage_bytes(force=True)
                > self.document["budget"]["max_storage_bytes"]
                else None
            )
            if reason:
                (self.directory / relative).unlink()
                self.stop_reason = reason
                row.update(status="budget_exceeded", reason=reason)
                row["artifact_omitted"] = {
                    "reason": reason,
                    "result_sha256": canonical_hash(result),
                }
                terminal = True
            else:
                row.update(result_path=relative, result_sha256=canonical_hash(result))
        self.verify()
        if terminal:
            write_json(self.directory / "task_completions" / f"{identity}.json", row)
            self.completed[identity] = row
        append(self.directory / "task_attempts.jsonl", row)
        self._campaign(
            "budget_exceeded"
            if self.stop_reason
            else "finalizing"
            if self.work_stop_reason
            else "running",
            self.stop_reason or self.work_stop_reason,
        )

    def close(self, *, interrupted: str | None = None) -> None:
        """Persist campaign termination evidence, separate from task physics."""
        self._campaign(
            "interrupted"
            if interrupted
            else "budget_exceeded"
            if self.stop_reason or self.work_stop_reason
            else "failed"
            if any(row["status"] != "ok" for row in self.completed.values())
            else "complete",
            interrupted or self.stop_reason or self.work_stop_reason,
        )


def task_status(directory: Path) -> dict[str, Any]:
    """Read compact task status without rerunning workers or traversing traces."""
    original = json.loads((directory / "task_plan.json").read_text(encoding="utf-8"))
    definitions = {task["task_id"]: task for task in original["tasks"]}
    definitions.update(_read_definitions(directory))
    rows = read_records(directory / "task_attempts.jsonl")
    latest = {row["task_id"]: row for row in rows}
    invalidations = {
        row["task_id"]: row["previous_completion"]["attempts"]
        for row in read_records(directory / "task_invalidations.jsonl")
    }
    tasks = {}
    for identity, task in definitions.items():
        path = directory / "task_completions" / f"{identity}.json"
        row = (
            json.loads(path.read_text(encoding="utf-8"))
            if path.exists()
            else latest.get(identity, {})
        )
        tasks[identity] = {
            "kind": task["kind"],
            "status": row.get("status", "pending")
            if path.exists()
            and row.get("status") in TERMINAL
            and not (
                row.get("status") == "ok"
                and row.get("attempts", 0) <= invalidations.get(identity, -1)
            )
            else "pending",
            "attempts": row.get("attempts", 0),
            "software_failures": row.get("software_failures", 0),
            "result_path": row.get("result_path"),
            "result_sha256": row.get("result_sha256"),
            "reason": row.get("reason"),
        }
    campaign = json.loads(
        (directory / "campaign_status.json").read_text(encoding="utf-8")
    )
    counts = Counter(row["status"] for row in tasks.values())
    return {
        "directory": str(directory),
        "planned": len(tasks),
        "completed": len(tasks) - counts["pending"],
        "pending": counts["pending"],
        "statuses": dict(counts),
        "tasks": tasks,
        "campaign_status": campaign["status"],
        "campaign_reason": campaign.get("reason"),
        "peak_observed_storage_bytes": campaign.get("peak_observed_storage_bytes", 0),
        "observed_storage_bytes": campaign.get("observed_storage_bytes"),
        "storage_observed_at": campaign.get("storage_observed_at"),
        "work_stop_reason": campaign.get("work_stop_reason"),
        "finalization": campaign.get("finalization"),
    }
