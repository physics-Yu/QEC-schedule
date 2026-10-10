"""Freeze the newly produced archived session artifacts for R7 dispatch only."""
from datetime import datetime
from hashlib import file_digest
import json
from pathlib import Path

root=Path(__file__).resolve().parents[2];kb=root/'knowledge/roles/R6';out=kb/'evidence/T605';current=root/'examples/scenarios/T505-dag-session-chunked-v1';old=root/'examples/scenarios/T505-dag-session-v1'
def digest(path):
    with path.open('rb') as f:return file_digest(f,'sha256').hexdigest()
def save(path,value):
    if path.exists():raise ValueError('Refusing to replace a prepared frozen artifact: '+str(path))
    path.write_bytes((json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
paths={f'window_{i}':current/f'window-{i:03}.json.gz' for i in range(5)}
paths.update({f'compiled_window_{i}':old/f'window-{i:03}.json.gz' for i in range(5)})
paths.update({f'history_{i}':current/'history'/f'window-{i:03}.json.gz' for i in range(5)})
paths.update({role:old/name for role,name in [('device','device.json.gz'),('logical_dag','logical-dag.json.gz'),('placement','patch-placement.json.gz'),('physical_bundle','physical-bundle.json.gz')]})
paths.update({role:current/name for role,name in [('event_trace','event-trace.json.gz'),('logical_schedule','logical-schedule.json.gz'),('producer_receipt','receipt.json')]})
runner=root/'tests/validation/qualify_chunked_session_artifacts.py';manifest=out/'chunked-session-input-manifest-v1.json';spec_path=kb/'chunked-session-validation-job-spec-v1.json';output='knowledge/roles/R6/evidence/T605/chunked-session-validation-v1'
inputs={role:{'path':p.relative_to(root).as_posix(),'byte_sha256':digest(p)} for role,p in paths.items()}
source_files=list((root/'src/na_pipeline/validation').glob('*.py'))+[runner]
save(manifest,{'schema_version':'R6FrozenChunkedSessionInputs/0.1','owner':'R6','kb_revision':'kb-0006','created_at':datetime.now().astimezone().isoformat(),'inputs':inputs,'verifier_source_byte_sha256':{p.relative_to(root).as_posix():digest(p) for p in source_files},'output_directory':output,'recompile':False,'search_calls':0,'scope':'actual five-window archived session, not full Shor or factory qualification'})
spec={'schema_version':'r7-server-job/0.2','name':'r6-chunked-five-window-verification','purpose_id':'r6-chunked-five-window-independent-verification','stage_kind':'validation','argv':['{python}',runner.relative_to(root).as_posix(),'--manifest',manifest.relative_to(root).as_posix()],
 'budget':{'wall_seconds':1800,'memory_gib':12,'parallelism':1,'search_expansions':0},'budget_rationale':'Previous exact five-window full geometry validation used 2.8 GB peak root RSS and 26 s verifier time. Retain 12 GiB/1800 s for the same unchanged compiled windows plus five archived event chunks, exact chain/dedup/state-boundary checks and current fake reexecution. No compiler, placer, runtime replay or search. R7 owns fresh shared-server quota checks and avoids active duplicate purpose.','output_roots':[output]}
save(spec_path,spec)
extra=[record['path'] for record in inputs.values()]+[runner.relative_to(root).as_posix(),manifest.relative_to(root).as_posix()]
save(kb/'chunked-session-validation-handoff-v1.json',{'schema_version':'R6R7JobHandoff/0.1','task_id':'T605','sender_role':'R6','receiver_role':'R7','status':'ready_for_R7_dispatch','objective':'Verify complete R5 archived five-window source/geometry/causality from unchanged compiled windows','kb_revision':'kb-0006','required_interface_versions':{'R5-HISTORY-001':'0.1.0-draft','R7-T704-IF-001':'0.4.0-draft','IF-SERVER-JOB-001':'0.1.0'},'job_spec':spec_path.relative_to(root).as_posix(),'spec_byte_sha256':digest(spec_path),'manifest':manifest.relative_to(root).as_posix(),'manifest_byte_sha256':digest(manifest),'read_paths':extra,'write_scope':'R6 evidence; R7 owns dispatch/index/export','deliverables':['full-source physical-session report','all-history byte chain and dedup verification','frozen input/code/resource receipt'],'acceptance_checks':['every chunk must be read and byte/chain checked','archived and live duplicate records agree exactly','all 2111 actions retained; not only 64 active retained producer events','same original source windows, no recompile/search','full_program_passed remains false for this component'],'dependencies':['R5 T505-dag-session-chunked-v1 completed reexecution receipt'],'unresolved_questions':[],'dispatch_argv':['scripts/.venv/Scripts/python.exe','scripts/server_pipeline_job.py','dispatch','--spec',spec_path.relative_to(root).as_posix(),*[part for p in extra for part in ('--input',p)]],'result_read_interface':output+'/report.json and receipt.json, fetched into R7 result; R6 copies exact bytes after checking manifest'})
print(json.dumps({'status':'ready_for_R7_dispatch','spec':spec_path.relative_to(root).as_posix(),'inputs':len(inputs),'verifier_files':len(source_files)},ensure_ascii=False))
