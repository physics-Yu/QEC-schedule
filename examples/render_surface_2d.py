"""Build the 2D acceptance report from complete, replay-verified worker outputs."""
import html
import json
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from neutral_atom_env.experiments.surface_ghz import verify


def render():
    out=ROOT/'artifacts/surface-2d'
    names=('patch_symmetric','patch_greedy')
    read=lambda name,file:json.loads((out/name/(file+'.json')).read_text(encoding='utf-8'))
    results={n:read(n,'result') for n in names}
    inputs={n:read(n,'input') for n in names}
    assert all(r['status']=='completed' and r['ideal_logical_GHZ_verified'] for r in results.values())
    assert {k:v for k,v in inputs[names[0]].items() if k!='compiler'}=={k:v for k,v in inputs[names[1]].items() if k!='compiler'}
    assert all(read(n,'verification')['status']=='verified' and
               abs(read(n,'verification')['wall_time_us']-results[n]['metrics']['simulation_time_us'])<1e-8 for n in names)
    records={n:read(n,'recording') for n in names}
    metrics={n:r['metrics'] for n,r in results.items()}
    a,b=(metrics[n]['simulation_time_us'] for n in names)
    compare={'same_input_except_compiler':True,'same_original_terminal':True,
        'baseline_us':a,'greedy_us':b,'saved_us':a-b,'reduction_percent':100*(a-b)/a,
        'quantum':verify(),'strategies':{}}
    initial=read('patch_greedy_initial','result')
    compare['initial_greedy_counterexample']={'complete_us':initial['metrics']['simulation_time_us'],
        'extra_us_vs_baseline':initial['metrics']['simulation_time_us']-a,
        'initial_batch_sizes':[o.get('batch_size',1) for o in read('patch_greedy_initial','recording')['operations'] if o['kind']=='entangling_pulse'],
        'extra_load_offload_cycles':initial['metrics']['aod_load_count']-metrics['patch_symmetric']['aod_load_count']}
    for n in names:
        pulses=[op for op in records[n]['operations'] if op['kind']=='entangling_pulse']
        compare['strategies'][n]={'metrics':metrics[n],'compile_seconds':results[n]['compile_seconds'],
            'batch_sizes':[op.get('batch_size',1) for op in pulses],
            'constructed':sum(d.get('constructed',0) for d in results[n]['decision_log']),
            'bound_pruned':sum(d.get('bound_pruned',0) for d in results[n]['decision_log']),
            'source_stable':not read(n,'source-stability')['changed_during_run']}
    (out/'comparison.json').write_text(json.dumps(compare,ensure_ascii=False,indent=2),encoding='utf-8')
    (out/'input.json').write_text(json.dumps(inputs['patch_greedy'],ensure_ascii=False,indent=2),encoding='utf-8')
    # Exact same 194 native gate list as the historical row experiment; reuse
    # only its circuit drawing/export, never its physical trace or animation.
    old=ROOT/'artifacts/surface-ghz'
    oldinput=json.loads((old/'input.json').read_text(encoding='utf-8'))
    assert sorted(oldinput['gates'],key=lambda g:g['id'])==sorted(inputs['patch_greedy']['gates'],key=lambda g:g['id'])
    for f in ('circuit.svg','circuit.qasm','circuit.csv'):shutil.copy2(old/f,out/f)
    svg=['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 560 480" role="img" aria-label="四个三乘三二维surface-code patch">',
         '<rect width="560" height="480" rx="16" fill="#eff5f3"/>']
    for block in range(4):
        bx=(block%2)*40;by=(block//2)*40
        x=65+bx*6;y=420-by*6
        svg.append(f'<rect x="{x-25}" y="{y-145}" width="170" height="175" rx="12" fill="white" stroke="#d0ddd8"/>')
        svg.append(f'<text x="{x-10}" y="{y-155}" font-size="16" fill="#244a49">L{block} · 3×3</text>')
        for r in range(2):
            for c in range(2):
                color='#dcece8' if (r+c)%2==0 else '#e7e2f0'
                svg.append(f'<rect x="{x+c*60}" y="{y-(r+1)*60}" width="60" height="60" fill="{color}"/>')
        for q in range(9):
            xx=x+(q%3)*60;yy=y-(q//3)*60
            svg.append(f'<circle cx="{xx}" cy="{yy}" r="9" fill="#436b84"/><text x="{xx}" y="{yy+24}" text-anchor="middle" font-size="10" fill="#435768">Q{9*block+q:03}</text>')
    svg.append('</svg>');(out/'layout.svg').write_text(''.join(svg),encoding='utf-8')
    job=read('patch_greedy','job')['url']
    table=''
    fields=[('全部结束 / μs','simulation_time_us'),('逻辑完成 / μs','logical_completion_elapsed_us'),
        ('AOD 路程 / μm','total_aod_distance_um'),('原子总路程 / μm','total_atom_distance_um'),
        ('装载次数','aod_load_count'),('卸载次数','aod_offload_count')]
    for label,key in fields:
        table+=f'<tr><td>{label}</td>'+''.join(f'<td>{metrics[n][key]:,.1f}</td>' for n in names)+'</tr>'
    for label,key in [('真实 CZ 脉冲数',None),('最大并行 CZ',None),('编译秒数（单次）',None)]:
        values=[]
        for n in names:
            s=compare['strategies'][n]
            values.append(len(s['batch_sizes']) if label.startswith('真实') else max(s['batch_sizes']) if label.startswith('最大') else round(s['compile_seconds'],2))
        table+=f'<tr><td>{label}</td><td>{values[0]}</td><td>{values[1]}</td></tr>'
    batch_rows=''
    for n,label in zip(names,('对称基线','并行贪心')):
        blocks=''.join(f'<span title="一个0.3 μs全局脉冲完成{k}个CZ" style="height:{22+k*3}px">{k}</span>' for k in compare['strategies'][n]['batch_sizes'])
        batch_rows+=f'<p>{label}：每个方块代表一次真实全局脉冲，数字为同时执行的 CZ 数。</p><div class="batches">{blocks}</div>'
    headline=(f'贪心比二维对称基线节省 {100*(a-b)/a:.2f}%' if b<a else
              f'贪心未击败二维对称基线：多用 {b-a:,.1f} μs')
    page=f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>二维 Surface GHZ · 可编辑编译验收</title>
<style>*{{box-sizing:border-box}}body{{margin:0;background:#f5f6f2;color:#243a3d;font:15px/1.7 system-ui,"Microsoft YaHei",sans-serif}}main{{max-width:1240px;margin:auto;padding:44px 30px}}h1{{font-size:40px;line-height:1.3;margin:12px 0}}h2{{font-size:23px;margin:0 0 18px}}.eyebrow{{letter-spacing:2px;color:#627a78;font-size:12px}}.lead{{font-size:18px;max-width:960px}}.actions{{display:flex;gap:12px;flex-wrap:wrap;margin:26px 0}}a{{color:#246b69}}.button{{padding:12px 22px;background:#285e5e;color:white;text-decoration:none;border-radius:7px}}.secondary{{background:white;color:#285e5e;border:1px solid #bad1ca}}section{{background:white;border:1px solid #dce4df;border-radius:14px;padding:28px;margin:24px 0}}.grid{{display:grid;grid-template-columns:1fr 1fr;gap:30px}}img{{max-width:100%}}.chips{{display:flex;gap:10px;flex-wrap:wrap}}.chips span{{padding:8px 14px;background:#eaf1ed;border-radius:6px}}table{{border-collapse:collapse;width:100%}}th,td{{text-align:right;padding:11px;border-bottom:1px solid #e0e7e3}}th:first-child,td:first-child{{text-align:left}}.batches{{display:flex;gap:5px;align-items:end;min-height:90px;flex-wrap:wrap}}.batches span{{display:flex;align-items:center;justify-content:center;min-width:24px;background:#367975;color:white;border-radius:4px;font-size:12px}}code{{background:#eff3f1;padding:2px 5px}}.circuit{{max-height:620px;overflow:auto;border:1px solid #dde5e0}}.circuit img{{max-width:none;width:1156px}}small{{color:#647773}}@media(max-width:800px){{.grid{{grid-template-columns:1fr}}h1{{font-size:29px}}main{{padding:24px 14px}}section{{padding:20px}}}}</style>
<main><div class="eyebrow">QEC SCHEDULER / PHYSICAL COMPILATION / 2026.09.12</div><h1>四个二维 patch，真正成组抓取与并行 CZ</h1>
<p class="lead">36 个数据原子组成四块旋转 [[9,1,3]] surface code。完整 194 门理想 GHZ 线路保留；AOD 按非均匀行列坐标抓取，动画来自物理 Executor 的完整执行记录。</p>
<div class="actions"><a class="button" href="{html.escape(job)}">打开已编译结果 · 继续编辑</a><a class="button secondary" href="http://127.0.0.1:8769/?example=surface-ghz">重新载入可编辑线路</a><a class="button secondary" href="patch_symmetric/index.html">对称基线完整动画</a><a class="button secondary" href="patch_greedy/index.html">贪心完整动画</a></div>
<section class="grid"><div><h2>二维 patch 与非均匀矩形 AOD</h2><img src="layout.svg" alt="四个3乘3二维patch的真实原子编号"/></div><div><h2>抓取规则已修正</h2><p>行、列坐标均为 <code>0, 10, 20, 40, 50, 60 μm</code>，容量为 <strong>6×6 = 36</strong>。30 μm 处没有轴；不是连续矩形内的所有原子都会被抓取。</p><p>开启交点 = 开启行 × 开启列。所有交点参与捕获和扫掠检查。可一起抓一个 patch 的 9 颗、两个 patch 的 18 颗，或初始完整 36 颗。</p><div class="chips"><span>局部间距 10 μm</span><span>patch 原点间距 40 μm</span><span>四邻格保护：本例关闭</span><span>运动：正交通道</span></div><p>两个分离 patch 先执行目标 H，近接至 2 μm 后用一次共同脉冲执行多对 CZ，再分离至允许单比特光的位置。不是将串行门的时间标签画成重叠。</p><small>本轮会选择既有非均匀轴上的行列并整体平移；尚未让规划器搜索运输中的动态变距。EZ 范围是项目配置，不直接等同于论文设备光束尺寸。</small></div></section>
<section><h2>{headline}</h2><p>两者使用完全相同的二维布局、非均匀 AOD、194 门输入和全部归还终态。对称基线按电路顺序选择可共同搬运的门；新版贪心优先块内已就绪工作，再比较跨块组，加入同源行／列子组，并用 A* 几何下界剪枝。</p><table><thead><tr><th>指标</th><th>二维对称基线</th><th>二维并行贪心</th></tr></thead><tbody>{table}</tbody></table><p><small>编译秒数为本机单次观测，部分运行有并发负载；不据此宣称严格计算性能加速。旧单行成绩属于不同布局，不能混入本表。</small></p>{batch_rows}</section>
<section><h2>保留失败反例，再修策略</h2><p>初版二维贪心实际用时 <strong>{initial['metrics']['simulation_time_us']:,.1f} μs</strong>，比对称基线多 5,103.9 μs。它把最后 27 个跨块 CZ 从 2 批拆成 14 批；整个电路额外 13 轮装卸，光阱能并行，但调度没有利用好。</p><p>新增装卸耗时 2,600 μs、移动 2,486 μs、CZ 脉冲 3.9 μs、单比特时间 14 μs，恰好闭合全部损失。另一个漏项是三角形捕获组被拒绝后直接逐颗抓，错过同一行或列的合法两颗子组。</p><p>修订采用几何近邻连通分量识别空间块，优先当前可执行的块内门，避免提前打碎跨块批次；当依赖必须跨块推进时仍允许跨块。候选增加同源行／列的闭合子组，先检查捕获闭包和端点配对，再完整验证路径与执行。该有限启发式未宣称全局最优或对任意异构电路都更好。</p><p><a href="patch_greedy_initial/index.html">初版较慢结果的完整动画</a> · <a href="patch_greedy_initial/verification.json">初版独立重放</a> · <a href="ordering-analysis.json">六种排序思路的离线模型（非物理成绩）</a></p></section>
<section><h2>完整线路与验收证据</h2><p>编码 4 个 patch 后执行逻辑 CNOT 0→1，再执行互不共享块的 0→2、1→3。每个逻辑 CNOT 由九个对应数据 CNOT 组成；底层只有 H 和 CZ。</p><div class="circuit"><img src="circuit.svg" alt="完整194门线路，36条量子线"/></div><p><a href="input.json">可编辑输入 JSON</a> · <a href="circuit.qasm">完整 QASM</a> · <a href="circuit.csv">逐门 CSV</a> · <a href="comparison.json">真实比较数据</a> · <a href="patch_symmetric/verification.json">基线独立重放</a> · <a href="patch_greedy/verification.json">贪心独立重放</a> · <a href="patch_greedy/browser-acceptance.json">浏览器验收</a></p><p>全 EZ 实际作用对与预期整批对集合必须相等；逐门效果恰好一次，checkpoint 可恢复，归还终态通过。独立带符号 Pauli 核验全部 32 个码稳定子及 4 个逻辑 GHZ 稳定子。</p><small>这是理想酉编码和物理调度实验；不含辅助原子测量、重复纠错、噪声或容错制备。</small></section>
<section><h2>参考的实验组织方式</h2><p>采用二维数据 patch 交错、整体运输与对应数据门并行的结构，见 <a href="https://arxiv.org/html/2312.03982v1">Bluvstein 等：Logical quantum processor（Fig. 2 / Transversal gates）</a>。该论文的四逻辑 GHZ 使用 color code，本文没有将其误称为 surface-code GHZ 复现。非均匀 AOD 行列坐标与有序变距依据见 <a href="https://arxiv.org/html/2112.03923v1">2022 实验 Methods：Optical tweezer generation</a>。</p></section></main></html>'''
    (out/'index.html').write_text(page,encoding='utf-8')
    print(json.dumps(compare,ensure_ascii=False))


if __name__=='__main__':render()
