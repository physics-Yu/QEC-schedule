"""Standalone parallel rollout acceptance; no neural training or production hooks."""
import argparse
from concurrent.futures import ProcessPoolExecutor
from hashlib import sha256
from html import escape
import json
from pathlib import Path
from time import perf_counter

from neutral_atom_env import NeutralAtomEnv
from neutral_atom_env.replay.serializer import canonical_json
from neutral_atom_env.visualization.recording import VisualRecorder
from neutral_atom_strategies.learning import DecisionEnv, EpisodeConfig
from neutral_atom_strategies.learning.policies import LocalCostPolicy, RandomPolicy
from .instances import make_snapshot,suite


def run_case(job):
    name,seed,policy_name,config,fragment_length,directory=job
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    n,gates=suite(seed)[name]
    initial=make_snapshot(gates,n,seed)
    env=DecisionEnv(initial,EpisodeConfig(**config))
    policy=RandomPolicy(seed) if policy_name=='random' else LocalCostPolicy()
    fragments=[]
    start=perf_counter()
    while env.status=='running':
        fragments.append(env.collect_fragment(policy,fragment_length))
    elapsed=perf_counter()-start
    audit_start=perf_counter()
    audit=env.audit()
    audit_seconds=perf_counter()-audit_start
    rewards=sum(t['reward'] for t in env.history)
    assert abs(rewards-env.total_reward)<1e-8
    if env.status=='completed':
        assert abs(rewards+audit['elapsed_us']/env.config.reward_scale_us)<1e-8
    assert audit['replay_equal'] and audit['effects_once']
    result=dict(audit,case=name,seed=seed,policy=policy_name,wall_seconds=elapsed,
        audit_seconds=audit_seconds,decisions_per_second=len(env.history)/elapsed if elapsed else 0,
        planning_seconds=sum(t['planning_seconds'] for t in env.history),
        execution_seconds=sum(t['execution_seconds'] for t in env.history),
        initial_sha256=sha256(initial.encode()).hexdigest(),
        final_sha256=sha256(env.snapshot()['current'].encode()).hexdigest(),
        fragment_count=len(fragments),fragment_cuts=sum(f['fragment_cut'] for f in fragments),
        max_batch=max((len(c['gate_ids']) for t in env.history for c in t['observation']['candidates']
                      if c['id']==t['action_id'] and t['executed']),default=0),
        max_cz_batch=max((len(c['gate_ids']) for t in env.history for c in t['observation']['candidates']
                      if c['kind']=='CZ' and c['id']==t['action_id'] and t['executed']),default=0),
        scope='untrained isolated controls; ordered-axis restoring services; finite candidates')
    (directory/'result.json').write_text(canonical_json(result),encoding='utf-8')
    (directory/'fragments.json').write_text(canonical_json(fragments),encoding='utf-8')
    (directory/'checkpoint.json').write_text(canonical_json(env.snapshot()),encoding='utf-8')
    (directory/'input.json').write_text(canonical_json({'name':name,'seed':seed,'atom_count':n,'gates':gates,'config':config}),encoding='utf-8')
    (directory/'plans.json').write_text(canonical_json(env.plans),encoding='utf-8')
    if policy_name=='random':
        (directory/'policy.json').write_text(canonical_json(policy.state_dict()),encoding='utf-8')
    if name=='eight_atoms' and policy_name=='local_cost' and seed==0:
        replay=NeutralAtomEnv.restore(initial);recorder=VisualRecorder(replay.state)
        for plan in env.plans:
            replay.submit(plan);replay.run(on_event=lambda s,e:recorder.observe(s))
        assert replay.snapshot()==env.snapshot()['current']
        from .circuit_replay import write_circuit_replay
        write_circuit_replay({'name':name,'atom_count':n,'gates':gates},recorder.payload(),directory/'animation.html',label=policy_name)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',default='configs/rl/stage_a.json')
    parser.add_argument('--output',default='artifacts/rl-stage-a/acceptance')
    parser.add_argument('--workers',type=int)
    parser.add_argument('--cases',nargs='*')
    args=parser.parse_args()
    config=json.loads(Path(args.config).read_text(encoding='utf-8'))
    if config['schema']!='rl-stage-a-v1':raise ValueError('Unsupported config schema')
    workers=args.workers if args.workers is not None else config['workers']
    if type(workers) is not int or workers<1:raise ValueError('workers must be positive')
    if any(p not in {'random','local_cost'} for p in config['policies']):raise ValueError('Unknown policy')
    if type(config['fragment_length']) is not int or config['fragment_length']<1:raise ValueError('Invalid fragment length')
    directory=Path(args.output);directory.mkdir(parents=True,exist_ok=True)
    jobs=[(name,seed,policy,config['episode'],config['fragment_length'],str(directory/f'{name}-{policy}-seed{seed}'))
          for seed in config['seeds'] for name in (args.cases or suite(seed)) for policy in config['policies']]
    effective=dict(config,workers=workers,cases=args.cases)
    (directory/'config.json').write_text(canonical_json(effective),encoding='utf-8')
    start=perf_counter();results=[]
    pool=ProcessPoolExecutor(max_workers=workers) if workers>1 else None
    try:
        runs=pool.map(run_case,jobs) if pool else map(run_case,jobs)
        for result in runs:
            results.append(result)
            print(f"{result['case']} / {result['policy']} / {result['seed']}: {result['status']}, {result['elapsed_us']:.3f} us, {result['wall_seconds']:.2f} s",flush=True)
    finally:
        if pool:pool.shutdown()
    report={'schema':'rl-stage-a-report-v1','workers':workers,'wall_seconds':perf_counter()-start,
            'episodes':len(results),'successes':sum(r['status']=='completed' for r in results),
            'all_replays_equal':all(r['replay_equal'] for r in results),
            'all_effects_once':all(r['effects_once'] for r in results),'results':results,
            'neural_training_started':False}
    report['episodes_per_second']=report['episodes']/report['wall_seconds']
    report['decisions_per_second']=sum(r['decisions'] for r in results)/report['wall_seconds']
    (directory/'report.json').write_text(canonical_json(report),encoding='utf-8')
    rows=''.join('<tr>'+''.join(f'<td>{escape(str(value))}</td>' for value in
        (r['case'],r['policy'],r['seed'],r['status'],round(r['elapsed_us'],3),
         round(r['wall_seconds'],3),r['max_batch'],r['replay_equal']))+'</tr>' for r in results)
    html='''<!doctype html><html lang="zh"><meta charset="utf-8"><title>RL 阶段 A 验收</title>
<style>body{font:16px system-ui;max-width:1150px;margin:40px auto;padding:20px;color:#243249;background:#f5f7fb}
table{border-collapse:collapse;width:100%;background:white}td,th{padding:12px;border-bottom:1px solid #ddd;text-align:left}
a{color:#4058ad}p{line-height:1.7}</style><h1>独立 RL 基础接口 · 阶段 A</h1>
<p>随机与独立局部成本基线，尚无神经网络训练。旧 greedy 和 8798 工作台未接入此实验。
片段边界保留状态，CZ 服务仍采用返回方式；有限候选不能代表全空间。</p>'''
    html+=f'<p>完成 {report["successes"]}/{report["episodes"]}；独立重放全部一致：{report["all_replays_equal"]}。</p>'
    animation='eight_atoms-local_cost-seed0/animation.html'
    if (directory/animation).exists():html+=f'<p><a href="{animation}">查看 8 原子物理动画</a> · <a href="report.json">完整机器可读报告</a></p>'
    html+='<table><tr>'+''.join(f'<th>{h}</th>' for h in ('电路','基线','Seed','结果','物理 μs','采样秒数','最大合批','重放一致'))+'</tr>'+rows+'</table></html>'
    (directory/'index.html').write_text(html,encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='results'},indent=2),flush=True)
    if report['successes']!=report['episodes']:raise SystemExit(1)


if __name__=='__main__':main()
