"""Resolve a fixed observation window from audited pilot costs and a preset rule."""

from collections.abc import Mapping
from collections.abc import Set as AbstractSet
from copy import deepcopy
from math import floor, isfinite
from typing import Any

from nadit_physical_compiler.provenance import canonical_hash


def _positive(value: Any, name: str, *, zero: bool = False) -> float:
    if (
        type(value) not in (int, float)
        or not isfinite(value)
        or value < 0
        or (value == 0 and not zero)
    ):
        raise ValueError(f"INVALID_PILOT_WINDOW_INPUT: {name}")
    return float(value)


def resolve_observation_policy(
    pilot: Mapping[str, Any],
    rule: Mapping[str, Any],
    *,
    available_worker_seconds: float,
    pilot_worker_seconds: float,
    output_factory_ids: AbstractSet[str] | None = None,
    warm_replay_worker_seconds: float | None = None,
) -> dict[str, Any]:
    """Choose one window per layout before any formal production seed executes.

    The cost estimate is the sum of unique pilot task work, including cold
    calibration, cache loading, replay and verification, divided by pilot cycles.
    It is a conservative allocation heuristic, not a runtime guarantee: the task
    runner still enforces actual limits. No rule is adapted to formal outcomes.
    Incomplete pilots or budgets below the declared minimum fail explicitly.

    Optional output_factory_ids selects terminal-output factories for cycle
    timing, for example L2. Every factory must still have completed without a
    failure; upstream handoff/retention outputs need not be terminal deliveries.
    pilot_worker_seconds always covers the whole run, including every level.
    The complete pilot remains hashed. Empty, unknown or non-set selectors raise
    ValueError. Omitting the selector retains the original all-factory behavior.

    An explicit warm replay measurement changes only the extrapolation slope.
    pilot_worker_seconds still records all preparation work already debited by
    the driver. The driver verifies replay evidence and reserves future misses;
    this calculator never infers a warm cost from partial software stage timers.
    """
    required = {
        "pilot_cycles",
        "warmup_cycles",
        "target_observation_cycles",
        "minimum_observation_cycles",
        "max_total_simulated_us",
        "software_safety_factor",
    }
    if set(rule) != required:
        raise ValueError("INCOMPLETE_OBSERVATION_WINDOW_RULE")
    for name in (
        "pilot_cycles",
        "warmup_cycles",
        "target_observation_cycles",
        "minimum_observation_cycles",
    ):
        minimum = 0 if name == "warmup_cycles" else 2 if name == "pilot_cycles" else 1
        if type(rule[name]) is not int or rule[name] < minimum:
            raise ValueError(f"INVALID_OBSERVATION_WINDOW_RULE: {name}")
    if rule["minimum_observation_cycles"] > rule["target_observation_cycles"]:
        raise ValueError("INVALID_OBSERVATION_WINDOW_RULE: minimum exceeds target")
    maximum_us = _positive(rule["max_total_simulated_us"], "max_total_simulated_us")
    safety = _positive(rule["software_safety_factor"], "software_safety_factor")
    if safety < 1:
        raise ValueError("INVALID_OBSERVATION_WINDOW_RULE: safety factor below one")
    budget = _positive(available_worker_seconds, "available_worker_seconds")
    work = _positive(pilot_worker_seconds, "pilot_worker_seconds")
    replay_work = (
        None
        if warm_replay_worker_seconds is None
        else _positive(warm_replay_worker_seconds, "warm_replay_worker_seconds")
    )
    case = pilot["case"]
    if case["status"] != "complete" or not case["factories"]:
        raise ValueError("PILOT_INCOMPLETE")
    factories = case["factories"]
    selected = factories
    if output_factory_ids is not None:
        if (
            not isinstance(output_factory_ids, AbstractSet)
            or not output_factory_ids
            or any(
                not isinstance(identity, str) or identity not in factories
                for identity in output_factory_ids
            )
        ):
            raise ValueError("INVALID_PILOT_OUTPUT_FACTORY_FILTER")
        if case.get("failure") is not None or any(
            line["status"] != "complete" or line.get("failure") is not None
            for line in factories.values()
        ):
            raise ValueError("PILOT_INCOMPLETE")
        selected = {
            identity: factories[identity] for identity in sorted(output_factory_ids)
        }
    rows = []
    identities: set[str] = set()
    for line in selected.values():
        outputs = line.get("outputs", [])
        if line["status"] != "complete" or len(outputs) != rule["pilot_cycles"]:
            raise ValueError("PILOT_REQUIRES_CONTINUOUS_DELIVERED_CYCLES")
        for index, output in enumerate(outputs):
            if output["cycle"] != index or output["token_id"] in identities:
                raise ValueError("PILOT_OUTPUT_IDENTITY_MISMATCH")
            identities.add(output["token_id"])
            times = [
                _positive(output[key], key, zero=True)
                for key in (
                    "ready_at_us",
                    "deliverable_at_us",
                    "consumed_at_us",
                    "released_at_us",
                )
            ]
            if times != sorted(times) or not output.get("delivery"):
                raise ValueError("PILOT_DELIVERY_INCOMPLETE")
            if index and times[0] < outputs[index - 1]["released_at_us"]:
                raise ValueError("PILOT_CYCLES_OVERLAP")
        rows.append(outputs)
    ends = [
        max(outputs[i]["released_at_us"] for outputs in rows)
        for i in range(rule["pilot_cycles"])
    ]
    spans = [end - start for start, end in zip([0.0, *ends[:-1]], ends, strict=True)]
    if min(spans) <= 0:
        raise ValueError("INVALID_PILOT_CYCLE_SPAN")
    cycle_us = max(spans)
    work_per_cycle = (work if replay_work is None else replay_work) / rule[
        "pilot_cycles"
    ]
    software_cycles = floor(budget / (safety * work_per_cycle))
    time_cycles = floor(maximum_us / cycle_us)
    total_cycles = min(
        rule["warmup_cycles"] + rule["target_observation_cycles"],
        software_cycles,
        time_cycles,
    )
    observation_cycles = total_cycles - rule["warmup_cycles"]
    if observation_cycles < rule["minimum_observation_cycles"]:
        raise ValueError("PILOT_BUDGET_CANNOT_SUPPORT_MINIMUM_OBSERVATION_WINDOW")
    return {
        "schema": "nadit.msd.observation_policy/1",
        **(
            {"output_factory_ids": sorted(output_factory_ids)}
            if output_factory_ids is not None
            else {}
        ),
        "rule": deepcopy(dict(rule)),
        "pilot_sha256": canonical_hash(pilot),
        "pilot_worker_seconds": work,
        "worker_seconds_basis": "unique pilot tasks, including calibration and replay"
        if replay_work is None
        else "all preparation work debited once; slope from verified successful warm replay process and artifact validation",
        **(
            {}
            if replay_work is None
            else {
                "software_cost_model": {
                    "mode": "cached_replay",
                    "warm_replay_worker_seconds": replay_work,
                    "warm_replay_cycles": rule["pilot_cycles"],
                    "work_per_cycle_seconds": work_per_cycle,
                }
            }
        ),
        "available_worker_seconds": budget,
        "cycle_scale_us": cycle_us,
        "warmup_us": rule["warmup_cycles"] * cycle_us,
        "stop_us": total_cycles * cycle_us,
        "observation_cycles": observation_cycles,
        "software_budget_cycles": software_cycles,
        "physical_time_budget_cycles": time_cycles,
        "boundary_convention": "[warmup_us, stop_us)",
        "rule_frozen_before_production": True,
    }
