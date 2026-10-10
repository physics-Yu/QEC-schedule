"""Join explicit component, continuous-session, reuse and viewer evidence."""
from pathlib import Path
import argparse,gzip,json,hashlib


def read(path):
    path=Path(path);data=path.read_bytes()
    return json.loads(gzip.decompress(data) if path.suffix=='.gz' else data)


def accept(out):
    out=Path(out);catalog=read(out/'catalog.json');physical=[]
    for row in catalog['components']:
        if row['kind']!='physical':continue
        report=read(out/row['id']/'validation.json');summary=read(out/row['id']/'summary.json')
        assert summary['status']=='passed' and report['passed'] and not report['failures'] and not report['unverified'],row['id']
        assert summary['implementation_version']=='neutral-modular/1'
        assert not any(summary['composition_search_delta'].values())
        physical.append({'id':row['id'],'action_count':summary['action_count'],'duration_us':summary['duration_us']})
    assert len(physical)==65
    protocols=[]
    for name,count in (('T',39),('TDG',39),('REJECT_RETRY',26)):
        folder=out/'protocols'/name;summary=read(folder/'summary.json');guard=read(folder/'raw-search-observation.json')
        assert summary['status']=='passed' and summary['physical_stage_count']==count,(name,summary)
        assert guard['zero_native_calls'] and not any(guard['call_counts'].values())
        for key in ('leaf_compile_count','placement_search_count','routing_search_count'):
            assert summary['module_stats'][key]==0
        for phase in summary['phases']:
            raw=read(folder/phase['artifact'])
            assert raw['validation']['passed'] and not raw['validation']['failures'] and not raw['validation']['unverified']
            assert raw['atom_program']['time_basis']=='absolute_session'
            assert len({a.get('site_id',a['qubit_id']) for a in raw['atom_program']['initial_state']['atoms']})==len(raw['atom_program']['initial_state']['atoms'])
            assert all(i['cache_hit'] and i['search_calls']==0 and i['static_geometry_passed'] for i in raw['physical_plan']['module_composition']['instances'])
        if name!='REJECT_RETRY':
            controller=read(folder/'controller.json');pool=read(folder/'pool.json')
            assert controller['terminal']=='consumed' and controller['token']['status']=='consumed'
            assert not pool['active_leases']
        else:
            assert summary['outcome']=='rejected_cleaned_and_new_epoch_initialized'
            assert summary['phases'][-1]['epoch']==1 and summary['phases'][-1]['stage_id']=='initialize'
            controller=read(folder/'controller.json');pool=read(folder/'pool.json')
            assert controller['epoch']==1 and controller['token'] is None
            releases=[x for x in pool['history'] if x['event']=='release' and x['epoch']==0]
            assert len(releases)==1
        protocols.append({'id':name,'stages':count,'actions':summary['action_count'],'duration_us':summary['duration_us'],
                          'module_stats':summary['module_stats'],'outcome':summary['outcome'],'native_entry_guard':guard})
    pair=read(out/'SE_PAIR/summary.json');assert pair['status']=='passed' and pair['joint_broadcast_count']>0
    viewer=read(out/'standalone-functional-checks.json');assert viewer['passed'] and viewer['components']==71
    source=read(out/'source-structure-audit.json');assert source['passed'] and len(source['components'])==66
    for name in ('SE','H','CX','CZ','S','SDG'):assert read(out/name/'source-semantics.json')['passed']
    proof=read(out/'compiled-modules/reindex-proof.json');assert proof['artifact_count']==415 and proof['leaf_compile_count']==0
    html=out/'full-viewer.html'
    result={'schema_version':'ModularComponentAcceptance/0.1','engineering_passed':True,'component_count':70,'parallel_examples':1,
            'physical_components':physical,'protocols':protocols,'immutable_modules_reindexed_without_search':proof['artifact_count'],
            'viewer_checks':viewer,'window':html.name,'window_sha256':hashlib.sha256(html.read_bytes()).hexdigest(),
            'scope':'compiled device model and no-loss fake events; source algebra and full-world physical constraints',
            'quantum_state_simulated':False,'hardware_executed':False,'fault_tolerance_qualified':False,'user_visual_acceptance':'pending',
            'full_shor_executed':False}
    (out/'acceptance.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',required=True);a=p.parse_args()
    r=accept(a.out);print(json.dumps({'engineering_passed':r['engineering_passed'],'components':r['component_count'],'visual':'pending'}))
