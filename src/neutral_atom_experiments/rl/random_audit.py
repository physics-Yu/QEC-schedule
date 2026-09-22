"""Independent replay checks and physical witnesses for the random curriculum."""
import argparse
import json
from pathlib import Path

from neutral_atom_env import NeutralAtomEnv
from neutral_atom_env.replay.serializer import canonical_json
from neutral_atom_env.visualization.recording import VisualRecorder
from neutral_atom_strategies.learning import DecisionEnv,EpisodeConfig
from neutral_atom_strategies.learning.network import NeuralPolicy
from neutral_atom_strategies.learning.policies import LocalCostPolicy
from .diagnose import oracle_choices,remaining_cost
from .random_training import random_manifest,render_report
from .training_cases import initial,wire_optimum,wire_case
from .circuit_replay import write_circuit_replay


def legacy_pulse_audit(directory):
    case=wire_case('test-greedy-trap',('HX','HHXX','HX','XHHH'),'diagnostic')
    rows=[]
    for label in ('local_cost','oracle'):
        env=DecisionEnv(initial(case),EpisodeConfig(reward_scale_us=1));actions=[]
        while env.status=='running':
            obs=env.observe()
            if label=='oracle':
                scores=oracle_choices(obs)
                action=obs['candidates'][min(range(len(scores)),key=scores.__getitem__)]
            else:action=next(c for c in obs['candidates'] if c['id']==LocalCostPolicy()(obs))
            assert action['distance_um']==0 and action['duration_us']==1
            actions.append({k:action[k] for k in ('kind','gate_ids','duration_us','distance_um')})
            env.step(action['id'])
        result=env.audit()
        assert result['replay_equal'] and result['effects_once'] and result['terminal_verified']
        assert result['elapsed_us']==(7 if label=='local_cost' else 6)
        rows.append({'policy':label,'actions':actions,'audit':result})
    (directory.parent/'six-seven-audit.json').write_text(canonical_json({'case':case,'runs':rows}),encoding='utf-8')


def audit(directory):
    import torch
    torch.set_num_threads(1)
    directory=Path(directory)
    legacy_pulse_audit(directory)
    report=json.loads((directory/'report.json').read_text(encoding='utf-8'))
    config=json.loads((directory/'config.json').read_text(encoding='utf-8'))
    cases=json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
    assert canonical_json(random_manifest(config['distribution']))==canonical_json(cases)
    results=report['test_results']
    for row in results:
        assert row['status']=='completed' and row['replay_equal'] and row['effects_once'] and row['terminal_verified'],row
        assert row['elapsed_us']>=row['optimum_us']
    for name in {r['name'] for r in results}:
        assert len({r['initial_sha256'] for r in results if r['name']==name})==1
    config_episode=EpisodeConfig(**dict(config['episode'],reward_scale_us=1))
    oracles=[]
    for case in cases:
        if case['split']!='test':continue
        env=DecisionEnv(initial(case),config_episode)
        while env.status=='running':
            obs=env.observe();scores=oracle_choices(obs)
            env.step(obs['candidates'][min(range(len(scores)),key=scores.__getitem__)]['id'])
        row=dict(env.audit(),name=case['name'])
        assert row['elapsed_us']==wire_optimum(case) and row['replay_equal'] and row['effects_once'] and row['terminal_verified']
        oracles.append(row)
        remaining_cost.cache_clear()
    # Diagnose already-frozen test decisions; never feed this oracle into training.
    diagnostics=[]
    for row in results:
        if row['policy']!='ppo':continue
        path=directory/f'seed-{row["training_seed"]}/evaluation/ppo'/row['name']/'decisions.json'
        decisions=json.loads(path.read_text(encoding='utf-8'))
        avoidable=0;partial=0;wrong_kind=0
        for step in decisions:
            obs=step['observation'];scores=oracle_choices(obs)
            index=next(i for i,c in enumerate(obs['candidates']) if c['id']==step['action_id'])
            action=obs['candidates'][index];gap=scores[index]-min(scores)
            avoidable+=gap
            partial+=len(action['gate_ids'])<max(len(c['gate_ids']) for c in obs['candidates'] if c['kind']==action['kind'])
            same_kind_best=min(s for c,s in zip(obs['candidates'],scores) if c['kind']==action['kind'])
            wrong_kind+=same_kind_best>min(scores)+1e-8
        assert abs(avoidable-(row['elapsed_us']-row['optimum_us']))<1e-8
        diagnostics.append({'name':row['name'],'seed':row['training_seed'],
            'avoidable_us':avoidable,'partial_same_kind_batches':partial,'suboptimal_gate_kind_decisions':wrong_kind})
        remaining_cost.cache_clear()
    # Predetermined first six-atom test and first seed, not chosen for a good result.
    case=next(c for c in cases if c['split']=='test' and c['atom_count']==6)
    seed=config['training_seeds'][0];animations=[]
    policies={'ppo':NeuralPolicy.load(directory/f'seed-{seed}/selected.pt'),'local_cost':LocalCostPolicy()}
    for label,policy in policies.items():
        source=initial(case);env=DecisionEnv(source,config_episode)
        while env.status=='running':env.step(policy(env.observe()))
        row=dict(env.audit(),policy=label,name=case['name'],training_seed=seed)
        assert row['replay_equal'] and row['effects_once'] and row['terminal_verified']
        reference=next(r for r in results if r['name']==case['name'] and r['policy']==label and r['training_seed']==seed)
        assert row['elapsed_us']==reference['elapsed_us']
        replay=NeutralAtomEnv.restore(source);recorder=VisualRecorder(replay.state)
        for plan in env.plans:
            replay.submit(plan);replay.run(on_event=lambda s,e:recorder.observe(s))
        assert replay.snapshot()==env.snapshot()['current']
        target=directory/'animations'/label;target.mkdir(parents=True,exist_ok=True)
        write_circuit_replay(case,recorder.payload(),target/'animation.html',label=label)
        (target/'case.json').write_text(canonical_json(case),encoding='utf-8')
        animations.append(row)
    acceptance={'schema':'rl-random-acceptance-v1','test_executions':len(results),
        'all_physical_replay_effects_terminal_passed':True,'identical_inputs_across_policies':True,
        'oracle_physical_witnesses':oracles,'weight_reload_animations':animations,
        'selected_policy_decision_diagnostics':diagnostics,
        'browser_interaction_verified':False,
        'scope':'Fixed input pure-1Q scheduling; no algebraic optimization, transport learning, or quantum-state fidelity claim'}
    (directory/'acceptance.json').write_text(canonical_json(acceptance),encoding='utf-8')
    render_report(directory,report)
    print(canonical_json({'test_executions':len(results),'oracle_witnesses':len(oracles),'animations':animations}))
    return acceptance


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('directory');args=parser.parse_args();audit(args.directory)
