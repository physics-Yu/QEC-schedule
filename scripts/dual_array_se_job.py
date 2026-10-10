"""Bounded six-block shared-CZ/readout qualification for two real AOD groups."""
from pathlib import Path
import argparse,json,sys
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT),str(ROOT/'scripts')]
from component_gallery_job import save,fixture_world


def build(folder,store):
    from na_pipeline.qec.factory_primitives import Circuit,BLOCKS
    from na_pipeline.qec.physical_dag import _program,physical_dag_from_program
    from na_pipeline.backend import LogicalComponentCompiler
    from na_pipeline.device import canonical_surface17_device
    from na_pipeline.runtime import run,make_scenario
    from na_pipeline.validation.dag_physical import validate_physical_plan
    from joint_encoder_job import metrics
    from viewer import export_view
    c=Circuit()
    for b in ('W0','W1','W2','W3','W4','D'):c.syndrome(b,'SE_'+b,rounds=1)
    dag=physical_dag_from_program(_program(c,{b:b for b in BLOCKS}|{'join_probe':'join_probe'},'SE_DUAL_SIX'),operation='MODULE_FRAGMENT')
    for q in dag['qubits']:q['aod_group']='data' if q['id'].startswith('D/') else 'magic'
    d=canonical_surface17_device();world=fixture_world(dag['qubits'],d)
    compiler=LogicalComponentCompiler(d,budget={'max_operations':100000,'max_wall_seconds':1800},module_directory=store)
    compiler.build_dependencies(dag,world);before=compiler.modules.stats;plan=compiler.compose_recipe(dag,world)
    if compiler.modules.stats['frontier_search_count']!=before['frontier_search_count']:raise ValueError('SE_REBIND_SEARCHED')
    atom=plan['atom_program'];scenario=make_scenario(atom);trace=run(atom,scenario,d);report=validate_physical_plan(plan,d,trace=trace)
    if not report['passed'] or report['unverified']:raise ValueError(report)
    p=[a for a in atom['actions'] if a['payload'].get('name')=='CZ'];reads=[a for a in atom['actions'] if a['kind']=='measure']
    if [len(a['payload']['pairs']) for a in p]!=[36,18,36,18,36] or len(reads)!=48 or len({a['t_start_us'] for a in reads})!=1:raise ValueError('SIX_PATCH_SE_FRAGMENTED')
    folder.mkdir(parents=True,exist_ok=True)
    summary={'status':'passed','id':'SE_DUAL_SIX',**metrics(plan),'physical_operations':len(dag['nodes']),
        'atom_count':len(world['atoms']),'action_count':len(atom['actions']),'AOD_groups':['data','magic'],
        'simultaneous_readouts':48,'CZ_pulse_counts':[len(a['payload']['pairs']) for a in p],'user_visual_acceptance':'pending'}
    for name,value in [('summary.json',summary),('physical-dag.json',dag),('physical-plan.json',plan),('atom-program.json',atom),('event-trace.json',trace),('scenario.json',scenario),('device.json',d),('validation.json',report)]:save(folder/name,value)
    export_view(folder/'atom-program.json',folder/'full-viewer.html',trace_path=folder/'event-trace.json',device_path=folder/'device.json',report_path=folder/'validation.json')
    print(json.dumps({k:v for k,v in summary.items() if k!='pulse_details'}),flush=True)
    return summary

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',required=True);a=p.parse_args();out=ROOT/a.out
    build(out/'SE_DUAL_SIX',out/'compiled-modules')
