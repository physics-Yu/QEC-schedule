"""Audit saved one-AOD factory witnesses and show their actual joint activity."""

import argparse
import csv
import hashlib
import html
import json
from collections import Counter, defaultdict
from math import isclose
from pathlib import Path


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def audit_native_activity(group, trace):
    """Reconstruct activity from serialized atom actions, independently of the exporter."""
    owner = {
        atom: member
        for member, atoms in group["participant_atoms"].items()
        for atom in atoms
    }
    wires = trace["entry_state"]["qubit_to_atom"]
    nodes = trace["dag"]["nodes"]
    costs = defaultdict(set)
    measurements = defaultdict(list)
    primitives = defaultdict(Counter)
    for node in nodes:
        members = {owner[wires[q]] for q in node["qubits"]}
        assert len(members) == 1
        if node["name"] != "barrier":
            primitives[next(iter(members))][node["name"]] += 1
    clock = 0.0
    peak = 0
    overlap = 0.0
    rows = columns = readout = 0
    for index, step in enumerate(trace["program"]["steps"]):
        duration = max(a["duration_us"] for a in step["actions"])
        activity = []
        readout_count = 0
        for action in step["actions"]:
            kind = action["kind"]
            if kind in ("Load", "Store"):
                atoms = [b[0] for b in action["bindings"]]
            elif kind == "Move":
                atoms = [b[0] for b in action["targets"]]
            elif kind == "Measure":
                atoms = [b[0] for b in action["results"]]
            elif kind in ("Rotation", "Reset"):
                atoms = action["atoms"]
            else:
                atoms = [
                    wires[q] for i in action["source_ids"] for q in nodes[i]["qubits"]
                ]
            members = {owner[a] for a in atoms if a in owner}
            category = (
                "transfer"
                if kind in ("Load", "Store")
                else "movement"
                if kind == "Move"
                else "measurement"
                if kind == "Measure"
                else "reset"
                if kind == "Reset"
                else "gate"
                if kind in ("Rotation", "CZPulse")
                else "other"
            )
            resource = (
                "aod:transport"
                if kind in ("Load", "Move", "Store")
                else "camera"
                if kind == "Measure"
                else "rydberg"
                if kind == "CZPulse"
                else "local"
                if kind in ("Rotation", "Reset")
                else "none"
            )
            for member in members:
                costs[member].add(
                    (clock, clock + action["duration_us"], category, resource)
                )
            activity.append(
                (action["duration_us"], {group["member_factories"][m] for m in members})
            )
            if kind == "Measure":
                readout_count += len(atoms)
                for atom in atoms:
                    measurements[owner[atom]].append(
                        [index, trace["device"]["readout"]["latency_us"]]
                    )
            if "grid" in action:
                rows = max(rows, len(action["grid"]["rows"]))
                columns = max(columns, len(action["grid"]["columns"]))
        readout = max(readout, readout_count)
        cuts = sorted({0.0, duration, *(t for t, _ in activity)})
        for a, b in zip(cuts, cuts[1:], strict=False):
            factories = set().union(*(owners for t, owners in activity if t > a))
            peak = max(peak, len(factories))
            if len(factories) > 1:
                overlap += b - a
        clock += duration
    assert (rows, columns, readout) == (
        group["peak_rows"],
        group["peak_columns"],
        group["peak_readout_atoms"],
    )
    assert peak == group["factory_concurrency"]["peak_active_factories"]
    assert isclose(
        overlap, group["factory_concurrency"]["multi_factory_active_us"], abs_tol=1e-7
    )
    for member, item in group["members"].items():
        actual = {
            (s["start_offset_us"], s["end_offset_us"], s["category"], s["resource"])
            for s in item["cost_segments"]
        }
        assert actual == costs[member]
        assert item["measurement_phases"] == measurements[member]
        assert item["primitive_counts"] == dict(primitives[member])


def load_and_audit(root: Path, partial: bool = False):
    """Check exact group membership/timing, stored traces and preparation causality."""
    cases = []
    for d in (3, 5, 7):
        for n in (1, 2, 4):
            directory = root / f"d{d}-n{n}"
            if not (directory / "summary.json").exists() and partial:
                continue
            summary = json.loads(
                (directory / "summary.json").read_text(encoding="utf-8")
            )
            profile = json.loads(
                (directory / "profile.json").read_text(encoding="utf-8")
            )
            case = json.loads((directory / "case.json").read_text(encoding="utf-8"))
            assert summary["seeds"] == [0]
            assert case["coordination_policy"] == "cohort_stage_barriers"
            assert summary["samples"][0]["hardware"]["aod_count"] == 1
            assert summary["samples"][0]["hardware"]["atom_count_estimate"] == 6 * n * (
                2 * d * d - 1
            )
            calls = case["execution"]["calls"]
            by_id = {c["invocation_id"]: c for c in calls}
            assert len(by_id) == len(calls)
            groups = profile["joint_groups"]
            for key, group in groups.items():
                assert key == digest({"members": sorted(group["members"])})
                trace = json.loads(
                    (directory / "groups" / f"{key}.trace.json").read_text(
                        encoding="utf-8"
                    )
                )
                assert digest(trace) == group["trace_sha256"]
                assert trace["validation"]["ok"] is True
                assert trace["entry_state"] == trace["exit_state"]
                audit_native_activity(group, trace)
                assert len(trace["device"]["aods"]) == 1
                assert trace["device"]["timing"]["load_us"] == 10
                assert trace["device"]["timing"]["store_us"] == 10
                assert trace["device"]["readout"]["duration_us"] == 100
                assert trace["device"]["readout"]["latency_us"] == 0
                assert (
                    hashlib.sha256(trace["source_qasm"].encode()).hexdigest()
                    == trace["inputs"]["qasm_sha256"]
                )
                assert len(group["phase_durations_us"]) == len(
                    trace["program"]["steps"]
                )
                for duration, step in zip(
                    group["phase_durations_us"], trace["program"]["steps"], strict=True
                ):
                    assert isclose(
                        duration, max(a["duration_us"] for a in step["actions"])
                    )
                for port in group["raw_ports"].values():
                    evidence = port["model"]["evidence"]
                    assert evidence["joint_trace_sha256"] == group["trace_sha256"]
                    assert evidence["factorized_actual_joint_channels"] is True
                    assert evidence["estimator"]["shots"] == 65536
                    assert (
                        port["outcomes"][0]["probability"]
                        == evidence["estimator"]["accepted"] / 65536
                    )
            batch_calls = defaultdict(list)
            for c in calls:
                assert c["parallel_mode"] == "shared_aod_lockstep"
                assert c["reserved_resources"] == []
                assert c["shared_resources"] == ["aod:transport"]
                batch_calls[c["batch_id"]].append(c)
            previous_end = 0
            witnesses = []
            growth_witnesses = []
            for wave in case["execution"]["waves"]:
                members = batch_calls[wave["batch_id"]]
                keys = {c["joint_group_key"] for c in members}
                assert len(keys) == 1
                group_key = keys.pop()
                group = groups[group_key]
                identities = {
                    c["component_id"] + ":" + ",".join(c["participant_blocks"])
                    for c in members
                }
                assert identities == set(group["members"])
                assert set(wave["invocations"]) == {c["invocation_id"] for c in members}
                assert wave["start_us"] >= previous_end - 1e-7
                assert isclose(
                    wave["end_us"] - wave["start_us"], sum(group["phase_durations_us"])
                )
                previous_end = wave["end_us"]
                for c in members:
                    assert c["joint_trace_sha256"] == group["trace_sha256"]
                    assert (
                        c["start_us"] == wave["start_us"]
                        and c["action_end_us"] == wave["end_us"]
                    )
                    member = c["component_id"] + ":" + ",".join(c["participant_blocks"])
                    phases = group["phase_durations_us"]
                    expected = [
                        wave["start_us"] + sum(phases[: i + 1]) + latency
                        for i, latency in group["members"][member]["measurement_phases"]
                    ]
                    assert len(expected) == len(c["result_availability"])
                    assert all(
                        isclose(a, b["available_at_us"])
                        for a, b in zip(expected, c["result_availability"], strict=True)
                    )
                if (
                    all(
                        c["component_id"] == "raw_t_postselection"
                        and all(b.endswith("/R") for b in c["participant_blocks"])
                        for c in members
                    )
                    and len(
                        {
                            b.split("/")[0]
                            for c in members
                            for b in c["participant_blocks"]
                        }
                    )
                    == n
                ):
                    witnesses.append((wave, group, members))
                growth_members = [
                    c
                    for c in members
                    if c["component_id"] == "raw_t_postselection/canonicalize"
                    and all(b.endswith("/R") for b in c["participant_blocks"])
                ]
                if growth_members:
                    growth_witnesses.append((wave, group, growth_members))
            assert isclose(previous_end, case["duration_us"])
            assert witnesses, "Missing all-factory raw-A wave"
            raw_wave, raw_group, raw_members = witnesses[0]
            growth_wave, growth_group, growth_members = max(
                growth_witnesses, key=lambda item: len(item[2])
            )
            if n > 1:
                assert raw_group["factory_concurrency"]["peak_active_factories"] == n
                assert raw_group["factory_concurrency"]["shared_transport_batches"] > 0
            for m in raw_group["members"].values():
                assert len(m["measurement_phases"]) == 24
                assert len({i for i, _ in m["measurement_phases"]}) >= 3
            accepted = set()
            for event in case["events"]:
                for dep in event["dependencies"]:
                    source = by_id[dep["invocation_id"]]
                    assert event["released_at_us"] >= source["action_end_us"] - 1e-7
                    if (
                        source["component_id"] == "raw_t_postselection"
                        and event["values"]["accepted"]
                    ):
                        accepted.add(
                            source["invocation_id"].removesuffix("/body")
                            + "/canonicalize"
                        )
            assert accepted == {
                c["invocation_id"]
                for c in calls
                if c["component_id"] == "raw_t_postselection/canonicalize"
            }

            def compact(c):
                return {
                    "id": c["invocation_id"],
                    "op": c["component_id"],
                    "blocks": c["participant_blocks"],
                    "start": c["start_us"],
                    "end": c["action_end_us"],
                    "ready": c["results_ready_us"],
                    "group": c["joint_group_key"],
                    "batch": c["batch_id"],
                    "segments": c["cost_segments"],
                }

            cases.append(
                {
                    "d": d,
                    "n": n,
                    "duration": case["duration_us"],
                    "outputs": summary["outputs"],
                    "atoms": summary["samples"][0]["hardware"]["atom_count_estimate"],
                    "fast_seconds": summary["mean_fast_seconds"],
                    "groups": len(groups),
                    "calls": [compact(c) for c in calls],
                    "raw": {
                        "start": raw_wave["start_us"],
                        "end": raw_wave["end_us"],
                        "calls": [compact(c) for c in raw_members],
                        "concurrency": raw_group["factory_concurrency"],
                        "partition": raw_group["schedule"]["time_partition_us"],
                        "transports": raw_group["schedule"]["transport_batches"],
                        "resource_peaks": {
                            k: raw_group[k]
                            for k in ("peak_rows", "peak_columns", "peak_readout_atoms")
                        },
                        "readout_batches_per_member": {
                            member: len({i for i, _ in item["measurement_phases"]})
                            for member, item in raw_group["members"].items()
                        },
                    },
                    "growth": {
                        "start": growth_wave["start_us"],
                        "end": growth_wave["end_us"],
                        "calls": [compact(c) for c in growth_members],
                        "concurrency": growth_group["factory_concurrency"],
                        "partition": growth_group["schedule"]["time_partition_us"],
                        "resource_peaks": {
                            k: growth_group[k]
                            for k in ("peak_rows", "peak_columns", "peak_readout_atoms")
                        },
                        "readout_batches_per_member": {
                            member: len({i for i, _ in item["measurement_phases"]})
                            for member, item in growth_group["members"].items()
                        },
                    },
                    "profile_sha256": summary["profile_sha256"],
                    "source_sha256": summary["source_snapshot_sha256"],
                }
            )
    assert len({c["source_sha256"] for c in cases}) == 1
    return cases


def write_report(root: Path, *, partial: bool = False) -> Path:
    """Save inspectable activity and spans without rescheduling the witnesses."""
    cases = load_and_audit(root, partial)
    output = root / "report"
    output.mkdir(exist_ok=True)
    for c in cases:
        with (output / f"d{c['d']}-n{c['n']}.schedule.csv").open(
            "w", encoding="utf-8", newline=""
        ) as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "invocation",
                    "component",
                    "blocks",
                    "start_us",
                    "end_us",
                    "ready_us",
                    "joint_group",
                ]
            )
            for call in c["calls"]:
                writer.writerow(
                    [
                        call["id"],
                        call["op"],
                        ";".join(call["blocks"]),
                        call["start"],
                        call["end"],
                        call["ready"],
                        call["group"],
                    ]
                )
        with (output / f"d{c['d']}-n{c['n']}.activity.csv").open(
            "w", encoding="utf-8", newline=""
        ) as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "invocation",
                    "component",
                    "blocks",
                    "category",
                    "resource",
                    "start_us",
                    "end_us",
                    "joint_group",
                ]
            )
            for call in c["calls"]:
                for segment in call["segments"]:
                    writer.writerow(
                        [
                            call["id"],
                            call["op"],
                            ";".join(call["blocks"]),
                            segment["category"],
                            segment["resource"],
                            segment["start_us"],
                            segment["end_us"],
                            call["group"],
                        ]
                    )
    summary = [
        {k: v for k, v in c.items() if k not in ("calls", "raw", "growth")}
        | {
            "raw_wave_us": c["raw"]["end"] - c["raw"]["start"],
            "raw_factory_concurrency": c["raw"]["concurrency"],
            "raw_time_partition_us": c["raw"]["partition"],
            "raw_readout_batches_per_member": c["raw"]["readout_batches_per_member"],
        }
        for c in cases
    ]
    audit = {
        "passed": True,
        "complete_grid": len(cases) == 9,
        "cohort_policy": "retained",
        "aod_count": 1,
        "seeds": [0],
        "case_count": len(cases),
        "call_count": sum(len(c["calls"]) for c in cases),
        "joint_calibrations": sum(c["groups"] for c in cases),
        "checks": [
            "trace content hashes",
            "physical validation receipts",
            "return-home world equality",
            "unchanged device timings",
            "actual joint group coverage and phase times",
            "measurement availability",
            "accepted-only growth",
            "cross-factory raw transport",
            "cohort barriers retained",
            "no exclusive AOD component leases",
            "native activity and peaks independently reconstructed from atom actions",
        ],
        "scope": "resource schedules from validated joint wave fragments; no noisy output LER",
    }
    for name, value in [("summary", summary), ("audit", audit)]:
        (output / f"{name}.json").write_text(
            json.dumps(value, indent=2) + "\n", encoding="utf-8"
        )
    table = "".join(
        "<tr>"
        + "".join(
            f"<td>{html.escape(str(x))}</td>"
            for x in (
                c["d"],
                c["n"],
                f"{c['duration'] / 1000:.3f}",
                c["outputs"],
                f"{(c['raw']['end'] - c['raw']['start']) / 1000:.3f}",
                c["groups"],
            )
        )
        + "</tr>"
        for c in cases
    )
    payload = json.dumps(cases, separators=(",", ":")).replace("<", "\\u003c")
    document = r"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>NADiT one-AOD joint factory schedules</title><style>
body{font:14px system-ui;color:#17334b;background:#f4f7fa;margin:20px}h1{font-size:25px}p{line-height:1.5}.note{padding:12px;background:#e4f2ec;border-left:4px solid #23876b}.controls,.cards,.legend{display:flex;gap:12px;flex-wrap:wrap;margin:16px 0;align-items:center}select,input,button{font:inherit;padding:7px}.card{padding:12px;background:white;border:1px solid #d3dfe8;border-radius:8px}.card b{display:block;font-size:21px}.chart{background:white;border:1px solid #d3dfe8;overflow:auto}svg{display:block}rect.activity,rect.component{cursor:pointer;stroke:white;stroke-width:.3}rect.activity:hover,rect.component:hover{stroke:#112c45;stroke-width:2}.legend span:before{content:'';background:var(--c);display:inline-block;width:12px;height:12px;margin-right:5px}pre{white-space:pre-wrap;padding:12px;background:#e8eef3}table{border-collapse:collapse;background:white;width:100%}td,th{text-align:left;padding:8px;border-bottom:1px solid #ddd}th{background:#e8eef3}.table{overflow:auto}.small{color:#536e80;font-size:12px}
</style><h1>One AOD · jointly compiled factory schedules</h1><p>STATUS · LOAD / STORE 10 µs · measurement 100 µs · processing 0 · original vertical layout and 50 µm gap</p>
<div class="note"><b>Single shared AOD; cohort stage barriers retained.</b> All operations in each admitted wave were compiled together in the same complete device world. Raw-A and growth views show native activity from the validated joint trace. The complete-cycle view shows component spans, including internal waits. No independent AOD substitution, no whole-component exclusive AOD lease. Seed 0 witnesses; accepted-input error p=0.01 is an ideal-Clifford reference, not measured output LER.</div>
<div class="controls"><label>Case <select id="case" aria-label="Factory case"></select></label><label>View <select id="view" aria-label="Schedule scope"><option value="raw">Joint raw-A / three SE rounds</option><option value="growth">Accepted growth / target SE</option><option value="full">Complete factory cycle</option></select></label><label>Zoom <input type="range" id="zoom" aria-label="Time zoom" min="1" max="12" step=".5" value="1"></label><button id="fit">Fit</button></div>
<div id="cards" class="cards"></div><div class="legend" id="legend"><span style="--c:#2b78b9">Movement</span><span style="--c:#d7952b">LOAD / STORE</span><span style="--c:#348c72">Gate</span><span style="--c:#c15d69">Measurement</span><span style="--c:#876db1">Reset</span><span style="--c:#e3e8ee">Call span / waiting</span></div>
<p class="small">The axis is relative to the selected window; clicked details use absolute time. Raw-A contains three SE rounds and 24 outcomes per factory. Growth uses d ordinary target SE rounds (no growth at d=3). Red bars are readout batches: one SE round may use several batches.</p><div class="chart" id="chart"></div><pre id="detail">Click an activity segment to inspect its component, exact time and joint trace key.</pre><pre id="proof"></pre>
<h2>Complete seed-0 witnesses</h2><p class="small">Duration includes preparation retries and rejected final batches. This table is not a steady-state throughput estimate. Each N uses the same one-AOD hardware.</p><div class="table"><table><thead><tr><th>d</th><th>N</th><th>Factory ms</th><th>Outputs</th><th>Joint raw-A ms</th><th>Calibrations</th></tr></thead><tbody>TABLE</tbody></table></div>
<script id="data" type="application/json">PAYLOAD</script><script>
const cases=JSON.parse(document.getElementById('data').textContent),sel=document.getElementById('case'),view=document.getElementById('view'),zoom=document.getElementById('zoom');cases.forEach((c,i)=>{let o=document.createElement('option');o.value=i;o.textContent=`d=${c.d}, N=${c.n}, one shared AOD`;sel.append(o)});sel.value=Math.max(0,cases.findIndex(c=>c.d===5&&c.n===4));
const ns='http://www.w3.org/2000/svg',colors={movement:'#2b78b9',transfer:'#d7952b',gate:'#348c72',measurement:'#c15d69',reset:'#876db1',other:'#6a7d89'};function el(t,a,text){let e=document.createElementNS(ns,t);for(let[k,v]of Object.entries(a))e.setAttribute(k,v);if(text!==undefined)e.textContent=text;return e}
function componentColor(op){return op==='raw_t_postselection'?'#2b78b9':op==='raw_t_postselection/canonicalize'?'#d7952b':op==='transversal_cnot'?'#348c72':op==='logical_s'?'#876db1':op==='logical_mx'||op==='logical_mz'?'#c15d69':'#708295'}
function draw(){let c=cases[+sel.value],raw=view.value!=='full',sample=raw?c[view.value]:null,calls=raw?sample.calls:c.calls,start=raw?sample.start:0,end=raw?sample.end:c.duration,blocks=[...new Set(calls.flatMap(x=>x.blocks))].sort((a,b)=>Number(a.split('/')[0].slice(7))-Number(b.split('/')[0].slice(7))||['W1','W2','W3','W4','W5','R'].indexOf(a.split('/')[1])-['W1','W2','W3','W4','W5','R'].indexOf(b.split('/')[1])),width=Math.max(520,document.getElementById('chart').clientWidth-6)*+zoom.value,left=130,row=31,top=38,height=top+blocks.length*row+24,scale=(width-left-25)/(end-start),svg=el('svg',{width,height,role:'img','aria-label':'Actual shared AOD joint activity'});document.getElementById('detail').textContent=raw?'Click a native activity segment for exact times and its source group.':'Click a component span for start/end times, participants and its source group.';let lg=document.getElementById('legend');lg.replaceChildren();let labels=raw?[['Movement','#2b78b9'],['LOAD / STORE','#d7952b'],['Gate','#348c72'],['Measurement','#c15d69'],['Reset','#876db1'],['Span / waiting','#e3e8ee']]:[['Raw-A','#2b78b9'],['Growth / correction','#d7952b'],['CNOT','#348c72'],['S','#876db1'],['Logical readout','#c15d69'],['Other','#708295']];for(let[label,color]of labels){let s=document.createElement('span');s.style.setProperty('--c',color);s.textContent=label;lg.append(s)};let card=document.getElementById('cards');card.replaceChildren();for(let[label,value]of [['Shown time',end-start<1000?`${(end-start).toFixed(3)} µs`:`${((end-start)/1000).toFixed(3)} ms`],['Whole factory',`${(c.duration/1000).toFixed(3)} ms`],['Factories / AODs',`${c.n} / 1`],['Atoms',c.atoms]]){let div=document.createElement('div');div.className='card';div.textContent=label;let b=document.createElement('b');b.textContent=value;div.append(b);card.append(div)}
blocks.forEach((b,i)=>{svg.append(el('rect',{x:0,y:top+i*row,width,height:row,fill:i%2?'#f3f6f9':'white'}));svg.append(el('text',{x:6,y:top+i*row+20,'font-size':12,fill:'#304d64'},b))});let ticks=Math.max(2,Math.floor((width-left-25)/95));for(let i=0;i<=ticks;i++){let t=(end-start)*i/ticks,x=left+t*scale;svg.append(el('line',{x1:x,x2:x,y1:28,y2:height-12,stroke:'#dce3e9'}));svg.append(el('text',{x,y:19,'font-size':11,'text-anchor':'middle',fill:'#36556c'},end-start<1000?`${t.toFixed(2)} µs`:`${(t/1000).toFixed(2)} ms`))}
for(let call of calls)for(let block of call.blocks){let i=blocks.indexOf(block),y=top+i*row+5;let span=el('rect',{class:raw?'span':'component',x:left+(call.start-start)*scale,y,width:Math.max(.5,(call.end-call.start)*scale),height:21,fill:raw?'#e3e8ee':componentColor(call.op),rx:2});span.addEventListener('click',()=>document.getElementById('detail').textContent=JSON.stringify({invocation:call.id,component:call.op,blocks:call.blocks,start_us:call.start,end_us:call.end,results_ready_us:call.ready,joint_group:call.group,meaning:'Admitted component span, including within-wave wait'},null,2));svg.append(span);if(!raw)continue;for(let seg of call.segments){let rect=el('rect',{class:'activity',x:left+(seg.start_us-start)*scale,y:y+2,width:Math.max(.5,(seg.end_us-seg.start_us)*scale),height:17,fill:colors[seg.category]||colors.other});rect.append(el('title',{},`${call.op} · ${seg.category}\n${seg.start_us.toFixed(3)} → ${seg.end_us.toFixed(3)} µs`));rect.addEventListener('click',()=>document.getElementById('detail').textContent=JSON.stringify({invocation:call.id,component:call.op,blocks:call.blocks,activity:seg,joint_group:call.group,batch:call.batch},null,2));svg.append(rect)}}document.getElementById('chart').replaceChildren(svg);document.getElementById('proof').textContent=raw?JSON.stringify({physical_factory_concurrency:sample.concurrency,actual_joint_resource_peaks:sample.resource_peaks,readout_batches_per_member:sample.readout_batches_per_member,time_partition_us:sample.partition,full_wave_trace:'Referenced by each component activity; atoms return home'},null,2):'Complete factory schedule. Cohort barriers and shared-device wave boundaries are retained. Click a colored segment for its source group.'}
sel.addEventListener('change',draw);view.addEventListener('change',draw);zoom.addEventListener('input',draw);document.getElementById('fit').addEventListener('click',()=>{zoom.value=1;draw()});draw();</script></html>"""
    path = output / "index.html"
    path.write_text(
        document.replace("TABLE", table)
        .replace("PAYLOAD", payload)
        .replace(
            "STATUS",
            "Partial preview" if partial else "Complete 9-case acceptance grid",
        ),
        encoding="utf-8",
    )
    if not partial:
        write_scaling(output, cases)
    return path


def write_scaling(output: Path, cases):
    """Plot same-device seed-0 timings; these are not sample means or LER estimates."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(10, 4), layout="constrained")
    for d in (3, 5, 7):
        rows = [c for c in cases if c["d"] == d]
        for axis, values in zip(
            axes,
            (
                [c["duration"] / 1000 for c in rows],
                [(c["raw"]["end"] - c["raw"]["start"]) / 1000 for c in rows],
            ),
            strict=True,
        ):
            axis.plot([c["n"] for c in rows], values, "o-", label=f"d={d}")
    for axis, title in zip(
        axes,
        ("Complete factory cycle (seed 0)", "Joint raw-A / three d3 SE rounds"),
        strict=True,
    ):
        axis.set(
            title=title,
            xlabel="Factories N (one shared AOD)",
            ylabel="Time (ms)",
            xticks=[1, 2, 4],
        )
        axis.grid(alpha=0.2)
        axis.legend()
    fig.savefig(output / "scaling.png", dpi=180)
    plt.close(fig)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--partial", action="store_true")
    args = parser.parse_args()
    print(write_report(args.root, partial=args.partial))
