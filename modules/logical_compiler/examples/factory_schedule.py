"""Render an existing complete object schedule without running any backend."""

import argparse
import hashlib
import html
import json
import math
from collections import Counter
from itertools import pairwise
from pathlib import Path
from typing import Any


def _comparison(
    summary: dict[str, Any], baseline_case: Path | None
) -> dict[str, Any] | None:
    if baseline_case is None:
        return None
    baseline = json.loads(baseline_case.read_text(encoding="utf-8"))["summary"]
    if summary.get("production_basis", "accepted_outputs") != baseline.get(
        "production_basis", "accepted_outputs"
    ):
        raise ValueError("BASELINE_PRODUCTION_BASIS_MISMATCH")
    fields = (
        "distance",
        "factories",
        "seed",
        "cycles_per_factory",
        "accepted_outputs",
        "raw_acceptance_parameter",
        "experiment_model",
    )
    if any(summary.get(key) != baseline.get(key) for key in fields):
        raise ValueError("BASELINE_CONFIGURATION_MISMATCH")
    before, after = float(baseline["makespan_us"]), float(summary["makespan_us"])
    if before <= 0:
        raise ValueError("INVALID_BASELINE_DURATION")
    return {
        "before_us": before,
        "after_us": after,
        "reduction_percent": 100 * (before - after) / before,
        "baseline_strategy": baseline.get("strategy", {}).get("name", "asynchronous"),
        "current_strategy": summary.get("strategy", {}).get("name", "asynchronous"),
        "baseline_placement": baseline.get("placement", {}).get("kind", "vertical"),
        "current_placement": summary.get("placement", {}).get("kind", "vertical"),
    }


def _layout_markup(run: dict[str, Any]) -> str:
    """Draw saved block footprints only; no code imports or atom expansion."""
    layout = run.get("layout", {})
    budget = layout.get("budget", {})
    if "code_geometry" not in budget:
        return ""
    x0, y0, x1, y1 = budget["storage_bounds_um"]
    width, depth = x1 - x0, y1 - y0
    bounds = budget["code_geometry"]["relative_bounds"]
    bw, bh = bounds["x_max"] - bounds["x_min"], bounds["y_max"] - bounds["y_min"]
    font = min(26, bw * 0.4)
    placement = budget["factory_placement"]
    labels = {"vertical": "上下排列", "horizontal": "左右排列", "grid": "二维排列"}
    label = labels[placement["kind"]]
    pieces = [
        (
            '<section class="surface" aria-labelledby="layout-title">'
            f'<h2 id="layout-title">{label} · {placement["rows"]} 行 × {placement["columns"]} 列工厂</h2>'
            f"<p>存储区包围盒 {width:g} × {depth:g} μm，面积 {width * depth:g} μm²；"
            f"{budget['atom_count_estimate']} 个驻留原子。每厂内部角色顺序不变。</p>"
            '<div class="chart-wrap">'
            f'<svg role="img" aria-label="工厂几何布局" viewBox="0 0 {width + 40:g} {depth + 210:g}" '
            'style="display:block;width:100%;max-height:460px" xmlns="http://www.w3.org/2000/svg">'
            f'<rect x="20" y="30" width="{width:g}" height="70" fill="#dce9ff"/>'
            f'<text x="30" y="65" font-size="{font:g}">readout y ≥ 50 μm (schematic)</text>'
            f'<rect x="20" y="100" width="{width:g}" height="50" fill="#f5f6f8"/>'
            f'<text x="30" y="130" font-size="{font:g}">50 μm gap</text>'
            f'<rect x="20" y="150" width="{width:g}" height="{depth:g}" fill="#f1f5ef"/>'
        )
    ]
    groups: dict[str, list[dict[str, Any]]] = {}
    for patch in layout["patches"]:
        groups.setdefault(patch["factory_id"], []).append(patch)
        x = 20 + patch["origin"]["x"] + bounds["x_min"] - x0
        y = 150 - (patch["origin"]["y"] + bounds["y_max"])
        role = html.escape(patch["role"])
        block = html.escape(patch["block_id"])
        pieces.append(
            f'<g data-block="{block}"><title>{block}: ({patch["origin"]["x"]:g}, '
            f"{patch['origin']['y']:g}) μm</title>"
            f'<rect x="{x:g}" y="{y:g}" width="{bw:g}" height="{bh:g}" fill="#c8ded8" stroke="#35675d"/>'
            f'<text x="{x + bw / 2:g}" y="{y + bh / 2:g}" dominant-baseline="middle" '
            f'text-anchor="middle" font-size="{font:g}">{role}</text></g>'
        )
    for name, patches in groups.items():
        x = 20 + min(p["origin"]["x"] for p in patches) - x0
        y = 150 - min(p["origin"]["y"] for p in patches) + 28
        pieces.append(
            f'<text x="{x:g}" y="{y:g}" font-size="{font:g}">{html.escape(name)}</text>'
        )
    pieces.append(
        "</svg></div><p>图示按比例缩放，比较占地请使用标注的 μm 数值。"
        "上方读出区仅作示意，不代表已统计读出占地；当前模型不限制设备横向宽度。</p></section>"
    )
    return "".join(pieces)


def render_schedule(
    source: Path, target: Path, *, baseline_case: Path | None = None
) -> dict[str, Any]:
    """Read saved case data and write a fresh self-contained HTML schedule.

    Args:
        source: A completed factory_objects case JSON.
        target: A new HTML file; its parent directory must already exist.
        baseline_case: Optional earlier case with matching configuration and seed.

    Returns:
        Render counts, source fingerprint and optional elapsed-time comparison.

    Raises:
        ValueError: Incomplete cases, inconsistent counts or mismatched baselines.
        FileExistsError: The requested output already exists.
    """
    run = json.loads(source.read_text(encoding="utf-8"))
    case = run["case"]
    if case["status"] != "complete":
        raise ValueError("COMPLETE_SCHEDULE_REQUIRED")
    summary = run["summary"]
    count = summary["factories"]
    if type(count) is not int or count <= 0:
        raise ValueError("POSITIVE_INTEGER_FACTORY_COUNT_REQUIRED")
    factory_indices = {f"factory{i}": i for i in range(count)}
    calls = {c["invocation_id"]: c for c in case["calls"]}
    waves = case["execution"]["waves"]
    total = case["duration_us"]
    components = list(dict.fromkeys(c["component_id"] for c in calls.values()))
    phase_names = sorted({s["phase"] for w in waves for s in w["stage_schedule"]})
    phase_index = {p: i for i, p in enumerate(phase_names)}
    resources = ["aod:transport", "camera", "local", "rydberg"]
    categories = ["reset", "gate", "transfer", "movement", "measurement"]
    labels = {
        "initialize_plus": ("Prep +", "prep", "初态制备 + SE"),
        "initialize_plus/canonicalize": ("Corr +", "correct", "初态修正"),
        "raw_t_postselection": ("Raw T", "raw", "Raw T + 三轮 SE / 后选择"),
        "raw_t_postselection/canonicalize": ("Corr T", "correct", "Raw T 修正"),
        "logical_s": ("S+SE", "s", "S + SE"),
        "logical_x": ("X", "correct", "逻辑 X"),
        "logical_mx": ("MX", "measure", "测量 MX"),
        "logical_mz": ("MZ", "measure", "测量 MZ"),
        "transversal_cnot": ("CNOT", "cnot", "CNOT"),
    }
    growth_legend = ""
    if summary["distance"] > 3:
        distance = summary["distance"]
        growth_rounds = summary["growth_rounds_per_accepted_input"]
        growth_label = f"通过后扩码至 d{distance} + {growth_rounds} 轮普通 SE + 修正"
        labels["raw_t_postselection/canonicalize"] = (
            f"Grow d{distance}",
            "growth",
            growth_label,
        )
        growth_legend = (
            '<span class="key"><i style="--c:var(--growth)"></i>'
            f"{html.escape(growth_label)}</span>"
        )
    outputs: list[tuple[float, int, int]] = []
    rejections: list[tuple[float, int]] = []
    final_rejections: list[tuple[float, int]] = []
    for f in range(count):
        factory = case["factories"][f"factory{f}"]
        for i, c in enumerate(factory["production_cycles"]):
            outputs.append((c["delivery"]["deliverable_at_us"], f, i + 1))
        for m in factory["milestones"]:
            if m["kind"] == "preparation_decision" and m.get("accepted") is False:
                rejections.append((m["at_us"], f))
            if m["kind"] == "batch_decision" and m.get("accepted") is False:
                final_rejections.append((m["at_us"], f))
    finished = {
        f: case["factories"][f"factory{f}"].get("completed_at_us")
        if case["factories"][f"factory{f}"].get("completed_at_us") is not None
        else max((t for t, ff, _ in outputs if f == ff), default=total)
        for f in range(count)
    }
    histories = {
        f: sorted(
            (
                m
                for m in case["factories"][f"factory{f}"]["milestones"]
                if m["kind"] == "line_state_changed"
            ),
            key=lambda m: m["at_us"],
        )
        for f in range(count)
    }
    state_cursors, states = [0] * count, ["ready"] * count
    factory_lanes: list[list[Any]] = [[] for _ in range(count)]
    accounting: list[Counter[str]] = [Counter() for _ in range(count)]
    aod: list[Any] = []
    data_waves: list[Any] = []
    table_rows: list[str] = []
    for wi, w in enumerate(waves):
        ids = w["invocations"]
        member_index = {v: i for i, v in enumerate(ids)}
        component = calls[ids[0]]["component_id"]
        roles = []
        for f in range(count):
            while (
                state_cursors[f] < len(histories[f])
                and histories[f][state_cursors[f]]["at_us"] <= w["start_us"]
            ):
                states[f] = histories[f][state_cursors[f]]["state"]
                state_cursors[f] += 1
            members = [calls[k] for k in ids if calls[k]["factory_id"] == f"factory{f}"]
            roles.append(
                "; ".join("→".join(m["participant_roles"]) for m in members) or "—"
            )
            segments = []
            if members:
                end = max(m["end_us"] for m in members)
                segments.append((w["start_us"], end, component, "component"))
                if w["end_us"] - end > 1e-7:
                    segments.append((end, w["end_us"], "同步", "sync"))
            else:
                status = (
                    "done"
                    if w["start_us"] >= finished[f] - 1e-7
                    else "barrier"
                    if states[f] == "waiting_peers"
                    else "wait"
                )
                segments.append(
                    (
                        w["start_us"],
                        w["end_us"],
                        {"done": "已完成", "barrier": "阶段同步", "wait": "等待"}[
                            status
                        ],
                        status,
                    )
                )
            for start, end, comp, kind in segments:
                factory_lanes[f].append((start, end, comp, kind, wi))
                accounting[f][kind] += end - start
        for s in w["stage_schedule"]:
            if "aod:transport" not in s["resources"]:
                continue
            owners = tuple(
                sorted({factory_indices[calls[k]["factory_id"]] for k in s["members"]})
            )
            interval = (
                w["start_us"] + s["start_us"],
                w["start_us"] + s["end_us"],
                owners,
                wi,
            )
            if (
                aod
                and abs(aod[-1][1] - interval[0]) < 1e-7
                and aod[-1][2:] == interval[2:]
            ):
                aod[-1] = (aod[-1][0], interval[1], owners, wi)
            else:
                aod.append(interval)

        def mask(names: list[str]) -> int:
            return sum(1 << resources.index(r) for r in names)

        data_waves.append(
            [
                w["start_us"],
                w["end_us"],
                components.index(component),
                [
                    [
                        k,
                        calls[k]["participant_roles"],
                        calls[k]["end_us"] - w["start_us"],
                    ]
                    for k in ids
                ],
                [
                    [
                        s["start_us"],
                        s["end_us"],
                        phase_index[s["phase"]],
                        categories.index(s["category"]),
                        mask(s["resources"]),
                        [member_index[m] for m in s["members"]],
                    ]
                    for s in w["stage_schedule"]
                ],
                [
                    [
                        q["start_us"],
                        q["end_us"],
                        member_index[q["member"]],
                        mask(q["resources"]),
                    ]
                    for q in w["stage_waits"]
                ],
            ]
        )
        role_cells = "".join("<td>" + html.escape(role) + "</td>" for role in roles)
        aod_time = w["resource_busy_us"].get("aod:transport", 0)
        table_rows.append(
            '<tr><td><button type="button" class="wave-button" '
            f'data-wave="{wi}">{wi + 1}</button></td>'
            f"<td>{html.escape(labels[component][2])}</td>"
            f'<td class="num">{w["start_us"]:,.3f}</td>'
            f'<td class="num">{w["end_us"]:,.3f}</td>'
            f'<td class="num">{w["end_us"] - w["start_us"]:,.3f}</td>'
            f'{role_cells}<td class="num">{aod_time:,.3f}</td></tr>'
        )

    for f, lane in enumerate(factory_lanes):
        assert abs(lane[0][0]) < 1e-8 and abs(lane[-1][1] - total) < 1e-8
        assert all(abs(a[1] - b[0]) < 1e-7 for a, b in pairwise(lane))
        assert abs(sum(accounting[f].values()) - total) < 1e-7
    assert all(a[1] <= b[0] + 1e-7 for a, b in pairwise(aod))
    if (
        len(outputs) != summary["accepted_outputs"]
        or len(rejections) != summary["raw_rejections"]
    ):
        raise ValueError("SCHEDULE_EVENT_COUNTS_MISMATCH")

    def render_strip(start: float, end: float, index: int) -> str:
        """Show a contiguous 50 ms interval with factory and resource lanes."""
        left, right, width = 100, 1180, 1200

        def x(t: float) -> float:
            return left + (t - start) / 50000 * (right - left)

        clip_end = x(end)
        aod_y = 45 + count * 53
        bottom = aod_y + 19
        height = bottom + 38
        pieces = [
            (
                '<div class="chart-wrap"><svg class="timeline" '
                f'viewBox="0 0 {width} {height}" role="img" '
                f'aria-label="完整调度 {start / 1000:g} 到 {end / 1000:.3f} ms">'
                f'<defs><pattern id="sync{index}" width="6" height="6" '
                'patternUnits="userSpaceOnUse">'
                '<rect width="6" height="6" fill="var(--sync)"/>'
                '<path d="M0,6 L6,0" stroke="#8795a4" stroke-width=".8"/>'
                "</pattern></defs>"
            )
        ]
        pieces.append(
            '<text x="0" y="17" font-weight="600">'
            f"{start / 1000:g}–{end / 1000:.3f} ms</text>"
        )
        for tick in range(int(start), int(end) + 1, 10000):
            xp = x(tick)
            pieces.append(
                f'<line class="grid" x1="{xp:.3f}" x2="{xp:.3f}" '
                f'y1="28" y2="{bottom}"/>'
                f'<text class="tick" x="{xp:.3f}" y="{bottom + 21}" '
                f'text-anchor="middle">{tick / 1000:g}</text>'
            )
        if end % 10000:
            pieces.append(
                f'<text class="tick" x="{clip_end:.3f}" y="{bottom + 21}" '
                f'text-anchor="end">{end / 1000:.3f}</text>'
            )
        for f in range(count):
            y = 44 + f * 53
            pieces.append(
                f'<text x="85" y="{y + 19}" text-anchor="end">工厂 {f}</text>'
            )
            for s, e, comp, kind, wi in factory_lanes[f]:
                if e <= start or s >= end:
                    continue
                xx, ww = x(max(s, start)), x(min(e, end)) - x(max(s, start))
                if kind == "component":
                    label, color, title = labels[comp]
                    fill = f"var(--{color})"
                else:
                    label, title = comp, comp
                    fill = f"url(#sync{index})" if kind == "sync" else f"var(--{kind})"
                desc = f"工厂 {f} · {title} · {s:,.3f}–{e:,.3f} μs · 波次 {wi + 1}"
                pieces.append(
                    '<g class="bar" role="button" tabindex="0" '
                    f'data-wave="{wi}" data-state="{kind}" '
                    f'aria-label="{html.escape(desc)}">'
                    f'<title>{html.escape(desc)}</title><rect x="{xx:.3f}" '
                    f'y="{y}" width="{ww:.3f}" height="29" fill="{fill}"/>'
                )
                if ww > len(label) * 8.4 + 9:
                    pieces.append(
                        f'<text x="{xx + ww / 2:.3f}" y="{y + 19}" '
                        f'text-anchor="middle">{label}</text>'
                    )
                pieces.append("</g>")
            for t, ff in rejections:
                if f == ff and start <= t < end:
                    xp = x(t)
                    pieces.append(
                        f'<line class="reject" x1="{xp:.3f}" x2="{xp:.3f}" '
                        f'y1="{y + 29}" y2="{y + 36}">'
                        f"<title>工厂 {f} raw 拒绝 · {t:,.3f} μs</title></line>"
                    )
            for t, ff, cycle in outputs:
                if f == ff and start < t <= end:
                    xp = x(t)
                    label = f"输出 {cycle} · {t / 1000:.3f} ms"
                    anchor = "end" if xp > clip_end - 170 else "start"
                    tx = xp - 6 if anchor == "end" else xp + 6
                    pieces.append(
                        f'<path class="out" d="M{xp:.3f},{y - 5} '
                        'l4,4 -4,4 -4,-4 Z"/>'
                        f'<text x="{tx:.3f}" y="{y - 5}" '
                        f'text-anchor="{anchor}">{label}</text>'
                    )
            for t, ff in final_rejections:
                if f == ff and start < t <= end:
                    xp = x(t)
                    pieces.append(
                        f'<text x="{xp:.3f}" y="{y + 32}" fill="#b91c1c">'
                        f"<title>工厂 {f} 最终拒绝：本轮无输出 · {t:,.3f} μs</title>×</text>"
                    )
        y = aod_y
        pieces.append(
            f'<text x="85" y="{y + 13}" text-anchor="end">单 AOD</text>'
            f'<rect x="{left}" y="{y}" width="{clip_end - left:.3f}" '
            'height="18" fill="var(--wait)"/>'
        )
        for s, e, owners, wi in aod:
            if e <= start or s >= end:
                continue
            xx, ww = x(max(s, start)), x(min(e, end)) - x(max(s, start))
            color = "ab" if len(owners) > 1 else "a" + str(owners[0])
            who = "+".join(f"F{f}" for f in owners)
            component_label = labels[
                calls[waves[wi]["invocations"][0]]["component_id"]
            ][2]
            desc = f"AOD · {who} · {component_label} · {s:,.3f}–{e:,.3f} μs"
            pieces.append(
                f'<g class="bar" data-wave="{wi}">'
                f'<title>{html.escape(desc)}</title><rect x="{xx:.3f}" '
                f'y="{y}" width="{ww:.3f}" height="18" fill="var(--{color})"/></g>'
            )
        pieces.append("</svg></div>")
        return "".join(pieces)

    schedule = "".join(
        render_strip(s, min(s + 50000, total), i)
        for i, s in enumerate(range(0, math.ceil(total), 50000))
    )
    output_markup = "".join(
        f"<span>工厂 {f} · 第 {cycle} 个输出：<strong>{t / 1000:.3f} ms</strong></span>"
        for t, f, cycle in sorted(outputs)
    )
    if summary.get("production_basis") == "production_rounds":
        output_markup += "<table><tr><th>工厂</th><th>生产轮</th><th>开始 ms</th><th>结束 ms</th><th>结果</th></tr>"
        for f in range(count):
            for row in case["factories"][f"factory{f}"].get("production_rounds", []):
                result_label = "已交付" if row["accepted"] else "最终拒绝，本轮无输出"
                output_markup += (
                    f"<tr><td>{f}</td><td>{row['round'] + 1}</td>"
                    f"<td>{row['started_at_us'] / 1000:.3f}</td>"
                    f"<td>{row['completed_at_us'] / 1000:.3f}</td><td>{result_label}</td></tr>"
                )
        output_markup += "</table>"
    accounting_markup = (
        '<table><thead><tr><th>工厂</th><th class="num">组件流程 ms</th>'
        '<th class="num">尾部同步 ms</th><th class="num">阶段同步 ms</th>'
        '<th class="num">等待调度 ms</th>'
        '<th class="num">完成后 ms</th><th class="num">合计 ms</th>'
        "</tr></thead><tbody>"
    )
    for f in range(count):
        accounting_markup += (
            f"<tr><td>工厂 {f}</td>"
            + "".join(
                f'<td class="num">{accounting[f][k] / 1000:.3f}</td>'
                for k in ("component", "sync", "barrier", "wait", "done")
            )
            + f'<td class="num">{total / 1000:.3f}</td></tr>'
        )
    accounting_markup += "</tbody></table>"
    wave_table = (
        '<table class="wave-table"><thead><tr><th>波次</th><th>组件</th>'
        '<th class="num">开始 μs</th><th class="num">结束 μs</th>'
        '<th class="num">时长 μs</th>'
        + "".join(f"<th>工厂 {f} 码块</th>" for f in range(count))
        + '<th class="num">AOD 占用 μs</th></tr></thead><tbody>'
        + "".join(table_rows)
        + "</tbody></table>"
    )
    data = json.dumps(
        {
            "components": components,
            "component_labels": {name: label[2] for name, label in labels.items()},
            "phases": phase_names,
            "resources": resources,
            "categories": categories,
            "waves": data_waves,
        },
        separators=(",", ":"),
        ensure_ascii=False,
    ).replace("<", "\\u003c")
    comparison = _comparison(summary, baseline_case)
    policy_names = {"asynchronous": "异步策略", "synchronous": "同步策略"}
    policy_name = summary.get("strategy", {}).get("name", "asynchronous")
    policy_label = policy_names.get(policy_name, policy_name)
    meta = (
        f"<span><strong>{html.escape(policy_label)}</strong></span>"
        f"<span><strong>d = {summary['distance']} · N = {count} · "
        f"seed = {summary['seed']}</strong></span>"
        f"<span>总时间 <strong>{total / 1000:.3f} ms</strong></span>"
        f"<span><strong>{len(outputs)}</strong> 个接受输出</span>"
        f"<span><strong>{summary['allocated_atoms']}</strong> 个驻留原子</span>"
    )
    aod_legend = "<span>单 AOD：</span>" + "".join(
        f'<span class="key"><i style="--c:var(--a{f})"></i>仅工厂 {f}</span>'
        for f in range(count)
    )
    if count > 1:
        owner_label = "两厂" if count == 2 else "多厂"
        aod_legend += (
            '<span class="key"><i style="--c:var(--ab)"></i>'
            f"{owner_label}共用同一命令</span>"
        )
    aod_legend += (
        "<span>◆ 接受输出</span><span>│ raw 拒绝</span><span>× 最终拒绝</span>"
    )
    comparison_markup = ""
    if comparison is not None:
        baseline_label = policy_names.get(
            comparison["baseline_strategy"], comparison["baseline_strategy"]
        )
        current_label = policy_names.get(
            comparison["current_strategy"], comparison["current_strategy"]
        )
        baseline_label += " / " + comparison["baseline_placement"]
        current_label += " / " + comparison["current_placement"]
        direction = "减少" if comparison["reduction_percent"] >= 0 else "增加"
        comparison_markup = (
            '<div class="note">相同 d、N、seed、生产口径和采样输出数：'
            f"{html.escape(baseline_label)} "
            f"<strong>{comparison['before_us'] / 1000:.3f} ms</strong> → "
            f"{html.escape(current_label)} "
            f"<strong>{comparison['after_us'] / 1000:.3f} ms</strong>；"
            f"{direction} "
            f"<strong>{abs(comparison['reduction_percent']):.2f}%</strong>。"
            "比较的是完整有限批次耗时。</div>"
        )
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    page = Path(__file__).with_suffix(".html").read_text(encoding="utf-8")
    values = {
        "__TITLE__": f"d{summary['distance']} N{count}",
        "__INTRO__": (
            f"{count} 个工厂，共享一个 AOD；每厂完成 {summary['cycles_per_factory']} 轮生产，"
            "成功立即交付，失败本轮无输出；不等待补齐成功输出数。外部注入成本由理想 sink 排除。"
            if summary.get("production_basis") == "production_rounds"
            else f"{count} 个工厂，共享一个 AOD；从启动一直到各自交付 "
            f"{summary['cycles_per_factory']} 个接受输出。"
        ),
        "__META__": meta,
        "__LAYOUT__": _layout_markup(run),
        "__AOD_LEGEND__": aod_legend,
        "__GROWTH_LEGEND__": growth_legend,
        "__AOD_COLORS__": "".join(
            f"--a{f}:hsl({(210 + f * 137.508) % 360:.3f} 52% 42%);"
            for f in range(2, count)
        ),
        "__SCHEDULE__": schedule,
        "__OUTPUTS__": output_markup,
        "__OUTPUT_COUNT__": str(len(outputs)),
        "__ACCOUNTING__": accounting_markup,
        "__WAVE_TABLE__": wave_table,
        "__WAVE_COUNT__": str(len(waves)),
        "__CALL_COUNT__": str(len(calls)),
        "__TOTAL_MS__": f"{total / 1000:.3f}",
        "__RAW_REJECTIONS__": str(summary["raw_rejections"]),
        "__FINAL_REJECTIONS__": str(summary["factory_rejections"]),
        "__RAW_PROBABILITY__": format(summary["raw_acceptance_parameter"], ".16g"),
        "__SOURCE_LABEL__": html.escape(source.name),
        "__SOURCE_HASH__": source_hash,
        "__DATA__": data,
        "__COMPARISON__": comparison_markup,
    }
    for marker, value in values.items():
        if marker not in page:
            raise ValueError(f"MISSING_REPORT_PLACEHOLDER: {marker}")
        page = page.replace(marker, value)
    with target.open("x", encoding="utf-8") as stream:
        stream.write(page)
    return {
        "output": str(target),
        "bytes": target.stat().st_size,
        "windows": math.ceil(total / 50000),
        "waves": len(waves),
        "calls": len(calls),
        "phases": sum(len(w["stage_schedule"]) for w in waves),
        "aod_display_spans": len(aod),
        "outputs": len(outputs),
        "raw_rejections": len(rejections),
        "source_sha256": source_hash,
        "comparison": comparison,
        "factory_time_us": [dict(a) for a in accounting],
    }


def main() -> int:
    """Write a standalone report from existing files, never rerun the factory."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline-case", type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            render_schedule(args.case, args.output, baseline_case=args.baseline_case)
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
