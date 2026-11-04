"""Windowed block-center cost accounting without loading atom action traces.

Segments are declared aggregates, not reconstructed atom trajectories. Movement
distance within a clipped segment follows the explicit constant-speed center
model. Optional busy_atom_us preserves an aggregate exposure integral; clipping
assumes that exposure is uniformly distributed inside its declared category
partition. Idle includes unselected atoms, wave padding and all waiting.
"""

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from copy import deepcopy
from math import isclose, isfinite
from typing import Any

from modules.codes.rotated_surface.definition import definition
from modules.logical_compiler.src.estimation.metrics import interval_union_us
from modules.logical_compiler.src.placement import PlacementPlan, validate_plan

from .production_metrics import _index_delivery_audit, _verify_output_delivery


def _number(value: Any) -> float:
    if type(value) not in (int, float) or not isfinite(value) or value < 0:
        raise ValueError("INVALID_CENTER_METRIC_NONNEGATIVE_NUMBER")
    return float(value)


def _clip(
    start: float, end: float, low: float, high: float
) -> tuple[float, float] | None:
    left, right = max(start, low), min(end, high)
    return (left, right) if right > left else None


def _output_rows(
    case: Mapping[str, Any], plan: PlacementPlan, low: float, high: float
) -> list[dict[str, Any]]:
    """Reuse the existing ledger delivery verifier without creating a world."""
    tokens = {row["token_id"]: row for row in case["resources"]["tokens"]}
    if len(tokens) != len(case["resources"]["tokens"]):
        raise ValueError("DUPLICATE_CENTER_METRIC_TOKEN")
    audit = _index_delivery_audit(case["resources"]["audit"])
    blocks = {block.block_id: block for block in plan.blocks}
    outputs, seen = [], set()
    for factory, line in case["factories"].items():
        for output in line.get("outputs", ()):
            identity = output["token_id"]
            token = tokens.get(identity)
            if (
                identity in seen
                or token is None
                or output["carrier_id"] not in blocks
                or blocks[output["carrier_id"]].factory_id != factory
                or any(
                    token[key] != output[key]
                    for key in ("carrier_id", "epoch", "ready_at_us", "quality")
                )
                or type(output["epoch"]) is not int
                or output.get("handoff") is not None
                or output.get("retention") is not None
            ):
                raise ValueError("CENTER_OUTPUT_LEDGER_MISMATCH_OR_UNSUPPORTED_HANDOFF")
            seen.add(identity)
            ready = previous = _number(output["ready_at_us"])
            missing = False
            for field in ("deliverable_at_us", "consumed_at_us", "released_at_us"):
                value = output[field]
                if value is None:
                    missing = True
                else:
                    current = _number(value)
                    if missing or current < previous or current > case["duration_us"]:
                        raise ValueError("CENTER_OUTPUT_TIME_ORDER_MISMATCH")
                    previous = current
            if ready > case["duration_us"]:
                raise ValueError("CENTER_OUTPUT_AFTER_CASE_END")
            verified = _verify_output_delivery(output, token, audit)
            delivered = output["deliverable_at_us"]
            outputs.append(
                {
                    **deepcopy(dict(output)),
                    "factory_id": factory,
                    "delivery_lifecycle_verified": verified,
                    "accepted_in_window": low <= ready < high,
                    "delivered_in_window": verified
                    and delivered is not None
                    and low <= delivered < high,
                }
            )
    return outputs


def _calls(case: Mapping[str, Any], plan: PlacementPlan) -> list[Mapping[str, Any]]:
    """Check one wave coverage and disjoint participant ownership per call."""
    rows: list[Mapping[str, Any]] = case["execution"]["calls"]
    calls = {row["invocation_id"]: row for row in rows}
    if len(calls) != len(rows):
        raise ValueError("DUPLICATE_CENTER_METRIC_CALL")
    blocks = {block.block_id for block in plan.blocks}
    seen: set[str] = set()
    batch_ids: set[str] = set()
    previous = 0.0
    for wave in case["execution"]["waves"]:
        start, end = _number(wave["start_us"]), _number(wave["end_us"])
        members = wave["invocations"]
        if (
            start < previous
            or end < start
            or end > case["duration_us"]
            or wave["batch_id"] in batch_ids
            or not members
            or len(set(members)) != len(members)
            or seen.intersection(members)
        ):
            raise ValueError("INVALID_CENTER_METRIC_WAVE")
        occupied: set[str] = set()
        for identity in members:
            if identity not in calls:
                raise ValueError("UNKNOWN_CENTER_METRIC_WAVE_CALL")
            call = calls[identity]
            participants = call["participant_blocks"]
            if (
                not participants
                or len(set(participants)) != len(participants)
                or not set(participants) <= blocks
                or occupied.intersection(participants)
                or _number(call["start_us"]) != start
                or not start <= _number(call["action_end_us"]) <= end
            ):
                raise ValueError("CENTER_METRIC_PARTICIPANT_OR_WAVE_TIME_MISMATCH")
            occupied.update(participants)
        previous = end
        seen.update(members)
        batch_ids.add(wave["batch_id"])
    if seen != set(calls):
        raise ValueError("CENTER_METRIC_CALL_MISSING_WAVE")
    return rows


def summarize_center_case(
    case: Mapping[str, Any],
    plan: PlacementPlan,
    *,
    warmup_us: float = 0,
    stop_us: float | None = None,
) -> dict[str, Any]:
    """Account declared active subsets and verified output lifecycles in a window.

    Point counts use [warmup, stop), intervals use exact intersections. Missing
    segments, aliased participants and invalid output consumption fail closed.
    Incomplete/failed windows retain costs and outputs but have no throughput.
    """
    validate_plan(plan)
    factories = set(case["factories"])
    if (
        not factories
        or {block.factory_id for block in plan.blocks} != factories
        or len({block.distance for block in plan.blocks}) != 1
        or any(
            block.code != f"rotated_surface_d{block.distance}" for block in plan.blocks
        )
        or any(
            Counter(block.role for block in plan.blocks if block.factory_id == factory)
            != Counter(("W1", "W2", "W3", "W4", "W5", "R"))
            for factory in factories
        )
    ):
        raise ValueError("CENTER_METRIC_FACTORY_LAYOUT_MISMATCH")
    duration, low = _number(case["duration_us"]), _number(warmup_us)
    stop = duration if stop_us is None else _number(stop_us)
    if stop <= low:
        raise ValueError("INVALID_CENTER_METRIC_WINDOW")
    high, elapsed = min(stop, duration), max(0.0, min(stop, duration) - low)
    if case.get("physical") is not None:
        raise ValueError("CENTER_METRICS_REQUIRE_LOGICAL_ESTIMATE")
    sizes = {
        block.block_id: definition(block.distance).atom_count for block in plan.blocks
    }
    atoms = sum(sizes.values())
    calls = _calls(case, plan)
    busy = distance = 0.0
    aggregate_segments = 0
    category_intervals: dict[str, list[tuple[float, float]]] = defaultdict(list)
    resource_intervals: dict[str, list[tuple[float, float]]] = defaultdict(list)
    exposure: dict[str, dict[str, Any]] = {}
    primitives: Counter[str] = Counter()
    component_counts: Counter[str] = Counter()
    for call in calls:
        if low <= call["start_us"] < high:
            component_counts[call["component_id"]] += 1
        if "estimate_segments" not in call:
            raise ValueError("CENTER_METRIC_SEGMENTS_REQUIRED")
        last = 0.0
        capacity = sum(sizes[block] for block in call["participant_blocks"])
        for segment in call["estimate_segments"]:
            left, right = (
                _number(segment["start_offset_us"]),
                _number(segment["end_offset_us"]),
            )
            selected = segment["atom_count"]
            moved = _number(segment["movement_distance_atom_um"])
            active_atom_time = _number(
                segment.get("busy_atom_us", selected * (right - left))
            )
            category, resource = segment["category"], segment["resource"]
            counts = segment["primitive_counts"]
            if (
                left < last
                or right < left
                or right > call["action_end_us"] - call["start_us"] + 1e-7
                or type(selected) is not int
                or not 0 <= selected <= capacity
                or not isinstance(category, str)
                or not category
                or not isinstance(resource, str)
                or not resource
                or segment["basis"]
                not in (
                    "calibration_intrinsic",
                    "block_center_transport",
                    "assumed_transversal_s",
                )
                or (right == left and moved != 0)
                or active_atom_time > selected * (right - left) + 1e-7
                or not isinstance(counts, Mapping)
                or any(
                    not isinstance(name, str)
                    or not name
                    or type(count) is not int
                    or count < 0
                    for name, count in counts.items()
                )
            ):
                raise ValueError("INVALID_CENTER_METRIC_SEGMENT")
            last = right
            aggregate_segments += int("busy_atom_us" in segment)
            start, end = call["start_us"] + left, call["start_us"] + right
            row = exposure.setdefault(
                category,
                {
                    "macro_segment_starts": 0,
                    "overlapping_macro_segments": 0,
                    "active_atom_time_us": 0.0,
                    "movement_distance_atom_um": 0.0,
                    "primitive_counts": Counter(),
                },
            )
            if low <= start < high:
                row["macro_segment_starts"] += 1
                row["primitive_counts"].update(counts)
                primitives.update(counts)
            clipped = _clip(start, end, low, high)
            if clipped is None:
                continue
            span = clipped[1] - clipped[0]
            distance_part = moved * span / (end - start)
            active_part = active_atom_time * span / (end - start)
            row["overlapping_macro_segments"] += 1
            row["active_atom_time_us"] += active_part
            row["movement_distance_atom_um"] += distance_part
            busy += active_part
            distance += distance_part
            category_intervals[category].append(clipped)
            resource_intervals[resource].append(clipped)
    atom_time = atoms * elapsed
    idle = atom_time - busy
    if idle < -max(1e-6, atom_time * 1e-10):
        raise ValueError("CENTER_ATOM_TIME_OVERCOUNTED")
    idle = max(0.0, idle)
    if not isclose(atom_time, busy + idle, abs_tol=max(1e-6, atom_time * 1e-10)):
        raise ValueError("CENTER_ATOM_TIME_NOT_CONSERVED")
    outputs = _output_rows(case, plan, low, high)
    accepted = sum(row["accepted_in_window"] for row in outputs)
    delivered = sum(row["delivered_in_window"] for row in outputs)
    failures = [
        deepcopy(row["failure"])
        for row in case["factories"].values()
        if row.get("failure") is not None
    ]
    if case.get("failure") is not None:
        failures.append(deepcopy(case["failure"]))
    failed = any(row.get("at_us", 0) < stop for row in failures) or (
        case["status"] != "complete" and not failures
    )
    complete = duration >= stop and not failed
    bounds = plan.occupied_bounds
    area = (bounds.x_max - bounds.x_min) * (bounds.y_max - bounds.y_min)
    raw_calls = [row for row in calls if row["component_id"] == "raw_t_postselection"]
    raw_ids = {row["invocation_id"].split("/attempt[", 1)[0] for row in raw_calls}
    decisions = [
        row
        for line in case["factories"].values()
        for row in line.get("milestones", ())
        if row["kind"] == "batch_decision" and low <= row["at_us"] < high
    ]
    costs = {
        "configured_atom_time_us": atom_time,
        "busy_atom_time_us": busy,
        "idle_atom_time_us": idle,
        "home_area_time_um2_us": area * elapsed,
        "movement_distance_atom_um": distance,
        "transport_elapsed_us": interval_union_us(
            interval
            for name, intervals in resource_intervals.items()
            if name == "aod" or name.startswith("aod:")
            for interval in intervals
        ),
    }
    deliverable = [
        row["deliverable_at_us"]
        for row in outputs
        if row["deliverable_at_us"] is not None
    ]
    return {
        "schema": "nadit.center_factory_metrics/1",
        "case_id": case.get("case_id"),
        "seed": case["seed"],
        "distance": plan.blocks[0].distance,
        "factory_count": len(case["factories"]),
        "placement_fingerprint": plan.geometry_fingerprint,
        "basis": "declared macro cost segments with block-center constant-speed transport",
        "physical_validation_run": False,
        "actual_output_error": None,
        "noise_scope": "operation counts and selected atom-time exposure; no output LER estimate",
        "atom_time_basis": "declared category-partition busy integrals; uniform aggregate exposure when clipping"
        if aggregate_segments
        else "declared active atom counts times segment overlap",
        "aggregate_exposure_segments": aggregate_segments,
        "atom_time_status": "component_cost_estimate_not_native_order_timeline",
        "requested_window_us": [low, stop],
        "actual_observation_us": elapsed,
        "case_duration_us": duration,
        "requested_window_complete": complete,
        "window_status": "failed"
        if failed
        else "complete"
        if complete
        else "incomplete",
        "run_status": case["status"],
        "failures": failures,
        "startup_deliverable_latency_us": min(deliverable) if deliverable else None,
        "outputs": outputs,
        "accepted_outputs": accepted,
        "delivered_outputs": delivered,
        "accepted_outputs_total": len(outputs),
        "delivered_outputs_total": sum(
            row["delivery_lifecycle_verified"] for row in outputs
        ),
        "accepted_outputs_per_second": accepted * 1e6 / elapsed
        if complete and elapsed
        else None,
        "delivered_outputs_per_second": delivered * 1e6 / elapsed
        if complete and elapsed
        else None,
        "raw_attempts": component_counts["raw_t_postselection"],
        "raw_retry_attempts": sum(
            low <= row["start_us"] < high
            and "/attempt[" in row["invocation_id"]
            and "/attempt[0]/" not in row["invocation_id"]
            for row in raw_calls
        ),
        "raw_rejections": sum(
            row["values"].get("accepted") is False
            and low <= row["released_at_us"] < high
            for row in case.get("events", ())
            if row["occurrence"]["invocation_id"] in raw_ids
        ),
        "final_rejections": sum(row["accepted"] is False for row in decisions),
        "s_calls": component_counts["logical_s"]
        + component_counts["assumed_transversal_s"],
        "standalone_ec_calls": component_counts["se_round"],
        "configured_atoms": atoms,
        "home_footprint_area_um2": area,
        **costs,
        "area_time_basis": "fixed home bounding rectangle including gaps; readout transit excluded",
        "actual_occupied_bbox_area_time_um2_us": None,
        "movement_distance_basis": "block-center constant-speed estimate; not native atom paths",
        "component_counts": dict(component_counts),
        "primitive_counts": dict(primitives),
        "exposure_by_category": {
            name: {**row, "primitive_counts": dict(row["primitive_counts"])}
            for name, row in exposure.items()
        },
        "resource_busy_union_us": {
            name: interval_union_us(rows) for name, rows in resource_intervals.items()
        },
        "category_busy_union_us": {
            name: interval_union_us(rows) for name, rows in category_intervals.items()
        },
        "per_accepted_output": {
            name: value / accepted if accepted else None
            for name, value in costs.items()
        },
        "per_delivered_output": {
            name: value / delivered if delivered else None
            for name, value in costs.items()
        },
        "count_boundary_convention": "start <= event_time < end; interval overlap clipped",
    }


def summarize_center_samples(samples: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Summarize independent seeds; exclude incomplete windows, retain zeros.

    Student-t intervals describe production-seed variation only. Calibration
    uncertainty and block-center model discrepancy are not included.
    """
    from .campaign_report import _mean_ci

    if not samples:
        raise ValueError("EMPTY_CENTER_METRIC_SAMPLE")
    first = samples[0]
    seeds = [row["seed"] for row in samples]
    if any(type(seed) is not int for seed in seeds) or len(set(seeds)) != len(seeds):
        raise ValueError("DUPLICATE_OR_INVALID_CENTER_METRIC_SEED")
    if any(
        any(
            row[key] != first[key]
            for key in (
                "distance",
                "factory_count",
                "placement_fingerprint",
                "requested_window_us",
            )
        )
        for row in samples
    ):
        raise ValueError("MIXED_CENTER_METRIC_EXPERIMENTS")
    valid = [row for row in samples if row["requested_window_complete"]]
    fields = (
        "startup_deliverable_latency_us",
        "accepted_outputs_per_second",
        "delivered_outputs_per_second",
        "raw_attempts",
        "raw_rejections",
        "s_calls",
        "standalone_ec_calls",
    )
    statistics = {
        name: _mean_ci(
            [_number(row[name]) for row in valid if row[name] is not None], len(valid)
        )
        for name in fields
    }
    cost_names = tuple(first["per_accepted_output"])
    for name in cost_names:
        statistics[name + "_per_accepted_output"] = {
            **_mean_ci(
                [
                    _number(row["per_accepted_output"][name])
                    for row in valid
                    if row["per_accepted_output"][name] is not None
                ],
                len(valid),
            ),
            "conditioning": "complete windows with positive accepted output; descriptive seed-ratio mean, not pooled cost",
        }
    complete_outputs = sum(row["accepted_outputs"] for row in valid)
    complete_time = sum(_number(row["actual_observation_us"]) for row in valid)
    complete_costs = {
        name: sum(_number(row[name]) for row in valid) for name in cost_names
    }
    all_outputs = sum(row["accepted_outputs"] for row in samples)
    all_costs = {
        name: sum(_number(row[name]) for row in samples) for name in cost_names
    }
    return {
        "schema": "nadit.center_factory_sample_statistics/1",
        "distance": first["distance"],
        "factory_count": first["factory_count"],
        "seed_count": len(samples),
        "complete_seed_count": len(valid),
        "excluded_seeds": [
            {"seed": row["seed"], "window_status": row["window_status"]}
            for row in samples
            if not row["requested_window_complete"]
        ],
        "statistics": statistics,
        "pooled_cost_per_accepted_output": {
            name: value / complete_outputs if complete_outputs else None
            for name, value in complete_costs.items()
        },
        "pooled_cost_basis": "all complete observation windows, including zero-output seeds, divided by their total accepted outputs",
        "pooled_accepted_outputs_per_second": complete_outputs * 1e6 / complete_time
        if complete_time
        else None,
        "complete_window_totals": {
            "accepted_outputs": complete_outputs,
            "actual_observation_us": complete_time,
            "costs": complete_costs,
        },
        "all_seed_incurred_costs": {
            "basis": "observed window intersections including failed and incomplete seeds; diagnostic, not steady-state throughput",
            "accepted_outputs": all_outputs,
            "delivered_outputs": sum(row["delivered_outputs"] for row in samples),
            "actual_observation_us": sum(
                _number(row["actual_observation_us"]) for row in samples
            ),
            "costs": all_costs,
            "per_accepted_output": {
                name: value / all_outputs if all_outputs else None
                for name, value in all_costs.items()
            },
        },
        "interval_basis": "two-sided Student-t 95%; independent seeds conditional on complete windows; excludes calibration uncertainty and model discrepancy",
    }
