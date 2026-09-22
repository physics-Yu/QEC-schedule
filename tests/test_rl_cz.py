import json
from pathlib import Path
from neutral_atom_experiments.rl.cz_training import cz_manifest
from neutral_atom_experiments.rl.training_cases import initial
from neutral_atom_strategies.learning import DecisionEnv,EpisodeConfig
from neutral_atom_strategies.learning.policies import LocalCostPolicy
from neutral_atom_env import NeutralAtomEnv
from neutral_atom_env.visualization.recording import VisualRecorder
from neutral_atom_experiments.rl.circuit_replay import write_circuit_replay
from neutral_atom_experiments.rl.instances import make_snapshot


def test_cz_corpus_disjoint_reproducible_and_every_wire_entangles():
    config=json.loads(Path('configs/rl/cz.json').read_text())
    cases=cz_manifest(config['distribution'])
    assert cases==cz_manifest(config['distribution']) and len(cases)==18
    assert len({c['fingerprint'] for c in cases})==18
    for case in cases:
        n=case['atom_count'];gates=case['gates']
        assert sum(k=='CZ' for k,_ in gates)==n
        for offset in (0,n+n//2):
            layer=gates[offset:offset+n+n//2]
            assert [k for k,_ in layer[:n]]==['H']*n
            assert sorted(q for k,qs in layer[n:] for q in qs)==list(range(n))
    assert {c['atom_count'] for c in cases if c['split']=='test'}=={4,6,8}


def test_actual_cz_transport_and_full_circuit_replay(tmp_path):
    case=cz_manifest(json.loads(Path('configs/rl/cz.json').read_text())['distribution'])[0]
    source=initial(case);env=DecisionEnv(source,EpisodeConfig(planning_seconds=60))
    while env.status=='running':env.step(LocalCostPolicy()(env.observe()))
    audit=env.audit()
    assert audit['status']=='completed' and audit['effects_once'] and audit['replay_equal'] and audit['terminal_verified']
    physical=NeutralAtomEnv.restore(source);recorder=VisualRecorder(physical.state)
    for plan in env.plans:
        physical.submit(plan);physical.run(on_event=lambda s,e:recorder.observe(s))
    payload=recorder.payload();cz=[o for o in payload['operations'] if o['kind']=='entangling_pulse']
    assert sum(len(o['gate_ids']) for o in cz)==4
    assert max(len(o['gate_ids']) for o in cz)==2
    assert any(o['kind']=='aod_move' for o in payload['operations'])
    path=write_circuit_replay(case,payload,tmp_path/'animation.html')
    text=path.read_text(encoding='utf-8')
    assert all(f'id="g{i:04d}"' in text for i in range(len(case['gates'])))
    import re
    connectors={gate:re.search(rf'id="{gate}".*?<line x1="(\d+)"',text).group(1) for gate in ('g0004','g0005')}
    assert connectors['g0004']!=connectors['g0005']  # Two CZs, not an apparent 4-body gate.
    assert 'viewer.setTime' in text
    assert json.loads((tmp_path/'case.json').read_text())['gates']==json.loads(json.dumps(case['gates']))


def test_axis_impossible_large_groups_do_not_starve_legal_cz():
    # Four ready gates across two rows; the AOD is one row x four columns.
    source=make_snapshot([('CZ',[0,2]),('CZ',[1,3]),('CZ',[4,6]),('CZ',[5,7])],8)
    env=DecisionEnv(source,EpisodeConfig(candidate_budget=24,planning_seconds=60))
    obs=env.observe();log=obs['search']
    assert log['capacity_pruned']>=24
    assert log['generated']==log['capacity_pruned']+log['attempted']+log['not_attempted']
    assert obs['candidates'] and any(c['kind']=='CZ' for c in obs['candidates'])
    while env.status=='running':env.step(LocalCostPolicy()(env.observe()))
    audit=env.audit()
    assert audit['status']=='completed' and audit['replay_equal'] and audit['effects_once'] and audit['terminal_verified']
