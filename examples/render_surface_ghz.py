"""Render the experiment from actual saved results; no animation synthesis."""
import argparse
import csv
import html
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from neutral_atom_env.experiments.surface_ghz import experiment_input, input_payload, verify, phase_columns


def render(output):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    value=experiment_input('row_greedy'); stages={x['gate_id']:x['stage'] for x in input_payload()[1]}
    gates=sorted(value['gates'],key=lambda g:(g['column'],g['id']))
    (output/'input.json').write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    proof=verify()
    (output/'quantum-verification.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf-8')
    qasm=['OPENQASM 2.0;','include "qelib1.inc";','qreg q[36];']
    for g in gates:
        qasm.append(g['gate_type'].lower()+' '+','.join('q['+str(int(q[1:]))+']' for q in g['qubit_ids'])+';')
    (output/'circuit.qasm').write_text('\n'.join(qasm)+'\n',encoding='utf-8')
    with (output/'circuit.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        w=csv.writer(stream);w.writerow(['gate_id','stage','column','gate','qubits'])
        w.writerows([g['id'],stages[g['id']],g['column'],g['gate_type'],' '.join(g['qubit_ids'])] for g in gates)
    cols=1+max(g['column'] for g in gates);width=170+cols*58;height=70+36*28
    svg=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="完整194门物理线路">',
         '<rect width="100%" height="100%" fill="#fff"/>']
    for q in range(36):
        y=55+q*28
        if q%9==0:svg.append(f'<rect x="0" y="{y-17}" width="{width}" height="252" fill="{("#f0f5fb","#f7f4ed")[q//9%2]}"/>')
    for q in range(36):
        y=55+q*28
        svg.extend([f'<text x="12" y="{y+4}" font-size="12" fill="#465569">L{q//9} · d{q%9} / Q{q:03d}</text>',
                    f'<path d="M 153 {y} H {width-15}" stroke="#bbc6d3"/>'])
    for col in range(cols):svg.append(f'<text x="{173+58*col}" y="22" font-size="11" fill="#64748b">{col}</text>')
    cz_lanes={col:[g['id'] for g in gates if g['column']==col and g['gate_type']=='CZ'] for col in range(cols)}
    for g in gates:
        x=180+58*g['column'];ys=[55+28*int(q[1:]) for q in g['qubit_ids']]
        if g['gate_type']=='CZ':
            lane=cz_lanes[g['column']]
            negative=(len(lane)+1)//2
            offsets=[-12-4*i for i in reversed(range(negative))]+[12+4*i for i in range(len(lane)-negative)]
            x+=offsets[lane.index(g['id'])]
        color='#266e73' if stages[g['id']].startswith('encode') else '#a45536'
        svg.append('<g><title>'+html.escape(f"{g['id']} · {stages[g['id']]} · {g['gate_type']} {' '.join(g['qubit_ids'])}")+'</title>')
        if g['gate_type']=='CZ':
            svg.append(f'<path d="M {x} {min(ys)} V {max(ys)}" stroke="{color}" stroke-width="2"/>')
            svg.extend(f'<circle cx="{x}" cy="{y}" r="5" fill="{color}"/>' for y in ys)
        else:
            svg.append(f'<rect x="{x-10}" y="{ys[0]-10}" width="20" height="20" rx="4" fill="{color}"/><text x="{x}" y="{ys[0]+4}" text-anchor="middle" fill="white" font-size="12">H</text>')
        svg.append('</g>')
    svg.append('</svg>');(output/'circuit.svg').write_text(''.join(svg),encoding='utf-8')
    results={name:json.loads((output/name/'result.json').read_text(encoding='utf-8')) for name in ('row_symmetric','row_greedy')}
    metrics={name:r['metrics'] for name,r in results.items()}
    a,b=(metrics[n]['simulation_time_us'] for n in ('row_symmetric','row_greedy'))
    comparison={'baseline_complete_us':a,'planner_complete_us':b,'saved_us':a-b,'reduction_percent':100*(a-b)/a,
                'same_input_except_strategy':True,'quantum_verification':proof,'strategies':{}}
    inputs=[json.loads((output/name/'input.json').read_text(encoding='utf-8')) for name in results]
    normalized=[{k:v for k,v in i.items() if k!='compiler'} for i in inputs]
    assert normalized[0]==normalized[1], 'Comparison inputs differ beyond strategy'
    for name,r in results.items():
        entries=r['decision_log']
        comparison['strategies'][name]={'status':r['status'],'compile_seconds':r['compile_seconds'],'metrics':r['metrics'],
             'constructed':sum(d.get('constructed',0) for d in entries),'bound_pruned':sum(d.get('bound_pruned',0) for d in entries),
             'budget_omitted':sum(d.get('budget_omitted',0) for d in entries)}
    categories={name:{c['key']:c['duration_us'] for c in json.loads((output/name/'recording.json').read_text(encoding='utf-8'))['summary']['categories']} for name in results}
    comparison['cost_decomposition']={'baseline_empty_us':categories['row_symmetric']['empty'],
        'planner_empty_us':categories['row_greedy']['empty'],
        'empty_saved_us':categories['row_symmetric']['empty']-categories['row_greedy']['empty'],
        'unchanged_loaded_motion_us':categories['row_greedy']['transport']+categories['row_greedy']['return'],
        'unchanged_transfers_us':categories['row_greedy']['load']+categories['row_greedy']['offload'],
        'additional_overlap_saving_us':a-b-(categories['row_symmetric']['empty']-categories['row_greedy']['empty'])}
    (output/'comparison.json').write_text(json.dumps(comparison,ensure_ascii=False,indent=2),encoding='utf-8')
    rows=''.join(f'<tr><th>{label}</th><td>{metrics["row_symmetric"][key]:,.2f}</td><td>{metrics["row_greedy"][key]:,.2f}</td></tr>' for label,key in [
        ('完整完成 / μs','simulation_time_us'),('逻辑完成 / μs','logical_completion_elapsed_us'),('AOD 路程 / μm','total_aod_distance_um'),
        ('LOAD 次数','aod_load_count'),('OFFLOAD 次数','aod_offload_count'),('完成门数','completed_gate_count')])
    rows+=f'<tr><th>编译墙钟 / s</th><td>{results["row_symmetric"]["compile_seconds"]:.2f}</td><td>{results["row_greedy"]["compile_seconds"]:.2f}</td></tr>'
    details=''.join(f'<tr><td>{g["id"]}</td><td>{stages[g["id"]]}</td><td>{g["column"]}</td><td>{g["gate_type"]}</td><td>{" · ".join(g["qubit_ids"])}</td></tr>' for g in gates)
    page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Surface code · 四逻辑 GHZ 调度实验</title>
<style>body{margin:0;background:#f1f4f6;color:#24354a;font:16px/1.7 system-ui,sans-serif}main{max-width:1200px;margin:42px auto;padding:0 24px}h1{font-size:38px;line-height:1.25;margin:12px 0}h2{font-size:22px}small,.muted{color:#64748b}.card{background:white;border:1px solid #dce3e9;border-radius:14px;padding:26px;margin:20px 0}.hero{border-top:5px solid #266e73}.stats{display:flex;gap:40px;flex-wrap:wrap}.stats strong{display:block;font-size:28px;color:#266e73}.actions{display:flex;gap:12px;flex-wrap:wrap;margin:18px 0}a,button{color:#215e65}a.btn,button{border:1px solid #bccdd3;background:#f8fbfc;padding:9px 16px;border-radius:7px;text-decoration:none;font:inherit;cursor:pointer}a.primary{background:#266e73;color:white}.scroll{overflow:auto}table{border-collapse:collapse;width:100%;font-size:14px}td,th{padding:10px;text-align:left;border-bottom:1px solid #e1e7ed}th{font-weight:600}iframe{width:100%;height:1050px;border:0}code{background:#edf2f4;padding:2px 5px}summary{cursor:pointer} .bar{height:30px;background:#8b9eab;border-radius:4px;margin:8px 0}.bar.plan{background:#266e73}</style>
<main><small>可复现的物理调度实验 · distance 3 · 单台刚性 AOD</small><h1>四个逻辑比特，制备一个 GHZ 态</h1>
<p>从 36 个 |0⟩ 数据原子出发，编码为 |+L⟩⊗|0L⟩³，再执行逻辑 CNOT 0→1、0→2、1→3。独立稳定子检查确认目标 (|0000L⟩+|1111L⟩)/√2；不包含测量纠错循环或噪声。</p>
<section class="card hero"><div class="stats"><div><strong>4 × [[9,1,3]]</strong>旋转 surface-code 数据块</div><div><strong>194 门</strong>135 H · 59 CZ</div><div><strong>1 × 36 AOD</strong>10 μm 原子间隔 · 列可开关</div></div>
<div class="actions"><a class="btn primary" href="http://127.0.0.1:8769/" target="_blank">打开可编辑电路工作台</a><a class="btn" href="input.json" download>下载可编辑输入</a><a class="btn" href="circuit.qasm" download>完整 OpenQASM</a><a class="btn" href="quantum-verification.json">量子逻辑验证</a></div><p class="muted">工作台点击“4 逻辑比特 GHZ”载入本例，可增删门、修改线路并重新编译。当前占据间隔 10 μm，SLM 候选网格仍为 5 μm，四邻格硬规则保持。</p></section>
<section class="card"><h2>相同硬件、布局、线路和完整归还终态</h2><p>基线先整行搬入 EZ，依固定门序执行 CZ、每次将伙伴卸回原格点，最后整行归还。规划器拥有相同动作族，可在 READY 门和两种原子角色、四个 CZ 方向中选择，用可证明的运输下界剪枝，再调用 A* 和共享物理校验。</p>
<h2>完整耗时减少 __PERCENT__%</h2><div class="bar" style="width:100%"></div><div class="bar plan" style="width:__WIDTH__%"></div><table><thead><tr><th>指标</th><th>对称逐门基线</th><th>下界剪枝贪心</th></tr></thead><tbody>__ROWS__</tbody></table><p class="muted">总耗时包含准备、装卸、运输、光照和归还；μs 是物理模拟时间，s 是本机编译墙钟，两者分开。CZ 仍逐次施加，多原子联合运输不等于批量 CZ。</p><p>改进版构造 __BUILT__ 个 CZ 候选，以时间下界剪去 __PRUNED__ 个。仅证明每次受限恢复服务族中的选择；不宣称全电路全局最优。</p><a href="comparison.json">查看完整原始比较数据</a></section>
<section class="card"><h2>完整电路 · 36 条物理线路</h2><p>绿色为编码，棕色为逻辑 CNOT 的物理展开；H–CZ–H 实现物理 CNOT。Q000–008、Q009–017、Q018–026、Q027–035 分别对应四个逻辑块。列仅表示依赖顺序，不表示物理同时执行。</p><div class="scroll"><img src="circuit.svg" alt="36物理比特完整194门线路"></div><details><summary>展开全部 194 个门与所属阶段</summary><table><thead><tr><th>ID</th><th>阶段</th><th>列</th><th>门</th><th>操作数</th></tr></thead><tbody>__GATES__</tbody></table></details><a href="circuit.csv" download>下载完整门表 CSV</a></section>
<section class="card"><h2>完整动画与实际调度</h2><p>两份动画都由真实 Executor 事件生成，包含联合搬入、全部 194 个门及联合归还。按需载入其中一份，避免同时播放造成浏览器负担。</p><div class="actions"><button onclick="show('row_symmetric')">载入对称基线动画</button><button onclick="show('row_greedy')">载入规划器动画</button><a class="btn" href="row_symmetric/index.html" target="_blank">独立打开基线</a><a class="btn" href="row_greedy/index.html" target="_blank">独立打开规划器</a></div><div id="playback"></div></section>
<section class="card"><h2>为什么总改善只有 3.12%？</h2><p>空载移动从 3,790 降至 2,720 μs，减少 28.23%，节省 1,070 μs；更多 Raman 与运输重叠另外节省 57 μs。两份记录的原子总路程都为 12,094 μm。逐 CZ 恢复模式中，载原子往返 19,988 μs 与装卸 12,200 μs 没有改变，占基线约 89.2%。因此改善主要来自空载次序，而非缩短这些必付运动。</p><p>高预算原 greedy 的 60 秒压力探针仍停在首个 CZ 候选枚举，已开始 42 组分工/站点、165 个方向分支。它先等常规候选集合构造完才进入联合预取，放大预算会扩大这部分开销。此次为主动限时观察，不能据此认定物理无解。<a href="legacy-search-probe/README.md">读取原始探针报告</a>。</p><p>后续可比较扣除每个门必付成本的排序；独立几何模型已有更好预测，但尚未通过本轮完整物理验收，因此不计入上方成绩。进一步改变动作族则需要长期多 cell 驻留或批量 CZ，以及相应的作用对与执行验证。</p><p><a href="row_symmetric/verification.json">基线独立重放证据</a> · <a href="row_greedy/verification.json">规划器独立重放证据</a> · <a href="row_greedy/input.json">规划器实际输入与预算</a></p></section></main><script>function show(name){document.getElementById('playback').innerHTML='<iframe title="完整原子动画" src="'+name+'/index.html"></iframe>'}</script></html>'''
    extra=comparison['strategies']['row_greedy']
    for old,new in {'__PERCENT__':f'{comparison["reduction_percent"]:.2f}','__WIDTH__':f'{100*b/max(a,b):.3f}',
                    '__ROWS__':rows,'__GATES__':details,'__BUILT__':str(extra['constructed']),'__PRUNED__':str(extra['bound_pruned'])}.items():page=page.replace(old,new)
    saved_job=output/'row_greedy'/'job.json'
    editor_url=json.loads(saved_job.read_text(encoding='utf-8'))['url'] if saved_job.exists() else 'http://127.0.0.1:8769/?example=surface-ghz'
    page=page.replace('href="http://127.0.0.1:8769/"',f'href="{html.escape(editor_url,quote=True)}"')
    (output/'index.html').write_text(page,encoding='utf-8')
    print(json.dumps(comparison,ensure_ascii=False,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',default='artifacts/surface-ghz')
    render(p.parse_args().output)
