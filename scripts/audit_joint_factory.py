"""Action/source evidence for two-level parallelism; no compilation or sampling."""
from pathlib import Path
from collections import Counter,defaultdict
import argparse,gzip,hashlib,json


def read(p):
    b=p.read_bytes();return json.loads(gzip.decompress(b) if p.suffix=='.gz' else b)


def plan_audit(plan,store,label):
    ops={o['id']:o for d in plan['physical_dags'] for o in d['nodes']};actions=plan['atom_program']['actions'];byid={a['id']:a for a in actions}
    pulses=[a for a in actions if a['payload'].get('name')=='CZ'];mapped=plan['atom_program']['source_map'];raw=defaultdict(list);se=defaultdict(list)
    for sid,o in ops.items():
        if '_encode_' in sid and o['params'].get('name')=='CX':raw[(o['qubits'][0].rsplit('/',1)[0],sid.rsplit('_encode_',1)[0])].append(o)
        m=o.get('metadata',{})
        if m.get('phase')=='SE' and o['params'].get('name')=='CX':se[(o['qubits'][0].rsplit('/',1)[0],m['se_instance'],m['se_round'])].append(o)
    def groups(rows):
        out=[]
        for key,items in rows.items():
            ids={o['id'] for o in items};last={};layers=[]
            for o in items:
                n=1+max((last.get(q,0) for q in o['qubits']),default=0);layers.append(n)
                for q in o['qubits']:last[q]=n
            batches=[a for a in pulses if any(s['physical_op_id'] in ids for s in a['payload']['pair_sources'])]
            out.append({'group':list(key),'physical_CX':len(items),'source_pair_dependency_depth':max(layers,default=0),
                'CZ_layers':len(batches),'pulse_pairs':[{'start_us':a['t_start_us'],'own_pairs':[s['qubits'] for s in a['payload']['pair_sources'] if s['physical_op_id'] in ids],
                    'all_pairs':len(a['payload']['pairs'])} for a in batches]})
        return out
    graph=plan['module_composition']['dependency_graph'];fronts=graph.get('joint_frontiers',[]);provenance=[]
    for f in fronts:
        expected=set(f['ready_source_ids']);eligible=set(f['candidate_source_ids']);selected=set(f['selected_source_ids'])
        assert selected<=eligible<=expected
        assert expected==eligible|{d['source_id'] for d in f['deferred']}
        assert selected|{d['source_id'] for d in f['unselected']}==eligible
        import re
        assert re.fullmatch('[0-9a-f]{64}',f['decision_hash'])
        proof=store/('frontier-proof-'+f['decision_hash']+'.json')
        artifact=read(proof if proof.exists() else store/f['artifact_file']);body=artifact['body'];buildids=body['build_source_ids'];indices=body['identity']['eligible_indices']
        assert artifact['hash']==f['decision_hash'],(label,'FRONTIER_PROOF_REFERENCE_CHANGED')
        candidate_ids={c['op_id'] for r in body['kernel_receipts'] if r.get('joint_search') is None for c in r['candidates']}
        assert candidate_ids=={buildids[i] for i in indices},(label,'ENOLA_FRONTIER_CANDIDATE_OMITTED')
        assert body['scheduler_receipts'] and set(o['id'] for o in body['scheduler_receipts'][0]['input_operations'])==candidate_ids
        provenance.append({'decision':artifact['hash'],'complete_eligible_domain_observed':True,'ready':len(expected),'eligible':len(eligible),'selected':len(selected)})
    for m,instance in zip(graph['modules'],plan['module_composition']['instances']):
        if m['kind']=='entangling_layer':
            selected=set(m['source_ids']);actual=[p for p in pulses if any(s['physical_op_id'] in selected for s in p['payload']['pair_sources'])]
            assert len(actual)==1,(label,m['id'],'POST_SELECTION_RESERIALIZED',len(actual))
    mixed=[]
    for p in pulses:
        phases=Counter(ops[s['physical_op_id']].get('metadata',{}).get('phase','other') for s in p['payload']['pair_sources'])
        blocks=Counter(q.rsplit('/',1)[0] for s in p['payload']['pair_sources'] for q in s['qubits'][:1])
        mixed.append({'start_us':p['t_start_us'],'phase_pairs':dict(phases),'block_pairs':dict(blocks),'pairs':[s['qubits'] for s in p['payload']['pair_sources']]})
    # Actual action DAG critical chain, including explicit compiler offsets.
    origin=plan['atom_program']['stats'].get('t_start_us',0.);end=plan['atom_program']['stats']['t_end_us']
    chain=[];leaf=max(actions,key=lambda a:a['t_end_us']);tail=end-leaf['t_end_us']
    while leaf:
        parents=[byid[d] for d in leaf['depends_on'] if d in byid]
        parent=max(parents,key=lambda a:a['t_end_us']) if parents else None
        ready=parent['t_end_us'] if parent else origin
        gap=leaf['t_start_us']-ready
        assert gap>=-1e-7,(label,leaf['id'],'DEPENDENCY_AFTER_START')
        chain.append({'action_id':leaf['id'],'kind':leaf['payload'].get('name',leaf['kind']),
            'duration_us':leaf['t_end_us']-leaf['t_start_us'],'prior_gap_us':max(0.,gap),
            'gap_classification':'explicit_schedule_or_feedback_offset' if gap>1e-7 else 'none',
            'source_ids':leaf['payload'].get('physical_op_ids',[])})
        leaf=parent
    assert abs(sum(v['duration_us']+v['prior_gap_us'] for v in chain)+tail-(end-origin))<1e-6
    return {'label':label,'duration_us':end-origin,'raw_encoders':groups(raw),'SE_rounds':groups(se),
            'frontier_evidence':provenance,'CZ_pulses':len(pulses),'pulse_details':mixed,
            'counts':dict(Counter(a['kind'] for a in actions)),
            'action_work_us':dict(sum((Counter({a['kind']:a['t_end_us']-a['t_start_us']}) for a in actions),Counter())),
            'readout_batches':len(plan['measurement_placements']),
            'joint_readout_group_counts':[len(p.get('source_group_ids',[])) for p in plan['measurement_placements']],
            'AOD_residency_saved_us':plan.get('aod_residency',{}).get('saved_transfer_us',0.),
            'wait_reasons':dict(Counter(c['reason'] for m in plan['module_composition']['instances'] for c in m['schedule_constraints'])),
            'critical_action_chain':list(reversed(chain)),'terminal_result_latency_us':tail,
            'critical_path_scope':'actual scheduled action DAG; offsets are reported, not claimed hardware lower bounds'}


def audit(out,baseline):
    store=out/'compiled-modules';protocols={}
    for name in ('T','TDG','REJECT_RETRY'):
        folder=out/'protocols'/name;summary=read(folder/'summary.json');rows=[]
        for phase in summary['phases']:
            r=read(folder/phase['artifact']);rows.append(plan_audit(r['physical_plan'],store,name+'/'+phase['id']))
        old=read(baseline/'protocols'/name/'summary.json')
        ready=next((p['end_us'] for p in summary['phases'] if p['stage_id']=='convert_output'),None)
        oldready=next((p['end_us'] for p in old['phases'] if p['stage_id']=='convert_output'),None)
        protocols[name]={'duration_us':summary['duration_us'],'baseline_duration_us':old['duration_us'],
            'factory_through_ready_us':ready,'baseline_factory_through_ready_us':oldready,
            'improvement_fraction':1-summary['duration_us']/old['duration_us'],'stages':rows}
    examples={p.parent.name:plan_audit(read(p),store,p.parent.name) for p in (out/'parallel-examples').glob('*/physical-plan.json')}
    result={'schema_version':'JointFactoryParallelAcceptance/0.1','passed':True,'protocols':protocols,'examples':examples,
        'same_transfer_us':100,'continuous_initial_and_exit_contract':True,'source_CX_depth_is_not_hardware_optimum':True,
        'frontier_candidates_and_post_selection_parallelism_checked':True,
        'scope':'every selected stage of complete T/TDG/reject paths plus single/four/mixed examples',
        'global_optimality_claimed':False,'noise_or_fault_tolerance_qualified':False,'user_visual_acceptance':'pending'}
    (out/'joint-parallel-acceptance.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--baseline',type=Path,default=Path('artifacts/demos/frame-cnot-cohorts-20261008'));a=p.parse_args()
    r=audit(a.out,a.baseline);print(json.dumps({k:{f:v[f] for f in ('duration_us','baseline_duration_us','factory_through_ready_us','improvement_fraction')} for k,v in r['protocols'].items()}))
