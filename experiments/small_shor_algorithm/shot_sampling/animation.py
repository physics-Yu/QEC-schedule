"""Embed the established physical-compiler viewer with parameter messages.

Only copies of the standard viewer assets are localized and simplified. The
renderer, AOD geometry, playback engine, and recorded sampled branches are reused.
"""

from __future__ import annotations

import json
import re
import subprocess
from html import escape
from pathlib import Path

from ..simplified_circuit.compile_inputs import BUILD

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]
WEB = REPO / "modules/physical_compiler/src/nadit_physical_compiler/visualization/web"
SOURCE = BUILD / "results"


def _traces(plans: dict[str, dict], engine: Path) -> list[dict]:
    """Apply ideal sampled results to the same maximal plans used by sampling."""
    from nadit_physical_compiler.visualization.result import build_result_trace

    manifest = json.loads((SOURCE.parent / "manifest.json").read_text(encoding="utf-8"))
    cases = {case["n"]: case for case in manifest["cases"]}
    traces = []
    ordered = []
    for n in (15, 21):
        document = json.loads((SOURCE / f"n{n}.json").read_text(encoding="utf-8"))
        if any(node["name"] == "cp" for node in document["dag"]["nodes"]):
            raise ValueError("The example animation must use semiclassical feedback.")
        trace = build_result_trace(document, title=f"N = {n} · 编译结果示例")
        plan = plans[str(n)]
        outcomes = cases[n]["ideal_reference_outcomes"]
        if {int(key) for key in outcomes} != {
            measurement["measurement_id"] for measurement in plan["measurements"]
        } or any(value not in (0, 1) for value in outcomes.values()):
            raise ValueError(f"N={n} ideal reference does not match plan measurements.")
        trace["measurements"] = [
            {"measurement_id": int(key), "value": value}
            for key, value in outcomes.items()
        ]
        trace["ideal_reference_seed"] = cases[n]["ideal_reference_seed"]
        traces.append(trace)
        ordered.append(plan)
    # The initial example uses precisely the same guarded plan, parameter
    # preparation, and false-condition idle slots as every subsequent replay.
    script = """
const fs = require('fs');
require(process.argv[1]);
const bridge = require(process.argv[2]);
const {traces,plans} = JSON.parse(fs.readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify(traces.map((t,i) =>
  bridge.buildTrace(t,plans[i],{},null,'尚未采样').trace)));
"""
    result = subprocess.run(
        [
            "node",
            "-e",
            script,
            str(engine),
            str(ROOT / "animation_bridge.js"),
        ],
        input=json.dumps({"traces": traces, "plans": ordered}),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    retimed = json.loads(result.stdout)
    labels = {
        "Load": "装载到 AOD",
        "Store": "卸载到 SLM",
        "Move": "移动原子",
        "Measure": "测量",
        "Reset": "初始化",
        "Wait": "等待结果",
        "CZPulse": "CZ 门",
    }
    for trace in retimed:
        for key in ("noise_report", "loss_time", "loss_time_result", "compilation"):
            trace.pop(key, None)
        for zone in trace["device"]["zones"]:
            zone["id"] = {
                "storage": "存储区",
                "entanglement": "纠缠区",
                "measurement": "测量区",
            }.get(zone["id"], zone["id"])
        for step in trace["steps"]:
            for action in step["actions"]:
                if action["kind"] in labels:
                    action["gate_label"] = labels[action["kind"]]
        measurement_ends = {
            result["measurement_id"]: step["start_us"] + action["duration_us"]
            for step in trace["steps"]
            for action in step["actions"]
            if action["kind"] == "Measure"
            for result in action["parameters"]["results"]
        }
        if any(
            abs(record["available_at_us"] - measurement_ends[record["measurement_id"]])
            > 1e-8
            for record in trace["measurements"]
        ):
            raise ValueError("Example animation retained nonzero readout latency.")
    return retimed


def build_animation_html(plans: dict[str, dict], engine: Path) -> str:
    """Return an offline standard-template animation for an iframe srcdoc.

    Build-time dependencies are the existing physical compiler, Node, and the
    saved maximal results and ideal-reference measurements. The returned document has no runtime external
    dependencies. It contains two reference traces plus guarded plans. Parent
    messages select current parameters and a reported measurement branch.
    """
    template = (WEB / "viewer.html").read_text(encoding="utf-8")
    translations = {
        'lang="en"': 'lang="zh-CN"',
        "Atom replay": "原子移动动画",
        "NADiT physical compiler": "NADiT 物理编译器",
        ">Trace</span>": ">电路</span>",
        "Select trace": "选择编译结果",
        "Present full screen (F)": "全屏展示（F）",
        "      Present\n": "      全屏\n",
        ">Atoms<": ">原子数<",
        ">Steps<": ">步骤数<",
        ">Duration<": ">总时长<",
        "SLM sites": "SLM 陷阱",
        "AOD beams": "AOD 光束",
        "Move paths": "移动路径",
        "Atom IDs": "原子编号",
        ">Path <select": ">路径 <select",
        "Display path": "显示路径",
        "Fit view": "适应视图",
        "Drag to pan, scroll to zoom, click an atom": "拖动平移，滚轮缩放，点击选择原子",
        "Exit full screen": "退出全屏",
        "SLM atom": "SLM 中原子",
        "AOD atom": "AOD 中原子",
        "Rydberg CZ / CP": "CZ 门",
        "Local gate": "单比特门",
        "Readout": "测量",
        "Previous step": "上一步",
        "Next step": "下一步",
        'aria-label="Play"': 'aria-label="播放"',
        ">Play</button>": ">播放</button>",
        ">Step <strong": ">步骤 <strong",
        'aria-label="Step"': 'aria-label="步骤"',
        "Initial layout": "初始布局",
        ">Load</span>": ">装载</span>",
        ">Move</span>": ">移动</span>",
        ">Store</span>": ">卸载</span>",
        ">CZ / CP</span>": ">CZ</span>",
        ">Local</span>": ">单比特门</span>",
        ">Wait</span>": ">等待</span>",
        ">Speed<select": ">播放速度<select",
        "Within step": "步骤内进度",
        "Time (µs)": "时间（µs）",
        ">Playback<select": ">播放方式<select",
        "0.8 s per step": "每步 0.8 秒",
        "Real-time ratio, 30 s total": "按物理时间比例，约 30 秒播放完",
    }
    for old, new in translations.items():
        template = template.replace(old, new)
    template = template.replace(
        '<option value="lanes">Lanes</option><option value="direct">Direct</option>',
        '<option value="direct">记录的移动段</option>',
    ).replace('<option value="proportional">', '<option value="proportional" selected>')
    # Retain all expected DOM nodes so the original viewer's modules still load.
    # Hide analysis/diagnostic panels rather than reimplementing the renderer.
    style = (
        (WEB / "viewer.css").read_text(encoding="utf-8")
        + """
.inspector,.analysis,.footer,#ir-panel,.size-controls,#qec-controls,.trace-choice,
#selection-chip,.path-choice,.caption-hint{display:none!important}
.workspace{display:block;padding:0 16px 16px}
.topbar{padding:12px 16px}.trace-heading{padding:12px 16px}
.canvas-wrap{height:440px}.trace-heading .trace-text{max-width:850px}
.trace-stats{gap:18px}.stage-toolbar{padding:10px 14px}
.legend,.transport,.fine-controls{padding-left:14px;padding-right:14px}
@media(max-width:650px){.canvas-wrap{height:400px}.trace-heading{gap:10px}}
"""
    )
    viewer = (WEB / "viewer.js").read_text(encoding="utf-8")
    # Only replace display strings; action-kind keys and physical data stay intact.
    literal_translations = {
        "'Load: SLM → AOD'": "'装载：SLM → AOD'",
        "'Move atoms'": "'移动原子'",
        "'Store: AOD → SLM'": "'卸载：AOD → SLM'",
        "'CZ pulse'": "'CZ 门'",
        "'CPhase pulse'": "'CPhase 门'",
        "'Readout'": "'测量'",
        "'Local rotation'": "'局部旋转'",
        "'Local gate'": "'单比特门'",
        "'Global Y rotation'": "'整体 Y 旋转'",
        "'Reset'": "'初始化'",
        "'Wait'": "'等待'",
        "'Direct preview, recorded timing'": "'几何回放，不表示实际 STA 波形'",
        "'No display lane, direct preview'": "'几何回放，不表示实际 STA 波形'",
        "'Lane preview, recorded timing'": "'几何回放，不表示实际 STA 波形'",
        "'Waiting for measurement results'": "'等待测量结果'",
        "'Waiting for measurement results · '": "'等待测量结果 · '",
        "'Final layout'": "'最终布局'",
        "'Final layout · '": "'最终布局 · '",
        "'Step '": "'步骤 '",
        "' atoms'": "' 颗原子'",
        "'End / '": "'结束 / '",
        "'Pause'": "'暂停'",
        "'Play'": "'播放'",
    }
    # Reset/Wait occur in action-kind comparisons as well as labels. Their values
    # must only be localized in KIND_LABELS, never in dispatcher expressions.
    literal_translations.pop("'Reset'")
    literal_translations.pop("'Wait'")
    for old, new in literal_translations.items():
        viewer = viewer.replace(old, new)
    viewer = viewer.replace(
        "Reset: 'Reset', Wait: 'Wait'", "Reset: '初始化', Wait: '等待'"
    )
    viewer = viewer.replace(
        "    updateControls(); updateInspector(); updateMeasurements(); draw();",
        """    updateControls(); updateInspector(); updateMeasurements(); draw();
    if (window.parent !== window) window.parent.postMessage({type:'shor-replay-clock',
      time_us:frame.time_us, n:trace.shor_n, bitstring:trace.shor_bitstring}, '*');""",
    )
    bridge_install = """
  const referenceTraces = data.traces.slice();
  window.addEventListener('message', event => {
    if (event.source !== window.parent || event.data?.type !== 'shor-replay-parameters') return;
    const request = event.data;
    try {
      const index = request.n === 15 ? 0 : request.n === 21 ? 1 : -1;
      if (index < 0) throw Error('只支持 N=15 或 N=21。');
      const result = ShorReplayBridge.buildTrace(referenceTraces[index], data.guarded_plans[index],
        request.parameters, request.bitstring, request.selection_label);
      data.traces = [result.trace];
      $('trace-select').replaceChildren(new Option(result.trace.title, '0'));
      loadTrace(0);
      window.parent.postMessage({...result.risk, request_id:request.request_id ?? null}, '*');
    } catch (error) {
      window.parent.postMessage({type:'shor-replay-error', message:error.message,
        request_id:request.request_id ?? null}, '*');
    }
  });
  window.parent.postMessage({type:'shor-replay-ready'}, '*');
"""
    viewer = viewer.replace(
        "  loadTrace(0);\n})();", "  loadTrace(0);\n" + bridge_install + "\n})();"
    )
    data = json.dumps(
        {
            "schema_version": 1,
            "traces": _traces(plans, engine),
            "guarded_plans": [plans[str(n)] for n in (15, 21)],
        },
        ensure_ascii=True,
        separators=(",", ":"),
        allow_nan=False,
    ).replace("<", "\\u003c")
    replacements = {
        "TITLE": escape("NADiT · 当前参数的物理执行动画"),
        "STYLE": style,
        "MODEL": "\n".join(
            (WEB / name).read_text(encoding="utf-8")
            for name in (
                "paths.js",
                "model.js",
                "loss.js",
                "analysis.js",
                "loss-panel.js",
                "dashboard.js",
                "qec.js",
            )
        )
        + "\n"
        + engine.read_text(encoding="utf-8")
        + "\n"
        + (ROOT / "animation_bridge.js").read_text(encoding="utf-8"),
        "SCRIPT": viewer,
        "DATA": data,
    }
    return re.sub(
        r"\{\{(TITLE|STYLE|MODEL|SCRIPT|DATA)\}\}",
        lambda match: replacements[match[1]],
        template,
    )


def replay_frame(animation: str) -> str:
    """Embed a complete local replay viewer and the atom-loss curve."""
    return (
        '<section class="card" style="margin-top:24px"><h2>本次参数下的编译回放</h2>'
        '<p id="replay-description" class="muted">采样完成后，动画按本次提交的参数和一个测量分支更新。'
        "这里展示门与搬运计划，不回放随机 Pauli 错误，也不随机移除原子。</p>"
        '<iframe id="compile-animation" title="本次参数的编译结果动画" loading="lazy" '
        'style="width:100%;height:850px;border:1px solid #dce5e8;border-radius:6px" '
        'srcdoc="' + escape(animation, quote=True) + '"></iframe>'
        '<h3 style="margin-top:16px">平均原子丢失概率随时间</h3>'
        '<p id="risk-at-time" class="muted">等待计划数据。</p>'
        '<div style="height:240px"><canvas id="atom-risk-curve" aria-label="平均原子丢失概率随时间的曲线"></canvas></div>'
        "<p><small>先计算每颗原子的累计丢失概率，再对所有原子取平均。曲线只包含物理原子丢失，不包含 T₂ 退相干。"
        "这是完整计划的风险估计；多-shot 采样仍在首次丢失时终止，不表示丢失后继续执行。</small></p>"
        "<details><summary>曲线怎么算</summary>"
        '<math display="block" xmlns="http://www.w3.org/1998/Math/MathML">'
        "<mover><mi>L</mi><mo>¯</mo></mover><mo>(</mo><mi>t</mi><mo>)</mo><mo>=</mo>"
        "<mfrac><mn>1</mn><mi>N</mi></mfrac><munderover><mo>∑</mo><mrow><mi>i</mi><mo>=</mo><mn>1</mn></mrow><mi>N</mi></munderover>"
        "<mo>[</mo><mn>1</mn><mo>−</mo><munder><mo>∏</mo><mrow><mi>j</mi><mo>:</mo><msub><mi>t</mi><mi>j</mi></msub><mo>≤</mo><mi>t</mi></mrow></munder>"
        "<mo>(</mo><mn>1</mn><mo>−</mo><msub><mi>p</mi><mrow><mi>i</mi><mi>j</mi></mrow></msub><mo>)</mo><mo>]</mo></math>"
        "<p><small>N 是原子数；i 是原子编号；j 是当前动画分支中实际作用于该原子的损失事件；"
        "tⱼ 是事件完成时刻；pᵢⱼ 是原子此前存活时该事件造成丢失的概率。"
        "未执行的条件门不计事件损失。空闲时这条物理丢失曲线保持不变，T₂ 仍参与上方量子态采样。</small></p>"
        "</details></section>"
    )
