"""Frozen joint-SE, serial, and same-world per-position control campaign."""

import argparse
import json
import os
import subprocess
import sys
from dataclasses import asdict
from math import isfinite
from pathlib import Path
from time import monotonic
from typing import Any

from nadit_physical_compiler.provenance import canonical_hash

from .calibrate import source_snapshot
from .parallel_se_compare import compare_cases
from .standard import STANDARD_ID, ExperimentSpec
from .survey import save


def main() -> None:
    """Run all actual schedules under the same geometry and timing per cell."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--distances", nargs="+", type=int, default=[3, 5, 7])
    parser.add_argument("--pipelines", nargs="+", type=int, default=[1, 2, 4])
    parser.add_argument("--cell-timeout", type=float, default=120)
    parser.add_argument("--campaign-timeout", type=float, default=1800)
    parser.add_argument("--max-atoms", type=int, default=20000)
    args = parser.parse_args()
    for values in (args.distances, args.pipelines):
        if len(values) != len(set(values)):
            parser.error(
                "Repeated distances/pipeline counts are not independent cells."
            )
    if not all(
        isfinite(v) and v > 0
        for v in (args.cell_timeout, args.campaign_timeout, args.max_atoms)
    ):
        parser.error("Limits must be finite and positive.")
    specs = [ExperimentSpec(d, n) for d in args.distances for n in args.pipelines]
    snapshot = source_snapshot()
    root = Path(__file__).resolve().parents[2]
    args.output.mkdir(parents=True, exist_ok=False)
    save(args.output / "source-snapshot.json", snapshot)
    save(
        args.output / "manifest.json",
        {
            "schema": "nadit.msd.parallel_se_survey/1",
            "standard": STANDARD_ID,
            "source_tree_sha256": canonical_hash(snapshot),
            "git_revision": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=root, text=True
            ).strip(),
            "python": sys.version,
            "command": sys.argv,
            "configurations": [asdict(spec) for spec in specs],
            "active_role_per_factory": "W1",
            "se_instances_in_joint_case": "N",
            "world": "all 6*N patches retained; single original transport AOD",
            "controls": [
                "joint",
                "same-source explicit serial barriers",
                "each factory solo in identical complete world",
            ],
            "limits": {
                "cell_timeout_s": args.cell_timeout,
                "campaign_timeout_s": args.campaign_timeout,
                "max_atoms": args.max_atoms,
            },
            "scope": "real joint SE round, not a full distillation production cycle",
        },
    )
    environment = dict(os.environ)
    environment.update(
        {
            key: "1"
            for key in (
                "OMP_NUM_THREADS",
                "OPENBLAS_NUM_THREADS",
                "MKL_NUM_THREADS",
                "NUMEXPR_NUM_THREADS",
            )
        }
    )
    started, records, comparisons = monotonic(), [], []
    for spec in specs:
        complete: dict[str, Any] = {}
        cases = [("joint", None), ("serial", None)] + [
            ("solo", i) for i in range(spec.pipelines)
        ]
        for mode, index in cases:
            label = mode if index is None else f"solo-f{index}"
            key = f"d{spec.distance}-n{spec.pipelines}-{label}"
            record: dict[str, Any] = {"cell": key, "status": "pending"}
            remaining = args.campaign_timeout - (monotonic() - started)
            if source_snapshot() != snapshot:
                raise RuntimeError("Source changed during parallel-SE campaign.")
            if 6 * spec.pipelines * (2 * spec.distance**2 - 1) > args.max_atoms:
                record["status"] = "atom_budget_exceeded"
            elif remaining <= 0:
                record["status"] = "campaign_timeout"
            else:
                destination = (args.output / f"{key}.json").resolve()
                command = [
                    sys.executable,
                    "-m",
                    "experiments.msd.parallel_se",
                    "--distance",
                    str(spec.distance),
                    "--pipelines",
                    str(spec.pipelines),
                    "--mode",
                    mode,
                    "--output",
                    str(destination),
                ]
                if index is not None:
                    command.extend(("--factory-index", str(index)))
                try:
                    process = subprocess.run(
                        command,
                        cwd=root,
                        env=environment,
                        capture_output=True,
                        text=True,
                        timeout=min(remaining, args.cell_timeout),
                    )
                except subprocess.TimeoutExpired:
                    record["status"] = "timeout"
                else:
                    if process.returncode:
                        record.update(status="failed", error=process.stderr[-14000:])
                    else:
                        result = json.loads(destination.read_text(encoding="utf-8"))
                        if result["source_tree_sha256"] != canonical_hash(snapshot):
                            raise RuntimeError(
                                "Child sources differ from the frozen manifest."
                            )
                        record.update(status="passed", result=result)
                        complete[label] = result
            if source_snapshot() != snapshot:
                raise RuntimeError("Source changed during parallel-SE child.")
            records.append(record)
            with (args.output / "journal.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, allow_nan=False) + "\n")
            print(json.dumps({"cell": key, "status": record["status"]}), flush=True)
        if len(complete) == len(cases):
            comparison = compare_cases(
                complete["joint"],
                complete["serial"],
                tuple(complete[f"solo-f{i}"] for i in range(spec.pipelines)),
            )
            comparison["parameters"] = asdict(spec)
            comparisons.append(comparison)
        else:
            comparisons.append(
                {"parameters": asdict(spec), "status": "incomplete_controls"}
            )
    if source_snapshot() != snapshot:
        raise RuntimeError("Source changed before parallel-SE endpoint export.")
    save(
        args.output / "summary.json",
        {
            "records": records,
            "comparisons": comparisons,
            "elapsed_host_s": monotonic() - started,
        },
    )


if __name__ == "__main__":
    main()
