"""Audit saved CZ executions and publish full-circuit synchronized replays."""
import argparse
from hashlib import sha256
import json
from pathlib import Path

from neutral_atom_env import NeutralAtomEnv
from neutral_atom_env.replay.operation_codec import plan_from_dict
from neutral_atom_env.replay.serializer import canonical_json
from neutral_atom_env.visualization.recording import VisualRecorder
from .training_cases import initial
from .circuit_replay import write_circuit_replay
from .cz_training import cz_manifest,render_report


def export_saved(case,directory,target,label):
    checkpoint=json.loads((directory/'checkpoint.json').read_text(encoding='utf-8'))
    plans=json.loads((directory/'plans.json').read_text(encoding='utf-8'))
    env=NeutralAtomEnv.restore(initial(case));recorder=VisualRecorder(env.state)
    for plan in plans:
        env.submit(plan_from_dict(plan));env.run(on_event=lambda s,e:recorder.observe(s))
    assert env.snapshot()==checkpoint['current']
    payload=recorder.payload();pulses=[op for op in payload['operations'] if op['kind'] in ('raman_rotation','entangling_pulse')]
    effects=[g for op in pulses for g in op['gate_ids']]
    assert sorted(effects)==[f'g{i:04d}' for i in range(len(case['gates']))]
    cz=[op for op in pulses if op['kind']=='entangling_pulse']
    assert sum(len(op['gate_ids']) for op in cz)==sum(k=='CZ' for k,_ in case['gates'])>0
    assert any(op['kind']=='aod_move' for op in payload['operations'])
    write_circuit_replay(case,payload,target/'animation.html',label=label)
    return {'name':case['name'],'label':label,'elapsed_us':payload['duration'],
        'gate_count':len(effects),'cz_count':sum(len(op['gate_ids']) for op in cz),
        'cz_batches':len(cz),'max_cz_batch':max(len(op['gate_ids']) for op in cz),
        'pulse_time_us':sum(op['end']-op['start'] for op in pulses),
        'independent_replay_equal':True,'all_input_gates_in_view':True,
        'atom_statistics':payload['atom_statistics']}


def audit(directory):
    directory=Path(directory);config=json.loads((directory/'config.json').read_text(encoding='utf-8'))
    report=json.loads((directory/'report.json').read_text(encoding='utf-8'))
    cases=json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
    assert canonical_json(cases)==canonical_json(cz_manifest(config['distribution']))
    rows=report['test_results'];failures=[r for r in rows if r['status']!='completed']
    for r in rows:
        assert r['replay_equal'] and r['effects_once']
        if r['status']=='completed':assert r['terminal_verified']
    for name in {r['name'] for r in rows}:
        assert len({r['initial_sha256'] for r in rows if r['name']==name})==1
    replays=[];seed=config['training_seeds'][0]
    import torch
    saved=torch.load(directory/f'seed-{seed}/selected.pt',weights_only=True)
    update=saved['metadata']['selected_update']
    for case in cases:
        if case['split']!='test':continue
        for label in ('ppo_last','ppo','local_cost'):
            row=next(r for r in rows if r['name']==case['name'] and r['training_seed']==seed and r['policy']==label)
            if row['status']!='completed':continue
            source=directory/f'seed-{seed}/evaluation'/label/case['name']
            description=(f'最后PPO模型（update {config["updates"]}，不代表验证选中）' if label=='ppo_last' else
                f'验证选中模型（{"模仿" if update==0 else "PPO"}，update {update}）' if label=='ppo' else 'local_cost 基线')
            replays.append(export_saved(case,source,directory/'replays'/case['name']/label,f'{case["name"]} · {description} · seed {seed}'))
    from .train import worker_init,work
    worker_init();case=next(c for c in cases if c['split']=='test')
    loaded=work(dict(episode=config['episode'],hidden=config['hidden'],weights=saved['weights'],
        case=case,seed=seed,policy='ppo',mode='evaluate'))
    expected=next(r for r in rows if r['name']==case['name'] and r['training_seed']==seed and r['policy']=='ppo')
    assert abs(loaded['elapsed_us']-expected['elapsed_us'])<1e-7 and loaded['status']==expected['status']
    last=torch.load(directory/f'seed-{seed}/last.pt',weights_only=True)
    last_loaded=work(dict(episode=config['episode'],hidden=config['hidden'],weights=last['weights'],
        case=case,seed=seed,policy='ppo_last',mode='evaluate'))
    last_expected=next(r for r in rows if r['name']==case['name'] and r['training_seed']==seed and r['policy']=='ppo_last')
    assert abs(last_loaded['elapsed_us']-last_expected['elapsed_us'])<1e-7 and last_loaded['status']==last_expected['status']
    result={'test_executions':len(rows),'successes':len(rows)-len(failures),'failures':failures,
        'replays':replays,'weight_reload':loaded,'last_weight_reload':last_loaded,
        'selected_to_last_weight_l2':sum(float(((saved['weights'][k]-last['weights'][k])**2).sum()) for k in saved['weights'])**.5,
        'gui_verified':False,
        'limits':'Two seeds, six random circuits; same finite restoring candidate provider. No globally optimal CZ schedule claim.'}
    proof=directory/'browser-final.json'
    if proof.exists():
        gui=json.loads(proof.read_text(encoding='utf-8'))
        assert sha256((directory/gui['recording_path']).read_bytes()).hexdigest()==gui['recording_sha256']
        result.update(gui_verified=True,gui_evidence=gui)
    (directory/'acceptance.json').write_text(canonical_json(result),encoding='utf-8')
    render_report(directory,report)
    print(canonical_json({'executions':len(rows),'failures':len(failures),'replays':len(replays),'weight_reload':loaded['status']}))
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('directory');args=parser.parse_args();audit(args.directory)
