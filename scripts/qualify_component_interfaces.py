"""Scoped gate/consumer bindings using frozen sources; never runs a factory."""
from pathlib import Path
from copy import deepcopy
from unittest.mock import patch
import argparse,json,sys,time,hashlib

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from na_pipeline.runtime import LogicalGateLibrary,EventSession,make_scenario,resource_inventory,bind_consumer_suffix
from na_pipeline.device import canonical_surface17_device,build_preinitialized_state
from na_pipeline.qec import physical_resource_requirements,get_component_spec,build_factory_physical_dag
from na_pipeline.validation.dag_physical import validate_physical_plan
from na_pipeline.validation.dag_core import DAGAudit
from na_pipeline.validation.dag_session import inspect_window_binding
from na_pipeline.runtime.pipeline import save_artifact
from na_pipeline.backend.enola_kernel import StrategyError


def world(device,full=False):
    names=['data_A','data_B','data_C'] if not full else ['w'+str(i) for i in range(5)]
    ref={'artifact_id':'interface-scope-placement','producer':'R0','fixture':True}
    if full:
        req=physical_resource_requirements({'patches':[{'patch_id':n,'initial_state':{'logical_basis':'Z','logical_value':0}} for n in names]})
        patches={p:{k:r[k] for k in ('aod_group','basis','value')} for p,r in req['patches'].items()}
        inventory=resource_inventory(req,{req['factory_id']+':join_probe':[1200.,980.]},placement_ref=ref)
    else:patches={p:{'aod_group':'data','basis':'Z','value':0} for p in names};inventory=None
    placements={p:{'anchor_um':[100.*i,900.],'orientation':'x_vertical_z_horizontal'} for i,p in enumerate(patches)}
    if not full:placements['data_B']['anchor_um']=[200.,700.];placements['data_C']['anchor_um']=[800.,500.]
    return build_preinitialized_state(device,patches,placements,placement_ref=ref,resource_inventory=inventory)


def execute(library,session,name,operands,namespace,out,dags=None):
    entry=session.snapshot();before={a['atom_id']:a for a in entry['world_state']['atoms']}
    started=time.perf_counter()
    with (patch('na_pipeline.backend.compiled_modules.module_graph',side_effect=AssertionError('internal graph rebuilt')),
          patch('na_pipeline.backend.frontier_store.select_frontier',side_effect=AssertionError('internal batch selection'))):
        prepared=library.prepare(name,session,operands=operands,invocation_id=namespace) if dags is None else library.prepare_dags(name,session,dags)
    atom=prepared['atom_program'];plan=prepared['physical_plan'];scenario=make_scenario(atom)
    session.submit(atom,scenario,expected_revision=prepared['context']['revision']);session.advance()
    trace=session.export_trace()
    ids={a['id'] for a in atom['actions']};events=[e for e in trace['events'] if e['action_id'] in ids]
    results={r:v for r,v in trace['results'].items() if v['action_id'] in ids}
    begin=min(a['t_start_us'] for a in atom['actions']);end=session.now_us
    window_trace={'schema_version':'EventTrace/0.2.0-draft','artifact_id':namespace+'/actual-window',
        'provenance':{'owner':'R0','fixture':True,'normalization':'actual events from one submitted window; illumination is cumulative delta'},
        'execution_kind':'fake_event_run','quantum_state_simulated':False,'hardware_executed':False,'loss_enabled':False,
        'sampled':False,'measurement_origin':'fake','atom_program_ref':atom['artifact_id'],'device_ref':session.device['artifact_id'],
        'events':events,'results':results,'final_state':trace['final_state'],
        'illumination_counts':{a:v-entry['illumination_counts'].get(a,0) for a,v in trace['illumination_counts'].items()},
        'stats':{'t_start_us':begin,'t_end_us':end,'duration_us':end-begin,'action_count':len(ids),'atom_count':len(before),
            'result_count':len(results),'executed_action_count':sum(e['status']=='completed' for e in events),
            'skipped_action_count':sum(e['status']=='skipped' for e in events)}}
    projection=deepcopy(plan);projection['atom_program']=atom
    report=validate_physical_plan(projection,session.device,trace=window_trace)
    if not report['passed']:raise ValueError(report)
    audit=DAGAudit('exact_original_runtime_binding',{'physical_plan':plan,'bound_program':atom,'context':prepared['context']},fixture=True)
    inspect_window_binding(audit,plan,atom,prepared['context'],trace['results'],session.run_id)
    if not audit.report()['passed']:raise ValueError(audit.report())
    for file,value in [('physical-plan.json',plan),('atom-program.json',atom),('event-trace.json',window_trace),('session-trace.json',trace),('scenario.json',scenario),('validation.json',report),('binding-validation.json',audit.report())]:
        save_artifact(out/file,value)
    return {'component':name,'operands':operands,'passed':True,'source_operations':sum(len(d['nodes']) for d in plan['physical_dags']),
            'actions':len(atom['actions']),'world_atoms':len(before),'outputs':prepared['results'],
            'template_id':library.describe(name)['template_id'],'instance':plan['parametric_component_instance'],
            'wall_seconds':time.perf_counter()-started}


def qualify(source,out):
    out.mkdir(parents=True,exist_ok=True);device=canonical_surface17_device()
    lib=LogicalGateLibrary(device,connection_directory=out/'connections',budget={'max_wall_seconds':600,'max_operations':100000})
    source_rows=[]
    for folder in sorted(source.iterdir()):
        if not (folder/'physical-plan.json').is_file():continue
        row=lib.import_component(folder.name,folder)
        operands={p:('port_atom_'+str(i) if '$atom' in q['sites'] else 'port_patch_'+str(i)) for i,(p,q) in enumerate(row['operands'].items())}
        dags=lib.source(folder.name,operands=operands,invocation_id='binding-test:'+folder.name)
        lib._get(folder.name).bind_graph(dags)
        source_rows.append({'component':folder.name,'passed':True,'template_id':row['template_id'],
                            'operand_ports':list(row['operands']),'inputs':row['inputs'],'input_boundary':row['input_boundary']})
    print(json.dumps({'source_binding_entries':len(source_rows),'passed':True}),flush=True)
    session=EventSession(device,world(device),run_id='qualification:live-gate-calls')
    calls=[]
    for i,name in enumerate(('CX','H','X','Z','SE','MEASURE_Z')):
        operands={p:('data_B' if p=='target' else 'data_A') for p in lib.describe(name)['operands']}
        calls.append(execute(lib,session,name,operands,'gate-'+str(i),out/('gate-'+str(i))))
        print(json.dumps({'gate':name,'passed':True,'time_us':session.now_us}),flush=True)
    # The exact measurement result is published by this same session. No
    # measurement fixture or prefilled bit is copied from the gallery.
    measurement_result=calls[-1]['outputs'][-1]
    desc=lib.describe('FEEDBACK_X');prepared=lib.prepare('FEEDBACK_X',session,operands={'block':'data_B'},
        invocation_id='feedback-real-input',result_bindings={desc['inputs'][0]:measurement_result})
    atom=prepared['atom_program'];session.submit(atom,make_scenario(atom),expected_revision=prepared['context']['revision']);session.advance()
    feedback={'passed':True,'input_result':measurement_result,'actual_value':session.results[measurement_result]['value'],
              'no_synthetic_measurements':not any(a['kind']=='measure' for a in atom['actions']),
              'actions_causally_skipped':all(session.events[a['id']]['status']=='skipped' for a in atom['actions'])}
    assert feedback['no_synthetic_measurements'] and feedback['actions_causally_skipped']
    save_artifact(out/'feedback.json',feedback)
    consumers=[]
    for target in ('w1','w3'):
        s=EventSession(device,world(device,full=True),run_id='qualification:consumer-geometry:'+target)
        operands={p:target if p=='live_data' else p+':join_probe' if '$atom' in q['sites'] else p
                  for p,q in lib.describe('factory.consume')['operands'].items()}
        suffix=bind_consumer_suffix(get_component_spec('factory.consume')['protocol'],target,request_id='use-'+target)
        graph=build_factory_physical_dag(suffix,'consume')
        row=execute(lib,s,'factory.consume',operands,'consume-'+target,out/('consumer-'+target),dags=graph)
        save_artifact(out/('consumer-'+target)/'consumer-suffix.json',suffix)
        row['scope']='consumer component geometry/source only; encoded magic input is a declared test contract, no ready token or factory execution'
        row['factory_started']=False;row['target_patch']=target
        plan=json.loads((out/('consumer-'+target)/'physical-plan.json').read_bytes())
        ops=[n for d in plan['physical_dags'] for n in d['nodes']]
        pairs=[n['qubits'] for n in ops if n['kind']=='gate' and len(n['qubits'])==2]
        assert len(pairs)==9 and all(a.startswith(target+'/d') and b.startswith('factory0:W4/d') for a,b in pairs)
        assert not any(n['kind'] in ('reset','measure') and any(q.startswith(target+'/d') for q in n['qubits']) for n in ops)
        row['data_control_magic_target_pairs']=pairs;row['live_data_not_destructively_measured_or_reset']=True
        consumers.append(row);print(json.dumps({'consumer':target,'passed':True,'atoms':row['world_atoms']}),flush=True)
    result={'schema_version':'ComponentInterfaceQualification/0.1','passed':True,'full_factory_executed':False,
        'compiled_library_source':str(source.resolve()),
        'interface_source_hashes':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in
            [ROOT/'src/na_pipeline/runtime'/n for n in ('component_interface.py','parametric_component.py','factory_ports.py','factory_session.py','resource_pool.py')]},
        'source_binding_entries':source_rows,'continuous_gate_calls':calls,'feedback':feedback,'consumer_geometry_calls':consumers,
        'catalog':lib.catalog(),'quantum_state_simulated':False,'hardware_executed':False,'sampled':False,
        'acceptance_scope':'structural bindings for imported recipes; listed physical examples plus separate lifecycle unit fixtures',
        'user_visual_acceptance':'pending'}
    save_artifact(out/'acceptance.json',result)
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    args=p.parse_args();qualify(args.source,args.out)
