"""Compare saved two-level estimates; never run a model or compile a component."""

import argparse
import json
import os
from hashlib import sha256
from html import escape
from pathlib import Path
from typing import Any


def compare_level2_runs(
    asynchronous: dict[str, Any], synchronous: dict[str, Any]
) -> dict[str, Any]:
    """Require matched inputs/budgets and compare elapsed time and L2 starvation.

    Seeded event outcomes must agree for common identities, while extra producer
    rounds and retained surplus may differ. Times are finite-batch quantities.
    Incomplete cases or mismatched configuration/probabilities raise ValueError.
    """
    a, b = asynchronous["summary"], synchronous["summary"]
    fields = (
        "distance",
        "level1_factories",
        "level2_factories",
        "buffer_capacity",
        "seed",
        "level2_rounds",
        "production_basis",
        "experiment_model",
        "raw_acceptance_parameter",
        "placement_fingerprint",
        "allocated_atoms",
        "storage_footprint_um2",
        "protocol",
    )
    if any(run["case"]["status"] != "complete" for run in (asynchronous, synchronous)):
        raise ValueError("INCOMPLETE_LEVEL2_COMPARISON")
    if any(any(s["forbidden_work"].values()) for s in (a, b)):
        raise ValueError("FORBIDDEN_WORK_IN_LEVEL2_COMPARISON")
    if any(a[k] != b[k] for k in fields):
        raise ValueError("LEVEL2_COMPARISON_CONFIGURATION_MISMATCH")
    if (a["strategy"]["name"], b["strategy"]["name"]) != (
        "asynchronous",
        "synchronous",
    ):
        raise ValueError("LEVEL2_COMPARISON_REQUIRES_L1_ASYNC_THEN_SYNC")
    if a["component_reuse"]["catalog_sha256"] != b["component_reuse"]["catalog_sha256"]:
        raise ValueError("LEVEL2_COMPARISON_CATALOG_MISMATCH")
    events = [
        {
            json.dumps(e["occurrence"], sort_keys=True): (
                e["port_sha256"],
                e["outcome_key"],
                e["values"],
            )
            for e in run["case"]["events"]
        }
        for run in (asynchronous, synchronous)
    ]
    common = events[0].keys() & events[1].keys()
    if any(events[0][key] != events[1][key] for key in common):
        raise ValueError("LEVEL2_COMMON_SEEDED_EVENT_MISMATCH")
    measures = (
        "level2_supply_wait_us",
        "level2_completion_us",
        "makespan_us",
        "drain_tail_us",
        "delivery_time_us",
        "atom_us_per_accepted_output",
        "level1_rounds",
        "level1_outputs",
        "retained_surplus",
        "raw_attempts",
        "raw_rejections",
        "accepted_outputs",
    )
    differences = {}
    for key in measures:
        before, after = a[key], b[key]
        differences[key] = {
            "asynchronous": before,
            "synchronous": after,
            "sync_minus_async": after - before
            if before is not None and after is not None
            else None,
            "sync_reduction_percent": 100 * (before - after) / before
            if before and after is not None
            else None,
        }
    return {
        "status": "complete",
        "matched_configuration": {key: a[key] for key in fields},
        "differences": differences,
        "common_seeded_events": len(common),
        "async_only_events": len(events[0].keys() - events[1].keys()),
        "sync_only_events": len(events[1].keys() - events[0].keys()),
        "common_outcomes_equal": True,
        "steady_state_throughput": None,
    }


def main() -> int:
    """Write a compact comparison index linking both complete saved schedules."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asynchronous", type=Path, required=True)
    parser.add_argument("--synchronous", type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sources = (args.asynchronous.resolve(), args.synchronous.resolve())
    runs = [json.loads(p.read_text(encoding="utf-8")) for p in sources]
    result = compare_level2_runs(*runs)
    for path in sources:
        if not path.with_name("complete-schedule.html").is_file():
            raise ValueError("COMPLETE_HTML_SCHEDULE_REQUIRED")
    args.output.mkdir(parents=True, exist_ok=False)
    result["source_sha256"] = {
        str(p): sha256(p.read_bytes()).hexdigest() for p in sources
    }
    rows = []
    metrics = [
        ("二级供给等待", "level2_supply_wait_us", 1000, "ms"),
        ("二级完成时间", "level2_completion_us", 1000, "ms"),
        ("总耗时（含排空）", "makespan_us", 1000, "ms"),
        ("二级完成后排空", "drain_tail_us", 1000, "ms"),
        ("跨级交付", "delivery_time_us", 1000, "ms"),
        ("每最终输出原子时间", "atom_us_per_accepted_output", 1e6, "atom·s"),
        ("一级尝试轮数合计", "level1_rounds", 1, ""),
        ("一级接受输出", "level1_outputs", 1, ""),
        ("一级保留剩余输出", "retained_surplus", 1, ""),
        ("Raw 尝试", "raw_attempts", 1, ""),
        ("Raw 拒绝", "raw_rejections", 1, ""),
        ("二级接受输出", "accepted_outputs", 1, ""),
    ]
    for label, key, scale, unit in metrics:
        d = result["differences"][key]
        values = [
            "—" if d[k] is None else f"{d[k] / scale:,.3f} {unit}"
            for k in ("asynchronous", "synchronous", "sync_minus_async")
        ]
        percent = d["sync_reduction_percent"]
        rows.append(
            f"<tr><td>{label}</td>"
            + "".join(f"<td>{v}</td>" for v in values)
            + f"<td>{'—' if percent is None else f'{percent:+.2f}%'}</td></tr>"
        )
    a, b = [r["summary"] for r in runs]
    resource_rows = "".join(
        f"<tr><td>{escape(key)}</td><td>{a['accounting']['resource_busy_us'].get(key, 0) / 1000:.3f}</td>"
        f"<td>{b['accounting']['resource_busy_us'].get(key, 0) / 1000:.3f}</td></tr>"
        for key in sorted(
            a["accounting"]["resource_busy_us"].keys()
            | b["accounting"]["resource_busy_us"].keys()
        )
    )
    baseline = ""
    if args.baseline:
        old = json.loads(args.baseline.read_text(encoding="utf-8"))["summary"]
        if (old["distance"], old["seed"], old["level2_rounds"]) != (
            a["distance"],
            a["seed"],
            a["level2_rounds"],
        ):
            raise ValueError("LEVEL2_REFERENCE_BASELINE_MISMATCH")
        wait = old["factory_wait_us"]["L2-factory0"].get("waiting_supply", 0)
        result["single_producer_reference"] = {
            "source": str(args.baseline),
            "level2_supply_wait_us": wait,
            "makespan_us": old["makespan_us"],
            "allocated_atoms": old["allocated_atoms"],
            "reductions_percent": {
                name: 100 * (wait - s["level2_supply_wait_us"]) / wait
                for name, s in zip(("asynchronous", "synchronous"), (a, b), strict=True)
            },
        }
        baseline = (
            f"<section><h2>上一轮单一级厂参考</h2><p>二级等待 {wait / 1000:.3f} ms，总耗时 {old['makespan_us'] / 1000:.3f} ms，"
            f"{old['allocated_atoms']} 原子。当前一级异步／同步相对它的二级等待减少 "
            f"{100 * (wait - a['level2_supply_wait_us']) / wait:.2f}% ／ {100 * (wait - b['level2_supply_wait_us']) / wait:.2f}%。</p>"
            "<p>增加一级厂也增加原子与占地，并使二级位置下移；这不是相同资源预算下的 N 比较。</p></section>"
        )
    links = " ".join(
        f'<a href="{escape(Path(os.path.relpath(p.with_name("complete-schedule.html"), args.output.resolve())).as_posix())}">'
        f"完整{label} schedule</a>"
        for p, label in zip(sources, ("一级异步", "一级同步"), strict=True)
    )
    max_wait = max(a["level2_supply_wait_us"], b["level2_supply_wait_us"], 1)
    bars = "".join(
        f'<text x="0" y="{30 + i * 45}">{label}</text><rect x="110" y="{12 + i * 45}" '
        f'width="{600 * s["level2_supply_wait_us"] / max_wait:.3f}" height="24" fill="{color}"/>'
        f'<text x="730" y="{30 + i * 45}">{s["level2_supply_wait_us"] / 1000:.3f} ms</text>'
        for i, (label, color, s) in enumerate(
            (("一级异步", "#5285bd", a), ("一级同步", "#35917c", b))
        )
    )
    page = (
        "<!doctype html><html lang=zh-CN><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
        "<title>NADiT 两级工厂策略比较</title><style>body{font:16px/1.6 system-ui;background:#f4f6f8;color:#203040;margin:24px auto;max-width:1200px;padding:0 18px}section{background:white;padding:20px;margin:18px 0;border:1px solid #dde4e8;border-radius:8px}table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}td,th{padding:8px;border-bottom:1px solid #ddd;text-align:right}td:first-child,th:first-child{text-align:left}a{display:inline-block;margin:12px 18px 12px 0;color:#135f99}svg{width:100%}.scroll{overflow:auto}</style>"
        f"<h1>{a['level1_factories']} 个一级厂供给一个二级厂 · 异步／同步</h1><p>d={a['distance']}，B=1，seed={a['seed']}，二级尝试 {a['level2_rounds']} 轮。"
        f"{a['allocated_atoms']} 原子，共同存储及停车包围盒 {a['storage_footprint_um2']:g} μm²。一级布局 {escape(a['level1_placement']['kind'])}，二级位于其下方。</p>"
        f"<p>{links}</p><section><h2>二级供给等待</h2><svg viewBox='0 0 920 110'>{bars}</svg>"
        "<p>等待按二级工厂时间分区统计，不是十五个输入请求等待之和。两级共用单 AOD，同组件并行，不同组件串行；仅一级策略不同。</p></section>"
        "<section class=scroll><h2>时间与产出</h2><table><tr><th>指标</th><th>一级异步</th><th>一级同步</th><th>同步－异步</th><th>同步减少比例</th></tr>"
        + "".join(rows)
        + "</table><p>减少比例为负表示增加。排空与保留剩余输出均计入；二级末端使用理想外部 sink。</p></section>"
        f"<section><h2>共享资源占用 ms</h2><table><tr><th>资源</th><th>一级异步</th><th>一级同步</th></tr>{resource_rows}</table>"
        "<p>资源时间不能相加为总耗时。</p></section>"
        + baseline
        + f"<section><h2>模型与复用</h2><p>{result['common_seeded_events']} 个共有语义事件结果一致。原概率 fake backend；物理编译、原子展开和构造均为 0。"
        "两种策略可能启动不同数量的一级轮次，剩余事件与输出已分别记录。</p><p>这是一个 seed 的有限批次估算，不是稳态吞吐量或原子级执行验证。</p></section></html>"
    )
    (args.output / "index.html").write_text(page, encoding="utf-8")
    (args.output / "comparison.json").write_text(
        json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(result["differences"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
