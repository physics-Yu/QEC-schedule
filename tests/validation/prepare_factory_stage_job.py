"""Prepare a reviewable R6 spec/manifest for R7; never dispatch or compile."""
from datetime import datetime
from hashlib import file_digest
import argparse,json,re
from pathlib import Path

root=Path(__file__).resolve().parents[2];kb=root/'knowledge/roles/R6';out=kb/'evidence/T605'
parser=argparse.ArgumentParser();parser.add_argument('--revision',required=True);args=parser.parse_args();revision=args.revision
if not re.fullmatch(r'v[2-9][0-9]*',revision):raise ValueError('A new v2+ revision is required; never replace frozen v1')
source=root/'scripts/outputs/T704/server/20261006T152602272401Z-r4-factory-first-stage-205/result/examples/atom/t405/factory-stage-v1'
def digest(p):
    with p.open('rb') as f:return file_digest(f,'sha256').hexdigest()
def save(p,v):p.write_bytes((json.dumps(v,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
roles={'input':'input.json.gz','physical_plan':'physical-plan.json.gz','execution':'execution.json.gz','observation':'enola-observation.json.gz','producer_status':'status.json'}
inputs={role:{'path':(source/name).relative_to(root).as_posix(),'byte_sha256':digest(source/name)} for role,name in roles.items()}
runner=root/'tests/validation/qualify_factory_stage_artifacts.py';manifest=out/f'factory-stage-input-manifest-{revision}.json';spec_path=kb/f'factory-stage-validation-job-spec-{revision}.json'
if manifest.exists() or spec_path.exists():raise ValueError('Do not overwrite an already prepared revision')
output_directory=f'knowledge/roles/R6/evidence/T605/factory-stage-validation-{revision}'
source_files=list((root/'src/na_pipeline/validation').glob('*.py'))+[runner]
save(manifest,{'schema_version':'R6FrozenFactoryStageInputs/0.1','owner':'R6','kb_revision':'kb-0006','created_at':datetime.now().astimezone().isoformat(),'inputs':inputs,'output_directory':output_directory,
 'verifier_source_byte_sha256':{p.relative_to(root).as_posix():digest(p) for p in source_files},
 'compile_calls':0,'search_calls':0,'source_scope':'first initialize stage only; no full factory or Shor qualification',
 'known_evidence_limit':'Original observer records router calls and source hashes but not raw router returns; report must retain this as unverified'})
spec={'schema_version':'r7-server-job/0.2','name':'r6-first-factory-stage-verification-'+revision,'purpose_id':'r6-first-factory-initialize-205-independent-verification','stage_kind':'validation',
 'argv':['{python}',runner.relative_to(root).as_posix(),'--manifest',manifest.relative_to(root).as_posix()],
 'budget':{'wall_seconds':3600,'memory_gib':24,'parallelism':1,'search_expansions':0},
 'budget_rationale':'Read only the exact frozen 205-atom, 1312-operation, 4906-action factory initialization artifacts. Previous five-window validation peaked at 2.8 GB RSS; reserve 24 GiB for the larger full-world geometry/state reconstruction and hashing. 3600 s wall, one process, no compilation/placement/search. R7 must verify current host resources and any same-purpose active job first.',
 'output_roots':[output_directory],
 'output_delivery':'R6 writes report/receipt under its own knowledge directory and emits one R6_VALIDATION_ARTIFACTS_JSON line in supervisor stdout. R7 exports that already-owned stdout artifact; R6 imports original JSON into its own evidence directory. No change to R7 output allowlist is required.'}
save(spec_path,spec)
read_paths=[v['path'] for v in inputs.values()]+[runner.relative_to(root).as_posix(),manifest.relative_to(root).as_posix()]
save(kb/f'factory-stage-validation-handoff-{revision}.json',{'schema_version':'R6R7JobHandoff/0.1','task_id':'T605','sender_role':'R6','receiver_role':'R7','status':'ready_for_R7_dispatch',
 'objective':'Independently verify the existing complete first factory stage, with zero recompilation and zero search',
 'kb_revision':'kb-0006','required_interface_versions':{'GOV-001':'0.4.1','IF-SERVER-JOB-001':'0.1.0','R7-T704-IF-001':'0.4.0-draft'},
 'read_paths':read_paths,'write_scope':'R6 validation/tests/knowledge; R7 owns dispatch/index/export logs',
 'job_spec':spec_path.relative_to(root).as_posix(),'spec_byte_sha256':digest(spec_path),'manifest':manifest.relative_to(root).as_posix(),'manifest_byte_sha256':digest(manifest),
 'deliverables':['frozen input/source hashes','full geometry/non-2q/trace/readout/live-data report','original Enola source and scheduler output comparison','explicit remaining router return-provenance gap'],
 'acceptance_checks':['use these exact five existing producer files','24 GiB, 3600 s, one process, zero search after current server preflight','no factory protocol restart or compilation','retain failures/unverified without inferring full program success'],
 'dependencies':['completed source job 20261006T152602272401Z-r4-factory-first-stage-205'],
 'unresolved_questions':[], 'original_source_job_untouched':True,'rerun_reason':'Verifier v1 required one direct move for every candidate. All 25 failures are actual continuous two-leg detours; candidate_motion_witness now checks complete ordered route chains. Regression still rejects missing/broken/overlapping/wrong-endpoint paths. Original report and input bytes retained; no compiler rerun.',
 'dispatch_argv':['scripts/.venv/Scripts/python.exe','scripts/server_pipeline_job.py','dispatch','--spec',spec_path.relative_to(root).as_posix(),*[part for p in read_paths for part in ('--input',p)]],
 'result_read_interface':'Read exported job stdout.log; use tests/validation/import_factory_stage_result.py --stdout PATH. Full original report is in R6_VALIDATION_ARTIFACTS_JSON.',
 'pre_dispatch_checks':'Verifier source is bound by manifest. If changed, do not bypass; compare reason and prepare a new reviewed manifest. R6 does not dispatch.'})
print(json.dumps({'status':'ready_for_R7_dispatch','spec':spec_path.relative_to(root).as_posix(),'inputs':len(inputs),'verifier_files':len(source_files)},ensure_ascii=False))
