"""Small canonical two-patch SE example through the public scheduler facade."""
from pathlib import Path
import sys,json
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT),str(ROOT/'scripts')]
from component_gallery_job import save,fixture_world
from na_pipeline.qec import instantiate_component,get_component_spec
from na_pipeline.device import canonical_surface17_device
from na_pipeline.backend import LogicalComponentCompiler
from na_pipeline.runtime import run,make_scenario
from na_pipeline.validation.dag_physical import validate_physical_plan
from viewer import export_view

def build(out):
    out=Path(out)/'SE_PAIR';out.mkdir(parents=True,exist_ok=True);device=canonical_surface17_device()
    q=get_component_spec('SE')['formal_qubits']
    dags=[instantiate_component('SE',namespace='SE-'+p,qubit_bindings={v['id']:p+'/'+v['local_id'] for v in q}) for p in ('A','B')]
    world=fixture_world([v for d in dags for v in d['qubits']],device)
    compiler=LogicalComponentCompiler(device,budget={'max_operations':1000,'max_wall_seconds':120},module_directory=out.parent/'compiled-modules')
    compiler.build_dependencies(dags,world)
    plan=compiler.compose_recipe(dags,world)
    atom=plan['atom_program'];scenario=make_scenario(atom,value=0);trace=run(atom,scenario,device)
    report=validate_physical_plan(plan,device,trace=trace);assert report['passed'] and not report['failures'] and not report['unverified']
    joint=[a for a in atom['actions'] if a['kind']=='gate' and a['payload'].get('name')=='CZ' and
           any('atom:A/' in v for pair in a['payload']['pairs'] for v in pair) and any('atom:B/' in v for pair in a['payload']['pairs'] for v in pair)]
    assert joint
    summary={'status':'passed','component_id':'SE_PAIR','physical_operations':112,'preview_input_operations':0,'atom_count':34,'action_count':len(atom['actions']),
             'duration_us':atom['stats']['duration_us'],'joint_broadcast_count':len(joint),'measurement_batches':len(plan['measurement_placements']),
             'fake_scenario':True,'quantum_state_simulated':False,'hardware_executed':False,'user_visual_acceptance':'pending',
             'implementation_version':'neutral-modular/1','module_stats':compiler.modules.stats,
             'module_count':len(plan['module_composition']['instances'])}
    for name,v in [('summary.json',summary),('physical-dag.json',dags),('physical-plan.json',plan),('atom-program.json',atom),('device.json',device),('scenario.json',scenario),('event-trace.json',trace),('validation.json',report)]:save(out/name,v)
    export_view(out/'atom-program.json',out/'full-viewer.html',trace_path=out/'event-trace.json',device_path=out/'device.json',report_path=out/'validation.json')
    print(json.dumps(summary))
if __name__=='__main__':build(ROOT/'artifacts/demos/logical-components-20261007')
