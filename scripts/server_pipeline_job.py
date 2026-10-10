"""T704 frozen argv dispatch with fresh resources, explicit budgets and durable logs."""
from datetime import datetime, timezone
import argparse
import hashlib
import io
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tarfile

from remote_resources import probe
from server_strategy_job import remote, write, HOST

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'scripts/outputs/T704/server'
REMOTE_ROOT='/home/yyq/na-platform-simulation/R7/T704'
INDEX=OUT.parent/'job-index.json'
ACTIVE={'running','starting','dispatched_not_completed','unknown','reserved','dispatch_outcome_unknown'}


def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode('utf-8')).hexdigest()


def valid_output_roots(roots):
    if not isinstance(roots,list) or not roots:raise ValueError('JOB_OUTPUT_ROOTS_REQUIRED')
    result=[]
    for value in roots:
        if not isinstance(value,str) or '\\' in value:raise ValueError('JOB_OUTPUT_ROOT_INVALID')
        p=PurePosixPath(value)
        allowed=('scripts/outputs/T704','examples/atom','examples/physical','examples/scenarios','artifacts',*(f'knowledge/roles/R{i}/evidence' for i in range(9)))
        if p.is_absolute() or '..' in p.parts or ':' in value or not any(p.is_relative_to(a) for a in allowed):raise ValueError('JOB_OUTPUT_ROOT_ESCAPE: '+value)
        if value not in result:result.append(value)
    return result


def purpose(spec):
    # These two legacy names were explicitly identified by R0 as the same purpose.
    return spec.get('purpose_id') or ({'r4-full-resource-placement':'complete-resource-world','shor15-complete-world':'complete-resource-world'}.get(spec['name'],spec['name']))


def identity(spec,inventory):
    files={k:v for k,v in inventory.items() if k!='scripts/outputs/T704/job-spec.json'}
    return {'purpose_id':purpose(spec),'source_and_input_sha256':digest(files),'dependency_lock_sha256':files.get('third_party/enola/requirements.lock'),'budget_sha256':digest(spec['budget']),'exact_job_sha256':digest({'purpose':purpose(spec),'argv':spec['argv'],'budget':spec['budget'],'files':files})}


def refresh_index(live=False):
    records=[]
    for path in sorted(OUT.glob('*/dispatch.json')):
        d=json.loads(path.read_bytes());p=PurePosixPath(d['project'])
        if d.get('schema_version')!='r7-pipeline-dispatch/0.1' or not p.is_relative_to(REMOTE_ROOT):continue
        observed=path.with_name('observed-status.json')
        state=json.loads(observed.read_bytes()).get('status',{}) if observed.exists() else {}
        fetched=path.with_name('fetch-receipt.json')
        records.append({'job_id':d['job_id'],'dispatch':str(path.resolve()),'project':d['project'],'purpose_id':purpose(d['spec']),'spec':d['spec'],'identity':identity(d['spec'],d['snapshot_byte_sha256']),'status':state.get('status','unknown'),'observed':state,'fetch':json.loads(fetched.read_bytes()) if fetched.exists() else None})
    for path in sorted(OUT.glob('*/reservation.json')):
        if path.with_name('dispatch.json').exists():continue
        d=json.loads(path.read_bytes())
        records.append({'job_id':d['job_id'],'dispatch':str(path.resolve()),'project':d['project'],'purpose_id':purpose(d['spec']),'spec':d['spec'],'identity':d['identity'],'status':d['status'],'reservation':True,'observed':{'status':d['status'],'phase':d['phase']},'fetch':None})
    if live and records:
        states=remote('''import json
from pathlib import Path
result={}
for value in PROJECTS:
    p=Path(value)/'scripts/outputs/T704/job/status.json'
    result[value]=json.loads(p.read_bytes()) if p.is_file() else {'status':'unknown'}
print(json.dumps(result))
'''.replace('PROJECTS',repr([r['project'] for r in records])))
        for r in records:
            if r.get('reservation') and states[r['project']]['status']=='unknown':continue
            r['observed']=states[r['project']];r['status']=r['observed']['status']
            path=Path(r['dispatch']).with_name('observed-status.json')
            saved=json.loads(path.read_bytes()) if path.exists() else {}
            saved.update(status=r['observed'],status_observed_at_utc=datetime.now(timezone.utc).isoformat())
            write(path,saved)
    sources=INDEX.with_name('job-index-sources.json')
    for external in (json.loads(sources.read_bytes()).get('external_history',[]) if sources.exists() else []):
        paths={key:(ROOT/external[key]).resolve() for key in ('dispatch','status','job','result')}
        if any(not p.is_relative_to(ROOT) for p in paths.values()):raise ValueError('INDEX_EXTERNAL_PATH_ESCAPE')
        d=json.loads(paths['dispatch'].read_bytes());state=json.loads(paths['status'].read_bytes());job=json.loads(paths['job'].read_bytes())
        if d.get('schema_version')!='R6ServerValidationJob/0.1':raise ValueError('INDEX_EXTERNAL_SCHEMA_UNSUPPORTED')
        spec={'name':external['job_id'],'purpose_id':external['purpose_id'],'stage_kind':'validation','argv':job['command'],'budget':d['budget']}
        records.append({'job_id':external['job_id'],'dispatch':str(paths['dispatch']),'project':d['project'],'purpose_id':external['purpose_id'],'spec':spec,'identity':identity(spec,d['input_sha256']),'status':state['status'],'observed':state,'fetch':{'result':str(paths['result']),'managed_by':external['owner']},'external_history':True,'registration_reason':external['registration_reason'],'dispatch_sha256':hashlib.sha256(paths['dispatch'].read_bytes()).hexdigest()})
    collisions={key:[{'job_id':r['job_id'],'identity':r['identity'],'status':r['status']} for r in records if r['purpose_id']==key] for key in {r['purpose_id'] for r in records}}
    output={'schema_version':'r7-job-index/0.1','owner':'R7','updated_at_utc':datetime.now(timezone.utc).isoformat(),'live_status_refreshed':live,'jobs':records,'active_job_ids':[r['job_id'] for r in records if r['status'] in ACTIVE],'repeated_purposes':{k:v for k,v in collisions.items() if len(v)>1},'policy':'R7 only heavy dispatcher; component owners submit specs; differing identity is retained and never called identical'}
    temporary=INDEX.with_suffix('.tmp');write(temporary,output);os.replace(temporary,INDEX)
    return output


def validate_spec(spec):
    if spec.get('schema_version') not in {'r7-server-job/0.1','r7-server-job/0.2'}:raise ValueError('JOB_SPEC_SCHEMA_UNSUPPORTED')
    if not re.fullmatch('[a-z0-9][a-z0-9-]{0,55}',spec.get('name','')):raise ValueError('JOB_NAME_REQUIRED')
    if spec.get('stage_kind') not in {'environment_probe','logical_frontend','physical_templates','representative_compile','factory_t','full_shor','validation','viewer_export'}:raise ValueError('JOB_STAGE_REQUIRED')
    argv=spec.get('argv')
    if not isinstance(argv,list) or len(argv)<2 or argv[0]!='{python}' or any(not isinstance(a,str) or '\0' in a for a in argv):raise ValueError('JOB_PYTHON_ARGV_REQUIRED')
    if argv[1]=='-m' and len(argv)<3:raise ValueError('JOB_MODULE_NAME_REQUIRED')
    if argv[1] in {'-c','-'}:raise ValueError('JOB_FILE_OR_MODULE_ENTRY_REQUIRED')
    if argv[1]!='-m' and not (ROOT/argv[1]).resolve().is_relative_to(ROOT):raise ValueError('JOB_ENTRY_OUTSIDE_PROJECT')
    budget=spec.get('budget',{})
    for k in ('wall_seconds','memory_gib','parallelism','search_expansions'):
        v=budget.get(k)
        zero_allowed=k=='search_expansions' and spec.get('stage_kind')=='validation'
        if not isinstance(v,(int,float)) or isinstance(v,bool) or not math.isfinite(v) or (v<0 if zero_allowed else v<=0):raise ValueError('JOB_BUDGET_REQUIRED: '+k)
    if not isinstance(budget['parallelism'],int) or not isinstance(budget['search_expansions'],int):raise ValueError('JOB_INTEGER_BUDGET_REQUIRED')
    if not spec.get('budget_rationale'):raise ValueError('JOB_BUDGET_RATIONALE_REQUIRED')
    if not re.fullmatch('[a-z0-9][a-z0-9-]{0,80}',spec.get('purpose_id','')):raise ValueError('JOB_PURPOSE_REQUIRED')
    valid_output_roots(spec.get('output_roots'))


def snapshot(spec,inputs):
    selected=[ROOT/'pyproject.toml']
    selected+=sorted((ROOT/'src/na_pipeline').rglob('*.py'))
    selected+=sorted((ROOT/'scripts').glob('*.py'))
    selected+=sorted((ROOT/'viewer').glob('*.py'))
    selected+=[ROOT/'viewer'/name for name in ('viewer.html','viewer.js','viewer.css','hierarchy.html','hierarchy.js')]
    selected+=[ROOT/'third_party/enola'/name for name in ('pin.json','requirements.lock','dependency-sources.json')]
    selected+=sorted((ROOT/'third_party/enola/upstream/enola').rglob('*.py'))
    selected+=[ROOT/'third_party/enola/upstream'/name for name in ('LICENSE','README.md','run.py')]
    selected+=inputs
    frozen={}
    for p in selected:
        p=p.resolve()
        if not p.is_relative_to(ROOT):raise ValueError('SNAPSHOT_INPUT_OUTSIDE_PROJECT: '+str(p))
        frozen[p.relative_to(ROOT).as_posix()]=p.read_bytes()
    frozen['scripts/outputs/T704/job-spec.json']=(json.dumps(spec,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
    inventory={p:hashlib.sha256(raw).hexdigest() for p,raw in frozen.items()}
    frozen['scripts/outputs/T704/source-inventory.json']=json.dumps(inventory,indent=2).encode()
    # Detect concurrent writes before dispatch, including input bytes.
    for p in selected:
        if p.read_bytes()!=frozen[p.resolve().relative_to(ROOT).as_posix()]:raise ValueError('SOURCE_CHANGED_DURING_SNAPSHOT: '+str(p))
    return frozen,inventory


def dispatch(args):
    OUT.mkdir(parents=True,exist_ok=True)
    lock=OUT/'.dispatch.lock'
    try:fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    except FileExistsError as exc:raise ValueError('DISPATCH_LOCK_HELD: inspect '+str(lock)+'; no concurrent launch') from exc
    try:
        os.write(fd,json.dumps({'pid':os.getpid(),'started_at_utc':datetime.now(timezone.utc).isoformat(),'spec':str(args.spec)}).encode())
        try:return _dispatch(args)
        except Exception as exc:
            reservation=getattr(args,'reservation_path',None)
            if reservation is not None and reservation.exists():
                d=json.loads(reservation.read_bytes())
                if not reservation.with_name('dispatch.json').exists():
                    d.update(status='dispatch_outcome_unknown' if d['phase']=='launch_request' else 'failed_before_launch',error=str(exc))
                    write(reservation,d);refresh_index()
            raise
    finally:
        os.close(fd);lock.unlink()


def _dispatch(args):
    spec=json.loads(args.spec.read_bytes());validate_spec(spec)
    frozen,inventory=snapshot(spec,[p.resolve() for p in args.input])
    fingerprint=identity(spec,inventory)
    registry=refresh_index(live=True)
    for old in registry['jobs']:
        if old['identity']['exact_job_sha256']==fingerprint['exact_job_sha256'] and old['status'] in ACTIVE|{'completed'}:
            print(json.dumps({'status':'reuse_existing_job','dispatch':old['dispatch'],'existing_status':old['status'],'same_exact_identity':True,'new_execution_started':False},ensure_ascii=False));return
        if old['purpose_id']==purpose(spec) and old['status'] in ACTIVE:
            raise ValueError('ACTIVE_PURPOSE_DIFFERENT_IDENTITY: '+old['dispatch']+'; follow existing work; no duplicate dispatch')
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    job_id=stamp+'-'+spec['name'];local=OUT/job_id;local.mkdir(parents=True)
    preflight=probe();write(local/'preflight.json',preflight)
    if not preflight['connected']:raise RuntimeError('SERVER_UNREACHABLE: '+str(local/'preflight.json'))
    r=preflight['remote'];budget=spec['budget']
    if budget['parallelism']>r['cpu_affinity_count']:raise ValueError('BUDGET_EXCEEDS_CPU_AFFINITY')
    available=next(int(line.split()[1])*1024 for line in r['meminfo'].splitlines() if line.startswith('MemAvailable:'))
    if budget['memory_gib']*1024**3>available*.5:raise ValueError('BUDGET_EXCEEDS_HALF_SHARED_AVAILABLE_MEMORY')
    for limits in r.get('cgroup_ancestor_limits',{}).values():
        memory=limits.get('memory.max');cpu=limits.get('cpu.max')
        if isinstance(memory,str) and memory.isdigit() and budget['memory_gib']*1024**3>int(memory):raise ValueError('BUDGET_EXCEEDS_CGROUP_MEMORY')
        if isinstance(cpu,str) and not cpu.startswith('max'):
            quota,period=map(int,cpu.split())
            if budget['parallelism']>math.ceil(quota/period):raise ValueError('BUDGET_EXCEEDS_CGROUP_CPU')
    if sum(map(len,frozen.values()))*3>r['disk']['free']:raise ValueError('SNAPSHOT_DISK_SPACE_INSUFFICIENT')
    bundle=local/'source.tar.gz'
    with tarfile.open(bundle,'w:gz') as archive:
        for name,raw in frozen.items():
            info=tarfile.TarInfo(name);info.size=len(raw);info.mode=0o644;archive.addfile(info,io.BytesIO(raw))
    write(local/'source-inventory.json',inventory);write(local/'job-spec.json',spec)
    project=REMOTE_ROOT+'/'+job_id
    reservation={'schema_version':'r7-pipeline-reservation/0.1','job_id':job_id,'host':HOST,'project':project,'spec':spec,'identity':fingerprint,'status':'reserved','phase':'remote_setup','created_at_utc':datetime.now(timezone.utc).isoformat(),'snapshot_inventory':str(local/'source-inventory.json')}
    args.reservation_path=local/'reservation.json'
    with args.reservation_path.open('xb') as stream:stream.write((json.dumps(reservation,ensure_ascii=False,indent=2)+'\n').encode())
    refresh_index()
    remote('from pathlib import Path\nimport json\np=Path('+repr(project)+')\np.mkdir(parents=True,exist_ok=False)\nprint(json.dumps({"project":str(p)}))')
    subprocess.run(['scp','-q',str(bundle),HOST+':'+project+'/source.tar.gz'],check=True,timeout=60)
    reservation['phase']='launch_request';write(args.reservation_path,reservation)
    launch=remote('''from pathlib import Path
import hashlib,json,subprocess,sys,tarfile
root=Path(PROJECT)
expected=INVENTORY
with tarfile.open(root/'source.tar.gz') as archive:archive.extractall(root,filter='data')
for name,value in expected.items():
    p=(root/name).resolve()
    if not p.is_relative_to(root) or hashlib.sha256(p.read_bytes()).hexdigest()!=value:raise ValueError('SNAPSHOT_HASH_MISMATCH '+name)
b=BUDGET
command=[sys.executable,str(root/'scripts/jobs.py'),'launch','--job-dir',str(root/'scripts/outputs/T704/job'),'--wall-seconds',str(b['wall_seconds']),'--memory-gib',str(b['memory_gib']),'--parallelism',str(b['parallelism']),'--search-expansions',str(b['search_expansions']),'--',sys.executable,str(root/'scripts/remote_pipeline_worker.py')]
r=subprocess.run(command,cwd=root,capture_output=True,text=True)
if r.returncode:raise RuntimeError(r.stderr)
print(json.dumps({'dispatch':json.loads(r.stdout),'python':sys.version,'snapshot_files_verified':len(expected)}))
'''.replace('PROJECT',repr(project)).replace('INVENTORY',repr(inventory)).replace('BUDGET',repr(budget)))
    record={'schema_version':'r7-pipeline-dispatch/0.1','host':HOST,'project':project,'job_id':job_id,'spec':spec,'preflight':str(local/'preflight.json'),'snapshot_byte_sha256':inventory,'bundle_sha256':hashlib.sha256(bundle.read_bytes()).hexdigest(),'launch':launch,'status':'dispatched_not_completed','full_program_passed':False,'search_budget_enforcement':'recorded environment; producer enforcement must be separately evidenced'}
    write(local/'dispatch.json',record)
    reservation.update(status='dispatched_not_completed',phase='launch_confirmed');write(args.reservation_path,reservation)
    refresh_index()
    print(json.dumps({'dispatch':str(local/'dispatch.json'),'remote_project':project,'status':record['status']},ensure_ascii=False))


def fetch_outputs(dispatch_path,record,extra_roots=()):
    roots=valid_output_roots(['scripts/outputs/T704',*record['spec'].get('output_roots',[]),*extra_roots])
    # Fetch is a packaging operation over the existing checkout, never a rerun.
    result=remote('''from pathlib import Path
import hashlib,json,tarfile
root=Path(PROJECT).resolve()
def digest(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()
files={}
missing=[]
omitted_frozen_inputs={}
inventory_path=root/'scripts/outputs/T704/source-inventory.json'
inventory=json.loads(inventory_path.read_bytes()) if inventory_path.is_file() else {}
for rel in ROOTS:
    target=(root/rel).resolve()
    if not target.is_relative_to(root):raise ValueError('OUTPUT_ROOT_ESCAPE')
    if not target.exists():missing.append(rel);continue
    candidates=sorted(target.rglob('*')) if target.is_dir() else [target]
    for p in candidates:
        if not p.is_file():continue
        if not p.resolve().is_relative_to(root):raise ValueError('OUTPUT_SYMLINK_ESCAPE')
        relative=p.relative_to(root).as_posix()
        if any(s in p.relative_to(root).parts for s in ('pip-cache','temporary')) or p.suffix=='.whl':continue
        actual=digest(p)
        if rel=='scripts/outputs/T704' and relative.startswith('scripts/outputs/T704/server/') and inventory.get(relative)==actual:
            omitted_frozen_inputs[relative]=actual
            continue
        archive_name='T704/'+relative[len('scripts/outputs/T704/'):] if relative.startswith('scripts/outputs/T704/') else relative
        files[archive_name]={'source_relative':relative,'sha256':actual,'bytes':p.stat().st_size}
if missing:raise ValueError('DECLARED_OUTPUT_ROOT_MISSING: '+repr(missing))
manifest={'schema_version':'r7-output-export/0.1','roots':ROOTS,'files':files,'omitted_unchanged_nested_inputs':omitted_frozen_inputs}
identity=hashlib.sha256(json.dumps(manifest,sort_keys=True,separators=(',',':')).encode()).hexdigest()
archive=root/('result-'+identity[:20]+'.tar.gz')
if not archive.exists():
    import io
    temporary=archive.with_suffix('.partial')
    with tarfile.open(temporary,'w:gz') as a:
        for name,item in files.items():a.add(root/item['source_relative'],arcname=name,recursive=False)
        data=(json.dumps(manifest,indent=2)+'\\n').encode();info=tarfile.TarInfo('export-manifest.json');info.size=len(data);a.addfile(info,io.BytesIO(data))
    temporary.replace(archive)
print(json.dumps({'archive':str(archive),'sha256':digest(archive),'identity':identity,'file_count':len(files)}))
'''.replace('PROJECT',repr(record['project'])).replace('ROOTS',repr(roots)), timeout=600)
    target=dispatch_path.parent/PurePosixPath(result['archive']).name
    if not target.exists() or hashlib.sha256(target.read_bytes()).hexdigest()!=result['sha256']:
        subprocess.run(['scp','-q',HOST+':'+result['archive'],str(target)],check=True,timeout=600)
    if hashlib.sha256(target.read_bytes()).hexdigest()!=result['sha256']:raise ValueError('FETCH_HASH_MISMATCH')
    destination=(dispatch_path.parent/'result').resolve();destination.mkdir(exist_ok=True)
    # Frozen inputs may themselves be nested fetched artifacts. Preserve their
    # original paths on Windows without changing system-wide long-path policy.
    io_destination=destination
    if os.name=='nt' and not str(destination).startswith('\\\\?\\'):
        value=str(destination)
        io_destination=Path('\\\\?\\UNC\\'+value[2:] if value.startswith('\\\\') else '\\\\?\\'+value)
    with tarfile.open(target) as archive:archive.extractall(io_destination,filter='data')
    manifest=json.loads((io_destination/'export-manifest.json').read_bytes())
    for name,item in manifest['files'].items():
        p=(io_destination/name).resolve()
        if not p.is_relative_to(io_destination.resolve()) or hashlib.sha256(p.read_bytes()).hexdigest()!=item['sha256']:raise ValueError('FETCH_FILE_HASH_MISMATCH: '+name)
    receipt={'sha256':result['sha256'],'archive':target.name,'result':str(destination),'output_roots':roots,'export_identity':result['identity'],'file_count':result['file_count'],'all_output_bytes_verified':True}
    write(dispatch_path.parent/'fetch-receipt.json',receipt)
    return receipt


def status(args):
    record=json.loads(args.dispatch.read_bytes());project=record['project']
    if record.get('schema_version') not in {'r7-pipeline-dispatch/0.1','r7-pipeline-reservation/0.1'} or not PurePosixPath(project).is_relative_to(REMOTE_ROOT):raise ValueError('REMOTE_PROJECT_OUT_OF_SCOPE')
    argv=record['spec']['argv']
    primary=argv[argv.index('--out')+1] if '--out' in argv else 'scripts/outputs/T704/run'
    valid_output_roots([primary])
    state=remote('''from pathlib import Path
import hashlib,json
r=Path(PROJECT)/'scripts/outputs/T704'
def read(p):return json.loads(p.read_bytes()) if p.is_file() else None
j=r/'job'
output=(Path(PROJECT)/PRIMARY).resolve()
if not output.is_relative_to(Path(PROJECT).resolve()):raise ValueError('STATUS_OUTPUT_ESCAPE')
def pin(p):
    if not p.is_file():return None
    h=hashlib.sha256()
    with p.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return {'name':p.name,'bytes':p.stat().st_size,'sha256':h.hexdigest()}
progress=None
if (output/'protocol.json.gz').exists():
    ledger=read(output/'factory-ledger.json') or {}
    progress={'source_output_root':PRIMARY,'producer_status':read(output/'status.json'),'committed_stage_receipts':[pin(p) for p in sorted(output.glob('*-receipt.json'))],
              'ledger':pin(output/'factory-ledger.json'),'checkpoint':pin(output/'checkpoint.json.gz'),'failed_prefix':pin(output/'failed-prefix.json.gz'),
              'ledger_stage_id':ledger.get('stage_id'),'terminal':ledger.get('terminal'),'token':ledger.get('token'),'full_program_passed':False}
pipeline_progress=None
if (output/'current-phase.json').is_file():
    pipeline_progress={'current_phase':read(output/'current-phase.json'),
                       'artifact_file_counts':{name:sum(p.is_file() for p in (output/name).rglob('*')) for name in ('windows','history','decisions','strategies','factory','compiler-evidence')},
                       'checkpoint':pin(output/'checkpoint.json.gz'),'failed_prefix':pin(output/'failed-prefix.json.gz'),
                       'incomplete':read(output/'incomplete.json'),'scope':'read-only published progress; not domain validation','full_program_passed':False}
print(json.dumps({'status':read(j/'status.json'),'worker':read(r/'worker-receipt.json'),'pipeline':read(output/'manifest.json') or read(output/'status.json'),'factory_progress':progress,'pipeline_progress':pipeline_progress,'stdout_tail':(j/'stdout.log').read_text(errors='replace')[-3000:] if (j/'stdout.log').exists() else '', 'stderr_tail':(j/'stderr.log').read_text(errors='replace')[-3000:] if (j/'stderr.log').exists() else ''}))
'''.replace('PROJECT',repr(project)).replace('PRIMARY',repr(primary)))
    write(args.dispatch.parent/'observed-status.json',state)
    display={**state,'pipeline':{k:v for k,v in (state.get('pipeline') or {}).items() if k not in {'source_byte_sha256','files','strategy_refs','factory_ledgers','inputs'}}}
    if 'coverage' in display['pipeline']:
        display['pipeline']['coverage']={k:v for k,v in display['pipeline']['coverage'].items() if k!='static_source_coverage'}
    print(json.dumps(display,ensure_ascii=False,indent=2))
    if args.fetch and (state.get('status') or {}).get('status') not in {'running','starting','dispatched_not_completed',None}:
        print(json.dumps(fetch_outputs(args.dispatch,record,args.output_root),ensure_ascii=False))
    refresh_index()


def main():
    parser=argparse.ArgumentParser();sub=parser.add_subparsers(dest='mode',required=True)
    p=sub.add_parser('dispatch');p.add_argument('--spec',type=Path,required=True);p.add_argument('--input',type=Path,action='append',default=[])
    p=sub.add_parser('status');p.add_argument('--dispatch',type=Path,required=True);p.add_argument('--fetch',action='store_true');p.add_argument('--output-root',action='append',default=[])
    p=sub.add_parser('index');p.add_argument('--live',action='store_true')
    args=parser.parse_args()
    if args.mode=='index':
        result=refresh_index(args.live);print(json.dumps({'index':str(INDEX),'jobs':len(result['jobs']),'active':result['active_job_ids']},ensure_ascii=False))
    elif args.mode=='dispatch':dispatch(args)
    else:status(args)


if __name__=='__main__':main()
