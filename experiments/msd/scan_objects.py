"""Finite server scan over existing object factories; stop the scan on any error.

The coordinator starts only this scan's children and never resumes other jobs.
Workers retain catalogs across seeds and save compact shot metrics, plus a
single full representative trace per parameter cell. No producer/compile path.
"""

import argparse
import gc
import gzip
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .scan_metrics import MotionAccounting, aggregate, metrics


def _write(path: Path, value: Any) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, allow_nan=False), encoding="utf-8")
    temp.replace(path)


def make_cells(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Enumerate all full rectangular layouts; merge only exact column aliases."""
    if config.get("schema") == "nadit.level2_object_scan/1":
        original = make_cells({**config, "schema": "nadit.object_scan/1"})
        result = [
            {
                **cell,
                "id": cell["id"] + "-" + position,
                "level2_position": position,
                "level2_factories": 1,
            }
            for cell in original
            if cell["strategy"] == "synchronous"
            for position in config["level2_positions"]
        ]
        if len(result) != config["expected_cells"]:
            raise ValueError("LEVEL2_MATRIX_COUNT_MISMATCH")
        return result
    if not config["distances"] or not config["factory_counts"]:
        raise ValueError("EMPTY_SCAN_AXES")
    cells = []
    for d in config["distances"]:
        if type(d) is not int or d not in (3, 5, 7, 9, 11):
            raise ValueError("UNSUPPORTED_SCAN_DISTANCE")
        for n in config["factory_counts"]:
            if type(n) is not int or n < 1:
                raise ValueError("INVALID_SCAN_FACTORY_COUNT")
            for columns in range(1, n + 1):
                if n % columns:
                    continue
                placement = (
                    {"kind": "vertical"}
                    if columns == 1
                    else {"kind": "horizontal"}
                    if columns == n
                    else {"kind": "grid", "columns": columns}
                )
                aliases = [f"grid(columns={columns})"]
                if columns == 1:
                    aliases.append("vertical")
                if columns == n:
                    aliases.append("horizontal")
                for strategy in ("asynchronous", "synchronous"):
                    cells.append(
                        {
                            "id": f"d{d:02d}-n{n:02d}-c{columns:02d}-{strategy}",
                            "distance": d,
                            "factories": n,
                            "columns": columns,
                            "rows": n // columns,
                            "placement": placement,
                            "layout_aliases": aliases,
                            "strategy": strategy,
                        }
                    )
    if len({c["id"] for c in cells}) != len(cells):
        raise ValueError("DUPLICATE_SCAN_AXES")
    return cells


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def peak_rss_kib() -> int | None:
    """Read Linux worker peak RSS; unavailable on Windows, never reported as zero."""
    if sys.platform == "win32":
        return None
    import resource

    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)


@contextmanager
def shot_deadline(seconds: float) -> Iterator[None]:
    """Interrupt a Linux shot including accounting/serialization; never retry it."""
    if sys.platform == "win32":
        yield
        return

    def exceeded(signum: int, frame: Any) -> None:
        raise TimeoutError(f"SHOT_WALL_TIMEOUT: budget={seconds}s")

    previous = signal.signal(signal.SIGALRM, exceeded)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def event_groups(events: list[dict[str, Any]]) -> dict[str, str]:
    """Hash complete per-factory production rounds, allowing different prefixes."""
    groups: dict[str, list[Any]] = {}
    for event in events:
        invocation = event["occurrence"]["invocation_id"]
        owner = invocation.split("/batch[", 1)[0]
        groups.setdefault(owner, []).append(
            (
                event["occurrence"],
                event["outcome_key"],
                event["values"],
                event["port_sha256"],
            )
        )
    return {
        owner: _digest(sorted(rows, key=lambda row: json.dumps(row[0], sort_keys=True)))
        for owner, rows in groups.items()
    }


def validate_level2_config(config: dict[str, Any]) -> None:
    """Validate the frozen model, allowing only explicitly approved larger budgets."""
    frozen = json.loads(
        Path(__file__).with_name("level2-sync-scan-preparation.json").read_text()
    )
    allowed = {
        "schema",
        "status",
        "preparation_only",
        "implementation_status",
        "execution_approved",
        "execution_source_commit",
    }
    continuation = config.get("continuation_approved") is True
    if continuation:
        allowed |= {"shot_timeout_seconds", "cell_wall_seconds"}
        if not config.get("continuation_from") or not config.get(
            "continuation_source_commit"
        ):
            raise ValueError("CONTINUATION_SOURCE_REQUIRED")
    if any(config.get(k) != v for k, v in frozen.items() if k not in allowed):
        raise ValueError("FROZEN_LEVEL2_PARAMETERS_CHANGED")
    budget = config.get("case_timeout_seconds")
    if (
        config.get("execution_approved") is not True
        or type(budget) is not int
        or budget != config["shot_timeout_seconds"]
        or (budget <= 30 if continuation else budget != 30)
        or config["cell_wall_seconds"] != config["seed_count"] * budget + 60
    ):
        raise ValueError("LEVEL2_APPROVAL_OR_DEADLINE_INVALID")
    if config["factory_counts"] != config["level1_factory_counts"]:
        raise ValueError("LEVEL1_COUNT_ALIAS_CHANGED")


def continuation_records(
    config: dict[str, Any], cell_id: str, sources: dict[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Read a completed seed prefix without altering its source or resuming its job."""
    if not config.get("continuation_from"):
        return [], {"imported_shots": 0}
    folder = Path(config["continuation_from"]) / "cells" / cell_id
    path = folder / "shots.jsonl"
    if not path.exists():
        return [], {"imported_shots": 0}
    data = path.read_bytes()
    if data and not data.endswith(b"\n"):
        raise ValueError("CONTINUATION_INCOMPLETE_RECORD")
    records = [json.loads(line) for line in data.splitlines()]
    expected = list(range(config["seed_start"], config["seed_start"] + len(records)))
    if len(records) > config["seed_count"] or [r["seed"] for r in records] != expected:
        raise ValueError("CONTINUATION_SEED_PREFIX")
    old_sources = json.loads((folder / "source-hashes.json").read_text())
    if old_sources["runtime"] != sources["runtime"] or any(
        old_sources["scan"][name] != sources["scan"][name]
        for name in ("scan_metrics.py", "object-motion-reference.json")
    ):
        raise ValueError("CONTINUATION_MODEL_SOURCE_CHANGED")
    return records, {
        "imported_shots": len(records),
        "source": str(path),
        "sha256": hashlib.sha256(data).hexdigest(),
        "source_commit": config.get("continuation_source_commit"),
        "software_seconds_scope": "imported_rows_keep_original_budget_and_timings",
    }


def run_worker(
    config: dict[str, Any],
    cell: dict[str, Any],
    directory: Path,
    cpu: int | None = None,
) -> None:
    """Run fixed seeds with one catalog; any error writes context and propagates."""
    from modules.codes.rotated_surface.object_factory import FactoryObjectCatalog
    from modules.logical_compiler.examples.factory_level2 import run_level2
    from modules.logical_compiler.examples.factory_objects import run_factory_objects
    from modules.logical_compiler.examples.object_cases import (
        _sources,
        forbid_atom_work,
    )

    if cpu is not None:
        setter = getattr(os, "sched_setaffinity", None)
        if not callable(setter):
            raise TypeError("LINUX_AFFINITY_REQUIRED")
        setter(0, {cpu})
    directory.mkdir(parents=True, exist_ok=True)
    if any(
        (directory / name).exists()
        for name in ("shots.jsonl", "summary.json", "error.json")
    ):
        raise FileExistsError("EXISTING_CELL_RESULTS: no retry or resume")
    started = time.monotonic()
    two_level = config.get("schema") == "nadit.level2_object_scan/1"
    rejection_saved = False
    current: int | None = None
    try:
        sources = _sources()
        scan_paths = tuple(Path(__file__).parent.glob("*.py")) + tuple(
            Path(__file__).parent.glob("*.json")
        )
        source_checks = {
            str(p.name): hashlib.sha256(p.read_bytes()).hexdigest() for p in scan_paths
        }
        _write(
            directory / "source-hashes.json",
            {"runtime": sources, "scan": source_checks},
        )
        imported, provenance = continuation_records(
            config, cell["id"], {"runtime": sources, "scan": source_checks}
        )
        manifest_path = directory.parents[1] / "manifest.json"
        if config.get("continuation_from") and manifest_path.exists():
            frozen_prefix = json.loads(manifest_path.read_text())["continuation"][
                "cells"
            ][cell["id"]]
            if provenance != frozen_prefix:
                raise ValueError("CONTINUATION_INPUT_CHANGED_AFTER_PREFLIGHT")
        _write(directory / "continuation.json", provenance)
        if imported:
            origin = Path(config["continuation_from"]) / "cells" / cell["id"]
            traces = ["representative.json.gz"] + [
                f"rejection-seed{r['seed']}.json.gz"
                for r in imported
                if r["metrics"]["outputs"] == 0
            ]
            for name in traces:
                path = origin / name
                if path.exists():
                    shutil.copyfile(path, directory / name)
                elif name == "representative.json.gz":
                    raise ValueError("CONTINUATION_REPRESENTATIVE_MISSING")
            rejection_saved = any(r["metrics"]["outputs"] == 0 for r in imported)
        with forbid_atom_work() as guards:
            catalog = FactoryObjectCatalog.load(distance=cell["distance"])
            if (
                two_level
                and catalog.fingerprint
                != config["catalog_fingerprints"][str(cell["distance"])]
            ):
                raise ValueError("CATALOG_FINGERPRINT_CHANGED")
            accounting = MotionAccounting(catalog)
            identity = {k: id(v) for k, v in catalog.entries.items()}
            rows: list[dict[str, Any]] = [r["metrics"] for r in imported]
            geometry = None
            if len(imported) == config["seed_count"]:
                geometry = json.loads((origin / "summary.json").read_text())["geometry"]
            with (directory / "shots.jsonl").open("x", encoding="utf-8") as stream:
                for row in imported:
                    stream.write(
                        json.dumps(row, separators=(",", ":"), allow_nan=False) + "\n"
                    )
                stream.flush()
                for current in range(
                    config["seed_start"] + len(imported),
                    config["seed_start"] + config["seed_count"],
                ):
                    _write(
                        directory / "progress.json",
                        {
                            "status": "running",
                            "seed": current,
                            "completed": len(rows),
                            "cell": cell["id"],
                            "shot_started_unix": time.time(),
                        },
                    )
                    shot_start = time.monotonic()
                    with shot_deadline(config["case_timeout_seconds"]):
                        if two_level:
                            result = run_level2(
                                catalog,
                                level1_factories=cell["factories"],
                                seed=current,
                                rounds=1,
                                producer_round_budget=config[
                                    "producer_round_budget_per_factory"
                                ],
                                strategy="synchronous",
                                placement=cell["placement"]["kind"],
                                columns=cell["placement"].get("columns"),
                                level2_position=cell["level2_position"],
                                timeout_seconds=config["case_timeout_seconds"],
                            )
                        else:
                            result = run_factory_objects(
                                catalog,
                                factories=cell["factories"],
                                seed=current,
                                strategy=cell["strategy"],
                                cycles=1,
                                production_basis="production_rounds",
                                placement=cell["placement"]["kind"],
                                columns=cell["placement"].get("columns"),
                                raw_attempts=config["raw_attempt_limit"],
                                batches=16,
                                input_z_error=config["input_z_error"],
                                timeout_seconds=config["case_timeout_seconds"],
                            )
                        values = metrics(result, accounting)
                        if geometry is None:
                            geometry = result["layout"]
                        result["summary"]["forbidden_work"] = dict(guards)
                        events = sorted(
                            (
                                _digest(e["occurrence"]),
                                e["outcome_key"],
                                e["values"],
                                e["port_sha256"],
                            )
                            for e in result["case"]["events"]
                        )
                        calls = sorted(
                            (c["invocation_id"], c["component_id"])
                            for c in result["case"]["calls"]
                        )
                        record = {
                            "seed": current,
                            "metrics": values,
                            "event_sha256": _digest(events),
                            "call_sha256": _digest(calls),
                            "events": len(events),
                            "calls": len(calls),
                            "software_seconds": time.monotonic() - shot_start,
                            **(
                                {
                                    "event_groups": event_groups(
                                        result["case"]["events"]
                                    ),
                                    "conservation": {
                                        "inputs": len(result["supply"]["deliveries"]),
                                        "surplus": result["summary"][
                                            "retained_surplus"
                                        ],
                                    },
                                }
                                if two_level
                                else {}
                            ),
                        }
                        save_rejection = (
                            two_level and not rejection_saved and values["outputs"] == 0
                        )
                        if current == config["seed_start"] or save_rejection:
                            geometry = result["layout"]
                            with gzip.open(
                                directory
                                / (
                                    "representative.json.gz"
                                    if current == config["seed_start"]
                                    else f"rejection-seed{current}.json.gz"
                                ),
                                "wt",
                                encoding="utf-8",
                                compresslevel=1,
                            ) as saved:
                                json.dump(
                                    result,
                                    saved,
                                    separators=(",", ":"),
                                    allow_nan=False,
                                )
                            rejection_saved = rejection_saved or save_rejection
                        if (
                            time.monotonic() - shot_start
                            > config["case_timeout_seconds"]
                        ):
                            raise TimeoutError(
                                f"SHOT_WALL_TIMEOUT: metrics/serialization; seed={current}; budget={config['case_timeout_seconds']}s"
                            )
                        record["software_seconds"] = time.monotonic() - shot_start
                        record["peak_rss_kib"] = peak_rss_kib()
                        stream.write(
                            json.dumps(record, separators=(",", ":"), allow_nan=False)
                            + "\n"
                        )
                        stream.flush()
                        rows.append(values)
                        del result, events, calls, record
                        gc.collect()

            if identity != {k: id(v) for k, v in catalog.entries.items()} or any(
                guards.values()
            ):
                raise RuntimeError("CATALOG_REBUILD_OR_FORBIDDEN_ATOM_WORK")
        if sources != _sources():
            raise RuntimeError("SOURCE_CHANGED_DURING_SCAN_CELL")
        if any(
            hashlib.sha256(p.read_bytes()).hexdigest() != source_checks[p.name]
            for p in scan_paths
        ):
            raise RuntimeError("SCAN_SOURCE_CHANGED_DURING_CELL")
        _write(
            directory / "summary.json",
            {
                "status": "complete",
                "cell": cell,
                "execution_scope": config.get("execution_scope", "complete_scan_cell"),
                "statistics": aggregate(rows),
                "geometry": geometry,
                "catalog_sha256": catalog.fingerprint,
                "raw_probability": catalog.raw_probability,
                "reuse": {
                    "scope": "newly_executed_shots_in_this_worker",
                    "templates": len(catalog.entries),
                    "lookups": catalog.lookups,
                    "cache_hits": catalog.bound_cost_hits,
                    "numeric_bindings": catalog.bound_cost_misses,
                    "identities_preserved": True,
                    **guards,
                },
                "software_seconds": time.monotonic() - started,
                "continuation": provenance,
                "peak_rss_kib": peak_rss_kib(),
            },
        )
        _write(
            directory / "progress.json",
            {
                "status": "complete",
                "seed": current,
                "completed": len(rows),
                "cell": cell["id"],
            },
        )
    except BaseException as error:
        _write(
            directory / "error.json",
            {
                "status": "error",
                "cell": cell,
                "seed": current,
                "type": type(error).__name__,
                "reason": str(error),
                "cause_type": getattr(error, "cause_type", type(error).__name__),
                "diagnostics": getattr(error, "diagnostics", None),
                "software_seconds": time.monotonic() - started,
                "partial_output_is_success": False,
            },
        )
        raise


def select_cpus(config: dict[str, Any]) -> list[int]:
    """Use at most the requested fraction of visible physical cores, one thread each."""
    fraction = config["cpu_fraction"]
    if not 0 < fraction <= 0.8:
        raise ValueError("CPU_FRACTION_EXCEEDS_AUTHORIZED_80_PERCENT")
    getter = getattr(os, "sched_getaffinity", None)
    if not callable(getter):
        raise TypeError("LINUX_SERVER_COORDINATOR_REQUIRED")
    allowed = getter(0)
    lines = subprocess.check_output(
        ["lscpu", "-p=CPU,CORE,SOCKET"], text=True
    ).splitlines()
    cores: dict[tuple[int, int], int] = {}
    for line in lines:
        if line.startswith("#"):
            continue
        cpu, core, socket = map(int, line.split(","))
        if cpu in allowed:
            cores.setdefault((socket, core), cpu)
    if not cores or config["worker_cap"] < 1:
        raise ValueError("NO_AUTHORIZED_WORKER_CPU")
    sockets: dict[int, list[int]] = {}
    for (socket, _), cpu in sorted(cores.items()):
        sockets.setdefault(socket, []).append(cpu)
    ordered = [
        cpus[i]
        for i in range(max(map(len, sockets.values())))
        for cpus in sockets.values()
        if i < len(cpus)
    ]
    return ordered[: max(1, min(config["worker_cap"], int(len(cores) * fraction)))]


def _stop_children(active: list[dict[str, Any]]) -> None:
    for job in active:
        process = job["process"]
        if process.poll() is None:
            try:
                if sys.platform == "win32":
                    process.terminate()
                else:
                    os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                # This owned child exited between poll and signal delivery.
                pass
    for job in active:
        process = job["process"]
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            if sys.platform == "win32":
                process.kill()
            else:
                os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)


def coordinate(config: dict[str, Any], config_path: Path, output: Path) -> None:
    """Execute this finite matrix with fail-stop child ownership and a wall cap."""
    cells = make_cells(config)
    cpus = select_cpus(config)
    if config.get("schema") == "nadit.level2_object_scan/1" and not os.environ.get(
        "NADIT_SOURCE_COMMIT"
    ):
        raise ValueError("FROZEN_SOURCE_COMMIT_REQUIRED")
    if (
        config.get("schema") == "nadit.level2_object_scan/1"
        and len(cpus) != config["worker_cap"]
    ):
        raise ValueError("REQUESTED_89_PHYSICAL_WORKERS_NOT_AVAILABLE")
    continuation = None
    if config.get("continuation_from"):
        from modules.logical_compiler.examples.object_cases import _sources

        origin = Path(config["continuation_from"])
        manifest_bytes = (origin / "manifest.json").read_bytes()
        old = json.loads(manifest_bytes)
        if old["source_commit"] != config["continuation_source_commit"]:
            raise ValueError("CONTINUATION_SOURCE_COMMIT_MISMATCH")
        budget_keys = {
            "case_timeout_seconds",
            "shot_timeout_seconds",
            "cell_wall_seconds",
        }
        if old["cells"] != cells or any(
            config.get(k) != v
            for k, v in old["configuration"].items()
            if k not in budget_keys
        ):
            raise ValueError("CONTINUATION_CONFIGURATION_MISMATCH")
        if not (origin / "error.json").exists():
            raise ValueError("CONTINUATION_REQUIRES_STOPPED_SOURCE")
        source_hashes = {
            "runtime": _sources(),
            "scan": {
                name: hashlib.sha256(
                    Path(__file__).with_name(name).read_bytes()
                ).hexdigest()
                for name in ("scan_metrics.py", "object-motion-reference.json")
            },
        }
        prefixes = {
            cell["id"]: continuation_records(config, cell["id"], source_hashes)[1]
            for cell in cells
        }
        continuation = {
            "source": str(origin),
            "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            "imported_shots": sum(p["imported_shots"] for p in prefixes.values()),
            "cells": prefixes,
        }
    output.mkdir(parents=True, exist_ok=False)
    _write(
        output / "manifest.json",
        {
            "configuration": config,
            "cells": cells,
            "cpu_ids": cpus,
            "physical_workers": len(cpus),
            "started_unix": time.time(),
            "python": sys.executable,
            "source_commit": os.environ.get("NADIT_SOURCE_COMMIT"),
            "continuation": continuation,
            "motion_reference_sha256": hashlib.sha256(
                Path(__file__).with_name("object-motion-reference.json").read_bytes()
            ).hexdigest(),
        },
    )
    active: list[dict[str, Any]] = []
    completed = []
    cursor = 0
    started = time.monotonic()
    last = -1.0
    env = dict(os.environ)
    for key in (
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
    ):
        env[key] = "1"
    try:
        while active or cursor < len(cells):
            # Do not dispatch after an already observable child failure.
            for job in active:
                code = job["process"].poll()
                if code is not None and code != 0:
                    reason_path = output / "cells" / job["cell"]["id"] / "error.json"
                    reason = (
                        reason_path.read_text()
                        if reason_path.exists()
                        else f"exit={code}; inspect worker.log"
                    )
                    raise RuntimeError(f"CELL_FAILED: {job['cell']['id']}; {reason}")
            while cursor < len(cells) and len(active) < len(cpus):
                cell = cells[cursor]
                cursor += 1
                directory = output / "cells" / cell["id"]
                directory.mkdir(parents=True)
                cpu = next(c for c in cpus if c not in {j["cpu"] for j in active})
                log = (directory / "worker.log").open("w")
                process = subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "experiments.msd.scan_objects",
                        "--config",
                        str(config_path),
                        "--output",
                        str(output),
                        "--cell",
                        cell["id"],
                        "--cpu",
                        str(cpu),
                    ],
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    env=env,
                    start_new_session=True,
                )
                active.append(
                    {
                        "process": process,
                        "log": log,
                        "cpu": cpu,
                        "cell": cell,
                        "started": time.monotonic(),
                    }
                )
            now = time.monotonic()
            if now - started > config["scan_wall_seconds"]:
                raise TimeoutError("SCAN_WALL_TIMEOUT")
            for job in list(active):
                code = job["process"].poll()
                if code is None:
                    if now - job["started"] > config["cell_wall_seconds"]:
                        raise TimeoutError(f"CELL_WALL_TIMEOUT: {job['cell']['id']}")
                    continue
                job["log"].close()
                if code:
                    path = output / "cells" / job["cell"]["id"] / "error.json"
                    reason = (
                        path.read_text()
                        if path.exists()
                        else f"exit={code}; inspect worker.log"
                    )
                    raise RuntimeError(f"CELL_FAILED: {job['cell']['id']}; {reason}")
                completed.append(job["cell"]["id"])
                active.remove(job)
            if now - last >= 5:
                shots = len(completed) * config["seed_count"]
                for job in active:
                    path = output / "cells" / job["cell"]["id"] / "progress.json"
                    if path.exists():
                        shots += json.loads(path.read_text())["completed"]
                _write(
                    output / "progress.json",
                    {
                        "status": "running",
                        "complete_cells": len(completed),
                        "total_cells": len(cells),
                        "complete_shots": shots,
                        "total_shots": len(cells) * config["seed_count"],
                        "active": len(active),
                        "wall_seconds": now - started,
                    },
                )
                last = now
            if active:
                time.sleep(0.25)
        _write(
            output / "summary.json",
            {
                "status": "complete",
                "cells": len(cells),
                "shots": len(cells) * config["seed_count"],
                "wall_seconds": time.monotonic() - started,
                "configuration": config,
            },
        )
        _write(
            output / "progress.json",
            {
                "status": "complete",
                "complete_cells": len(cells),
                "complete_shots": len(cells) * config["seed_count"],
                "wall_seconds": time.monotonic() - started,
            },
        )
    except BaseException as error:
        _stop_children(active)
        _write(
            output / "error.json",
            {
                "status": "error",
                "reason": str(error),
                "type": type(error).__name__,
                "completed_cells": completed,
                "wall_seconds": time.monotonic() - started,
                "partial_output_is_success": False,
            },
        )
        _write(
            output / "progress.json",
            {"status": "error", "reason": str(error), "complete_cells": len(completed)},
        )
        raise
    finally:
        for job in active:
            job["log"].close()


def main() -> None:
    """Run one explicit scan or its owned worker; no automatic retries/resume."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cell")
    parser.add_argument("--cpu", type=int)
    parser.add_argument(
        "--one-shot",
        action="store_true",
        help="Bounded cell control; never a completed scan",
    )
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    if config.get("schema") == "nadit.level2_object_scan/1":
        validate_level2_config(config)
    elif (
        config.get("schema") != "nadit.object_scan/1"
        or type(config["seed_count"]) is not int
        or config["seed_count"] < 1
        or config.get("rounds_per_factory") != 1
        or config.get("production_basis") != "production_rounds"
        or config.get("wave_timeout_seconds") != 5
    ):
        raise ValueError("INVALID_SCAN_CONFIGURATION")
    if args.one_shot:
        if not args.cell:
            raise ValueError("ONE_SHOT_REQUIRES_EXPLICIT_CELL")
        config = {
            **config,
            "seed_count": 1,
            "execution_scope": "bounded_one_shot_control",
        }
    if args.cell:
        cell = next(c for c in make_cells(config) if c["id"] == args.cell)
        run_worker(config, cell, args.output / "cells" / cell["id"], args.cpu)
    else:

        def interrupted(signum: int, frame: Any) -> None:
            raise KeyboardInterrupt(f"scan interrupted by signal {signum}")

        signal.signal(signal.SIGTERM, interrupted)
        coordinate(config, args.config.resolve(), args.output.resolve())


if __name__ == "__main__":
    main()
