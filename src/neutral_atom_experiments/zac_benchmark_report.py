"""Aggregate actual benchmark outcomes; never rank failed prefixes as timings."""
from html import escape
from pathlib import Path
import csv
import json

from neutral_atom_experiments.zac_reuse_report import head


def rows_from_manifest(manifest):
    rows = []
    for case in manifest['cases']:
        for mode, run in case['variants'].items():
            result = run.get('result', {})
            metrics = result.get('metrics', {})
            phases = result.get('phase_time_us', {})
            error = result.get('error') or run.get('error')
            rows.append(dict(case=case['id'], family=case['family'], atoms=case['spec']['atom_count'],
                gates=len(case['spec']['pairs']), depth=case['depth'], seed=case['seed'], mode=mode,
                status=run['status'], completed_gates=metrics.get('completed_gate_count'),
                # Physical prefix is explicitly separate from a completed benchmark time.
                total_us=metrics.get('episode_wall_time_us') if run['status']=='completed' else None,
                prefix_us=metrics.get('episode_wall_time_us'), logical_us=metrics.get('logical_completion_elapsed_us'),
                prepare_us=phases.get('prepare'), cz_us=phases.get('CZ'), return_us=phases.get('return non-reuse'),
                terminal_us=phases.get('terminal return', 0)+phases.get('terminal', 0) if phases else None,
                load_batches=metrics.get('aod_load_count'), loaded_atoms=metrics.get('captured_atom_count_total'),
                atom_distance_um=metrics.get('total_atom_distance_um'),
                retained_planned=sum(map(len,result.get('selected_reuse', []))),
                retained_verified=sum(r['passed'] for r in result.get('reuse_audit', [])),
                author_frontend_s=result.get('author_frontend_seconds'),
                author_compile_verify_s=result.get('author_compile_verify_seconds'),
                local_execute_record_s=result.get('realize_execute_record_seconds'),
                independent_replay_s=result.get('independent_replay_seconds'),
                process_s=run.get('process_elapsed_seconds'), replay_equal=result.get('replay_equal'),
                effects_once=result.get('effects_once'), terminal_verified=result.get('terminal_verified'),
                error=json.dumps(error,ensure_ascii=False) if error else '',
                replay_url=f"{case['id']}/{run['replay_url']}" if run.get('replay_url') else '',
                evidence_url=f"{case['id']}/{mode}/worker.json" if run['status']!='queued' else '',
                initial_sha256=result.get('initial_sha256')))
    return rows


def write_dashboard(manifest, output):
    output = Path(output)
    rows = rows_from_manifest(manifest)
    for row in rows:
        row['editor_url'] = f'../?input={output.name}/{row["case"]}/input.json'
    with (output/'summary.csv').open('w',encoding='utf-8-sig',newline='') as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    complete = sum(r['status']=='completed' for r in rows)
    html = head('ZAC · 大规模 benchmark')
    html += '''<style>.filters{display:flex;gap:12px;flex-wrap:wrap}td,th{white-space:nowrap;padding:10px;font-size:13px}td.error{white-space:normal;min-width:220px;max-width:360px;font-size:12px}.muted{color:#78839b}.bars{display:grid;gap:5px;min-width:100px}.bar{height:10px;background:#91a4c8;border-radius:3px}.bar.reuse{background:#43796c}.detail{max-height:570px;overflow:auto}code{font-size:12px}#notice{white-space:pre-wrap}</style>
<header><div class="eyebrow">ZAC / LARGE CZ BENCHMARK</div><h1>更大线路上的跨层复用</h1>'''
    sizes = sorted({r['atoms'] for r in rows})
    html += f'<p>{" / ".join(map(str,sizes))} 原子 · {len(manifest["cases"])} 条线路 × reuse 开／关 · 已完成 {complete}/{len(rows)} 份物理执行与独立重放</p>'
    html += f'<p>批次状态：{escape(manifest["status"])}。每组同初态、同硬件、同 CZ 顺序、同完整终态。每种规模的 AOD 为 2 × max(4, N/2)，存储区和 EZ 随规模扩展。</p>'
    policy = '在原世界边界内安排闲置轴' if manifest['cases'][0]['spec'].get('bounded_spares') else '原始右侧 10 μm 补齐闲置轴'
    html += f'<p>本批运输候选：{policy}。源文件哈希随批次保存。</p>'
    html += '<p class="note">这是固定源码算法在本框架中的合成 CZ 压力实验；重复配对是正对照，蝶形逐层换伙伴，随机配对使用记录中的固定 seed。重复 CZ 不消去。不是论文全套 AE、混合门电路或保真度复现。失败前缀不参与速度比较。</p>'
    html += f'<p class="note">每份本地规划执行预算 {manifest["contract"]["timeout_s"]:g}s，进程上限 {manifest["contract"]["hard_timeout_s"]:g}s；{manifest["contract"]["workers"]} 个并发子进程。秒是主机墙钟（含校验/录制），μs 是仿真物理时间，二者不可互换。跨规模硬件容量变化，曲线不代表固定设备强扩展。</p>'
    html += '<p><a href="summary.csv">下载 CSV</a> · <a href="benchmark.json">输入、源码哈希、预算与完整结果</a> · <a href="../">返回现有实验台</a></p></header>'
    siblings = sorted(output.parent.glob('*/benchmark.json'))
    if len(siblings)>1:
        html += '<section>实验批次：'+' · '.join(f'<a href="../{escape(p.parent.name)}/index.html">{escape(p.parent.name)}</a>' for p in siblings)+'</section>'
    html += '''<section><div class="filters"><label>规模 <select id="size"><option value="">全部</option></select></label><label>线路 <select id="family"><option value="">全部</option><option>repeat</option><option>butterfly</option><option>random</option></select></label><label><input type="checkbox" id="failures"> 仅看未完成</label></div><p id="notice" class="note"></p><div class="scroll"><table><thead><tr><th>线路</th><th>原子 / CZ</th><th>关 / 开状态</th><th>关 / 开总物理 μs</th><th>时间变化</th><th>同尺度时间条</th><th>关 / 开装载原子次数</th><th>完整电路与回放</th></tr></thead><tbody id="pairs"></tbody></table></div></section>
<section><h2>逐份执行明细</h2><p class="note">阶段分解来自已接受的真实操作：准备入区、CZ、非复用归还、末尾共同终态恢复。局部执行含规划、Executor 和录制；独立重放另计。超时或失败仅展示已执行前缀与错误，审计通过不等于完整线路成功。</p><div class="detail"><table><thead><tr><th>线路 / 设置</th><th>完成门</th><th>准备 μs</th><th>CZ μs</th><th>非复用归还 μs</th><th>终态 μs</th><th>作者前端 s</th><th>作者含路由/校验 s</th><th>本地执行/录制 s</th><th>独立重放 s</th><th>全程含导出 s</th><th>重放 / 门 / 终态</th><th>失败原因</th></tr></thead><tbody id="details"></tbody></table></div></section>'''
    data = json.dumps(rows, ensure_ascii=False).replace('<',r'\u003c')
    html += '<script>const rows='+data+';\n'
    html += '''const $=id=>document.getElementById(id),fmt=v=>v==null?'—':typeof v==='number'?v.toFixed(3):String(v);
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
for(const n of [...new Set(rows.map(r=>r.atoms))]){const o=document.createElement('option');o.value=n;o.textContent=n;$('size').append(o);}
function render(){const selected=rows.filter(r=>(!$('size').value||r.atoms===Number($('size').value))&&(!$('family').value||r.family===$('family').value));const groups=[...new Set(selected.map(r=>r.case))].map(id=>selected.filter(r=>r.case===id)).filter(g=>!$('failures').checked||g.some(r=>r.status!=='completed'));const max=Math.max(1,...selected.map(r=>r.total_us||0));
$('notice').textContent='当前显示 '+groups.length+' 组；负百分比表示 reuse 更快，正百分比表示更慢。点击对照进入原共用 viewer；未完成录制只能查看已执行前缀。';
$('pairs').innerHTML=groups.map(g=>{const a=g.find(r=>r.mode==='no_reuse'),b=g.find(r=>r.mode==='reuse'),ok=a.status==='completed'&&b.status==='completed'&&a.initial_sha256===b.initial_sha256;const change=ok?100*(b.total_us/a.total_us-1):null;const links=ok?'<a href="'+esc(a.case)+'/index.html">对照与两版回放</a>':g.map(r=>r.replay_url?'<a href="'+esc(r.replay_url)+'">'+r.mode+(r.status==='completed'?' 完整回放':' 前缀')+'</a>':r.evidence_url?'<a href="'+esc(r.evidence_url)+'">'+r.mode+' 诊断</a>':'等待中').join(' · ');return '<tr><td>'+esc(a.case)+'</td><td>'+a.atoms+' / '+a.gates+'</td><td>'+esc(a.status)+' / '+esc(b.status)+'</td><td>'+fmt(a.total_us)+' / '+fmt(b.total_us)+'</td><td class="'+(change==null?'muted':change>0?'bad':'good')+'">'+(change==null?'不可比较':(change>0?'+':'')+change.toFixed(2)+'%')+'</td><td><div class="bars">'+g.map(r=>'<div title="'+r.mode+'" class="bar '+r.mode+'" style="width:'+100*(r.total_us||0)/max+'%"></div>').join('')+'</div></td><td>'+fmt(a.loaded_atoms)+' / '+fmt(b.loaded_atoms)+'</td><td>'+links+' · <a href="'+esc(a.editor_url)+'">编辑输入</a></td></tr>';}).join('');
$('details').innerHTML=groups.flat().map(r=>'<tr><td>'+esc(r.case)+' / '+r.mode+'</td><td>'+fmt(r.completed_gates)+' / '+r.gates+'</td>'+['prepare_us','cz_us','return_us','terminal_us','author_frontend_s','author_compile_verify_s','local_execute_record_s','independent_replay_s','process_s'].map(k=>'<td>'+fmt(r[k])+'</td>').join('')+'<td>'+[r.replay_equal,r.effects_once,r.terminal_verified].map(fmt).join(' / ')+'</td><td class="error">'+esc(r.error)+'</td></tr>').join('');}
for(const id of ['size','family','failures'])$(id).onchange=render;render();</script></body></html>'''
    temp = output/'index.html.tmp'
    temp.write_text(html, encoding='utf-8')
    temp.replace(output/'index.html')
