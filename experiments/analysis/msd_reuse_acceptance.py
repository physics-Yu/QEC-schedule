"""Small physical comparisons for reusable component IR and shared scheduling.

These are controlled frontier witnesses, including an explicit rejected-then-
accepted preparation script. They are not complete production or decoded-QEC
experiments and do not authorize resuming a parameter scan.
"""

import argparse
import json
from collections import Counter
from pathlib import Path
from time import perf_counter
from typing import Any

from nadit_physical_compiler.activity import derive_activity
from nadit_physical_compiler.cost import model_for
from nadit_physical_compiler.experiments.journal import write_json
from nadit_physical_compiler.provenance import canonical_hash

from experiments.msd.joint_cache import JointCalibrationCache
from experiments.msd.joint_factory_calibration import compile_joint_actions
from experiments.msd.standard import ExperimentSpec, build_world


def run(output: Path) -> dict[str, Any]:
    """Compare the old full-source path against the production cache adapter."""
    output.mkdir(parents=True, exist_ok=False)
    world = build_world(ExperimentSpec(3, 2))
    noise_params = json.loads(
        Path(
            "modules/physical_compiler/cost_params/noise_illustrative.json"
        ).read_text()
    )
    raw = tuple(f"raw_t_postselection:factory{i}/R" for i in range(2))
    measured = tuple(f"logical_mz:factory{i}/W1" for i in range(2))
    cases = {
        "synchronous": [raw],
        "postselection_retry_offset": [raw, (raw[0],), (raw[0],)],
        "readout_conflict": [measured],
    }
    report: dict[str, Any] = {
        "schema": "nadit.component_reuse_acceptance/1",
        "distance": 3,
        "pipelines": 2,
        "passed": False,
        "cases": {},
        "scope": "controlled frontier schedules; scripted retry outcomes; no full factory/decoded acceptance claim",
    }
    totals: Counter[str] = Counter()
    for label, waves in cases.items():
        records = []
        for index, members in enumerate(waves):
            print(f"{label} wave {index}: full reference", flush=True)
            started = perf_counter()
            reference, trace = compile_joint_actions(world, members, family="reference")
            reference_s = perf_counter() - started
            write_json(output / f"{label}-{index}-reference.json", trace)
            # A fresh cache object models a new subprocess/production seed.
            cache = JointCalibrationCache(output / "cache")
            started = perf_counter()
            result = cache.get_or_create(
                world,
                members,
                family="acceptance",
                noise_params=noise_params,
                shots=1024,
                seed=20261024,
            )
            elapsed = perf_counter() - started
            actual = json.loads(result.trace_path.read_text())
            checks = {
                "program": actual["program"] == trace["program"],
                "entry": actual["entry_state"] == trace["entry_state"],
                "exit": actual["exit_state"] == trace["exit_state"],
                "metrics": result.group["shared_metrics"]
                == reference["shared_metrics"],
                "native_counts": result.group["native_action_counts"]
                == reference["native_action_counts"],
                "resource_intervals": result.group["shared_resource_intervals"]
                == reference["shared_resource_intervals"],
                "constraints": actual["validation"]["ok"] is True
                and trace["validation"]["ok"] is True,
            }
            # Independently recalculate all waiting/transport noise channels from
            # each actual schedule, never from a singleton total duration.
            noises = [
                model_for("noise/v1").evaluate(derive_activity(t), t, noise_params)[
                    "noise"
                ]["channels"]
                for t in (trace, actual)
            ]
            checks["scheduled_noise_channels"] = noises[0] == noises[1]
            if not all(checks.values()):
                write_json(
                    output / "failure.json",
                    {"case": label, "wave": index, "checks": checks},
                )
                raise AssertionError(checks)
            reuse = (
                result.group.get("component_reuse", {}) if not result.action_hit else {}
            )
            totals.update(
                {
                    k: reuse.get(k, 0)
                    for k in (
                        "requests",
                        "internal_compiles",
                        "disk_hits",
                        "memory_hits",
                        "shared_schedule_calls",
                    )
                }
            )
            totals["exact_schedule_hits"] += result.action_hit
            records.append(
                {
                    "members": members,
                    "checks": checks,
                    "duration_us": sum(result.group["phase_durations_us"]),
                    "reference_wall_s": reference_s,
                    "cache_and_schedule_wall_s": elapsed,
                    "action_hit": result.action_hit,
                    "component_reuse": reuse,
                    "software_seconds": result.software_seconds,
                    "action_stage_seconds": result.group.get("software_seconds", {}),
                    "native_counts": result.group["native_action_counts"],
                    "exposure": result.group["shared_metrics"],
                    "trace_path": str(result.trace_path),
                }
            )
            print(
                json.dumps(
                    {
                        "case": label,
                        "wave": index,
                        "checks_passed": True,
                        "component_reuse": reuse,
                        "wall_s": elapsed,
                    }
                ),
                flush=True,
            )
        report["cases"][label] = {
            "waves": records,
            "round_completion_us": sum(r["duration_us"] for r in records),
        }
        write_json(output / "summary.json", report)
    # The same independent singleton readout destination appears in both plans;
    # the joint plan must resolve it through placement or serialized transport.
    destinations = []
    for member in measured:
        _, trace = compile_joint_actions(world, (member,), family="independent-readout")
        destinations.append(
            {
                tuple(p)
                for e in derive_activity(trace).events
                if e.kind == "Measure"
                for p in e.starts
            }
        )
    overlap = destinations[0] & destinations[1]
    if not overlap:
        raise AssertionError("Readout fixture did not create competing destinations")
    report["readout_independent_destination_overlap"] = sorted(overlap)
    # New seed and more retries must not invoke the component frontend.
    cold = sum(totals[k] for k in ("internal_compiles",))
    for seed in (0, 1, 2):
        cache = JointCalibrationCache(output / "cache")
        for members in (raw, (raw[0],), measured):
            result = cache.lookup(
                world,
                members,
                family=f"production-seed-{seed}",
                noise_params=noise_params,
                shots=1024,
                seed=20261024,
            )
            if not result.action_hit:
                raise AssertionError("Repeated production seed recompiled actions")
            totals["additional_seed_schedule_hits"] += 1
    report.update(
        passed=True,
        statistics=dict(totals),
        first_component_compiles=cold,
        component_hit_rate=(totals["memory_hits"] + totals["disk_hits"])
        / totals["requests"],
        noise_params_sha256=canonical_hash(noise_params),
    )
    write_json(output / "summary.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.output.resolve())
