"""Unfiltered random 1Q scheduling curriculum, isolated from production policy."""
import argparse
from hashlib import sha256
from html import escape
import json
from pathlib import Path
import random
from statistics import mean

from neutral_atom_env.replay.serializer import canonical_json
from .training_cases import wire_case


def random_manifest(distribution):
    """Sampling never consults a baseline, an oracle, or a trained model.

    Exclude exact wire-permutation duplicates across splits. Excluding adjacent
    equal gates is generator hygiene, not a claim of algebraic normal form.
    """
    kinds=distribution['gate_set']
    if len(set(kinds))<2 or not set(kinds)<=set('HXYZT'):
        raise ValueError('Expected at least two distinct supported 1Q gates')
    low,high=distribution['wire_length']
    if not 1<=low<=high:raise ValueError('Invalid wire length')
    seen=set();cases=[]
    for split in ('train','validation','test'):
        spec=distribution[split];rng=random.Random(spec['seed'])
        if not spec['atom_counts'] or not set(spec['atom_counts'])<= {4,6,8}:
            raise ValueError('Supported atom counts are 4, 6, 8')
        for i in range(spec['count']):
            count=spec['atom_counts'][i%len(spec['atom_counts'])]
            for _ in range(10000):
                words=[]
                for _ in range(count):
                    word=''
                    for _ in range(rng.randint(low,high)):
                        choices=[k for k in kinds if not distribution['reject_adjacent_equal'] or not word or k!=word[-1]]
                        word+=rng.choice(choices)
                    words.append(word)
                key=tuple(sorted(words))
                if key not in seen:seen.add(key);break
            else:raise RuntimeError('Random corpus exhausted distinct circuits')
            case=wire_case(f'{split}-random-{i:03d}',words,split)
            case.update(family=f'random_{count}q',generator_seed=spec['seed'],
                        fingerprint=sha256(canonical_json([count,case['gates']]).encode()).hexdigest())
            cases.append(case)
    return cases


def summaries(report):
    results=report['test_results'];out=[]
    baselines={(r['training_seed'],r['name']):r for r in results if r['policy']=='local_cost'}
    for family in ('all',*sorted({r['family'] for r in results})):
        for policy in ('untrained','imitation','ppo_last','ppo','local_cost','random'):
            rows=[r for r in results if r['policy']==policy and (family=='all' or r['family']==family)]
            success=[r for r in rows if r['status']=='completed']
            paired=[r for r in success if baselines[r['training_seed'],r['name']]['status']=='completed']
            deltas=[r['elapsed_us']-baselines[r['training_seed'],r['name']]['elapsed_us'] for r in paired]
            out.append(dict(family=family,policy=policy,runs=len(rows),successes=len(success),
                objective=mean(-r['return'] for r in rows),
                mean_success_us=mean(r['elapsed_us'] for r in success) if success else None,
                wins=sum(d < -1e-8 for d in deltas),ties=sum(abs(d)<1e-8 for d in deltas),losses=sum(d>1e-8 for d in deltas),
                optima=sum(abs(r['elapsed_us']-r['optimum_us'])<1e-8 for r in success),
                per_seed={str(seed):mean(-r['return'] for r in rows if r['training_seed']==seed) for seed in report['training_seeds']}))
    return out


def render_report(output,report):
    output=Path(output);summary=summaries(report)
    (output/'summary.json').write_text(canonical_json(summary),encoding='utf-8')
    # Replace the shared runner's historical Stage-B (nine-case) narrative.
    analysis={'schema':'rl-random-analysis-v1','summaries':summary,
        'unique_test_circuits':len({r['name'] for r in report['test_results']}),
        'training_seeds':report['training_seeds'],
        'selected_updates':{str(seed):sorted({r['selected_update'] for r in report['test_results']
            if r['training_seed']==seed and r['policy']=='ppo'}) for seed in report['training_seeds']},
        'uncertainty':'Small fixed corpus and two training seeds; repeated policy/seed evaluations are not independent circuits.'}
    (output/'analysis.json').write_text(canonical_json(analysis),encoding='utf-8')
    html='''<!doctype html><html lang="zh"><meta charset="utf-8"><title>随机电路 RL 实验</title>
<style>body{font:16px system-ui;max-width:1180px;margin:40px auto;padding:20px;background:#f5f7fb;color:#253149}p{line-height:1.8}table{border-collapse:collapse;width:100%;background:white}td,th{padding:10px;border-bottom:1px solid #ddd;text-align:left}a{color:#4358ab}code{background:#eee;padding:3px}</style>
<h1>从随机电路学习同门并行</h1>
<p>冻结随机清单：48训练 / 24验证 / 32未见测试。训练为4原子，测试一半4原子、一半6原子；H/X/Y/Z/T，每根线随机2–5门。每次从与前一门不同的门中均匀抽样，不包含相邻重复门；未做完整代数优化。生成器不查询贪心、精确最优或网络分数，不筛选贪心反例。</p>
<p>独立图网络先模仿局部成本策略，再做PPO；片段最多16步，结束电路才复位。验证集只用于选模（允许保留更新0的模仿模型）；测试集只在训练完成后评估。这里的local_cost是隔离的局部成本基线，不是生产M4贪心。</p>
<p><strong>范围：单比特物理门调度。没有训练CZ运输、测量、跨批驻留或长电路，也不代表任意量子算法已可泛化。</strong>两训练seed、32个不同测试电路只是先导实验。</p>'''
    html+=f'<p>实际PPO采样 {report["training_samples"]} 次；训练失败 {report["training_failures"]} 次；总实验耗时 {report["elapsed_seconds"]:.1f} 秒（包含评估与导出）。</p>'
    reference=[r for r in report['test_results'] if r['policy']=='local_cost' and r['training_seed']==report['training_seeds'][0]]
    html+=f'<p>32条测试电路的固定输入精确最优平均值：{mean(r["optimum_us"] for r in reference):.4f} μs。该值在测试时计算，不参与随机生成、训练奖励或选模。</p>'
    selected=next(s for s in summary if s['family']=='all' and s['policy']=='ppo')
    baseline=next(s for s in summary if s['family']=='all' and s['policy']=='local_cost')
    conclusion='本轮已选模型的平均目标仍未超过局部贪心，不替换现有策略。' if selected['objective']>=baseline['objective'] else '本轮已选模型的平均目标优于局部贪心；只代表此冻结分布的先导结果，不代表稳定泛化。'
    html+=f'<p style="background:#fff1ce;padding:16px;border-left:4px solid #aa7210"><strong>{conclusion}</strong></p>'
    html+='<h2>独立测试结果</h2><p>目标列是平均负回报，失败带惩罚，越小越好；全部成功时等于平均μs。胜/平/负相对于相同电路与初态的local_cost，最优指保留全部输入门的最少同类型脉冲数。两个seed重复测试相同32条电路，不能视为64条独立电路。</p><table><tr><th>范围</th><th>模型</th><th>完成</th><th>目标</th><th>胜/平/负</th><th>达到最优</th><th>seed目标</th></tr>'
    for s in summary:
        html+=f'<tr><td>{s["family"]}</td><td>{s["policy"]}</td><td>{s["successes"]}/{s["runs"]}</td><td>{s["objective"]:.4f}</td><td>{s["wins"]}/{s["ties"]}/{s["losses"]}</td><td>{s["optima"]}/{s["runs"]}</td><td>{escape(str(s["per_seed"]))}</td></tr>'
    html+='</table><h2>原来的6μs / 7μs</h2><p>四条线分别为 HX、HHXX、HX、XHHH，共12个门。7μs顺序为 <code>HXHHHXX</code>，6μs为 <code>XHHHXX</code>；都是每种脉冲1μs，没有增加搬运或输入门。先做X让下一批H能包含4个原子，代替贪心先做3个H。原电路有可消去的HH/XX，是固定输入的排程反例，不能当作经过优化的算法电路；新随机生成器排除了直接相邻重复门。</p>'
    html+='<p><a href="../six-seven-audit.json">6/7逐门物理审计</a> · <a href="manifest.json">全部随机线路</a> · <a href="config.json">配置</a> · <a href="summary.json">汇总JSON</a> · <a href="report.json">完整结果</a></p>'
    if (output/'acceptance.json').exists():
        acceptance=json.loads((output/'acceptance.json').read_text(encoding='utf-8'))
        diagnostics=acceptance['selected_policy_decision_diagnostics']
        html+='<h2>已选模型的决策诊断</h2><p>在训练与选模全部结束后，逐步计算每个动作离精确最优还差多少；不把诊断反馈给本轮训练。</p>'
        html+=f'<p>64次已选模型测试累计可避免 {sum(r["avoidable_us"] for r in diagnostics):.0f} μs；选择非最优门类型 {sum(r["suboptimal_gate_kind_decisions"] for r in diagnostics)} 次；拆分当前可合批同类型门 {sum(r["partial_same_kind_batches"] for r in diagnostics)} 次。门类型错误次数不是独立电路数，也不等于损失的μs。</p>'
        html+='<p><a href="acceptance.json">执行/重放验收与权重加载</a></p>'
        for label in ('ppo','local_cost'):
            html+=f'<p><a href="animations/{label}/animation.html">首个6原子未见随机电路：{label} 动画</a></p>'
    html+='</html>'
    (output/'index.html').write_text(html,encoding='utf-8')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',default='configs/rl/random.json')
    parser.add_argument('--output',default='artifacts/rl-random/attempt1')
    args=parser.parse_args();config=json.loads(Path(args.config).read_text(encoding='utf-8'))
    if config['schema']!='rl-random-v1':raise ValueError('Unknown config schema')
    from .train import run
    run(config,args.output,cases=random_manifest(config['distribution']),renderer=render_report)


if __name__=='__main__':main()
