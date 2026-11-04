"""Read-only, time-local playback of an already compiled factory array ledger.

No compilation, sampling, physical simulation or validation is performed here.
Frames contain compact ownership fields; probability models and token quality
evidence remain in the linked machine-readable artifacts.
"""

from __future__ import annotations

import html
import json
from math import isfinite
from pathlib import Path
from typing import Any

from modules.logical_compiler.src.protocols.array_ledger import resource_state_at

_CARRIER = ("carrier_id", "phase", "epoch", "owner", "safe_exit_at_us")
_TOKEN = (
    "token_id",
    "carrier_id",
    "epoch",
    "resource_kind",
    "status",
    "consumer",
    "ready_at_us",
    "consumed_at_us",
    "usage_kind",
)


def _compact(resources: dict[str, Any]) -> dict[str, Any]:
    return {
        "carriers": [
            {key: row.get(key) for key in _CARRIER} for row in resources["carriers"]
        ],
        "tokens": [
            {key: row.get(key) for key in _TOKEN} for row in resources["tokens"]
        ],
    }


def _frame(
    ledger: dict[str, Any], at: float, resources: dict[str, Any]
) -> dict[str, Any]:
    tokens = {token["token_id"]: token for token in resources["tokens"]}
    lines = {}
    for identity, line in ledger["lines"].items():
        states = [s for s in line["state_intervals"] if s["start_us"] <= at]
        state = states[-1] if states else {"state": "pending"}
        terminal = (
            line.get("completed_at_us") is not None and line["completed_at_us"] <= at
        )
        calls = [
            c
            for c in ledger["calls"]
            if c["invocation_id"].startswith(identity + "/") and c["start_us"] <= at
        ]
        raw = [c for c in calls if c["component_id"] == "raw_t_postselection"]
        raw_ids = {c["invocation_id"].split("/attempt[", 1)[0] for c in raw}
        events = [
            e
            for e in ledger["events"]
            if e["released_at_us"] <= at and e["occurrence"]["invocation_id"] in raw_ids
        ]
        decisions = [m for m in line.get("batch_decisions", []) if m["at_us"] <= at]
        output = tokens.get(line.get("output_token_id"))
        consumed = tokens.get(line.get("algorithm_consumed_token_id"))
        lines[identity] = {
            "state": state["state"],
            "reason": state.get("reason", ""),
            "stage_key": state.get("stage_key"),
            "peers": state.get("peers", []),
            "terminal_status": line["status"] if terminal else None,
            "failure": line.get("failure") if terminal else None,
            "raw_attempts": len(raw),
            "raw_accepted": sum(e["values"].get("accepted") is True for e in events),
            "raw_rejections": sum(e["values"].get("accepted") is False for e in events),
            "s_calls": sum(c["component_id"] == "logical_s" for c in calls),
            "factory_accepted": decisions[-1]["accepted"] if decisions else None,
            "output": output,
            "algorithm_consumed": consumed is not None
            and consumed["status"] == "consumed",
        }
    return {"at_us": at, "lines": lines, "resources": resources}


def report_state_at(ledger: dict[str, Any], at_us: float) -> dict[str, Any]:
    """Return the displayed state at one time, never using final token snapshots."""
    return _frame(ledger, at_us, _compact(resource_state_at(ledger, at_us)))


def _apply(
    event: dict[str, Any], carriers: dict[str, Any], tokens: dict[str, Any]
) -> None:
    """Incrementally replay only the audit fields required by the report."""
    action = event["action"]
    if action == "register_carrier":
        row = event["carrier"]
        carriers[row["carrier_id"]] = {key: row.get(key) for key in _CARRIER}
        return
    if action == "offer":
        row = event["token"]
        tokens[row["token_id"]] = {key: row.get(key) for key in _TOKEN}
        carriers[row["carrier_id"]].update(
            phase="resource", safe_exit_at_us=row["exit_at_us"]
        )
        return
    if "token_id" in event:
        token = tokens[event["token_id"]]
        carrier = carriers[token["carrier_id"]]
        if action == "reserve":
            token.update(status="reserved", consumer=event["consumer"])
            carrier["owner"] = event["consumer"]
        elif action in ("consume", "discard"):
            token["status"] = "consumed" if action == "consume" else "discarded"
            if action == "consume":
                token.update(
                    consumed_at_us=event["at_us"], usage_kind=event["usage_kind"]
                )
            carrier.update(phase="work", safe_exit_at_us=event["safe_exit_at_us"])
        else:
            raise ValueError(f"UNKNOWN_RESOURCE_ACTION: {action}")
    else:
        carrier = carriers[event["carrier_id"]]
        if action == "begin_preparation":
            carrier.update(
                phase="preparing",
                epoch=event["epoch"],
                owner=event["owner"],
                safe_exit_at_us=event["at_us"],
            )
        elif action == "finish_preparation":
            carrier["phase"] = "work"
        elif action == "extend_use":
            carrier["safe_exit_at_us"] = event["safe_exit_at_us"]
        elif action == "complete_use":
            carrier.update(phase="free", owner=None)
        else:
            raise ValueError(f"UNKNOWN_RESOURCE_ACTION: {action}")


def _audit_time(event: dict[str, Any]) -> float:
    if event["action"] == "offer":
        token = event["token"]
        return float(max(event["at_us"], token["ready_at_us"], token["exit_at_us"]))
    return float(event["at_us"])


def _chart_data(ledger: dict[str, Any], budget: dict[str, Any]) -> dict[str, Any]:
    if ledger.get("schema") != "nadit.factory_array_ledger/1":
        raise ValueError("INVALID_ARRAY_REPORT_SCHEMA")
    duration = ledger["duration_us"]
    if type(duration) not in (int, float) or not isfinite(duration) or duration < 0:
        raise ValueError("INVALID_ARRAY_REPORT_DURATION")
    times = {0.0, float(duration)}
    for line in ledger["lines"].values():
        times.update(s["start_us"] for s in line["state_intervals"])
        if line.get("completed_at_us") is not None:
            times.add(line["completed_at_us"])
    for call in ledger["calls"]:
        times.update((call["start_us"], call["end_us"]))
    times.update(e["released_at_us"] for e in ledger["events"])
    times.update(m["at_us"] for m in ledger["milestones"])
    audit = sorted(
        enumerate(ledger["resources"]["audit"]),
        key=lambda item: (_audit_time(item[1]), item[0]),
    )
    times.update(_audit_time(event) for _, event in audit)
    if any(
        type(t) not in (int, float) or not isfinite(t) or not 0 <= t <= duration
        for t in times
    ):
        raise ValueError("INVALID_ARRAY_REPORT_TIME")
    carriers: dict[str, Any] = {}
    tokens: dict[str, Any] = {}
    cursor, frames = 0, []
    for time in sorted(times):
        while cursor < len(audit) and _audit_time(audit[cursor][1]) <= time:
            _apply(audit[cursor][1], carriers, tokens)
            cursor += 1
        resources = {
            "carriers": [dict(carriers[k]) for k in sorted(carriers)],
            "tokens": [dict(tokens[k]) for k in sorted(tokens)],
        }
        frames.append(_frame(ledger, time, resources))
    return {
        "schema": "nadit.factory_array_report/1",
        "case_id": ledger["case_id"],
        "seed": ledger["seed"],
        "duration_us": duration,
        "coordination_policy": ledger["coordination_policy"],
        "budget": budget,
        "times": sorted(times),
        "frames": frames,
        "lines": {
            key: {
                "roles": list(value["role_bindings"]),
                "states": value["state_intervals"],
            }
            for key, value in ledger["lines"].items()
        },
        "calls": [
            {
                key: c.get(key)
                for key in (
                    "factory_id",
                    "invocation_id",
                    "component_id",
                    "participant_roles",
                    "start_us",
                    "end_us",
                    "batch_id",
                )
            }
            for c in ledger["calls"]
        ],
        "events": [
            {
                "at_us": e["released_at_us"],
                "invocation_id": e["occurrence"]["invocation_id"],
                "attempt": e["occurrence"].get("attempt"),
                "values": e["values"],
                "branch_id": e.get("branch_id"),
            }
            for e in ledger["events"]
        ],
        "decisions": [m for m in ledger["milestones"] if m["kind"] == "batch_decision"],
    }


def write_array_report(
    ledger: dict[str, Any], output: Path, *, budget: dict[str, Any]
) -> None:
    """Write a self-contained interactive index and an explicitly final summary."""
    data = _chart_data(ledger, budget)
    payload = json.dumps(
        data, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
    payload = (
        payload.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    )
    model = ledger.get("experiment_model", {})
    theory = (
        ledger.get("factory_acceptance_kind") == "theoretical_iid_z"
        or model.get("mode") == "theory"
    )
    if theory:
        probability = model.get("theoretical_acceptance_probability")
        output_error = model.get("conditional_output_z_error")
        semantics = (
            f"Joint theoretical MX checks use iid accepted-input Z error p = {model.get('input_z_error')}; "
            f"acceptance probability = {probability}, conditional output Z error = {output_error}. "
            "These assume ideal factory Clifford gates, storage and readout. "
            "Physical no-fault cost does not control acceptance and is not logical success. "
            "Sampled checks are reference feedback; physical measurement bits remain unobserved."
        )
        coverage = (
            "Physical cost includes all six carriers throughout the line's first-component to final-check window, "
            "including raw physical loss and other carriers' waiting during raw preparation. "
            "Later decision-barrier waiting, output correction and held-output storage remain unassessed."
        )
        cost_file = "physical-costs.json"
    else:
        semantics = (
            "Factory acceptance is a physical no-fault proxy, not logical success. "
            "This is the explicitly selected legacy experiment. Physical measurements remain unobserved."
        )
        coverage = (
            "Each legacy factory proxy stops at that line's own final-check evaluation. "
            "Its own raw horizons are excluded for all line atoms: raw physical loss and other carriers' "
            "waiting in those horizons are omitted. Later decision-barrier waiting, output correction "
            "and held-output storage remain unassessed."
        )
        cost_file = "proxy-costs.json"
    page = (
        _HTML.replace("__TITLE__", html.escape(str(ledger["case_id"])))
        .replace("__DATA__", payload)
        .replace("__SEMANTICS__", html.escape(semantics))
        .replace("__COVERAGE__", html.escape(coverage))
        .replace("__COST_FILE__", cost_file)
    )
    final = data["frames"][-1]
    rows = []
    for identity, line in final["lines"].items():
        token = line["output"]
        rows.append(
            f"| {identity} | {line['terminal_status'] or line['state']} | {line['raw_attempts']} | {line['raw_rejections']} | {line['s_calls']} | {line['factory_accepted']} | {token['status'] if token else 'not offered'} |"
        )
    markdown = "\n".join(
        [
            "# Factory array — Final case summary",
            "",
            f"Case: `{ledger['case_id']}`; seed: {ledger['seed']}; duration: {ledger['duration_us']:.6f} us.",
            "",
            f"Coordination policy: `{ledger['coordination_policy']}`. Successful lines hold at stage barriers until their active peers reach the same stage.",
            "",
            "| Line | Terminal status | Raw attempts | Raw rejected | S calls | Factory accepted | Output token |",
            "|---|---|---:|---:|---:|---|---|",
            *rows,
            "",
            "An output being offered is distinct from being reserved or consumed. A raw rejection is an attempt outcome; it is not a factory failure.",
            "",
            semantics,
            "",
            coverage,
            "",
            f"Source physical validation: {ledger.get('physical_validation_ok')}. Device budget: `{json.dumps(budget, sort_keys=True)}`.",
            "",
            "The interactive view starts at time zero. Decisions use feedback release times; tokens are reconstructed from the resource audit. Offers become visible only after max(audit time, token ready time, token safe exit). Future outcomes are hidden until their effective times.",
            "",
            f"[Interactive report](index.html) · [Atom replay](atom-replay.html) · [Case](case.json) · [Array ledger](array-ledger.json) · [Resource audit](resource-events.jsonl) · [Physical costs]({cost_file})",
            "",
        ]
    )
    output.mkdir(parents=True, exist_ok=True)
    (output / "index.html").write_text(page, encoding="utf-8")
    (output / "report.md").write_text(markdown, encoding="utf-8")


_HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Factory array · __TITLE__</title><style>
:root{color-scheme:light;--ink:#173044;--muted:#607483;--line:#d7e1e7;--green:#128675;--amber:#c28221;--red:#bf4d4d}
*{box-sizing:border-box}body{margin:0;background:#f3f6f8;color:var(--ink);font:14px system-ui,sans-serif}main{max-width:1480px;margin:auto;padding:28px}
h1{font-size:29px;margin:0 0 7px}h2{font-size:18px;margin:0 0 12px}p{margin:8px 0;line-height:1.5}.muted{color:var(--muted)}nav{display:flex;gap:18px;flex-wrap:wrap;margin:18px 0}a{color:#276bb0}
.panel,.card{background:white;border:1px solid var(--line);border-radius:12px;padding:18px;margin-bottom:18px}.control{position:sticky;top:0;z-index:3;box-shadow:0 4px 16px #1730440a}.buttons{display:flex;align-items:center;gap:9px;flex-wrap:wrap}
button,select{background:white;border:1px solid #b8c9d3;border-radius:6px;padding:7px 11px;color:var(--ink);cursor:pointer}button:hover{background:#e9f0f4}input[type=range]{width:100%;accent-color:var(--green);margin:13px 0 4px}#clock{font-variant-numeric:tabular-nums;font-weight:700;font-size:18px;margin-left:auto}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(330px,1fr));gap:16px}.card{margin:0}.badge{font-size:12px;font-weight:700;border-radius:20px;padding:5px 10px;background:#e7f3ef;display:inline-block}.waiting{background:#fff0d7;color:#87580f}.failed{background:#ffe7e5;color:#a43c3c}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;border-block:1px solid #e4ebef;padding:14px 0;margin:14px 0}.stats strong{font-size:23px;display:block}.stats span{font-size:11px;color:var(--muted);text-transform:uppercase}.detail{overflow-wrap:anywhere;font-size:13px}.output{border-left:3px solid var(--green);padding-left:10px;margin-top:12px}.failure{color:var(--red)}
.legend{display:flex;gap:17px;flex-wrap:wrap;font-size:12px;margin:12px 0}.dot{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:5px}.timeline{overflow:auto;border:1px solid #e3eaf0;border-radius:7px}svg{display:block;font-family:system-ui,sans-serif}svg text{fill:#536b7b;font-size:11px}svg .lane{fill:#f7f9fb}svg .cursor{stroke:#16394f;stroke-width:1.4;stroke-dasharray:4 3}.tables{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-top:18px}.scroll{max-height:330px;overflow:auto}table{width:100%;border-collapse:collapse;font-size:12px}th,td{text-align:left;padding:9px 7px;border-bottom:1px solid #e8eef2;overflow-wrap:anywhere}th{position:sticky;top:0;background:#f5f8fa;color:#567082}td:first-child{font-variant-numeric:tabular-nums}.notice{font-size:12px;color:var(--muted)}code{font-size:12px;overflow-wrap:anywhere}.empty{padding:20px;color:var(--muted)}@media(max-width:850px){main{padding:15px}.tables{grid-template-columns:1fr}.cards{grid-template-columns:1fr}}
</style></head><body><main>
<h1>Factory array</h1><p class="muted">__TITLE__ · One shared physical timeline · Time-local production and ownership</p>
<nav><a href="atom-replay.html">Atom replay ↗</a><a href="case.json">Case JSON</a><a href="array-ledger.json">Array ledger</a><a href="resource-events.jsonl">Resource audit</a><a href="__COST_FILE__">Physical costs</a><a href="report.md">Final summary</a></nav>
<p class="notice">__SEMANTICS__</p>
<section class="panel control"><div class="buttons"><button id="play">Play</button><button id="previous">← Previous event</button><button id="next">Next event →</button><button id="start">Start</button><button id="end">End</button><label>Timeline zoom <select id="zoom"><option value="1">1×</option><option value="2">2×</option><option value="4">4×</option></select></label><span id="clock"></span></div><input id="time" type="range" min="0" max="1" step="any" value="0" aria-label="Global physical time"><p class="notice">Stage barrier: a ready line holds while active peers finish the same stage. Feedback appears at release time. Future outcomes and tokens remain hidden.</p></section>
<section id="cards" class="cards"></section>
<section class="panel" style="margin-top:18px"><h2>Shared clock · state and component lanes</h2><div class="legend"><span><i class="dot" style="background:#159482"></i>Running</span><span><i class="dot" style="background:#e0a33c"></i>Waiting for peers / feedback / resources</span><span><i class="dot" style="background:#728cc5"></i>Raw preparation</span><span><i class="dot" style="background:#a273be"></i>S correction</span><span><i class="dot" style="background:#5495be"></i>Other component</span><span><i class="dot" style="background:#c96b67"></i>Failed</span></div><div id="timeline" class="timeline"></div><p class="notice">Elapsed actions are clipped to the current time; hover a visible segment for its invocation. Each role has its own lane. Dark markers identify stage barriers. The full axis is the compiled case horizon.</p></section>
<div class="tables"><section class="panel"><h2>Released decisions and component starts</h2><div class="scroll" id="history"></div></section><section class="panel"><h2>Token lifecycle at this time</h2><div class="scroll" id="tokens"></div><p class="notice">Offered ≠ reserved ≠ consumed. Adopted raw resources become protected working carriers.</p></section></div>
<section class="panel"><h2>Carrier ownership</h2><div class="scroll" id="carriers"></div></section>
<p class="notice" id="budget"></p><p class="notice">__COVERAGE__ This view reads a compiled case; it does not simulate hardware or sample new outcomes.</p>
<script id="report-data" type="application/json">__DATA__</script><script>
"use strict";
const D=JSON.parse(document.getElementById('report-data').textContent), slider=document.getElementById('time');
const $=id=>document.getElementById(id), esc=x=>String(x??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt=x=>(x/1000).toFixed(3)+' ms', color=s=>s==='failed'?'#c96b67':s.startsWith('waiting')?'#e0a33c':'#159482';
slider.max=D.duration_us;let timer=null;
function frame(t){let lo=0,hi=D.times.length-1;while(lo<hi){const m=Math.ceil((lo+hi)/2);if(D.times[m]<=t)lo=m;else hi=m-1;}return D.frames[lo];}
function table(headers,rows){return rows.length?'<table><thead><tr>'+headers.map(x=>'<th>'+esc(x)+'</th>').join('')+'</tr></thead><tbody>'+rows.map(r=>'<tr>'+r.map(x=>'<td>'+esc(x)+'</td>').join('')+'</tr>').join('')+'</tbody></table>':'<div class="empty">No records at this time.</div>';}
function draw(t){const F=frame(t);$('clock').textContent=fmt(t)+' / '+fmt(D.duration_us);
$('cards').innerHTML=Object.entries(F.lines).map(([id,l])=>'<article class="card"><h2>'+esc(id)+' <span class="badge '+(l.state.startsWith('waiting')?'waiting':l.failure?'failed':'')+'">'+esc(l.terminal_status||l.state)+'</span></h2><div class="detail"><b>Stage</b> '+esc(l.stage_key||'—')+'<br><b>Waiting for</b> '+esc(l.state==='waiting_peers'?l.peers.filter(p=>p!==id).join(', '):l.state.startsWith('waiting')?l.reason:'—')+'</div><div class="stats">'+[['Raw attempts',l.raw_attempts],['Accepted',l.raw_accepted],['Rejected',l.raw_rejections],['S calls',l.s_calls]].map(([k,v])=>'<div><strong>'+v+'</strong><span>'+k+'</span></div>').join('')+'</div><div class="detail">Factory decision: <b>'+esc(l.factory_accepted===null?'pending':l.factory_accepted?'accepted':'rejected')+'</b><div class="output">Output: <b>'+esc(l.output?l.output.status:'not offered')+'</b>'+(l.output?'<br><code>'+esc(l.output.token_id)+'</code>':'')+'<br>Algorithm consumption: '+(l.algorithm_consumed?'consumed':'not consumed')+'</div>'+(l.failure?'<p class="failure">Terminal failure: '+esc(JSON.stringify(l.failure))+'</p>':'')+'</div></article>').join('');
const rows=[];for(const e of D.events)if(e.at_us<=t)rows.push([e.at_us,e.invocation_id+' · attempt '+e.attempt,JSON.stringify(e.values)+' · '+e.branch_id]);for(const c of D.calls)if(c.start_us<=t)rows.push([c.start_us,c.invocation_id,c.component_id+' · '+(c.end_us<=t?'completed':'in progress')]);for(const d of D.decisions)if(d.at_us<=t)rows.push([d.at_us,d.factory_id+' · batch '+d.batch,d.accepted?'Factory accepted':'Factory rejected']);rows.sort((a,b)=>b[0]-a[0]);$('history').innerHTML=table(['Time','Invocation','Record'],rows.slice(0,150).map(r=>[fmt(r[0]),r[1],r[2]]));
$('tokens').innerHTML=table(['Token','Carrier / epoch','Status','Consumer'],F.resources.tokens.map(r=>[r.token_id,r.carrier_id+' / '+r.epoch,r.status+(r.usage_kind?' ('+r.usage_kind+')':''),r.consumer]));
$('carriers').innerHTML=table(['Carrier','Epoch','Phase','Owner','Safe exit'],F.resources.carriers.map(r=>[r.carrier_id,r.epoch,r.phase,r.owner,fmt(r.safe_exit_at_us)]));timeline(t);}
function timeline(t){const width=Math.max(1000,$('timeline').clientWidth)*Number($('zoom').value),left=130,right=25,span=width-left-right,horizon=Math.max(D.duration_us,1),x=u=>left+u/horizon*span;let y=44;const out=[];
for(let i=0;i<=8;i++){const xx=x(horizon*i/8);out.push('<line x1="'+xx+'" y1="27" x2="'+xx+'" y2="9999" stroke="#e5ecf1"/><text x="'+xx+'" y="18" text-anchor="middle">'+fmt(horizon*i/8)+'</text>');}
function segment(a,b,yy,fill,title,height=16){if(a>t)return;const end=Math.min(b,t);if(end<=a)return;out.push('<rect x="'+x(a)+'" y="'+yy+'" width="'+Math.max(0.7,x(end)-x(a))+'" height="'+height+'" rx="2" fill="'+fill+'"><title>'+esc(title)+'</title></rect>');}
for(const [id,line]of Object.entries(D.lines)){out.push('<text x="10" y="'+(y+12)+'" font-weight="700">'+esc(id)+'</text>');for(const s of line.states){segment(s.start_us,s.end_us,y,color(s.state),s.state+' · '+(s.stage_key||'')+' · '+(s.reason||''));if(s.state==='waiting_peers'&&s.start_us<=t)out.push('<line x1="'+x(s.start_us)+'" x2="'+x(s.start_us)+'" y1="'+(y-3)+'" y2="'+(y+20)+'" stroke="#7f510f"><title>'+esc('Stage barrier: '+(s.stage_key||'')+'; peers '+(s.peers||[]).join(', '))+'</title></line>');}y+=25;
for(const role of line.roles){out.push('<rect class="lane" x="'+left+'" y="'+y+'" width="'+span+'" height="20"/><text x="25" y="'+(y+13)+'">'+esc(role)+'</text>');for(const c of D.calls)if(c.invocation_id.startsWith(id+'/')&&(c.participant_roles||[]).includes(role))segment(c.start_us,c.end_us,y+2,c.component_id==='raw_t_postselection'?'#728cc5':c.component_id==='logical_s'?'#a273be':'#5495be',c.component_id+' · '+c.invocation_id);y+=24;}y+=18;}
out.push('<line class="cursor" x1="'+x(t)+'" x2="'+x(t)+'" y1="27" y2="'+y+'"/>');$('timeline').innerHTML='<svg role="img" aria-label="Time-aligned factory states and component lanes" width="'+width+'" height="'+y+'" viewBox="0 0 '+width+' '+y+'">'+out.join('')+'</svg>';}
function set(t){slider.value=Math.max(0,Math.min(D.duration_us,t));draw(Number(slider.value));}
function stop(){clearInterval(timer);timer=null;$('play').textContent='Play';}
slider.addEventListener('input',()=>{stop();draw(Number(slider.value));});$('zoom').onchange=()=>draw(Number(slider.value));
$('previous').onclick=()=>{stop();set([...D.times].reverse().find(t=>t<Number(slider.value))??0);};$('next').onclick=()=>{stop();set(D.times.find(t=>t>Number(slider.value))??D.duration_us);};$('start').onclick=()=>{stop();set(0);};$('end').onclick=()=>{stop();set(D.duration_us);};
$('play').onclick=()=>{if(timer){stop();return;}if(Number(slider.value)>=D.duration_us)set(0);$('play').textContent='Pause';timer=setInterval(()=>{set(Number(slider.value)+Math.max(D.duration_us/300,0.001));if(Number(slider.value)>=D.duration_us)stop();},80);};
$('budget').textContent='Device budget: '+JSON.stringify(D.budget)+' · Seed '+D.seed+' · Policy '+D.coordination_policy;draw(0);
</script></main></body></html>"""
