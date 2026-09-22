import ast
import json
from pathlib import Path

import pytest

from neutral_atom_experiments.rl.instances import make_snapshot
from neutral_atom_strategies.learning import DecisionEnv,EpisodeConfig
from neutral_atom_strategies.learning.policies import LocalCostPolicy,RandomPolicy


def new(gates=None,**config):
    return DecisionEnv(make_snapshot(gates or [('H',[q]) for q in range(4)]),EpisodeConfig(**config))


def finish(env,policy=None,length=2):
    policy=policy or LocalCostPolicy()
    while env.status=='running':env.collect_fragment(policy,length)
    return env.audit()


def test_same_kind_parallel_real_executor_and_reward():
    env=new()
    assert len(env.observe()['candidates'])==5
    audit=finish(env)
    assert audit['elapsed_us']==1
    assert audit['total_reward']==-.001
    assert audit['replay_equal'] and audit['terminal_verified']
    serial=new()
    def one(obs):return next(c['id'] for c in obs['candidates'] if len(c['gate_ids'])==1)
    audit=finish(serial,one)
    assert audit['elapsed_us']==4 and audit['total_reward']==-.004


def test_fragment_is_not_terminal_and_resume_preserves_original_target():
    gates=[('H',[0]),('X',[0]),('Z',[0]),('H',[0])]
    env=new(gates)
    part=env.collect_fragment(LocalCostPolicy(),2)
    assert part['fragment_cut'] and part['bootstrap_required'] and not part['terminated']
    assert all(not t['terminated'] and not t['truncated'] for t in part['transitions'])
    snapshot=json.loads(json.dumps(env.snapshot()))
    resumed=DecisionEnv.restore(snapshot)
    assert resumed.observe()==env.observe()
    a=finish(env);b=finish(resumed)
    assert env.snapshot()==resumed.snapshot()
    assert a['replay_equal'] and b['replay_equal'] and a['elapsed_us']==4
    assert a['total_reward']==-.004


def test_invalid_and_stale_actions_fail_without_physical_mutation():
    env=new([('H',[0]),('X',[0])])
    first=env.observe()['candidates'][0]['id'];env.step(first)
    before=env.snapshot()['current']
    result=env.step(first)
    assert result['failure']['code']=='INVALID_ACTION'
    assert env.snapshot()['current']==before
    assert result['terminated'] and result['total_reward']<-100
    with pytest.raises(RuntimeError):env.step(first)


@pytest.mark.parametrize('settings,code',[
    ({'time_limit_us':.5},'PHYSICAL_TIME_LIMIT'),
    ({'max_decisions':1},'DECISION_BUDGET')])
def test_failure_cannot_outscore_success(settings,code):
    env=new([('H',[0]),('X',[0])],**settings)
    result=env.step(env.observe()['candidates'][0]['id'])
    assert env.status=='failed' and result['failure']['code']==code
    assert env.total_reward < -env.config.time_limit_us/env.config.reward_scale_us
    assert sum(t['reward'] for t in env.history)==env.total_reward


def test_observation_is_a_detached_whitelist():
    env=new()
    obs=env.observe()
    assert not {'rng_state','quantum_state','trace','plans','readout_flip'}&set(obs)
    assert 'readout_flip' not in json.dumps(obs)
    obs['atoms'][0]['position']['x_um']=999
    obs['gates'][0]['status']='completed'
    obs['action_mask'].clear()
    assert env.observe()['atoms'][0]['position']['x_um']==0
    assert env.observe()['gates'][0]['status']=='ready'
    assert len(env.observe()['action_mask'])==5


def test_budget_is_reported_not_called_physical_impossibility():
    env=new(candidate_budget=1)
    obs=env.observe()
    assert obs['search']['generated']==5 and obs['search']['attempted']==1
    assert obs['search']['not_attempted']==4 and obs['action_mask']==[True]
    assert finish(env)['terminal_verified']


def test_no_candidates_is_explicit_failure(monkeypatch):
    env=new()
    monkeypatch.setattr(env._provider,'build',lambda *a:([],{'budget_exhausted':True}))
    assert env.observe()['action_mask']==[]
    assert env.step(None)['failure']['code']=='CANDIDATES_EXHAUSTED'


def test_random_seed_reproducibility_and_environment_isolation():
    a=new();b=new()
    initial=b.snapshot()
    a.collect_fragment(RandomPolicy(7),1)
    assert b.snapshot()==initial
    b.collect_fragment(RandomPolicy(7),1)
    assert a.snapshot()==b.snapshot()


def test_policy_rng_checkpoint_and_reset():
    env=new([('H',[q]) for q in range(4)]+[('X',[q]) for q in range(4)])
    policy=RandomPolicy(9)
    env.collect_fragment(policy,1)
    restored=DecisionEnv.restore(json.loads(json.dumps(env.snapshot())))
    other=RandomPolicy(0)
    other.load_state_dict(json.loads(json.dumps(policy.state_dict())))
    finish(env,policy);finish(restored,other)
    assert env.snapshot()==restored.snapshot()
    observation=env.reset()
    assert observation['time_us']==0 and observation['decision_count']==0
    assert env.total_reward==0 and env.status=='running'


def test_different_one_qubit_kinds_are_separate_actions():
    env=new([('H',[0]),('X',[1]),('H',[2])])
    obs=env.observe()
    assert {c['kind'] for c in obs['candidates']}=={'H','X'}
    assert all(c['gate_ids']!=['g0000','g0001','g0002'] for c in obs['candidates'])
    assert finish(env)['elapsed_us']==2


@pytest.mark.parametrize('key,value',[('ready_limit',9),('max_decisions',0),('reward_scale_us',0),('planning_seconds',float('nan'))])
def test_config_validation(key,value):
    with pytest.raises(ValueError):EpisodeConfig(**{key:value})


def test_cz_batch_and_cleanup_are_real_and_fragment_does_not_restore_axes():
    env=new([('CZ',[0,2]),('CZ',[1,3])])
    fragment=env.collect_fragment(LocalCostPolicy(),1)
    assert fragment['fragment_cut']
    assert all(g['status']=='completed' for g in fragment['final_observation']['gates'])
    assert fragment['final_observation']['candidates'][0]['kind']=='CLEANUP'
    assert len(next(c for c in fragment['transitions'][0]['observation']['candidates']
                    if c['id']==fragment['transitions'][0]['action_id'])['gate_ids'])==2
    before=env.snapshot()['current']
    restored=DecisionEnv.restore(env.snapshot())
    assert finish(restored)['replay_equal']
    assert env.snapshot()['current']==before
    audit=finish(env)
    assert audit['terminal_verified'] and audit['replay_equal']
    assert audit['total_reward']==pytest.approx(-audit['elapsed_us']/1000)


def test_learning_does_not_import_production_schedulers_and_is_opt_in():
    root=Path(__file__).resolve().parents[1]
    for folder in ('src/neutral_atom_strategies/learning','src/neutral_atom_experiments/rl'):
        for path in (root/folder).glob('*.py'):
            for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
                if isinstance(node,ast.ImportFrom):
                    assert not (node.module or '').startswith(('neutral_atom_strategies.scheduling','neutral_atom_app'))
    for path in (root/'src').rglob('*.py'):
        if '/learning/' in path.as_posix() or '/rl/' in path.as_posix():continue
        assert 'neutral_atom_strategies.learning' not in path.read_text(encoding='utf-8')
