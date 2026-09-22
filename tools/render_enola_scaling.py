"""Render saved native Enola/QMAP scaling runs without rerunning either compiler.

The figures compare declared *models*.  They are not local Env execution results.
Failed runs remain visible and never contribute a synthetic zero to a mean.
"""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import html
import io
import json
import math
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


METHODS = ("enola", "qmap")
LABELS = {"enola": "Enola native", "qmap": "QMAP IDS native"}
COLORS = {"enola": "#196D91", "qmap": "#DD7637"}
LOSS_KEYS = ("two_qubit", "transfer", "decoherence")
LOSS_LABELS = ("Two-qubit / spectator loss", "Transfer loss", "Decoherence loss")
LOSS_COLORS = ("#5B86B2", "#E1A046", "#A9B9AC")


def number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def mean_std(values: list[float]) -> tuple[float, float | None]:
    return statistics.mean(values), statistics.stdev(values) if len(values) > 1 else None


def normalise(raw: dict, path: Path, root: Path) -> dict:
    """Keep missing measurements missing; fidelity underflow is not failure."""
    score = raw.get("score") or raw.get("metrics") or raw
    losses = score.get("losses") or {}
    parsed_losses = {key: number(losses.get(key)) for key in LOSS_KEYS}
    losses_present = all(value is not None and value >= 0 for value in parsed_losses.values())
    valid = score.get("model_valid", raw.get("model_valid")) is True
    status = raw.get("status", "unknown")
    n = int(raw.get("n", path.parent.parent.name.split("_")[0][1:]))
    graph_id = raw.get("graph_id", path.parent.parent.name.split("_g")[-1])
    method = str(raw.get("method", path.parent.name)).lower()
    warnings = []
    if status == "completed" and not valid:
        warnings.append("model_valid 未通过")
    if status == "completed" and not losses_present:
        warnings.append("损失分量缺失或非有限/负数")
    if status == "completed" and losses_present:
        supplied_log = number(score.get("log_fidelity"))
        if supplied_log is not None and not math.isclose(
            -supplied_log, sum(parsed_losses.values()), rel_tol=1e-7, abs_tol=1e-8
        ):
            warnings.append("分量总和与 -log_fidelity 不一致；排除损失对照")
            losses_present = False
    error = raw.get("error") or raw.get("failure_reason") or raw.get("reason") or raw.get("message") or ""
    if not isinstance(error, str):
        error = json.dumps(error, ensure_ascii=False)
    row = {
        "n": n,
        "graph_id": str(graph_id),
        "method": method,
        "status": status,
        "model_valid": valid,
        "loss_eligible": status == "completed" and valid and losses_present,
        "native_compile_seconds": number(raw.get("native_compile_seconds")
                                         if raw.get("native_compile_seconds") is not None
                                         else raw.get("compile_seconds")),
        "process_wall_seconds": number(raw.get("process_wall_seconds")),
        "peak_working_set_bytes": number(raw.get("peak_working_set_bytes")),
        "losses": parsed_losses,
        "total_loss": sum(parsed_losses.values()) if losses_present else None,
        "log_fidelity": number(score.get("log_fidelity")),
        "fidelity": number(score.get("fidelity")),
        "execution_us": number(score.get("execution_us")),
        "pulses": number(score.get("pulses")),
        "transfers": number(score.get("transfers")),
        "spectator_excitations": number(score.get("spectator_excitations")),
        "max_parallel_cz": number(score.get("max_parallel_cz", raw.get("max_parallel_cz"))),
        "source": path.relative_to(root).as_posix(),
        "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "warnings": warnings,
        "error": error,
        "checks": raw.get("checks", raw.get("audit", score.get("checks", {}))),
        "phases": raw.get("phases", {}),
        "full_parity": raw.get("full_parity"),
        "model_exposure": score.get("exposure"),
        "model_status": score.get("model_status"),
        "invalid_idle_atom_count": len(score.get("invalid_idle_atom_ids", [])),
        "error_tail": raw.get("error_tail", ""),
    }
    idle = score.get("idle_us")
    if isinstance(idle, list) and idle:
        finite_idle = [number(value) for value in idle]
        if all(value is not None for value in finite_idle):
            row["idle_us_summary"] = {
                "count": len(idle), "minimum": min(finite_idle),
                "mean": statistics.mean(finite_idle), "maximum": max(finite_idle),
            }
    return row


def load_results(root: Path) -> list[dict]:
    rows = []
    keys = set()
    for path in sorted(root.glob("n*_g*/*/result.json")):
        row = normalise(json.loads(path.read_text(encoding="utf-8")), path, root)
        if row["method"] not in METHODS:
            continue
        key = (row["n"], row["graph_id"], row["method"])
        if key in keys:
            raise ValueError(f"Duplicate result: {key}")
        keys.add(key)
        rows.append(row)
    return sorted(rows, key=lambda row: (row["n"], row["graph_id"], row["method"]))


def aggregate(rows: list[dict]) -> dict:
    by_case: dict[tuple[int, str], dict[str, dict]] = defaultdict(dict)
    for row in rows:
        by_case[row["n"], row["graph_id"]][row["method"]] = row
    paired = defaultdict(list)
    excluded = []
    for (n, graph_id), methods in sorted(by_case.items()):
        if all(method in methods and methods[method]["loss_eligible"] for method in METHODS):
            paired[n].append(methods)
        else:
            excluded.append({"n": n, "graph_id": graph_id, "reason": {
                method: methods.get(method, {}).get("status", "missing")
                + (" / model invalid" if method in methods and not methods[method]["loss_eligible"]
                   and methods[method]["status"] == "completed" else "") for method in METHODS
            }})
    groups = []
    for n, cases in sorted(paired.items()):
        for method in METHODS:
            selected = [case[method] for case in cases]
            total_mean, total_std = mean_std([row["total_loss"] for row in selected])
            groups.append({
                "n": n, "method": method, "count": len(selected),
                "graph_ids": [row["graph_id"] for row in selected],
                "losses_mean": {key: statistics.mean(row["losses"][key] for row in selected)
                                for key in LOSS_KEYS},
                "total_loss_mean": total_mean, "total_loss_std": total_std,
                "per_qubit_loss_mean": total_mean / n,
                "per_qubit_loss_std": total_std / n if total_std is not None else None,
            })
    return {"paired_loss_groups": groups, "excluded_pairs": excluded}


def decorate(ax, *, logx=False, logy=False):
    ax.set_facecolor("#FFFFFF")
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="both", alpha=.16, linewidth=.7)
    ax.set_axisbelow(True)
    if logx:
        ax.set_xscale("log")
    if logy:
        ax.set_yscale("log")


def save_figure(fig, root: Path, stem: str) -> str:
    fig.savefig(root / f"{stem}.png", dpi=180, bbox_inches="tight", facecolor="white")
    fig.savefig(root / f"{stem}.svg", bbox_inches="tight", facecolor="white")
    fig.savefig(root / f"{stem}.pdf", bbox_inches="tight", facecolor="white")
    data = io.BytesIO()
    fig.savefig(data, format="svg", bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return base64.b64encode(data.getvalue()).decode("ascii")


def loss_figure(aggregates: dict, sizes: list[int]):
    fig, axes = plt.subplots(1, 2, figsize=(13.2, 4.5), layout="constrained")
    groups = {(g["n"], g["method"]): g for g in aggregates["paired_loss_groups"]}
    width = .34
    for column, (ax, normalised) in enumerate(zip(axes, (False, True))):
        for mi, method in enumerate(METHODS):
            for xi, n in enumerate(sizes):
                group = groups.get((n, method))
                xpos = xi + (mi - .5) * width
                if group is None:
                    ax.annotate("N/A", (xpos, 0), xytext=(0, 5), textcoords="offset points",
                                rotation=90, ha="center", va="bottom", color="#7A7F87", fontsize=8)
                    continue
                bottom = 0.
                for index, (key, color) in enumerate(zip(LOSS_KEYS, LOSS_COLORS)):
                    value = group["losses_mean"][key] / (n if normalised else 1)
                    ax.bar(xpos, value, width * .90, bottom=bottom, color=color,
                           edgecolor="white", linewidth=.45,
                           hatch="///" if method == "qmap" else None,
                           label=LOSS_LABELS[index] if mi == 0 and xi == 0 else None)
                    bottom += value
                std = group["per_qubit_loss_std" if normalised else "total_loss_std"]
                if std is not None:
                    ax.errorbar(xpos, bottom, yerr=std, color="#283646", fmt="none", capsize=3, linewidth=1)
        ax.set_xticks(range(len(sizes)), [str(n) for n in sizes])
        ax.set_xlabel("Number of qubits")
        ax.set_ylabel("Mean -ln(F) / qubit" if normalised else "Mean -ln(F)")
        ax.set_title("(b) Loss per qubit" if normalised else "(a) Figure 2-style loss decomposition", loc="left", pad=14)
        decorate(ax)
        ax.set_ylim(bottom=0)
    from matplotlib.patches import Patch
    fig.legend([Patch(facecolor=c) for c in LOSS_COLORS], LOSS_LABELS,
               loc="outside lower center", ncol=3, frameon=False, fontsize=9)
    fig.suptitle("Paired graph instances only | Left bar: Enola; hatched right bar: QMAP IDS\n"
                 "Distinct hardware models; error bars: sample SD of total loss (when repetitions > 1)",
                 fontsize=11, color="#394E61")
    return fig


def runtime_figure(rows: list[dict], sizes: list[int]):
    fig, axes = plt.subplots(1, 2, figsize=(13.2, 4.5), layout="constrained")
    for ax, key, title in zip(axes, ("native_compile_seconds", "process_wall_seconds"),
                              ("(a) Native compiler time", "(b) Whole worker process wall time")):
        for method in METHODS:
            selected = [row for row in rows if row["method"] == method and row["status"] == "completed"
                        and row[key] is not None and row[key] > 0]
            x, y, errors = [], [], []
            for n in sizes:
                values = [row[key] for row in selected if row["n"] == n]
                if values:
                    avg, std = mean_std(values)
                    x.append(n); y.append(avg); errors.append(std or 0.)
                    ax.scatter([n] * len(values), values, color=COLORS[method], s=20, alpha=.3)
            if x:
                ax.errorbar(x, y, yerr=errors, fmt="o-", color=COLORS[method], label=LABELS[method],
                            capsize=3, markersize=5, linewidth=1.6)
            if key == "process_wall_seconds":
                failed = [row for row in rows if row["method"] == method and row["status"] != "completed"
                          and row[key] is not None and row[key] > 0]
                for row in failed:
                    ax.scatter(row["n"], row[key], marker="x", s=58, color=COLORS[method], zorder=4)
                    offset = (-4, -16) if method == "enola" else (4, 5)
                    label = ("E: " if method == "enola" else "Q: ") + row["status"]
                    ax.annotate(label, (row["n"], row[key]), xytext=offset,
                                ha="right" if method == "enola" else "left",
                                textcoords="offset points", fontsize=7, color=COLORS[method])
        decorate(ax, logx=True, logy=True)
        ax.set_xticks(sizes, [str(n) for n in sizes], rotation=25)
        ax.set_xlabel("Number of qubits")
        ax.set_ylabel("Seconds (log scale)")
        ax.set_title(title, loc="left", pad=14)
        handles, labels = ax.get_legend_handles_labels()
        if handles:
            ax.legend(handles, labels, frameon=False, fontsize=9)
    fig.suptitle("Completed-run means; SD when repeated | Crosses are terminated runs, not successful runtimes\n"
                 "Native time excludes process startup, later scoring, and local Env execution",
                 fontsize=11, color="#394E61")
    return fig


def diagnostics_figure(rows: list[dict], sizes: list[int]):
    fig, axes = plt.subplots(1, 3, figsize=(13.2, 3.7), layout="constrained")
    for ax, key, title in zip(axes, ("pulses", "transfers", "execution_us"),
                              ("Rydberg pulses", "Atom transfer events", "Model execution time (ms)")):
        for method in METHODS:
            x, y = [], []
            for n in sizes:
                values = [row[key] for row in rows if row["n"] == n and row["method"] == method
                          and row["status"] == "completed" and row[key] is not None and row[key] > 0]
                if values:
                    x.append(n); y.append(statistics.mean(values) / (1000 if key == "execution_us" else 1))
            if x:
                ax.plot(x, y, "o-", color=COLORS[method], markersize=4, label=LABELS[method])
        decorate(ax, logx=True, logy=True)
        ax.set_xticks(sizes, [str(n) for n in sizes], rotation=40)
        ax.set_xlabel("Number of qubits")
        ax.set_title(title, loc="left", pad=12)
        handles, labels = ax.get_legend_handles_labels()
        if handles:
            ax.legend(handles, labels, frameon=False, fontsize=8)
    fig.suptitle("Completed native outputs, including runs with invalid fidelity models\n"
                 "Different hardware and terminal-storage contracts", fontsize=11)
    return fig


def fmt(value: Any, digits=4) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.{digits}g}"
    return html.escape(str(value))


def write_html(root: Path, rows: list[dict], aggregates: dict, figures: dict, manifest: dict):
    completed = sum(row["status"] == "completed" for row in rows)
    pairs = sum(group["count"] for group in aggregates["paired_loss_groups"] if group["method"] == "enola")
    invalid = sum(row["status"] == "completed" and not row["loss_eligible"] for row in rows)
    body = []
    for row in rows:
        badge = "ok" if row["loss_eligible"] else "bad"
        checks = json.dumps({key: row[key] for key in ("checks", "phases", "full_parity",
                            "model_exposure", "model_status", "invalid_idle_atom_count", "error_tail")
                            if row[key]}, ensure_ascii=False, indent=2)
        notes = "；".join(row["warnings"] + ([row["error"]] if row["error"] else []))
        details = f'<details><summary>原始证据 / 检查</summary><p>{html.escape(notes) or "无额外警告"}</p>' \
                  f'<a href="{html.escape(row["source"])}">result.json</a><pre>{html.escape(checks)}</pre></details>'
        body.append("<tr>" + "".join(f"<td>{value}</td>" for value in (
            fmt(row["n"]), fmt(row["graph_id"]), LABELS[row["method"]],
            f'<span class="badge {badge}">{html.escape(row["status"])}</span>',
            "通过" if row["loss_eligible"] else "N/A",
            fmt(row["native_compile_seconds"]), fmt(row["process_wall_seconds"]),
            fmt(row["total_loss"] if row["loss_eligible"] else None),
            fmt(row["fidelity"] if row["loss_eligible"] else None),
            fmt(row["pulses"]), fmt(row["transfers"]),
            fmt(row["peak_working_set_bytes"] / 1024**3 if row["peak_working_set_bytes"] else None), details
        )) + "</tr>")
    paired_rows = []
    for group in aggregates["paired_loss_groups"]:
        paired_rows.append("<tr>" + "".join(f"<td>{fmt(v)}</td>" for v in (
            group["n"], LABELS[group["method"]], ", ".join(group["graph_ids"]), group["count"],
            group["total_loss_mean"], group["total_loss_std"], group["per_qubit_loss_mean"]
        )) + "</tr>")
    excluded = "".join(f'<li>{item["n"]} qubits / graph {html.escape(item["graph_id"])}：'
                       f'{html.escape(json.dumps(item["reason"], ensure_ascii=False))}</li>'
                       for item in aggregates["excluded_pairs"])
    images = []
    for stem, (title, note, image) in figures.items():
        images.append(f'<section><h2>{title}</h2><p>{note}</p><img src="data:image/svg+xml;base64,{image}" '
                      f'alt="{html.escape(title)}"><div class="downloads">导出：'
                      + " · ".join(f'<a href="{stem}.{ext}">{ext.upper()}</a>' for ext in ("png", "svg", "pdf"))
                      + "</div></section>")
    manifest_text = html.escape(json.dumps(manifest, ensure_ascii=False, indent=2))
    html_text = """<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Enola × QMAP IDS — 原生编译扩展实验</title><style>
:root{font-family:system-ui,"Microsoft YaHei",sans-serif;color:#233646;background:#f1f4f6;line-height:1.7}
*{box-sizing:border-box}body{margin:0}main{max-width:1480px;margin:auto;padding:32px 24px 64px}h1{font-size:clamp(25px,3vw,40px);line-height:1.3;margin:8px 0 18px}h2{font-size:22px;margin:0 0 10px}p{margin:8px 0 15px}.eyebrow{font-size:13px;letter-spacing:.14em;color:#416378}.lead{max-width:1020px;font-size:17px}.scope{background:#e5edf3;border-left:4px solid #2c7299;padding:16px 20px;margin:22px 0}.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:24px 0}.card,section{background:white;border:1px solid #dbe3e9;border-radius:12px}.card{padding:17px 22px}.number{font-size:30px;font-weight:700;display:block}.muted{color:#62717f;font-size:13px}section{padding:25px;margin:20px 0;overflow:hidden}img{display:block;width:100%;height:auto}.downloads{font-size:13px;text-align:right}a{color:#176d96;text-decoration-thickness:1px;text-underline-offset:3px}.table-scroll{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:13px;text-align:left}th{white-space:nowrap;background:#edf3f6;color:#3c5669}th,td{padding:11px 13px;border-bottom:1px solid #e3e9ed;vertical-align:top}td{font-variant-numeric:tabular-nums}td:nth-child(-n+3){white-space:nowrap}.badge{border-radius:20px;padding:3px 8px;font-size:12px}.ok{background:#dceee5;color:#235e47}.bad{background:#fbe9dc;color:#8e491f}details{min-width:180px}summary{cursor:pointer;color:#326483}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:420px;overflow:auto;background:#f5f7f9;padding:14px;font-size:12px}.notice{color:#81531e;background:#faf1dd;border-radius:8px;padding:13px 17px}li{margin:7px 0}.fine{font-size:13px;color:#647482}@media(max-width:700px){main{padding:22px 12px}section{padding:16px}.cards{grid-template-columns:repeat(2,1fr)}.card{padding:12px}.number{font-size:25px}}
</style><main><header><div class="eyebrow">NATIVE COMPILATION · SCALING STUDY</div>
<h1>Enola × QMAP IDS<br>Figure 2 风格的规模扩展实验</h1>
<p class="lead">固定同一份随机图输入，分别运行原生编译器，再从各自指令计算声明模型下的损失。这里检验规模、编译耗时和模型成本；不将两套硬件模型的差异归因于编译算法优劣。</p>
<div class="scope"><strong>证据边界：</strong>仅作者原生输出与指令级审计，不经过本地 <code>NeutralAtomEnv</code>，没有连续路径碰撞、空 AOD 交点扫掠或实验量子态验收。QMAP 的终态为稳定 SZ；Enola 为稳定 SLM，位置不限于原处；两者都计入各自的末尾收尾操作。它们不是同物理平台、同绝对终态的端到端胜负对照。</div>
<div class="notice"><strong>平台随规模的变化不同：</strong>QMAP 使用固定的作者平台，EZ 有 340 对 CZ 位置，90% 填充上限对应最多 306 对；Enola 的阵列边长按 <code>max(16, ceil(sqrt(n)) + 4)</code> 增长。因此大规模下的并行层数、模型时间和损失同时受容量策略影响，不能直接解释成纯编译算法排名。</div></header>
"""
    html_text += '<div class="cards">' + "".join(
        f'<div class="card"><span class="number">{value}</span><span class="muted">{label}</span></div>'
        for value, label in ((len(rows), "已落盘的运行结果"), (completed, "完成原生编译"),
                             (pairs, "双方法有效配对图"), (len(rows) - completed, "超时 / 失败 / 资源终止"))) + "</div>"
    html_text += f'<p class="fine">完成但损失模型不可用：{invalid} 份。尚未落盘的运行不算失败。单样本不绘误差棒，也不宣称统计显著性。</p>'
    html_text += "".join(images)
    diagnosis_path = root / "scheduling-diagnosis.json"
    if diagnosis_path.exists():
        diagnosis = json.loads(diagnosis_path.read_text(encoding="utf-8"))
        html_text += '<section><h2>单独核查调度层：可交换 CZ 的重排空间</h2><p>原始 QMAP ASAP 按输入顺序分层；Enola 边着色利用 CZ 可交换性。下表只重算门层，没有把重排后的线路重新做落点或路径编译，因此不能作为运动时间或保真度的改进结果。</p><div class="table-scroll"><table><thead><tr><th>原子数</th><th>原顺序 ASAP</th><th>边着色，无容量限制</th><th>重排后 ASAP，306 对上限</th></tr></thead><tbody>'
        for row in diagnosis["rows"]:
            html_text += '<tr>' + ''.join(f'<td>{fmt(row[key])}</td>' for key in (
                'n', 'original_order_asap_layers', 'edge_coloring_layers',
                'reordered_asap_layers_under_capacity306')) + '</tr>'
        html_text += '</tbody></table></div><p><a href="scheduling-diagnosis.json">调度核查原始记录</a></p></section>'
    html_text += ('<section><h2>读图规则与可复现范围</h2><ul>'
        '<li>Figure 2 风格柱图采用自然对数损失：<code>−ln F = L₂Q + Ltransfer + Ldecoherence</code>。'
        '先逐实例求损失再按配对图求均值；误差棒是总损失的样本标准差，不是分量标准差相加。</li>' \
        '<li>两方法必须在同一个规模与 graph_id 都完成且模型有效，才进入成对柱图。超时、缺失、失败和无效模型均保留为 N/A，不补零。'
        '完整 fidelity 在大规模下可能下溢到 0；只要有限的对数损失存在，就仍可分析，不能把 0 当成编译失败。</li>' \
        '<li>耗时图使用各方法所有完成样本，可能与配对损失样本数不同。原生计时与包含启动/导入等成本的进程墙钟分开展示；'
        '终止记录的叉号只表示用掉的墙钟，不能当作该实例的成功编译时间。</li>' \
        '<li>固定 seed / 单一随机图只是扩展试跑，不是原论文全部重复实验；没有复现 OLSQ-DPQA 的对照曲线，'
        '也不把旧的小规模物理结果拼接进新曲线。当前输入、参数、软件版本与每次检查以原始 manifest / result 为准。</li></ul>' \
        '<p>来源：<a href="https://arxiv.org/abs/2405.15095">Enola 论文</a> · '
        '<a href="https://github.com/UCLA-VAST/Enola">Enola 仓库</a> · '
        '<a href="https://github.com/munich-quantum-toolkit/qmap">MQT QMAP 仓库</a></p></section>')
    html_text += '<section><h2>配对统计</h2><div class="table-scroll"><table><thead><tr>' \
        '<th>原子数</th><th>方法</th><th>graph_id</th><th>配对数</th><th>平均 −ln F</th><th>样本 SD</th><th>每原子损失</th>' \
        '</tr></thead><tbody>' + "".join(paired_rows) + '</tbody></table></div>'
    if excluded:
        html_text += '<details><summary>未进入成对损失统计的案例</summary><ul>' + excluded + '</ul></details>'
    html_text += '</section><section><h2>逐次结果与原始证据</h2><div class="table-scroll"><table><thead><tr>' \
        '<th>原子数</th><th>图</th><th>方法</th><th>运行状态</th><th>损失模型</th><th>原生 / s</th><th>进程 / s</th>' \
        '<th>−ln F</th><th>F</th><th>脉冲</th><th>原子装卸</th><th>峰值 / GiB</th><th>审计</th>' \
        '</tr></thead><tbody>' + "".join(body) + '</tbody></table></div></section>'
    html_text += ('<section><h2>输入合同与下载</h2><p><a href="manifest.json">运行 manifest</a> · '
        '<a href="report-data.json">归一化统计 JSON</a> · <a href="results.csv">逐次结果 CSV</a></p>' \
        '<details><summary>显示完整 manifest</summary><pre>' + manifest_text + '</pre></details></section>')
    html_text += ('<p class="fine">图表和表格已嵌入本 HTML；离线打开可阅读。原始 JSON 与 PNG/SVG/PDF 下载链接依赖同目录文件。'
        '本页由 tools/render_enola_scaling.py 从保存结果生成，不会重新编译。</p></main></html>')
    (root / "index.html").write_text(html_text, encoding="utf-8")


def render(root: Path) -> dict:
    root = root.resolve()
    rows = load_results(root)
    if not rows:
        raise ValueError(f"No result.json files under {root}")
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    aggregates = aggregate(rows)
    sizes = sorted({row["n"] for row in rows})
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                         "axes.labelcolor": "#34485A", "text.color": "#233646",
                         "svg.fonttype": "none", "pdf.fonttype": 42})
    figures = {
        "loss-scaling": ("损失随规模的变化", "相同 graph_id 配对；斜纹柱为 QMAP IDS。右图按原子数归一化，用于观察系统规模效应。",
                         save_figure(loss_figure(aggregates, sizes), root, "loss-scaling")),
        "runtime-scaling": ("编译耗时与进程墙钟", "双对数坐标。成功点取均值；被终止的进程以叉号单独标出，原生耗时未产出时留空。",
                            save_figure(runtime_figure(rows, sizes), root, "runtime-scaling")),
        "operation-scaling": ("指令与执行模型诊断", "只使用原生编译完成结果；保真度模型失效时仍保留可统计的指令数量与时长。脉冲、装卸和模型时间共同解释损失来源；不是本地物理执行时长。",
                              save_figure(diagnostics_figure(rows, sizes), root, "operation-scaling")),
    }
    write_html(root, rows, aggregates, figures, manifest)
    report = {"schema": "enola-qmap-scaling-report/1", "generated_utc": datetime.now(timezone.utc).isoformat(),
              "scope": "native compiler outputs and declared scoring models; no local Env or continuous path validation",
              "rows": rows, **aggregates,
              "renderer_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (root / "report-data.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    fields = ["n", "graph_id", "method", "status", "model_valid", "loss_eligible", "native_compile_seconds",
              "process_wall_seconds", "peak_working_set_bytes", "total_loss", "log_fidelity", "fidelity",
              "execution_us", "pulses", "transfers", "spectator_excitations", "max_parallel_cz", "source", "error"]
    with (root / "results.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader(); writer.writerows(rows)
    return {"rows": len(rows), "paired_instances": sum(group["count"] for group in aggregates["paired_loss_groups"]
                                                       if group["method"] == "enola"),
            "html": str(root / "index.html")}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("artifacts/enola-scaling-20260922"))
    args = parser.parse_args()
    print(json.dumps(render(args.root), ensure_ascii=False))
