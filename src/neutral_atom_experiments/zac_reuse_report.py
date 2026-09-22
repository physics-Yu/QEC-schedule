"""Read-only ZAC circuit/reuse overlays around the shared physical viewer."""
from html import escape
from pathlib import Path
from neutral_atom_env.replay.serializer import canonical_json
from neutral_atom_env.visualization.viewer import javascript

STYLE = '''body{margin:0;background:#f4f6fb;color:#26334b;font:15px system-ui}header,section{margin:18px;padding:22px;background:white;border:1px solid #e2e6f0;border-radius:14px}h1{font-size:24px;margin:0 0 10px}h2{font-size:18px}p{line-height:1.7}a{color:#425dc0}button,select{font:inherit;padding:9px 14px;border:1px solid #cdd5e7;border-radius:8px;background:#fff;cursor:pointer}button:hover{background:#eef2ff}.eyebrow{font-size:12px;letter-spacing:2px;color:#6f7894}.scroll{overflow:auto}.gate{cursor:pointer}.pending{color:#758199}.active{color:#d52d78}.complete{color:#168669}.active rect{fill:#ffe3ef}.complete rect{fill:#e6f8ee}.gate-id{font-size:10px}table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}th,td{padding:12px;border-bottom:1px solid #e7ebf3;text-align:left}.bad{color:#b72d42}.good{color:#178366}.chips{display:flex;flex-wrap:wrap;gap:8px}.note{font-size:13px;color:#66718a}iframe{width:100%;height:1300px;border:0}#circuit-status,#reuse-status{min-height:26px;font-weight:600}'''


def head(title):
    return ('<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{escape(title)}</title><style>{STYLE}</style><body>')


def write_replay(spec, placement, result, payload, path):
    n = spec['atom_count']
    next_layer = [0]*n
    occupied = {}
    gates = []
    markup = []
    for i,pair in enumerate(spec['pairs']):
        layer = max(next_layer[q] for q in pair)
        span = set(range(min(pair), max(pair)+1))
        while occupied.get(layer,set()) & span:
            layer += 1
        occupied.setdefault(layer,set()).update(span)
        for q in pair:
            next_layer[q] = layer+1
        x = 115+78*layer
        ys = [48+46*q for q in pair]
        gid = f'g{i:04d}'
        gates.append(dict(id=gid,qubits=[f'Q{q:03d}' for q in pair]))
        title = f'{gid} CZ Q{pair[0]:03d} Q{pair[1]:03d}'
        shapes = f'<line x1="{x}" y1="{min(ys)}" x2="{x}" y2="{max(ys)}" stroke="currentColor" stroke-width="2"/>'
        for y in ys:
            shapes += f'<rect x="{x-22}" y="{y-15}" width="44" height="30" rx="6" fill="white" stroke="currentColor"/><text x="{x}" y="{y+5}" text-anchor="middle">CZ</text>'
        markup.append(f'<g id="{gid}" class="gate pending" role="button" tabindex="0" aria-label="{title}"><title>{title}</title>{shapes}<text x="{x}" y="{min(ys)-21}" text-anchor="middle" class="gate-id">{gid}</text></g>')
    width = max(640,150+78*max(next_layer))
    wires = ''.join(f'<text x="10" y="{53+46*q}">Q{q:03d}</text><line x1="78" y1="{48+46*q}" x2="{width-20}" y2="{48+46*q}" stroke="#d3daea"/>' for q in range(n))
    mode = 'Reuse 开启' if result['reuse_enabled'] else 'Reuse 关闭'
    html = head(f'ZAC · {mode}')
    html += f'<header><div class="eyebrow">ZAC → PHYSICAL EXECUTION</div><h1>{escape(spec["name"])} · {mode}</h1><p>完整输入电路 → 作者分层与复用/布局 → 实际装卸和路径 → Executor → 共用回放。</p><p class="note">电路横坐标用于排版，真实并行以 CZ 脉冲为准。原子坐标来自已提交状态；32× 仅改变播放速度。</p></header>'
    if 'initial_placement' in result:
        method = result['initial_placement']['method']
        label = '作者 SA 优化初态' if method == 'sa' else '固定编号顺序初态'
        html += f'<section><p><strong>{label}</strong>；终态统一恢复固定编号顺序的 holder、SLM 开关和 AOD 轴 / 开关。运行前制备初态的成本不计入本次物理时间。</p></section>'
    if result['status'] != 'completed':
        html += f'<section class="bad"><h2>执行未完成：以下仅为已执行前缀</h2><p>完成 {result["metrics"].get("completed_gate_count",0)} / {len(spec["pairs"])} 个 CZ；不计算完整运行的加速比。</p><p>{escape(str(result.get("error") or result.get("replay_error") or "完整性审计未通过"))}</p></section>'
    html += f'<section><h2>完整 CZ 电路</h2><div id="circuit-status"></div><div class="scroll" style="max-height:520px"><svg width="{width}" height="{80+46*n}" aria-label="完整 CZ 电路">{wires}{"".join(markup)}</svg></div><p class="note">点击门定位实际脉冲。灰色待执行，粉色正在作用，绿色已完成；门完成后仍可能需要归还。大线路可在电路区域内横向和纵向滚动。</p></section>'
    html += '<section><h2>跨层驻留</h2><div id="reuse-status"></div><div class="chips">'
    for i,layer in enumerate(placement['gate_layers']):
        qs = placement['selected_reuse'][i]
        names = ', '.join(f'Q{q:03d}' for q in qs) or '无'
        proposed = ', '.join(f'Q{q:03d}' for q in placement['matching_reuse'][i]) or '无'
        label = names if n <= 16 else f'{len(qs)} 原子'
        html += f'<button data-stage="{i}">层 {i+1} · {len(layer)} CZ · 留驻 {label}</button>'
        if n <= 16:
            html += f'<span class="note">匹配候选：{proposed}</span>'
        else:
            html += f'<details class="note"><summary>层 {i+1} 原子编号</summary>留驻：{names}<br>匹配候选：{proposed}</details>'
    html += '</div><p class="note">Reuse 为纠缠区 SLM 驻留。作者 placement 会评估并可能放弃匹配候选。每个按钮跳到该层之后的真实边界。</p></section><div id="atom-viewer"></div>'
    data = canonical_json(dict(gates=gates,result=result,recording=payload)).replace('<',r'\u003c')
    html += '<script>'+javascript().replace('</script',r'<\/script')+'\nconst experiment='+data+';\n'
    html += '''const viewer=window.NeutralAtomViewer.mount(document.getElementById('atom-viewer'),experiment.recording,{gridStepUm:10,showCandidateSites:false,compact:true});
window.zacReplay={viewer,experiment};
const pulses=new Map();for(const op of experiment.recording.operations)if(op.kind==='entangling_pulse')for(const id of op.gate_ids||[])pulses.set(id,op);
for(const gate of experiment.gates){const el=document.getElementById(gate.id),op=pulses.get(gate.id);if(!op){el.setAttribute('aria-disabled','true');continue;}const seek=()=>viewer.setTime((op.start+op.end)/2);el.onclick=seek;el.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();seek();}};}
document.querySelectorAll('[data-stage]').forEach(button=>button.onclick=()=>{const b=experiment.result.boundaries[Number(button.dataset.stage)];if(b)viewer.setTime(b.end_us);});
let previous=-1;function sync(){const t=viewer.getStatus().time_us;if(t!==previous){previous=t;let completed=0;const active=[];
for(const gate of experiment.gates){const op=pulses.get(gate.id);let state='pending';if(op&&t>=op.end){state='complete';completed++;}else if(op&&t>=op.start){state='active';active.push(gate.id);}document.getElementById(gate.id).setAttribute('class','gate '+state);}
document.getElementById('circuit-status').textContent=t.toFixed(3)+' μs · 已完成 '+completed+'/'+experiment.gates.length+' 门'+(active.length?' · 脉冲：'+active.join(', '):'');
const retained=experiment.result.reuse_audit.filter(r=>t>=r.start_us&&t<r.end_us);
document.getElementById('reuse-status').textContent=retained.length?retained.map(r=>r.atom+' 留在 '+r.holder).join('；'):'当前不在跨层驻留区间';}
requestAnimationFrame(sync);}sync();</script></body></html>'''
    Path(path).write_text(html,encoding='utf-8')


def write_comparison(report, path):
    a,b = (report['results'][k] for k in ('no_reuse','reuse'))
    html = head('ZAC Reuse · 物理执行对照')
    html += '<header><div class="eyebrow">REPRODUCTION / REUSE AWARE</div><h1>ZAC 跨层复用 · 物理执行对照</h1>'
    html += f'<p>{escape(report["spec"]["name"])} · {report["spec"]["atom_count"]} 原子 · {len(report["spec"]["pairs"])} 个 CZ</p>'
    html += '<p>直接运行作者的 ASAP、二分匹配、动态 placement（含 reuse 筛选）；两组使用同初态、同平台、同 CZ 电路、同末尾归还条件。运输批次和连续路径由我们的策略生成，并经真实 Executor 执行及独立重放。</p>'
    html += '<p class="note">这是算法接入与 CZ 电路物理复现，尚未复现论文全套 benchmark / 保真度图。单 AOD；作者 ZAIR 也单独运行，时间不混入本环境指标。源码：<a href="https://github.com/UCLA-VAST/ZAC/tree/e5083362f99e6915f20c2bd0eaa88b6d1cdcecac">GitHub 固定版本</a> · <a href="https://zenodo.org/records/14219336">Zenodo AE</a></p></header>'
    html += '<section><h2>同口径结果</h2><table><tr><th>指标</th><th>Reuse 关闭</th><th>Reuse 开启</th></tr>'
    rows = [('执行状态',a['status'],b['status']),
            ('总物理时间（μs，含归还）',a['metrics'].get('episode_wall_time_us'),b['metrics'].get('episode_wall_time_us')),
            ('逻辑门完成时间（μs）',a['metrics'].get('logical_completion_elapsed_us'),b['metrics'].get('logical_completion_elapsed_us')),
            ('装载批次数',a['metrics'].get('aod_load_count'),b['metrics'].get('aod_load_count')),
            ('被装载原子累计次数',a['metrics'].get('captured_atom_count_total'),b['metrics'].get('captured_atom_count_total')),
            ('原子总路程（μm）',a['metrics'].get('total_atom_distance_um'),b['metrics'].get('total_atom_distance_um')),
            ('作者选定跨层留驻次数',sum(map(len,a['selected_reuse'])),sum(map(len,b['selected_reuse']))),
            ('独立重放完全一致',a['replay_equal'],b['replay_equal']),
            ('全部门恰好完成一次',a['effects_once'],b['effects_once']),
            ('显式终态校验',a['terminal_verified'],b['terminal_verified'])]
    for label,x,y in rows:
        def fmt(v):
            return f'{v:.3f}' if type(v) is float else str(v)
        html += f'<tr><td>{label}</td><td>{escape(fmt(x))}</td><td>{escape(fmt(y))}</td></tr>'
    html += '</table><p><a href="comparison.json">完整指标 / 对照 JSON</a> · <a href="input.json">实验输入</a> · <a href="reuse/upstream/placement.json">作者分层与目标映射</a> · <a href="reuse/plans.json">实际物理操作</a></p></section>'
    if report['status']=='completed':
        change=100*(b['metrics']['episode_wall_time_us']/a['metrics']['episode_wall_time_us']-1)
        html += f'<section><p>本例开启 reuse 后，总物理时间{"增加" if change>0 else "减少"} <strong>{abs(change):.2f}%</strong>。装卸批次、空载定位与末尾归还都参与计时；复用数量更多不保证本环境总时间更短。</p></section>'
    html += '<section><h2>完整电路与物理回放</h2><div class="chips"><button data-mode="reuse">查看 Reuse 开启</button><button data-mode="no_reuse">查看 Reuse 关闭</button><a href="reuse/index.html" target="_blank">单独打开开启版</a><a href="no_reuse/index.html" target="_blank">单独打开关闭版</a></div></section><iframe id="replay" title="电路与原子回放" src="reuse/index.html"></iframe>'
    html += '<script>const frame=document.getElementById("replay");frame.onload=()=>{const body=frame.contentDocument.body;const resize=()=>frame.style.height=(body.getBoundingClientRect().height+40)+"px";resize();new ResizeObserver(resize).observe(body);};document.querySelectorAll("[data-mode]").forEach(b=>b.onclick=()=>frame.src=b.dataset.mode+"/index.html");</script></body></html>'
    Path(path).write_text(html,encoding='utf-8')
