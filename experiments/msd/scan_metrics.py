"""Shot statistics and numeric resource diagnostics; no atom expansion."""

import json
import math
import statistics
from collections import Counter
from pathlib import Path
from typing import Any


class MotionAccounting:
    """Use saved atom-distance totals plus the admitted common readout lift.

    This preserves reference motion patterns, adds uniform vertical displacement
    to readout members, and uses d-squared moving data for CNOT. It estimates
    distance under the object model; it is not an atomic trajectory certificate.
    """

    def __init__(self, catalog: Any) -> None:
        document = json.loads(
            Path(__file__)
            .with_name("object-motion-reference.json")
            .read_text(encoding="utf-8")
        )
        reference = document["distances"][str(catalog.distance)]
        if reference["catalog_sha256"] != catalog.fingerprint:
            raise ValueError("MOTION_REFERENCE_CATALOG_MISMATCH")
        self.base = reference["reference_atom_distance_um"]
        self.distance = catalog.distance
        self.speed = catalog.document["move_us_per_um"]
        self.phases = {}
        for name, entry in catalog.entries.items():
            rows = catalog.document["entries"][name]["phases"]
            for i, (phase, row) in enumerate(zip(entry.stages, rows, strict=True)):
                atoms = 0
                if row[4] == "readout":
                    atoms = (rows[i - 1][3] if i else 0) or (
                        rows[i + 1][3] if i + 1 < len(rows) else 0
                    )
                    if not atoms:
                        raise ValueError("MISSING_READOUT_MOVEMENT_MULTIPLICITY")
                self.phases[name, phase.name] = (row[0], row[1], row[4], atoms)

    def motion(self, case: dict[str, Any]) -> dict[str, float]:
        """Separate atom-summed path estimates from shared command motion."""
        calls = {c["invocation_id"]: c for c in case["calls"]}
        total = sum(self.base[c["component_id"]] for c in calls.values())
        result: Counter[str] = Counter()
        for wave in case["execution"]["waves"]:
            for stage in wave["stage_schedule"]:
                component = calls[stage["members"][0]]["component_id"]
                reference, kind, motion, atoms = self.phases[component, stage["phase"]]
                duration = stage["end_us"] - stage["start_us"]
                if kind in ("load", "store", "movement"):
                    label = "move" if kind == "movement" else kind
                    result[label + "_command_us"] += duration
                    result[label + "_command_count"] += 1
                if motion == "readout":
                    delta = duration - reference
                    if delta < -1e-7:
                        raise ValueError("READOUT_MOTION_BELOW_REFERENCE")
                    total += len(stage["members"]) * atoms * max(0, delta) / self.speed
                elif motion == "cnot":
                    total += (
                        len(stage["members"]) * self.distance**2 * duration / self.speed
                    )
        result["aod_move_command_distance_um"] = result["move_command_us"] / self.speed
        result["atom_distance_estimate_um"] = total
        return dict(result)


def metrics(run: dict[str, Any], motion: MotionAccounting) -> dict[str, Any]:
    """Extract scalar diagnostics with explicit time/occupancy bases."""
    s, case = run["summary"], run["case"]
    result = {
        "outputs": s["accepted_outputs"],
        "duration_us": s["makespan_us"],
        "startup_us": s["startup_latency_us"],
        "atoms": s["allocated_atoms"],
        "storage_area_um2": s["storage_footprint_um2"],
        "storage_width_um": s["storage_width_um"],
        "storage_depth_um": s["storage_depth_um"],
        "full_physical_area_um2": None,
        "atom_time_us": s["allocated_atoms"] * s["makespan_us"],
        "storage_area_time_um2_us": s["storage_footprint_um2"] * s["makespan_us"],
        "shot_rate_per_second": s["finite_batch_rate_per_second"],
        "raw_rejections": s["raw_rejections"],
        "final_rejections": s["factory_rejections"],
        "raw_attempts": s["raw_attempts"],
        "aod_busy_us": s["accounting"]["resource_busy_us"].get("aod:transport", 0),
        **motion.motion(case),
    }
    timing = s["timing_breakdown"]
    for key in ("readout_transport", "gate_transport"):
        result[key + "_command_us"] = timing["command_microseconds"].get(key, 0)
    result["protocol_wait_factory_us"] = sum(
        timing["protocol_barrier_wait_us_by_factory"].values()
    )
    result["dispatch_wait_factory_us"] = sum(
        v.get("waiting_resources", 0)
        for v in timing["factory_frontier_wait_us"].values()
    )
    result["wave_tail_wait_member_us"] = timing["member_microseconds"].get(
        "wave_tail_synchronization", 0
    )
    result["aod_phase_wait_member_us"] = timing["member_microseconds"].get(
        "shared_aod_wait", 0
    )
    occupancy: dict[str, list[tuple[float, float]]] = {
        p["block_id"]: [] for p in run["layout"]["patches"]
    }
    receipts = {c["invocation_id"]: c for c in case["execution"]["calls"]}
    for call in case["calls"]:
        receipt = receipts[call["invocation_id"]]
        for role in call["participant_roles"]:
            occupancy[call["factory_id"] + "/" + role].append(
                (receipt["start_us"], receipt["action_end_us"])
            )
    busy = 0.0
    for intervals in occupancy.values():
        end = 0.0
        for start, stop in sorted(intervals):
            busy += max(0, stop - max(start, end))
            end = max(end, stop)
    result["unassigned_block_us"] = len(occupancy) * s["makespan_us"] - busy
    result["unassigned_block_atom_us"] = result["unassigned_block_us"] * (
        2 * s["distance"] ** 2 - 1
    )
    primitives = s["accounting"]["primitive_counts"]
    result["single_qubit_operation_count"] = sum(
        primitives.get(k, 0) for k in ("rx", "ry", "rz")
    )
    for name in ("cz", "measure", "reset"):
        result[name + "_operation_count"] = primitives.get(name, 0)
    for category, value in s["accounting"]["work_by_category_us"].items():
        result["operation_" + category + "_member_us"] = value
    return result


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Report shot variance and renewal ratios without dropping zero-output cost.

    Pooled production and cost use ratios of sums, not means of inverses. Rate
    estimator variance uses the delta method; startup renewal moments assume
    independent restart cycles. Conditional startup statistics remain separate.
    """
    if not rows or any(r["duration_us"] <= 0 for r in rows):
        raise ValueError("POSITIVE_DURATION_SHOTS_REQUIRED")
    statistics_by_metric = {}
    for name in sorted(set().union(*(r.keys() for r in rows))):
        values = [r[name] for r in rows if r.get(name) is not None]
        statistics_by_metric[name] = {
            "n": len(values),
            "mean": statistics.mean(values) if values else None,
            "variance": statistics.variance(values) if len(values) > 1 else None,
            "min": min(values) if values else None,
            "max": max(values) if values else None,
        }
    outputs = sum(r["outputs"] for r in rows)
    duration = sum(r["duration_us"] for r in rows)
    rate = outputs * 1e6 / duration
    residual = [r["outputs"] - rate * r["duration_us"] / 1e6 for r in rows]
    rate_variance = (
        statistics.variance(residual) / (len(rows) * (duration / len(rows) / 1e6) ** 2)
        if len(rows) > 1
        else None
    )
    accepted = [r for r in rows if r["startup_us"] is not None]
    empty = [r for r in rows if r["startup_us"] is None]
    first = (
        (sum(r["startup_us"] for r in accepted) + sum(r["duration_us"] for r in empty))
        / len(accepted)
        if accepted
        else None
    )
    second = (
        (
            sum(r["startup_us"] ** 2 for r in accepted)
            + sum(r["duration_us"] ** 2 for r in empty)
            + 2 * sum(r["duration_us"] for r in empty) * first
        )
        / len(accepted)
        if first is not None
        else None
    )
    se = math.sqrt(rate_variance) if rate_variance is not None else None
    return {
        "shots": len(rows),
        "total_outputs": outputs,
        "metrics": statistics_by_metric,
        "pooled_rate_per_second": rate,
        "rate_estimator_variance_delta": rate_variance,
        "rate_ci95_delta": [max(0, rate - 1.96 * se), rate + 1.96 * se]
        if se is not None
        else None,
        "atom_us_per_output": sum(r["atom_time_us"] for r in rows) / outputs
        if outputs
        else None,
        "storage_area_us_per_output": sum(r["storage_area_time_um2_us"] for r in rows)
        / outputs
        if outputs
        else None,
        "no_output_fraction": len(empty) / len(rows),
        "renewal_startup_mean_us": first,
        "renewal_startup_variance_us2": max(0, second - first * first)
        if second is not None and first is not None
        else None,
        "interpretation": "independent shot-restart renewal estimate; asynchronous continuous-pipeline equivalence is not established",
    }
