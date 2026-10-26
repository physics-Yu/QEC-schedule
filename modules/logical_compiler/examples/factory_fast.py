"""Fast d3 factory experiments from an explicitly supplied offline calibration.

Run and sweep never compile atoms. Calibrate is a separate, deliberately slow
operation over a previously validated physical experiment and finite templates.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean
from time import perf_counter
from typing import Any

from modules.codes.rotated_surface_d3.protocols.factory_experiment import (
    ExperimentMode,
    FactoryExperimentModel,
)
from modules.codes.rotated_surface_d3.protocols.fast_backend import FastCostBackend
from modules.codes.rotated_surface_d3.protocols.fast_profile import (
    FastProfile,
    load_fast_profile,
    make_fast_layout,
)
from modules.logical_compiler.src.estimation.kernel import ProfileExecutionKernel
from modules.logical_compiler.src.estimation.metrics import summarize_samples
from modules.logical_compiler.src.protocols.array_ledger import build_array_ledger
from modules.logical_compiler.src.protocols.cooperative import CooperativeFactoryRuntime
from modules.logical_compiler.src.protocols.factory import FactoryLimits
from modules.logical_compiler.src.protocols.factory_process import FactoryProcess
from modules.logical_compiler.src.scheduling import ComponentScheduler

CODE_ID = "rotated_surface_d3"
EXPECTED_TERMINALS = {"complete", "distillation_rejected", "input_supply_exhausted"}


def _write(path: Path, data: Any) -> None:
    path.write_text(
        json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n",
        encoding="utf-8",
    )


def source_hashes() -> dict[str, str]:
    """Freeze this runtime and code sources separately from profile provenance."""
    root = Path(__file__).resolve().parents[3]
    paths = [
        p
        for directory in (
            "modules/logical_compiler/src",
            "modules/codes",
        )
        for p in (root / directory).rglob("*.py")
        if "tests" not in p.parts
    ]
    paths.extend((Path(__file__).resolve(), Path(__file__).with_name("fast_report.py")))
    return {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(paths)
    }


@dataclass(frozen=True)
class FastRun:
    """One complete logical trajectory plus scoped cost and accounting."""

    case: dict[str, Any]
    ledger: dict[str, Any]
    reports: dict[str, Any]
    summary: dict[str, Any]


def run_fast(
    profile: FastProfile,
    *,
    code: str,
    seed: int,
    factory_count: int = 2,
    aod_max_rows: int = 4,
    aod_max_columns: int = 48,
    max_readout_atoms: int = 96,
    limits: FactoryLimits | None = None,
    acceptance_model: ExperimentMode = "theory",
    input_z_error: float | None = None,
) -> FastRun:
    """Reuse the factory state machine without any physical execution kernel.

    Duration is model time; wall_seconds measures construction, scheduling,
    event/cost resolution and ledger projection, excluding profile load and I/O.
    Nonterminal/error statuses remain visible and are never counted as successes.
    """
    if code != CODE_ID or type(seed) is not int:
        raise ValueError("EXPLICIT_SUPPORTED_CODE_AND_INTEGER_SEED_REQUIRED")
    model = FactoryExperimentModel(acceptance_model, input_z_error)
    started = perf_counter()
    layout = make_fast_layout(
        profile,
        factory_count,
        aod_max_rows=aod_max_rows,
        aod_max_columns=aod_max_columns,
        max_readout_atoms=max_readout_atoms,
    )
    execution = ProfileExecutionKernel(profile, layout)
    adapters = {
        f.factory_id: FastCostBackend(
            profile, execution, factory_id=f.factory_id, experiment_model=model
        )
        for f in layout.factories
    }
    recipe = model.recipe()
    limits = limits or FactoryLimits(
        raw_attempts=8, batches=1, max_component_calls=2000
    )
    processes = tuple(
        FactoryProcess(
            f.factory_id,
            code=code,
            recipe=recipe,
            backend=adapters[f.factory_id],
            role_bindings={role: patch.block_id for role, patch in f.bindings.items()},
            distance=3,
            limits=limits,
            reference_parameters=model.parameters(profile.noise_params),
        )
        for f in layout.factories
    )
    runtime = CooperativeFactoryRuntime(
        execution=execution,
        case_id=model.case_id(),
        seed=seed,
        scheduler=ComponentScheduler(),
        processes=processes,
    )
    case = runtime.run().to_dict()
    case["experiment_model"] = model.to_dict()
    ledger = build_array_ledger(case)
    ledger["device_budget"] = layout.budget
    reports = {
        name: {
            "raw_horizons": list(adapter.raw_horizons.values()),
            "factory": adapter.factory_reports,
        }
        for name, adapter in adapters.items()
    }
    lines = {
        name: {key: value for key, value in row.items() if key != "state_intervals"}
        for name, row in ledger["lines"].items()
    }
    summary = {
        "schema": "nadit.fast_factory_run/1",
        "case_id": model.case_id(),
        "experiment_model": model.to_dict(),
        "code": code,
        "seed": seed,
        "factory_count": factory_count,
        "profile_sha256": profile.profile_sha256,
        "representation": "logical_estimate",
        "physical_validation": "not_run",
        "physical_validation_ok": None,
        "logical_success": None,
        "physical_execution": False,
        "status": case["status"],
        "execution_completed": all(
            row["status"] in EXPECTED_TERMINALS for row in lines.values()
        ),
        "configuration": {
            "code": code,
            "experiment_model": model.to_dict(),
            "device_budget": layout.budget,
            "limits": {
                "raw_attempts": limits.raw_attempts,
                "batches": limits.batches,
                "max_component_calls": limits.max_component_calls,
            },
        },
        "lines": lines,
        "counts": ledger["counts"],
        "outputs": ledger["counts"]["successful_lines"],
        "makespan_us": case["duration_us"],
        "accounting": case["execution"]["accounting"],
        "factory_acceptance_probabilities": {
            name: [
                report["factory_acceptance_probability"]
                for report in adapter.factory_reports.values()
            ]
            for name, adapter in adapters.items()
        },
        "physical_no_fault_diagnostics": {
            name: [
                row["report"]["metrics"]["no_fault_probability"]
                for row in adapter.factory_reports.values()
            ]
            for name, adapter in adapters.items()
        },
        "conditional_output_z_error": model.to_dict()["conditional_output_z_error"],
        "wave_count": len(case["component_schedule"]["admissions"]),
        "parallel_wave_count": sum(
            len(a["nodes"]) > 1 for a in case["component_schedule"]["admissions"]
        ),
        "wall_seconds": perf_counter() - started,
    }
    return FastRun(case, ledger, reports, summary)


def export_run(
    run: FastRun, output: Path, *, sampling_role: str = "individual_seed"
) -> None:
    """Keep full component, outcome and resource evidence for a selected run."""
    from .fast_report import write_run_report

    output.mkdir(parents=True, exist_ok=False)
    started = perf_counter()
    _write(output / "case.json", run.case)
    _write(output / "array-ledger.json", run.ledger)
    cost_name = (
        "physical-costs.json"
        if run.summary["experiment_model"]["mode"] == "theory"
        else "proxy-costs.json"
    )
    _write(output / cost_name, run.reports)
    _write(output / "summary.json", {**run.summary, "sampling_role": sampling_role})
    (output / "resource-events.jsonl").write_text(
        "".join(
            json.dumps(event, sort_keys=True, allow_nan=False) + "\n"
            for event in run.ledger["resources"]["audit"]
        ),
        encoding="utf-8",
    )
    write_run_report(run, output)
    _write(
        output / "export.json",
        {
            "export_wall_seconds": perf_counter() - started,
            "files_sha256": {
                p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(output.iterdir())
                if p.is_file()
            },
        },
    )


def sweep(
    profile: FastProfile,
    *,
    code: str,
    factory_counts: Sequence[int],
    seeds: Sequence[int],
    output: Path,
    aod_max_rows: int = 4,
    aod_max_columns: int = 48,
    max_readout_atoms: int = 96,
    detailed: bool = False,
    acceptance_model: ExperimentMode = "theory",
    input_z_error: float | None = None,
) -> dict[str, Any]:
    """Scan independent seeds at a fixed device capacity and expanding area.

    Each seed run, not each concurrent line, is a statistical unit. Per-run line
    ledgers and modeled costs are always retained; full trajectories are optional.
    Unexpected runtime failures invalidate statistics for that size, not vanish.
    """
    from .fast_report import write_sweep_report

    if (
        not factory_counts
        or not seeds
        or len(set(factory_counts)) != len(factory_counts)
        or len(set(seeds)) != len(seeds)
    ):
        raise ValueError("SCALING_REQUIRES_DISTINCT_NONEMPTY_COUNTS_AND_SEEDS")
    model = FactoryExperimentModel(acceptance_model, input_z_error)
    output.mkdir(parents=True, exist_ok=False)
    before = source_hashes()
    samples, aggregates = [], []
    for count in factory_counts:
        group = []
        for seed in seeds:
            run = run_fast(
                profile,
                code=code,
                seed=seed,
                factory_count=count,
                aod_max_rows=aod_max_rows,
                aod_max_columns=aod_max_columns,
                max_readout_atoms=max_readout_atoms,
                acceptance_model=acceptance_model,
                input_z_error=input_z_error,
            )
            identity = f"factories-{count}-seed-{seed}"
            _write(output / (identity + ".json"), run.summary)
            if detailed:
                export_run(run, output / identity, sampling_role="prespecified_sweep")
            samples.append(run.summary)
            group.append(run.summary)
        valid = all(row["execution_completed"] for row in group)
        aggregates.append(
            {
                **summarize_samples(group),
                **{
                    "mean_" + field: {
                        key: fmean(
                            row["accounting"][field].get(key, 0.0) for row in group
                        )
                        for key in sorted(
                            {key for row in group for key in row["accounting"][field]}
                        )
                    }
                    for field in (
                        "work_by_category_us",
                        "category_busy_us",
                        "resource_busy_us",
                    )
                },
                "mean_explicit_global_wait_us": fmean(
                    row["accounting"]["explicit_global_wait_us"] for row in group
                ),
                "statistics_valid": valid,
                "unexpected_statuses": [
                    row["seed"] for row in group if not row["execution_completed"]
                ],
            }
        )
        print(
            json.dumps(
                {
                    "factories": count,
                    "runs": len(group),
                    "statistics_valid": valid,
                    "compile_wall_seconds": sum(r["wall_seconds"] for r in group),
                }
            ),
            flush=True,
        )
    after = source_hashes()
    result = {
        "schema": "nadit.fast_factory_sweep/1",
        "representation": "logical_estimate",
        "code": code,
        "experiment_model": model.to_dict(),
        "profile_sha256": profile.profile_sha256,
        "seeds": list(seeds),
        "factory_counts": list(factory_counts),
        "device_capacity": {
            "aod_count": 1,
            "aod_max_rows": aod_max_rows,
            "aod_max_columns": aod_max_columns,
            "max_readout_atoms": max_readout_atoms,
        },
        "capacity_scales_with_factory_count": False,
        "area_scales_with_factory_count": True,
        "sampling_role": "prespecified_sweep",
        "statistics_unit": "independent_seed_trajectory",
        "physical_validation": "not_run",
        "logical_success": None,
        "source_start": before,
        "source_end": after,
        "source_stable": before == after,
        "groups": aggregates,
        "all_runs_completed": all(row["execution_completed"] for row in samples),
        "sample_files": [
            f"factories-{row['factory_count']}-seed-{row['seed']}.json"
            for row in samples
        ],
    }
    _write(output / "sweep.json", result)
    write_sweep_report(result, output)
    return result


def _integers(value: str) -> list[int]:
    """Parse comma-separated integers or an inclusive a..b range."""
    try:
        if ".." in value:
            a, b = (int(part) for part in value.split(".."))
            if b < a:
                raise ValueError
            return list(range(a, b + 1))
        return [int(part) for part in value.split(",")]
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "Use comma-separated integers or a..b"
        ) from error


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    calibration = sub.add_parser(
        "calibrate", help="Explicit offline physical calibration"
    )
    calibration.add_argument("--artifact", required=True, type=Path)
    calibration.add_argument("--output", required=True, type=Path)
    for command in ("run", "sweep"):
        item = sub.add_parser(command)
        item.add_argument("--code", choices=(CODE_ID,), required=True)
        item.add_argument("--profile", required=True, type=Path)
        item.add_argument("--output", required=True, type=Path)
        item.add_argument("--aod-rows", type=int, default=4)
        item.add_argument("--aod-columns", type=int, default=48)
        item.add_argument("--readout-atoms", type=int, default=96)
        item.add_argument(
            "--acceptance-model",
            choices=("theory", "physical_no_fault_proxy"),
            default="theory",
        )
        item.add_argument(
            "--input-z-error",
            type=float,
            help="Required for theory: iid Z error of accepted canonical raw A",
        )
        if command == "run":
            item.add_argument("--factories", type=int, default=2)
            item.add_argument("--seed", type=int, default=0)
            item.add_argument(
                "--sampling-role",
                choices=("individual_seed", "witness"),
                default="individual_seed",
            )
        else:
            item.add_argument("--factories", type=_integers, default=[1, 2, 4, 8, 16])
            item.add_argument("--seeds", type=_integers, default=list(range(16)))
            item.add_argument("--detailed", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "calibrate":
        from modules.codes.rotated_surface_d3.protocols.fast_calibration import (
            calibrate_fast_profile,
        )

        calibrate_fast_profile(args.artifact, args.output)
        return 0
    if args.acceptance_model == "theory" and args.input_z_error is None:
        parser.error("theory requires explicit --input-z-error")
    if (
        args.acceptance_model == "physical_no_fault_proxy"
        and args.input_z_error is not None
    ):
        parser.error("physical_no_fault_proxy does not accept --input-z-error")
    started = perf_counter()
    profile = load_fast_profile(args.profile)
    loaded = perf_counter() - started
    kwargs = {
        "code": args.code,
        "aod_max_rows": args.aod_rows,
        "aod_max_columns": args.aod_columns,
        "max_readout_atoms": args.readout_atoms,
        "acceptance_model": args.acceptance_model,
        "input_z_error": args.input_z_error,
    }
    if args.command == "sweep":
        result = sweep(
            profile,
            factory_counts=args.factories,
            seeds=args.seeds,
            output=args.output,
            detailed=args.detailed,
            **kwargs,
        )
        return 0 if result["all_runs_completed"] and result["source_stable"] else 1
    before = source_hashes()
    run = run_fast(profile, seed=args.seed, factory_count=args.factories, **kwargs)
    after = source_hashes()
    export_run(run, args.output, sampling_role=args.sampling_role)
    _write(
        args.output / "manifest.json",
        {
            "profile_load_seconds": loaded,
            "source_start": before,
            "source_end": after,
            "source_stable": before == after,
            "profile_file": str(args.profile.resolve()),
            "profile_sha256": profile.profile_sha256,
        },
    )
    print(
        json.dumps(
            {
                key: run.summary[key]
                for key in (
                    "status",
                    "execution_completed",
                    "makespan_us",
                    "wall_seconds",
                    "counts",
                )
            }
        ),
        flush=True,
    )
    return 0 if run.summary["execution_completed"] and before == after else 1


if __name__ == "__main__":
    raise SystemExit(main())
