"""Post-training physical oracle, historical-regression and pairing audit."""
import argparse
import json
from pathlib import Path
import torch

from neutral_atom_env import NeutralAtomEnv
from neutral_atom_env.replay.serializer import canonical_json
from neutral_atom_env.visualization.recording import VisualRecorder
from neutral_atom_strategies.learning import DecisionEnv,EpisodeConfig
from neutral_atom_strategies.learning.network import NeuralPolicy
from .diagnose import oracle_choices
from .training_cases import manifest,initial
from .horizon import summarize
from .train import work,worker_init
from .circuit_replay import write_circuit_replay


def audit(directory):
    directory=Path(directory);report=json.loads((directory/'report.json').read_text(encoding='utf-8'))
    config=report['config'];torch.set_num_threads(1)
    for seed in config['training_seeds']:
        starts=[torch.load(directory/f'seed-{seed}-h{h}/imitation.pt',weights_only=True)['weights'] for h in config['fragment_lengths']]
        assert all(torch.equal(starts[0][k],other[k]) for other in starts[1:] for k in starts[0])
        for h in config['fragment_lengths']:
            updates=[r for r in report['training'] if r['seed']==seed and r['horizon']==h]
            assert len(updates)==config['updates']
            assert all(r['samples']==config['samples_per_update'] for r in updates)
    assert all(r['status']=='completed' and r['terminal_verified'] and r['effects_once'] and r['replay_equal'] for r in report['results'])
    original=[c for c in manifest() if c['name'] in ('train-words-2','test-greedy-trap')]
    regressions=[]
    for case in original:
        choices=[('oracle',None,None)]
        for seed in config['training_seeds']:
            for h in config['fragment_lengths']:
                choices.append((f'h{h}',seed,NeuralPolicy.load(directory/f'seed-{seed}-h{h}/selected.pt')))
        for label,seed,policy in choices:
            env=DecisionEnv(initial(case),EpisodeConfig(reward_scale_us=1))
            while env.status=='running':
                obs=env.observe()
                if policy:action=policy(obs)
                else:
                    costs=oracle_choices(obs);action=obs['candidates'][min(range(len(costs)),key=lambda i:costs[i])]['id']
                env.step(action)
            result=env.audit();assert result['replay_equal'] and result['effects_once'] and result['terminal_verified']
            regressions.append(dict(result,name=case['name'],seed=seed,policy=label))
            if case['name']=='test-greedy-trap' and seed in (None,config['training_seeds'][-1]):
                replay=NeutralAtomEnv.restore(initial(case));recorder=VisualRecorder(replay.state)
                for plan in env.plans:
                    replay.submit(plan);replay.run(on_event=lambda s,e:recorder.observe(s))
                assert replay.snapshot()==env.snapshot()['current']
                path=directory/'regression-animations'/label;path.mkdir(parents=True,exist_ok=True)
                write_circuit_replay(case,recorder.payload(),path/'animation.html',label=label)
    # Transport regressions are diagnostics, never used to select H or weights.
    worker_init();cz_results=[]
    for case in [c for c in manifest() if c['name'] in ('test-cz-8','test-cz-crossed')]:
        for seed in (None,*config['training_seeds']):
            weights=None
            if seed is not None:
                weights=torch.load(directory/f'seed-{seed}-h16/selected.pt',weights_only=True)['weights']
            r=work(dict(case=case,episode=config['episode'],hidden=config['hidden'],weights=weights,
                        policy='ppo' if seed is not None else 'local_cost',seed=seed or 0,mode='evaluate'))
            r['training_seed']=seed;cz_results.append(r)
    result={'matched_initial_weights':True,'matched_samples_per_update':True,
            'training_samples':sum(r['samples'] for r in report['training']),
            'all_test_replays_and_terminals_passed':True,'test_executions':len(report['results']),
            'historical_diagnostics':regressions,'cz_regressions':cz_results}
    (directory/'audit.json').write_text(canonical_json(result),encoding='utf-8')
    summarize(directory,report)
    print(json.dumps(result,indent=2))
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('directory');args=parser.parse_args();audit(args.directory)
