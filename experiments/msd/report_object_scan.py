"""Audit a complete saved scan and build statistical figures and an HTML report.

This is read-only analysis of compact shot records. It never executes factories.
"""

import argparse
import csv
import gzip
import html
import json
import math
import statistics
from collections.abc import Sequence
from pathlib import Path
from typing import Any


def _read(path: Path) -> dict[str, Any]:
    value: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return value


def _ratio_variance(
    numerators: Sequence[float], denominators: Sequence[float]
) -> float | None:
    denominator = sum(denominators)
    if not denominator or len(numerators) < 2:
        return None
    ratio = sum(numerators) / denominator
    residual = [a - ratio * b for a, b in zip(numerators, denominators, strict=True)]
    return statistics.variance(residual) / (
        len(residual) * (denominator / len(residual)) ** 2
    )


def audit_data(root: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Require every requested shot and paired signature before reporting success."""
    final = _read(root / "summary.json")
    if final.get("status") != "complete" or (root / "error.json").exists():
        raise ValueError("COMPLETE_SCAN_REQUIRED")
    manifest = _read(root / "manifest.json")
    config = manifest["configuration"]
    two_level = config.get("schema") == "nadit.level2_object_scan/1"
    common_rounds: dict[tuple[int, int, int, str], str] = {}
    expected = list(
        range(config["seed_start"], config["seed_start"] + config["seed_count"])
    )
    cells = []
    signatures: dict[tuple[int, int, int], tuple[str, str, int]] = {}
    catalogs: dict[int, str] = {}
    records_total = 0
    case_seconds = 0.0
    for cell in manifest["cells"]:
        folder = root / "cells" / cell["id"]
        saved = _read(folder / "summary.json")
        if saved["status"] != "complete" or (folder / "error.json").exists():
            raise ValueError(f"INCOMPLETE_CELL: {cell['id']}")
        shots = [
            json.loads(line)
            for line in (folder / "shots.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        if [r["seed"] for r in shots] != expected:
            raise ValueError(f"SEED_COVERAGE_MISMATCH: {cell['id']}")
        if saved["catalog_sha256"] != catalogs.setdefault(
            cell["distance"], saved["catalog_sha256"]
        ):
            raise ValueError("CATALOG_CHANGED_WITHIN_DISTANCE")
        reuse = saved["reuse"]
        if (
            not reuse["identities_preserved"]
            or reuse["templates"] != 10
            or any(
                reuse[k]
                for k in (
                    "physical_compile_attempts",
                    "atom_expansion_attempts",
                    "atom_construction_attempts",
                )
            )
        ):
            raise ValueError("COMPONENT_REUSE_OR_ATOM_GUARD_FAILED")
        for shot in shots:
            key = (cell["distance"], cell["factories"], shot["seed"])
            if two_level:
                for owner, digest in shot["event_groups"].items():
                    group = (*key, owner)
                    if common_rounds.setdefault(group, digest) != digest:
                        raise ValueError(f"COMMON_EVENT_MISMATCH: {group}")
                if (
                    shot["metrics"]["outputs"] not in (0, 1)
                    or shot["conservation"]["inputs"] != 15
                    or shot["metrics"]["level1_outputs"]
                    != 15 + shot["conservation"]["surplus"]
                ):
                    raise ValueError("LEVEL2_CONSERVATION_MISMATCH")
                signatures.setdefault(
                    key, ("common_rounds", "", shot["metrics"]["outputs"])
                )
                case_seconds += shot["software_seconds"]
                continue
            signature = (
                shot["event_sha256"],
                shot["call_sha256"],
                shot["metrics"]["outputs"],
            )
            if signature != signatures.setdefault(key, signature):
                raise ValueError(
                    f"PAIRED_SIGNATURE_MISMATCH: {cell['id']} seed={shot['seed']}"
                )
            if (
                shot["metrics"]["outputs"] + shot["metrics"]["final_rejections"]
                != cell["factories"]
            ):
                raise ValueError("SINGLE_ROUND_COUNT_MISMATCH")
            case_seconds += shot["software_seconds"]
        stat = saved["statistics"]
        for metric, summary in stat["metrics"].items():
            values = [
                r["metrics"][metric]
                for r in shots
                if r["metrics"].get(metric) is not None
            ]
            if summary["n"] != len(values):
                raise ValueError("METRIC_SAMPLE_COUNT_MISMATCH")
            for field, actual in (
                ("mean", statistics.mean(values) if values else None),
                ("variance", statistics.variance(values) if len(values) > 1 else None),
            ):
                if actual is None:
                    if summary[field] is not None:
                        raise ValueError("MISSING_METRIC_WAS_INVENTED")
                elif not math.isclose(
                    actual, summary[field], rel_tol=1e-11, abs_tol=1e-8
                ):
                    raise ValueError(f"STATISTIC_READBACK_MISMATCH: {metric}/{field}")
        output = [r["metrics"]["outputs"] for r in shots]
        durations = [r["metrics"]["duration_us"] for r in shots]
        if not math.isclose(
            stat["pooled_rate_per_second"],
            sum(output) * 1e6 / sum(durations),
            rel_tol=1e-12,
        ):
            raise ValueError("POOLED_RATE_MISMATCH")
        transport = [
            sum(
                r["metrics"][k]
                for k in ("move_command_us", "load_command_us", "store_command_us")
            )
            for r in shots
        ]
        stat["metrics"]["transport_command_us"] = {
            "n": len(transport),
            "mean": statistics.mean(transport),
            "variance": statistics.variance(transport),
            "min": min(transport),
            "max": max(transport),
        }
        stat["atom_cost_estimator_variance_delta"] = _ratio_variance(
            [r["metrics"]["atom_time_us"] for r in shots], output
        )
        stat["area_cost_estimator_variance_delta"] = _ratio_variance(
            [r["metrics"]["storage_area_time_um2_us"] for r in shots], output
        )
        delivered = [int(r["metrics"]["startup_us"] is not None) for r in shots]
        startup_work = [
            r["metrics"]["startup_us"] if hit else r["metrics"]["duration_us"]
            for r, hit in zip(shots, delivered, strict=True)
        ]
        stat["startup_estimator_variance_delta"] = _ratio_variance(
            startup_work, delivered
        )
        saved["shots_path"] = str(folder / "shots.jsonl")
        cells.append(saved)
        records_total += len(shots)
    if records_total != final["shots"] or len(cells) != final["cells"]:
        raise ValueError("FINAL_COVERAGE_MISMATCH")
    audit = {
        "status": "passed",
        "cells": len(cells),
        "shots": records_total,
        "paired_groups": len(signatures),
        "common_production_rounds": len(common_rounds),
        "catalogs": catalogs,
        "case_software_seconds_sum": case_seconds,
        "server_wall_seconds": final["wall_seconds"],
        "worker_software_seconds_sum": sum(c["software_seconds"] for c in cells),
        "source_commit": manifest.get("source_commit"),
        "physical_workers": manifest["physical_workers"],
        "configuration": config,
    }
    return cells, audit


PLOTS = {
    "rate": ("Shot-renewal accepted-output rate", "outputs / s", 1),
    "startup": ("First delivery under shot restart", "ms", 1000),
    "atom_cost": ("Atom-time per accepted output", "atom s / output", 1e6),
    "atom_distance_estimate_um": (
        "Estimated atom-summed travel per shot",
        "million atom um",
        1e6,
    ),
    "transport_command_us": ("Move + Load + Store per shot", "ms", 1000),
    "unassigned_block_us": ("Unassigned block time per shot", "block s", 1e6),
    "atoms": ("All configured atoms", "atoms", 1),
    "storage_area_um2": (
        "Storage bounding area (not whole device)",
        "million square um",
        1e6,
    ),
    "aod_move_command_distance_um": (
        "Shared Move limiting-displacement sum",
        "thousand um",
        1000,
    ),
}


def findings_html(cells: list[dict[str, Any]]) -> str:
    """Summarize observed scan values without making a physical-optimum claim."""
    rows = []
    if "level2_position" in cells[0]["cell"]:
        for d in (3, 5, 7, 9, 11):
            best = max(
                (c for c in cells if c["cell"]["distance"] == d),
                key=lambda c: c["statistics"]["pooled_rate_per_second"],
            )
            c, s = best["cell"], best["statistics"]
            rows.append(
                f"<tr><td>{d}</td><td>{c['factories']}</td><td>{c['rows']}x{c['columns']}</td><td>{c['level2_position']}</td><td>{s['pooled_rate_per_second']:.5f}</td><td>{s['metrics']['level2_supply_wait_us']['mean'] / 1000:.3f}</td></tr>"
            )
        return (
            "<section><h2>每个码距的观测最高产率配置</h2><table><tr><th>d</th><th>N1</th><th>一级行列</th><th>二级位置</th><th>输出/s</th><th>二级等输入 ms</th></tr>"
            + "".join(rows)
            + "</table><p>仅表示本次有限扫描的观测结果。不同 N1 的原子预算不同；不是稳态或完整硬件最优结论。</p></section>"
        )
    for d in (3, 5, 7, 9, 11):
        entries = {
            e["cell"]["strategy"]: e
            for e in cells
            if e["cell"]["distance"] == d
            and e["cell"]["factories"] == 10
            and e["cell"]["columns"] == 10
        }
        a = entries["asynchronous"]["statistics"]["pooled_rate_per_second"]
        s = entries["synchronous"]["statistics"]["pooled_rate_per_second"]
        bounds = entries["synchronous"]["statistics"]["rate_ci95_delta"]
        rows.append(
            f"<tr><td>{d}</td><td>{a:.3f}</td><td>{s:.3f}</td><td>[{bounds[0]:.3f}, {bounds[1]:.3f}]</td><td>{s / a:.2f}×</td></tr>"
        )
    base = next(
        e
        for e in cells
        if e["cell"]["distance"] == 11
        and e["cell"]["factories"] == 1
        and e["cell"]["strategy"] == "asynchronous"
    )
    vertical = next(
        e
        for e in cells
        if e["cell"]["distance"] == 11
        and e["cell"]["factories"] == 10
        and e["cell"]["columns"] == 1
        and e["cell"]["strategy"] == "asynchronous"
    )
    before = base["statistics"]["pooled_rate_per_second"]
    after = vertical["statistics"]["pooled_rate_per_second"]
    return (
        "<section><h2>主要结果</h2><p>在本模型的扫描范围内，左右排列给出最高产率；它以更大的横向宽度换取较短的读出运输。N=10 左右排列的结果如下，单位为接受输出/秒。</p>"
        "<table><tr><th>d</th><th>异步</th><th>同步</th><th>同步 95% 区间</th><th>同步/异步</th></tr>"
        + "".join(rows)
        + "</table>"
        f"<p>增加工厂数并不保证产率上升：d=11 的上下排列异步方案，从 N=1 的 {before:.3f}/s 变为 N=10 的 {after:.3f}/s（下降 {100 * (1 - after / before):.1f}%）。需要同时考虑布局、共享 AOD 竞争和时空成本。</p>"
        "<p>这些数值是固定概率资源模型下的比较。没有提供不同码距的实际解码输出误差，也没有施加共同设备宽度上限，因此不构成物理最优设计或输出质量匹配结论。</p></section>"
    )


def _value(cell: dict[str, Any], metric: str) -> tuple[float | None, float | None]:
    stat = cell["statistics"]
    if metric in ("rate", "startup", "atom_cost"):
        value_key, var_key = {
            "rate": ("pooled_rate_per_second", "rate_estimator_variance_delta"),
            "startup": ("renewal_startup_mean_us", "startup_estimator_variance_delta"),
            "atom_cost": ("atom_us_per_output", "atom_cost_estimator_variance_delta"),
        }[metric]
        value = stat[value_key]
        variance = stat[var_key]
    else:
        row = stat["metrics"][metric]
        value = row["mean"]
        variance = (
            row["variance"] / row["n"]
            if row["variance"] is not None and row["n"]
            else None
        )
    return value, math.sqrt(variance) if variance is not None else None


def _plot_points(
    cells: list[dict[str, Any]],
    metric: str,
    layout: str,
    mode: str,
    x_axis: str,
    series: int,
) -> list[tuple[int, float, float | None]]:
    """Select one curve; preserve unknown uncertainty separately from zero."""
    points = []
    for entry in cells:
        c = entry["cell"]
        matches = {
            "vertical": c["columns"] == 1,
            "horizontal": c["columns"] == c["factories"],
            "two_columns": c["columns"] == 2 and c["rows"] >= 2,
            "two_rows": c["rows"] == 2 and c["columns"] >= 2,
        }[layout]
        series_key, x_key = (
            ("distance", "factories") if x_axis == "N" else ("factories", "distance")
        )
        if c[series_key] != series or c["strategy"] != mode or not matches:
            continue
        value, se = _value(entry, metric)
        if value is not None:
            points.append((c[x_key], value, 1.96 * se if se is not None else None))
    return sorted(points)


def _plot_limits(
    points: list[tuple[int, float, float | None]], scale: float
) -> tuple[float, float]:
    """Fit one panel to its own points and confidence-interval endpoints."""
    upper = max(
        (
            (value + halfwidth if halfwidth is not None else value) / scale
            for _, value, halfwidth in points
        ),
        default=0.0,
    )
    return 0.0, upper * 1.08 if upper > 0 else 1.0


def plot_figures(cells: list[dict[str, Any]], output: Path) -> list[str]:
    """Export both axis projections with independent panel scales and CI audits."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    from matplotlib.ticker import MaxNLocator

    plt.rcParams.update(
        {"font.size": 10, "axes.spines.top": False, "axes.spines.right": False}
    )
    palette = ["#0072B2", "#E69F00", "#009E73", "#CC79A7", "#D55E00", "#555555"]
    layouts = ("vertical", "horizontal", "two_columns", "two_rows")
    figures = output / "figures"
    figures.mkdir(exist_ok=True)
    names = []
    two_level = "level2_position" in cells[0]["cell"]
    modes = (
        ("below_center", "right_center", "above_center")
        if two_level
        else ("asynchronous", "synchronous")
    )
    plots = {
        **PLOTS,
        **(
            {
                "level2_supply_wait_us": ("L2 input starvation", "ms", 1000),
                "delivery_us": ("Inter-level delivery", "ms", 1000),
            }
            if two_level
            else {}
        ),
    }
    audit: dict[str, Any] = {
        "interval": "estimate +/- 1.96 SE",
        "metrics": {},
        "plots": {},
    }
    for metric, (title, unit, scale) in plots.items():
        values = [_value(c, metric) for c in cells]
        relative = [
            196 * se / abs(value)
            for value, se in values
            if value and se is not None and se > 0
        ]
        audit["metrics"][metric] = {
            "zero_ci": sum(se == 0 for value, se in values if value is not None),
            "nonzero_ci": sum(se is not None and se > 0 for value, se in values),
            "missing_ci": sum(se is None for _, se in values),
            "relative_halfwidth_percent_range": [min(relative), max(relative)]
            if relative
            else None,
            "scale_policy": "independent_per_panel",
        }
        for x_axis in ("N", "d"):
            series_values = [3, 5, 7, 9, 11] if x_axis == "N" else [1, 2, 4, 6, 8, 10]
            ticks = [1, 2, 4, 6, 8, 10] if x_axis == "N" else [3, 5, 7, 9, 11]
            legend_key = "d" if x_axis == "N" else "N"
            fig, axes = plt.subplots(
                len(modes),
                4,
                figsize=(16, 4.1 * len(modes)),
                sharex=True,
                sharey=False,
                layout="constrained",
            )
            count_points = 0
            count_nonzero = 0
            for ri, mode in enumerate(modes):
                for ci, layout in enumerate(layouts):
                    ax = axes[ri, ci]
                    panel_points: list[tuple[int, float, float | None]] = []
                    for series, color in zip(series_values, palette, strict=False):
                        points = _plot_points(
                            [c for c in cells if c["cell"]["level2_position"] == mode]
                            if two_level
                            else cells,
                            metric,
                            layout,
                            "synchronous" if two_level else mode,
                            x_axis,
                            series,
                        )
                        if not points:
                            continue
                        panel_points.extend(points)
                        count_points += len(points)
                        count_nonzero += sum(
                            p[2] is not None and p[2] > 0 for p in points
                        )
                        ax.plot(
                            [p[0] for p in points],
                            [p[1] / scale for p in points],
                            color=color,
                            linewidth=1.3,
                            zorder=1,
                        )
                        known = [p for p in points if p[2] is not None]
                        ax.errorbar(
                            [p[0] for p in known],
                            [p[1] / scale for p in known],
                            yerr=[p[2] / scale for p in known if p[2] is not None],
                            fmt="o",
                            color=color,
                            markerfacecolor="white",
                            markersize=3,
                            elinewidth=1.2,
                            capsize=3.5,
                            capthick=1.1,
                            barsabove=True,
                            zorder=3,
                        )
                        unknown = [p for p in points if p[2] is None]
                        if unknown:
                            ax.plot(
                                [p[0] for p in unknown],
                                [p[1] / scale for p in unknown],
                                linestyle="none",
                                marker="x",
                                color=color,
                                zorder=3,
                            )
                    ax.set_title(
                        f"{mode if two_level else 'Async' if ri == 0 else 'Sync v2'} / {layout.replace('_', ' ')}"
                    )
                    ax.set_xlabel(
                        ("N1 producers" if two_level else "N factories")
                        if x_axis == "N"
                        else "Code distance d"
                    )
                    ax.set_ylabel(unit)
                    ax.set_xticks(ticks)
                    ax.set_ylim(*_plot_limits(panel_points, scale))
                    ax.yaxis.set_major_locator(MaxNLocator(nbins=6))
                    ax.tick_params(labelleft=True, labelbottom=True)
                    ax.grid(alpha=0.2)
            fig.legend(
                handles=[
                    Line2D(
                        [0],
                        [0],
                        color=color,
                        marker="o",
                        markerfacecolor="white",
                        label=f"{legend_key}={value}",
                    )
                    for value, color in zip(series_values, palette, strict=False)
                ],
                loc="outside lower center",
                ncol=len(series_values),
                frameon=False,
            )
            zero = audit["metrics"][metric]["nonzero_ci"] == 0
            note = (
                "All seed variances are zero; CI collapses to each marker"
                if zero
                else "95% estimator CI (not shot SD); small intervals may overlap markers"
            )
            fig.suptitle(
                f"{title} | x={x_axis}, legend={legend_key}\n100 seeds/cell; independent y-scale per panel; compare axis values\n{note}",
                fontsize=12,
            )
            name = metric if x_axis == "N" else metric + "_by_d"
            fig.savefig(figures / (name + ".svg"), bbox_inches="tight")
            fig.savefig(figures / (name + ".png"), dpi=140, bbox_inches="tight")
            audit["plots"][name] = {
                "x_axis": x_axis,
                "legend": legend_key,
                "points": count_points,
                "nonzero_errorbars": count_nonzero,
                "panel_limits": [list(ax.get_ylim()) for ax in axes.flat],
                "panel_ticks": [ax.get_yticks().tolist() for ax in axes.flat],
            }
            plt.close(fig)
            names.append(name)
    (output / "plot-audit.json").write_text(
        json.dumps(audit, indent=2), encoding="utf-8"
    )
    return names


def build_report(root: Path, output: Path) -> dict[str, Any]:
    """Audit complete inputs, export machine-readable data, plots and one HTML page."""
    cells, audit = audit_data(root)
    output.mkdir(parents=True, exist_ok=False)
    with (output / "cell-summary.csv").open(
        "w", newline="", encoding="utf-8-sig"
    ) as stream:
        writer = csv.writer(stream)
        writer.writerow(
            [
                "d",
                "N",
                "columns",
                "rows",
                "strategy",
                "metric",
                "samples",
                "mean",
                "variance",
                "min",
                "max",
                "variance_basis",
            ]
        )
        for entry in cells:
            c = entry["cell"]
            for metric, row in entry["statistics"]["metrics"].items():
                writer.writerow(
                    [
                        c["distance"],
                        c["factories"],
                        c["columns"],
                        c["rows"],
                        c["strategy"],
                        metric,
                        *[row[k] for k in ("n", "mean", "variance", "min", "max")],
                        "between_shot_sample",
                    ]
                )
            stat = entry["statistics"]
            for key, var in (
                ("pooled_rate_per_second", "rate_estimator_variance_delta"),
                ("renewal_startup_mean_us", "startup_estimator_variance_delta"),
                ("atom_us_per_output", "atom_cost_estimator_variance_delta"),
                ("storage_area_us_per_output", "area_cost_estimator_variance_delta"),
            ):
                writer.writerow(
                    [
                        c["distance"],
                        c["factories"],
                        c["columns"],
                        c["rows"],
                        c["strategy"],
                        key,
                        stat["shots"],
                        stat[key],
                        stat[var],
                        None,
                        None,
                        "ratio_estimator_delta",
                    ]
                )
    with gzip.open(output / "all-shots.jsonl.gz", "wt", encoding="utf-8") as stream:
        for entry in cells:
            for line in (
                Path(entry.pop("shots_path")).read_text(encoding="utf-8").splitlines()
            ):
                stream.write(
                    json.dumps(
                        {"cell": entry["cell"], **json.loads(line)},
                        separators=(",", ":"),
                    )
                    + "\n"
                )
    (output / "audit.json").write_text(json.dumps(audit, indent=2), encoding="utf-8")
    (output / "aggregate-results.json").write_text(
        json.dumps(cells, separators=(",", ":"), allow_nan=False), encoding="utf-8"
    )
    selected = []
    two_level = "level2_position" in cells[0]["cell"]
    for d in (3, 5, 7, 9, 11):
        for mode in ("synchronous",) if two_level else ("asynchronous", "synchronous"):
            candidates = [
                e
                for e in cells
                if e["cell"]["distance"] == d
                and e["cell"]["factories"] == 10
                and e["cell"]["strategy"] == mode
            ]
            selected.append(
                max(
                    candidates, key=lambda e: e["statistics"]["pooled_rate_per_second"]
                )["cell"]["id"]
            )
    selected.extend(
        (
            [
                f"d03-n01-c01-synchronous-{p}"
                for p in ("below_center", "right_center", "above_center")
            ]
            + ["d11-n10-c01-synchronous-below_center"]
        )
        if two_level
        else ["d03-n01-c01-synchronous", "d11-n10-c01-asynchronous"]
    )
    selected = list(dict.fromkeys(selected))
    (output / "representative-selection.json").write_text(
        json.dumps(selected, indent=2), encoding="utf-8"
    )
    print("AUDIT COMPLETE " + json.dumps(audit), flush=True)
    plot_figures(cells, output)
    plot_audit = _read(output / "plot-audit.json")
    cards = []
    plots = {
        **PLOTS,
        **(
            {
                "level2_supply_wait_us": ("L2 input starvation", "ms", 1000),
                "delivery_us": ("Inter-level delivery", "ms", 1000),
            }
            if two_level
            else {}
        ),
    }
    for name, (title, unit, _) in plots.items():
        info = plot_audit["metrics"][name]
        interval = info["relative_halfwidth_percent_range"]
        note = (
            f"本指标所有 {len(cells)} 个组合的 seed 方差均为零，置信区间收缩为点，不是遗漏误差棒。"
            if interval is None and info["zero_ci"] == len(cells)
            else f"非零误差棒 {info['nonzero_ci']} 个，零误差 {info['zero_ci']} 个，缺失 {info['missing_ci']} 个。"
        )
        if interval:
            note += f"95% 区间半宽为均值的 {interval[0]:.3f}%–{interval[1]:.3f}%；较小的区间仍可能与标记重叠。"
        cards.append(
            f"<section><h2>{title}</h2><p>单位：{unit}。每个子图按自身数据独立设置纵轴范围和刻度，以便看清趋势与误差棒；跨子图比较时请读取刻度值，不直接比较曲线的视觉高度。</p><p>{note}</p>"
            "<p>N=1 的上下布局、N=4 的两列／两行引用同一组几何样本，不重复累计；两行／两列网格仅显示 N≥4 的已有配置，不补造 N=1/2 数据。</p>"
            f'<h3>横轴 N · 图例 d</h3><a href="figures/{name}.svg"><img src="figures/{name}.png" alt="{title}: x=N, legend=d" loading="lazy"></a>'
            f'<h3>横轴 d · 图例 N</h3><a href="figures/{name}_by_d.svg"><img src="figures/{name}_by_d.png" alt="{title}: x=d, legend=N" loading="lazy"></a></section>'
        )
    payload = json.dumps(cells, separators=(",", ":"), ensure_ascii=False).replace(
        "<", "\\u003c"
    )
    template = Path(__file__).with_suffix(".html").read_text(encoding="utf-8")
    if two_level:
        template = template.replace(
            "d、N、布局、策略", "单二级厂：d、N1、布局；一级仅同步"
        )
        template = template.replace(
            "每 shot 一轮生产", "每 shot 一轮二级尝试并排空一级；N2=B=1"
        )
        template = template.replace(
            "所有配对条件的概率事件／调用签名一致",
            "布局间共有语义轮次的概率事件一致；额外生产前缀可不同",
        )
        template = template.replace(
            "按独立 shot 重启的更新模型解释为长期平均率",
            "采用独立 shot 重启口径，不视为连续流水线稳态",
        )
        template = template.replace("6N(2d²−1)", "6(N1+1)(2d²−1)")
        template = template.replace(
            "理想外部 sink，排除外部注入成本",
            "仅二级输出使用理想外部 sink；跨级三段交付计费，排除外部注入成本",
        )
        template = template.replace(
            "每 shot 20秒、每波 5秒、每组合 2060秒、整批 3600秒",
            "每 shot 30秒、每波 5秒、每组合 3060秒、整批 86400秒",
        )
        template = template.replace(
            '<label>策略 <select id="mode"><option value="all">全部</option><option value="asynchronous">异步</option><option value="synchronous">同步</option>',
            '<label>二级位置 <select id="mode"><option value="all">全部</option><option>below_center</option><option>right_center</option><option>above_center</option>',
        )
        template = template.replace("<th>策略</th>", "<th>二级位置</th>").replace(
            "<th>N</th>", "<th>N1</th>"
        )
        template = template.replace(
            "'factories':'strategy'", "'factories':'level2_position'"
        ).replace("c.strategy==='synchronous'?'同步':'异步'", "c.level2_position")
        template = template.replace(
            "const labels={",
            "const labels={level2_supply_wait_us:'二级等输入 μs',level2_resource_wait_us:'二级等资源 μs',level2_computation_us:'二级计算 μs',level2_completion_us:'二级完成 μs',drain_tail_us:'排空尾部 μs',delivery_us:'跨级交付 μs',retained_surplus:'一级剩余输出',mean_queue_occupancy:'平均队列占用',level1_rounds:'一级总尝试轮数',",
        )
    content = (
        template.replace("__CELLS__", str(audit["cells"]))
        .replace("__SHOTS__", str(audit["shots"]))
        .replace("__WALL__", f"{audit['server_wall_seconds']:.1f}")
        .replace("__SOURCE__", html.escape(str(audit["source_commit"])))
        .replace("__FINDINGS__", findings_html(cells))
        .replace("__FIGURES__", "".join(cards))
        .replace("__DATA__", payload)
    )
    (output / "index.html").write_text(content, encoding="utf-8")
    return audit


def main() -> None:
    """Read downloaded compact scan results; require a fresh report directory."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build_report(args.input, args.output), indent=2))


if __name__ == "__main__":
    main()
