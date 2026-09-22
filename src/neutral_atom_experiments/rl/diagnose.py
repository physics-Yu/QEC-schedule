"""Post-training exact 1Q counterexamples; never used to update/select models."""
import argparse
from functools import lru_cache
import json
from pathlib import Path

import torch
from neutral_atom_strategies.learning import EpisodeConfig
from neutral_atom_strategies.learning.cache import ExactCandidateCache,cached_environment
from neutral_atom_strategies.learning.network import GraphActorCritic
from neutral_atom_strategies.learning.policies import LocalCostPolicy
from neutral_atom_env.replay.serializer import canonical_json
from .training_cases import manifest,initial


@lru_cache(None)
def remaining_cost(words):
    kinds={w[0] for w in words if w}
    return 0 if not kinds else 1+min(remaining_cost(tuple(w[1:] if w.startswith(k) else w for w in words)) for k in kinds)


def oracle_choices(obs):
    if any(g['type']=='CZ' for g in obs['gates']):raise ValueError('Exact oracle is limited to independent 1Q wires')
    qubits=sorted(a['id'] for a in obs['atoms'])
    # Fixture gate IDs carry input order; this is an explicit small-instance oracle.
    gates=sorted(obs['gates'],key=lambda g:g['id'])
    scores=[]
    for action in obs['candidates']:
        completed=set(action['gate_ids'])
        words=tuple(''.join(g['type'] for g in gates if g['status']!='completed'
                    and g['id'] not in completed and q in g['qubits']) for q in qubits)
        scores.append(action['duration_us']+remaining_cost(words))
    return scores


def diagnose(directory):
    directory=Path(directory);config=json.loads((directory/'config.json').read_text(encoding='utf-8'))
    cases=[c for c in manifest() if c['name'] in ('train-words-2','test-greedy-trap')]
    cache=ExactCandidateCache();rows=[];torch.set_num_threads(1)
    for case in cases:
        policies=[('oracle',None,None),('local_cost',None,None)]
        for seed in config['training_seeds']:
            for stage in ('imitation','last','selected'):
                data=torch.load(directory/f'seed-{seed}/{stage}.pt',weights_only=True)
                model=GraphActorCritic(data['hidden']);model.load_state_dict(data['weights'])
                policies.append((stage,seed,model))
        for label,seed,model in policies:
            env=cached_environment(initial(case),EpisodeConfig(**dict(config['episode'],reward_scale_us=case['scale'])),cache)
            decisions=[]
            while env.status=='running':
                obs=env.observe();scores=oracle_choices(obs)
                if label=='oracle':index=min(range(len(scores)),key=lambda i:scores[i])
                elif model is not None:index=model.choose(obs,True)[0]
                else:
                    target=LocalCostPolicy()(obs)
                    index=next(i for i,c in enumerate(obs['candidates']) if c['id']==target)
                choice=obs['candidates'][index]
                decisions.append({'gate_type':choice['kind'],'gate_count':len(choice['gate_ids']),
                    'optimal_remaining_if_chosen_us':scores[index],'best_remaining_us':min(scores),
                    'avoidable_us_at_this_decision':scores[index]-min(scores)})
                env.step(choice['id'])
            audit=env.audit();assert audit['replay_equal'] and audit['effects_once']
            rows.append(dict(audit,name=case['name'],policy=label,training_seed=seed,decisions=decisions))
    result={'scope':'post-training diagnostic, no training/selection feedback; exact independent-1Q-wire oracle',
            'cases':rows}
    (directory/'diagnosis.json').write_text(canonical_json(result),encoding='utf-8')
    print(json.dumps([{k:r[k] for k in ('name','policy','training_seed','elapsed_us')} for r in rows],indent=2))
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('directory');args=parser.parse_args();diagnose(args.directory)
