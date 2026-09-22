"""Matched-sample short/long rollout ablation on fresh 1Q counterexamples."""
import argparse
from concurrent.futures import ProcessPoolExecutor
from copy import deepcopy
from functools import lru_cache
from hashlib import sha256
from html import escape
import json
from pathlib import Path
import random
from statistics import mean
from time import perf_counter

import torch
from neutral_atom_env.replay.serializer import canonical_json
from neutral_atom_strategies.learning.network import GraphActorCritic,ppo_update
from .training_cases import manifest as old_manifest,wire_case,wire_optimum
from .train import work,worker_init,serial_weights,save_model


def words_of(case):
    result=['']*case['atom_count']
    for kind,qs in case['gates']:
        if kind=='CZ':return None
        result[qs[0]]+=kind
    return tuple(result)


def canonical_words(words):
    swapped=tuple(w.translate(str.maketrans('HX','XH')) for w in words)
    return min(tuple(sorted(words)),tuple(sorted(swapped)))


def local_cost_steps(words):
    steps=0
    while any(words):
        kind=min({w[0] for w in words if w},key=lambda k:(-sum(w.startswith(k) for w in words),'HXYZT'.index(k)))
        words=tuple(w[1:] if w.startswith(kind) else w for w in words);steps+=1
    return steps


def fresh_manifest():
    seen={canonical_words(w) for c in old_manifest() if (w:=words_of(c)) is not None}
    cases=[]
    for split,seed,count,maxlen in [('train',601,24,4),('validation',607,8,4),('test',613,16,5)]:
        rng=random.Random(seed)
        for i in range(count):
            want_trap=i%2==0
            for _ in range(10000):
                words=tuple(''.join(rng.choice('HX') for _ in range(rng.randint(1,maxlen))) for q in range(4))
                key=canonical_words(words)
                if key in seen:continue
                case=wire_case(f'{split}-horizon-{i}',words,split)
                optimum=wire_optimum(case);baseline=local_cost_steps(words)
                if (baseline>optimum)!=want_trap:continue
                seen.add(key)
                case.update(family='counterexample' if want_trap else 'control',
                            optimum_us=optimum,baseline_us=baseline,
                            fingerprint=sha256(canonical_json([4,case['gates']]).encode()).hexdigest())
                cases.append(case);break
            else:raise RuntimeError('Could not construct fresh circuit distribution')
    return cases


def run(config,output):
    output=Path(output)
    if output.exists():raise ValueError('Preserve prior experiment; choose a fresh output directory')
    output.mkdir(parents=True)
    cases=fresh_manifest()
    for name,value in [('config.json',config),('manifest.json',cases)]:
        (output/name).write_text(canonical_json(value),encoding='utf-8')
    train=[c for c in cases if c['split']=='train'];validation=[c for c in cases if c['split']=='validation'];test=[c for c in cases if c['split']=='test']
    base={'episode':config['episode'],'hidden':config['hidden']}
    def status(**values):(output/'status.json').write_text(canonical_json(values),encoding='utf-8')
    torch.set_num_threads(1);started=perf_counter();all_results=[];training=[]
    pool=ProcessPoolExecutor(config['workers'],initializer=worker_init)
    try:
        status(status='running',phase='teacher')
        teacher=list(pool.map(work,[dict(base,mode='teacher',policy='local_cost',case=c,seed=0) for c in train]))
        assert all(t['status']=='completed' for t in teacher)
        demonstrations=[s for t in teacher for s in t['samples']]
        print(f'Teacher {len(train)} circuits / {len(demonstrations)} samples',flush=True)
        (output/'teacher-summary.json').write_text(canonical_json([
            {'name':t['name'],'elapsed_us':t['elapsed_us']} for t in teacher]),encoding='utf-8')
        for seed in config['training_seeds']:
            torch.manual_seed(seed);rng=random.Random(seed);model=GraphActorCritic(config['hidden'])
            opt=torch.optim.Adam(model.parameters(),lr=.003)
            for _ in range(config['imitation_epochs']):
                indices=list(range(len(demonstrations)));rng.shuffle(indices)
                for offset in range(0,len(indices),32):
                    loss=torch.stack([-torch.log_softmax(model(demonstrations[i]['observation'])[0],0)[demonstrations[i]['index']]
                                      for i in indices[offset:offset+32]]).mean()
                    opt.zero_grad();loss.backward();opt.step()
            warm=serial_weights(model)
            def evaluate(weights,subset,label,directory=None):
                return list(pool.map(work,[dict(base,mode='evaluate',case=c,policy=label,weights=weights,seed=seed,
                    directory=str(directory/c['name']) if directory else None) for c in subset]))
            warm_validation=evaluate(warm,validation,'imitation')
            warm_score=mean(r['elapsed_us'] for r in warm_validation)
            for horizon in config['fragment_lengths']:
                directory=output/f'seed-{seed}-h{horizon}';directory.mkdir()
                model.load_state_dict(warm);optimizer=torch.optim.Adam(model.parameters(),lr=config['learning_rate'])
                save_model(directory/'imitation.pt',model,{'stage':'imitation','seed':seed})
                best=deepcopy(warm);best_score=warm_score;best_update=0
                slots=[None]*config['slots'];slot_cases=[None]*config['slots'];episode=0;request=0;total_samples=0
                arm_started=perf_counter()
                for update in range(1,config['updates']+1):
                    tick=perf_counter();weights=serial_weights(model);samples=[];cuts=0;failed=[]
                    while len(samples)<config['samples_per_update']:
                        left=config['samples_per_update']-len(samples);jobs=[];active=[]
                        for slot in range(min(config['slots'],left)):
                            if slots[slot] is None:
                                slot_cases[slot]=train[episode%len(train)];episode+=1
                            length=min(horizon,left);left-=length
                            jobs.append(dict(base,mode='collect',case=slot_cases[slot],checkpoint=slots[slot],
                                policy='ppo',weights=weights,seed=seed*1000000+request,
                                fragment_length=length));active.append(slot);request+=1
                            if left==0:break
                        fragments=list(pool.map(work,jobs))
                        for slot,fragment in zip(active,fragments):
                            slots[slot]=fragment['checkpoint'] if fragment['fragment_cut'] else None
                            samples.extend(fragment['samples']);cuts+=fragment['fragment_cut']
                            if fragment['failure']:failed.append(fragment['failure'])
                    assert len(samples)==config['samples_per_update']
                    loss=ppo_update(model,optimizer,samples,epochs=config['ppo_epochs'])
                    total_samples+=len(samples)
                    row={'seed':seed,'horizon':horizon,'update':update,'samples':len(samples),'loss':loss,
                         'fragment_cuts':cuts,'failures':failed,'seconds':perf_counter()-tick}
                    if update%config['validation_interval']==0 or update==config['updates']:
                        val=evaluate(serial_weights(model),validation,'ppo')
                        current=mean(r['elapsed_us'] if r['status']=='completed' else 1e9 for r in val)
                        row['validation_score']=current
                        if current<best_score-1e-8:best_score=current;best=serial_weights(model);best_update=update
                    training.append(row)
                    with (directory/'training.jsonl').open('a',encoding='utf-8') as f:f.write(canonical_json(row)+'\n')
                    status(status='running',phase='training',seed=seed,horizon=horizon,update=update)
                    print(f'Seed {seed} H{horizon} update {update}/{config["updates"]}: loss {loss:.3f}, {row["seconds"]:.1f}s',flush=True)
                save_model(directory/'last.pt',model,{'stage':'ppo_last','seed':seed,'horizon':horizon})
                last=serial_weights(model);model.load_state_dict(best)
                save_model(directory/'selected.pt',model,{'stage':'ppo' if best_update else 'imitation','seed':seed,'selected_update':best_update,'horizon':horizon})
                arm_results=[]
                for label,weights in [('imitation',warm),('ppo_last',last),('ppo',best),('local_cost',None)]:
                    status(status='running',phase='test',seed=seed,horizon=horizon,policy=label)
                    results=evaluate(weights,test,label,directory/'test'/label)
                    for result in results:result.update(horizon=horizon,training_seed=seed,selected_update=best_update if label=='ppo' else None)
                    arm_results.extend(results)
                (directory/'test.json').write_text(canonical_json(arm_results),encoding='utf-8')
                all_results.extend(arm_results)
                print(f'Seed {seed} H{horizon} complete: {total_samples} training decisions, {perf_counter()-arm_started:.1f}s',flush=True)
        report={'schema':'rl-horizon-v1','results':all_results,'training':training,'seconds':perf_counter()-started,
                'config':config,'scope':'fresh pure-1Q curriculum, same initial weights and samples/updates per arm; no CZ improvement claim'}
        (output/'report.json').write_text(canonical_json(report),encoding='utf-8')
        summarize(output,report)
        status(status='completed',seconds=report['seconds'],training_samples=sum(r['samples'] for r in training))
        return report
    except Exception as error:
        status(status='failed',error={'type':type(error).__name__,'message':str(error)});raise
    finally:pool.shutdown()


def summarize(output,report):
    output=Path(output);rows=report['results'];summary=[]
    for horizon in report['config']['fragment_lengths']:
        for policy in ('imitation','ppo_last','ppo','local_cost'):
            group=[r for r in rows if r['horizon']==horizon and r['policy']==policy]
            baseline={(r['training_seed'],r['name']):r['elapsed_us'] for r in rows if r['horizon']==horizon and r['policy']=='local_cost'}
            summary.append({'horizon':horizon,'policy':policy,'runs':len(group),
                'successes':sum(r['status']=='completed' for r in group),
                'mean_us':mean(r['elapsed_us'] for r in group),
                'mean_ratio':mean(r['elapsed_us']/baseline[r['training_seed'],r['name']] for r in group),
                'optima_reached':sum(abs(r['elapsed_us']-r['optimum_us'])<1e-8 for r in group),
                'per_seed':{str(seed):mean(r['elapsed_us'] for r in group if r['training_seed']==seed) for seed in report['config']['training_seeds']}})
    (output/'summary.json').write_text(canonical_json(summary),encoding='utf-8')
    html='''<!doctype html><html lang="zh"><meta charset="utf-8"><title>RL片段长度对照</title>
<style>body{font:16px system-ui;color:#253149;background:#f5f7fb;max-width:1100px;margin:40px auto;padding:20px}p{line-height:1.8}td,th{padding:12px;border-bottom:1px solid #ddd;text-align:left}table{width:100%;border-collapse:collapse;background:white}</style>
<h1>新的反例课程：短片段 / 长片段</h1><p>独立纯单比特电路实验。两个长度使用相同数据、初始网络、更新次数及每次采样数，验证集选模型；所有测试都经真实物理执行与独立重放。长度是上限，episode完成和采样批次尾部会产生更短片段。</p>
<p>本实验没有改变CZ运输、greedy或工作台。测试集针对反例富集，不能将收益比例推广到任意电路。imitation是模仿初始模型；ppo_last是预先约定报告的最后模型；ppo是仅按验证集选中的模型，可能仍是update0。不能按测试结果重新挑选模型。</p><table><tr><th>片段长度</th><th>策略</th><th>完成</th><th>平均μs</th><th>耗时比</th><th>达到最优</th><th>各训练seed平均μs</th></tr>'''
    for s in summary:
        seeds=' / '.join(f'{seed}: {value:.3f}' for seed,value in s['per_seed'].items())
        html+=f'<tr><td>{s["horizon"]}</td><td>{s["policy"]}</td><td>{s["successes"]}/{s["runs"]}</td><td>{s["mean_us"]:.3f}</td><td>{s["mean_ratio"]:.4f}</td><td>{s["optima_reached"]}/{s["runs"]}</td><td>{seeds}</td></tr>'
    html+='</table><p><a href="summary.json">汇总JSON</a> · <a href="report.json">完整报告</a> · <a href="manifest.json">冻结的数据清单</a></p>'
    if (output/'audit.json').exists():
        html+='<p><a href="audit.json">同初始权重、同采样预算及历史反例核验</a></p><p>历史反例回放（仅诊断，不用于更新/选模）：'
        for label in ('oracle','h4','h16'):
            html+=f'<a href="regression-animations/{label}/animation.html">{label}</a> '
        html+='</p>'
    html+='</html>'
    (output/'index.html').write_text(html,encoding='utf-8')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--config',default='configs/rl/horizon.json');parser.add_argument('--output',default='artifacts/rl-horizon/attempt1')
    args=parser.parse_args();run(json.loads(Path(args.config).read_text(encoding='utf-8')),args.output)
