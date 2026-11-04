"""Distinct work, resource-occupancy and seed-level experimental statistics."""

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from math import isfinite, log, sqrt
from statistics import fmean, stdev
from typing import Any


def _time(value: Any) -> float:
    if type(value) not in (int, float) or not isfinite(value) or value < 0:
        raise ValueError("INVALID_ESTIMATE_TIME")
    return float(value)


def _interval(record: Mapping[str, Any], horizon: float) -> tuple[float, float]:
    start, end = _time(record["start_us"]), _time(record["end_us"])
    if start > end or end > horizon + 1e-7:
        raise ValueError("ESTIMATE_INTERVAL_OUTSIDE_HORIZON")
    return min(start, horizon), min(end, horizon)


def interval_union_us(intervals: Iterable[tuple[float, float]]) -> float:
    """Return occupied time, counting concurrent or touching intervals once."""
    total, previous = 0.0, 0.0
    for start, end in sorted(intervals):
        if _time(start) > _time(end):
            raise ValueError("INVALID_ESTIMATE_INTERVAL")
        total += max(0.0, end - max(start, previous))
        previous = max(previous, end)
    return total


def summarize_costs(
    calls: Iterable[Mapping[str, Any]],
    waits: Iterable[Mapping[str, Any]],
    makespan_us: float,
) -> dict[str, Any]:
    """Separate summed member work from shared busy intervals and total duration.

    Cost segments contain absolute start/end times, category and resource names.
    Work is the sum of each member's category union, not atom-microseconds.
    Categories/resources may overlap, so their sums are not the global makespan.
    """
    horizon = _time(makespan_us)
    work: dict[str, float] = defaultdict(float)
    resources: dict[str, list[tuple[float, float]]] = defaultdict(list)
    categories: dict[str, list[tuple[float, float]]] = defaultdict(list)
    all_intervals = []
    counts: Counter[str] = Counter()
    primitives: Counter[str] = Counter()
    for call in calls:
        counts[str(call["component_id"])] += 1
        member: dict[str, list[tuple[float, float]]] = defaultdict(list)
        for segment in call.get("cost_segments", ()):
            interval = _interval(segment, horizon)
            category, resource = segment["category"], segment["resource"]
            if (
                not isinstance(category, str)
                or not category
                or not isinstance(resource, str)
                or not resource
            ):
                raise ValueError("INVALID_ESTIMATE_RESOURCE_CATEGORY")
            member[category].append(interval)
            resources[resource].append(interval)
            categories[category].append(interval)
            all_intervals.append(interval)
        for category, intervals in member.items():
            work[category] += interval_union_us(intervals)
        for name, count in call.get("primitive_counts", {}).items():
            if type(count) is not int or count < 0:
                raise ValueError("INVALID_PRIMITIVE_COUNT")
            primitives[str(name)] += count
    busy = interval_union_us(all_intervals)
    return {
        "schema": "nadit.profiled_cost_accounting/1",
        "time_unit": "us",
        "work_basis": "sum_of_member_category_union_times_not_atom_time",
        "work_by_category_us": dict(sorted(work.items())),
        "resource_busy_us": {
            name: interval_union_us(intervals)
            for name, intervals in sorted(resources.items())
        },
        "category_busy_us": {
            name: interval_union_us(intervals)
            for name, intervals in sorted(categories.items())
        },
        "global_busy_union_us": busy,
        "explicit_global_wait_us": interval_union_us(
            _interval(wait, horizon) for wait in waits
        ),
        "unoccupied_timeline_us": max(0.0, horizon - busy),
        "makespan_us": horizon,
        "component_counts": dict(sorted(counts.items())),
        "primitive_counts": dict(sorted(primitives.items())),
        "category_sum_is_elapsed": False,
        "resource_sum_is_elapsed": False,
    }


def _quantile(values: list[float], fraction: float) -> float:
    values = sorted(values)
    index = (len(values) - 1) * fraction
    left = int(index)
    return values[left] + (values[min(left + 1, len(values) - 1)] - values[left]) * (
        index - left
    )


def summarize_samples(samples: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Use independent seeded trajectories, never individual concurrent lines, as samples."""
    records = tuple(samples)
    if not records:
        raise ValueError("EMPTY_SCALING_SAMPLE")
    seeds = [record["seed"] for record in records]
    if any(type(seed) is not int for seed in seeds) or len(set(seeds)) != len(seeds):
        raise ValueError("DUPLICATE_OR_INVALID_SCALING_SEED")
    counts = {record["factory_count"] for record in records}
    if len(counts) != 1 or any(type(count) is not int or count < 1 for count in counts):
        raise ValueError("MIXED_OR_INVALID_SCALING_FACTORY_COUNT")
    factory_count = records[0]["factory_count"]
    outputs = [record["outputs"] for record in records]
    if any(
        type(count) is not int or not 0 <= count <= factory_count for count in outputs
    ):
        raise ValueError("INVALID_SCALING_OUTPUT_COUNT")
    times = [_time(record["makespan_us"]) for record in records]
    walls = [_time(record["wall_seconds"]) for record in records]
    n = len(records)
    successes = sum(count > 0 for count in outputs)
    observed, z = successes / n, 1.959963984540054
    denominator = 1 + z * z / n
    center = (observed + z * z / (2 * n)) / denominator
    radius = z * sqrt(observed * (1 - observed) / n + z * z / (4 * n * n)) / denominator
    fractions = [count / factory_count for count in outputs]
    mean_fraction = fmean(fractions)
    hoeffding = sqrt(log(40) / (2 * n))
    return {
        "factory_count": factory_count,
        "independent_seed_runs": n,
        "observed_outputs": sum(outputs),
        "mean_makespan_us": fmean(times),
        "p50_makespan_us": _quantile(times, 0.5),
        "p95_makespan_us": _quantile(times, 0.95),
        "makespan_standard_error_us": stdev(times) / sqrt(n) if n > 1 else None,
        "mean_output_fraction": mean_fraction,
        "output_fraction_hoeffding_95": [
            max(0, mean_fraction - hoeffding),
            min(1, mean_fraction + hoeffding),
        ],
        "probability_unit": "seed_run_with_at_least_one_output",
        "any_output_wilson_95": [
            0.0 if successes == 0 else max(0, center - radius),
            1.0 if successes == n else min(1, center + radius),
        ],
        "line_independence_assumed": False,
        "output_yield_precision": "no_outputs_observed"
        if not sum(outputs)
        else "finite_seed_sample",
        "modeled_outputs_per_second": sum(outputs) * 1e6 / sum(times)
        if sum(times)
        else None,
        "total_compile_wall_seconds": sum(walls),
        "mean_compile_wall_seconds": fmean(walls),
    }
