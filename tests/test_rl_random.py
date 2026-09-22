import json
from pathlib import Path

from neutral_atom_experiments.rl.random_training import random_manifest
from neutral_atom_experiments.rl.training_cases import wire_case,wire_optimum,initial
from neutral_atom_strategies.learning import DecisionEnv,EpisodeConfig
from neutral_atom_strategies.learning.policies import LocalCostPolicy


def test_random_manifest_reproducible_disjoint_and_not_performance_filtered(monkeypatch):
    import neutral_atom_experiments.rl.training_cases as cases_module
    def forbidden(*args,**kwargs):raise AssertionError('Generator must not query optimum')
    monkeypatch.setattr(cases_module,'wire_optimum',forbidden)
    config=json.loads(Path('configs/rl/random.json').read_text())['distribution']
    cases=random_manifest(config)
    assert cases==random_manifest(config)
    assert len(cases)==104 and len({c['fingerprint'] for c in cases})==104
    seen=set()
    for c in cases:
        words=['']*c['atom_count']
        for kind,qs in c['gates']:words[qs[0]]+=kind
        assert all(2<=len(w)<=5 and all(a!=b for a,b in zip(w,w[1:])) for w in words)
        key=tuple(sorted(words));assert key not in seen;seen.add(key)
    assert {c['atom_count'] for c in cases if c['split']=='train'}=={4}
    assert sum(c['atom_count']==6 for c in cases if c['split']=='test')==16


def test_extra_pulse_is_ordering_not_extra_gate_or_transport():
    case=wire_case('diagnostic',('HX','HHXX','HX','XHHH'),'test')
    sequences={}
    for label,sequence in [('greedy',None),('oracle','XHHHXX')]:
        env=DecisionEnv(initial(case),EpisodeConfig(reward_scale_us=1));chosen=[];effects=[]
        while env.status=='running':
            obs=env.observe()
            if sequence:
                candidates=[c for c in obs['candidates'] if c['kind']==sequence[len(chosen)]]
                action=max(candidates,key=lambda c:len(c['gate_ids']))
            else:action=next(c for c in obs['candidates'] if c['id']==LocalCostPolicy()(obs))
            assert action['duration_us']==1 and action['distance_um']==0
            chosen.append(action['kind']);effects.extend(action['gate_ids']);env.step(action['id'])
        audit=env.audit()
        assert audit['replay_equal'] and audit['effects_once'] and audit['terminal_verified']
        assert len(effects)==len(set(effects))==12
        sequences[label]=''.join(chosen)
    assert sequences=={'greedy':'HXHHHXX','oracle':'XHHHXX'}
    assert wire_optimum(case)==6
