"""Four-arm evidence dashboard, actual initial maps and shared physical viewer."""
from html import escape
from pathlib import Path
import csv
import json
import re
from neutral_atom_experiments.zac_reuse_report import head

LABELS={'fixed_no_reuse':'固定初态 · Reuse 关','fixed_reuse':'固定初态 · Reuse 开',
        'sa_no_reuse':'SA 初态 · Reuse 关','sa_reuse':'SA 初态 · Reuse 开'}
EFFECTS={'fixed_reuse_effect':'固定初态下的复用收益','sa_reuse_effect':'SA 初态下的复用收益',
         'sa_effect_without_reuse':'关闭复用时的初态收益','sa_effect_with_reuse':'开启复用时的初态收益',
         'combined_effect':'两项联合：固定/关 → SA/开'}
STYLE='''<style>.layouts{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:16px}.layouts.wide{grid-template-columns:repeat(auto-fit,minmax(min(100%,660px),1fr))}.map{background:#f8faff;border-radius:10px;padding:12px}.map svg{width:100%;min-height:150px}.stats{display:flex;gap:24px;flex-wrap:wrap}.stats b{font-size:27px;display:block}.bar{height:10px;background:#5874b9;border-radius:3px}.bar.sa{background:#248879}.small{font-size:12px;color:#67738a}.error{max-width:380px;white-space:normal}.actions{display:flex;gap:8px;flex-wrap:wrap}td{font-size:13px;vertical-align:top}th{font-size:13px}button[aria-pressed=true]{background:#4059b5;color:white}.wrap{max-width:1500px;margin:auto}.contract{border-left:4px solid #5874b9;padding-left:16px}details{margin:12px 0}iframe{min-height:1200px}</style>'''


def fmt(value):
    if value is None: return '—'
    if isinstance(value,bool): return '通过' if value else '未通过'
    if type(value) is int: return f'{value:,}'
    return f'{value:,.3f}' if isinstance(value,float) else escape(str(value))


def rows(manifest):
    result=[]
    for case in manifest['cases']:
        for mode,run in case['variants'].items():
            r=run.get('result',{}); m=r.get('metrics',{}); p=r.get('phase_time_us',{})
            init=r.get('initial_placement',{})
            result.append(dict(case=case['id'],atoms=case['spec']['atom_count'],gates=len(case['spec']['pairs']),
                mode=mode,status=run['status'],total_us=m.get('episode_wall_time_us') if run['status']=='completed' else None,
                executed_prefix_us=m.get('episode_wall_time_us'),logical_us=m.get('logical_completion_elapsed_us'),
                gates_completed=m.get('completed_gate_count'),prepare_us=p.get('prepare'),cz_us=p.get('CZ'),
                return_us=p.get('return non-reuse'),terminal_us=p.get('terminal return',0)+p.get('terminal',0) if p else None,
                loaded_atoms=m.get('captured_atom_count_total'),atom_distance_um=m.get('total_atom_distance_um'),
                initial_placement_s=init.get('seconds'),baseline_proxy=init.get('baseline_cost'),selected_proxy=init.get('selected_cost'),
                author_frontend_s=r.get('author_frontend_seconds'),author_compile_verify_s=r.get('author_compile_verify_seconds'),
                local_execute_record_s=r.get('realize_execute_record_seconds'),independent_replay_s=r.get('independent_replay_seconds'),
                process_s=run.get('process_elapsed_seconds'),effects_once=r.get('effects_once'),replay_equal=r.get('replay_equal'),
                terminal_verified=r.get('terminal_verified'),initial_sha256=r.get('initial_sha256'),
                terminal_target_sha256=r.get('terminal_target_sha256'),
                error=json.dumps(r.get('error') or run.get('error'),ensure_ascii=False) if r.get('error') or run.get('error') else ''))
    return result


def contract_html():
    return '''<div class="contract"><p>四组使用相同 CZ 输入、平台、动态布局算法及本地运输器。SA 在创建物理环境前选择 qubit→SLM；所有组最后回到<b>同一编号顺序的绝对终态</b>（holder、SLM 开关、AOD 轴及开关）。</p><p class="note">运行时间从各自已制备初态开始；首次装载或从固定布局重排成 SA 布局的物理成本不在本次计时内。SA 用作者原始代码、seed=0、默认退火参数与分层距离代理；代理值不是 μs，也不保证本地路径更快。初态搜索秒数单列，并包含在作者前端秒数中，不应重复相加。只对完整执行、独立重放及共同终态通过的组计算百分比。</p></div>'''


def layout_svg(spec,mapping):
    slms={s['id']:s for z in spec['architecture']['storage_zones'] for s in z['slms']}
    if mapping is None: return '<p class="note">初态映射尚未生成；请查看执行状态。</p>'
    occupancy={tuple(site):q for q,site in enumerate(mapping)}
    max_x=max(s['location'][0]+(s['c']-1)*s['site_seperation'][0] for s in slms.values())
    max_y=max(s['location'][1]+(s['r']-1)*s['site_seperation'][1] for s in slms.values())
    width,height=max_x*4+60,max_y*4+65
    svg=f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="SZ 初始布局，所有原子编号可见">'
    for sid,s in slms.items():
        for r in range(s['r']):
            for c in range(s['c']):
                x=30+4*(s['location'][0]+c*s['site_seperation'][0]);y=25+4*(max_y-s['location'][1]-r*s['site_seperation'][1])
                q=occupancy.get((sid,r,c)); label=f'Q{q:03d}' if q is not None else '空'
                svg+=f'<g><title>{label} · Z{sid}_R{r}_C{c}</title><circle cx="{x}" cy="{y}" r="5" fill="{"#5364bc" if q is not None else "white"}" stroke="#9aa8bd"/>'
                if q is not None: svg+=f'<text x="{x}" y="{y+17}" text-anchor="middle" font-size="9" fill="#26334b">{label}</text>'
                svg+='</g>'
    return svg+f'<text x="20" y="{height-4}" font-size="10" fill="#66718a">y 向上、上方靠近 EZ；相邻格 10 μm，两图同尺度</text></svg>'


def table(case_rows):
    max_time=max([r['total_us'] or 0 for r in case_rows]+[1])
    body=''
    for r in case_rows:
        mode=r['mode'];total=r['total_us']
        link=f'<a href="{mode}/index.html">{"完整回放" if r["status"]=="completed" else "已执行前缀"}</a>' if r['executed_prefix_us'] is not None else f'<a href="{mode}/worker.json">诊断</a>' if r['status']!='queued' else '等待中'
        bar=f'<div class="bar {"sa" if mode.startswith("sa_") else ""}" style="width:{100*total/max_time}%"></div>' if total is not None else ''
        body+=f'<tr><td>{LABELS[mode]}</td><td>{escape(r["status"])}</td><td>{fmt(r["gates_completed"])} / {r["gates"]}</td><td>{fmt(total)}{bar}</td><td>{fmt(r["executed_prefix_us"]) if total is None else "—"}</td><td>{fmt(r["loaded_atoms"])}</td><td>{fmt(r["initial_placement_s"])}</td><td>{link}</td></tr>'
    return '<div class="scroll"><table><tr><th>实验组</th><th>状态</th><th>完成 CZ</th><th>完整物理时间 μs</th><th>失败前缀 μs</th><th>装载原子次数</th><th>初态求解 s</th><th>证据</th></tr>'+body+'</table></div>'


def write_report(manifest,output):
    output=Path(output); data=rows(manifest)
    with (output/'summary.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(data[0]));w.writeheader();w.writerows(data)
    completed=sum(r['status']=='completed' for r in data)
    html=head('ZAC · 初态优化 × 跨层复用')+STYLE+'<main class="wrap"><header><div class="eyebrow">ZAC / INITIAL PLACEMENT × REUSE</div><h1>初始化优化与跨层复用：四组物理对照</h1>'
    html+=f'<div class="stats"><div><b>{len(manifest["cases"])}</b>完整输入线路</div><div><b>{completed} / {len(data)}</b>完整通过执行与审计</div><div><b>{escape(manifest["status"])}</b>批次状态</div></div>'+contract_html()
    html+='<p><a href="summary.csv">下载全部指标 CSV</a> · <a href="benchmark.json">输入 / 参数 / 源码哈希 / 全部结果</a> · <a href="../">返回实验台</a> · <button onclick="location.reload()">刷新进度</button></p></header>'
    if (output/'audit.json').exists():
        html+='<section><a href="audit.json">独立产物审计结果</a> · <a href="render.json">当前展示代码版本</a></section>'
    for case in manifest['cases']:
        cr=[r for r in data if r['case']==case['id']]
        html+=f'<section><h2>{escape(case["spec"]["name"])} · {len(case["spec"]["pairs"])} CZ</h2><p><a href="{case["id"]}/index.html">打开完整四组结果、初始布局和回放 →</a></p>'
        # Root table links point inside the selected case.
        html+=table(cr).replace('href="','href="'+case['id']+'/')+'</section>'
        write_case(case,cr,output/case['id'])
    html+='<section><p class="note">每种规模的 AOD 与存储 / EZ 容量随 N 增长；不是固定硬件强扩展。合成 CZ 线路保留全部门，不是作者完整应用 AE 或保真度复现。失败与超时均保留，不能将代理改善、门完成或前缀重放等同于整条线路成功。</p></section></main></body></html>'
    (output/'index.html').write_text(html,encoding='utf-8')


def write_case(case,cr,output):
    spec=case['spec'];variants=case['variants']
    html=head('ZAC 四组对照 · '+spec['name'])+STYLE+'<main class="wrap"><header><div class="eyebrow">ZAC / FACTORIAL COMPARISON</div>'
    html+=f'<h1>{escape(spec["name"])} · 初态优化 × Reuse</h1><p>{spec["atom_count"]} 原子 · {len(spec["pairs"])} 个 CZ · 所有组使用同一绝对终态</p>'+contract_html()
    html+=f'<p><a href="../index.html">返回全部结果</a> · <a href="input.json">完整输入</a> · <a href="../../?input={output.parent.name}/{output.name}/input.json">在实验台编辑这条线路</a> · <a href="../summary.csv">下载 CSV</a> · <button onclick="location.reload()">刷新进度</button></p></header>'
    html+='<section><h2>1 · 四组实际结果</h2>'+table(cr)+'</section><section><h2>2 · 分开衡量初始化与复用</h2><p class="note">负值表示耗时减少，正值表示增加；不完整或审计不匹配的组不计算。</p><table><tr><th>比较</th><th>物理时间变化</th></tr>'
    for name,value in case.get('comparisons',{}).items():
        delta=value['change_percent']
        pending=any(variants[value[k]]['status'] in ('queued','running') for k in ('baseline','candidate'))
        text=f'{delta:+.2f}%' if delta is not None else '等待结果' if pending else '不可比较（存在未完成运行）'
        html+=f'<tr><td>{EFFECTS[name]}</td><td class="{"good" if delta is not None and delta<0 else "bad" if delta is not None else "note"}">{text}</td></tr>'
    html+='</table></section><section><h2>3 · 初始布局与作者目标函数</h2><div class="layouts'+(' wide' if spec['atom_count']>16 else '')+'"><div class="map"><h3>固定初态 / 四组共同终态</h3>'+layout_svg(spec,spec['initial_mapping'])+'</div>'
    infos=[]
    for mode in ('sa_no_reuse','sa_reuse'):
        path=output/mode/'upstream/placement.json'
        if path.exists():
            try: infos.append(json.loads(path.read_text(encoding='utf-8'))['initial_placement'])
            except (OSError,json.JSONDecodeError): pass  # Writer may still be finishing this frontend.
    info=infos[0] if infos else None
    html+='<div class="map"><h3>作者 SA 初态</h3>'+layout_svg(spec,info['mapping'] if info else None)+'</div></div>'
    if info:
        same=len(infos)==2 and infos[0]['mapping']==infos[1]['mapping']
        html+=f'<p>作者距离代理：{fmt(info["baseline_cost"])} → {fmt(info["selected_cost"])}；改变位置 {info["changed_atoms"]}/{spec["atom_count"]} 个原子。两次独立 SA 输出映射一致：{fmt(same) if len(infos)==2 else "等待另一组"}。</p>'
        for mode in ('sa_reuse','sa_no_reuse'):
            log=output/mode/'upstream/upstream.log'
            if log.exists():
                text=log.read_text(encoding='utf-8',errors='replace')
                match=re.search(r'initial cost: ([0-9.]+)',text)
                if match:
                    initial_cost=float(match.group(1))
                    html+=f'<p class="note">作者日志中的 SA 主循环起点最佳代价为 {fmt(initial_cost)}（已包含作者初始解构造与预扰动），最终为 {fmt(info["selected_cost"])}。固定布局到最终布局的全部改善，不能都归因于退火主循环。</p>'
                    break
        html+='<p class="note">直接运行原始 SAPlacer；层权重依次 1、0.9、0.8、0.7、0.6，后续层保持 0.6。代理距离由作者架构最近纠缠位置函数计算，l2=False。下方物理时间来自实际路径、装卸、CZ 和末尾归还。</p>'
    html+='</section><section><h2>4 · 时间分解与验证</h2><div class="scroll"><table><tr><th>组别</th><th>入区 μs</th><th>CZ μs</th><th>非复用归还 μs</th><th>共同终态 μs</th><th>作者前端 s</th><th>作者含路由/校验 s</th><th>本地执行/录制 s</th><th>独立重放 s</th><th>门 / 重放 / 终态</th></tr>'
    for r in cr:
        html+='<tr><td>'+LABELS[r['mode']]+'</td>'+''.join('<td>'+fmt(r[k])+'</td>' for k in ('prepare_us','cz_us','return_us','terminal_us','author_frontend_s','author_compile_verify_s','local_execute_record_s','independent_replay_s'))+'<td>'+ ' / '.join(fmt(r[k]) for k in ('effects_once','replay_equal','terminal_verified'))+'</td></tr>'
    html+='</table></div><p class="note">前端秒数含距离代理核算。秒为本机墙钟，含校验和录制；并发机器负载会影响数值。μs 为仿真物理时间。失败行的阶段分解只覆盖已执行前缀。</p>'
    for r in cr:
        if r['error']:
            html+=f'<p class="bad">{LABELS[r["mode"]]}：{escape(r["error"])}</p>'
            rejected=output/r['mode']/'rejections.json'
            if rejected.exists():
                records=json.loads(rejected.read_text(encoding='utf-8'))
                if records:
                    last=records[-1]
                    html+=f'<p class="note">最后拒绝：阶段 {last["stage"]+1}，{escape(last["phase"])}，原子 {escape(str(last["atoms"]))}。{escape(last["violation"]["message"])}。这是有限候选耗尽，不能推断物理无解。<a href="{r["mode"]}/rejections.json">全部候选拒绝记录</a></p>'
    html+='</section><section><h2>5 · 完整 CZ 电路与实际原子回放</h2><p>点击切换四组。门可定位实际脉冲，跨层留驻与运输均使用原共用 viewer。</p><div class="actions">'
    available=[r['mode'] for r in cr if r['executed_prefix_us'] is not None]
    selected=next((m for m in ('sa_reuse','sa_no_reuse','fixed_reuse','fixed_no_reuse')
                   if m in available and variants[m]['status']=='completed'),available[0] if available else None)
    for mode in available:
        html+=f'<button data-mode="{mode}" aria-pressed="{str(mode==selected).lower()}">{LABELS[mode]}</button><a href="{mode}/index.html" target="_blank">独立打开</a>'
    html+='</div></section>'
    if selected:
        html+=f'<iframe id="replay" title="所选实验组完整电路与物理回放" src="{selected}/index.html"></iframe>'
        html+='''<script>const frame=document.getElementById('replay');let observer;frame.onload=()=>{if(observer)observer.disconnect();const body=frame.contentDocument.body;const resize=()=>frame.style.height=(body.getBoundingClientRect().height+40)+'px';resize();observer=new ResizeObserver(resize);observer.observe(body);};document.querySelectorAll('[data-mode]').forEach(b=>b.onclick=()=>{frame.src=b.dataset.mode+'/index.html';document.querySelectorAll('[data-mode]').forEach(x=>x.setAttribute('aria-pressed',String(x===b)));});</script>'''
    else: html+='<section><p>尚无可回放记录；执行完成后刷新本页。</p></section>'
    html+='<section><details><summary>逐组原始证据（作者日志、映射、操作和审计字段）</summary><ul>'
    for mode,run in variants.items():
        if run['status']=='queued': continue
        html+=f'<li>{LABELS[mode]}：<a href="{mode}/worker.json">结果与错误</a> · <a href="{mode}/upstream/upstream.log">作者日志</a>'
        if (output/mode/'upstream/placement.json').exists():
            html+=f' · <a href="{mode}/upstream/placement.json">作者映射与 SA 代价</a>'
        if 'result' in run:
            html+=f' · <a href="{mode}/initial.json">实际初态</a> · <a href="{mode}/terminal-target.json">共同终态目标</a> · <a href="{mode}/plans.json">物理操作</a> · <a href="{mode}/trace.jsonl">Trace</a>'
        html+='</li>'
    html+='</ul></details></section></main></body></html>'
    (output/'index.html').write_text(html,encoding='utf-8')
