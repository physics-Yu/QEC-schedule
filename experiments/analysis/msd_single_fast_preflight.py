"""Inventory existing exact joint summaries without generating atom actions.

This is a static coverage audit, not a production scan or authorization to
reuse old source versions. A missing entry remains missing; no fallback runs.
"""

import argparse
import json
from pathlib import Path
from typing import Any

from nadit_physical_compiler.provenance import canonical_hash

from experiments.msd.fast_guard import no_atom_execution
from modules.codes.rotated_surface.factory_assumptions import ECPolicy
from modules.codes.rotated_surface.joint_factory_profile import joint_key


def inspect_coverage(config: dict[str, Any], profile_root: Path) -> dict[str, Any]:
    """Check file identities, EC contracts and complete final-MX coverage only.

    All dynamic retry frontiers and source applicability still require separate
    checks. A passed inventory never certifies a complete production trajectory.
    """
    ec = ECPolicy(**config["ec"])
    cells = []
    for distance in config["distances"]:
        for count in config["factory_counts"]:
            path = profile_root / f"d{distance}-n{count}" / "profile.json"
            row: dict[str, Any] = {
                "distance": distance,
                "factory_count": count,
                "profile": str(path.resolve()),
                "requested_seeds": list(config["production_seeds"]),
                "production_status": "not_run",
            }
            if not path.is_file():
                row.update(status="missing_profile", missing=["profile_file"])
                cells.append(row)
                continue
            document = json.loads(path.read_text(encoding="utf-8"))
            if (document["distance"], document["factory_count"]) != (distance, count):
                raise ValueError(f"PROFILE_IDENTITY_MISMATCH: {path}")
            entries = document.get("entries", document.get("source_contracts", {}))
            required_ec = (
                [
                    f"se_round:factory{factory}/W{role}"
                    for factory in range(count)
                    for role in range(1, 6)
                ]
                if ec.resolved_rounds(distance)
                else []
            )
            missing = [key for key in required_ec if key not in entries]
            final_members = tuple(
                f"logical_mx:factory{factory}/W{role}"
                for factory in range(count)
                for role in range(2, 6)
            )
            if joint_key(final_members) not in document.get("joint_groups", {}):
                missing.append("complete_final_mx_joint_frontier")
            row.update(
                status="missing_coverage" if missing else "requires_dynamic_validation",
                missing=missing,
                profile_sha256=canonical_hash(document),
                source_applicability="not_requalified_for_new_model",
                existing_joint_groups=len(document.get("joint_groups", {})),
            )
            cells.append(row)
    return {
        "schema": "nadit.single_fast_preflight/1",
        "scope": "static historical cache inventory; not production acceptance",
        "config_sha256": canonical_hash(config),
        "cells": cells,
        "requested_trajectories": len(cells) * len(config["production_seeds"]),
        "executed_trajectories": 0,
        "physical_compilation_run": False,
        "cost_basis_decided": config["cost_basis"] is not None,
    }


def main() -> None:
    """Save a complete missing-coverage report; never invoke a compiler."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--profiles", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output already exists; choose a fresh file.")
    config = json.loads(args.config.read_text(encoding="utf-8"))
    with no_atom_execution() as audit:
        report = inspect_coverage(config, args.profiles)
    report["no_atom_execution"] = audit.to_dict()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, allow_nan=False), encoding="utf-8"
    )
    print(json.dumps({"output": str(args.output), "cells": len(report["cells"])}))


if __name__ == "__main__":
    main()
