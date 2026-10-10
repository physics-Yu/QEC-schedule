"""Qualify a stopped order-only cache miss, then resume that exact checkpoint."""
from pathlib import Path
import argparse,gzip,json,hashlib,subprocess,sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts'),str(ROOT)]
from basic_shor_job import build_world
from na_pipeline.runtime import LogicalGateLibrary,run,make_scenario
from na_pipeline.runtime.component_pipeline import ComponentPipeline
from na_pipeline.runtime.compilation_guard import CompilationGuard,UnexpectedCompilation
from na_pipeline.runtime.fragment_order_binding import OrderInvariantModuleLibrary
from na_pipeline.runtime.pipeline import save_artifact
from na_pipeline.validation.dag_physical import validate_physical_plan
from na_pipeline.validation.dag_core import DAGAudit
from na_pipeline.validation.dag_session import inspect_window_binding


def read(path):
    raw=path.read_bytes();return json.loads(gzip.decompress(raw) if path.suffix=='.gz' else raw)


def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--component-source',type=Path,required=True);a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True)
    tests=[sys.executable,'-m','unittest','discover','-s','tests/runtime','-p','test_fragment_order_binding.py','-v']
    with (a.out/'regression.log').open('w') as log:
        rc=subprocess.call(tests,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
    if rc:raise ValueError('ORDER_BINDING_REGRESSION_FAILED')
    frozen=read(a.run/'world.json.gz');world=build_world()
    if world!=frozen:raise ValueError('RESUME_WORLD_CHANGED')
    violation=read(a.run/'execute/compilation-violation.json.gz')
    modules=a.run/'recipes/modules'
    leaf=OrderInvariantModuleLibrary(world['device'],directory=modules)
    with CompilationGuard() as guard:
        plan=leaf.get_or_build(violation['fragment'],violation['world'],instance_id='first-miss-replay',build_missing=False)
    trace=run(plan['atom_program'],make_scenario(plan['atom_program']),world['device'])
    report=validate_physical_plan(plan,world['device'],trace=trace)
    if not report['passed']:raise ValueError(report['failures'])
    for name,data in [('fragment-plan.json.gz',plan),('fragment-validation.json',report),('fragment-guard.json',guard.receipt())]:
        save_artifact(a.out/name,data)
    library=LogicalGateLibrary(world['device'],connection_directory=modules,allow_connection_planning=False)
    library.import_directory(a.component_source)
    checkpoint=read(a.run/'execute/checkpoint.json.gz')
    # Uses the existing execution root and exact original checkpoint. No state
    # is copied into another execution and no identity checks are bypassed.
    driver=ComponentPipeline.restore(world,a.run/'execute',checkpoint,compiler=library)
    graph=driver.factory.next_graph()
    with CompilationGuard() as guard:
        prepared=library.prepare_dags('factory.finish_04',driver.session,[graph])
    plan=prepared['physical_plan'];atom=prepared['atom_program']
    report=validate_physical_plan(plan,world['device'])
    if report['failures']:raise ValueError(report['failures'])
    audit=DAGAudit('restored_finish04_binding',{},fixture=False)
    inspect_window_binding(audit,plan,atom,prepared['context'],driver.session.results,driver.session.run_id)
    if not audit.report()['passed']:raise ValueError(audit.report())
    stats=library.stats
    if any(stats['module_stats'][k] for k in ('leaf_compile_count','placement_search_count','routing_search_count','frontier_search_count')):
        raise ValueError('REPAIR_RECOMPILED')
    for name,data in [('stage-plan.json.gz',plan),('stage-static-validation.json',report),('stage-binding-validation.json',audit.report()),('stage-guard.json',guard.receipt())]:
        save_artifact(a.out/name,data)
    repair={'schema_version':'FragmentOrderRepair/0.1','passed':True,'stage':'factory.finish_04',
        'checkpoint_windows':driver.window_count,'fragment_original_hash':plan.get('module_binding',{}).get('module_hash'),
        'fragment_order_bindings':leaf.order_bindings,'whole_stage_order_bindings':library.adapter.connections.order_bindings,
        'source_changed':False,'batch_membership_changed':False,'motion_replanned':False,
        'stats':stats,'resumed_from_same_execution_root':str(a.run.resolve()),'whole_stage_executed_by_probe':False}
    stop=a.run/'stops/order-miss-v5';stop.mkdir(parents=True,exist_ok=True);saved={}
    for name in ['status.json','execute/compilation-violation.json.gz','execute/compilation-guard.json','execute/compiler-stats.json','execute/checkpoint.json.gz','execute/stopped-summary.json']:
        source=a.run/name
        if not source.exists():continue
        raw=source.read_bytes();target=stop/name;target.parent.mkdir(parents=True,exist_ok=True)
        if target.exists() and target.read_bytes()!=raw:raise ValueError('STOP_EVIDENCE_REDEFINED')
        target.write_bytes(raw);saved[name]=hashlib.sha256(raw).hexdigest()
    repair['preserved_stop_evidence']=saved
    save_artifact(a.out/'repair.json',repair);save_artifact(a.run/'order-repair.json',repair)
    print(json.dumps({k:repair[k] for k in ('passed','checkpoint_windows','fragment_order_bindings','whole_stage_order_bindings','source_changed','motion_replanned')}),flush=True)
    return subprocess.call([sys.executable,str(ROOT/'scripts/basic_shor_job.py'),'--out',str(a.run),'--mode','execute',
                            '--component-source',str(a.component_source)],cwd=ROOT)


if __name__=='__main__':raise SystemExit(main())
