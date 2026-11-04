"""Label `nadit experiment plan` output by SE trade-off configuration.

nadit experiment plan SPEC > plan.json
python -m experiments.se_tradeoff.admission SPEC plan.json -o admission.json
"""

import argparse
import json
from pathlib import Path
from typing import Any

from nadit_physical_compiler.experiments.spec import load_spec, runs


def label(architecture: dict[str, Any]) -> dict[str, Any]:
    """Return the chart identity of one expanded architecture."""
    zones = architecture.get("gate_zones")
    max_atoms = architecture["measurement"]["readout"]["max_atoms"]
    return {
        "architecture": "shared" if zones is None else f"zoned-{zones[0]['rows']}row",
        "motion": architecture["aod"]["motion"],
        "readout": "batch" if max_atoms is None else f"single<={max_atoms}",
    }


def tabulate(spec_path: Path, plan: dict[str, Any]) -> dict[str, Any]:
    """Join planned run IDs with rejection reasons, grouped across rounds."""
    reasons = {
        item["run_id"]: [r["reason"] for r in item.get("reasons", ())]
        or [item.get("reason", item.get("status", "rejected"))]
        for item in plan["rejected"]
    }
    rows: dict[tuple[str, ...], dict[str, Any]] = {}
    for run in runs(load_spec(spec_path), plan["code"]):
        identity = {**label(run["architecture"]), "compiler": run["strategy"]}
        row = rows.setdefault(
            tuple(identity.values()),
            {**identity, "admitted": [], "rejected": [], "reasons": []},
        )
        if run["run_id"] in reasons:
            row["rejected"].append(run["circuit"])
            row["reasons"] = sorted(set(row["reasons"]) | set(reasons[run["run_id"]]))
        else:
            row["admitted"].append(run["circuit"])
    return {
        "runs": plan["runs"],
        "rejected": len(plan["rejected"]),
        "configurations": [rows[key] for key in sorted(rows)],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec", type=Path)
    parser.add_argument("plan", type=Path)
    parser.add_argument("-o", "--output", type=Path)
    args = parser.parse_args()
    table = tabulate(args.spec, json.loads(args.plan.read_text(encoding="utf-8")))
    text = json.dumps(table, indent=2) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8", newline="\n")
    for row in table["configurations"]:
        status = "ADMITTED" if row["admitted"] else "; ".join(row["reasons"])
        print(
            f"{row['architecture']:15} {row['motion']:9} {row['readout']:10} "
            f"{row['compiler']:13} {status}"
        )


if __name__ == "__main__":
    main()
