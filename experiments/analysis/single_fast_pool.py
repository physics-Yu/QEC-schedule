"""Pool frozen fast trajectories without changing scientific execution or identity."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Iterable
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from pathlib import Path
from typing import Any

from nadit_physical_compiler.experiments.journal import directory_lock, write_json

from experiments.msd import single_fast as runner
from modules.logical_compiler.src.protocols.production import ProductionPolicy

_CONTEXT: dict[str, Any] = {}
Task = dict[str, Any]
Reporter = Callable[[Task], None]


def _initialize_worker(context: dict[str, Any]) -> None:
    global _CONTEXT
    _CONTEXT = context


def _execute_task(task: dict[str, Any]) -> dict[str, Any]:
    context, config = _CONTEXT, _CONTEXT["config"]
    distance, count, seed = (task[key] for key in ("distance", "factory_count", "seed"))
    cell = context["output"] / "cells" / f"d{distance}-n{count}"
    pilot = task["kind"] == "pilot"
    directory = cell / ("pilot" if pilot else f"seed-{seed:04d}")
    with directory_lock(directory):
        reused = (directory / "completion.json").exists()
        record = runner._run_once(
            context,
            directory,
            distance,
            count,
            seed,
            ProductionPolicy(task["max_cycles"], task["stop_at_us"]),
            warmup_us=task["warmup_us"],
        )
    result = {
        **task,
        "status": record["status"],
        "reused": reused,
        "accepted_outputs": record["metrics"]["accepted_outputs"],
        "window_complete": record["metrics"]["requested_window_complete"],
    }
    if pilot:
        try:
            policy = runner.freeze_observation(record, config, count)
            name, document = "observation.json", policy
            result.update(status="pilot_ready", policy=policy)
        except ValueError as error:
            name = "excluded.json"
            document = {
                "status": "pilot_excluded",
                "reason": str(error),
                "distance": distance,
                "factory_count": count,
                "identity": context["identity"],
            }
            result.update(status="pilot_excluded", reason=str(error))
        with directory_lock(cell):
            path = cell / name
            if path.exists():
                if runner._read(path) != document:
                    raise ValueError("POOL_FROZEN_PILOT_DOCUMENT_CHANGED")
            else:
                runner._write_new(path, document)
    return result


def _phase(
    executor: Any, tasks: Iterable[Task], workers: int, report: Reporter
) -> list[Task]:
    iterator, pending, results = iter(tasks), set(), []
    try:
        for _ in range(workers):
            task = next(iterator, None)
            if task is not None:
                pending.add(executor.submit(_execute_task, task))
        while pending:
            done, pending = wait(pending, return_when=FIRST_COMPLETED)
            completed = [future.result() for future in done]
            for result in completed:
                results.append(result)
                report(result)
            for _ in completed:
                task = next(iterator, None)
                if task is not None:
                    pending.add(executor.submit(_execute_task, task))
    except BaseException:
        for future in pending:
            future.cancel()
        raise
    return results


def _task(
    distance: int, count: int, seed: int, cycles: int, policy: Task | None = None
) -> Task:
    return {
        "kind": "pilot" if policy is None else "production",
        "distance": distance,
        "factory_count": count,
        "seed": seed,
        "max_cycles": cycles,
        "stop_at_us": None if policy is None else policy["stop_us"],
        "warmup_us": 0 if policy is None else policy["warmup_us"],
    }


def run_pool(config_path: Path, output: Path, workers: int = 2) -> dict[str, Any]:
    """Run pilots then seed-major cell interleaving through unchanged fast helpers."""
    if type(workers) is not int or not 1 <= workers <= 4:
        raise ValueError("POOL_WORKERS_MUST_BE_BETWEEN_ONE_AND_FOUR")
    context = runner._initialize(config_path, output)
    config = context["config"]
    acceptance = runner._read(output / "smoke/acceptance.json")
    smoke = runner._verified_completion(output / "smoke", context["identity"])
    if (
        acceptance.get("identity") != context["identity"]
        or acceptance.get("passed") is not True
        or smoke is None
        or acceptance.get("completion_sha256") != runner.reference_digest(smoke)
    ):
        raise ValueError("SOURCE_MATCHED_SMOKE_ACCEPTANCE_REQUIRED")
    control_path = output / "pool-control.json"
    orchestration = {
        "script": Path(__file__).relative_to(runner._ROOT).as_posix(),
        "script_bytes_sha256": runner._sha(Path(__file__)),
        "workers": workers,
    }
    frozen = {"identity": context["identity"], "orchestration": orchestration}
    cells = [(d, n) for d in config["distances"] for n in config["factory_counts"]]
    with directory_lock(output / "pool-control"):
        previous = runner._read(control_path) if control_path.exists() else frozen
        if any(previous.get(key) != value for key, value in frozen.items()):
            raise ValueError("POOL_ORCHESTRATION_IDENTITY_CHANGED")
        control = {"schema": "nadit.single_fast_pool/1", **frozen}
        control.update(status="running", phase="pilots", completed_tasks=[])

        def report(result: dict[str, Any]) -> None:
            control["completed_tasks"].append(result)
            write_json(control_path, control)
            print(json.dumps(result, allow_nan=False), flush=True)

        write_json(control_path, control)
        try:
            pilot_cycles = config["observation"]["pilot_cycles"]
            max_cycles = config["limits"]["max_cycles"]
            pilots_to_run = [
                _task(d, n, config["pilot_seed"], pilot_cycles) for d, n in cells
            ]
            with ProcessPoolExecutor(
                max_workers=workers, initializer=_initialize_worker, initargs=(context,)
            ) as executor:
                pilots = _phase(executor, pilots_to_run, workers, report)
                policies = {
                    (row["distance"], row["factory_count"]): row["policy"]
                    for row in pilots
                    if row["status"] == "pilot_ready"
                }
                control["phase"] = "production"
                write_json(control_path, control)
                jobs = (
                    _task(d, n, seed, max_cycles, policies[d, n])
                    for seed in config["production_seeds"]
                    for d, n in cells
                    if (d, n) in policies
                )
                _phase(executor, jobs, workers, report)
            summary = runner.summarize_campaign(config_path, output)
            control.update(status="complete", phase="finished")
            control["report_directory"] = summary["report_directory"]
            write_json(control_path, control)
            return summary
        except BaseException as error:
            control.update(
                status="failed", error_type=type(error).__name__, error=str(error)
            )
            write_json(control_path, control)
            raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=2, choices=range(1, 5))
    args = parser.parse_args()
    summary = run_pool(args.config, args.output, args.workers)
    print(json.dumps({"report_directory": summary["report_directory"]}), flush=True)


if __name__ == "__main__":
    main()
