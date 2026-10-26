"""Run, resume and inspect an explicitly resolved MSD task plan.

This entry reuses the bounded experiment runner. It never fills unspecified
server budgets, chooses a delivery protocol, or changes observation windows.
"""

import argparse
import json
import os
from copy import deepcopy
from pathlib import Path, PureWindowsPath
from typing import Any

from nadit_physical_compiler.experiments.journal import write_json
from nadit_physical_compiler.experiments.runner import run_task_plan, status
from nadit_physical_compiler.experiments.task_plan import validate_plan, validate_task
from nadit_physical_compiler.experiments.version import code_version
from nadit_physical_compiler.provenance import canonical_hash

from .campaign_report import summarize_campaign


def _read(path: Path) -> dict[str, Any]:
    return dict(json.loads(path.read_text(encoding="utf-8")))


def _summarize_level(
    layout_plan: dict[str, Any],
    directory: Path,
    snapshot: dict[str, Any],
    *,
    produce_kind: str,
    driver_kind: str,
    output_dir: Path,
    plots: bool,
) -> dict[str, Any]:
    """Export all planned trajectories, retaining unrun and failed task records.

    Task definitions identify trajectories; only a result matching the runner's
    recorded hash can enter statistics. Per-layout policies are loaded from their
    explicit resolved artifacts. Missing layouts remain visible as unrun.
    """
    layout_plan = deepcopy(layout_plan)
    mapped: dict[str, dict[str, Any]] = {}
    results: dict[str, dict[str, Any]] = {}
    policies: dict[str, dict[str, Any]] = {}
    drivers: dict[str, tuple[str, dict[str, Any]]] = {}
    for identity, row in snapshot["tasks"].items():
        if row.get("kind") is not None and row["kind"] not in (
            produce_kind,
            driver_kind,
        ):
            continue
        task = validate_task(_read(directory / "task_definitions" / f"{identity}.json"))
        if task["task_id"] != identity:
            raise ValueError("CAMPAIGN_TASK_FILE_IDENTITY_MISMATCH")
        if task["kind"] == driver_kind:
            layout_id = task["payload"]["layout_id"]
            if layout_id in drivers:
                raise ValueError("DUPLICATE_CAMPAIGN_LAYOUT_DRIVER")
            drivers[layout_id] = (identity, row)
        if task["kind"] != produce_kind:
            continue
        trajectory = task["payload"]["trajectory_id"]
        if trajectory in mapped:
            raise ValueError("DUPLICATE_CAMPAIGN_TRAJECTORY_TASK")
        mapped[trajectory] = {**row, "trajectory_id": trajectory}
        if row.get("result_path"):
            path = (directory / row["result_path"]).resolve()
            if not path.is_relative_to(directory.resolve()):
                raise ValueError("CAMPAIGN_RESULT_OUTSIDE_DIRECTORY")
            result = _read(path)
            if canonical_hash(result) != row["result_sha256"]:
                raise ValueError("CAMPAIGN_RESULT_HASH_MISMATCH")
            results[trajectory] = result
            mapped[trajectory]["result_available"] = "metrics" in result
        policy = task["payload"].get("observation_policy")
        if policy is not None:
            layout_id = task["payload"]["layout_id"]
            if layout_id in policies and policies[layout_id] != policy:
                raise ValueError("CAMPAIGN_LAYOUT_OBSERVATION_POLICY_CHANGED")
            policies[layout_id] = policy
    for trajectory in layout_plan["tasks"]:
        identity = trajectory.get("trajectory_id", trajectory["task_id"])
        driver = drivers.get(trajectory.get("layout_id"))
        if identity not in mapped and driver is not None:
            driver_id, row = driver
            failed = row["status"] in ("software_error", "blocked", "budget_exceeded")
            mapped[identity] = {
                "trajectory_id": identity,
                "status": "blocked" if failed else "pending",
                "reason": {
                    "phase": "layout_pilot_and_resolution",
                    "driver_task_id": driver_id,
                    "driver_status": row["status"],
                    "cause": row.get("reason"),
                },
            }
    layout_plan["observation_policy"] = {"by_layout": policies}
    return summarize_campaign(
        layout_plan, mapped, results, output_dir=output_dir, plots=plots
    )


def _frozen_two_level_plan(
    plan: dict[str, Any], directory: Path
) -> dict[str, Any] | None:
    """Read only a complete Stage 3 publication tied to the original campaign."""
    folder = directory / "two-level"
    if not (folder / "frozen.json").exists():
        return None
    identity = _read(folder / "identity.json")
    arrivals = _read(folder / "arrivals.json")
    candidates = _read(folder / "candidate-plan.json")
    marker = _read(folder / "frozen.json")
    expected = {
        "schema": "nadit.msd.two_level_freeze/1",
        "identity_sha256": canonical_hash(identity),
        "arrival_evidence_sha256": canonical_hash(arrivals),
        "candidate_plan_sha256": canonical_hash(candidates),
    }
    context = plan["campaign"]
    rule = {
        **context["configuration"]["two_level"]["candidate_rule"],
        "arrival_evidence_sha256": canonical_hash(arrivals),
        "arrival_source_sha256": arrivals.get("source_sha256"),
    }
    stages = [task for task in plan["tasks"] if task["kind"] == "msd.two_level_driver"]
    if (
        marker != expected
        or len(stages) != 1
        or identity.get("task_id") != stages[0]["task_id"]
        or identity.get("payload_sha256") != canonical_hash(stages[0]["payload"])
        or identity.get("configuration_sha256")
        != canonical_hash(context["configuration"])
        or identity.get("source_sha256") != canonical_hash(context["source_identity"])
        or identity.get("single_level_plan_sha256")
        != canonical_hash(context["layout_plan"])
        or candidates.get("configuration") != rule
        or candidates.get("source_identity") != context["source_identity"]
        or candidates.get("arrival_evidence") != arrivals
    ):
        raise ValueError("FROZEN_TWO_LEVEL_SUMMARY_INPUT_MISMATCH")
    return candidates


def summarize_saved(
    plan: dict[str, Any], directory: Path, *, plots: bool = False
) -> dict[str, Any]:
    """Export frozen stages separately, retaining absent or failed second-level work."""
    snapshot = status(directory)
    context = plan["campaign"]
    multi = context.get("scope") == "single_and_two_level"
    single = _summarize_level(
        context["layout_plan"],
        directory,
        snapshot,
        produce_kind="msd.produce",
        driver_kind="msd.layout_driver",
        output_dir=directory / "report" / "single-level"
        if multi
        else directory / "report",
        plots=plots,
    )
    if not multi:
        return single
    candidates = _frozen_two_level_plan(plan, directory)
    stage_status = {
        key: {"status": row["status"], "reason": row.get("reason")}
        for key, row in snapshot["tasks"].items()
        if row.get("kind") == "msd.two_level_driver"
    }
    two = (
        {
            "status": "not_run",
            "campaign_complete": False,
            "reason": "no_complete_frozen_two_level_plan",
            "stage_status": stage_status,
        }
        if candidates is None
        else _summarize_level(
            candidates,
            directory,
            snapshot,
            produce_kind="msd.two_level_produce",
            driver_kind="msd.two_level_layout_driver",
            output_dir=directory / "report/two-level",
            plots=plots,
        )
    )
    complete = bool(single.get("campaign_complete") and two.get("campaign_complete"))
    result = {
        "schema": "nadit.msd.multistage_summary/1",
        "status": "complete" if complete else "partial",
        "campaign_complete": complete,
        "single_level": single,
        "two_level": two,
        "stage_status": stage_status,
        "source_identity": context["source_identity"],
        "configuration_sha256": canonical_hash(context["configuration"]),
    }
    write_json(directory / "report/summary.json", result)
    return result


def run_resolved(
    plan: dict[str, Any], directory: Path, *, workers: int | None = None
) -> dict[str, Any]:
    """Launch a ready, frozen campaign without increasing its configured budget."""
    validate_plan(plan)
    context = plan.get("campaign", {})
    if (
        context.get("schema") != "nadit.msd.campaign_context/1"
        or context.get("runnable") is not True
    ):
        raise ValueError("MSD_CAMPAIGN_NOT_READY")
    config = context["configuration"]
    if context["configuration_sha256"] != canonical_hash(config):
        raise ValueError("MSD_CAMPAIGN_CONFIGURATION_CHANGED")
    expected = context.get("source_identity")
    if not expected or expected != code_version(
        allow_dirty=False, scope="msd", source_paths=plan.get("source_paths", ())
    ):
        raise ValueError("MSD_CAMPAIGN_SOURCE_CHANGED_SINCE_RESOLUTION")
    target = context.get("campaign_directory")
    if target is not None:
        windows = bool(PureWindowsPath(target).drive)
        if (
            windows != (os.name == "nt")
            or Path(target).resolve() != directory.resolve()
        ):
            raise ValueError("MSD_CAMPAIGN_OUTPUT_LOCATION_CHANGED")
    configured_workers = config["budget"]["workers"]
    if workers is not None and workers != configured_workers:
        raise ValueError("MSD_CAMPAIGN_WORKER_BUDGET_CHANGED")
    return run_task_plan(plan, directory, workers=configured_workers)


def main() -> None:
    """Expose the same run/resume/status contract used by server package scripts."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    resolve = commands.add_parser("resolve")
    resolve.add_argument("--config", type=Path, required=True)
    resolve.add_argument(
        "--output", required=True, help="Frozen target-host campaign directory"
    )
    resolve.add_argument("--resolved-plan", type=Path, required=True)
    resolve.add_argument("--acceptance-evidence", type=Path)
    resolve.add_argument("--two-level-evidence", type=Path)
    for name in ("run", "resume", "summarize", "status"):
        command = commands.add_parser(name)
        command.add_argument("--output", type=Path, required=True)
        if name != "status":
            command.add_argument("--plan", type=Path, required=True)
        if name in ("run", "resume"):
            command.add_argument("--workers", type=int)
        if name == "summarize":
            command.add_argument("--plots", action="store_true")
    args = parser.parse_args()
    if args.command == "resolve":
        from .campaign_driver import resolve_campaign
        from .joint_cache import (
            action_dependency_fingerprints,
            probability_dependency_fingerprints,
        )

        configuration = _read(args.config)
        descriptor = None
        if args.acceptance_evidence is not None:
            descriptor = {
                "path": str(args.acceptance_evidence.resolve()),
                "sha256": canonical_hash(_read(args.acceptance_evidence)),
                "hash_kind": "canonical_json",
            }
        result = resolve_campaign(
            configuration,
            source_identity=code_version(
                allow_dirty=False,
                scope="msd",
                source_paths=configuration.get("source_paths", ()),
            ),
            action_dependencies=action_dependency_fingerprints(),
            probability_dependencies=probability_dependency_fingerprints(),
            campaign_directory=args.output,
            acceptance_evidence=descriptor,
            two_level_evidence=None
            if args.two_level_evidence is None
            else {
                "path": str(args.two_level_evidence.resolve()),
                "sha256": canonical_hash(_read(args.two_level_evidence)),
                "hash_kind": "canonical_json",
            },
        )
        if args.resolved_plan.exists():
            if _read(args.resolved_plan) != result:
                raise ValueError(
                    "MSD_RESOLVED_PLAN_ALREADY_EXISTS_WITH_DIFFERENT_CONTENT"
                )
        else:
            write_json(args.resolved_plan, result)
    elif args.command == "status":
        result = status(args.output)
    elif args.command == "summarize":
        from .campaign_driver import software_accounting

        result = summarize_saved(_read(args.plan), args.output, plots=args.plots)
        result["campaign_software_accounting"] = software_accounting(args.output)
        write_json(args.output / "report/summary.json", result)
    else:
        result = run_resolved(_read(args.plan), args.output, workers=args.workers)
    print(json.dumps(result, ensure_ascii=True, allow_nan=False))


if __name__ == "__main__":
    main()
