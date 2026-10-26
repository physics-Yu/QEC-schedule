"""Small standalone reports for logical estimates, without atom replay links."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

_STYLE = """
body{font:15px system-ui,sans-serif;background:#f5f7fb;color:#17253a;max-width:1300px;margin:28px auto;padding:0 24px}
h1{font-size:30px;margin-bottom:8px}h2{font-size:20px;margin-top:32px}.note{background:#fff3d7;padding:14px;border-left:4px solid #d99b24}
.cards{display:flex;gap:16px;flex-wrap:wrap;margin:24px 0}.card{background:white;border:1px solid #dce3ec;border-radius:10px;padding:16px;min-width:165px}.card b{display:block;font-size:24px}
table{border-collapse:collapse;background:white;width:100%;margin:14px 0}th,td{padding:9px 12px;border-bottom:1px solid #dce3ec;text-align:left;font-variant-numeric:tabular-nums}th{background:#eaf0f9}a{color:#175cb5}
canvas{display:block;background:white;border:1px solid #dce3ec;width:100%;margin-top:12px}input[type=range]{width:320px}code{font-size:13px}.muted{color:#506178}.bar{display:block;background:#4081bf;height:16px;border-radius:3px}
"""


def _page(title: str, body: str) -> str:
    return f'<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>{html.escape(title)}</title><style>{_STYLE}</style><body>{body}</body></html>'


def _table(headers: list[str], rows: list[list[Any]]) -> str:
    return (
        "<table><thead><tr>"
        + "".join(f"<th>{html.escape(h)}</th>" for h in headers)
        + "</tr></thead><tbody>"
        + "".join(
            "<tr>" + "".join(f"<td>{html.escape(str(v))}</td>" for v in row) + "</tr>"
            for row in rows
        )
        + "</tbody></table>"
    )


def _model_note(model: dict[str, Any]) -> str:
    if model["mode"] == "theory":
        return (
            f"Theoretical 15-to-1 joint MX checks; accepted-input iid Z error p={model['input_z_error']:.6g}. "
            f"Theory acceptance P={model['theoretical_acceptance_probability']:.9g}; conditional output Z error={model['conditional_output_z_error']:.9g}. "
            "Physical no-fault probability is a separate diagnostic and does not control acceptance. "
            "Ideal factory Clifford, storage and readout are assumed; actual output fidelity is not established."
        )
    return "Legacy physical no-fault proxy experiment; acceptance is not the theoretical 15-to-1 check probability. Logical output quality remains unknown."


def write_run_report(run: Any, output: Path) -> None:
    """Show costs and a component timeline, explicitly scoped to estimates."""
    summary, accounting = run.summary, run.summary["accounting"]
    categories = sorted(
        set(accounting["work_by_category_us"]) | set(accounting["category_busy_us"])
    )
    body = f"""<h1>Fast logical factory experiment</h1><p class="muted">{html.escape(summary["code"])} · seed {summary["seed"]} · {summary["factory_count"]} factory lines · 1 shared AOD</p>
    <p class="note">Logical estimates from frozen component calibration. No atom movement compilation or physical validation was run. {_model_note(summary["experiment_model"])}</p>
    <div class="cards"><div class="card">Modeled makespan<b>{summary["makespan_us"] / 1000:.3f} ms</b></div><div class="card">Measured fast compile<b>{summary["wall_seconds"]:.3f} s</b></div><div class="card">Offered outputs<b>{summary["outputs"]}</b></div><div class="card">Raw attempts / rejects<b>{summary["counts"]["raw_attempts"]} / {summary["counts"]["raw_rejections"]}</b></div><div class="card">Conditional S<b>{summary["counts"]["s_calls"]}</b></div></div>
    <p>Compile time excludes profile load and export. Device capacity: {summary["configuration"]["device_budget"]["aod_max_columns"]} columns, {summary["configuration"]["device_budget"]["max_readout_atoms"]} readout atoms. Profile <code>{summary["profile_sha256"]}</code>.</p>
    <h2>Line ledger</h2>"""
    body += _table(
        [
            "Line",
            "Terminal status",
            "Raw attempts",
            "Rejected raw",
            "S",
            "Output",
            "Final acceptance P",
            "No-fault diagnostic P",
            "Joint MX checks",
        ],
        [
            [
                name,
                row["status"],
                row["raw_attempts"],
                row["raw_rejections"],
                row["s_calls"],
                row["output_status"],
                ", ".join(
                    f"{p:.7g}"
                    for p in summary["factory_acceptance_probabilities"][name]
                ),
                ", ".join(
                    f"{p:.7g}" for p in summary["physical_no_fault_diagnostics"][name]
                ),
                " / ".join(
                    "".join(str(check["values"][f"m_w{i}"]) for i in range(2, 6))
                    for check in row.get("factory_check_events", ())
                )
                or "n/a",
            ]
            for name, row in summary["lines"].items()
        ],
    )
    body += "<h2>Cost accounting</h2><p>Work sums each component member’s category duration. Busy time counts overlapping intervals once. Category and resource sums can overlap and are not the total makespan.</p>"
    body += _table(
        ["Category", "Cumulative member work (µs)", "Union busy time (µs)"],
        [
            [
                key,
                f"{accounting['work_by_category_us'].get(key, 0):.3f}",
                f"{accounting['category_busy_us'].get(key, 0):.3f}",
            ]
            for key in categories
        ],
    )
    body += _table(
        ["Shared resource", "Busy time (µs)"],
        [
            [key, f"{value:.3f}"]
            for key, value in accounting["resource_busy_us"].items()
        ],
    )
    body += f'<p>Global occupied union: {accounting["global_busy_union_us"]:.3f} µs; explicit global waiting: {accounting["explicit_global_wait_us"]:.3f} µs; unoccupied timeline: {accounting["unoccupied_timeline_us"]:.3f} µs. Per-line peer waits are retained in <a href="array-ledger.json">the ledger</a>.</p>'
    body += """<h2>Logical component timeline</h2><p>One row per patch; a CNOT appears on both participating patches. Colors identify component families. Hover for the invocation and times. This is not an atom trajectory.</p>
    <label>Zoom <input id="zoom" type="range" min="1" max="20" value="1"></label> <label>Start <input id="offset" type="range" min="0" max="1000" value="0"></label>
    <canvas id="timeline"></canvas><p id="detail" class="muted">Hover over a component.</p>
    <p><a href="case.json">Complete logical case</a> · <a href="summary.json">Cost summary</a> · <a href="proxy-costs.json">Scoped probability reports</a> · <a href="resource-events.jsonl">Resource lifecycle</a></p>"""
    if summary["experiment_model"]["mode"] == "theory":
        body = body.replace(
            'href="proxy-costs.json">Scoped probability reports',
            'href="physical-costs.json">Physical cost diagnostics',
        )
    data = {
        "duration": summary["makespan_us"],
        "calls": [
            {
                key: row[key]
                for key in (
                    "invocation_id",
                    "component_id",
                    "participant_blocks",
                    "start_us",
                    "action_end_us",
                    "results_ready_us",
                )
            }
            for row in run.case["execution"]["calls"]
        ],
    }
    body += (
        "<script>const data="
        + json.dumps(data, ensure_ascii=True).replace("<", "\\u003c")
        + ";"
        + r"""
    const canvas=document.querySelector('#timeline'),ctx=canvas.getContext('2d'),zoom=document.querySelector('#zoom'),offset=document.querySelector('#offset');
    const rows=[...new Set(data.calls.flatMap(c=>c.participant_blocks))].sort(), colors={raw_t_postselection:'#a364c7',initialize_plus:'#448fb2',transversal_cnot:'#4285c4',logical_s:'#da9344',logical_mx:'#4aa878',logical_mz:'#609858',logical_x:'#d56b68'};let hit=[];
    function draw(){const width=1200,height=60+rows.length*24;canvas.width=width;canvas.height=height;const span=data.duration/Number(zoom.value),start=(data.duration-span)*Number(offset.value)/1000,left=150,w=width-left-20;ctx.clearRect(0,0,width,height);ctx.font='12px system-ui';hit=[];
    for(let i=0;i<=6;i++){let x=left+i*w/6;ctx.fillStyle='#53657b';ctx.fillText(((start+i*span/6)/1000).toFixed(2)+' ms',x-20,18);ctx.strokeStyle='#edf0f5';ctx.beginPath();ctx.moveTo(x,25);ctx.lineTo(x,height);ctx.stroke();}
    rows.forEach((name,i)=>{let y=40+i*24;ctx.fillStyle='#34485e';ctx.fillText(name,5,y+11);ctx.fillStyle='#f1f4f9';ctx.fillRect(left,y,w,17)});
    for(const c of data.calls){if(c.action_end_us<start||c.start_us>start+span)continue;let x=left+Math.max(0,(c.start_us-start)/span*w),end=left+Math.min(w,(c.action_end_us-start)/span*w);for(const p of c.participant_blocks){let y=40+rows.indexOf(p)*24;ctx.fillStyle=colors[c.component_id]||'#93a0ad';ctx.fillRect(x,y,Math.max(2,end-x),17);hit.push({x,y,w:Math.max(2,end-x),c})}}}
    zoom.oninput=offset.oninput=draw;canvas.onmousemove=e=>{let r=canvas.getBoundingClientRect(),x=(e.clientX-r.left)*canvas.width/r.width,y=(e.clientY-r.top)*canvas.height/r.height,h=hit.findLast(h=>x>=h.x&&x<=h.x+h.w&&y>=h.y&&y<=h.y+17);document.querySelector('#detail').textContent=h?`${h.c.invocation_id} | ${h.c.start_us.toFixed(3)}–${h.c.action_end_us.toFixed(3)} µs; results ready ${h.c.results_ready_us.toFixed(3)} µs`:'Hover over a component.'};draw();
    </script>"""
    )
    (output / "index.html").write_text(
        _page("Fast logical factory", body), encoding="utf-8"
    )


def write_sweep_report(result: dict[str, Any], output: Path) -> None:
    """Compare fixed-capacity sizes; avoid certainty claims from zero successes."""
    budget = result["device_capacity"]
    body = f'<h1>Fast factory scaling</h1><p>{len(result["seeds"])} predeclared independent seeds per size. Shared capacity stays at 1 AOD, {budget["aod_max_rows"]} rows, {budget["aod_max_columns"]} columns and {budget["max_readout_atoms"]} readout atoms. Geometric area grows with line count.</p><p class="note">Calibrated logical estimates; no physical validation in this sweep. {_model_note(result["experiment_model"])} A seed trajectory is the statistical unit; concurrent lines are not assumed independent.</p>'
    rows = []
    for group in result["groups"]:
        rows.append(
            [
                group["factory_count"],
                group["independent_seed_runs"],
                f"{group['mean_makespan_us'] / 1000:.3f}",
                f"{group['p95_makespan_us'] / 1000:.3f}",
                group["observed_outputs"],
                f"{group['mean_output_fraction']:.4g}",
                f"{group['mean_compile_wall_seconds']:.3f}",
                group["statistics_valid"],
            ]
        )
    body += _table(
        [
            "Factories",
            "Seeds",
            "Mean model ms",
            "P95 model ms",
            "Outputs",
            "Output fraction",
            "Mean compile s",
            "Valid run set",
        ],
        rows,
    )
    body += "<p>Compile time excludes profile loading and file export. Full protocol errors invalidate the size group; raw exhaustion and final-check rejection are valid terminal outcomes.</p>"
    body += "<h2>Mean component costs</h2><p>Cumulative member work in microseconds, before merging concurrent members. Shared resource busy time and explicit global waits appear separately below.</p>"
    categories = sorted(
        {key for group in result["groups"] for key in group["mean_work_by_category_us"]}
    )
    body += _table(
        ["Factories", *categories],
        [
            [
                g["factory_count"],
                *(
                    f"{g['mean_work_by_category_us'].get(key, 0):.1f}"
                    for key in categories
                ),
            ]
            for g in result["groups"]
        ],
    )
    resources = sorted(
        {key for group in result["groups"] for key in group["mean_resource_busy_us"]}
    )
    body += _table(
        ["Factories", *(key + " busy µs" for key in resources), "Global wait µs"],
        [
            [
                g["factory_count"],
                *(f"{g['mean_resource_busy_us'].get(key, 0):.1f}" for key in resources),
                f"{g['mean_explicit_global_wait_us']:.1f}",
            ]
            for g in result["groups"]
        ],
    )
    body += "<h2>Uncertainty</h2><p>Intervals below use seed-run output fractions (Hoeffding) and whether a seed has any output (Wilson). Small scans, especially zero-output scans, cannot establish high-precision yield.</p>"
    body += _table(
        [
            "Factories",
            "Mean output fraction: 95% bound",
            "Any output per seed: 95% interval",
            "Yield evidence",
        ],
        [
            [
                g["factory_count"],
                str([round(v, 5) for v in g["output_fraction_hoeffding_95"]]),
                str([round(v, 5) for v in g["any_output_wilson_95"]]),
                g["output_yield_precision"],
            ]
            for g in result["groups"]
        ],
    )
    body += (
        '<p><a href="sweep.json">Full manifest, source hashes and statistics</a></p><details><summary>Per-seed line and cost ledgers</summary><ul>'
        + "".join(
            f'<li><a href="{html.escape(name)}">{html.escape(name)}</a></li>'
            for name in result["sample_files"]
        )
        + "</ul></details>"
    )
    (output / "index.html").write_text(
        _page("Fast factory scaling", body), encoding="utf-8"
    )
