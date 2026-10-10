"""R6-owned frozen verification job; consumes R7 read-only probe/supervisor.

Never writes the shared R7 source/output directories or runs a compiler.
"""
from datetime import datetime,timezone
from hashlib import sha256
import argparse,io,json,subprocess,sys,tarfile
from pathlib import Path,PurePosixPath

root=Path(__file__).resolve().parents[2]; out=root/'knowledge/roles/R6/evidence/T605'; host='yyq@10.133.24.178'


def remote(code):
    r=subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=10',host,'python3','-'],input=code,text=True,capture_output=True,encoding='utf-8',timeout=45)
    if r.returncode: raise RuntimeError(r.stderr+'\n'+r.stdout)
    return json.loads(r.stdout)


def save(path,data): path.write_bytes((json.dumps(data,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))


def launch():
    raise RuntimeError('GOV-001/0.4.1: new heavy jobs must be dispatched by R7; this shim is retained only for historical status/fetch')
    sys.path.insert(0,str(root/'scripts'))
    from remote_resources import probe
    preflight=probe()
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    local=out/('server-session-'+stamp); local.mkdir(parents=True,exist_ok=False); save(local/'preflight.json',preflight)
    if not preflight['connected']: raise RuntimeError('Server unavailable; preflight evidence preserved')
    files=list((root/'src/na_pipeline').rglob('*.py'))+[root/'scripts/jobs.py',root/'pyproject.toml',Path(__file__),root/'tests/validation/qualify_session_artifacts.py']
    files+=list((root/'viewer').glob('*.py'))
    for base in ('T505-dag-session-v1','T505-dag-session-fixed-runtime'):
        directory=root/'examples/scenarios'/base
        files+=list(directory.glob('window-*.json.gz'))+[directory/'receipt.json',directory/'logical-schedule.json.gz',directory/'event-trace.json.gz']
    files+=[root/'examples/scenarios/T505-dag-session-v1'/name for name in ('device.json.gz','logical-dag.json.gz','patch-placement.json.gz','physical-bundle.json.gz')]
    frozen={p.relative_to(root).as_posix():p.read_bytes() for p in dict.fromkeys(files)}
    manifest={name:sha256(data).hexdigest() for name,data in frozen.items()}
    package=local/'frozen-verifier-inputs.tar.gz'
    with tarfile.open(package,'w:gz',compresslevel=1) as archive:
        for name,data in frozen.items():
            item=tarfile.TarInfo(name); item.size=len(data); item.mode=0o644; archive.addfile(item,io.BytesIO(data))
    project='/home/yyq/na-platform-simulation/R6/T605/'+stamp
    remote("from pathlib import Path\nimport json\np=Path("+repr(project)+")\np.mkdir(parents=True,exist_ok=False)\nprint(json.dumps({'created':str(p)}))")
    subprocess.run(['scp','-q',str(package),host+':'+project+'/frozen-verifier-inputs.tar.gz'],check=True,timeout=120)
    launch_code="""from pathlib import Path
import hashlib,json,subprocess,sys,tarfile
root=Path(PROJECT)
with tarfile.open(root/'frozen-verifier-inputs.tar.gz') as f:f.extractall(root,filter='data')
expected=MANIFEST
for name,value in expected.items():
 p=(root/name).resolve()
 if not p.is_relative_to(root) or hashlib.sha256(p.read_bytes()).hexdigest()!=value:raise ValueError('Frozen input identity mismatch: '+name)
command=[sys.executable,str(root/'scripts/jobs.py'),'launch','--job-dir',str(root/'knowledge/roles/R6/evidence/T605/job-server'),'--wall-seconds','1800','--memory-gib','12','--parallelism','1','--search-expansions','1','--',sys.executable,str(root/'tests/validation/qualify_session_artifacts.py')]
p=subprocess.run(command,cwd=root,text=True,capture_output=True)
if p.returncode:raise RuntimeError(p.stderr)
print(json.dumps({'python':sys.version,'verified_files':len(expected),'dispatch':json.loads(p.stdout)}))
""".replace('PROJECT',repr(project)).replace('MANIFEST',repr(manifest))
    result=remote(launch_code)
    receipt={'schema_version':'R6ServerValidationJob/0.1','host':host,'project':project,'local_directory':str(local),'budget':{'wall_seconds':1800,'memory_gib':12,'parallelism':1,'search_calls':0},'rationale':'Measured local 2GiB load budget exceeded on a 222MB compressed-input expansion; use 12GiB for parsed graphs/hash temporaries and 1800s for whole-history independent geometry. No compilation, placement or factory stage is executed.','input_sha256':manifest,'result':result,'status':'dispatched_not_completed'}
    save(local/'dispatch.json',receipt); save(out/'server-session-latest.json',receipt)
    print(json.dumps({'dispatch_file':str(local/'dispatch.json'),'server':project,'result':result},ensure_ascii=False))


def status(fetch):
    receipt=json.loads((out/'server-session-latest.json').read_bytes()); project=receipt['project']
    if not PurePosixPath(project).is_relative_to('/home/yyq/na-platform-simulation/R6/T605'): raise ValueError('Unknown R6 server root')
    data=remote("from pathlib import Path\nimport json\np=Path("+repr(project)+")/'knowledge/roles/R6/evidence/T605/job-server/status.json'\nprint(p.read_text())")
    local=Path(receipt['local_directory']); save(local/'status.json',data)
    if fetch and data['status'] not in ('running','starting','dispatched_not_completed'):
        info=remote("from pathlib import Path\nimport json,tarfile\nr=Path("+repr(project)+")\np=r/'knowledge/roles/R6/evidence/T605'\nwith tarfile.open(r/'validation-results.tar.gz','w:gz') as f:\n for x in p.rglob('*'):\n  if x.is_file():f.add(x,arcname=str(x.relative_to(p)))\nprint(json.dumps({'archive':str(r/'validation-results.tar.gz')}))")
        destination=local/'validation-results.tar.gz'; subprocess.run(['scp','-q',host+':'+info['archive'],str(destination)],check=True,timeout=120)
        with tarfile.open(destination) as archive: archive.extractall(local/'result',filter='data')
    print(json.dumps(data,ensure_ascii=False,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('mode',choices=('launch','status')); parser.add_argument('--fetch',action='store_true'); args=parser.parse_args()
    launch() if args.mode=='launch' else status(args.fetch)
