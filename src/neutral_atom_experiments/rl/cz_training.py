"""CZ-centred random matching circuits; transport cost drives learning."""
import argparse
from hashlib import sha256
from html import escape
import json
from pathlib import Path
import random
from statistics import mean

from neutral_atom_env.replay.serializer import canonical_json


def cz_manifest(distribution):
    cases=[];seen=set()
    for split in ('train','validation','test'):
        spec=distribution[split];rng=random.Random(spec['seed'])
        for i in range(spec['count']):
            n=spec['atom_counts'][i%len(spec['atom_counts'])]
            if n not in (4,6,8):raise ValueError('Supported atom count: 4,6,8')
            for _ in range(10000):
                gates=[]
                for _ in range(distribution['rounds']):
                    gates.extend(('H',[q]) for q in range(n))
                    order=list(range(n));rng.shuffle(order)
                    pairs=sorted(tuple(sorted(order[j:j+2])) for j in range(0,n,2))
                    gates.extend(('CZ',list(pair)) for pair in pairs)
                fingerprint=sha256(canonical_json([n,gates]).encode()).hexdigest()
                if fingerprint not in seen:seen.add(fingerprint);break
            else:raise RuntimeError('Distinct random matching corpus exhausted')
            cases.append(dict(name=f'{split}-cz-random-{i:03d}',split=split,atom_count=n,gates=gates,
                scale=1000.,family=f'random_cz_{n}q',fingerprint=fingerprint,generator_seed=spec['seed']))
    return cases


def render_report(output,report):
    output=Path(output);rows=report['test_results'];summaries=[]
    baseline={(r['training_seed'],r['name']):r for r in rows if r['policy']=='local_cost'}
    for label in ('untrained','imitation','ppo_last','ppo','local_cost','random'):
        group=[r for r in rows if r['policy']==label]
        good=[r for r in group if r['status']=='completed']
        deltas=[r['elapsed_us']-baseline[r['training_seed'],r['name']]['elapsed_us'] for r in good if baseline[r['training_seed'],r['name']]['status']=='completed']
        summaries.append(dict(policy=label,runs=len(group),successes=len(good),objective=mean(-r['return'] for r in group),
            mean_us=mean(r['elapsed_us'] for r in good) if good else None,
            wins=sum(d < -1e-7 for d in deltas),ties=sum(abs(d)<=1e-7 for d in deltas),losses=sum(d>1e-7 for d in deltas),
            max_cz_batch=max((r['max_cz_batch'] for r in good),default=0),
            per_seed={str(seed):mean(-r['return'] for r in group if r['training_seed']==seed) for seed in report['training_seeds']}))
    (output/'summary.json').write_text(canonical_json(summaries),encoding='utf-8')
    (output/'analysis.json').write_text(canonical_json({'summaries':summaries,'scope':'CZ matching pilot, no global transport optimality claim'}),encoding='utf-8')
    html='''<!doctype html><html lang="zh"><meta charset="utf-8"><title>双比特 CZ 学习验收</title><style>body{font:16px system-ui;max-width:1100px;margin:35px auto;padding:20px;background:#f5f7fb;color:#253149}p{line-height:1.8}table{width:100%;border-collapse:collapse;background:white}td,th{padding:12px;border-bottom:1px solid #ddd;text-align:left}a{color:#4358ab}</style><h1>以 CZ 执行与运输为核心的随机电路训练</h1>
<p>每条线路包含两轮随机完美匹配CZ，中间加入H层打破直接重复CZ抵消。训练4/6原子，测试4/6/8原子；H只作为线路的准备与依赖，不再用纯单比特合批替代双比特训练。线路随机生成，不根据贪心输赢筛选。</p>
<p>策略选择待执行CZ批次、移动操作数以及靠近伙伴的方向；几何工具生成有限合法路线。奖励按完整物理时间计算，包括装载、移动、CZ、卸载和最终清理。仍使用每批CZ归还的受限候选，没有学习自由驻留或连续轨迹，旧greedy/物理环境不改。</p>'''
    html+=f'<p>{report["train_size"]}训练 / {report["validation_size"]}验证 / {report["test_size"]}测试；实际PPO采样{report["training_samples"]}，训练失败{report["training_failures"]}，两seed；总实验{report["elapsed_seconds"]:.1f}秒。</p><table><tr><th>策略</th><th>完成</th><th>成功平均μs</th><th>目标（含失败惩罚）</th><th>胜/平/负</th><th>最大CZ批次</th></tr>'
    for s in summaries:html+=f'<tr><td>{s["policy"]}</td><td>{s["successes"]}/{s["runs"]}</td><td>{s["mean_us"]}</td><td>{s["objective"]:.4f}</td><td>{s["wins"]}/{s["ties"]}/{s["losses"]}</td><td>{s["max_cz_batch"]}</td></tr>'
    html+='</table><p>ppo仅由验证集选出；ppo_last为最后模型。基线为隔离local_cost，不冒充生产M4。两个训练seed重复测试相同6条线路，不是12个独立线路样本。</p>'
    selection={str(seed):sorted({r['selected_update'] for r in rows if r['policy']=='ppo' and r['training_seed']==seed}) for seed in report['training_seeds']}
    html+=f'<p>验证选中的更新轮次：{escape(str(selection))}。0表示保留模仿模型，不能算PPO训练增益。</p>'
    selected=next(s for s in summaries if s['policy']=='ppo');base=next(s for s in summaries if s['policy']=='local_cost')
    conclusion='仍有执行失败，不能宣称可靠完成。' if selected['successes']<selected['runs'] else '本轮平均目标优于局部基线，仅是小样本先导结果。' if selected['objective']<base['objective'] else '本轮平均目标尚未优于局部基线，不替换现有策略。'
    html+=f'<p><strong>{conclusion}</strong></p>'
    failures=[{k:r.get(k) for k in ('name','policy','training_seed','failure')} for r in rows if r['status']!='completed']
    if failures:html+='<details open><summary>执行失败记录</summary><pre>'+escape(json.dumps(failures,ensure_ascii=False,indent=2))+'</pre></details>'
    if (output.parent/'attempt1/failure.json').exists():
        html+='<p role="alert">第一轮曾因候选预算被轴容量不可能的批次占满而失败。已保留<a href="../attempt1/index.html">失败记录</a>，本轮在预算前做必要容量检查，以同一电路与超参数重新训练。测试清单用于过工程故障定位，不宣称完全未触碰的研究测试集。</p>'
    if (output/'acceptance.json').exists():
        html+='<h2>完整线路 + 同步原子回放</h2><p>下列页面均展示完整输入电路，点击任意门可定位真实脉冲，播放时同步标记已完成/准备/作用状态。</p>'
        names={'ppo_last':'PPO训练后（最后权重）','ppo':'验证选中模型','local_cost':'局部贪心基线'}
        for p in sorted((output/'replays').glob('*/*/animation.html')):
            html+=f'<p><a href="{p.relative_to(output).as_posix()}">{escape(p.parent.parent.name)} · {escape(names[p.parent.name])}</a></p>'
        html+='<p><a href="acceptance.json">逐门、运输、重放与加载权重核验</a></p>'
    html+='<p><a href="manifest.json">全部输入线路</a> · <a href="config.json">冻结配置</a> · <a href="report.json">全部结果</a> · <a href="summary.json">汇总</a></p></html>'
    (output/'index.html').write_text(html,encoding='utf-8')


def render_failure(output,failure):
    output=Path(output)
    text='<!doctype html><html lang="zh"><meta charset="utf-8"><title>CZ第一轮失败记录</title><body style="font:16px system-ui;max-width:900px;margin:40px auto;line-height:1.8"><h1>第一轮已停止：候选预算被不可能的批次占满</h1><p role="alert">单行AOD无法抓取两行原子。120个候选中，前24个全部因行数超限被拒绝，剩余96个未被尝试，触发CANDIDATES_EXHAUSTED。这不是物理无解证明，也不是放宽硬件的理由。</p><p>修复：在昂贵规划预算之前检查必要轴容量，合法候选仍经过完整物理校验。保留第一轮部分记录，在新目录以同一随机线路、seed和超参数重跑。</p><pre>'+escape(json.dumps(failure,ensure_ascii=False,indent=2))+'</pre><a href="failure.json">结构化失败记录</a></body></html>'
    (output/'index.html').write_text(text,encoding='utf-8')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--config',default='configs/rl/cz.json');parser.add_argument('--output',default='artifacts/rl-cz/attempt1');args=parser.parse_args()
    config=json.loads(Path(args.config).read_text(encoding='utf-8'))
    if config['schema']!='rl-cz-v1':raise ValueError('Unknown schema')
    from .train import run
    run(config,args.output,cases=cz_manifest(config['distribution']),renderer=render_report)


if __name__=='__main__':main()
