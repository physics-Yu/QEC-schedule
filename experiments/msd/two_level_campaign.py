"""Freeze observed L1 supply and delegate L2 cells to the existing layout driver."""

from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any

from nadit_physical_compiler.experiments.journal import directory_lock, write_json
from nadit_physical_compiler.experiments.task_plan import TERMINAL, validate_task
from nadit_physical_compiler.provenance import canonical_hash

from .campaign_driver import _completion, _positive, _read, _target_path, _task
from .campaign_plan import expand_two_level


def _freeze(
    task: dict[str, Any], directory: Path
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    # Local import avoids coupling the arrival reader to driver initialization.
    from .campaign_arrivals import freeze_arrival_evidence

    payload = task["payload"]
    folder = directory / "two-level"
    paths = {
        name: folder / name
        for name in (
            "identity.json",
            "arrivals.json",
            "candidate-plan.json",
            "frozen.json",
        )
    }
    identity = {
        "schema": "nadit.msd.two_level_freeze_identity/1",
        "task_id": task["task_id"],
        "payload_sha256": canonical_hash(payload),
        "configuration_sha256": canonical_hash(payload["configuration"]),
        "source_sha256": canonical_hash(payload["source_identity"]),
        "single_level_plan_sha256": canonical_hash(payload["single_level_plan"]),
        "dependencies_sha256": canonical_hash(payload["dependencies"]),
        "allocation_sha256": canonical_hash(payload["allocation"]),
    }
    with directory_lock(folder):
        marker = paths["frozen.json"]
        committed = marker.exists()
        if committed and any(not path.is_file() for path in paths.values()):
            raise ValueError("FROZEN_TWO_LEVEL_INPUT_MISSING")
        identity_path = paths["identity.json"]
        if identity_path.exists():
            if _read(identity_path) != identity:
                raise ValueError("TWO_LEVEL_FREEZE_IDENTITY_CHANGED")
        elif any(
            path.exists() for name, path in paths.items() if name != "identity.json"
        ):
            raise ValueError("TWO_LEVEL_FREEZE_IDENTITY_MISSING")
        else:
            write_json(identity_path, identity)

        # Re-read original result/proof artifacts even on a committed cache hit.
        arrivals = freeze_arrival_evidence(payload["single_level_plan"], directory)
        arrival_hash = canonical_hash(arrivals)
        arrival_path = paths["arrivals.json"]
        if arrival_path.exists():
            if _read(arrival_path) != arrivals:
                raise ValueError("FROZEN_TWO_LEVEL_ARRIVAL_EVIDENCE_CHANGED")
        else:
            write_json(arrival_path, arrivals)
        rule = deepcopy(payload["configuration"]["two_level"]["candidate_rule"])
        if {"arrival_evidence_sha256", "arrival_source_sha256"} & rule.keys():
            raise ValueError("TWO_LEVEL_ARRIVAL_PINS_ARE_RESOLVED_AT_FREEZE")
        rule.update(
            arrival_evidence_sha256=arrival_hash,
            arrival_source_sha256=arrivals["source_sha256"],
        )
        plan_path = paths["candidate-plan.json"]
        if committed:
            plan = _read(plan_path)
        else:
            plan = expand_two_level(
                rule, arrivals, source_identity=payload["source_identity"]
            )
            if plan_path.exists():
                if _read(plan_path) != plan:
                    raise ValueError("FROZEN_TWO_LEVEL_CANDIDATE_PLAN_CHANGED")
            else:
                write_json(plan_path, plan)
        expected_marker = {
            "schema": "nadit.msd.two_level_freeze/1",
            "identity_sha256": canonical_hash(identity),
            "arrival_evidence_sha256": arrival_hash,
            "candidate_plan_sha256": canonical_hash(plan),
        }
        if committed:
            if _read(marker) != expected_marker:
                raise ValueError("FROZEN_TWO_LEVEL_COMMITMENT_CHANGED")
        else:
            # Readback precedes completion publication; a partial write is no hit.
            if (
                _read(identity_path) != identity
                or _read(arrival_path) != arrivals
                or _read(plan_path) != plan
            ):
                raise ValueError("TWO_LEVEL_FREEZE_READBACK_MISMATCH")
            write_json(marker, expected_marker)
        artifacts = [
            {
                "path": str(path),
                "sha256": canonical_hash(_read(path)),
                "hash_kind": "canonical_json",
            }
            for path in paths.values()
        ]
    return plan, artifacts


def _children(
    payload: dict[str, Any], plan: dict[str, Any], directory: Path
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    config = payload["configuration"]
    two_level, budget = config["two_level"], config["budget"]
    limits = two_level["limits"]
    admitted = [
        row
        for row in plan["layouts"]
        if not row["budget_exclusions"]
        and not row["supply_exclusions"]
        and not row.get("selection_exclusions")
    ]
    seconds = _positive(
        payload["allocation"]["stage_worker_seconds"], "stage_worker_seconds"
    )
    allocation = {
        "schema": "nadit.msd.equal_two_level_layout_worker_allocation/1",
        "stage_worker_seconds": seconds,
        "admitted_layouts": len(admitted),
        "layout_worker_seconds": seconds / len(admitted) if admitted else None,
        "basis": "heuristic equal stage worker-seconds per admitted capacity/layout cell; pilot and seed costs use the existing layout driver",
    }
    children = []
    for layout in admitted:
        runtime = {
            key: layout[key]
            for key in (
                "level1_count",
                "level2_count",
                "buffer_capacity",
                "parking_origin",
            )
        }
        runtime.update(
            {
                key: limits[key]
                for key in (
                    "producer_max_cycles",
                    "consumer_max_cycles",
                    "level1_batches",
                    "level2_batches",
                )
            }
        )
        runtime.update(
            output_sink=config["sink"], acknowledge_theory_transport_exclusions=True
        )
        common = {
            "two_level": runtime,
            "spec": layout["spec"],
            "placement": layout["placement"],
            "noise_params": config["noise_params"],
            "sampling": config["sampling"],
            "cache_root": _target_path(directory, "cache"),
            "dependencies": payload["dependencies"],
            "calibration_budget": {
                "timeout_s": budget["calibration_timeout_s"],
                "max_attempts": budget["software_max_attempts"],
                "memory_bytes": budget["memory_bytes"],
            },
            "output_sink": config["sink"],
            "input_z_error": config["input_z_error"],
            "geometry_layout_id": layout["geometry_layout_id"],
            "buffer_capacity": layout["buffer_capacity"],
            "arrival_evidence_sha256": plan["configuration"]["arrival_evidence_sha256"],
        }
        child_payload = {
            "phase": "two_level",
            "campaign_directory": str(directory),
            "layout_id": layout["layout_id"],
            "trajectories": [
                row for row in plan["tasks"] if row["layout_id"] == layout["layout_id"]
            ],
            "common": common,
            "budget": budget,
            "limits": {
                "raw_attempts": limits["raw_attempts"],
                "max_component_calls": limits["max_component_calls"],
                "max_cycles": limits["consumer_max_cycles"],
            },
            "pilot_seed": two_level["pilot_seed"],
            "observation_rule": two_level["observation_rule"],
            "allocation": allocation,
            "config_sha256": canonical_hash(plan["configuration"]),
            "source_sha256": canonical_hash(payload["source_identity"]),
        }
        if "pilot_cost_model" in config:
            child_payload["pilot_cost_model"] = deepcopy(config["pilot_cost_model"])
        children.append(
            _task(
                "msd.two_level_layout_driver",
                child_payload,
                budget,
                "export_timeout_s",
                terminal=True,
            )
        )
    return children, allocation


def advance_two_level(task: dict[str, Any], directory: Path) -> dict[str, Any]:
    """Freeze supply, request absent layout drivers, and retain every terminal cell.

    The caller gates this task on acceptance and terminal L1 drivers. Original L1
    proof is read on every invocation; committed geometry is reused without world
    reconstruction. Identity is published first and the completion marker last,
    so interrupted publications can resume only under the exact original inputs.
    Unsupported, supply, budget and selection exclusions remain plan coverage. There is
    no physical compilation, probability sampling or hidden execution fallback.
    """
    validate_task(task)
    payload = task["payload"]
    if task["kind"] != "msd.two_level_driver":
        raise ValueError("EXPECTED_TWO_LEVEL_DRIVER_TASK")
    if (
        not directory.is_absolute()
        or Path(payload["campaign_directory"]).resolve() != directory.resolve()
    ):
        raise ValueError("TWO_LEVEL_CAMPAIGN_DIRECTORY_MISMATCH")
    directory = directory.resolve()
    two_level = payload["configuration"]["two_level"]
    if (
        not isinstance(two_level, Mapping)
        or two_level.get("acknowledge_theory_transport_exclusions") is not True
    ):
        raise ValueError("EXPLICIT_THEORY_TRANSPORT_EXCLUSIONS_REQUIRED")
    _positive(payload["allocation"]["stage_worker_seconds"], "stage_worker_seconds")
    try:
        plan, artifacts = _freeze(task, directory)
    except ValueError as error:
        if str(error).startswith("Experiment already has a writer:"):
            return {"status": "deferred", "reason": str(error)}
        raise
    children, allocation = _children(payload, plan, directory)
    records = [
        {
            "task_id": child["task_id"],
            "layout_id": child["payload"]["layout_id"],
            "completion": _completion(directory, child["task_id"]),
        }
        for child in children
    ]
    missing_ids = {
        row["task_id"]
        for row in records
        if row["completion"] is None or row["completion"]["status"] == "invalidated"
    }
    result = {
        "two_level_plan": plan,
        "children": records,
        "allocation": allocation,
        "arrival_coverage": deepcopy(plan["arrival_evidence"].get("coverage", {})),
    }
    if missing_ids:
        return {
            "status": "needs_dependencies",
            "result": result,
            "artifacts": artifacts,
            "dependency_requests": [
                child for child in children if child["task_id"] in missing_ids
            ],
            "reason": {"stage": "two_level_layouts", "missing": len(missing_ids)},
        }
    statuses = {row["completion"]["status"] for row in records}
    if not statuses <= TERMINAL:
        raise ValueError("INVALID_TWO_LEVEL_CHILD_COMPLETION_STATUS")
    failed = statuses - {"ok"}
    return {
        "status": "software_error"
        if failed - {"budget_exceeded"}
        else "budget_exceeded"
        if failed
        else "ok",
        "result": result,
        "artifacts": artifacts,
    }
