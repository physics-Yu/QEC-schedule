"""Export verified single-level fast MSD ledgers, costs and a scientific figure.

Only completed, hash-checked saved records are read. No atom actions are decoded
or replayed, and no trajectory is launched. Incomplete or failed windows remain
visible; they do not become low-throughput steady-state samples.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections.abc import Mapping, Sequence
from hashlib import file_digest
from math import isclose, isfinite
from pathlib import Path
from typing import Any

from experiments.msd.center_metrics import summarize_center_samples
from experiments.msd.single_fast import _verified_completion
from modules.codes.rotated_surface.center_costs import reference_digest

_EXPECTED_DISTANCES = (3, 5, 7)
_EXPECTED_COUNTS = (1, 2, 4, 8)
_EXPECTED_SEEDS = tuple(range(16))
_SHARES = ("gate", "readout", "transport", "reset", "other_active", "idle")
_BUDGET_ABORT_CODES = frozenset(
    {
        "input_supply_exhausted",
        "distillation_rejected",
        "expansion_budget_exhausted",
        "production_cycle_budget_exhausted",
    }
)


def observed_window_diagnostic(metrics: Mapping[str, Any]) -> dict[str, Any]:
    """Describe full observed horizons independently of per-line budget success.

    A failed line can stop while peers continue through the fixed window. Its
    saved outputs and incurred costs remain observed evidence. Truly truncated
    horizons are not extrapolated to the requested window.
    """
    start, stop = metrics["requested_window_us"]
    duration, observed = metrics["case_duration_us"], metrics["actual_observation_us"]
    if (
        any(
            type(value) not in (int, float) or not isfinite(value) or value < 0
            for value in (start, stop, duration, observed)
        )
        or stop <= start
    ):
        raise ValueError("INVALID_OBSERVED_WINDOW_INTERVAL")
    coverage_complete = duration >= stop
    if coverage_complete and not isclose(
        observed, stop - start, rel_tol=1e-10, abs_tol=1e-7
    ):
        raise ValueError("OBSERVED_WINDOW_HORIZON_MISMATCH")
    failures = [row for row in metrics["failures"] if row.get("at_us", 0) < stop]
    budget = [row for row in failures if row.get("code") in _BUDGET_ABORT_CODES]
    width = stop - start
    return {
        "observation_coverage_complete": coverage_complete,
        "no_budget_abort": not budget,
        "budget_abort_scope": "line failure before requested stop; missing failure time counted conservatively",
        "pre_stop_failure_codes": sorted(
            {str(row.get("code", "unknown")) for row in failures}
        ),
        "pre_stop_budget_abort_codes": sorted({str(row["code"]) for row in budget}),
        "planned_primary_eligible": metrics["requested_window_complete"],
        "observed_accepted_outputs_per_second": metrics["accepted_outputs"]
        * 1e6
        / width
        if coverage_complete
        else None,
        "observed_delivered_outputs_per_second": metrics["delivered_outputs"]
        * 1e6
        / width
        if coverage_complete
        else None,
        "rate_basis": "descriptive fixed-window outputs divided by full observed window; includes line budget aborts; no truncated-window extrapolation or asymptotic steady-state claim",
    }


def summarize_observed_windows(samples: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Report secondary pooled costs/rates for every fully observed fixed window."""
    from experiments.msd.campaign_report import _mean_ci

    diagnostics = [observed_window_diagnostic(row) for row in samples]
    covered = [
        (row, info)
        for row, info in zip(samples, diagnostics, strict=True)
        if info["observation_coverage_complete"]
    ]
    costs = tuple(samples[0]["per_accepted_output"]) if samples else ()
    total_outputs = sum(row["accepted_outputs"] for row, _ in covered)
    total_time = sum(
        row["requested_window_us"][1] - row["requested_window_us"][0]
        for row, _ in covered
    )
    totals = {name: sum(row[name] for row, _ in covered) for name in costs}
    return {
        "schema": "nadit.single_fast_observed_window_diagnostic/1",
        "covered_seed_count": len(covered),
        "budget_abort_seed_count": sum(
            not info["no_budget_abort"] for _, info in covered
        ),
        "primary_excluded_but_covered_seeds": [
            row["seed"] for row, _ in covered if not row["requested_window_complete"]
        ],
        "uncovered_seeds": [
            row["seed"]
            for row, info in zip(samples, diagnostics, strict=True)
            if not info["observation_coverage_complete"]
        ],
        "accepted_outputs": total_outputs,
        "observed_window_us": total_time,
        "rate_statistics": _mean_ci(
            [info["observed_accepted_outputs_per_second"] for _, info in covered],
            len(covered),
        ),
        "pooled_accepted_outputs_per_second": total_outputs * 1e6 / total_time
        if total_time
        else None,
        "pooled_cost_per_accepted_output": {
            name: value / total_outputs if total_outputs else None
            for name, value in totals.items()
        },
        "incurred_costs": totals,
        "scope": "secondary descriptive observed-window statistic including pre-stop line budget aborts; zero-output covered seeds contribute costs; truly truncated windows excluded; primary planned conditional statistics unchanged",
        "steady_state_claim": False,
    }


def half_window_diagnostic(metrics: Mapping[str, Any]) -> dict[str, Any]:
    """Compare equal halves using accepted-resource ready times, retaining zeros.

    Midpoint events belong only to the second half, and stop events are excluded.
    An incomplete or failed observation window is explicitly ineligible.
    """
    if not metrics["requested_window_complete"]:
        return {
            "eligible": False,
            "reason": metrics["window_status"],
            "first_half_accepted_outputs": None,
            "second_half_accepted_outputs": None,
            "first_half_rate_per_second": None,
            "second_half_rate_per_second": None,
            "paired_rate_difference_per_second": None,
        }
    start, stop = metrics["requested_window_us"]
    if (
        any(
            type(value) not in (int, float) or not isfinite(value)
            for value in (start, stop)
        )
        or start < 0
        or stop <= start
    ):
        raise ValueError("INVALID_HALF_WINDOW_INTERVAL")
    midpoint = start + (stop - start) / 2
    first = second = 0
    seen: set[str] = set()
    for output in metrics["outputs"]:
        identity, ready = output["token_id"], output["ready_at_us"]
        if (
            identity in seen
            or type(ready) not in (float, int)
            or not isfinite(ready)
            or ready < 0
        ):
            raise ValueError("INVALID_HALF_WINDOW_OUTPUT_IDENTITY_OR_TIME")
        seen.add(identity)
        counted = start <= ready < stop
        if "accepted_in_window" in output and output["accepted_in_window"] != counted:
            raise ValueError("HALF_WINDOW_OUTPUT_MEMBERSHIP_MISMATCH")
        first += int(start <= ready < midpoint)
        second += int(midpoint <= ready < stop)
    if first + second != metrics["accepted_outputs"]:
        raise ValueError("HALF_WINDOW_ACCEPTED_COUNT_MISMATCH")
    scale = 1e6 / ((stop - start) / 2)
    return {
        "eligible": True,
        "reason": "complete_observation_window",
        "first_half_us": [start, midpoint],
        "second_half_us": [midpoint, stop],
        "first_half_accepted_outputs": first,
        "second_half_accepted_outputs": second,
        "first_half_rate_per_second": first * scale,
        "second_half_rate_per_second": second * scale,
        "paired_rate_difference_per_second": (second - first) * scale,
        "event_time_basis": "accepted resource ready_at_us; half-open intervals",
    }


def summarize_half_windows(samples: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Use seeds as paired samples; expose temporal variation without a verdict."""
    from experiments.msd.campaign_report import _mean_ci

    seeds = [row["seed"] for row in samples]
    if len(set(seeds)) != len(seeds):
        raise ValueError("DUPLICATE_HALF_WINDOW_SEED")
    rows = [half_window_diagnostic(metrics) for metrics in samples]
    eligible = [row for row in rows if row["eligible"]]
    fields = (
        "first_half_rate_per_second",
        "second_half_rate_per_second",
        "paired_rate_difference_per_second",
    )
    return {
        "schema": "nadit.single_fast_half_window_diagnostic/1",
        "eligible_seed_count": len(eligible),
        "ineligible_seed_count": len(rows) - len(eligible),
        "statistics": {
            name: _mean_ci([row[name] for row in eligible], len(eligible))
            for name in fields
        },
        "difference_definition": "second-half accepted output rate minus first-half rate within the same seed",
        "sampling_unit": "independent production seed, not individual factory lines or output states",
        "interpretation": "finite-window temporal diagnostic, not an asymptotic steady-state proof; a difference interval containing zero does not establish stationarity",
        "binary_stationarity_verdict": None,
    }


def _read(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise TypeError(f"EXPECTED_REPORT_JSON_OBJECT: {path}")
    return document


def _hash(path: Path) -> str:
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def _guard_passed(record: Mapping[str, Any]) -> bool:
    guard = record["guard"]
    return (
        guard.get("passed") is True
        and guard.get("completed") is True
        and guard.get("intercepted_call_count") == 0
    )


def _shares(metrics: Mapping[str, Any]) -> dict[str, float]:
    exposure = metrics["exposure_by_category"]

    def selected(*names: str) -> float:
        return sum(
            float(exposure.get(name, {}).get("active_atom_time_us", 0))
            for name in names
        )

    result = {
        "gate": selected("gate"),
        "readout": selected("readout", "measurement"),
        "transport": selected("movement", "transfer"),
        "reset": selected("reset"),
        "idle": float(metrics["idle_atom_time_us"]),
    }
    result["other_active"] = float(metrics["busy_atom_time_us"]) - sum(
        result[name] for name in ("gate", "readout", "transport", "reset")
    )
    total = float(metrics["configured_atom_time_us"])
    if min(result.values()) < -max(1e-6, total * 1e-10) or abs(
        sum(result.values()) - total
    ) > max(1e-6, total * 1e-10):
        raise ValueError("REPORT_ATOM_TIME_PARTITION_MISMATCH")
    return {name: max(0.0, result[name]) for name in _SHARES}


def _seed_row(record: Mapping[str, Any], completion: Path) -> dict[str, Any]:
    metrics, counts = record["metrics"], record["ledger_counts"]
    halves = half_window_diagnostic(metrics)
    observed = observed_window_diagnostic(metrics)
    decisions = [
        row for line in record["lines"].values() for row in line["batch_decisions"]
    ]
    return {
        "distance": record["distance"],
        "factory_count": record["factory_count"],
        "seed": record["seed"],
        "status": record["status"],
        "window_status": metrics["window_status"],
        "guard_passed": _guard_passed(record),
        "raw_attempts_full_case": counts["raw_attempts"],
        "raw_rejections_full_case": counts["raw_rejections"],
        "factory_attempts_full_case": len(decisions),
        "factory_rejections_full_case": sum(not row["accepted"] for row in decisions),
        "s_calls_full_case": counts["s_calls"],
        "se_calls_full_case": counts["se_calls"],
        "accepted_outputs_full_case": counts["accepted_outputs"],
        "delivered_outputs_full_case": counts["delivered_outputs"],
        "raw_attempts_in_window": metrics["raw_attempts"],
        "raw_rejections_in_window": metrics["raw_rejections"],
        "accepted_outputs_in_window": metrics["accepted_outputs"],
        "delivered_outputs_in_window": metrics["delivered_outputs"],
        "startup_latency_us": metrics["startup_deliverable_latency_us"],
        "accepted_outputs_per_second": metrics["accepted_outputs_per_second"],
        **{
            name: observed[name]
            for name in (
                "observation_coverage_complete",
                "no_budget_abort",
                "observed_accepted_outputs_per_second",
                "observed_delivered_outputs_per_second",
            )
        },
        **{
            name: halves[name]
            for name in (
                "first_half_accepted_outputs",
                "second_half_accepted_outputs",
                "first_half_rate_per_second",
                "second_half_rate_per_second",
                "paired_rate_difference_per_second",
            )
        },
        "worker_wall_seconds": record["worker_wall_seconds"],
        "failures_json": json.dumps(metrics["failures"], sort_keys=True),
        "completion_path": str(completion),
        "completion_sha256": _hash(completion),
    }


def _line_rows(record: Mapping[str, Any]) -> list[dict[str, Any]]:
    result = []
    for name, line in sorted(record["lines"].items()):
        decisions = line["batch_decisions"]
        result.append(
            {
                "distance": record["distance"],
                "factory_count": record["factory_count"],
                "seed": record["seed"],
                "factory_id": name,
                "status": line["status"],
                "scope": "whole case including warmup and drain",
                "raw_attempts": line["raw_attempts"],
                "raw_rejections": line["raw_rejections"],
                "factory_attempts": len(decisions),
                "factory_rejections": sum(not row["accepted"] for row in decisions),
                "s_calls": line["s_calls"],
                "se_calls": line["se_calls"],
                "accepted_outputs": line["accepted_outputs"],
                "delivered_outputs": line["delivered_outputs"],
                "logical_success": line.get("logical_success"),
                "batch_decisions_json": json.dumps(decisions, sort_keys=True),
                "failure_json": json.dumps(line.get("failure"), sort_keys=True),
            }
        )
    return result


def _check_ledger_totals(record: Mapping[str, Any]) -> None:
    """Reconcile saved line counters with whole-case and window summaries."""
    for name in (
        "raw_attempts",
        "raw_rejections",
        "s_calls",
        "se_calls",
        "accepted_outputs",
        "delivered_outputs",
    ):
        total = sum(line[name] for line in record["lines"].values())
        if total != record["ledger_counts"][name]:
            raise ValueError(f"REPORT_LINE_LEDGER_TOTAL_MISMATCH: {name}")
    for name in ("accepted_outputs", "delivered_outputs"):
        if (
            record["metrics"][name + "_total"] != record["ledger_counts"][name]
            or record["metrics"][name] > record["metrics"][name + "_total"]
        ):
            raise ValueError(f"REPORT_OUTPUT_TOTAL_MISMATCH: {name}")


def _cost_row(record: Mapping[str, Any]) -> dict[str, Any]:
    metrics = record["metrics"]
    share = _shares(metrics)
    return {
        "distance": record["distance"],
        "factory_count": record["factory_count"],
        "seed": record["seed"],
        "window_status": metrics["window_status"],
        "warmup_us": metrics["requested_window_us"][0],
        "stop_us": metrics["requested_window_us"][1],
        "actual_observation_us": metrics["actual_observation_us"],
        "accepted_outputs": metrics["accepted_outputs"],
        "configured_atoms": metrics["configured_atoms"],
        "configured_atom_time_us": metrics["configured_atom_time_us"],
        "movement_distance_atom_um": metrics["movement_distance_atom_um"],
        "transport_busy_union_us": metrics["transport_elapsed_us"],
        "home_footprint_area_um2": metrics["home_footprint_area_um2"],
        "home_area_time_um2_us": metrics["home_area_time_um2_us"],
        "allocated_scene_bbox_area_um2": metrics.get("allocated_scene_bbox_area_um2"),
        "allocated_scene_bbox_area_time_um2_us": metrics.get(
            "allocated_scene_bbox_area_time_um2_us"
        ),
        **{name + "_atom_time_us": share[name] for name in _SHARES},
        "category_busy_union_us_json": json.dumps(
            metrics["category_busy_union_us"], sort_keys=True
        ),
        "primitive_counts_json": json.dumps(
            metrics["primitive_counts"], sort_keys=True
        ),
    }


def _write_csv(
    path: Path, rows: Sequence[Mapping[str, Any]], fallback: Sequence[str]
) -> None:
    fields = list(dict.fromkeys(key for row in rows for key in row)) or list(fallback)
    with path.open("x", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _plot(
    cells: Sequence[Mapping[str, Any]],
    destination: Path,
    *,
    final_complete: bool,
    recorded_trajectories: int,
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    colors = {3: "#147d92", 5: "#ad5c2c", 7: "#7045a2"}
    figure, axes = plt.subplots(
        1, 3, figsize=(18, 5.8), gridspec_kw={"width_ratios": [1, 1, 1.45]}
    )
    for distance in sorted({cell["distance"] for cell in cells}):
        points = sorted(
            (
                cell
                for cell in cells
                if cell["distance"] == distance and cell["statistics"] is not None
            ),
            key=lambda item: item["factory_count"],
        )
        usable = [
            cell
            for cell in points
            if cell["statistics"]["statistics"]["accepted_outputs_per_second"]["mean"]
            is not None
        ]
        if usable:
            x = [cell["factory_count"] for cell in usable]
            means, errors = [], []
            for cell in usable:
                row = cell["statistics"]["statistics"]["accepted_outputs_per_second"]
                means.append(row["mean"])
                interval = row["confidence_interval_95"]
                errors.append(
                    0 if interval is None else (interval[1] - interval[0]) / 2
                )
            axes[0].errorbar(
                x,
                means,
                yerr=errors,
                marker="o",
                capsize=3,
                color=colors.get(distance),
                label=f"d = {distance}",
            )
            for cell, xvalue, mean in zip(usable, x, means, strict=True):
                axes[0].annotate(
                    f"{cell['complete_windows']}/{cell['recorded_seeds']}",
                    (xvalue, mean),
                    xytext=(0, 7),
                    textcoords="offset points",
                    fontsize=7,
                    ha="center",
                    color=colors.get(distance),
                )
        pooled = [
            cell
            for cell in points
            if cell["statistics"]["pooled_cost_per_accepted_output"][
                "configured_atom_time_us"
            ]
            is not None
        ]
        if pooled:
            axes[1].plot(
                [cell["factory_count"] for cell in pooled],
                [
                    cell["statistics"]["pooled_cost_per_accepted_output"][
                        "configured_atom_time_us"
                    ]
                    / 1e6
                    for cell in pooled
                ],
                marker="o",
                color=colors.get(distance),
                label=f"d = {distance}",
            )
    axes[0].set(
        title="Primary accepted output rate",
        xlabel="Parallel pipelines N",
        ylabel="States / second",
    )
    axes[1].set(
        title="Primary pooled atom-time per accepted output",
        xlabel="Parallel pipelines N",
        ylabel="Atom · seconds / state",
    )
    for axis in axes[:2]:
        axis.set_xscale("log", base=2)
        axis.set_xticks([1, 2, 4, 8], labels=[1, 2, 4, 8])
        axis.grid(alpha=0.2)
        if axis.lines:
            axis.legend(frameon=False, fontsize=9)
    available = [cell for cell in cells if cell["pooled_atom_time_shares"] is not None]
    palette = ("#339fbb", "#e5a63b", "#8b67b2", "#7cab73", "#8a8a8a", "#dbe1e7")
    bottoms = [0.0] * len(available)
    labels = {
        "gate": "Gate",
        "readout": "Readout",
        "transport": "Transport",
        "reset": "Reset",
        "other_active": "Other active",
        "idle": "Idle",
    }
    for category, color in zip(_SHARES, palette, strict=True):
        values = [cell["pooled_atom_time_shares"][category] * 100 for cell in available]
        axes[2].bar(
            range(len(available)),
            values,
            bottom=bottoms,
            label=labels[category],
            color=color,
            width=0.8,
        )
        bottoms = [
            bottom + value for bottom, value in zip(bottoms, values, strict=True)
        ]
    axes[2].set(
        title="Modeled atom-time shares",
        ylabel="Share of allocated atom-time (%)",
        ylim=(0, 100),
    )
    axes[2].set_xticks(
        range(len(available)),
        labels=[f"d{cell['distance']}\nN{cell['factory_count']}" for cell in available],
        fontsize=8,
    )
    axes[2].legend(
        ncol=3,
        frameon=False,
        fontsize=8,
        loc="lower center",
        bbox_to_anchor=(0.5, -0.28),
    )
    title = "Single-level MSD · fast center-distance cost model · one shared AOD"
    if not final_complete:
        title = (
            f"PRELIMINARY — recorded {recorded_trajectories}/192 trajectories\n" + title
        )
    figure.suptitle(title, fontsize=15 if final_complete else 14)
    figure.text(
        0.015,
        0.025,
        "Primary rates/costs condition on complete, failure-free windows (no pre-stop line budget abort). Rate: mean ± 95% t CI; labels = eligible / recorded seeds.\nFull-horizon budget-abort runs remain in separate observed-window statistics. Shares use additive modeled atom-time, including idle; no native legality or output-LER claim.",
        fontsize=8,
    )
    figure.subplots_adjust(left=0.06, right=0.99, top=0.85, bottom=0.25, wspace=0.28)
    figure.savefig(destination, dpi=240)
    plt.close(figure)


def build_report(campaign: Path, output: Path) -> dict[str, Any]:
    """Read verified completions and write a fresh immutable report directory."""
    campaign = campaign.resolve()
    if output.exists():
        raise FileExistsError(f"REPORT_OUTPUT_ALREADY_EXISTS: {output}")
    manifest_path = campaign / "manifest.json"
    manifest = _read(manifest_path)
    config, identity = manifest["configuration"], manifest["identity"]
    if (
        manifest["schema"] != "nadit.single_fast_campaign/1"
        or identity["config_sha256"] != reference_digest(config)
        or identity["source_sha256"] != manifest["source"]["sha256"]
        or manifest["source"]["sha256"] != reference_digest(manifest["source"]["files"])
    ):
        raise ValueError("REPORT_MANIFEST_IDENTITY_MISMATCH")
    cells, seed_rows, line_rows, cost_rows = [], [], [], []
    total_recorded = total_complete = 0
    all_guards = True
    pilots = []
    for distance in config["distances"]:
        for count in config["factory_counts"]:
            directory = campaign / "cells" / f"d{distance}-n{count}"
            policy = (
                _read(directory / "observation.json")
                if (directory / "observation.json").exists()
                else None
            )
            pilot = _verified_completion(
                directory / "pilot",
                identity,
                {
                    "distance": distance,
                    "factory_count": count,
                    "seed": config["pilot_seed"],
                    "max_cycles": config["observation"]["pilot_cycles"],
                    "stop_at_us": None,
                    "warmup_us": 0,
                },
            )
            pilots.append(
                {
                    "distance": distance,
                    "factory_count": count,
                    "recorded": pilot is not None,
                    "guard_passed": _guard_passed(pilot)
                    if pilot is not None
                    else False,
                }
            )
            metrics, missing = [], []
            exposure = {name: 0.0 for name in _SHARES}
            for seed in config["production_seeds"]:
                seed_directory = directory / f"seed-{seed:04d}"
                if policy is None:
                    if (seed_directory / "completion.json").exists():
                        raise ValueError("REPORT_COMPLETION_WITHOUT_FROZEN_POLICY")
                    record = None
                else:
                    record = _verified_completion(
                        seed_directory,
                        identity,
                        {
                            "distance": distance,
                            "factory_count": count,
                            "seed": seed,
                            "max_cycles": config["limits"]["max_cycles"],
                            "stop_at_us": policy["stop_us"],
                            "warmup_us": policy["warmup_us"],
                        },
                    )
                if record is None:
                    missing.append(seed)
                    seed_rows.append(
                        {
                            "distance": distance,
                            "factory_count": count,
                            "seed": seed,
                            "status": "not_run",
                        }
                    )
                    line_rows.extend(
                        {
                            "distance": distance,
                            "factory_count": count,
                            "seed": seed,
                            "factory_id": f"factory{i}",
                            "status": "not_run",
                        }
                        for i in range(count)
                    )
                    continue
                for filename in ("case.json.gz", "ledger.json.gz"):
                    if f"{record['attempt']}/{filename}" not in record["artifacts"]:
                        raise ValueError("REPORT_COMPLETE_LEDGER_ARTIFACT_MISSING")
                if set(record["lines"]) != {f"factory{i}" for i in range(count)}:
                    raise ValueError("REPORT_FACTORY_LINE_COVERAGE_MISMATCH")
                _check_ledger_totals(record)
                all_guards = all_guards and _guard_passed(record)
                value = record["metrics"]
                if value["requested_window_us"] != [
                    policy["warmup_us"],
                    policy["stop_us"],
                ]:
                    raise ValueError("REPORT_WINDOW_DIFFERS_FROM_FROZEN_POLICY")
                metrics.append(value)
                seed_rows.append(_seed_row(record, seed_directory / "completion.json"))
                line_rows.extend(_line_rows(record))
                cost_rows.append(_cost_row(record))
                if value["requested_window_complete"]:
                    for name, amount in _shares(value).items():
                        exposure[name] += amount
            statistics = summarize_center_samples(metrics) if metrics else None
            complete = sum(row["requested_window_complete"] for row in metrics)
            total_recorded += len(metrics)
            total_complete += complete
            total_atom_time = sum(exposure.values())
            exclusion = (
                _read(directory / "excluded.json")
                if (directory / "excluded.json").exists()
                else None
            )
            cells.append(
                {
                    "distance": distance,
                    "factory_count": count,
                    "status": "pilot_excluded"
                    if exclusion
                    else "not_run"
                    if not metrics
                    else "incomplete"
                    if missing
                    else "complete"
                    if complete == len(metrics)
                    else "partial_failure",
                    "recorded_seeds": len(metrics),
                    "complete_windows": complete,
                    "missing_seeds": missing,
                    "exclusion": exclusion,
                    "statistics": statistics,
                    "half_window_diagnostic": summarize_half_windows(metrics),
                    "observed_window_secondary": summarize_observed_windows(metrics),
                    "observation_policy": policy,
                    "pooled_atom_time_shares": {
                        name: value / total_atom_time
                        for name, value in exposure.items()
                    }
                    if total_atom_time
                    else None,
                }
            )
    smoke = _verified_completion(
        campaign / "smoke",
        identity,
        {
            "distance": 3,
            "factory_count": 2,
            "seed": 0,
            "max_cycles": 2,
            "stop_at_us": None,
            "warmup_us": 0,
        },
    )
    acceptance = (
        _read(campaign / "smoke/acceptance.json")
        if (campaign / "smoke/acceptance.json").exists()
        else None
    )
    smoke_passed = (
        smoke is not None
        and _guard_passed(smoke)
        and acceptance is not None
        and acceptance.get("passed") is True
        and acceptance.get("identity") == identity
        and acceptance.get("completion_sha256") == reference_digest(smoke)
    )
    exact_grid = (
        set(config["distances"]) == set(_EXPECTED_DISTANCES)
        and set(config["factory_counts"]) == set(_EXPECTED_COUNTS)
        and set(config["production_seeds"]) == set(_EXPECTED_SEEDS)
        and len(cells) == 12
    )
    coverage_complete = (
        exact_grid
        and total_recorded == 192
        and all(cell["recorded_seeds"] == 16 for cell in cells)
    )
    guards_passed = (
        all_guards
        and bool(total_recorded)
        and all(row["guard_passed"] for row in pilots)
        and smoke_passed
    )
    summary = {
        "schema": "nadit.single_fast_report/1",
        "campaign": str(campaign),
        "identity": identity,
        "configuration": config,
        "manifest_sha256": _hash(manifest_path),
        "source_sha256": manifest["source"]["sha256"],
        "configured_trajectories": len(cells) * len(config["production_seeds"]),
        "recorded_trajectories": total_recorded,
        "complete_observation_windows": total_complete,
        "primary_eligible_observation_windows": total_complete,
        "observation_coverage_complete_windows": sum(
            cell["observed_window_secondary"]["covered_seed_count"] for cell in cells
        ),
        "covered_windows_with_budget_abort": sum(
            cell["observed_window_secondary"]["budget_abort_seed_count"]
            for cell in cells
        ),
        "primary_eligibility_definition": "requested horizon observed without a pre-stop line failure or budget abort; coverage alone does not imply primary eligibility",
        "expected_final_trajectories": 192,
        "requested_grid_exact": exact_grid,
        "coverage_complete": coverage_complete,
        "all_guards_passed": guards_passed,
        "all_observation_windows_complete": coverage_complete and total_complete == 192,
        "final_report_complete": coverage_complete and guards_passed,
        "final_report_definition": "all 192 hash-checked production trajectories recorded; 16 seeds per requested cell; smoke/pilot/production guards passed; failed windows remain explicit",
        "smoke_passed": smoke_passed,
        "pilots": pilots,
        "cells": cells,
        "physical_execution": False,
        "native_legality_verified": False,
        "actual_output_error": None,
        "cost_scope": "reference intrinsic operations plus block-center transport; independent assumed transversal S; declared post-rotation EC",
        "statistical_scope": "production-seed variability conditional on complete windows; pooled costs include complete zero-output trajectories; calibration uncertainty and model discrepancy excluded",
        "throughput_interpretation": "finite fixed-window output rates after configured warmup; per-cell paired half-window diagnostics are reported; asymptotic steady state is not established",
        "secondary_observed_window_scope": "separately reports fully observed fixed windows including line budget aborts; no extrapolation for truncated runs; not an asymptotic steady-state estimate",
        "omissions": [
            "Native AOD capture, collision, finite-capacity and trajectory legality are unverified.",
            "Raw acceptance uses archived supply references fixed across geometry; accepted-input quality p is separate.",
            "SE syndrome outcomes and general decoding are not simulated; Pauli canonicalization is a cost envelope.",
            "Waiting maintenance and external output transport/consumption/reset are excluded.",
            "Category partitions preserve cost integrals, not native operation order; clipped exposure is uniform aggregate modeling.",
            "Noise exposure is not decoded output logical error or a hardware result.",
        ],
    }
    output.mkdir(parents=True, exist_ok=False)
    _write_csv(
        output / "seed-ledger.csv",
        seed_rows,
        ("distance", "factory_count", "seed", "status"),
    )
    _write_csv(
        output / "line-ledger.csv",
        line_rows,
        ("distance", "factory_count", "seed", "factory_id", "status"),
    )
    _write_csv(
        output / "costs.csv",
        cost_rows,
        ("distance", "factory_count", "seed", "window_status"),
    )
    _plot(
        cells,
        output / "scaling.png",
        final_complete=summary["final_report_complete"],
        recorded_trajectories=total_recorded,
    )
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True, allow_nan=False), encoding="utf-8"
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    summary = build_report(arguments.campaign, arguments.output)
    print(
        json.dumps(
            {
                key: summary[key]
                for key in (
                    "recorded_trajectories",
                    "complete_observation_windows",
                    "final_report_complete",
                    "all_guards_passed",
                )
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
