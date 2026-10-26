"""Deterministic coverage, seed statistics and evidence-linked campaign exports.

Inference uses independent production seeds conditional on valid complete
observation windows. It excludes calibration uncertainty and never infers output
quality. JSON/CSV export does not require plotting or reconstruct atom events.
"""

from __future__ import annotations

import csv
import json
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from math import isclose, isfinite
from pathlib import Path
from statistics import fmean, stdev
from typing import Any

from nadit_physical_compiler.activity import derive_activity
from nadit_physical_compiler.cost.base import require_validated
from nadit_physical_compiler.provenance import canonical_hash
from nadit_physical_compiler.serialization import decode_program

from modules.codes.rotated_surface import definition
from modules.logical_compiler.src.placement import (
    PlacementPlan,
    VerticalFactoryPlacement,
    place,
)

from .production_metrics import _waves
from .standard import (
    FACTORY_ROLES,
    PAIR_SEPARATION_UM,
    SITE_PITCH_UM,
    ExperimentSpec,
    placement_request,
)
from .supply_metrics import summarize_supply_window

type ResultLoader = (
    Mapping[str, Mapping[str, Any]] | Callable[[Mapping[str, Any]], Mapping[str, Any]]
)
type _NativeActionRow = tuple[int, int, float, float, str, str, str, str]
type _NativeTemplate = tuple[float, tuple[_NativeActionRow, ...]]

_SUCCESS = {"ok", "complete", "completed", "passed", "succeeded"}
_FAILED = {
    "failed",
    "failure",
    "timeout",
    "timed_out",
    "cancelled",
    "budget_exhausted",
    "software_error",
}
_PENDING = {
    "pending",
    "pending_pilot",
    "ready",
    "running",
    "interrupted",
    "not_run",
    "pending_execution",
}
_TWO_LEVEL_FIELDS = (
    "geometry_layout_id",
    "level1_count",
    "level2_count",
    "buffer_capacity",
    "layout_families",
    "grid_columns",
    "home_occupied_bounding_area_um2",
    "total_slm_bounding_area_um2",
    "slm_site_count",
    "parking_site_count",
    "supply_exclusions",
    "source_layout_id",
    "arrival_group_id",
    "arrival_group_ids",
)
_SOFTWARE = ("cold_calibration", "cache_load", "fast_execution", "validation", "export")
_ALLOCATED_METRICS = (
    "allocated_slm_area_time_um2_us",
    "allocated_slm_area_time_per_accepted_output_um2_us",
    "allocated_slm_area_time_per_delivered_output_um2_us",
)

_SUPPLY_WINDOW_METRICS = {
    "buffer_slot_time_us": ("buffer", "occupied_slot_time_us"),
    "buffer_peak_occupancy": ("buffer", "peak_occupied_slots"),
    "buffer_mean_occupancy": ("buffer", "mean_occupied_slots"),
    "buffer_mean_residence_age_us": ("buffer", "token_time_weighted_mean_age_us"),
    "buffer_maximum_residence_age_us": ("buffer", "maximum_residence_age_us"),
    "source_backlog_peak": ("source_backlog", "peak_tokens"),
    "unconsumed_output_mean_age_us": (
        "unconsumed_outputs",
        "token_time_weighted_mean_age_us",
    ),
    "unconsumed_output_max_age_us": ("unconsumed_outputs", "maximum_age_us"),
    "l2_starvation_factory_time_us": ("waits", "consumer_starvation", "factory_sum_us"),
    "l2_starvation_union_us": ("waits", "consumer_starvation", "union_us"),
    "l1_backpressure_factory_time_us": (
        "waits",
        "producer_backpressure",
        "factory_sum_us",
    ),
    "l1_backpressure_union_us": ("waits", "producer_backpressure", "union_us"),
}
_METRICS = {
    "startup_deliverable_latency_us": ("startup_deliverable_latency_us",),
    "steady_deliverable_throughput_per_s": ("delivered_outputs_per_second",),
    "accepted_outputs": ("accepted_outputs",),
    "delivered_outputs": ("delivered_outputs",),
    "atom_time_per_accepted_output_us": (
        "per_accepted_output",
        "configured_atom_time_us",
    ),
    "area_time_per_accepted_output_um2_us": (
        "per_accepted_output",
        "occupied_bbox_area_time_um2_us",
    ),
    "idle_atom_time_per_accepted_output_us": (
        "per_accepted_output",
        "idle_atom_time_us",
    ),
    "transport_per_accepted_output_us": ("per_accepted_output", "transport_elapsed_us"),
    "movement_per_accepted_output_atom_um": (
        "per_accepted_output",
        "movement_distance_atom_um",
    ),
}


def _number(value: Any, field: str) -> float:
    if type(value) not in (int, float) or not isfinite(value) or value < 0:
        raise ValueError(f"INVALID_CAMPAIGN_METRIC: {field}")
    return float(value)


def _trajectory(task: Mapping[str, Any]) -> str:
    identity = task.get("trajectory_id", task.get("task_id"))
    if not isinstance(identity, str) or not identity:
        raise ValueError("CAMPAIGN_TRAJECTORY_ID_REQUIRED")
    return identity


def _status_records(
    status: Mapping[str, Any] | Sequence[Mapping[str, Any]],
) -> dict[str, Mapping[str, Any]]:
    records: dict[str, Mapping[str, Any]] = {}
    pairs = (
        status.items()
        if isinstance(status, Mapping)
        else ((_trajectory(row), row) for row in status)
    )
    for identity, value in pairs:
        row = {"status": value} if isinstance(value, str) else value
        if not isinstance(row, Mapping) or identity in records:
            raise ValueError("DUPLICATE_OR_INVALID_CAMPAIGN_STATUS")
        if row.get("trajectory_id", identity) != identity:
            raise ValueError("CAMPAIGN_STATUS_ID_MISMATCH")
        records[identity] = row
    return records


def _mean_ci(values: list[float], eligible: int) -> dict[str, Any]:
    """Use the preselected two-sided Student-t interval, without data-driven switches."""
    count = len(values)
    mean = fmean(values) if values else None
    interval = None
    if count >= 2:
        from scipy.stats import t  # type: ignore[import-untyped]

        assert mean is not None
        half = float(t.ppf(0.975, count - 1)) * stdev(values) / count**0.5
        interval = [mean - half, mean + half]
    return {
        "n": count,
        "eligible_valid_seeds": eligible,
        "missing_values": eligible - count,
        "mean": mean,
        "confidence_interval_95": interval,
    }


def _value(document: Mapping[str, Any], path: tuple[str, ...]) -> float | None:
    value: Any = document
    for key in path:
        if not isinstance(value, Mapping):
            return None
        value = value.get(key)
    return None if value is None else _number(value, ".".join(path))


def _policy(plan: Mapping[str, Any], layout_id: str) -> Mapping[str, Any] | None:
    policy = plan.get("observation_policy", {}).get("by_layout", {}).get(layout_id)
    if policy is None:
        return None
    if not isinstance(policy, Mapping):
        raise TypeError("INVALID_RESOLVED_CAMPAIGN_POLICY")
    warmup, stop = (
        _number(policy["warmup_us"], "warmup_us"),
        _number(policy["stop_us"], "stop_us"),
    )
    if stop <= warmup:
        raise ValueError("INVALID_RESOLVED_CAMPAIGN_WINDOW")
    return policy


def _load_result(
    task: Mapping[str, Any],
    layout: Mapping[str, Any],
    policy: Mapping[str, Any] | None,
    loader: ResultLoader,
) -> Mapping[str, Any]:
    identity = _trajectory(task)
    result = loader(task) if callable(loader) else loader[identity]
    expected = {
        "trajectory_id": identity,
        **{
            key: task[key]
            for key in ("layout_id", "seed", "config_sha256", "source_sha256")
        },
    }
    if any(result.get(key) != value for key, value in expected.items()):
        raise ValueError("STALE_CAMPAIGN_RESULT_IDENTITY")
    if policy is None or result.get("observation_policy_sha256") != canonical_hash(
        policy
    ):
        raise ValueError("CAMPAIGN_OBSERVATION_POLICY_MISMATCH")
    metrics = result["metrics"]
    if (
        metrics.get("schema") != "nadit.production_metrics/1"
        or metrics.get("actual_output_error") is not None
    ):
        raise ValueError("UNSUPPORTED_CAMPAIGN_METRICS_SCHEMA_OR_QUALITY")
    if metrics["requested_window_us"] != [policy["warmup_us"], policy["stop_us"]]:
        raise ValueError("CAMPAIGN_OBSERVATION_WINDOW_MISMATCH")
    if metrics["configured_atoms"] != layout["configured_atoms"] or not isclose(
        metrics["occupied_footprint_area_um2"],
        layout["occupied_bounding_area_um2"],
        abs_tol=1e-7,
    ):
        raise ValueError("CAMPAIGN_RESULT_RESOURCE_BUDGET_MISMATCH")
    if "geometry_layout_id" in layout:
        if any(
            result.get(key) != value
            for key, value in {
                "geometry_layout_id": layout["geometry_layout_id"],
                "buffer_capacity": layout["buffer_capacity"],
                "arrival_evidence_sha256": task["arrival_evidence_sha256"],
            }.items()
        ):
            raise ValueError("TWO_LEVEL_RESULT_CONTEXT_MISMATCH")
        expected_outputs = sorted(
            f"factory{i}"
            for i in range(layout["level1_count"], layout["factory_count"])
        )
        if (
            policy.get("output_factory_ids") != expected_outputs
            or metrics.get("output_factory_ids") != expected_outputs
            or any(
                row.get("factory_id") not in expected_outputs
                for row in metrics["outputs"]
            )
        ):
            raise ValueError("TWO_LEVEL_OUTPUT_SCOPE_MISMATCH")
        atom_time = layout["configured_atoms"] * metrics["actual_observation_us"]
        if not isclose(
            _number(metrics.get("configured_atom_time_us"), "configured_atom_time_us"),
            atom_time,
            abs_tol=1e-7,
        ):
            raise ValueError("TWO_LEVEL_ALL_LAYER_COST_MISMATCH")
    for key in ("accepted_outputs", "delivered_outputs"):
        if type(metrics[key]) is not int or metrics[key] < 0:
            raise ValueError("INVALID_CAMPAIGN_OUTPUT_COUNT")
    outputs = metrics["outputs"]
    if len({row["token_id"] for row in outputs}) != len(outputs):
        raise ValueError("DUPLICATE_CAMPAIGN_OUTPUT")
    if metrics["requested_window_complete"]:
        duration = policy["stop_us"] - policy["warmup_us"]
        if metrics["window_status"] != "complete" or not isclose(
            metrics["actual_observation_us"], duration, abs_tol=1e-7
        ):
            raise ValueError("INCONSISTENT_CAMPAIGN_COMPLETE_WINDOW")
        expected_rate = metrics["delivered_outputs"] * 1e6 / duration
        if not isclose(
            metrics["delivered_outputs_per_second"], expected_rate, abs_tol=1e-7
        ):
            raise ValueError("CAMPAIGN_THROUGHPUT_DENOMINATOR_MISMATCH")
    case = result.get("case")
    if case is not None:
        if case.get("seed") != task["seed"] or case.get("case_id") != metrics.get(
            "case_id"
        ):
            raise ValueError("CAMPAIGN_SCHEDULE_IDENTITY_MISMATCH")
        if result.get("case_sha256", canonical_hash(case)) != canonical_hash(case):
            raise ValueError("CAMPAIGN_SCHEDULE_HASH_MISMATCH")
        calls = case["execution"]["calls"]
        if len({call["invocation_id"] for call in calls}) != len(calls):
            raise ValueError("DUPLICATE_CAMPAIGN_SCHEDULE_INVOCATION")
        for call in calls:
            start = _number(call["start_us"], "schedule.start_us")
            end = _number(call["action_end_us"], "schedule.action_end_us")
            ready = _number(call["results_ready_us"], "schedule.results_ready_us")
            if not start <= end <= ready <= case["duration_us"]:
                raise ValueError("CAMPAIGN_SCHEDULE_TIME_MISMATCH")
            if (
                not isinstance(call.get("joint_trace_sha256"), str)
                or not call["joint_trace_sha256"]
            ):
                raise ValueError("CAMPAIGN_SCHEDULE_REQUIRES_TRACE_REFERENCES")
    return result


def _independent_arrival_groups(
    config: Mapping[str, Any],
    groups: Mapping[str, Mapping[str, Any]],
    distance: int,
    n1: int,
    n2: int,
) -> list[dict[str, Any]]:
    """Recompute eligibility per frozen source; never pool counts or seed windows."""
    records = []
    for identity, group in sorted(groups.items()):
        if group["distance"] != distance or group["level1_count"] != n1:
            continue
        excluded = []
        if len(group["trajectories"]) < config["minimum_arrival_seeds"]:
            excluded.append("minimum_arrival_seeds")
        if any(row["observed_arrivals"] < 15 * n2 for row in group["trajectories"]):
            excluded.append("arrival_count_below_15N2")
        records.append(
            {
                "arrival_group_id": identity,
                "source_layout_id": group["source_layout_id"],
                "trajectories": group["trajectories"],
                "supply_exclusions": excluded,
                "independently_eligible": not excluded,
            }
        )
    if not records:
        raise ValueError("TWO_LEVEL_ARRIVAL_GROUPS_REQUIRED")
    return records


def _two_level_inventory(
    plan: Mapping[str, Any],
) -> tuple[dict[str, Mapping[str, Any]], list[Mapping[str, Any]]]:
    """Audit saved geometry/capacity cells without constructing a physical world."""
    from .campaign_plan import _arrival_groups

    config, budget = plan["configuration"], plan["configuration"]["budget"]
    groups = {
        g["arrival_group_id"]: g
        for g in _arrival_groups(config, plan["arrival_evidence"])
    }
    layouts: dict[str, Mapping[str, Any]] = {}
    coverage: set[tuple[str, int, str, int, int]] = set()
    placements: dict[str, tuple[Mapping[str, Any], PlacementPlan]] = {}
    default_placements: dict[ExperimentSpec, PlacementPlan] = {}
    source_cells: dict[tuple[int, int, int], tuple[list[dict[str, Any]], str]] = {}
    for row in plan["layouts"]:
        saved = placements.get(row["geometry_layout_id"])
        if saved is None:
            placement = PlacementPlan.from_dict(row["placement"])
            placements[row["geometry_layout_id"]] = row["placement"], placement
        else:
            if row["placement"] != saved[0]:
                raise ValueError("CONFLICTING_TWO_LEVEL_GEOMETRY_CELLS")
            placement = saved[1]
        d, n1, n2 = row["distance"], row["level1_count"], row["level2_count"]
        spec = ExperimentSpec(**row["spec"])
        capacity = row["buffer_capacity"]
        source_cell = source_cells.get((d, n1, n2))
        if source_cell is None:
            source_rows = _independent_arrival_groups(config, groups, d, n1, n2)
            source_cell = source_rows, canonical_hash({"arrival_groups": source_rows})
            source_cells[d, n1, n2] = source_cell
        source_rows, source_hash = source_cell
        if canonical_hash({"arrival_groups": row.get("arrival_groups")}) != source_hash:
            raise ValueError("TWO_LEVEL_ARRIVAL_GROUPS_MISMATCH")
        eligible = [
            source for source in source_rows if source["independently_eligible"]
        ]
        representative = (eligible or source_rows)[0]
        expected_coverage = {
            "rule": "each_complete_seed_at_least_15N2",
            "required_arrivals_per_seed": 15 * n2,
            "minimum_complete_seeds": config["minimum_arrival_seeds"],
            "trajectories": representative["trajectories"],
            "throughput_prediction": False,
        }
        if (
            row["arrival_group_id"] != representative["arrival_group_id"]
            or row["source_layout_id"] != representative["source_layout_id"]
            or row["supply_exclusions"] != representative["supply_exclusions"]
            or canonical_hash(row["supply_coverage"])
            != canonical_hash(expected_coverage)
        ):
            raise ValueError("TWO_LEVEL_ARRIVAL_REPRESENTATIVE_MISMATCH")
        group = groups[representative["arrival_group_id"]]
        geometry_id = canonical_hash(
            {
                "geometry": placement.geometry_fingerprint,
                "standard": config["standard"],
                "parking_origin": row["parking_origin"],
                "level1_count": n1,
                "level2_count": n2,
            }
        )
        if (
            row["geometry_layout_id"] != geometry_id
            or row["layout_id"]
            != canonical_hash(
                {"geometry_layout_id": geometry_id, "buffer_capacity": capacity}
            )
            or row["layout_id"] in layouts
            or row["geometry_fingerprint"] != placement.geometry_fingerprint
            or row["factory_count"] != n1 + n2
            or spec.distance != d
            or spec.pipelines != n1 + n2
            or group["distance"] != d
            or group["level1_count"] != n1
            or row["source_layout_id"] != group["source_layout_id"]
            or any(block.distance != d for block in placement.blocks)
            or {block.factory_id for block in placement.blocks}
            != {f"factory{i}" for i in range(n1 + n2)}
        ):
            raise ValueError("STALE_TWO_LEVEL_LAYOUT_IDENTITY")
        bounds = placement.occupied_bounds
        area = (bounds.x_max - bounds.x_min) * (bounds.y_max - bounds.y_min)
        atoms = sum(definition(block.distance).atom_count for block in placement.blocks)
        # Both standard branches span these endpoints. Default vertical placement
        # preserves the historical whole-factory grid across role gaps; other
        # placements allocate separate block grids. Parking adds one empty grid.
        origins = [(p.origin.x, p.origin.y) for p in placement.placements.values()]
        origins.append((row["parking_origin"]["x"], row["parking_origin"]["y"]))
        left, bottom = min(x for x, _ in origins), min(y for _, y in origins)
        right = max(x for x, _ in origins) + 2 * d * SITE_PITCH_UM + PAIR_SEPARATION_UM
        top = max(y for _, y in origins) + 2 * d * SITE_PITCH_UM
        allocated = (right - left) * (top - bottom)
        sites_per_grid = 2 * (2 * d + 1) ** 2
        default = default_placements.get(spec)
        if default is None:
            default = place(
                placement_request(spec),
                VerticalFactoryPlacement(
                    FACTORY_ROLES, spec.patch_gap_um, spec.factory_gap_um
                ),
            )
            default_placements[spec] = default
        if placement.placements == default.placements:
            columns = round(bounds.x_max / SITE_PITCH_UM) + 1
            slm_sites = 2 * (2 * d + 1) * columns * spec.pipelines + sites_per_grid
        else:
            slm_sites = sites_per_grid * (len(placement.blocks) + 1)
        if (
            atoms != row["configured_atoms"]
            or not isclose(area, row["home_occupied_bounding_area_um2"], abs_tol=1e-7)
            or not isclose(allocated, row["total_slm_bounding_area_um2"], abs_tol=1e-7)
            or row["slm_bounding_box_um"] != [left, bottom, right, top]
            or row["slm_site_count"] != slm_sites
            or row["parking_site_count"] != sites_per_grid
            or row["parking_atom_count"] != 0
        ):
            raise ValueError("STALE_TWO_LEVEL_LAYOUT_RESOURCES")
        excluded = []
        if atoms > budget["max_atoms"]:
            excluded.append("max_atoms")
        if allocated > _number(budget["max_footprint_um2"], "max_footprint_um2"):
            excluded.append("max_footprint_um2")
        if row["budget_exclusions"] != excluded:
            raise ValueError("STALE_TWO_LEVEL_EXCLUSIONS")
        layouts[row["layout_id"]] = {
            **row,
            "occupied_bounding_area_um2": area,
            "arrival_group_ids": [source["arrival_group_id"] for source in source_rows],
        }
        coverage.update(
            (source["arrival_group_id"], n2, family, columns, capacity)
            for source in source_rows
            for family in row["layout_families"]
            for columns in row["grid_columns"]
        )
    expected = {
        (g["arrival_group_id"], n2, family, columns, capacity)
        for g in groups.values()
        if [g["distance"], g["distance"]] in config["distance_pairs"]
        for n2 in config["level2_counts"]
        for family in config["layout_families"]
        for columns in config["grid_columns"]
        for capacity in config["buffer_capacities"]
    }
    if coverage != expected:
        raise ValueError("INCOMPLETE_TWO_LEVEL_LAYOUT_CAPACITY_GRID")
    if "max_candidate_layouts" in config:
        from .campaign_plan import select_two_level_candidates

        selection = select_two_level_candidates(
            list(layouts.values()),
            max_candidate_layouts=config["max_candidate_layouts"],
        )
        if plan.get("candidate_selection") != selection:
            raise ValueError("STALE_TWO_LEVEL_CANDIDATE_SELECTION")
        selected_ids = set(selection["selected_layout_ids"])
        for row in layouts.values():
            exclusions = (
                ["max_candidate_layouts"]
                if not row["budget_exclusions"]
                and not row["supply_exclusions"]
                and row["layout_id"] not in selected_ids
                else []
            )
            if row.get("selection_exclusions") != exclusions:
                raise ValueError("STALE_TWO_LEVEL_SELECTION_EXCLUSIONS")
    elif "candidate_selection" in plan or any(
        "selection_exclusions" in row for row in layouts.values()
    ):
        raise ValueError("UNCONFIGURED_TWO_LEVEL_CANDIDATE_SELECTION")
    identities, seeded = set(), set()
    config_hash, source_hash = (
        canonical_hash(config),
        canonical_hash(plan["source_identity"]),
    )
    for task in plan["tasks"]:
        identity = _trajectory(task)
        row = layouts[task["layout_id"]]
        if task.get("selection_exclusions", []) != row.get("selection_exclusions", []):
            raise ValueError("TWO_LEVEL_TASK_SELECTION_EXCLUSIONS_MISMATCH")
        key = task["layout_id"], task["seed"]
        if identity in identities or key in seeded:
            raise ValueError("DUPLICATE_CAMPAIGN_TRAJECTORY_OR_SEED")
        identities.add(identity)
        seeded.add(key)
        if (
            task["phase"] != "two_level"
            or task["buffer_capacity"] != row["buffer_capacity"]
            or task["config_sha256"] != config_hash
            or task["source_sha256"] != source_hash
            or task["arrival_evidence_sha256"] != config["arrival_evidence_sha256"]
            or (
                "trajectory_id" not in task
                and task["task_id"]
                != canonical_hash(
                    {
                        name: task[name]
                        for name in (
                            "phase",
                            "layout_id",
                            "buffer_capacity",
                            "seed",
                            "config_sha256",
                            "source_sha256",
                            "arrival_evidence_sha256",
                        )
                    }
                )
            )
        ):
            raise ValueError("STALE_TWO_LEVEL_TASK_IDENTITY")
    if seeded != {
        (layout, seed) for layout in layouts for seed in config["production_seeds"]
    }:
        raise ValueError("INCOMPLETE_CAMPAIGN_SEED_GRID")
    tasks = sorted(
        plan["tasks"], key=lambda t: (t["layout_id"], t["seed"], _trajectory(t))
    )
    return layouts, tasks


def _supply_diagnostics(result: Mapping[str, Any], capacity: int) -> dict[str, Any]:
    """Describe the saved case-end snapshot; do not infer window maxima from it."""
    diagnostics: dict[str, Any] = {
        "status": "unavailable",
        "scope": "case-end supply snapshot; may be later than the observation stop",
        "snapshot_at_us": None,
        "buffer_occupied": None,
        "source_backlog_count": None,
        "consumer_backlog_count": None,
        "maximum_buffer_age_us": None,
        "mean_buffer_age_us": None,
        "window_maximum_source_backlog": None,
        "window_statistics_status": "not_derived_from_case_end_snapshot",
    }
    supply = result.get("supply")
    if (
        not isinstance(supply, Mapping)
        or supply.get("schema") != "nadit.factory_supply/1"
    ):
        return diagnostics
    buffer = supply["buffer"]
    if buffer["capacity"] != capacity:
        raise ValueError("TWO_LEVEL_SUPPLY_CAPACITY_MISMATCH")
    occupied = buffer["occupied"]
    if type(occupied) is not int or not 0 <= occupied <= capacity:
        raise ValueError("INVALID_TWO_LEVEL_SUPPLY_OCCUPANCY")
    snapshot = result.get("case", {}).get("duration_us")
    ages = []
    if snapshot is not None:
        snapshot = _number(snapshot, "supply.snapshot_at_us")
        for item in buffer.get("items", ()):
            queued = _number(item["queued_at_us"], "supply.queued_at_us")
            if queued > snapshot:
                raise ValueError("INVALID_TWO_LEVEL_BUFFER_AGE")
            ages.append(snapshot - queued)
    diagnostics.update(
        status="saved_snapshot",
        snapshot_at_us=snapshot,
        buffer_occupied=occupied,
        source_backlog_count=None
        if "waiting_producer_outputs" not in supply
        else len(supply["waiting_producer_outputs"]),
        consumer_backlog_count=None
        if "pending_consumer_requests" not in supply
        else len(supply["pending_consumer_requests"]),
        maximum_buffer_age_us=max(ages) if ages else None,
        mean_buffer_age_us=fmean(ages) if ages else None,
    )
    diagnostics["window"] = None
    window = result.get("metrics", {}).get("requested_window_us")
    if "audit" in buffer and window is not None and snapshot is not None:
        diagnostics["window"] = summarize_supply_window(
            result, warmup_us=window[0], stop_us=window[1]
        )
    return diagnostics


def _allocated_costs(
    result: Mapping[str, Any] | None, layout: Mapping[str, Any]
) -> dict[str, float | None]:
    """Charge the fixed allocated rectangle, separately from home/visited areas."""
    if result is None:
        return dict.fromkeys(_ALLOCATED_METRICS)
    metrics = result["metrics"]
    area_time = layout["total_slm_bounding_area_um2"] * _number(
        metrics["actual_observation_us"], "actual_observation_us"
    )
    return dict(
        zip(
            _ALLOCATED_METRICS,
            (
                area_time,
                area_time / metrics["accepted_outputs"]
                if metrics["accepted_outputs"]
                else None,
                area_time / metrics["delivered_outputs"]
                if metrics["delivered_outputs"]
                else None,
            ),
            strict=True,
        )
    )


def _plan_inventory(
    plan: Mapping[str, Any],
) -> tuple[dict[str, Mapping[str, Any]], list[Mapping[str, Any]]]:
    if plan.get("schema") == "nadit.msd.two_level_plan/1":
        return _two_level_inventory(plan)
    if plan.get("schema") != "nadit.msd.single_level_plan/1":
        raise ValueError("UNSUPPORTED_CAMPAIGN_PLAN")
    layouts = {row["layout_id"]: row for row in plan["layouts"]}
    if len(layouts) != len(plan["layouts"]):
        raise ValueError("DUPLICATE_CAMPAIGN_LAYOUT")
    budget = plan["configuration"]["budget"]
    for layout in layouts.values():
        placement = PlacementPlan.from_dict(layout["placement"])
        if layout["layout_id"] != canonical_hash(
            {
                "placement": layout["placement"],
                "standard": plan["configuration"]["standard"],
            }
        ):
            raise ValueError("STALE_CAMPAIGN_LAYOUT_ID")
        bounds = placement.occupied_bounds
        area = (bounds.x_max - bounds.x_min) * (bounds.y_max - bounds.y_min)
        atoms = sum(definition(block.distance).atom_count for block in placement.blocks)
        if atoms != layout["configured_atoms"] or not isclose(
            area, layout["occupied_bounding_area_um2"], abs_tol=1e-7
        ):
            raise ValueError("STALE_CAMPAIGN_LAYOUT_RESOURCES")
        expected_exclusions = []
        if atoms > budget["max_atoms"]:
            expected_exclusions.append("max_atoms")
        if (
            budget.get("max_footprint_um2") is not None
            and area > budget["max_footprint_um2"]
        ):
            expected_exclusions.append("max_footprint_um2")
        if layout["budget_exclusions"] != expected_exclusions:
            raise ValueError("STALE_CAMPAIGN_BUDGET_EXCLUSIONS")
    expected_layouts = {
        (distance, count, columns)
        for distance in plan["configuration"]["distances"]
        for count in plan["configuration"]["factory_counts"]
        for columns in range(1, count + 1)
        if count % columns == 0
    }
    actual_layouts = {
        (row["distance"], row["factory_count"], row["columns"])
        for row in layouts.values()
    }
    if actual_layouts != expected_layouts or len(actual_layouts) != len(layouts):
        raise ValueError("INCOMPLETE_OR_DUPLICATE_CAMPAIGN_LAYOUT_GRID")
    if any(task["layout_id"] not in layouts for task in plan["tasks"]):
        raise ValueError("UNKNOWN_CAMPAIGN_TASK_LAYOUT")
    tasks = sorted(
        plan["tasks"],
        key=lambda t: (
            layouts[t["layout_id"]]["distance"],
            layouts[t["layout_id"]]["factory_count"],
            layouts[t["layout_id"]]["columns"],
            t["seed"],
            _trajectory(t),
        ),
    )
    identities, seeds = set(), set()
    config_hash, source_hash = (
        canonical_hash(plan["configuration"]),
        canonical_hash(plan["source_identity"]),
    )
    for task in tasks:
        identity, seed = _trajectory(task), (task["layout_id"], task["seed"])
        if identity in identities or seed in seeds:
            raise ValueError("DUPLICATE_CAMPAIGN_TRAJECTORY_OR_SEED")
        identities.add(identity)
        seeds.add(seed)
        if task["config_sha256"] != config_hash or task["source_sha256"] != source_hash:
            raise ValueError("STALE_CAMPAIGN_TASK_SOURCE_OR_CONFIG")
        if "trajectory_id" not in task and task["task_id"] != canonical_hash(
            {
                key: task[key]
                for key in (
                    "phase",
                    "layout_id",
                    "seed",
                    "config_sha256",
                    "source_sha256",
                )
            }
        ):
            raise ValueError("STALE_CAMPAIGN_TASK_ID")
    expected_seeds = {
        (layout_id, seed)
        for layout_id in layouts
        for seed in plan["configuration"]["production_seeds"]
    }
    if seeds != expected_seeds:
        raise ValueError("INCOMPLETE_CAMPAIGN_SEED_GRID")
    return layouts, tasks


def summarize_campaign(
    resolved_plan: Mapping[str, Any],
    task_status: Mapping[str, Any] | Sequence[Mapping[str, Any]],
    result_loader: ResultLoader,
    *,
    output_dir: Path | None = None,
    plots: bool = False,
) -> dict[str, Any]:
    """Audit trajectory identities and export partial or complete campaign results.

    Status records are keyed by the plan's trajectory_id (task_id fallback).
    Loaded envelopes carry the same identity, layout/seed/source/config metadata,
    a per-layout observation-policy hash, and ``metrics`` from production_metrics.
    Optional ``case`` provides existing execution receipts for schedule export;
    optional artifacts and software_times_seconds retain original evidence.
    Missing/failed pilot policies are permitted only for tasks without results.
    """
    layouts, tasks = _plan_inventory(resolved_plan)
    two_level = resolved_plan["schema"] == "nadit.msd.two_level_plan/1"
    statuses = _status_records(task_status)
    if set(statuses) - {_trajectory(task) for task in tasks}:
        raise ValueError("UNKNOWN_CAMPAIGN_STATUS_ID")
    results: dict[str, Mapping[str, Any]] = {}
    rows = []
    for task in tasks:
        identity, layout = _trajectory(task), layouts[task["layout_id"]]
        status = statuses.get(identity, {"status": task.get("status", "not_run")})
        state = status["status"]
        excluded = layout["budget_exclusions"]
        if excluded:
            if state in _SUCCESS:
                raise ValueError("COMPLETED_CAMPAIGN_TASK_EXCEEDS_FROZEN_BUDGET")
            category = "budget_excluded"
        elif layout.get("supply_exclusions"):
            if state in _SUCCESS:
                raise ValueError("COMPLETED_CAMPAIGN_TASK_EXCEEDS_SUPPLY_COVERAGE")
            category = "supply_excluded"
        elif layout.get("selection_exclusions"):
            if state in _SUCCESS:
                raise ValueError("COMPLETED_CAMPAIGN_TASK_EXCEEDS_FROZEN_SELECTION")
            category = "selection_excluded"
        elif state in _SUCCESS:
            category = "complete"
        elif state in _FAILED:
            category = "failed"
        elif state == "budget_exceeded":
            category = "budget_exceeded"
        elif state == "blocked":
            category = "not_run_dependency"
        elif state in _PENDING:
            category = "not_run"
        else:
            raise ValueError(f"UNKNOWN_CAMPAIGN_TASK_STATUS: {state}")
        result = None
        if category == "complete" or (
            category not in ("budget_excluded", "supply_excluded", "selection_excluded")
            and status.get("result_available") is True
        ):
            result = _load_result(
                task, layout, _policy(resolved_plan, task["layout_id"]), result_loader
            )
            results[identity] = result
            metrics = result["metrics"]
            if category == "complete":
                if (
                    not metrics["requested_window_complete"]
                    or metrics["all_loaded_traces_validated"] is not True
                    or metrics.get("failures")
                    or metrics.get("run_status", "complete") != "complete"
                ):
                    category = "failed"
                elif metrics["delivered_outputs"] == 0:
                    category = "zero_output"
        reason = status.get("reason", status.get("error", status.get("failure")))
        if reason is None and category == "failed" and result is not None:
            reason = {
                "window_status": result["metrics"]["window_status"],
                "failures": result["metrics"].get("failures", []),
                "trace_validation": result["metrics"]["all_loaded_traces_validated"],
            }
        diagnostics = (
            _supply_diagnostics(result, layout["buffer_capacity"])
            if two_level and result is not None
            else None
        )
        supply_window = (diagnostics or {}).get("window") or {}
        rows.append(
            {
                "trajectory_id": identity,
                "layout_id": task["layout_id"],
                "seed": task["seed"],
                "distance": layout["distance"],
                "factory_count": layout["factory_count"],
                "columns": layout["columns"],
                **(
                    {key: deepcopy(layout[key]) for key in _TWO_LEVEL_FIELDS}
                    if two_level
                    else {}
                ),
                **(
                    {
                        "configured_atoms": layout["configured_atoms"],
                        "supply_diagnostics": diagnostics,
                        **{
                            name: _value(supply_window, path)
                            for name, path in _SUPPLY_WINDOW_METRICS.items()
                        },
                    }
                    if two_level
                    else {}
                ),
                **(_allocated_costs(result, layout) if two_level else {}),
                "status": category,
                "runner_status": state,
                "reason": reason
                if isinstance(reason, str) or reason is None
                else json.dumps(reason, sort_keys=True, allow_nan=False),
                "valid_complete_window": category in ("complete", "zero_output"),
                "budget_exclusions": deepcopy(excluded),
                **(
                    {"selection_exclusions": deepcopy(layout["selection_exclusions"])}
                    if "selection_exclusions" in layout
                    else {}
                ),
                "runner_detail": deepcopy(dict(status)),
                "accepted_outputs": None
                if result is None
                else result["metrics"]["accepted_outputs"],
                "delivered_outputs": None
                if result is None
                else result["metrics"]["delivered_outputs"],
                "actual_observation_us": None
                if result is None
                else result["metrics"]["actual_observation_us"],
                "metrics_window_status": None
                if result is None
                else result["metrics"]["window_status"],
                "metrics_failures": []
                if result is None
                else deepcopy(result["metrics"].get("failures", [])),
                "artifacts": {}
                if result is None
                else deepcopy(result.get("artifacts", {})),
            }
        )
    layout_rows = []
    budget = resolved_plan["configuration"]["budget"]
    for layout_id, layout in sorted(
        layouts.items(),
        key=lambda item: (
            item[1]["distance"],
            item[1]["factory_count"],
            item[1]["columns"],
            item[0],
        ),
    ):
        selected = [row for row in rows if row["layout_id"] == layout_id]
        valid = [
            results[row["trajectory_id"]]
            for row in selected
            if row["valid_complete_window"]
        ]
        statistics = {}
        for name, path in _METRICS.items():
            values = [
                value
                for result in valid
                if (value := _value(result["metrics"], path)) is not None
            ]
            statistics[name] = _mean_ci(values, len(valid))
        if two_level:
            allocated = [_allocated_costs(result, layout) for result in valid]
            for name in _ALLOCATED_METRICS:
                statistics[name] = _mean_ci(
                    [
                        value
                        for costs in allocated
                        if (value := costs[name]) is not None
                    ],
                    len(valid),
                )
            for name in _SUPPLY_WINDOW_METRICS:
                statistics[name] = _mean_ci(
                    [
                        row[name]
                        for row in selected
                        if row["valid_complete_window"] and row[name] is not None
                    ],
                    len(valid),
                )
        software = {}
        loaded = [
            results[row["trajectory_id"]]
            for row in selected
            if row["trajectory_id"] in results
        ]
        for name in _SOFTWARE:
            values = [
                value
                for result in loaded
                if (value := _value(result.get("software_times_seconds", {}), (name,)))
                is not None
            ]
            software[name] = {
                "observed_task_time_sum_seconds": sum(values) if values else None,
                "n_recorded": len(values),
                "n_missing": len(selected) - len(values),
            }
        footprint_limit = budget.get("max_footprint_um2")
        layout_rows.append(
            {
                **{
                    key: deepcopy(layout[key])
                    for key in (
                        "layout_id",
                        "distance",
                        "factory_count",
                        "columns",
                        "rows",
                        "configured_atoms",
                        "occupied_bounding_area_um2",
                        "budget_exclusions",
                    )
                },
                "common_budget": deepcopy(budget),
                **(
                    {
                        "arrival_groups": deepcopy(layout["arrival_groups"]),
                        "supply_coverage": deepcopy(layout["supply_coverage"]),
                    }
                    if two_level
                    else {}
                ),
                **(
                    {key: deepcopy(layout[key]) for key in _TWO_LEVEL_FIELDS}
                    if two_level
                    else {}
                ),
                "within_atom_budget": layout["configured_atoms"] <= budget["max_atoms"],
                "within_footprint_budget": footprint_limit is None
                or layout[
                    "total_slm_bounding_area_um2"
                    if two_level
                    else "occupied_bounding_area_um2"
                ]
                <= footprint_limit,
                "expected_seed_count": len(selected),
                "valid_seed_count": len(valid),
                "coverage": dict(
                    sorted(Counter(row["status"] for row in selected).items())
                ),
                "valid_production_seeds": [
                    row["seed"] for row in selected if row["valid_complete_window"]
                ],
                "observation_policy": deepcopy(_policy(resolved_plan, layout_id)),
                "statistics": statistics,
                "software_times": software,
            }
        )
    coverage = Counter(row["status"] for row in rows)
    valid_count = coverage["complete"] + coverage["zero_output"]
    finished = not coverage["not_run"]
    unsuccessful = (
        coverage["failed"]
        + coverage["budget_exceeded"]
        + coverage["not_run_dependency"]
    )
    complete = bool(valid_count) and not unsuccessful and finished
    summary = {
        "schema": "nadit.msd.campaign_report/1",
        "source_identity": deepcopy(resolved_plan["source_identity"]),
        "configuration_sha256": canonical_hash(resolved_plan["configuration"]),
        "resolved_plan_sha256": canonical_hash(resolved_plan),
        "status": "complete"
        if complete
        else "completed_with_failures"
        if finished and unsuccessful
        else "supply_excluded"
        if finished and not valid_count and coverage["supply_excluded"]
        else "selection_excluded"
        if finished and not valid_count and coverage["selection_excluded"]
        else "budget_excluded"
        if finished and not valid_count
        else "partial",
        "campaign_complete": complete,
        "all_tasks_terminal": finished,
        "expected_trajectories": len(rows),
        "valid_trajectories": valid_count,
        "coverage": dict(sorted(coverage.items())),
        "layouts": layout_rows,
        "trajectories": rows,
        "statistics_method": {
            "name": "two-sided Student-t mean interval",
            "confidence": 0.95,
            "unit": "independent production seed trajectory",
            "assumption": "approximately normal independent seed-level statistics; interval not truncated at zero",
            "fewer_than_two_samples": "mean retained; confidence interval null",
            "selection": "conditional on valid complete observation windows; per-metric nulls excluded with n reported",
            "calibration_uncertainty_included": False,
        },
        "software_time_basis": "sum of recorded task stage times; missing is null, not zero; concurrent task sums are not campaign wall time",
        "actual_output_error": None,
        "evidence_scope": "audited resource metrics and saved schedule references; no logical-quality inference or human visual acceptance",
    }
    if two_level:
        if "candidate_selection" in resolved_plan:
            summary["candidate_selection"] = deepcopy(
                resolved_plan["candidate_selection"]
            )
        summary.update(
            output_scope="final L2 outputs only; all levels and spectators contribute physical costs",
            footprint_budget_basis="total allocated SLM rectangle including empty parking; separate from configured home area-time",
            allocated_area_time_basis="fixed allocated SLM rectangle times actual observation duration; not dynamic occupied area-time",
            protocol_dependencies=deepcopy(resolved_plan["protocol_dependencies"]),
            unavailable_sources=deepcopy(resolved_plan["unavailable_sources"]),
        )
        if summary["protocol_dependencies"] or summary["unavailable_sources"]:
            summary["campaign_complete"] = False
            summary["status"] = (
                "unavailable_sources"
                if summary["unavailable_sources"]
                else "unsupported_protocol"
            )
    if output_dir is not None:
        _export(summary, resolved_plan, results, output_dir)
        if plots:
            export_plots(summary, resolved_plan, results, output_dir)
    elif plots:
        raise ValueError("CAMPAIGN_PLOTS_REQUIRE_OUTPUT_DIRECTORY")
    return summary


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream, fieldnames=fields, extrasaction="ignore", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


def _representatives(
    summary: Mapping[str, Any], results: Mapping[str, Mapping[str, Any]]
) -> dict[str, Mapping[str, Any]]:
    selected: dict[str, Mapping[str, Any]] = {}
    for row in sorted(
        summary["trajectories"],
        key=lambda r: (r["status"] != "complete", r["seed"], r["trajectory_id"]),
    ):
        result = results.get(row["trajectory_id"])
        if (
            row["valid_complete_window"]
            and result is not None
            and result.get("case") is not None
        ):
            selected.setdefault(row["layout_id"], result)
    return selected


def _native_template(path: Path, trace_sha256: str) -> _NativeTemplate:
    """Retain compact relative action rows; release the decoded atom world."""
    document = json.loads(path.read_text(encoding="utf-8"))
    if canonical_hash(document) != trace_sha256:
        raise ValueError("CAMPAIGN_NATIVE_TRACE_HASH_MISMATCH")
    require_validated(document)
    program = decode_program(document["program"])
    events = {
        (event.step_index, event.action_index): event
        for event in derive_activity(document).events
    }
    rows: list[_NativeActionRow] = []
    for step_index, (start, step) in enumerate(program.timeline()):
        for action_index, action in enumerate(step.actions):
            event = events[(step_index, action_index)]
            resource = ""
            if hasattr(action, "grid"):
                resource = "aod:" + action.grid.aod_id
            elif hasattr(action, "channel"):
                resource = "channel:" + action.channel
            rows.append(
                (
                    step_index,
                    action_index,
                    start,
                    action.duration_us,
                    type(action).__name__,
                    resource,
                    json.dumps(event.atoms, separators=(",", ":")),
                    json.dumps(action.source_ids, separators=(",", ":")),
                )
            )
    return program.duration_us, tuple(rows)


def _export_native_schedule(
    result: Mapping[str, Any], folder: Path
) -> tuple[dict[str, Any], dict[str, list[str]]]:
    """Stream saved native actions once per joint wave, never once per member."""
    if "calibration_records" not in result:
        return {
            "status": "not_provided",
            "reason": "calibration trace paths were not supplied",
        }, {}
    records = result["calibration_records"]
    if not isinstance(records, Mapping):
        raise TypeError("INVALID_CAMPAIGN_NATIVE_TRACE_RECORDS")
    paths: dict[str, set[str]] = {}
    for record in records.values():
        key, path = record.get("trace_sha256"), record.get("trace_path")
        if not isinstance(key, str) or not key or not isinstance(path, str) or not path:
            raise ValueError("CAMPAIGN_NATIVE_TRACE_REFERENCE_REQUIRED")
        paths.setdefault(key, set()).add(path)
    waves = _waves(result["case"])
    cached: dict[str, _NativeTemplate] = {}
    row_count = 0
    pending = folder / "native-action-schedule.csv.partial"
    final = folder / "native-action-schedule.csv"
    with pending.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(
            [
                "wave_id",
                "step_index",
                "action_index",
                "global_start_us",
                "global_end_us",
                "duration_us",
                "kind",
                "resource",
                "atom_ids",
                "trace_sha256",
                "source_ids",
            ]
        )
        for wave, key in waves:
            if key not in cached:
                if key not in paths:
                    raise ValueError(f"CAMPAIGN_NATIVE_TRACE_REFERENCE_MISSING: {key}")
                cached[key] = _native_template(Path(min(paths[key])), key)
            duration, rows = cached[key]
            if not isclose(
                duration, wave["end_us"] - wave["start_us"], rel_tol=1e-10, abs_tol=1e-7
            ):
                raise ValueError("CAMPAIGN_NATIVE_TRACE_DURATION_MISMATCH")
            offset = wave["start_us"]
            for step, action, start, span, kind, resource, atoms, sources in rows:
                writer.writerow(
                    [
                        wave["batch_id"],
                        step,
                        action,
                        offset + start,
                        offset + start + span,
                        span,
                        kind,
                        resource,
                        atoms,
                        key,
                        sources,
                    ]
                )
                row_count += 1
    pending.replace(final)
    return {
        "status": "exported",
        "filename": final.name,
        "row_count": row_count,
        "wave_count": len(waves),
        "unique_traces": len(cached),
        "cache_basis": "compact relative rows once per unique trace; decoded worlds and activities are not retained",
        "scope": "native saved trace actions at actual wave offsets; inter-wave waits remain in case.execution.waits and are not synthesized as atom actions",
    }, {key: sorted(paths[key]) for key in sorted(cached)}


def _export(
    summary: dict[str, Any],
    plan: Mapping[str, Any],
    results: Mapping[str, Mapping[str, Any]],
    output: Path,
) -> None:
    output.mkdir(parents=True, exist_ok=True)
    _write_json(output / "summary.json", summary)
    two_level_fields = (
        list(_TWO_LEVEL_FIELDS)
        if plan["schema"] == "nadit.msd.two_level_plan/1"
        else []
    )
    _write_csv(
        output / "trajectory-status.csv",
        summary["trajectories"],
        [
            "trajectory_id",
            "layout_id",
            "distance",
            "factory_count",
            "columns",
            "seed",
            "status",
            "runner_status",
            "reason",
            "valid_complete_window",
            "accepted_outputs",
            "delivered_outputs",
            "actual_observation_us",
            *two_level_fields,
            *(["configured_atoms"] if two_level_fields else []),
            *(list(_ALLOCATED_METRICS) if two_level_fields else []),
            *(list(_SUPPLY_WINDOW_METRICS) if two_level_fields else []),
        ],
    )
    flat = []
    for row in summary["layouts"]:
        record = {
            key: row[key]
            for key in (
                "layout_id",
                "distance",
                "factory_count",
                "columns",
                "configured_atoms",
                "occupied_bounding_area_um2",
                "expected_seed_count",
                "valid_seed_count",
            )
        }
        record.update({key: row[key] for key in two_level_fields})
        for metric, stats in row["statistics"].items():
            record[metric + "_mean"] = stats["mean"]
            record[metric + "_n"] = stats["n"]
            ci = stats["confidence_interval_95"]
            record[metric + "_ci95_low"] = None if ci is None else ci[0]
            record[metric + "_ci95_high"] = None if ci is None else ci[1]
        flat.append(record)
    fields = list(flat[0]) if flat else ["layout_id"]
    _write_csv(output / "layout-summary.csv", flat, fields)
    layouts = {row["layout_id"]: row for row in plan["layouts"]}
    for layout_id, result in _representatives(summary, results).items():
        folder = output / "representatives" / layout_id
        folder.mkdir(parents=True, exist_ok=True)
        case = result["case"]
        _write_json(folder / "placement.json", layouts[layout_id]["placement"])
        _write_json(folder / "case.json", case)
        calls = case["execution"]["calls"]
        if len({c["invocation_id"] for c in calls}) != len(calls):
            raise ValueError("DUPLICATE_CAMPAIGN_SCHEDULE_INVOCATION")
        schedule = [
            {
                "invocation": c["invocation_id"],
                "component": c["component_id"],
                "blocks": ";".join(c["participant_blocks"]),
                "start_us": c["start_us"],
                "action_end_us": c["action_end_us"],
                "results_ready_us": c["results_ready_us"],
                "reserved_resources": ";".join(c.get("reserved_resources", ())),
                "shared_resources": ";".join(c.get("shared_resources", ())),
                "joint_group": c.get("joint_group_key"),
                "joint_trace_sha256": c.get("joint_trace_sha256"),
            }
            for c in calls
        ]
        _write_csv(
            folder / "schedule.csv",
            schedule,
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
                "joint_trace_sha256",
            ],
        )
        native, trace_paths = _export_native_schedule(result, folder)
        _write_json(
            folder / "trace-references.json",
            {
                "trajectory_id": result["trajectory_id"],
                "case_sha256": canonical_hash(case),
                "joint_trace_sha256": sorted({c["joint_trace_sha256"] for c in calls}),
                "original_artifacts": deepcopy(result.get("artifacts", {})),
                "native_action_schedule": native,
                "trace_paths": trace_paths,
                "scope": "schedule.csv and schedule.png show full joint receipt spans including waits, not native component durations; native action CSV uses only saved trace actions",
            },
        )


def export_plots(
    summary: Mapping[str, Any],
    plan: Mapping[str, Any],
    results: Mapping[str, Mapping[str, Any]],
    output: Path,
) -> None:
    """Plot available seed statistics and saved plan/case coordinates; no simulation.

    Uses already installed matplotlib. Call after JSON/CSV export so report
    availability does not depend on plot generation. Missing cells remain absent
    from curves and visible in the coverage tables, never zero-filled.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    output.mkdir(parents=True, exist_ok=True)
    two_level = plan["schema"] == "nadit.msd.two_level_plan/1"
    dimensions = ("distance", "level1_count", "level2_count", "buffer_capacity")
    axes = (
        [
            (
                axis,
                (
                    *[name for name in dimensions if name != axis],
                    "columns",
                    "layout_families",
                ),
            )
            for axis in dimensions
        ]
        if two_level
        else [
            ("distance", ("factory_count", "columns")),
            ("factory_count", ("distance", "columns")),
        ]
    )
    labels = {
        "distance": "Code distance d",
        "factory_count": "Factory count N",
        "level1_count": "L1 factory count N1",
        "level2_count": "L2 factory count N2",
        "buffer_capacity": "Buffer capacity (tokens)",
    }
    for axis, groups in axes:
        fig, panels = plt.subplots(1, 2, figsize=(12, 4.5), constrained_layout=True)
        for panel, metric, label, scale in (
            (
                panels[0],
                "startup_deliverable_latency_us",
                "First deliverable output (ms)",
                0.001,
            ),
            (
                panels[1],
                "steady_deliverable_throughput_per_s",
                "Deliverable outputs / s",
                1,
            ),
        ):

            def group_key(
                row: Mapping[str, Any], fields: tuple[str, ...] = groups
            ) -> tuple[Any, ...]:
                return tuple(
                    tuple(row[name]) if isinstance(row[name], list) else row[name]
                    for name in fields
                )

            keys = sorted({group_key(row) for row in summary["layouts"]})
            for key in keys:
                rows = sorted(
                    (
                        row
                        for row in summary["layouts"]
                        if group_key(row) == key
                        and row["statistics"][metric]["mean"] is not None
                    ),
                    key=lambda row: row[axis],
                )
                if not rows:
                    continue
                panel.plot(
                    [row[axis] for row in rows],
                    [row["statistics"][metric]["mean"] * scale for row in rows],
                    marker="o",
                    linestyle="none" if two_level else "-",
                    label=", ".join(
                        f"{name}={value}"
                        for name, value in zip(groups, key, strict=True)
                    ),
                )
                for row in rows:
                    stats = row["statistics"][metric]
                    if stats["confidence_interval_95"] is not None:
                        low, high = stats["confidence_interval_95"]
                        panel.errorbar(
                            [row[axis]],
                            [stats["mean"] * scale],
                            yerr=[
                                [(stats["mean"] - low) * scale],
                                [(high - stats["mean"]) * scale],
                            ],
                            fmt="none",
                            capsize=3,
                        )
            panel.set(
                xlabel=labels[axis],
                ylabel=label,
            )
            panel.grid(alpha=0.25)
            if panel.lines:
                panel.legend(fontsize=7)
        fig.suptitle(
            f"Single shared AOD; {summary['status']}; conditional valid-seed means with Student-t 95% intervals"
        )
        fig.savefig(output / f"scaling-{axis}.png", dpi=160)
        plt.close(fig)
    layouts = {row["layout_id"]: row for row in plan["layouts"]}
    for layout_id, result in _representatives(summary, results).items():
        folder = output / "representatives" / layout_id
        folder.mkdir(parents=True, exist_ok=True)
        placement = PlacementPlan.from_dict(layouts[layout_id]["placement"])
        fig, panel = plt.subplots(figsize=(10, 5), constrained_layout=True)
        for block in placement.blocks:
            position = placement.placements[block.block_id].origin
            bounds = placement.geometries[block.code].relative_bounds
            panel.add_patch(
                Rectangle(
                    (position.x + bounds.x_min, position.y + bounds.y_min),
                    bounds.x_max - bounds.x_min,
                    bounds.y_max - bounds.y_min,
                    fill=False,
                )
            )
            panel.text(
                position.x + (bounds.x_min + bounds.x_max) / 2,
                position.y + (bounds.y_min + bounds.y_max) / 2,
                block.block_id,
                ha="center",
                va="center",
                fontsize=5,
            )
        bounds = placement.occupied_bounds
        if two_level:
            layout = layouts[layout_id]
            parking = layout["parking_origin"]
            width = 2 * layout["distance"] * SITE_PITCH_UM
            panel.add_patch(
                Rectangle(
                    (parking["x"], parking["y"]),
                    width + PAIR_SEPARATION_UM,
                    width,
                    fill=False,
                    linestyle="--",
                )
            )
            panel.text(
                parking["x"] + width / 2,
                parking["y"] + width / 2,
                "empty parking",
                ha="center",
                fontsize=5,
            )
            left, bottom, right, _top = layout["slm_bounding_box_um"]
        else:
            left, bottom, right = bounds.x_min, bounds.y_min, bounds.x_max
        panel.axhline(0, color="gray", linewidth=0.8)
        panel.axhline(50, color="gray", linewidth=0.8)
        panel.set(
            xlim=(left - 20, right + 20),
            ylim=(bottom - 20, 80),
            xlabel="x (um)",
            ylabel="y (um)",
            title="Saved home placement; readout y >= 50 um; one shared AOD",
        )
        panel.set_aspect("equal")
        fig.savefig(folder / "layout.png", dpi=160)
        plt.close(fig)
        calls = result["case"]["execution"]["calls"]
        lanes = {
            name: index
            for index, name in enumerate(
                sorted({b for c in calls for b in c["participant_blocks"]})
            )
        }
        fig, panel = plt.subplots(
            figsize=(12, max(3, len(lanes) * 0.22)), constrained_layout=True
        )
        colors = {
            name: index
            for index, name in enumerate(sorted({c["component_id"] for c in calls}))
        }
        cmap = plt.get_cmap("tab20")
        for call in calls:
            for block in call["participant_blocks"]:
                panel.broken_barh(
                    [
                        (
                            call["start_us"] / 1000,
                            (call["action_end_us"] - call["start_us"]) / 1000,
                        )
                    ],
                    (lanes[block] - 0.35, 0.7),
                    facecolors=cmap(colors[call["component_id"]] % 20),
                )
        panel.set(
            yticks=list(lanes.values()),
            yticklabels=list(lanes),
            xlabel="Elapsed time (ms)",
            title="Joint-wave receipt spans include waits, not native component durations\nNative atom timing is in native-action-schedule.csv when provided",
        )
        panel.tick_params(axis="y", labelsize=6)
        fig.savefig(folder / "schedule.png", dpi=160)
        plt.close(fig)
