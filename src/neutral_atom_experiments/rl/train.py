"""Small, reproducible imitation + on-policy PPO experiment, opt-in only."""
import argparse
from concurrent.futures import ProcessPoolExecutor
from copy import deepcopy
from dataclasses import asdict
from hashlib import sha256
from html import escape
import json
from pathlib import Path
import random
from time import perf_counter

import torch
from neutral_atom_env import NeutralAtomEnv
from neutral_atom_env.visualization.recording import VisualRecorder
from neutral_atom_env.replay.serializer import canonical_json
from neutral_atom_strategies.learning import EpisodeConfig
from neutral_atom_strategies.learning.cache import ExactCandidateCache,cached_environment
from neutral_atom_strategies.learning.network import GraphActorCritic,gae,ppo_update
from neutral_atom_strategies.learning.policies import LocalCostPolicy,RandomPolicy
from .training_cases import manifest,initial,wire_optimum
from .analysis import aggregate

CACHE=None


def worker_init():
    global CACHE
    torch.set_num_threads(1)
    CACHE=ExactCandidateCache(128)


def work(job):
    case=job['case'];config=EpisodeConfig(**dict(job['episode'],reward_scale_us=case['scale']))
    start=perf_counter();hits=CACHE.hits;misses=CACHE.misses
    source=initial(case)
    env=cached_environment(source,config,CACHE,job.get('checkpoint'))
    model=None
    if job.get('weights') is not None:
        model=GraphActorCritic(job['hidden']);model.load_state_dict(job['weights']);model.eval()
    torch.manual_seed(job['seed'])
    policy=LocalCostPolicy() if job['policy']=='local_cost' else RandomPolicy(job['seed'])
    samples=[];actions=[]
    limit=job.get('fragment_length',config.max_decisions+1)
    for _ in range(limit):
        if env.status!='running':break
        obs=env.observe()
        if model is not None:
            index,logp,value=model.choose(obs,deterministic=job['mode']=='evaluate')
            action=obs['candidates'][index]['id'] if index is not None else None
        else:
            action=policy(obs)
            index=next((i for i,c in enumerate(obs['candidates']) if c['id']==action),None)
            logp=value=0.
        transition=env.step(action)
        samples.append({'observation':obs,'index':index,'logp':logp,'value':value,
                        'reward':transition['reward'],'terminated':transition['terminated']})
        actions.append(next((c for c in obs['candidates'] if c['id']==action),None))
    final=env.observe()
    bootstrap=0.
    if env.status=='running' and model is not None:
        with torch.no_grad():bootstrap=float(model(final)[1])
    adv,returns=gae([s['reward'] for s in samples],[s['value'] for s in samples],
                    [s['terminated'] for s in samples],bootstrap)
    for s,a,r in zip(samples,adv,returns):s.update(advantage=a,return_=r)
    # Use a JSON-friendly key while preserving compatibility with update helper.
    for s in samples:s['return']=s.pop('return_')
    result={'name':case['name'],'status':env.status,'failure':env.failure,
        'elapsed_us':final['elapsed_us'],'return':env.total_reward,'wall_seconds':perf_counter()-start,
        'cache_hits':CACHE.hits-hits,'cache_misses':CACHE.misses-misses,
        'checkpoint':env.snapshot(),'samples':samples,'bootstrap':bootstrap,
        'fragment_cut':env.status=='running','initial_sha256':sha256(source.encode()).hexdigest()}
    if job['mode']=='evaluate':
        result.update(env.audit())
        assert result['replay_equal'] and result['effects_once']
        result.update(optimum_us=wire_optimum(case),family=case['family'],policy=job['policy'],
                      max_cz_batch=max((len(a['gate_ids']) for a in actions if a and a['kind']=='CZ'),default=0))
        directory=job.get('directory')
        if directory:
            path=Path(directory);path.mkdir(parents=True,exist_ok=True)
            (path/'case.json').write_text(canonical_json(case),encoding='utf-8')
            (path/'checkpoint.json').write_text(canonical_json(env.snapshot()),encoding='utf-8')
            (path/'decisions.json').write_text(canonical_json(env.history),encoding='utf-8')
            (path/'plans.json').write_text(canonical_json(env.plans),encoding='utf-8')
            if case['name']=='test-cz-8' and job['policy'] in ('ppo','local_cost'):
                replay=NeutralAtomEnv.restore(source);recorder=VisualRecorder(replay.state)
                for plan in env.plans:
                    replay.submit(plan);replay.run(on_event=lambda s,e:recorder.observe(s))
                assert replay.snapshot()==env.snapshot()['current']
                from .circuit_replay import write_circuit_replay
                write_circuit_replay(case,recorder.payload(),path/'animation.html',label=job['policy'])
        result.pop('checkpoint');result.pop('samples')
    return result


def serial_weights(model):return {k:v.detach().cpu().clone() for k,v in model.state_dict().items()}


def save_model(path,model,metadata):
    torch.save({'schema':'rl-graph-ppo-v1','hidden':model.hidden,'weights':serial_weights(model),'metadata':metadata},path)


def score(results):
    # Same per-instance normalization as the reward, including failure penalty.
    # Mixing raw us would let a CZ case outweigh every short 1Q case.
    return sum(-r['return'] for r in results)/len(results)


def run(config,output,*,cases=None,renderer=None):
    output=Path(output)
    if (output/'status.json').exists():raise ValueError('Use a fresh output directory to preserve prior attempts')
    output.mkdir(parents=True,exist_ok=True)
    cases=manifest() if cases is None else cases
    train=[c for c in cases if c['split']=='train'];validation=[c for c in cases if c['split']=='validation'];test=[c for c in cases if c['split']=='test']
    for filename,value in [('config.json',config),('manifest.json',cases)]:
        (output/filename).write_text(canonical_json(value),encoding='utf-8')
    def status(**values):(output/'status.json').write_text(canonical_json(values),encoding='utf-8')
    status(status='running',phase='teacher')
    torch.set_num_threads(1)
    pool=ProcessPoolExecutor(config['workers'],initializer=worker_init)
    base={'episode':config['episode'],'hidden':config['hidden']}
    started=perf_counter();all_tests=[];training_logs=[]
    try:
        teacher=list(pool.map(work,[dict(base,mode='teacher',case=c,policy='local_cost',seed=0) for c in train]))
        if any(r['status']!='completed' for r in teacher):
            raise RuntimeError('Teacher failed within the declared finite candidate family')
        demonstrations=[s for r in teacher for s in r['samples'] if s['index'] is not None]
        (output/'demonstrations.json').write_text(canonical_json(teacher),encoding='utf-8')
        print(f'Teacher: {len(train)} training circuits, {len(demonstrations)} decisions',flush=True)
        for seed in config['training_seeds']:
            directory=output/f'seed-{seed}';directory.mkdir()
            torch.manual_seed(seed);rng=random.Random(seed)
            model=GraphActorCritic(config['hidden'])
            untrained=serial_weights(model)
            save_model(directory/'untrained.pt',model,{'stage':'untrained','seed':seed})
            optimizer=torch.optim.Adam(model.parameters(),lr=.003)
            for epoch in range(config['imitation_epochs']):
                indices=list(range(len(demonstrations)));rng.shuffle(indices)
                for start in range(0,len(indices),32):
                    losses=[]
                    for i in indices[start:start+32]:
                        sample=demonstrations[i];logits,_=model(sample['observation'])
                        losses.append(-torch.log_softmax(logits,dim=0)[sample['index']])
                    loss=torch.stack(losses).mean();optimizer.zero_grad();loss.backward();optimizer.step()
            warm=serial_weights(model)
            save_model(directory/'imitation.pt',model,{'stage':'imitation','seed':seed,'teacher':'local_cost'})
            print(f'Seed {seed}: imitation complete',flush=True)
            # Selection uses validation ONLY; test data is untouched until training ends.
            def evaluate(weights,subset,policy='ppo',save=False):
                jobs=[dict(base,mode='evaluate',case=c,policy=policy,weights=weights,seed=seed,
                    directory=str(directory/'evaluation'/policy/c['name']) if save else None) for c in subset]
                return list(pool.map(work,jobs))
            initial_validation=evaluate(warm,validation)
            best_score=score(initial_validation);best=deepcopy(warm);best_update=0
            slots=[None]*config['slots'];slot_cases=[None]*config['slots'];episode_number=0
            optimizer=torch.optim.Adam(model.parameters(),lr=config['learning_rate'])
            seed_log=[]
            for update in range(1,config['updates']+1):
                tick=perf_counter();weights=serial_weights(model);jobs=[]
                for slot in range(config['slots']):
                    if slots[slot] is None:
                        slot_cases[slot]=train[episode_number%len(train)];episode_number+=1
                    jobs.append(dict(base,mode='collect',case=slot_cases[slot],checkpoint=slots[slot],
                        policy='ppo',weights=weights,seed=seed*100000+update*100+slot,
                        fragment_length=config['fragment_length']))
                fragments=list(pool.map(work,jobs))
                samples=[s for f in fragments for s in f['samples']]
                for slot,f in enumerate(fragments):slots[slot]=f['checkpoint'] if f['fragment_cut'] else None
                loss=ppo_update(model,optimizer,samples,epochs=config['ppo_epochs'])
                record={'seed':seed,'update':update,'samples':len(samples),'loss':loss,
                        'completed':sum(f['status']=='completed' for f in fragments),
                        'failures':[f['failure'] for f in fragments if f['failure']],
                        'fragment_cuts':sum(f['fragment_cut'] for f in fragments),
                        'cache_hits':sum(f['cache_hits'] for f in fragments),'cache_misses':sum(f['cache_misses'] for f in fragments),
                        'seconds':perf_counter()-tick}
                if update%config['validation_interval']==0 or update==config['updates']:
                    evaluated=evaluate(serial_weights(model),validation)
                    current=score(evaluated);record['validation']=evaluated;record['validation_score']=current
                    if current<best_score-1e-8:
                        best_score=current;best=serial_weights(model);best_update=update
                seed_log.append(record)
                with (directory/'training.jsonl').open('a',encoding='utf-8') as handle:handle.write(canonical_json(record)+'\n')
                status(status='running',phase='ppo',seed=seed,update=update,total=config['updates'])
                print(f'Seed {seed} update {update}/{config["updates"]}: {len(samples)} samples, loss {loss:.4f}, cache {record["cache_hits"]}/{record["cache_hits"]+record["cache_misses"]}, {record["seconds"]:.1f}s',flush=True)
            save_model(directory/'last.pt',model,{'stage':'ppo_last','seed':seed,'updates':config['updates']})
            last=serial_weights(model)
            model.load_state_dict(best)
            save_model(directory/'selected.pt',model,{'stage':'ppo' if best_update else 'imitation','seed':seed,'selected_update':best_update,'validation_score':best_score})
            tests=[]
            for label,weights in [('untrained',untrained),('imitation',warm),('ppo_last',last),('ppo',best),('local_cost',None),('random',None)]:
                status(status='running',phase='held_out_evaluation',seed=seed,policy=label)
                results=evaluate(weights,test,label,save=True)
                for r in results:r.update(training_seed=seed,selected_update=best_update if label=='ppo' else None)
                tests.extend(results)
                print(f'Seed {seed} held-out {label}: {sum(r["status"]=="completed" for r in results)}/{len(results)} complete',flush=True)
            all_tests.extend(tests);training_logs.extend(seed_log)
            (directory/'test.json').write_text(canonical_json(tests),encoding='utf-8')
        report={'schema':'rl-stage-b-report-v1','elapsed_seconds':perf_counter()-started,
                'training_seeds':config['training_seeds'],'updates_per_seed':config['updates'],
                'training_samples':sum(r['samples'] for r in training_logs),
                'training_failures':sum(len(r['failures']) for r in training_logs),
                'test_results':all_tests,'train_size':len(train),'validation_size':len(validation),'test_size':len(test),
                'selection_rule':'minimum mean negative normalized return on validation only; imitation incumbent allowed at update 0',
                'scope':'finite restoring stage-A candidate selection; no residency, measurement or universal optimality claim'}
        (output/'report.json').write_text(canonical_json(report),encoding='utf-8')
        (output/'analysis.json').write_text(canonical_json(aggregate(report)),encoding='utf-8')
        (renderer or render_report)(output,report)
        status(status='completed',elapsed_seconds=report['elapsed_seconds'],training_samples=report['training_samples'])
        return report
    except Exception as error:
        status(status='failed',error={'type':type(error).__name__,'message':str(error)})
        raise
    finally:pool.shutdown()


def render_report(output,report):
    rows=[]
    for result in report['test_results']:
        rows.append('<tr>'+''.join(f'<td>{escape(str(v))}</td>' for v in
            (result['training_seed'],result['name'],result['policy'],result['status'],
             round(result['elapsed_us'],3),result['optimum_us'],result['selected_update']))+'</tr>')
    text='''<!doctype html><html lang="zh"><meta charset="utf-8"><title>RL 第二步实验</title>
<style>body{font:16px system-ui;color:#243249;background:#f5f7fb;max-width:1200px;margin:40px auto;padding:20px}p{line-height:1.7}
table{border-collapse:collapse;width:100%;background:white}td,th{padding:10px;border-bottom:1px solid #ddd;text-align:left}a{color:#4358ab}</style>
<h1>独立 RL 第二步 · 小规模学习</h1><p>图网络、局部成本模仿预训练、PPO连续分段采样。
相同物理候选空间与终态；旧greedy和8798工作台未改。模型仅按验证集选取，未见测试集不参与更新。</p>
<p>PPO列为验证集选出的模型；更新编号0意味着模仿模型仍是最佳，不能记作PPO提升。
“精确最优”仅指纯单比特小实例的动态规划最少脉冲数，不是CZ运输全局最优。</p>'''
    text+=f'<p>训练样本 {report["training_samples"]}；训练失败 {report["training_failures"]}；耗时 {report["elapsed_seconds"]:.1f} 秒。</p>'
    acceptance_path=output/'acceptance.json'
    if acceptance_path.exists():
        acceptance=json.loads(acceptance_path.read_text(encoding='utf-8'))
        text+='<p style="padding:16px;background:#fff1ce;border-left:4px solid #aa7210"><strong>执行验收通过；性能优势尚未成立。</strong>两个训练种子表现不一致；6μs反例仍用了7μs。当前不宣称优于基线，也不以成功执行替代学习效果验收。</p>'
        text+='<p><a href="acceptance.json">验收与未完成项</a> · <a href="diagnosis.json">最优反例物理诊断</a></p>'
    analysis=aggregate(report)
    text+='<h2>全部测试汇总</h2><p>耗时比是每个测试电路相对同条件局部成本基线的比值再取平均；小于1更快。只对双方成功样本计算比值，失败单列。两训练seed和九条测试电路仅为初试。</p><table><tr><th>策略</th><th>完成</th><th>平均耗时比</th></tr>'
    for summary in analysis['summaries']:
        ratio=summary['mean_ratio_to_local_cost_on_success']
        text+=f'<tr><td>{summary["policy"]}</td><td>{summary["successes"]}/{summary["cases"]}</td><td>{ratio:.4f}</td></tr>' if ratio is not None else ''
    text+='</table><h2>逐电路结果与动画</h2>'
    for seed in report['training_seeds']:
        for label in ('ppo','local_cost'):
            target=f'seed-{seed}/evaluation/{label}/test-cz-8/animation.html'
            if (output/target).exists():text+=f'<p><a href="{target}">Seed {seed} / {label}：8原子物理动画</a></p>'
    text+='<p><a href="report.json">完整结果JSON</a> · <a href="manifest.json">训练/验证/测试清单</a></p><table><tr>'
    text+=''.join(f'<th>{v}</th>' for v in ('训练Seed','未见电路','策略','结果','物理μs','精确最优μs','选中更新'))+'</tr>'+''.join(rows)+'</table></html>'
    (output/'index.html').write_text(text,encoding='utf-8')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',default='configs/rl/stage_b.json')
    parser.add_argument('--output',default='artifacts/rl-stage-b/attempt1')
    args=parser.parse_args()
    config=json.loads(Path(args.config).read_text(encoding='utf-8'))
    if config['schema']!='rl-stage-b-v1':raise ValueError('Unknown training config')
    run(config,args.output)


if __name__=='__main__':main()
