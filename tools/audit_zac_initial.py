"""Independently audit saved four-arm inputs, effects, initial and terminal states."""
from collections import Counter
from hashlib import sha256
from pathlib import Path
import argparse
import json
import math
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from neutral_atom_env import NeutralAtomEnv
from neutral_atom_env.replay.serializer import canonical_json, primitive
from neutral_atom_experiments.zac_reuse import make_state
from neutral_atom_strategies.scheduling.m3 import initial_terminal


def audit(root):
    root=Path(root)
    read=lambda p:json.loads(p.read_text(encoding='utf-8'))
    manifest=read(root/'benchmark.json')
    assert manifest['schema']=='zac-initial-benchmark/1' and manifest['status']=='finished'
    assert sha256(canonical_json(manifest['contract']).encode()).hexdigest()==manifest['contract_sha256']
    counts=Counter()
    for case in manifest['cases']:
        spec=read(root/case['id']/'input.json')
        assert spec==case['spec']
        reference=make_state(spec)
        terminal=primitive(initial_terminal(reference))
        terminal_hash=sha256(canonical_json(terminal).encode()).hexdigest()
        reference=json.loads(NeutralAtomEnv(reference).snapshot())
        initial_hashes={};mappings={}
        expected=Counter({f'g{i:04d}':1 for i in range(len(spec['pairs']))})
        depth=[0]*spec['atom_count']
        for a,b in spec['pairs']:
            depth[a]=depth[b]=max(depth[a],depth[b])+1
        for mode,run in case['variants'].items():
            counts[run['status']]+=1
            assert run['status'] in ('completed','failed','timeout')
            directory=root/case['id']/mode
            assert read(directory/'worker.json')==run
            upstream=directory/'upstream/placement.json'
            if upstream.exists():
                placement=read(upstream)
                assert placement['spec']==dict(spec,initial_placement='sa' if mode.startswith('sa_') else 'fixed')
                assert len(placement['gate_layers'])==max(depth)
                assert Counter(i for layer in placement['gate_layers'] for i in layer)==Counter(range(len(expected)))
                info=placement['initial_placement']
                mappings[mode]=info['mapping']
                assert mappings[mode]==placement['mappings'][0]
                assert len({tuple(s) for s in mappings[mode]})==spec['atom_count']
                if mode.startswith('fixed_'): assert mappings[mode]==spec['initial_mapping']
            if 'result' not in run:
                assert run.get('error')
                continue
            result=read(directory/'result.json');assert result==run['result']
            initial_text=(directory/'initial.json').read_text(encoding='utf-8')
            initial_hashes[mode]=sha256(initial_text.encode()).hexdigest()
            assert initial_hashes[mode]==result['initial_sha256']
            initial=json.loads(initial_text);final=read(directory/'checkpoint.json')
            actual_initial=make_state(dict(spec,initial_mapping=mappings[mode]))
            assert initial_text==NeutralAtomEnv(actual_initial).snapshot()
            assert read(directory/'terminal-target.json')==terminal
            assert result['terminal_target_sha256']==terminal_hash
            trace=[json.loads(line) for line in (directory/'trace.jsonl').read_text(encoding='utf-8').splitlines()]
            effects=Counter(g for record in trace if record.get('effect_completed') for g in record.get('effect_gate_ids',[]))
            assert all(effects[g]<=expected[g] for g in effects)
            assert (effects==expected)==result['effects_once']
            assert sum(effects.values())==result['metrics']['completed_gate_count']
            assert math.isclose(sum(result['phase_time_us'].values()),result['metrics']['episode_wall_time_us'],abs_tol=1e-6)
            if run['status']=='completed':
                assert result['replay_equal'] and result['effects_once'] and result['terminal_verified']
                assert all(x['passed'] for x in result['reuse_audit'])
                assert len(result['reuse_audit'])==sum(map(len,result['selected_reuse'][:-1]))
                for key in ('placement','slm_enabled','aod'):
                    assert final[key]==reference[key],(case['id'],mode,key)
        for prefix in ('fixed','sa'):
            a,b=prefix+'_no_reuse',prefix+'_reuse'
            if a in initial_hashes and b in initial_hashes: assert initial_hashes[a]==initial_hashes[b]
            if a in mappings and b in mappings: assert mappings[a]==mappings[b]
        for comparison in case['comparisons'].values():
            a,b=(case['variants'][comparison[k]] for k in ('baseline','candidate'))
            complete=all(r['status']=='completed' for r in (a,b))
            assert comparison['comparable']==complete
            if complete:
                expected_delta=100*(b['result']['metrics']['episode_wall_time_us']/a['result']['metrics']['episode_wall_time_us']-1)
                assert math.isclose(comparison['change_percent'],expected_delta,abs_tol=1e-9)
            else: assert comparison['change_percent'] is None
    result=dict(status='passed',cases=len(manifest['cases']),variants=dict(counts),
        checks=['contract and saved input','four-arm identical circuit/platform','actual SA initial snapshots',
                'paired identical initial mapping','trace exactly once','independent ASAP depth','phase accounting',
                'residency audit coverage','one common full absolute terminal','completed-only percentages'])
    (root/'audit.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('output',type=Path)
    print(json.dumps(audit(p.parse_args().output),indent=2))
