"""T044 persistent, per-component compilation. Outputs come from real plans."""
from pathlib import Path
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from copy import deepcopy
import hashlib
import json
import sys
import time
import traceback
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from na_pipeline.qec import component_catalog,get_component_spec,shor_component_requirements
from na_pipeline.qec.physical_dag import physical_dag_from_program
from na_pipeline.device import canonical_surface17_device,build_preinitialized_state,validate_preinitialized_state
from na_pipeline.backend import LogicalComponentCompiler
from na_pipeline.runtime import run,make_scenario
from na_pipeline.validation.dag_physical import validate_physical_plan
from viewer import export_view

def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,separators=(',',':'))+'\n',encoding='utf-8')

def fixture_world(qubits,device,*,orientations=None):
    groups={};singles=[]
    for q in qubits:
        tail=q['id'].rsplit('/',1)[-1]
        if tail in [f'{p}{i}' for p,n in [('d',9),('x',4),('z',4)] for i in range(n)]:
            groups[q['id'].rsplit('/',1)[0]]=q['aod_group']
        else:singles.append(q)
    if not groups:groups={'test-input':'data'}
    patches={p:{'aod_group':a,'basis':'Z','value':0} for p,a in groups.items()}
    placements={p:{'anchor_um':[100.*i,900.],'orientation':'x_vertical_z_horizontal'} for i,p in enumerate(patches)}
    for p,orientation in (orientations or {}).items():
        placements[p]['orientation']=orientation
    inv={'schema_version':'initial-resource-inventory/0.1','artifact_id':'component-fixture-inventory',
         'provenance':{'producer':'R0-component-gallery','fixture':True,'source_refs':['LogicalComponentSpec/0.1']},
         'patch_roles':{p:{'role':'algorithm' if a=='data' else 'factory','pool_id':'component','slot_id':p} for p,a in groups.items()},
         'nonpatch_atoms':{'atom:'+q['id']:{'qubit_id':q['id'],'trap_id':'slm:'+q['id'],'position_um':[100.*len(patches)+10.*i,980.],
                             'aod_group':q['aod_group'],'role':'probe','pool_id':'component','slot_id':'probe:'+q['id'],'basis':'Z','value':0}
                           for i,q in enumerate(singles)}}
    world=build_preinitialized_state(device,patches,placements,placement_ref={'artifact_id':'canonical-component-fixture','producer':'R0-canonical-layout','fixture':True},resource_inventory=inv)
    errors=validate_preinitialized_state(world,device)
    if errors:raise ValueError(errors)
    return world

def preview_dag(spec):
    dag=deepcopy(spec['physical_dag']);reads=dag['external_reads']
    if not reads:return dag,[]
    # Demonstration inputs are actual measured auxiliary carriers. Their configured
    # fake values remain scenario inputs, never scheduler-supplied ready evidence.
    qubits=deepcopy(dag['qubits'])
    qubits += [{'id':f'test-input/{p}{i}','block_id':'test-input','local_id':f'{p}{i}',
                'role':'data' if p=='d' else 'syndrome','aod_group':'data'} for p,n in [('d',9),('x',4),('z',4)] for i in range(n)]
    prefix=[];slots=['x0','x1','x2','x3','z0','z1','z2','z3']
    for i,r in enumerate(reads):
        prefix.append({'id':f'test-input/measure-{i}','kind':'measure','qubits':['test-input/'+slots[i]],'params':{'basis':'Z'},
                       'reads':[],'writes':[r],'after':[],'condition':None,'source_ids':['T044:explicit_fake_input_readout']})
    merged=deepcopy(dag);merged['artifact_id']='component-preview-'+spec['id']
    merged['qubits']=qubits;merged['nodes']=prefix+dag['nodes'];merged['external_reads']=[]
    writers={r:o['id'] for o in prefix for r in o['writes']}
    merged['result_producers'].update(writers)
    merged['result_types'].update({r:'bit' for r in reads})
    for o in prefix:merged['source_map'][o['id']]={'physical_source_op_id':o['id'],'source_ids':o['source_ids']}
    for o in dag['nodes']:
        for r in o['reads']:
            if r in writers:
                merged['edges'].append({'source':writers[r],'target':o['id'],'kind':'classical_ready','result_id':r})
                if writers[r] not in o['after']:o['after'].append(writers[r])
    targets={e['target'] for e in merged['edges']};sources={e['source'] for e in merged['edges']}
    merged['roots']=[o['id'] for o in merged['nodes'] if o['id'] not in targets]
    merged['terminals']=[o['id'] for o in merged['nodes'] if o['id'] not in sources]
    merged['provenance']['fixture']=True
    merged['preview_input_prefix']={'component_spec_hash':spec['spec_hash'],'external_reads':reads,
                                    'measurement_operations':[o['id'] for o in prefix]}
    return merged,reads

def compile_one(component_id,out,budget_seconds):
    started=time.perf_counter();folder=Path(out)/component_id;folder.mkdir(parents=True,exist_ok=True)
    save(folder/'status.json',{'status':'running','component_id':component_id})
    try:
        spec=get_component_spec(component_id)
        dag,inputs=preview_dag(spec);device=canonical_surface17_device()
        world=fixture_world(dag['qubits'],device,orientations={'right':'canonical_rot90'} if component_id=='CZ' else None)
        compiler=LogicalComponentCompiler(device,budget={'max_operations':100000,'max_wall_seconds':budget_seconds},module_directory=Path(out)/'compiled-modules')
        dag=compiler.resolve_geometry(dag,world)
        build=compiler.build_dependencies(dag,world)
        before=compiler.modules.stats
        plan=compiler.compose_recipe(dag,world);atom=plan['atom_program']
        delta={k:compiler.modules.stats[k]-before[k] for k in ('leaf_compile_count','placement_search_count','routing_search_count')}
        if any(delta.values()):raise ValueError('COMPOSITION_RECOMPILED_DEPENDENCY')
        save(folder/'module-build.json',{'dependency_graph':build['module_composition']['dependency_graph'],'counters':before})
        save(folder/'module-composition.json',plan['module_composition'])
        scenario=make_scenario(atom,value=0)
        if inputs:
            wanted=([0,1,0,0,0,0,0,0] if component_id=='CLASSICAL_POSTPROCESS' else [1]*len(inputs))
            for r,v in zip(inputs,wanted):scenario['results'][r]['value']=v
        trace=run(atom,scenario,device);report=validate_physical_plan(plan,device,trace=trace)
        for name,value in [('component-spec.json',spec),('device.json',device),('initial-state.json',world),('physical-dag.json',dag),
                           ('physical-plan.json',plan),('atom-program.json',atom),('scenario.json',scenario),('event-trace.json',trace),('validation.json',report)]:save(folder/name,value)
        if not report['passed'] or report['failures'] or report['unverified']:raise ValueError({'validation':report})
        export_view(folder/'atom-program.json',folder/'full-viewer.html',trace_path=folder/'event-trace.json',device_path=folder/'device.json',report_path=folder/'validation.json')
        summary={'status':'passed','component_id':component_id,'physical_operations':len(spec['physical_dag']['nodes']),
                 'preview_input_operations':len(inputs),'atom_count':len(world['atoms']),'action_count':len(atom['actions']),
                 'duration_us':atom['stats']['duration_us'],'wall_seconds':time.perf_counter()-started,'measurement_batches':len(plan['measurement_placements']),
                 'fake_scenario':True,'source_spec_hash':spec['spec_hash'],'quantum_state_simulated':False,'hardware_executed':False,'user_visual_acceptance':'pending',
                 'module_stats':compiler.modules.stats,'composition_search_delta':delta,'module_count':len(plan['module_composition']['instances']),
                 'geometry_variants':dag.get('geometry_variant_selection',[]),'implementation_version':'neutral-modular/1'}
        save(folder/'summary.json',summary);save(folder/'status.json',summary)
        print(json.dumps(summary),flush=True);return summary
    except Exception as e:
        error={'status':'failed','component_id':component_id,'wall_seconds':time.perf_counter()-started,
               'error':str(e),'type':type(e).__name__,'details':getattr(e,'details',None),'traceback':traceback.format_exc()}
        save(folder/'status.json',error);print(json.dumps(error),flush=True);return error

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',default='artifacts/demos/logical-components-20261007');ap.add_argument('--components',nargs='*')
    ap.add_argument('--workers',type=int,default=4);ap.add_argument('--seconds',type=float,default=3600);args=ap.parse_args()
    out=ROOT/args.out;out.mkdir(parents=True,exist_ok=True)
    catalog=component_catalog();save(out/'catalog.json',catalog);save(out/'shor-coverage.json',shor_component_requirements())
    rows=[r for r in catalog['components'] if r['kind']=='physical' and (not args.components or r['id'] in args.components)]
    status={'status':'running','total':len(rows),'completed':[],'failed':[],'workers':args.workers,'per_component_seconds':args.seconds}
    save(out/'status.json',status)
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        tasks={pool.submit(compile_one,r['id'],str(out),args.seconds):r['id'] for r in rows}
        for f in as_completed(tasks):
            result=f.result();status['completed' if result['status']=='passed' else 'failed'].append(result)
            save(out/'status.json',status)
    status['status']='passed' if not status['failed'] else 'incomplete';save(out/'status.json',status)
    if status['failed']:raise SystemExit(1)

if __name__=='__main__':main()
