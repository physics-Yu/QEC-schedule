"""Bounded local object-scheduler acceptance; no complete MSD performance claims."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import asdict, replace
from hashlib import sha256
from html import escape
from math import isfinite
from pathlib import Path
from time import perf_counter
from typing import Any
from unittest.mock import patch

from nadit_physical_compiler.atom_ir import AtomProgram
from nadit_physical_compiler.device import Position
from nadit_physical_compiler.state import AtomState

from modules.codes.contracts.factory_recipe import ComponentCall
from modules.codes.rotated_surface.fast_factory import required_variants
from modules.codes.rotated_surface.object_readout import (
    SurfaceReadoutCatalog,
    SurfaceReadoutProfile,
)
from modules.logical_compiler.src.estimation.kernel import ProfileExecutionKernel
from modules.logical_compiler.src.protocols.execution_kernel import ExecutionRequest
from modules.logical_compiler.src.scheduling import ComponentNode, ComponentScheduler

from .object_fixtures import FixtureCatalog, run_retry_case

ROOT = Path(__file__).resolve().parents[3]


def _write(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )


def _read_progress(output: Path) -> dict[str, Any]:
    try:
        value: dict[str, Any] = json.loads((output / "progress.json").read_text())
        return value
    except (OSError, ValueError):
        return {"stage": "startup_or_incomplete_progress_record"}


def _record_error(output: Path, document: dict[str, Any]) -> None:
    """Invalidate any early success marker, including a partially written file."""
    _write(output / "error.json", document)
    path = output / "summary.json"
    if path.exists():
        try:
            previous = json.loads(path.read_text())
        except (OSError, ValueError):
            previous = {"previous_summary_unreadable": True}
        _write(
            path, {**previous, "status": "error", "invalidated_by": document["code"]}
        )


@contextmanager
def forbid_atom_work() -> Iterator[dict[str, int]]:
    """Instrument and reject compiler, atom construction and expansion entry points."""
    import nadit_physical_compiler.compiler as compiler

    import modules.codes._support.atom_template as templates

    counters = {
        "physical_compile_attempts": 0,
        "atom_expansion_attempts": 0,
        "atom_construction_attempts": 0,
    }

    def reject(kind: str) -> Any:
        def fail(*args: Any, **kwargs: Any) -> None:
            counters[kind] += 1
            raise RuntimeError(f"FORBIDDEN_SCAN_WORK: {kind}; object run aborted")

        return fail

    with ExitStack() as stack:
        for owner, name, kind in (
            (compiler, "compile_physical", "physical_compile_attempts"),
            (templates, "compile_physical", "physical_compile_attempts"),
            (templates, "compile_template", "physical_compile_attempts"),
            (templates.BoundAtomComponent, "expand", "atom_expansion_attempts"),
            (templates.AtomComponentTemplate, "bind", "atom_expansion_attempts"),
            (AtomState, "__post_init__", "atom_construction_attempts"),
            (AtomProgram, "__post_init__", "atom_construction_attempts"),
        ):
            stack.enter_context(patch.object(owner, name, reject(kind)))
        yield counters


def run_readout_case(
    catalog: SurfaceReadoutCatalog,
    *,
    distance: int = 3,
    factories: int = 2,
    shifted: bool = False,
) -> dict[str, Any]:
    """Schedule the same MZ object for each factory's W2 carrier on one AOD."""
    layout = catalog.layout(distance, factories)
    if shifted:
        if factories != 2:
            raise ValueError("CONFLICT_WITNESS_REQUIRES_TWO_FACTORIES")
        first, second = layout.factories
        second = replace(
            second,
            patches=tuple(
                replace(p, origin=Position(p.origin.x + 20, p.origin.y))
                for p in second.patches
            ),
        )
        budget = dict(layout.budget)
        budget["storage_bounds_um"] = [
            *budget["storage_bounds_um"][:2],
            budget["storage_bounds_um"][2] + 20,
            0,
        ]
        budget["placement_fingerprint"] = None
        budget["placement_override"] = "factory1 translated +20 um in x"
        layout = replace(layout, factories=(first, second), budget=budget)
    profile = SurfaceReadoutProfile(catalog, layout)
    execution = ProfileExecutionKernel(profile, layout)
    scheduler = ComponentScheduler()
    call = ComponentCall("mz", "logical_mz", ("W2",))
    requests = tuple(
        ExecutionRequest(f.factory_id + "/mz", None, call, (f.bindings["W2"].block_id,))
        for f in layout.factories
    )
    scheduler.add(
        *(
            ComponentNode(
                r.invocation_id, execution.describe(None, call, r.participant_blocks)
            )
            for r in requests
        )
    )
    admission = scheduler.admit(0, snapshot_id=execution.snapshot_id)
    assert admission is not None
    execution.execute(admission, requests)
    scheduler.commit_admission(admission)
    for request in requests:
        scheduler.mark_completed(
            request.invocation_id, execution.source(request.invocation_id).action_end_us
        )
    return {
        "scope": "single_MZ_wave_not_full_factory",
        "distance": distance,
        "factories": factories,
        "layout": {
            "budget": layout.budget,
            "patches": [asdict(p) for f in layout.factories for p in f.patches],
        },
        "profile_sha256": profile.profile_sha256,
        "execution": execution.snapshot(),
        "schedule": scheduler.snapshot(),
    }


def _sources() -> dict[str, str]:
    paths = [
        p
        for directory in (
            "modules/codes",
            "modules/logical_compiler/src",
            "modules/logical_compiler/examples",
        )
        for p in (ROOT / directory).rglob("*.py")
        if "tests" not in p.parts
    ]
    return {
        p.relative_to(ROOT).as_posix(): sha256(p.read_bytes()).hexdigest()
        for p in sorted(paths)
    }


def run_cases(configuration: dict[str, Any], output: Path) -> dict[str, Any]:
    """Prepare once; stop on the first failed case and retain scope evidence."""
    started = perf_counter()
    if configuration.get("schema") != "nadit.msd.object_acceptance/1":
        raise ValueError("UNSUPPORTED_LOCAL_ACCEPTANCE_CONFIG")
    source_before = _sources()
    prepare_started = perf_counter()
    catalog = SurfaceReadoutCatalog(tuple(configuration["distances"]))
    fixture = FixtureCatalog(catalog)
    prepared_seconds = perf_counter() - prepare_started
    initial_ids = {str(d): id(e) for d, e in catalog.entries.items()}
    fixture_ids = tuple(map(id, fixture.entries.values()))
    timings: dict[str, float] = {}
    stages: dict[str, Any] = {}
    scaling = []

    def begin(name: str) -> float:
        _write(output / "progress.json", {"stage": name, "state": "running"})
        return perf_counter()

    with forbid_atom_work() as guards:
        t = begin("synchronous")
        stages["synchronous"] = run_readout_case(catalog)
        timings["synchronous"] = perf_counter() - t
        t = begin("resource_conflict")
        stages["resource_conflict"] = run_readout_case(catalog, shifted=True)
        timings["resource_conflict"] = perf_counter() - t
        t = begin("postselection_retry_offset")
        retry = configuration["retry_fixture"]
        stages["postselection_retry_offset"] = run_retry_case(fixture, **retry)
        if stages["postselection_retry_offset"]["status"] != "complete":
            raise RuntimeError("RETRY_ACCEPTANCE_FAILED: inspect fixture case")
        timings["postselection_retry_offset"] = perf_counter() - t
        t = begin("component_reuse_scaling")
        for distance in configuration["distances"]:
            for count in configuration["factory_counts"]:
                row_started = perf_counter()
                case = run_readout_case(catalog, distance=distance, factories=count)
                scaling.append(
                    {
                        "distance": distance,
                        "factories": count,
                        "model_time_us": case["execution"]["waves"][0]["end_us"],
                        "software_wall_seconds": perf_counter() - row_started,
                        "allocated_atoms": case["layout"]["budget"][
                            "atom_count_estimate"
                        ],
                        "scope": "single_MZ_wave_not_factory_throughput",
                    }
                )
        for seed in configuration["reuse_seeds"]:
            case = run_retry_case(
                fixture,
                factories=4,
                seed=seed,
                reject_attempts=2,
                cycles=1,
                timeout_seconds=retry["timeout_seconds"],
            )
            if case["status"] != "complete":
                raise RuntimeError("REUSE_ACCEPTANCE_FAILED")
        timings["reuse_scaling"] = perf_counter() - t
    if source_before != _sources():
        raise RuntimeError("SOURCE_CHANGED_DURING_LOCAL_ACCEPTANCE")
    preserved = initial_ids == {
        str(d): id(e) for d, e in catalog.entries.items()
    } and fixture_ids == tuple(map(id, fixture.entries.values()))
    if not preserved or any(guards.values()):
        raise RuntimeError("COMPONENT_REUSE_INVARIANT_FAILED")
    summary = {
        "schema": "nadit.msd.object_acceptance_result/1",
        "status": "complete",
        "scope": "three_local_acceptance_cases_only",
        "configuration": configuration,
        "full_factory_scaling_run": False,
        "catalog_coverage": {
            str(distance): {
                "prepared": ["logical_mz"],
                "pending": sorted(
                    {name for name, _ in required_variants(distance)} - {"logical_mz"}
                ),
            }
            for distance in configuration["distances"]
        },
        "steady_state_throughput": None,
        "actual_output_LER": None,
        "physical_validation": "not_run",
        "timing_parameters": asdict(catalog.timing),
        "component_preparation_seconds": prepared_seconds,
        "software_wall_seconds": perf_counter() - started,
        "timings_seconds": timings,
        "reuse": {
            "surface_templates_built": catalog.template_builds,
            "fixture_templates_built": fixture.template_builds,
            "surface_lookups": catalog.lookups,
            "fixture_lookups": fixture.lookups,
            "same_objects_preserved": preserved,
            **guards,
        },
        "readout_scaling": scaling,
        "limitations": [
            "Readout timings use a rigid transport estimate, not validated "
            "atom schedules.",
            "Retry and production times/probabilities are explicit test fixtures.",
            "Complete factory component profiles and exposure-dependent raw "
            "acceptance remain pending.",
        ],
    }
    export_started = perf_counter()
    for name, case in stages.items():
        _write(output / (name + ".json"), case)
    _write(output / "source-hashes.json", source_before)
    _report(output, summary, stages)
    summary["export_wall_seconds"] = perf_counter() - export_started
    summary["total_worker_work_seconds"] = perf_counter() - started
    _write(output / "summary.json", summary)
    _write(output / "progress.json", {"stage": "complete", "state": "complete"})
    return summary


def _report(output: Path, summary: dict[str, Any], cases: dict[str, Any]) -> None:
    sections = []
    for name, case in cases.items():
        rows = []
        for wave in case["execution"]["waves"]:
            for stage in wave["stage_schedule"]:
                rows.append(
                    "<tr>"
                    + "".join(
                        f"<td>{escape(str(value))}</td>"
                        for value in (
                            wave["start_us"] + stage["start_us"],
                            wave["start_us"] + stage["end_us"],
                            stage["phase"],
                            ", ".join(stage["members"]),
                            ", ".join(stage["resources"]),
                        )
                    )
                    + "</tr>"
                )
        sections.append(
            f"<h2>{escape(name)}</h2><table><tr><th>Start (us)</th><th>End (us)</th>"
            "<th>Phase</th><th>Members</th><th>Resources</th></tr>"
            + "".join(rows)
            + "</table>"
        )
    text = (
        "<!doctype html><meta charset='utf-8'><title>MSD local object "
        "acceptance</title>"
        "<style>body{font:14px "
        "system-ui;margin:32px;max-width:1500px}table{border-collapse:collapse}"
        "td,th{border:1px solid "
        "#aaa;padding:6px;text-align:left}td{overflow-wrap:anywhere}"
        "pre{white-space:pre-wrap}</style><h1>MSD local object acceptance</h1>"
        "<p>Same components only; one shared AOD. These are acceptance cases, "
        "not full factory throughput. "
        "Retry timings and probabilities are synthetic fixtures. Physical "
        "validation was not run.</p>"
        f"<pre>{escape(json.dumps(summary['reuse'], indent=2))}</pre>"
        + "".join(sections)
    )
    (output / "schedule.html").write_text(text, encoding="utf-8")


def execute_worker(command: list[str], output: Path, timeout_seconds: float) -> int:
    """Enforce a wall deadline; record reason and logs, never continue after timeout."""
    if (
        type(timeout_seconds) not in (int, float)
        or not isfinite(timeout_seconds)
        or timeout_seconds <= 0
    ):
        _record_error(
            output,
            {
                "status": "error",
                "code": "INVALID_WALL_TIMEOUT",
                "reason": "A finite positive wall timeout is required",
            },
        )
        return 2
    started = perf_counter()
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            cwd=ROOT,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        _record_error(
            output,
            {
                "status": "error",
                "code": "LOCAL_CASE_TIMEOUT",
                "reason": f"Wall budget {timeout_seconds}s exceeded; worker terminated",
                "last_progress": _read_progress(output),
                "elapsed_wall_seconds": perf_counter() - started,
                "partial_output_is_success": False,
            },
        )
        (output / "worker.stdout.log").write_bytes(error.stdout or b"")
        (output / "worker.stderr.log").write_bytes(error.stderr or b"")
        return 124
    (output / "worker.stdout.log").write_text(result.stdout, encoding="utf-8")
    (output / "worker.stderr.log").write_text(result.stderr, encoding="utf-8")
    _write(
        output / "worker.json",
        {
            "returncode": result.returncode,
            "wall_seconds": perf_counter() - started,
            "wall_timeout_seconds": timeout_seconds,
            "includes_startup_and_imports": True,
        },
    )
    if result.returncode and not (output / "error.json").exists():
        _record_error(
            output,
            {
                "status": "error",
                "code": "LOCAL_CASE_WORKER_FAILED",
                "returncode": result.returncode,
                "reason": result.stderr,
            },
        )
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    output = args.output.resolve()
    if args.worker:
        try:
            summary = run_cases(config, output)
            print(json.dumps({"status": summary["status"], "reuse": summary["reuse"]}))
            return 0
        except Exception as error:
            _record_error(
                output,
                {
                    "status": "error",
                    "code": type(error).__name__,
                    "reason": str(error),
                    "last_progress": _read_progress(output),
                    "partial_output_is_success": False,
                },
            )
            raise
    output.mkdir(parents=True, exist_ok=False)
    code = execute_worker(
        [
            sys.executable,
            "-m",
            "modules.logical_compiler.examples.object_cases",
            "--config",
            str(args.config.resolve()),
            "--output",
            str(output),
            "--worker",
        ],
        output,
        config["wall_timeout_seconds"],
    )
    print(
        json.dumps(
            {
                "status": "complete" if code == 0 else "error",
                "exit_code": code,
                "report": str(output / ("summary.json" if code == 0 else "error.json")),
            }
        )
    )
    return code


if __name__ == "__main__":
    raise SystemExit(main())
