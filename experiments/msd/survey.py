"""Bounded component calibration campaign with compact records and one witness."""

import argparse
import json
import os
import subprocess
import sys
from math import isfinite
from pathlib import Path
from time import monotonic
from typing import Any

from nadit_physical_compiler.provenance import canonical_hash

from .calibrate import CALIBRATION_OPERATIONS, source_snapshot
from .standard import STANDARD_ID, ExperimentSpec, build_world


def save(path: Path, value: Any) -> None:
    """Exclusively create a deterministic JSON artifact."""
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")


def main() -> None:
    """Run independent physical component cells with enforced host-time limits."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--distances", type=int, nargs="+", default=[3, 5, 7])
    parser.add_argument("--pipelines", type=int, nargs="+", default=[1, 2, 4])
    parser.add_argument(
        "--operations",
        choices=CALIBRATION_OPERATIONS,
        nargs="+",
        default=[
            "initialize_0",
            "initialize_plus",
            "se_round",
            "logical_s",
            "raw_t",
            "logical_mx",
            "logical_mz",
            "transversal_cnot",
        ],
    )
    parser.add_argument("--cell-timeout", type=float, default=120)
    parser.add_argument("--campaign-timeout", type=float, default=1800)
    parser.add_argument("--max-atoms", type=int, default=20000)
    args = parser.parse_args()
    if (
        not all(isfinite(value) for value in (args.cell_timeout, args.campaign_timeout))
        or min(args.cell_timeout, args.campaign_timeout, args.max_atoms) <= 0
    ):
        parser.error("Run limits must be finite and positive.")
    for values in (args.distances, args.pipelines, args.operations):
        if len(values) != len(set(values)):
            parser.error(
                "Distance, pipeline, and operation lists must not repeat cells."
            )
    specs = [ExperimentSpec(d, n) for d in args.distances for n in args.pipelines]
    args.output.mkdir(parents=True, exist_ok=False)
    snapshot = source_snapshot()
    save(args.output / "source-snapshot.json", snapshot)
    root = Path(__file__).resolve().parents[2]
    save(
        args.output / "manifest.json",
        {
            "schema": "nadit.msd.component_survey/1",
            "standard": STANDARD_ID,
            "source_tree_sha256": canonical_hash(snapshot),
            "git_revision": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=root, text=True
            ).strip(),
            "python": sys.version,
            "command": sys.argv,
            "scope": (
                "independent components at the bottom factory, not parallel production"
            ),
            "distance": args.distances,
            "pipelines": args.pipelines,
            "operations": args.operations,
            "limits": {
                "cell_timeout_s": args.cell_timeout,
                "campaign_timeout_s": args.campaign_timeout,
                "max_atoms": args.max_atoms,
            },
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
    started, records = monotonic(), []
    for spec in specs:
        for operation in args.operations:
            key = f"d{spec.distance}-n{spec.pipelines}-{operation}"
            row: dict[str, Any] = {"cell": key, "status": "pending"}
            remaining = args.campaign_timeout - (monotonic() - started)
            if source_snapshot() != snapshot:
                raise RuntimeError(
                    "Source files changed during campaign; "
                    "stop without combining versions."
                )
            if 6 * spec.pipelines * (2 * spec.distance**2 - 1) > args.max_atoms:
                row.update(status="atom_budget_exceeded")
            elif remaining <= 0:
                row.update(status="campaign_timeout")
            else:
                path = args.output / f"{key}.json"
                command = [
                    sys.executable,
                    "-m",
                    "experiments.msd.calibrate",
                    "--distance",
                    str(spec.distance),
                    "--pipelines",
                    str(spec.pipelines),
                    "--factory-index",
                    str(spec.pipelines - 1),
                    "--operation",
                    operation,
                    "--output",
                    str(path.resolve()),
                ]
                if (spec.distance, spec.pipelines, operation) == (3, 1, "logical_s"):
                    command.append("--witness")
                try:
                    process = subprocess.run(
                        command,
                        cwd=root,
                        env=environment,
                        capture_output=True,
                        text=True,
                        timeout=min(args.cell_timeout, remaining),
                    )
                except subprocess.TimeoutExpired:
                    row.update(status="timeout")
                else:
                    if process.returncode:
                        row.update(status="failed", error=process.stderr[-12000:])
                    else:
                        result = json.loads(path.read_text(encoding="utf-8"))
                        if result["source_tree_sha256"] != canonical_hash(snapshot):
                            raise RuntimeError(
                                "Child source fingerprint differs from manifest."
                            )
                        row.update(status="passed", result=result)
            if source_snapshot() != snapshot:
                raise RuntimeError(
                    "Source files changed during campaign; "
                    "stop without combining versions."
                )
            records.append(row)
            with (args.output / "journal.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(row, allow_nan=False) + "\n")
            print(json.dumps({"cell": key, "status": row["status"]}), flush=True)
    representative = build_world(ExperimentSpec(5, 4)).document()
    if source_snapshot() != snapshot:
        raise RuntimeError("Source files changed before final survey export.")
    save(
        args.output / "summary.json",
        {"records": records, "elapsed_host_s": monotonic() - started},
    )
    save(args.output / "representative-world.json", representative)


if __name__ == "__main__":
    main()
