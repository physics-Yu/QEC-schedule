"""Package T704 component evidence without promoting it to complete Shor."""
import argparse
import hashlib
import importlib
import json
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
NODE=Path('C:/Users/yuyqp/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe')
def read(p):return json.loads(Path(p).read_bytes())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(p,obj):Path(p).write_bytes((json.dumps(obj,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))


def verify_job(path):
    dispatch=read(path/'dispatch.json');fetch=read(path/'fetch-receipt.json')
    if sha(path/fetch.get('archive','result.tar.gz'))!=fetch['sha256']:raise ValueError('FETCH_ARCHIVE_MISMATCH')
    run=path/'result/T704/run';manifest=read(run/'manifest.json');worker=read(path/'result/T704/worker-receipt.json')
    if not worker.get('source_snapshot_stable') or not manifest.get('source_snapshot_stable'):raise ValueError('SOURCE_NOT_STABLE')
    for receipt in manifest['files'].values():
        if sha(run/receipt['path'])!=receipt['byte_sha256']:raise ValueError('MANIFEST_BYTE_MISMATCH: '+receipt['path'])
    return {'dispatch':str(path/'dispatch.json'),'run':str(run),'manifest':str(run/'manifest.json'),'manifest_sha256':sha(run/'manifest.json'),'source_bundle_sha256':dispatch['bundle_sha256'],'status':manifest['status'],'stage_wall_seconds':manifest['stage_wall_seconds'],'budget':dispatch['spec']['budget'],'supervisor':read(path/'result/T704/job/status.json'),'source_snapshot_stable':True,'input_bytes_verified':True},run


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--prepare',type=Path,required=True);parser.add_argument('--lower',type=Path,required=True);parser.add_argument('--world',type=Path);parser.add_argument('--checks',type=Path,required=True);args=parser.parse_args()
    prepare,prepared=verify_job(args.prepare);lower,lowered=verify_job(args.lower)
    from viewer.bundle import load_bundle
    world_record=None
    if args.world:world_record,world_run=verify_job(args.world)
    bundle_path=(world_run if args.world else lowered)/'bundle.json'
    _,values,bundle_receipt=load_bundle(bundle_path)
    from viewer.hierarchy import export_hierarchy
    viewer=ROOT/'viewer/t704-shor15-hierarchy.html';export=export_hierarchy(bundle_path,viewer)
    dom=json.loads(subprocess.check_output([str(NODE),str(ROOT/'scripts/check_hierarchy_logic.js'),str(viewer)],text=True,encoding='utf-8'))
    out=ROOT/'scripts/outputs/T704';write(out/'hierarchy-dom.json',dom)
    required={'na_pipeline.qec':['build_physical_dag_bundle','materialize_physical_node','materialize_factory_protocol'],'na_pipeline.runtime':['LogicalListScheduler','EventSession'],'na_pipeline.backend':['place_logical_dag','compile_physical_dag']}
    available={name:{fn:callable(getattr(importlib.import_module(name),fn,None)) for fn in functions} for name,functions in required.items()}
    write(out/'public-api-probe.json',available)
    physical=values['physical_dag_bundle'];resource=values['resource_requirements'];placement=values['patch_placement']
    receipt={'schema_version':'r7-t704-progress/0.1','created_at_utc':datetime.now(timezone.utc).isoformat(),'kb_revision':'kb-0006','plan_revision':'plan-0008','status':'frontend_placement_and_shared_physical_library_delivered_execution_pending',
             'server_jobs':{'prepare':prepare,'lower':lower,'world':world_record},'bundle_receipt':bundle_receipt,
             'logical_nodes':len(values['logical_dag']['nodes']),'phase_rounds':len(values['logical_dag']['rounds']),
             'physical_specification_count':len(physical['specifications']),'instance_coverage':{k:v for k,v in physical['coverage'].items() if k!='static_source_coverage'},
             'positioned_algorithm_atoms':sum(a.get('patch_id') in {p['patch_id'] for p in values['logical_dag']['patches']} for a in values['initial_state']['atoms']),'positioned_atoms':len(values['initial_state']['atoms']),'required_complete_world_atoms':resource['physical_qubit_count'],'resource_counts':resource['counts'],
             'placement_cost':placement['cost'],'placement_search':placement['search'],'complete_world_placed':set(a['qubit_id'] for a in values['initial_state']['atoms'])==set(resource['physical_qubit_ids']),
             'viewer':export,'dom_logic':dom,'tooling_checks':read(args.checks),'public_api_snapshot':available,
             'missing_pipeline':['D05: integrated qualification of relative/absolute clock and published guard','same-world PhysicalPlan/EventSession/LogicalSchedule artifacts','factory lifecycle and full eight-round fake path','independent full-program R6 qualification'],
             'physical_dag_bundle_mapping':'original R3 bundle preserved; formal shared templates are not passed as executed physical_dags',
             'full_program_passed':False,'runtime_executed':False,'quantum_state_simulated':False,'hardware_executed':False,'user_visual_acceptance':'pending','browser_render_check':'not_performed_prior_file_protocol_policy'}
    write(out/'delivery.json',receipt)
    print(json.dumps({k:receipt[k] for k in ['status','logical_nodes','phase_rounds','physical_specification_count','positioned_atoms','required_complete_world_atoms','full_program_passed']},ensure_ascii=False))


if __name__=='__main__':main()
