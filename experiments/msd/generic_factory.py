"""Calibrate explicitly, then scan generic factory profiles without atom compilation."""

import argparse
import csv
import json
from pathlib import Path
from statistics import fmean
from typing import Any

from modules.codes.rotated_surface.fast_factory import SurfaceFactoryProfile
from modules.codes.rotated_surface.joint_factory_profile import (
    JointSurfaceFactoryProfile,
)
from modules.logical_compiler.examples.surface_factory_fast import run_surface_factory


def _write(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )


def scan(profiles: Path, output: Path, plan: dict[str, Any]) -> dict[str, Any]:
    """Execute a fixed seed grid; export witnesses and component schedule CSVs."""
    output.mkdir(parents=True, exist_ok=False)
    rows = []
    joint_mode: bool | None = None
    for distance in plan["distances"]:
        for count in plan["factory_counts"]:
            path = profiles / f"d{distance}-n{count}" / "profile.json"
            document = json.loads(path.read_text(encoding="utf-8"))
            if (
                document["standard"] != plan["standard"]
                or document["timing"]
                != {
                    "load_us": 10,
                    "store_us": 10,
                    "measure_us": 100,
                    "result_processing_us": 0,
                }
                or document["distance"] != distance
                or document["factory_count"] != count
            ):
                raise ValueError("Profile does not match the frozen MSD standard/grid.")
            is_joint = "joint_calibration" in document
            if joint_mode is not None and is_joint != joint_mode:
                raise ValueError(
                    "Do not mix joint profiles and historical exclusive-AOD controls."
                )
            joint_mode = is_joint
            profile = (
                JointSurfaceFactoryProfile(document)
                if is_joint
                else SurfaceFactoryProfile(document)
            )
            hardware_modes = (
                ("shared_aod",)
                if is_joint
                else ("shared_aod", "independent_aod_control")
            )
            for hardware in hardware_modes:
                samples = []
                for seed in plan["seeds"]:
                    result = run_surface_factory(
                        profile,
                        seed=seed,
                        input_z_error=plan["input_z_error"],
                        hardware=hardware,
                        **plan["limits"],
                    )
                    samples.append(result["summary"])
                    if seed == plan["witness_seed"]:
                        name = f"d{distance}-n{count}-{hardware}"
                        _write(output / f"{name}.case.json", result["case"])
                        with (output / f"{name}.schedule.csv").open(
                            "w", encoding="utf-8", newline=""
                        ) as stream:
                            writer = csv.writer(stream)
                            writer.writerow(
                                [
                                    "invocation",
                                    "component",
                                    "blocks",
                                    "start_us",
                                    "action_end_us",
                                    "results_ready_us",
                                    "reserved_resources",
                                    "shared_resources",
                                    "joint_group",
                                ]
                            )
                            for call in result["case"]["execution"]["calls"]:
                                writer.writerow(
                                    [
                                        call["invocation_id"],
                                        call["component_id"],
                                        ";".join(call["participant_blocks"]),
                                        call["start_us"],
                                        call["action_end_us"],
                                        call["results_ready_us"],
                                        ";".join(call.get("reserved_resources", ())),
                                        ";".join(call.get("shared_resources", ())),
                                        call.get("joint_group_key", ""),
                                    ]
                                )
                _write(
                    output / f"d{distance}-n{count}-{hardware}.samples.json", samples
                )
                outputs = sum(s["outputs"] for s in samples)
                elapsed = sum(s["makespan_us"] for s in samples)
                row = {
                    "distance": distance,
                    "factory_count": count,
                    "hardware": hardware,
                    "profile_sha256": profile.profile_sha256,
                    "independent_seed_count": len(samples),
                    "outputs": outputs,
                    "mean_makespan_us": fmean(s["makespan_us"] for s in samples),
                    "min_makespan_us": min(s["makespan_us"] for s in samples),
                    "max_makespan_us": max(s["makespan_us"] for s in samples),
                    "observed_outputs_per_second": 1e6 * outputs / elapsed,
                    "mean_software_seconds": fmean(
                        s["software_wall_seconds"] for s in samples
                    ),
                    "mean_raw_attempts": fmean(s["raw_attempts"] for s in samples),
                    "mean_raw_rejections": fmean(s["raw_rejections"] for s in samples),
                    "atoms": samples[0]["hardware"]["atom_count_estimate"],
                    "aod_count": samples[0]["hardware"]["aod_count"],
                    "mean_allocated_atom_us": fmean(s["makespan_us"] for s in samples)
                    * samples[0]["hardware"]["atom_count_estimate"],
                    "scope": "finite one-batch trajectories; not steady-state production",
                    "witness": f"d{distance}-n{count}-{hardware}.case.json",
                }
                rows.append(row)
                print(json.dumps(row), flush=True)
    report = {
        "schema": "nadit.generic_factory_scaling/1",
        "plan": plan,
        "results": rows,
        "physical_validation": "exact joint-wave calibration traces validated; fast trajectory remains a logical estimate"
        if joint_mode
        else "historical individual calibrations; not parallel factory acceptance",
        "shared_hardware_policy": "one shared AOD; exact joint-frontier calibration; cohort stage barriers retained"
        if joint_mode
        else "historical conservative complete-component AOD reservation; co-batching not modeled",
        "quality": "matched assumed input_z_error only; no decoded output-error comparison",
    }
    _write(output / "summary.json", report)
    return report


def main() -> None:
    """Keep physical calibration and fast experiment execution separate commands."""
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    calibration = sub.add_parser("calibrate")
    calibration.add_argument("--distance", type=int, required=True)
    calibration.add_argument("--factories", type=int, required=True)
    calibration.add_argument("--output", type=Path, required=True)
    run = sub.add_parser("scan")
    run.add_argument("--profiles", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    for command in (calibration, run):
        command.add_argument(
            "--plan",
            type=Path,
            default=Path(__file__).with_name("generic_factory_plan.json"),
        )
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    if args.command == "calibrate":
        from .calibrate_factory import calibrate_factory

        if (
            6 * args.factories * (2 * args.distance**2 - 1)
            > plan["max_calibration_world_atoms"]
        ):
            raise ValueError("Calibration exceeds the explicit experiment atom budget.")
        noise = json.loads(Path(plan["noise_params"]).read_text(encoding="utf-8"))
        calibrate_factory(
            args.distance,
            args.factories,
            noise_params=noise,
            output=args.output,
            shots=plan["acceptance_shots"],
            seed=plan["acceptance_seed"],
        )
    else:
        scan(args.profiles, args.output, plan)


if __name__ == "__main__":
    main()
