"""Compare bounded encoder candidates through the real joint compiler."""
from pathlib import Path
from copy import deepcopy
import argparse, json, sys, time
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'), str(ROOT), str(ROOT/'scripts')]
from na_pipeline.qec.factory_primitives import Circuit, css_encoder, reference_css_encoder, BLOCKS
from na_pipeline.qec.physical_dag import _program, physical_dag_from_program
from na_pipeline.validation.raw_encoder import certify_encoder
from na_pipeline.backend import LogicalComponentCompiler
from na_pipeline.device import canonical_surface17_device
from na_pipeline.runtime import run, make_scenario
from na_pipeline.validation.dag_physical import validate_physical_plan
from component_gallery_job import fixture_world, save


def encoder_dag(enc, blocks, *, mixed=False):
    c=Circuit()
    for b in blocks:
        c.reset(b+'_reset', [f'{b}_d{i}' for i in range(9)])
        c.gate(b+'_seed_H','H',[b+'_'+enc['seed']]);c.gate(b+'_seed_T','T',[b+'_'+enc['seed']])
        for q in enc['plus_inputs']:c.gate(b+'_plus_'+q,'H',[b+'_'+q])
        for i,(u,v) in enumerate(enc['cx']):c.gate(f'{b}_encode_{i}','CX',[f'{b}_d{u}',f'{b}_d{v}'],metadata={'phase':'raw_encoding','block':b})
    if mixed:c.syndrome('W4','mixed_SE',rounds=1)
    return physical_dag_from_program(_program(c,{b:b for b in BLOCKS}|{'join_probe':'join_probe'},'encoder-compare'),operation='MODULE_FRAGMENT')


def metrics(plan):
    a=plan['atom_program'];pulses=[x for x in a['actions'] if x['payload'].get('name')=='CZ']
    blocks={}
    for p in pulses:
        for s in p['payload']['pair_sources']:
            b=s['qubits'][0].rsplit('/',1)[0];blocks.setdefault(b,{'gates':0,'pulses':set()});blocks[b]['gates']+=1;blocks[b]['pulses'].add(p['id'])
    return {'duration_us':a['stats']['duration_us'],'CZ_pulses':len(pulses),'per_block':{b:{'gates':v['gates'],'CZ_layers':len(v['pulses'])} for b,v in blocks.items()},
            'pairs_by_pulse':[len(p['payload']['pairs']) for p in pulses],
            'pulse_details':[{'start_us':p['t_start_us'],'pairs':[s['qubits'] for s in p['payload']['pair_sources']]} for p in pulses],
            'pickup_count':sum(x['kind']=='pickup' for x in a['actions']),'drop_count':sum(x['kind']=='drop' for x in a['actions']),
            'action_time_us':{k:sum(x['t_end_us']-x['t_start_us'] for x in a['actions'] if x['kind']==k) for k in ('pickup','drop','move')},
            'cross_phase_pulses':sum(any('encode_' in s['physical_op_id'] for s in p['payload']['pair_sources']) and any('mixed_SE' in s['physical_op_id'] for s in p['payload']['pair_sources']) for p in pulses)}


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',required=True);ap.add_argument('--candidates',required=True);a=ap.parse_args()
    out=ROOT/a.out;out.mkdir(parents=True,exist_ok=True);search=json.loads((ROOT/a.candidates).read_bytes());base=reference_css_encoder()['columns']
    recipes=[css_encoder()]
    for candidate in search['candidates']:
        if 'recipe' in candidate:
            recipes.append(candidate['recipe']);continue
        order=candidate['order'];recipes.append({'columns':[base[i] for i in order],'seed':'d'+str(order.index(0)),
            'plus_inputs':['d'+str(i) for i,j in enumerate(order) if 1<=j<=4], 'zero_inputs':['d'+str(i) for i,j in enumerate(order) if j>4],
            'cx':candidate['cx'],'synthesis_score':candidate['score']})
    device=canonical_surface17_device();results=[]
    for i,enc in enumerate(recipes):
        proof=certify_encoder(enc)
        if not proof['passed']:raise ValueError({'candidate':i,'proof':proof})
        row={'candidate':i,'recipe':enc,'signed_proof':proof,'cases':{}}
        for n in (1,4):
            start=time.perf_counter();dag=encoder_dag(enc,[f'W{j}' for j in range(n)])
            world=fixture_world(dag['qubits'],device);c=LogicalComponentCompiler(device,budget={'max_operations':100000,'max_wall_seconds':600})
            plan=c.build_dependencies(dag,world);atom=plan['atom_program'];report=validate_physical_plan(plan,device,trace=run(atom,make_scenario(atom),device))
            if not report['passed'] or report['failures'] or report['unverified']:raise ValueError(report)
            row['cases'][str(n)]={**metrics(plan),'passed':True,'wall_seconds':time.perf_counter()-start}
        results.append(row);save(out/'comparison.json',{'status':'running','results':results});print(json.dumps({'candidate':i,'cases':row['cases']}),flush=True)
    best=min(results[1:],key=lambda r:(r['cases']['4']['duration_us'],r['cases']['1']['duration_us']))
    dag=encoder_dag(best['recipe'],['W0','W1','W2','W3'],mixed=True);world=fixture_world(dag['qubits'],device);c=LogicalComponentCompiler(device,budget={'max_operations':100000,'max_wall_seconds':1200})
    plan=c.build_dependencies(dag,world);atom=plan['atom_program'];trace=run(atom,make_scenario(atom),device);report=validate_physical_plan(plan,device,trace=trace)
    save(out/'mixed-plan.json',plan);save(out/'mixed-trace.json',trace);save(out/'mixed-validation.json',report)
    save(out/'comparison.json',{'status':'passed' if report['passed'] else 'failed','results':results,'selected':best['candidate'],'selected_recipe':best['recipe'],'mixed':metrics(plan),'global_optimality_claimed':False})
    if not report['passed']:raise ValueError(report)

if __name__=='__main__':main()
