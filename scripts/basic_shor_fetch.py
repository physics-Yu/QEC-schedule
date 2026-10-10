"""Hash-verified transfer of immutable run outputs, optionally a committed prefix."""
from pathlib import Path, PurePosixPath
import argparse, hashlib, json, subprocess, tarfile
from server_strategy_job import remote, HOST

ROOT=Path(__file__).resolve().parents[1]


def fetch(dispatch, source, destination, *, phase='execute', prefix=False, viewer_only=False):
    record=json.loads(Path(dispatch).read_bytes());project=record['project']
    if not PurePosixPath(project).is_relative_to('/home/yyq/na-platform-simulation/R7/T704'):raise ValueError('PROJECT_SCOPE')
    if PurePosixPath(source).is_absolute() or '..' in PurePosixPath(source).parts:raise ValueError('SOURCE_SCOPE')
    script='''from pathlib import Path
import hashlib,json,tarfile,io
base=Path(PROJECT)/SOURCE;phase=PHASE
if VIEWER_ONLY: paths=list((base/'viewer').rglob('*'))+[base/'acceptance.json',base/'status.json']
elif PREFIX:
 paths=[base/'world.json.gz']+list((base/phase).glob('*.json*'))
 for sub in ('windows','window-index','history','decisions','factory'):
  paths+=list((base/phase/sub).rglob('*'))
else: paths=[p for p in base.rglob('*') if 'prepare' not in p.relative_to(base).parts]
paths=sorted({p for p in paths if p.is_file() and not p.name.endswith(('.tmp','.writing','-wal','-shm'))})
files={};raws={}
for p in paths:
 raw=p.read_bytes();name=p.relative_to(base).as_posix();raws[name]=raw
 files[name]={'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}
manifest={'project':PROJECT,'source':SOURCE,'phase':phase,'prefix':PREFIX,'files':files}
key=hashlib.sha256(json.dumps(manifest,sort_keys=True).encode()).hexdigest()
path=Path(PROJECT)/('basic-shor-export-'+key[:20]+'.tar.gz')
with tarfile.open(path,'w:gz',compresslevel=1) as t:
 for name,raw in raws.items():
  info=tarfile.TarInfo(name);info.size=len(raw);t.addfile(info,io.BytesIO(raw))
 raw=json.dumps(manifest).encode();info=tarfile.TarInfo('export-manifest.json');info.size=len(raw);t.addfile(info,io.BytesIO(raw))
print(json.dumps({'archive':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'bytes':path.stat().st_size,'files':len(files)}))
'''
    for key,value in [('PROJECT',project),('SOURCE',source),('PHASE',phase),('PREFIX',prefix),('VIEWER_ONLY',viewer_only)]:script=script.replace(key,repr(value))
    export=remote(script,timeout=600)
    archive=Path(dispatch).parent/Path(export['archive']).name
    subprocess.run(['scp','-q',HOST+':'+export['archive'],str(archive)],check=True,timeout=600)
    if hashlib.sha256(archive.read_bytes()).hexdigest()!=export['sha256']:raise ValueError('TRANSFER_HASH')
    destination=Path(destination).resolve();destination.mkdir(parents=True,exist_ok=True)
    with tarfile.open(archive) as t:
        manifest=json.loads(t.extractfile('export-manifest.json').read())
        for name,item in manifest['files'].items():
            target=(destination/name).resolve()
            if not target.is_relative_to(destination):raise ValueError('EXTRACTION_SCOPE')
            raw=t.extractfile(name).read()
            if hashlib.sha256(raw).hexdigest()!=item['sha256']:raise ValueError('FILE_HASH')
            if target.exists() and target.read_bytes()!=raw:raise ValueError('EXISTING_EVIDENCE_CHANGED: '+name)
            target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
    receipt={**export,'manifest':manifest,'all_bytes_verified':True,'new_compilation':False}
    (destination/'fetch-receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return {**export,'destination':str(destination)}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--dispatch',type=Path,required=True);p.add_argument('--source',required=True);p.add_argument('--destination',type=Path,required=True);p.add_argument('--phase',default='execute');p.add_argument('--prefix',action='store_true');p.add_argument('--viewer-only',action='store_true');a=p.parse_args()
    print(json.dumps(fetch(a.dispatch,a.source,a.destination,phase=a.phase,prefix=a.prefix,viewer_only=a.viewer_only),ensure_ascii=False))
