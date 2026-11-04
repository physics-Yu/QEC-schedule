"""Read and validate frozen single-level arrivals without writing campaign files."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping
from copy import deepcopy
from math import isclose
from pathlib import Path
from typing import Any

from nadit_physical_compiler.experiments.task_plan import validate_task
from nadit_physical_compiler.provenance import canonical_hash

from modules.logical_compiler.src.placement import PlacementPlan

from .campaign_report import _load_result, _plan_inventory
from .production_metrics import (
    _index_delivery_audit,
    _time,
    _verified_offer,
    _verify_output_delivery,
)
from .standard import STANDARD_ID


def _read(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise TypeError(f"ARRIVAL_SOURCE_REQUIRES_JSON_OBJECT: {path}")
    return document


def _task_inventory(
    directory: Path,
    trajectories: Mapping[str, Mapping[str, Any]],
    layouts: Mapping[str, Mapping[str, Any]],
    config_hash: str,
    source_hash: str,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    producers, drivers = {}, {}
    for path in sorted((directory / "task_definitions").glob("*.json")):
        task = validate_task(_read(path))
        if path.stem != task["task_id"]:
            raise ValueError("ARRIVAL_TASK_FILENAME_IDENTITY_MISMATCH")
        if task["kind"] not in ("msd.produce", "msd.layout_driver"):
            continue
        payload = task["payload"]
        if (
            payload.get("source_sha256") != source_hash
            or payload.get("config_sha256") != config_hash
            or payload.get("layout_id") not in layouts
        ):
            raise ValueError("ARRIVAL_TASK_SOURCE_OR_LAYOUT_MISMATCH")
        if task["kind"] == "msd.layout_driver":
            identity = payload["layout_id"]
            if identity in drivers:
                raise ValueError("DUPLICATE_ARRIVAL_LAYOUT_DRIVER")
            drivers[identity] = task
            continue
        identity = payload.get("trajectory_id")
        if identity not in trajectories or identity in producers:
            raise ValueError("UNKNOWN_OR_DUPLICATE_ARRIVAL_TRAJECTORY")
        row = trajectories[identity]
        if (
            type(payload.get("seed")) is not int
            or type(payload.get("production_seed")) is not int
            or any(
                payload.get(key) != row[key]
                for key in ("layout_id", "seed", "config_sha256", "source_sha256")
            )
            or payload.get("production_seed") != row["seed"]
        ):
            raise ValueError("ARRIVAL_PRODUCTION_TASK_IDENTITY_MISMATCH")
        layout = layouts[row["layout_id"]]
        if (
            payload.get("placement") != layout["placement"]
            or type(payload.get("spec", {}).get("distance")) is not int
            or type(payload.get("spec", {}).get("pipelines")) is not int
            or payload.get("spec", {}).get("distance") != layout["distance"]
            or payload.get("spec", {}).get("pipelines") != layout["factory_count"]
        ):
            raise ValueError("ARRIVAL_TASK_GEOMETRY_MISMATCH")
        producers[identity] = task
    return producers, drivers


def _policy(directory: Path, task: Mapping[str, Any]) -> dict[str, Any]:
    from .campaign_driver import _local

    payload = task["payload"]
    descriptor = payload["observation_policy_artifact"]
    if (
        not isinstance(descriptor, Mapping)
        or set(descriptor) != {"path", "sha256", "hash_kind"}
        or descriptor["hash_kind"] != "canonical_json"
    ):
        raise ValueError("INVALID_ARRIVAL_POLICY_DESCRIPTOR")
    path = _local(directory, descriptor["path"])
    envelope = _read(path)
    policy = payload["observation_policy"]
    if (
        canonical_hash(envelope) != descriptor["sha256"]
        or envelope.get("schema") != "nadit.msd.frozen_observation_policy/1"
        or envelope.get("policy") != policy
        or envelope.get("policy_sha256") != canonical_hash(policy)
        or any(
            envelope.get("identity", {}).get(key) != payload[key]
            for key in ("layout_id", "config_sha256", "source_sha256")
        )
        or _read(path.with_name("frozen.json"))
        != {"policy_artifact_sha256": descriptor["sha256"]}
    ):
        raise ValueError("FROZEN_ARRIVAL_POLICY_MISMATCH")
    low, high = _time(policy["warmup_us"]), _time(policy["stop_us"])
    if low >= high:
        raise ValueError("INVALID_ARRIVAL_OBSERVATION_WINDOW")
    return dict(policy)


def _arrivals(
    case: Mapping[str, Any],
    metrics: Mapping[str, Any],
    layout: Mapping[str, Any],
    low: float,
    high: float,
) -> list[dict[str, Any]]:
    blocks = {
        block.block_id: block
        for block in PlacementPlan.from_dict(layout["placement"]).blocks
    }
    factories = {str(block.factory_id) for block in blocks.values()}
    if (
        set(case["factories"]) != factories
        or set(metrics["output_factory_ids"]) != factories
    ):
        raise ValueError("ARRIVAL_FACTORY_COVERAGE_MISMATCH")
    resources = case["resources"]
    tokens = {token["token_id"]: token for token in resources["tokens"]}
    carriers = {carrier["carrier_id"]: carrier for carrier in resources["carriers"]}
    measured = {output["token_id"]: output for output in metrics["outputs"]}
    if (
        len(tokens) != len(resources["tokens"])
        or len(carriers) != len(resources["carriers"])
        or len(measured) != len(metrics["outputs"])
        or set(carriers) != set(blocks)
    ):
        raise ValueError("ARRIVAL_DUPLICATE_OR_MISSING_RESOURCE_IDENTITY")
    for identity, carrier in carriers.items():
        block = blocks[identity]
        if carrier["code_id"] != block.code or carrier["distance"] != block.distance:
            raise ValueError("ARRIVAL_CARRIER_CODE_MISMATCH")
    audit = _index_delivery_audit(resources["audit"])
    seen: set[str] = set()
    arrivals = []
    accepted = delivered = 0
    duration = _time(case["duration_us"])
    for factory, line in case["factories"].items():
        for output in line.get("outputs", ()):
            identity, carrier_id = output["token_id"], output["carrier_id"]
            if identity in seen or identity not in tokens or identity not in measured:
                raise ValueError("ARRIVAL_DUPLICATE_OR_MISSING_OUTPUT")
            seen.add(identity)
            token, metric = tokens[identity], measured[identity]
            if (
                carrier_id not in blocks
                or blocks[carrier_id].factory_id != factory
                or output["code"] != blocks[carrier_id].code
                or output["distance"] != blocks[carrier_id].distance
                or any(
                    token.get(key) != output[key]
                    for key in ("carrier_id", "epoch", "quality", "ready_at_us")
                )
                or type(output["epoch"]) is not int
                or type(token["epoch"]) is not int
                or any(metric.get(key) != value for key, value in output.items())
                or metric.get("factory_id") != factory
                or metric.get("delivery_lifecycle_verified") is not True
                or output.get("handoff") is not None
                or output.get("retention") is not None
            ):
                raise ValueError("ARRIVAL_OUTPUT_METRIC_OR_LEDGER_MISMATCH")
            times = [
                _time(output[key])
                for key in (
                    "ready_at_us",
                    "deliverable_at_us",
                    "consumed_at_us",
                    "released_at_us",
                )
            ]
            if times != sorted(times) or times[-1] > duration:
                raise ValueError("ARRIVAL_OUTPUT_TIME_MISMATCH")
            offered = _verified_offer(token, audit)
            if not _verify_output_delivery(output, token, audit):
                raise ValueError("ARRIVAL_REQUIRES_TERMINAL_DELIVERY")
            reserves = audit.reserves.get(identity, ())
            consumption = audit.consumes[identity][0]
            if (
                len(reserves) != 1
                or reserves[0][1]["consumer"] != token["consumer"]
                or not times[0] <= reserves[0][1]["at_us"] <= times[2]
                or not (offered["at_us"], audit.offers[identity][0][0])
                <= (reserves[0][1]["at_us"], reserves[0][0])
                <= (consumption[1]["at_us"], consumption[0])
            ):
                raise ValueError("ARRIVAL_RESERVATION_LIFECYCLE_MISMATCH")
            in_ready, in_delivered = low <= times[0] < high, low <= times[1] < high
            if (
                metric.get("accepted_in_window") is not in_ready
                or metric.get("delivered_in_window") is not in_delivered
            ):
                raise ValueError("ARRIVAL_WINDOW_FLAG_MISMATCH")
            accepted += in_ready
            delivered += in_delivered
            arrivals.append(
                {
                    "token_id": identity,
                    "factory_id": factory,
                    "carrier_id": carrier_id,
                    "epoch": output["epoch"],
                    "ready_at_us": times[0],
                    "deliverable_at_us": times[1],
                    "quality": deepcopy(output["quality"]),
                }
            )
    if set(measured) != seen or any(
        type(metrics[key]) is not int or metrics[key] != expected
        for key, expected in (
            ("accepted_outputs", accepted),
            ("delivered_outputs", delivered),
            ("accepted_outputs_total", len(arrivals)),
            ("terminal_deliveries_total", len(arrivals)),
        )
    ):
        raise ValueError("ARRIVAL_METRIC_COUNT_MISMATCH")
    return sorted(
        arrivals,
        key=lambda row: (row["deliverable_at_us"], row["ready_at_us"], row["token_id"]),
    )


def freeze_arrival_evidence(
    single_level_plan: Mapping[str, Any], directory: Path
) -> dict[str, Any]:
    """Return deterministic arrival evidence from original frozen runner records.

    The input is campaign.layout_plan from expand_single_level. Task definitions,
    completions, result/case hashes, frozen policy artifacts, metrics and token
    lifecycles are cross-checked. Only complete successful trajectories enter
    arrivals; absent, failed and incomplete sources remain explicit exclusions.
    Tokens are unique within each trajectory, never merged across seeds or scaled
    by factory count. Result hashes cannot be reused for another trajectory.

    This reads only, does not validate physics again, and makes no output-error
    inference. The caller freezes the returned document and its hash. Invalid
    identities or inconsistent evidence raise ValueError; missing source files
    referenced by a completed task raise OSError rather than inventing evidence.
    """
    from .campaign_driver import _completion, _result

    directory = directory.resolve()
    if (
        single_level_plan.get("schema") != "nadit.msd.single_level_plan/1"
        or single_level_plan["configuration"]["standard"] != STANDARD_ID
    ):
        raise ValueError("ARRIVAL_REQUIRES_SINGLE_LEVEL_STANDARD_PLAN")
    layouts, rows = _plan_inventory(single_level_plan)
    source = single_level_plan["source_identity"]
    if not isinstance(source, Mapping) or not source:
        raise ValueError("ARRIVAL_SOURCE_IDENTITY_REQUIRED")
    source_hash, config_hash = (
        canonical_hash(source),
        canonical_hash(single_level_plan["configuration"]),
    )
    planned = {row.get("trajectory_id", row["task_id"]): row for row in rows}
    producers, drivers = _task_inventory(
        directory, planned, layouts, config_hash, source_hash
    )
    trajectories, excluded = [], []
    coverage: Counter[str] = Counter()
    used_results: set[str] = set()
    policies: dict[str, Mapping[str, Any]] = {}
    for identity, row in sorted(planned.items()):
        layout = layouts[row["layout_id"]]
        task = producers.get(identity)
        completion = None if task is None else _completion(directory, task["task_id"])
        reason: Any = None
        status = "not_run"
        if layout["budget_exclusions"]:
            status, reason = "budget_excluded", list(layout["budget_exclusions"])
        elif completion is None or completion["status"] == "invalidated":
            driver = drivers.get(row["layout_id"])
            parent = (
                None if driver is None else _completion(directory, driver["task_id"])
            )
            if parent is not None and parent["status"] in (
                "software_error",
                "blocked",
                "budget_exceeded",
            ):
                assert driver is not None
                status, reason = (
                    "blocked",
                    {
                        "driver_task_id": driver["task_id"],
                        "driver_status": parent["status"],
                        "cause": parent.get("reason"),
                    },
                )
            else:
                reason = "production_completion_unavailable"
        elif completion["status"] != "ok":
            status, reason = completion["status"], completion.get("reason")
        else:
            assert task is not None
            if completion.get("kind") != "msd.produce":
                raise ValueError("ARRIVAL_COMPLETION_KIND_MISMATCH")
            result_hash = completion.get("result_sha256")
            if not isinstance(result_hash, str) or result_hash in used_results:
                raise ValueError("DUPLICATE_OR_MISSING_ARRIVAL_RESULT_SHA256")
            used_results.add(result_hash)
            result = _result(directory, completion)
            case = result["case"]
            if type(result.get("seed")) is not int or type(case.get("seed")) is not int:
                raise ValueError("ARRIVAL_SEED_REQUIRES_INTEGER")
            if result.get("case_sha256") != canonical_hash(case):
                raise ValueError("ARRIVAL_CASE_HASH_MISMATCH")
            policy = _policy(directory, task)
            if row["layout_id"] in policies and policies[row["layout_id"]] != policy:
                raise ValueError("ARRIVAL_LAYOUT_POLICY_CHANGED_BETWEEN_SEEDS")
            policies[row["layout_id"]] = policy
            _load_result(row, layout, policy, {identity: result})
            metrics = result["metrics"]
            if (
                case["status"] != "complete"
                or case.get("failure") is not None
                or any(
                    line["status"] != "complete" or line.get("failure") is not None
                    for line in case["factories"].values()
                )
                or metrics.get("failures")
            ):
                status, reason = "failed", "case_or_factory_failure"
            elif (
                metrics.get("requested_window_complete") is not True
                or metrics.get("window_status") != "complete"
            ):
                status, reason = "incomplete_window", metrics.get("window_status")
            else:
                low, high = _time(policy["warmup_us"]), _time(policy["stop_us"])
                duration = _time(case["duration_us"])
                if (
                    duration < high
                    or metrics.get("all_loaded_traces_validated") is not True
                    or not isclose(
                        metrics["actual_observation_us"], high - low, abs_tol=1e-7
                    )
                ):
                    raise ValueError("ARRIVAL_COMPLETE_WINDOW_OR_VALIDATION_MISMATCH")
                arrivals = _arrivals(case, metrics, layout, low, high)
                trajectories.append(
                    {
                        "trajectory_id": identity,
                        "layout_id": row["layout_id"],
                        "distance": layout["distance"],
                        "factory_count": layout["factory_count"],
                        "seed": row["seed"],
                        "window_us": [low, high],
                        "duration_us": duration,
                        "status": "complete",
                        "window_complete": True,
                        "source_sha256": source_hash,
                        "config_sha256": config_hash,
                        "result_sha256": result_hash,
                        "case_sha256": result["case_sha256"],
                        "runner_task_id": task["task_id"],
                        "observation_policy_sha256": canonical_hash(policy),
                        "arrivals": arrivals,
                    }
                )
                coverage["complete"] += 1
                continue
        coverage[status] += 1
        excluded.append(
            {
                "trajectory_id": identity,
                "layout_id": row["layout_id"],
                "seed": row["seed"],
                "status": status,
                "reason": deepcopy(reason),
                **({"runner_task_id": task["task_id"]} if task is not None else {}),
            }
        )
    return {
        "schema": "nadit.msd.arrival_evidence/1",
        "standard": STANDARD_ID,
        "source_identity": deepcopy(dict(source)),
        "source_sha256": source_hash,
        "config_sha256": config_hash,
        "single_level_plan_sha256": canonical_hash(single_level_plan),
        "trajectories": trajectories,
        "coverage": dict(sorted(coverage.items())),
        "expected_trajectory_count": len(planned),
        "complete_trajectory_count": len(trajectories),
        "excluded_trajectories": excluded,
        "actual_output_error": None,
        "evidence_scope": "original runner result and policy hashes, complete metrics and ledger-verified terminal outputs; no physics revalidation",
    }
