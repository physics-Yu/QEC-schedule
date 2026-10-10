"""One frozen full component/factory build, then actual parallel examples."""
from pathlib import Path
import argparse,hashlib,json,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT),str(ROOT/'scripts')]
from component_gallery_job import save,fixture_world


def examples(out):
    from joint_encoder_job import encoder_dag,metrics
    from na_pipeline.qec.factory_primitives import css_encoder
    from na_pipeline.validation.raw_encoder import certify_encoder
    from na_pipeline.backend import LogicalComponentCompiler
    from na_pipeline.device import canonical_surface17_device
    from na_pipeline.runtime import run,make_scenario
    from na_pipeline.validation.dag_physical import validate_physical_plan
    from viewer import export_view
    device=canonical_surface17_device();rows=[]
    for key,blocks,mixed in [('RAW_A_SINGLE',['W0'],False),('RAW_A_FOUR',['W0','W1','W2','W3'],False),('RAW_A_WITH_SE',['W0','W1','W2','W3'],True)]:
        folder=out/'parallel-examples'/key;folder.mkdir(parents=True,exist_ok=True)
        dag=encoder_dag(css_encoder(),blocks,mixed=mixed)
        for q in dag['qubits']:q['aod_group']='data' if q['id'].startswith('D/') else 'magic'
        world=fixture_world(dag['qubits'],device);compiler=LogicalComponentCompiler(device,budget={'max_operations':100000,'max_wall_seconds':1800},module_directory=out/'compiled-modules')
        compiler.build_dependencies(dag,world);before=compiler.modules.stats
        plan=compiler.compose_recipe(dag,world);atom=plan['atom_program'];scenario=make_scenario(atom);trace=run(atom,scenario,device)
        report=validate_physical_plan(plan,device,trace=trace)
        if not report['passed'] or report['unverified']:raise ValueError(report)
        if any(compiler.modules.stats[k]!=before[k] for k in ('frontier_search_count','leaf_compile_count','routing_search_count')):raise ValueError('EXAMPLE_BIND_SEARCHED')
        summary={'status':'passed','id':key,**metrics(plan),'signed_encoder':certify_encoder(css_encoder()),
                 'physical_operations':len(dag['nodes']),'atom_count':len(world['atoms']),'action_count':len(atom['actions']),
                 'source_CX_depth':4,'hardware_optimality_claimed':False,'user_visual_acceptance':'pending'}
        for name,value in [('physical-dag.json',dag),('physical-plan.json',plan),('atom-program.json',atom),('event-trace.json',trace),('scenario.json',scenario),('device.json',device),('summary.json',summary),('validation.json',report)]:save(folder/name,value)
        export_view(folder/'atom-program.json',folder/'full-viewer.html',trace_path=folder/'event-trace.json',device_path=folder/'device.json',report_path=folder/'validation.json')
        rows.append(summary);save(out/'parallel-examples/status.json',{'status':'running','cases':rows})
    from dual_array_se_job import build
    rows.append(build(out/'parallel-examples'/'SE_DUAL_SIX',out/'compiled-modules'))
    save(out/'parallel-examples/status.json',{'status':'passed','cases':rows})


def main():
    p=argparse.ArgumentParser();p.add_argument('--out',required=True);a=p.parse_args();out=ROOT/a.out
    import aod_held_components_job
    sys.argv=[sys.argv[0],'--out',a.out,'--workers','4'];aod_held_components_job.main()
    from audit_cnot_cohorts import audit
    audit(out)
    examples(out)
    import frame_continuation_job
    store=out/'compiled-modules';manifest={'source':str(store),'files':{f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in store.glob('*.json')}}
    save(out/'frame-module-input.json',manifest)
    sys.argv=[sys.argv[0],'--out',(out/'frame-continuations').relative_to(ROOT).as_posix(),'--module-source',str(store),'--module-manifest',(out/'frame-module-input.json').relative_to(ROOT).as_posix()]
    frame_continuation_job.main();audit(out)
    from audit_joint_factory import audit as audit_joint
    audit_joint(out, ROOT/'artifacts/demos/frame-cnot-cohorts-20261008')
    save(out/'residency-and-frame-complete.json',{'status':'passed','joint_frontier':True,'frames':7,'parallel_examples':4,'user_visual_acceptance':'pending','full_shor_executed':False})

if __name__=='__main__':main()
