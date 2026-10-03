"""Read-only canonical d=3 report from committed physical execution artifacts.

The code diagram is protocol geometry. Spatial motion is shown only by the
shared viewer, using the original VisualRecorder payload. No simulator runs
and no quantum or physical state is changed by this module.
"""
from collections import Counter
from dataclasses import asdict, is_dataclass
import html
import json
import math
from pathlib import Path

from neutral_atom_env.visualization.viewer import write_bundle


def _read(path, *, required=False):
    if not path.exists():
        if required:
            raise FileNotFoundError(path)
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _mapping(value):
    if hasattr(value, "to_dict"):
        value = value.to_dict()
    elif is_dataclass(value):
        value = asdict(value)
    if not isinstance(value, dict):
        raise ValueError("Canonical metadata must be a mapping or expose to_dict()")
    # Normalize tuples in direct dataclass/to_dict inputs exactly as saved JSON.
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))


def _interval(row, start="start_us", end="end_us"):
    a, b = row.get(start), row.get(end)
    if a is None and b is None:
        return None, None
    if (isinstance(a, bool) or isinstance(b, bool) or
            not isinstance(a, (int, float)) or not isinstance(b, (int, float)) or
            not math.isfinite(a) or not math.isfinite(b) or a < 0 or b < a):
        raise ValueError("Invalid actual operation interval")
    return a, b


def _json(value):
    # HTML parsers recognize </script even in JavaScript strings. Escape before
    # embedding inert JSON; the browser reads all values with textContent.
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            .replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
            .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


def _bit(value):
    return type(value) is int and value in (0, 1)


def _evaluate(expression, measurements):
    value = expression.get("constant", 0)
    if not _bit(value):
        raise ValueError("Invalid detector or observable XOR constant")
    for key in expression.get("terms", []):
        bit = measurements.get(key)
        if bit is None:
            return None
        if not _bit(bit):
            raise ValueError("Semantic measurement result must be a bit")
        value ^= bit
    return value


def _checks(value, prefix=""):
    """Extract assertions without turning integer measurement bits into PASS."""
    rows = []
    if isinstance(value, dict):
        for key, item in value.items():
            label = f"{prefix}.{key}" if prefix else key
            if type(item) is bool:
                rows.append({"id": label, "passed": item})
            elif isinstance(item, dict):
                rows.extend(_checks(item, label))
    return rows


def _report_payload(output, metadata):
    compiled = _read(output / "compiled.json", required=True)
    schedule = _read(output / "gate_schedule.json", required=True)
    evidence = _read(output / "evidence.json")
    evidence_filename = "evidence.json"
    if evidence is None:
        evidence = _read(output / "result.json", required=True)
        evidence_filename = "result.json"
    run_metadata = _read(output / "run_metadata.json") or {}
    evidence_mode = evidence.get("initial_placement")
    metadata_mode = run_metadata.get("initial_placement")
    if evidence_mode is not None and metadata_mode is not None and evidence_mode != metadata_mode:
        raise ValueError("Initial placement metadata disagree")
    declared_mode = evidence_mode if evidence_mode is not None else metadata_mode
    placement_source = (evidence_filename if evidence_mode is not None else
                        "run_metadata.json" if metadata_mode is not None else None)
    placement_mode = declared_mode if declared_mode in ("prearranged", "storage") else None
    placement_text = {
        "prearranged": "已重排 EZ 工作布局起步；上游重排/加载准备时间未计入本次运行；量子 RESET/测量仍真实执行。",
        "storage": "SZ 初始布局起步，包含逐原子 staging/归还；量子 RESET/测量仍真实执行。",
        None: "初始布局模式未声明；不推断是否计入上游重排/加载准备时间。",
    }[placement_mode]
    canonical = _mapping(metadata) if metadata is not None else _mapping(
        _read(output / "canonical.json", required=True))
    program = compiled["program"]
    if canonical.get("program") is not None and canonical["program"] != program:
        raise ValueError("Canonical metadata and compiled program disagree")
    bindings = compiled["bindings"]
    roles = program["roles"]
    role_ids = {r["id"] for r in roles}
    if (len(role_ids) != len(roles) or set(bindings) != role_ids or
            len(set(bindings.values())) != len(bindings)):
        raise ValueError("Report requires unique physical bindings for all protocol roles")
    gates = compiled["gates"]
    gate_map = {g["id"]: g for g in gates}
    if len(gate_map) != len(gates):
        raise ValueError("Duplicate compiled gate ID")
    schedule_map = {}
    for row in schedule:
        gid = row["id"]
        if gid not in gate_map or gid in schedule_map:
            raise ValueError("Unknown or duplicate gate schedule ID")
        for key in ("gate_type", "qubit_ids", "depends_on", "condition"):
            if key in row and row[key] != gate_map[gid].get(key):
                raise ValueError(f"Gate schedule changes compiled {key} for {gid}")
        _interval(row)
        if row.get("applied") is not None and type(row["applied"]) is not bool:
            raise ValueError("Gate applied status must be boolean or unknown")
        schedule_map[gid] = row
    phases, phase_map = canonical.get("phases", []), {}
    for phase in phases:
        ids = phase.get("native_gate_ids")
        if ids is None:
            ids = [gid + "__g000" for gid in phase.get("gate_ids", [])]
        for gid in ids:
            if gid not in gate_map or gid in phase_map:
                raise ValueError("Unknown or duplicate phase native gate ID")
            phase_map[gid] = phase
    couplings, coupling_map = canonical.get("couplings", []), {}
    for row in couplings:
        gid = row["native_cz_id"]
        if gid not in gate_map or gid in coupling_map or gate_map[gid]["gate_type"] != "CZ":
            raise ValueError("Unknown, duplicate or non-CZ canonical coupling")
        if (type(row["round_index"]) is not int or row["round_index"] < 1 or
                type(row["layer_index"]) is not int or row["layer_index"] not in (1, 2, 3, 4)):
            raise ValueError("Invalid canonical round or interaction layer")
        pair = (row["ancilla_role"], row["data_role"])
        if not set(pair) <= role_ids or {bindings[r] for r in pair} != set(gate_map[gid]["qubit_ids"]):
            raise ValueError("Canonical coupling disagrees with physical CZ targets")
        coupling_map[gid] = row
    reverse = {q: role for role, q in bindings.items()}
    provenance = {p["gate_id"]: p for p in compiled.get("provenance", [])}
    gate_rows = []
    for gate in gates:
        actual = schedule_map.get(gate["id"], {})
        phase = phase_map.get(gate["id"], {})
        gate_rows.append({**gate, "roles": [reverse.get(q, q) for q in gate["qubit_ids"]],
                          "start_us": actual.get("start_us"), "end_us": actual.get("end_us"),
                          "applied": actual.get("applied"), "phase": phase.get("id"),
                          "round_index": phase.get("round_index"),
                          "layer_index": phase.get("layer_index"),
                          "provenance": provenance.get(gate["id"], {})})
    recording = _read(output / "recording.json")
    operations = _read(output / "schedule.json")
    operation_source = "schedule.json"
    if operations is None:
        operation_source = "recording.json.operations"
        operations = [] if recording is None else [
            {**op, "start_us": op.get("start"), "end_us": op.get("end")}
            for op in recording.get("operations", [])]
    pulses, pulse_gate_ids = [], set()
    for op in operations:
        start, end = _interval(op)
        ids = list(op.get("gate_ids", []))
        if not ids and op.get("gate_id"):
            ids = [op["gate_id"]]
        if any(gid not in gate_map for gid in ids):
            raise ValueError("Physical operation refers to an unknown gate")
        if op.get("kind") != "entangling_pulse":
            continue
        if start is None:
            raise ValueError("Committed entangling pulse requires actual times")
        if any(gate_map[gid]["gate_type"] != "CZ" for gid in ids):
            raise ValueError("Entangling pulse includes a non-CZ gate")
        if len(set(ids)) != len(ids) or pulse_gate_ids.intersection(ids):
            raise ValueError("Physical CZ effect appears in multiple pulses")
        pulse_gate_ids.update(ids)
        phase_ids = sorted({phase_map[gid]["id"] for gid in ids if gid in phase_map})
        pulses.append({"index": len(pulses) + 1, "plan_id": op.get("plan_id"),
                       "operation_id": op.get("operation_id", op.get("index")),
                       "label": op.get("label"), "start_us": start, "end_us": end,
                       "gate_ids": ids, "phase_ids": phase_ids,
                       "pairs": [gate_map[gid]["qubit_ids"] for gid in ids],
                       "couplings": [coupling_map[gid] for gid in ids if gid in coupling_map]})
        for gid in ids:
            actual = schedule_map.get(gid, {})
            a, b = actual.get("start_us"), actual.get("end_us")
            if a is not None and (abs(start-a) > 1e-7 or abs(end-b) > 1e-7):
                raise ValueError("CZ pulse interval disagrees with gate schedule")
    audit = evidence.get("audit", {})
    raw = audit.get("raw_measurements", evidence.get("raw_measurements", {}))
    reported_semantic = audit.get("semantic_results", evidence.get("semantic_results", {}))
    semantic, measurements = {}, []
    for binding in compiled.get("measurements", []):
        result_id, raw_id = binding["result_id"], binding["raw_gate_id"]
        flip = binding.get("bit_flip", 0)
        if not _bit(flip) or raw_id not in gate_map:
            raise ValueError("Invalid measurement sidecar binding")
        bit = raw.get(raw_id)
        if bit is not None and not _bit(bit):
            raise ValueError("Raw measurement result must be a bit")
        value = None if bit is None else bit ^ flip
        if result_id in reported_semantic:
            if not _bit(reported_semantic[result_id]):
                raise ValueError("Semantic measurement result must be a bit")
            if value is not None and reported_semantic[result_id] != value:
                raise ValueError("Raw and semantic measurements disagree")
            value = reported_semantic[result_id]
        if value is not None:
            semantic[result_id] = value
        actual = schedule_map.get(raw_id, {})
        measurements.append({**binding, "raw": bit, "semantic": value,
                             "roles": [reverse.get(q, q) for q in gate_map[raw_id]["qubit_ids"]],
                             "start_us": actual.get("start_us"), "end_us": actual.get("end_us")})
    classical = audit.get("classical_outputs", evidence.get("classical_outputs", {}))
    outputs = {}
    for kind in ("detectors", "observables"):
        rows = []
        for spec in program.get(kind, []):
            value = _evaluate(spec["expression"], semantic)
            reported = classical.get(kind, {}).get(spec["id"])
            if reported is not None and (not _bit(reported) or value is not None and reported != value):
                raise ValueError(f"Reported {kind} disagree with semantic XOR")
            rows.append({**spec, "value": value if value is not None else reported})
        outputs[kind] = rows
    fault_audit = _read(output / "fault_audit.json")
    counts = Counter(g["gate_type"] for g in gates)
    layer_counts = Counter((c["round_index"], c["layer_index"]) for c in couplings)
    warnings = []
    if len(schedule_map) < len(gates):
        warnings.append("部分门尚无执行记录；缺少的时间和 applied 状态显示为未知。")
    if recording is None or not recording.get("operations"):
        warnings.append("没有可播放的真实操作记录；不能由理想线路生成运动动画。")
    if len(phase_map) < len(gates):
        warnings.append("部分 native gates 尚无 canonical phase 元数据。")
    duration = None if recording is None else recording.get("duration")
    start_time = 0 if recording is None else recording.get("start_time", 0)
    if duration is not None:
        if (isinstance(duration, bool) or not isinstance(duration, (int, float)) or
                not math.isfinite(duration) or duration < start_time):
            raise ValueError("Invalid recording duration")
    if duration is None:
        duration = evidence.get("metrics", {}).get("simulation_time_us")
    if duration is not None:
        if (isinstance(start_time, bool) or not isinstance(start_time, (int, float)) or
                not math.isfinite(start_time) or start_time < 0 or
                isinstance(duration, bool) or not isinstance(duration, (int, float)) or
                not math.isfinite(duration) or duration < start_time or
                any(p["start_us"] < start_time - 1e-7 or p["end_us"] > duration + 1e-7
                    for p in pulses)):
            raise ValueError("Actual CZ pulses lie outside recording or evidence duration")
    payload = {"schema": "qec-canonical-baseline-report/1", "canonical": canonical,
               "program": program, "bindings": bindings, "gates": gate_rows,
               "pulses": pulses, "measurements": measurements, **outputs,
               "evidence": evidence, "machine_checks": _checks(audit),
               "fault_audit": fault_audit, "fault_checks": _checks(fault_audit),
               "warnings": warnings, "duration_us": duration, "start_time_us": start_time,
               "initial_placement": {"mode": placement_mode, "declared_mode": declared_mode,
                                     "source": placement_source, "description": placement_text},
               "counts": dict(counts), "layer_counts": [
                   {"round_index": r, "layer_index": l, "pairs": n}
                   for (r, l), n in sorted(layer_counts.items())],
               "sources": {"evidence": evidence_filename, "operations": operation_source},
               "links": [name for name in ("compiled.json", "canonical.json", "gate_schedule.json",
                    "schedule.json", "recording.json", evidence_filename, "run_metadata.json", "fault_audit.json",
                    "physical_circuit.html", "animation.html", "plans.json", "checkpoint.json")
                    if (output / name).exists()]}
    return payload, recording


def canonical_memory_report(output, *, metadata=None):
    """Write ``index.html`` beside a run's original JSON, returning its path.

    ``metadata`` may be a CanonicalMemory object or its JSON mapping. With no
    override, canonical.json is read. evidence.json is preferred to result.json.
    Missing actual intervals are never derived from protocol layers. Invalid
    bindings, conflicting times or classical output sidecars fail closed.
    """
    output = Path(output)
    path = output / "index.html"
    if path.exists():
        path.write_text(_failure_page("报告正在重新生成；此前页面的验收标记已清除。"), encoding="utf-8")
    try:
        payload, recording = _report_payload(output, metadata)
        # This is a copy of the common viewer source, never a change to its source.
        if recording is not None and recording.get("frames"):
            write_bundle(output)
        rendered = _HTML.replace("__REPORT_JSON__", _json(payload)).replace(
            "__RECORDING_JSON__", _json(recording))
    except Exception as error:
        if output.is_dir():
            path.write_text(_failure_page(f"生成失败：{type(error).__name__}: {error}"), encoding="utf-8")
        raise
    path.write_text(rendered, encoding="utf-8")
    return path


def _failure_page(message):
    return ('<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>QEC baseline report · 生成失败或待生成</title>'
            '<body style="font:16px/1.7 system-ui;margin:35px;color:#172b43">'
            '<h1>QEC baseline 报告尚未通过生成校验</h1><p>' + html.escape(message) + '</p>'
            '<p>原始运行证据保留。此页面不提供验收通过标记，也不生成替代运动动画。</p></body></html>')


_HTML = r'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>d=3 Surface code · 阶段 A 物理基线</title>
<style>
:root{color-scheme:light;--ink:#172b43;--muted:#63738a;--x:#147e89;--z:#8d53a2;--border:#dce5eb;--accent:#086d7b}
*{box-sizing:border-box}body{margin:0;background:#edf2f5;color:var(--ink);font:15px/1.6 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1440px;margin:auto;padding:28px}h1{font-size:32px;line-height:1.25;letter-spacing:-.8px;margin:8px 0 16px}h2{font-size:21px;margin:0 0 12px}h3{font-size:16px;margin:0 0 10px}p{margin:8px 0}.eyebrow{color:var(--accent);font-size:12px;letter-spacing:1.8px;font-weight:750}.muted{color:var(--muted)}
header{padding:12px 4px 24px}nav{display:flex;gap:18px;flex-wrap:wrap;margin:22px 0 0}a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
.card{border:1px solid var(--border);border-radius:16px;background:#fff;padding:23px;margin:18px 0;box-shadow:0 3px 20px #182b4305}.metrics{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:12px}.metric{background:#f8fafb;border:1px solid var(--border);border-radius:12px;padding:16px}.metric strong{display:block;font-size:25px;line-height:1.5}.metric span{font-size:12px;color:var(--muted)}
.grid{display:grid;grid-template-columns:minmax(350px,1fr) minmax(400px,1.25fr);gap:25px}.controls{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin:12px 0}label{font-size:13px;color:var(--muted)}select,input,button{font:inherit;border:1px solid #c7d5df;border-radius:7px;padding:7px 10px;background:#fff;color:var(--ink)}button{cursor:pointer}button:hover{background:#eef7f8;border-color:var(--accent)}button:disabled{cursor:default;color:#8895a4}
.scroll{max-height:430px;overflow:auto;border:1px solid var(--border);border-radius:10px}table{border-collapse:collapse;width:100%;font-size:12px}th,td{padding:9px 10px;text-align:left;vertical-align:top;border-bottom:1px solid #e8edf1}th{position:sticky;top:0;background:#f2f6f8;z-index:1;white-space:nowrap}td.code{font:11px/1.5 ui-monospace,SFMono-Regular,Consolas,monospace;overflow-wrap:anywhere}tr:last-child td{border-bottom:0}tr:hover td{background:#f8fbfc}.badge{display:inline-block;padding:2px 8px;border-radius:5px;background:#edf3f6;font-size:12px}.ok{color:#137153;background:#e7f4ed}.fail{color:#ad3f40;background:#fce9ea}.unknown{color:#697687;background:#edf1f5}.note{border-left:3px solid #90bfc6;padding:8px 12px;background:#f1f7f8;border-radius:0 6px 6px 0;font-size:13px}.warning{border-color:#cf9a5d;background:#fcf5eb}.diagram{width:100%;max-height:435px;display:block;background:#fafcfd;border-radius:12px;border:1px solid var(--border)}.legend{display:flex;gap:15px;flex-wrap:wrap;font-size:12px;margin:8px 0}.dot{width:10px;height:10px;display:inline-block;border-radius:50%;margin-right:6px;background:var(--x)}.dot.z{background:var(--z)}.dot.data{background:#5364bc}.small{font-size:12px}.pillrow{display:flex;gap:10px;flex-wrap:wrap}.pillrow a{border:1px solid var(--border);border-radius:6px;padding:6px 9px;font-size:12px}.bar-chart{width:100%;height:100px;display:block;min-width:700px}.chart-scroll{overflow-x:auto}.viewer{min-height:120px}.audits{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:5px 18px}.audit{display:flex;gap:8px;align-items:start;font-size:12px;padding:7px 0;overflow-wrap:anywhere}.audit .badge{white-space:nowrap}details{margin-top:12px}summary{cursor:pointer;font-weight:600;font-size:13px}pre{overflow:auto;max-height:340px;font-size:11px;white-space:pre-wrap;overflow-wrap:anywhere;background:#f7f9fa;border:1px solid var(--border);padding:14px;border-radius:8px}#viewer-error{color:#ad3f40}footer{font-size:12px;padding:12px 2px 25px;color:var(--muted)}
@media(max-width:900px){main{padding:15px}.grid{grid-template-columns:1fr}.metrics{grid-template-columns:repeat(3,1fr)}.card{padding:17px}.audits{grid-template-columns:1fr}h1{font-size:27px}}@media(max-width:520px){.metrics{grid-template-columns:repeat(2,1fr)}main{padding:9px}.card{padding:13px}.grid{gap:15px}.controls{gap:7px}input{max-width:100%}h1{font-size:24px}}
</style></head><body><main>
<header><div class="eyebrow">QEC → PHYSICAL CIRCUIT → NEUTRAL ATOMS</div><h1>d=3 Surface code · 阶段 A 基线</h1>
<p id="lead"></p><p class="muted">理想 Clifford 执行；未启用随机噪声。此页核验协议、编译与物理执行的一致性，不给出 fidelity、逻辑错误率或噪声容错结论。</p>
<nav><a href="#code">码与四层协议</a><a href="#pulses">实际 CZ 批次</a><a href="#motion">中性原子回放</a><a href="#classical">测量与 detectors</a><a href="#checks">机器验收</a></nav></header>
<p id="initial-placement" class="note"></p><div class="metrics" id="metrics"></div><div id="warnings"></div>
<section class="card" id="code"><h2>9 个 data、8 个 syndrome ancillas</h2><p class="muted small">下图表示编码与相互作用关系。坐标是 canonical 码图坐标，不是中性原子的 μm 位置。</p>
<div class="grid"><div><svg id="code-svg" class="diagram" viewBox="0 0 520 435" role="img" aria-label="d3 surface code protocol geometry"></svg><div class="legend"><span><i class="dot data"></i>data</span><span><i class="dot"></i>X check</span><span><i class="dot z"></i>Z check</span><span>加粗连线：所选理想 layer</span></div></div>
<div><div class="controls"><label>Round <select id="round"></select></label><label>Interaction layer <select id="layer"><option value="1">1</option><option value="2">2</option><option value="3">3</option><option value="4">4</option></select></label></div>
<p id="layer-info" class="note"></p><div class="scroll"><table><thead><tr><th>Check</th><th>Ancilla ↔ data</th><th>Physical CZ</th><th>实际时间 μs</th></tr></thead><tbody id="couplings"></tbody></table></div>
<p class="muted small">四个 interaction layers 是协议依赖分组；物理调度可以将一个 layer 拆成多个真实脉冲。每轮应有 24 对 data–ancilla 相互作用。</p></div></div>
<details><summary>Canonical phases 与来源</summary><div class="scroll"><table><thead><tr><th>Phase</th><th>Round / layer</th><th>Primitive gates</th><th>真实执行范围 μs</th></tr></thead><tbody id="phases"></tbody></table></div><p id="source" class="small muted"></p></details></section>
<section class="card" id="pulses"><h2>真实 CZ 脉冲批次与门时间线</h2><p id="pulse-info" class="muted small"></p><div class="chart-scroll"><svg id="pulse-chart" class="bar-chart" viewBox="0 0 1100 100" role="img" aria-label="actual CZ pulse timeline in microseconds"></svg></div>
<p class="muted small">横轴是真实仿真 μs。短脉冲最小显示 2 px 仅用于辨识，时间取原始区间；点击批次或“定位”将回放暂停在实际中点。</p>
<div class="scroll"><table><thead><tr><th>实际批次</th><th>Phase</th><th>Pair count</th><th>起止 μs</th><th>Physical targets</th><th></th></tr></thead><tbody id="pulse-table"></tbody></table></div>
<details><summary>全部 native physical gates</summary><div class="controls"><input id="gate-search" placeholder="搜索 gate ID / role / Q 编号" aria-label="搜索物理门"><label>Gate <select id="gate-kind"><option value="">全部</option></select></label><label>Applied <select id="gate-state"><option value="">全部</option><option value="true">applied</option><option value="false">skipped</option><option value="unknown">未知</option></select></label><span id="gate-count" class="muted small"></span></div><div class="scroll"><table><thead><tr><th>Native gate</th><th>Type / phase</th><th>Roles → physical</th><th>Dependencies / condition</th><th>起止 μs</th><th>Applied</th><th></th></tr></thead><tbody id="gate-table"></tbody></table></div></details></section>
<section class="card" id="motion"><h2>中性原子：已提交事件的真实回放</h2><p class="muted small">复用平台共用 viewer，原始 recording.json 中的坐标、承载、完整 AOD axes、操作区间与时间均保留。这里没有另外生成运动轨迹。</p><div id="viewer-error"></div><div id="atom-viewer" class="viewer"></div></section>
<section class="card" id="classical"><h2>测量结果、帧与 detector 边界</h2><p class="note">bit 0 对应本征值 +1。原始 syndrome 在理想执行中仍可随机；detector 检查预期关系是否发生变化。首轮、轮间 XOR 与终端 data parity 使用各自明确的边界定义。</p>
<h3>Detectors</h3><div class="controls"><label>Boundary <select id="det-boundary"><option value="">全部</option></select></label><span id="det-summary" class="muted small"></span></div><div class="scroll"><table><thead><tr><th>ID</th><th>Boundary</th><th>Semantic XOR</th><th>结果</th></tr></thead><tbody id="detectors"></tbody></table></div>
<h3 style="margin-top:20px">逻辑读出表达式</h3><p class="muted small">本基线保留初次 syndrome sector，下面直接计算声明的 observable；带故障时需要独立 decoder 校正。</p><div class="scroll"><table><thead><tr><th>Observable</th><th>Semantic XOR</th><th>结果</th><th>Interpretation</th></tr></thead><tbody id="observables"></tbody></table></div>
<details><summary>全部 measurement sidecars：raw → semantic</summary><div class="scroll"><table><thead><tr><th>Semantic ID / roles</th><th>Raw physical MEASURE</th><th>Raw bit</th><th>Sign flip</th><th>Semantic bit</th><th>实际时间 μs</th><th></th></tr></thead><tbody id="measurements"></tbody></table></div></details></section>
<section class="card" id="checks"><h2>机器验收与独立 fault audit</h2><p id="run-status"></p><div id="machine-checks" class="audits"></div><details><summary>运行证据原文</summary><pre id="evidence-json"></pre></details>
<h3 style="margin-top:24px">离线 qubit-level fault audit</h3><p class="muted small">此处读取独立审计产物，显示它实际覆盖的单故障集合与结论。它不表示中性原子运动、loss、leakage、相干噪声或全部硬件故障均已通过容错验证。</p><div id="fault-status"></div><div id="fault-checks" class="audits"></div><details id="fault-details"><summary>Fault audit 原文与覆盖范围</summary><pre id="fault-json"></pre></details></section>
<section class="card"><h2>原始产物</h2><div id="links" class="pillrow"></div><p class="muted small">报告只读取这些产物；source 元数据、失败和未完成检查保留，不会以页面渲染覆盖执行证据。</p></section>
<footer>Canonical d=3 memory · 只读报告 · 所有仿真时间使用 μs；码图坐标与物理 μm 坐标分开。</footer>
</main><script type="application/json" id="report-data">__REPORT_JSON__</script><script type="application/json" id="recording-data">__RECORDING_JSON__</script><script src="atom-viewer.js"></script><script>
(()=>{'use strict';const d=JSON.parse(document.getElementById('report-data').textContent),recording=JSON.parse(document.getElementById('recording-data').textContent),$=id=>document.getElementById(id),NS='http://www.w3.org/2000/svg';let viewer=null;
const number=v=>v==null?'未知':Number(v).toLocaleString('en-US',{maximumFractionDigits:6}),interval=g=>g.start_us==null?'未记录':number(g.start_us)+' – '+number(g.end_us),el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!=null)n.textContent=String(text);if(cls)n.className=cls;return n},svg=(tag,attrs,parent)=>{const n=document.createElementNS(NS,tag);Object.entries(attrs).forEach(([k,v])=>n.setAttribute(k,String(v)));parent.append(n);return n},badge=(v,labels=['未通过','通过'])=>el('span',v==null?'未知':labels[v?1:0],'badge '+(v==null?'unknown':v?'ok':'fail'));
const cell=(row,value,cls)=>{const n=el('td',value,cls);row.append(n);return n},tableRow=(root,values)=>{const row=el('tr');values.forEach(v=>cell(row,v));root.append(row);return row},jump=(g,cell)=>{if(g.start_us==null)return;const b=el('button','定位');b.disabled=!recording?.operations?.length;b.onclick=()=>{if(viewer){viewer.setTime((g.start_us+g.end_us)/2);$('motion').scrollIntoView({behavior:'smooth',block:'start'})}};cell.append(b)},expr=x=>(x.terms?.length?x.terms.join(' ⊕ '):'0')+(x.constant?' ⊕ 1':'');
$('lead').textContent=(d.evidence.basis||d.program.memory_contract?.basis||'?')+' basis memory · '+new Set(d.canonical.couplings.map(c=>c.round_index)).size+' 总 syndrome rounds · '+d.program.roles.filter(r=>r.kind==='data').length+' data / '+d.program.roles.filter(r=>r.kind==='syndrome_ancilla').length+' checks · '+(d.evidence.physical_atom_count??'未知')+' 个平台原子';
$('initial-placement').textContent=d.initial_placement.description;if(d.initial_placement.source)$('initial-placement').append(el('span','  来源：'+d.initial_placement.source,'muted small'));
const metrics=[['Native CZ',d.counts.CZ||0,'编译出的双比特门'],['真实 CZ 脉冲',d.pulses.length,'来自 '+d.sources.operations],['MEASURE',d.counts.MEASURE||0,'单原子测量任务'],['Detectors',d.detectors.length,'声明的时域边界'],['终态时间 μs',number(d.duration_us),'包含原始运行终态条件']];for(const [name,value,note]of metrics){const m=el('div',null,'metric');m.append(el('div',name,'small'),el('strong',value),el('span',note));$('metrics').append(m)}
for(const warning of d.warnings)$('warnings').append(el('p',warning,'note warning'));
const gateMap=new Map(d.gates.map(g=>[g.id,g])),rounds=[...new Set(d.canonical.couplings.map(c=>c.round_index))].sort((a,b)=>a-b);rounds.forEach(r=>{const o=el('option',r);o.value=r;$('round').append(o)});
const coords=d.canonical.role_coordinates||{},roles=d.program.roles,positions={};let values=roles.map(r=>coords[r.id]).filter(v=>Array.isArray(v)&&v.length===2);const xs=values.map(v=>v[0]),ys=values.map(v=>v[1]),xmin=Math.min(...xs),xmax=Math.max(...xs),ymin=Math.min(...ys),ymax=Math.max(...ys);roles.forEach(r=>{const c=coords[r.id];if(c)positions[r.id]=[65+(c[0]-xmin)/Math.max(1,xmax-xmin)*390,55+(c[1]-ymin)/Math.max(1,ymax-ymin)*320]});
function code(){const s=$('code-svg');s.replaceChildren();const round=Number($('round').value),layer=Number($('layer').value),selected=d.canonical.couplings.filter(c=>c.round_index===round&&c.layer_index===layer),all=d.canonical.couplings.filter(c=>c.round_index===round);const dedup=new Set();for(const c of all){const key=c.ancilla_role+'|'+c.data_role;if(dedup.has(key))continue;dedup.add(key);const a=positions[c.ancilla_role],b=positions[c.data_role];if(a&&b)svg('line',{x1:a[0],y1:a[1],x2:b[0],y2:b[1],stroke:'#dbe5eb','stroke-width':2},s)}for(const c of selected){const a=positions[c.ancilla_role],b=positions[c.data_role];if(a&&b)svg('line',{x1:a[0],y1:a[1],x2:b[0],y2:b[1],stroke:c.check_id.includes('.X')?'#147e89':'#8d53a2','stroke-width':4},s)}for(const r of roles){const p=positions[r.id];if(!p)continue;const color=r.kind==='data'?'#5364bc':r.id.includes('.X')?'#147e89':'#8d53a2';svg('circle',{cx:p[0],cy:p[1],r:r.kind==='data'?18:15,fill:color,stroke:'#fff','stroke-width':3},s);const text=svg('text',{x:p[0],y:p[1]+4,'text-anchor':'middle','font-size':11,fill:'#fff','font-weight':650},s);text.textContent=r.id.split('.').pop();const q=svg('text',{x:p[0],y:p[1]+32,'text-anchor':'middle','font-size':10,fill:'#65778b'},s);q.textContent=d.bindings[r.id]}if(!values.length){const text=svg('text',{x:40,y:70,fill:'#63738a'},s);text.textContent='缺少 canonical role_coordinates；不推断码图位置。'}$('couplings').replaceChildren();for(const c of selected){const g=gateMap.get(c.native_cz_id),tr=tableRow($('couplings'),[c.check_id,c.ancilla_role+' ↔ '+c.data_role,c.native_cz_id,interval(g)]);tr.children[2].className='code';jump(g,tr.children[3])}const count=all.length,batches=d.pulses.filter(p=>p.couplings.some(c=>c.round_index===round&&c.layer_index===layer));$('layer-info').textContent='Round '+round+' / layer '+layer+'：'+selected.length+' 对；本轮 '+count+' / 24 对。所选层关联 '+batches.length+' 个已记录的真实 CZ 脉冲。';}code();$('round').onchange=code;$('layer').onchange=code;
for(const p of d.canonical.phases){const gs=(p.native_gate_ids||p.gate_ids.map(id=>id+'__g000')).map(id=>gateMap.get(id)),actual=gs.filter(g=>g.start_us!=null),range=actual.length?number(Math.min(...actual.map(g=>g.start_us)))+' – '+number(Math.max(...actual.map(g=>g.end_us))):'未记录';tableRow($('phases'),[p.id,[p.round_index??'—',p.layer_index??'—'].join(' / '),gs.length,range])}const source=d.canonical.source||{};$('source').textContent='Canonical 来源：'+(source.version||'未声明')+' · commit '+(source.commit||'未声明');if(source.url){try{const url=new URL(source.url);if(['http:','https:'].includes(url.protocol)){const a=el('a','源代码');a.href=url.href;a.target='_blank';a.rel='noopener';$('source').append(document.createTextNode(' · '),a)}}catch{}}
$('pulse-info').textContent=d.pulses.length+' 个实际 entangling_pulse，包含 '+d.pulses.reduce((n,p)=>n+p.gate_ids.length,0)+' 个 CZ effect；协议有 '+d.layer_counts.length+' 个 interaction layer 分组。';
const chart=$('pulse-chart'),start=d.start_time_us||0,end=d.duration_us??Math.max(start,...d.pulses.map(p=>p.end_us)),scale=t=>55+(t-start)/Math.max(1,end-start)*990;svg('line',{x1:55,y1:60,x2:1045,y2:60,stroke:'#b3c5d0'},chart);for(let i=0;i<=4;i++){const t=start+(end-start)*i/4,x=scale(t);svg('line',{x1:x,y1:57,x2:x,y2:65,stroke:'#b3c5d0'},chart);const label=svg('text',{x,y:85,'text-anchor':'middle','font-size':11,fill:'#63738a'},chart);label.textContent=number(t)}for(const p of d.pulses){const r=svg('rect',{x:scale(p.start_us),y:25,width:Math.max(2,scale(p.end_us)-scale(p.start_us)),height:32,rx:1,fill:'#147e89',tabindex:0,role:'button','aria-label':'CZ 批次 '+p.index},chart),title=svg('title',{},r);title.textContent='Pulse '+p.index+' · '+p.gate_ids.length+' pairs · '+interval(p)+' μs';const action=()=>{if(viewer){viewer.setTime((p.start_us+p.end_us)/2);$('motion').scrollIntoView({behavior:'smooth'})}};r.onclick=action;r.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();action()}};const tr=tableRow($('pulse-table'),[p.index,p.phase_ids.join(', '),p.gate_ids.length,interval(p),p.pairs.map(pair=>pair.join(' ↔ ')).join('; '),'']);jump(p,tr.lastChild)}
Object.keys(d.counts).sort().forEach(k=>{const o=el('option',k);o.value=k;$('gate-kind').append(o)});function gates(){const text=$('gate-search').value.toLowerCase(),kind=$('gate-kind').value,state=$('gate-state').value;const filtered=d.gates.filter(g=>(!kind||g.gate_type===kind)&&(!state||(g.applied==null?'unknown':String(g.applied))===state)&&(!text||[g.id,...g.qubit_ids,...g.roles,g.phase].join(' ').toLowerCase().includes(text)));$('gate-table').replaceChildren();for(const g of filtered){const tr=el('tr');cell(tr,g.id,'code');cell(tr,g.gate_type+' · '+(g.phase||'未映射'));cell(tr,g.roles.join(', ')+' → '+g.qubit_ids.join(', '),'code');cell(tr,'deps: '+(g.depends_on||[]).join(', ')+'\ncondition: '+JSON.stringify(g.condition||[]),'code');cell(tr,interval(g));cell(tr,null).append(badge(g.applied,['skipped','applied']));jump(g,cell(tr,null));$('gate-table').append(tr)}$('gate-count').textContent=filtered.length+' / '+d.gates.length+' gates';}gates();$('gate-search').oninput=gates;$('gate-kind').onchange=gates;$('gate-state').onchange=gates;
if(recording?.frames?.length&&window.NeutralAtomViewer){try{viewer=window.NeutralAtomViewer.mount($('atom-viewer'),recording,{compact:true});window.qecBaselineViewer=viewer}catch(error){$('viewer-error').textContent='真实记录加载失败：'+error.message}}else{$('atom-viewer').textContent='没有可播放的真实 recording；本页仅展示已有协议与执行证据。'}
const boundaries=[...new Set(d.detectors.map(x=>x.boundary))];boundaries.forEach(b=>{const o=el('option',b);o.value=b;$('det-boundary').append(o)});function detectors(){$('detectors').replaceChildren();for(const x of d.detectors.filter(x=>!$('det-boundary').value||x.boundary===$('det-boundary').value)){const tr=tableRow($('detectors'),[x.id,x.boundary,expr(x.expression),'']);tr.children[2].className='code';tr.lastChild.append(badge(x.value==null?null:x.value===0,['1 · 事件','0 · 关系满足']))}}detectors();$('det-boundary').onchange=detectors;$('det-summary').textContent=d.detectors.filter(x=>x.value===0).length+' 个 0，'+d.detectors.filter(x=>x.value===1).length+' 个 1，'+d.detectors.filter(x=>x.value==null).length+' 个未知';for(const x of d.observables)tableRow($('observables'),[x.id,expr(x.expression),x.value??'未知',x.interpretation||'']);for(const m of d.measurements){const tr=tableRow($('measurements'),[m.result_id+' · '+m.roles.join(','),m.raw_gate_id,m.raw??'未知',m.bit_flip,m.semantic??'未知',interval(m),'']);tr.children[1].className='code';jump(m,tr.lastChild)}
function audits(rows,target){if(!rows.length){target.append(el('p','未记录布尔机器断言。','muted small'));return}for(const r of rows){const row=el('div',null,'audit');row.append(badge(r.passed),el('span',r.id));target.append(row)}}audits(d.machine_checks,$('machine-checks'));const status=el('span',d.evidence.status||'未知','badge '+(d.evidence.status==='completed'?'ok':d.evidence.status==='failed'?'fail':'unknown'));$('run-status').append(status,document.createTextNode(' · '+d.machine_checks.filter(c=>c.passed).length+' / '+d.machine_checks.length+' 个记录的布尔断言通过'));$('evidence-json').textContent=JSON.stringify(d.evidence,null,2);if(d.evidence.error)$('run-status').append(el('p',JSON.stringify(d.evidence.error),'note warning'));
if(d.fault_audit){$('fault-status').textContent='已加载 fault_audit.json；具体覆盖与失败项见下方原文。';audits(d.fault_checks,$('fault-checks'));$('fault-json').textContent=JSON.stringify(d.fault_audit,null,2)}else{$('fault-status').textContent='未提供独立 fault_audit.json；不将此项标为已验收。';$('fault-details').hidden=true}for(const name of d.links){const a=el('a',name);a.href=name;$('links').append(a)}window.qecBaselineReport={data:d,recording};
})();
</script></body></html>'''
