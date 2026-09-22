from copy import deepcopy
import json
from pathlib import Path

import pytest
torch=pytest.importorskip('torch')
from neutral_atom_experiments.rl.instances import make_snapshot
from neutral_atom_experiments.rl.training_cases import manifest,wire_optimum
from neutral_atom_strategies.learning import DecisionEnv,EpisodeConfig
from neutral_atom_strategies.learning.cache import ExactCandidateCache,cached_environment
from neutral_atom_strategies.learning.network import GraphActorCritic,gae,ppo_update
from neutral_atom_strategies.learning.policies import LocalCostPolicy

torch.set_num_threads(1)


def observation():
    return DecisionEnv(make_snapshot([('H',[0]),('H',[1]),('X',[2]),('X',[0])]),EpisodeConfig(reward_scale_us=1.)).observe()


def test_gae_bootstrap_and_terminal_differ():
    advantages,returns=gae([-1.,-2.],[4.,5.],[False,False],7.,lam=1.)
    assert returns==[4.,5.]
    assert advantages==[0.,0.]
    _,terminal=gae([-1.,-2.],[4.,5.],[False,True],7.,lam=1.)
    assert terminal==[-3.,-2.]
    with pytest.raises(ValueError):gae([1.],[],[],0.)


def test_graph_policy_permutation_and_mask():
    torch.manual_seed(3);model=GraphActorCritic()
    obs=observation();logits,value=model(obs)
    changed=deepcopy(obs);changed['gates'].reverse();changed['atoms'].reverse()
    changed['candidates'].reverse();changed['action_mask'].reverse()
    other,v=model(changed)
    assert torch.allclose(logits.flip(0),other,atol=1e-6)
    assert torch.allclose(value,v,atol=1e-6)
    masked=deepcopy(obs);masked['action_mask'][0]=False
    logits,_=model(masked)
    assert torch.isneginf(logits[0])
    for _ in range(10):assert model.choose(masked)[0]!=0


def test_ppo_updates_weights_and_roundtrips(tmp_path):
    torch.manual_seed(5);model=GraphActorCritic();obs=observation()
    samples=[]
    for i in range(len(obs['candidates'])):
        with torch.no_grad():
            logits,value=model(obs)
            logp=torch.log_softmax(logits,0)[i]
        samples.append(dict(observation=deepcopy(obs),index=i,logp=float(logp),advantage=float(i-1),
                            **{'return':-float(i)}))
    before={k:v.clone() for k,v in model.state_dict().items()}
    loss=ppo_update(model,torch.optim.Adam(model.parameters(),lr=.001),samples,epochs=2)
    assert isinstance(loss,float)
    assert any(not torch.equal(before[k],v) for k,v in model.state_dict().items())
    path=tmp_path/'weights.pt';torch.save(model.state_dict(),path)
    restored=GraphActorCritic();restored.load_state_dict(torch.load(path,weights_only=True))
    assert torch.equal(model(obs)[0],restored(obs)[0])


def test_exact_cache_uses_full_state_and_preserves_execution():
    initial=make_snapshot([('H',[0]),('H',[1]),('X',[0])]);cache=ExactCandidateCache()
    a=cached_environment(initial,EpisodeConfig(),cache)
    b=cached_environment(initial,EpisodeConfig(),cache)
    ao=a.observe();bo=b.observe()
    assert not ao['search']['cache_hit'] and bo['search']['cache_hit']
    assert ao['candidates']==bo['candidates']
    first=LocalCostPolicy()(ao)
    a.step(first);b.step(first)
    assert a.snapshot()==b.snapshot()
    assert a.audit()['replay_equal'] and b.audit()['replay_equal']
    a.observe()
    assert cache.misses==2
    c=cached_environment(initial,EpisodeConfig(candidate_budget=1),cache)
    c.observe();assert cache.misses==3


def test_split_manifest_and_greedy_trap_exact_oracle():
    cases=manifest();assert len({c['fingerprint'] for c in cases})==len(cases)
    trap=next(c for c in cases if c['name']=='test-greedy-trap')
    assert trap['split']=='test' and wire_optimum(trap)==6
    env=DecisionEnv(make_snapshot(trap['gates']),EpisodeConfig(reward_scale_us=1))
    while env.status=='running':env.collect_fragment(LocalCostPolicy(),4)
    assert env.audit()['elapsed_us']==7


def test_tensor_features_do_not_read_private_simulator_fields():
    obs=observation();model=GraphActorCritic()
    a=model(obs)[0]
    obs.update(quantum_state='hidden',rng_state='hidden',trace='hidden',readout_flip=True)
    assert torch.equal(a,model(obs)[0])


def test_validation_selection_matches_training_normalization():
    from neutral_atom_experiments.rl.train import score
    a=[{'return':-4.,'elapsed_us':4.},{'return':-1.,'elapsed_us':1000.}]
    b=[{'return':-6.,'elapsed_us':6.},{'return':-.9,'elapsed_us':900.}]
    assert score(a)<score(b)  # Saving 100us must not override per-case objective.


def test_saved_policy_is_callable_by_isolated_adapter(tmp_path):
    from neutral_atom_strategies.learning.network import NeuralPolicy
    model=GraphActorCritic();path=tmp_path/'policy.pt'
    torch.save({'schema':'rl-graph-ppo-v1','hidden':32,'weights':model.state_dict()},path)
    policy=NeuralPolicy.load(path)
    env=DecisionEnv(make_snapshot([('H',[0]),('H',[1])]))
    while env.status=='running':env.collect_fragment(policy,2)
    assert env.audit()['terminal_verified'] and env.audit()['replay_equal']
