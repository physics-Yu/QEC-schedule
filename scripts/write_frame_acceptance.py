"""Freeze the scoped checks of the delivered frame/CNOT gallery."""
from pathlib import Path
import argparse,hashlib,json,re


def read(p):return json.loads(p.read_bytes())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--dispatch',type=Path,required=True);a=p.parse_args()
    out=a.out;job=a.dispatch.parent;worker=read(job/'held-cz-receipt/worker-receipt.json')
    assert worker['returncode']==0 and worker['source_snapshot_stable'] and worker['input_snapshot_verified']
    assert read(out/'residency-and-frame-complete.json')['status']=='passed'
    assert read(out/'status.json')['status']=='passed'
    suites={}
    for name in ('qec','backend','device','runtime','validation'):
        t=(out/(name+'-tests.log')).read_text(encoding='utf-8');assert '\nOK' in t
        suites[name]=int(re.findall(r'Ran (\d+) tests?',t)[-1])
    inventory=read(job/'held-cz-receipt/source-inventory.json');verified=[]
    for path,value in inventory.items():
        if path.startswith(('src/','tests/')) and path.endswith('.py'):
            assert sha(Path(path))==value,path;verified.append(path)
    checks=['cohort-acceptance.json','atom-brightness-functional-checks.json','frame-functional-checks.json','viewer-path-audit.json']
    for name in checks:assert read(out/name)['passed'],name
    assert read(out/'viewer-path-audit.json')['original_fallback_count']==0
    protocols={}
    for name in ('T','TDG','REJECT_RETRY'):
        summary=read(out/'protocols'/name/'summary.json');assert summary['status']=='passed'
        guard=read(out/'protocols'/name/'raw-search-observation.json');assert guard['zero_native_calls']
        protocols[name]={'duration_us':summary['duration_us'],'stages':summary['physical_stage_count'],'new_native_compilation_calls':0}
    frames={p.parent.name:read(p) for p in (out/'frame-continuations').glob('*/summary.json')}
    assert len(frames)==7 and all(r['status']=='passed' for r in frames.values())
    for name in ('H_VIRTUAL','H_THEN_H'):assert frames[name]['action_count']==0 and frames[name]['duration_us']==0
    manifest=json.loads((out/'manifest.js').read_text(encoding='utf-8').split('=',1)[1].strip().removesuffix(';'))
    assert len(manifest['components'])==78
    result={'schema_version':'FrameCnotDeliveryAcceptance/0.1','status':'engineering_passed_visual_pending',
            'scope':'Surface17 canonical profile, declared CZ quarter-turn geometry, complete selected T/TDG/reject paths and seven frame continuations',
            'transfer_us':100,'components_and_examples':78,'regressions':suites,'regressions_total':sum(suites.values()),
            'source_test_files_match_server':len(verified),'server_job_id':read(a.dispatch)['job_id'],
            'protocols':protocols,'factory_through_ready_us':read(out/'timing-T.json')['factory_through_ready_us'],
            'frames':{k:{f:v[f] for f in ('duration_us','action_count','module_stats')} for k,v in frames.items()},
            'logical_cohort_audit':{k:v for k,v in read(out/'cohort-acceptance.json').items() if k not in ('rows','input_sha256')},
            'paired_CNOT_target_physical_H_required':True,'CZ_faster_than_CNOT_unconditionally':False,
            'source_and_resource_parallel_schedule_verified':True,'bounded_internal_AOD_residency_verified':True,
            'global_optimal_parallel_schedule_qualified':False,'hardware_executed':False,'quantum_state_simulated':False,
            'browser_rendering_verified':False,'user_visual_acceptance':'pending',
            'remaining_limits':['SE5, not4','shared static-scene mutation reservation','maintenance readout service groups not globally merged',
                                'standalone JOINT_ZZ remains a sequential reference','H-to-T uses explicit physical materialization',
                                'no arbitrary suspended-AOD external module boundary','independent general retime API not implemented'],
            'evidence_sha256':{n:sha(out/n) for n in checks+['timing-T.json','timing-TDG.json','timing-REJECT_RETRY.json','animation-library.html']}}
    (out/'acceptance.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:result[k] for k in ('status','components_and_examples','regressions_total','factory_through_ready_us','user_visual_acceptance')}))


if __name__=='__main__':main()
