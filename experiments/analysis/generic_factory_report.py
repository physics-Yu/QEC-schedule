"""Inspectable time schedules and scaling plots from saved fast-factory cases."""

import argparse
import html
import json
from pathlib import Path


def write_report(directory: Path) -> Path:
    """Embed complete witness calls with resource and patch lanes; no rescheduling."""
    report = json.loads((directory / "summary.json").read_text(encoding="utf-8"))
    cases = []
    for row in report["results"]:
        case = json.loads((directory / row["witness"]).read_text(encoding="utf-8"))
        cases.append(
            {
                **row,
                "label": f"d={row['distance']} | N={row['factory_count']} | {row['hardware']}",
                "duration": case["duration_us"],
                "calls": [
                    {
                        "id": c["invocation_id"],
                        "op": c["component_id"],
                        "start": c["start_us"],
                        "end": c["action_end_us"],
                        "ready": c["results_ready_us"],
                        "blocks": c["participant_blocks"],
                        "resources": c.get("reserved_resources", []),
                    }
                    for c in case["execution"]["calls"]
                ],
                "events": case["events"],
            }
        )
    payload = json.dumps(cases, separators=(",", ":"), allow_nan=False).replace(
        "<", "\\u003c"
    )
    table = "".join(
        "<tr>"
        + "".join(
            f"<td>{html.escape(str(v))}</td>"
            for v in (
                r["distance"],
                r["factory_count"],
                r["hardware"],
                f"{r['mean_makespan_us'] / 1000:.3f}",
                f"{r['observed_outputs_per_second']:.2f}",
                f"{r['mean_software_seconds'] * 1000:.2f}",
                r["outputs"],
                r["independent_seed_count"],
            )
        )
        + "</tr>"
        for r in report["results"]
    )
    document = r"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>NADiT generic factory schedules</title><style>
body{font:14px system-ui,sans-serif;color:#183047;background:#f5f7fa;margin:24px}h1{font-size:26px;margin-bottom:8px}.note{background:#fff3cf;border-left:4px solid #cf8b24;padding:12px;max-width:1100px;line-height:1.5}.controls,.cards{display:flex;gap:16px;flex-wrap:wrap;align-items:center;margin:18px 0}select,input,button{font:inherit;padding:7px}select{min-width:380px}.card{background:white;border:1px solid #dce2eb;padding:12px 20px;border-radius:8px}.card b{display:block;font-size:22px}.chart{overflow:auto;background:white;border:1px solid #dce2eb;max-height:760px}svg{display:block}rect.call{cursor:pointer;stroke:#fff;stroke-width:.4}rect.call:hover{stroke:#172d42;stroke-width:2}.legend{display:flex;gap:18px;flex-wrap:wrap;margin:12px 0}.legend span:before{content:'';display:inline-block;width:12px;height:12px;background:var(--c);margin-right:5px}pre{white-space:pre-wrap;background:#eaf0f5;padding:12px;min-height:70px}table{border-collapse:collapse;background:white;width:100%;margin-top:16px}th,td{padding:8px;border-bottom:1px solid #dce2eb;text-align:left;font-variant-numeric:tabular-nums}th{background:#e8eef4}small{color:#567}.summary{overflow:auto}a{color:#176b9c}
</style><h1>Generic surface-code factory · time schedules</h1>
<p>LOAD / STORE 10 µs · readout 100 µs · classical processing 0 · d3 injection (3 rounds), then d target growth rounds · actual S implementation</p>
<div class="note"><b>Resource estimates from position-specific physical calibration.</b> Shared-AOD runs reserve transport-bearing components until their atoms return home: a conservative schedule, without unvalidated co-batching. Independent-module controls add AODs and assume separately addressable control; they are not a same-budget speedup. Final checks use assumed iid input Z error p=0.01; output LER is not measured. These are finite one-batch trajectories.</div>
<div class="controls"><label>Witness <select id="case" aria-label="Witness schedule"></select></label><label>Time zoom <input id="zoom" aria-label="Time zoom" type="range" min="1" max="10" step=".5" value="1"></label><button id="reset">Fit full schedule</button></div>
<div class="cards" id="cards"></div><div class="legend"><span style="--c:#2877b5">d3 injection</span><span style="--c:#d9922b">Growth + correction</span><span style="--c:#20887d">CNOT</span><span style="--c:#8663ac">S / feedback</span><span style="--c:#c35a63">Readout</span><span style="--c:#6b7b8c">Other / correction</span><span style="--c:#ba8aaa">AOD reservation</span></div>
<div class="chart" id="chart"></div><pre id="detail">Click a call to inspect absolute times, participants and resource reservations. Blank intervals are waiting/idle on that patch; multi-patch calls appear on both participants.</pre>
<h2>Fixed seed grid</h2><p>16 independent seeded trajectories per cell; output rate = total outputs / total modeled time. Software time excludes profile loading and export. See adjacent CSV and case JSON files for the full witness.</p>
<div class="summary"><table><thead><tr><th>d</th><th>N</th><th>Hardware</th><th>Mean makespan (ms)</th><th>Outputs/s</th><th>Fast run (ms)</th><th>Outputs</th><th>Seeds</th></tr></thead><tbody>TABLE</tbody></table></div>
<script id="data" type="application/json">PAYLOAD</script><script>
const cases=JSON.parse(document.getElementById('data').textContent),select=document.getElementById('case'),zoom=document.getElementById('zoom');
cases.forEach((c,i)=>{const o=document.createElement('option');o.value=i;o.textContent=c.label;select.append(o)});
select.value=Math.max(0,cases.findIndex(c=>c.distance===5&&c.factory_count===4&&c.hardware==='shared_aod'));
const ns='http://www.w3.org/2000/svg';function element(tag,attrs,text){const e=document.createElementNS(ns,tag);for(const[k,v]of Object.entries(attrs))e.setAttribute(k,v);if(text!==undefined)e.textContent=text;return e}
function color(op){return op==='raw_t_postselection'?'#2877b5':op==='raw_t_postselection/canonicalize'?'#d9922b':op==='transversal_cnot'?'#20887d':op==='logical_s'?'#8663ac':op==='logical_mx'||op==='logical_mz'?'#c35a63':'#6b7b8c'}
function render(){const c=cases[+select.value],resources=[...new Set(c.calls.flatMap(x=>x.resources))].sort(),blocks=[];for(let i=0;i<c.factory_count;i++)for(const r of ['W1','W2','W3','W4','W5','R'])blocks.push(`factory${i}/${r}`);const lanes=[...resources,...blocks],left=155,top=36,row=25,width=Math.max(520,document.getElementById('chart').clientWidth-12)*Number(zoom.value),height=top+row*lanes.length+40,scale=(width-left-25)/c.duration,svg=element('svg',{width,height,role:'img','aria-label':'Complete factory and AOD time schedule'});const cards=document.getElementById('cards');cards.replaceChildren();for(const[label,value]of [['Witness duration',`${(c.duration/1000).toFixed(3)} ms`],['Complete calls',c.calls.length],['Atoms',c.atoms],['AODs',c.aod_count]]){const d=document.createElement('div');d.className='card';d.textContent=label;const b=document.createElement('b');b.textContent=value;d.append(b);cards.append(d)}
lanes.forEach((lane,i)=>{svg.append(element('rect',{x:0,y:top+i*row,width,height:row,fill:i%2?'#f4f7fa':'white'}));svg.append(element('text',{x:8,y:top+i*row+17,fill:'#344d61','font-size':12},lane))});
const ticks=Math.max(2,Math.floor((width-left-25)/90));for(let i=0;i<=ticks;i++){const t=c.duration*i/ticks,x=left+t*scale;svg.append(element('line',{x1:x,x2:x,y1:top-8,y2:height-25,stroke:'#dbe2e9'}));svg.append(element('text',{x,y:20,'text-anchor':'middle',fill:'#425d72','font-size':11},`${(t/1000).toFixed(1)} ms`))}
for(const call of c.calls){for(const lane of [...call.resources,...call.blocks]){const i=lanes.indexOf(lane);if(i<0)continue;const rect=element('rect',{class:'call',x:left+call.start*scale,y:top+i*row+4,width:Math.max(.8,(call.end-call.start)*scale),height:17,rx:2,fill:lane.startsWith('aod:')?'#ba8aaa':color(call.op)});rect.append(element('title',{},`${call.id}\n${call.start.toFixed(3)} → ${call.end.toFixed(3)} µs`));rect.addEventListener('click',()=>document.getElementById('detail').textContent=JSON.stringify(call,null,2));svg.append(rect)}}document.getElementById('chart').replaceChildren(svg)}
select.addEventListener('change',render);zoom.addEventListener('input',render);document.getElementById('reset').addEventListener('click',()=>{zoom.value=1;render()});render();
</script></html>"""
    path = directory / "time-schedules.html"
    path.write_text(
        document.replace("TABLE", table).replace("PAYLOAD", payload), encoding="utf-8"
    )
    return path


def write_plot(directory: Path) -> None:
    """Save publication-independent scaling figures with hardware controls split."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    data = json.loads((directory / "summary.json").read_text(encoding="utf-8"))
    fig, axes = plt.subplots(1, 2, figsize=(10, 4), layout="constrained")
    for axis, hardware, title in zip(
        axes,
        ("shared_aod", "independent_aod_control"),
        ("One shared AOD (conservative)", "Independent module hardware (control)"),
        strict=True,
    ):
        for d in data["plan"]["distances"]:
            rows = [
                r
                for r in data["results"]
                if r["distance"] == d and r["hardware"] == hardware
            ]
            axis.plot(
                [r["factory_count"] for r in rows],
                [r["mean_makespan_us"] / 1000 for r in rows],
                "o-",
                label=f"d={d}",
            )
        axis.set(
            xlabel="Factory modules N",
            ylabel="Mean one-batch makespan (ms)",
            title=title,
            xticks=data["plan"]["factory_counts"],
        )
        axis.legend()
        axis.grid(alpha=0.2)
    fig.savefig(directory / "scaling.png", dpi=180)
    plt.close(fig)


def main() -> None:
    """Render saved fast results; never run a compiler or change their schedules."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    print(write_report(args.directory))
    write_plot(args.directory)


if __name__ == "__main__":
    main()
