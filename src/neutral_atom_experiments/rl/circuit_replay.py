"""Circuit and real physical replay on one page, without changing the viewer."""
from html import escape
from pathlib import Path
from neutral_atom_env.replay.serializer import canonical_json
from neutral_atom_env.visualization.viewer import javascript


def write_circuit_replay(case,payload,path,*,label=''):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    gates=[{'id':f'g{i:04d}','kind':kind,'qubits':[f'Q{q:03d}' for q in qs]} for i,(kind,qs) in enumerate(case['gates'])]
    # Layer assignment only draws the input DAG; it does not schedule execution.
    next_layer=[0]*case['atom_count'];markup=[];occupied={}
    for gate in gates:
        indices=[int(q[1:]) for q in gate['qubits']]
        layer=max(next_layer[q] for q in indices)
        # Interleaved disjoint CZ pairs must not share one vertical line:
        # that would visually suggest a many-atom gate.
        span=set(range(min(indices),max(indices)+1))
        while span & occupied.get(layer,set()):layer+=1
        occupied.setdefault(layer,set()).update(span)
        for q in indices:next_layer[q]=layer+1
        gate['layer']=layer;x=110+80*layer;ys=[45+48*q for q in indices]
        shapes=f'<line x1="{x}" y1="{min(ys)}" x2="{x}" y2="{max(ys)}" stroke="currentColor" stroke-width="3"/>' if len(ys)>1 else ''
        for y in ys:
            shapes+=f'<rect x="{x-23}" y="{y-17}" width="46" height="34" rx="7" fill="white" stroke="currentColor"/><text x="{x}" y="{y+5}" text-anchor="middle">{gate["kind"]}</text>'
        title=escape(gate['id']+' '+gate['kind']+' '+', '.join(gate['qubits']))
        markup.append(f'<g class="gate pending" id="{gate["id"]}" tabindex="0" role="button" aria-label="{title}"><title>{title}</title>{shapes}<text x="{x}" y="{min(ys)-22}" class="gate-id" text-anchor="middle">{gate["id"]}</text></g>')
    width=max(680,130+80*max(next_layer));height=60+48*case['atom_count']
    wires=''.join(f'<text x="10" y="{50+48*q}">Q{q:03d}</text><line x1="78" y1="{45+48*q}" x2="{width-20}" y2="{45+48*q}" stroke="#c9d3e2"/>' for q in range(case['atom_count']))
    data=canonical_json({'case':case,'gates':gates,'recording':payload}).replace('<',r'\u003c')
    html='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>电路与原子执行回放</title>
<style>body{margin:0;background:#f4f6fa;font:15px system-ui;color:#26334b}header,section.circuit{margin:16px;padding:18px;background:white;border-radius:14px}h1{font-size:22px;margin:0 0 10px}p{line-height:1.6}.circuit-scroll{overflow:auto}svg{font:14px system-ui}.gate{cursor:pointer;transition:color .1s}.pending{color:#65728c}.preparing{color:#d47712}.active{color:#d52d78}.complete{color:#21866d}.active rect{fill:#ffe3ef}.complete rect{fill:#e6f8ee}.preparing rect{fill:#fff0d8}.gate-id{font-size:10px}#circuit-status{font-weight:600;min-height:24px}a{color:#4159ab}</style><body>'''
    html+=f'<header><h1>{escape(label or case["name"])}</h1><p>完整输入电路与真实物理回放。点击任意门跳到其真实光脉冲；播放、暂停或拖动时间轴时电路同步更新。横向位置用于展示门顺序和避免连线重叠，实际并行以回放为准。</p><a href="case.json">下载所示输入电路 JSON</a></header>'
    html+=f'<section class="circuit"><div id="circuit-status">正在载入</div><p>灰：待执行　橙：运输/准备　粉：实际门脉冲　绿：门已完成（可能仍需归还）</p><div class="circuit-scroll"><svg width="{width}" height="{height}" role="img" aria-label="完整输入量子电路">{wires}{"".join(markup)}</svg></div></section><div id="atom-viewer"></div>'
    html+='<script>'+javascript().replace('</script',r'<\/script')+'\nconst experiment='+data+';\n'
    html+='''const recording=experiment.recording;
const viewer=window.NeutralAtomViewer.mount(document.getElementById('atom-viewer'),recording);
window.circuitReplay={viewer,experiment};
const pulses=new Map();
for(const op of recording.operations){if(['raman_rotation','entangling_pulse','measurement','reset'].includes(op.kind))for(const id of op.gate_ids||[]){if(pulses.has(id))throw Error('Duplicate gate pulse '+id);pulses.set(id,op);}}
for(const gate of experiment.gates){const el=document.getElementById(gate.id),op=pulses.get(gate.id);if(!op)throw Error('Missing gate pulse '+gate.id);const seek=()=>viewer.setTime((op.start+op.end)/2);el.onclick=seek;el.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();seek();}};}
let previous=-1;
function sync(){const t=viewer.getStatus().time_us;if(t!==previous){previous=t;const active=[],preparing=[];let complete=0;
for(const gate of experiment.gates){const pulse=pulses.get(gate.id);const plan=recording.plans.find(p=>p.id===pulse.plan_id);const ops=recording.operations.filter(o=>o.plan_id===pulse.plan_id);const start=Math.min(...ops.map(o=>o.start)),end=Math.max(...ops.map(o=>o.end));let state='pending';if(t>=pulse.end){state='complete';complete++;}else if(t>=pulse.start){state='active';active.push(gate.id+' '+gate.kind);}else if(t>=start&&t<end){state='preparing';preparing.push(gate.id);}document.getElementById(gate.id).setAttribute('class','gate '+state);}
document.getElementById('circuit-status').textContent=t.toFixed(3)+' μs · 已完成 '+complete+'/'+experiment.gates.length+' · '+(active.length?'正在作用：'+active.join('、'):preparing.length?'正在为这些门准备运输：'+preparing.join('、'):'运输/清理或等待下一个门');}
requestAnimationFrame(sync);}sync();
</script></body></html>'''
    path.write_text(html,encoding='utf-8')
    (path.parent/'case.json').write_text(canonical_json(case),encoding='utf-8')
    (path.parent/'recording.json').write_text(canonical_json(payload),encoding='utf-8')
    return path
