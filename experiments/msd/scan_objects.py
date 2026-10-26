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
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from .scan_metrics import MotionAccounting, aggregate, metrics


def _write(path: Path, value: Any) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, allow_nan=False), encoding="utf-8")
    temp.replace(path)


def make_cells(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Enumerate all full rectangular layouts; merge only exact column aliases."""
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


def run_worker(
    config: dict[str, Any],
    cell: dict[str, Any],
    directory: Path,
    cpu: int | None = None,
) -> None:
    """Run fixed seeds with one catalog; any error writes context and propagates."""
    from modules.codes.rotated_surface.object_factory import FactoryObjectCatalog
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
    started = time.monotonic()
    current: int | None = None
    try:
        sources = _sources()
        with forbid_atom_work() as guards:
            catalog = FactoryObjectCatalog.load(distance=cell["distance"])
            accounting = MotionAccounting(catalog)
            identity = {k: id(v) for k, v in catalog.entries.items()}
            rows: list[dict[str, Any]] = []
            geometry = None
            with (directory / "shots.jsonl").open("x", encoding="utf-8") as stream:
                for current in range(
                    config["seed_start"], config["seed_start"] + config["seed_count"]
                ):
                    _write(
                        directory / "progress.json",
                        {
                            "status": "running",
                            "seed": current,
                            "completed": len(rows),
                            "cell": cell["id"],
                        },
                    )
                    shot_start = time.monotonic()
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
                    }
                    if current == config["seed_start"]:
                        geometry = result["layout"]
                        with gzip.open(
                            directory / "representative.json.gz",
                            "wt",
                            encoding="utf-8",
                            compresslevel=1,
                        ) as saved:
                            json.dump(
                                result, saved, separators=(",", ":"), allow_nan=False
                            )
                    if time.monotonic() - shot_start > config["case_timeout_seconds"]:
                        raise TimeoutError(
                            f"SHOT_WALL_TIMEOUT: metrics/serialization; seed={current}; budget={config['case_timeout_seconds']}s"
                        )
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
        _write(
            directory / "summary.json",
            {
                "status": "complete",
                "cell": cell,
                "statistics": aggregate(rows),
                "geometry": geometry,
                "catalog_sha256": catalog.fingerprint,
                "raw_probability": catalog.raw_probability,
                "reuse": {
                    "templates": len(catalog.entries),
                    "lookups": catalog.lookups,
                    "cache_hits": catalog.bound_cost_hits,
                    "numeric_bindings": catalog.bound_cost_misses,
                    "identities_preserved": True,
                    **guards,
                },
                "software_seconds": time.monotonic() - started,
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
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    if (
        config.get("schema") != "nadit.object_scan/1"
        or type(config["seed_count"]) is not int
        or config["seed_count"] < 1
        or config.get("rounds_per_factory") != 1
        or config.get("production_basis") != "production_rounds"
        or config.get("wave_timeout_seconds") != 5
    ):
        raise ValueError("INVALID_SCAN_CONFIGURATION")
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
