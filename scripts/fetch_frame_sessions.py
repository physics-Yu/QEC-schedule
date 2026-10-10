"""Fetch completed frame receipts without duplicating the static module store."""
from pathlib import Path, PurePosixPath
import argparse, hashlib, json, subprocess, tarfile, os
from server_strategy_job import remote, HOST
ROOT=Path(__file__).resolve().parents[1]


def main():
    p=argparse.ArgumentParser();p.add_argument('--dispatch',type=Path,required=True);p.add_argument('--source',required=True);p.add_argument('--with-referenced-modules',action='store_true');a=p.parse_args()
    record=json.loads(a.dispatch.read_bytes());source=PurePosixPath(a.source);project=PurePosixPath(record['project'])
    if '..' in source.parts or not source.is_relative_to('artifacts/demos') or not project.is_relative_to('/home/yyq/na-platform-simulation/R7/T704'):raise ValueError('FRAME_FETCH_SCOPE')
    script='''from pathlib import Path
import hashlib,json,tarfile,io,gzip
root=Path(PROJECT);base=root/SOURCE
status=json.loads((base/'status.json').read_bytes())
if status['status']!='passed':raise ValueError('FRAME_JOB_INCOMPLETE')
paths=[base/'status.json']
for item in status['components']:
 folder=base/item['id']
 if json.loads((folder/'summary.json').read_bytes())['status']!='passed':raise ValueError('FRAME_CASE_INCOMPLETE')
 paths.extend([folder/'summary.json',folder/'frame-session.json.gz'])
 if INCLUDE_MODULES:
  data=json.loads(gzip.decompress((folder/'frame-session.json.gz').read_bytes()))
  names=set()
  for entry in data['entries']:
   composition=entry['physical_plan']['module_composition']
   names.update(m['artifact_ref']['file'] for m in composition['instances'])
   names.update('frontier-proof-'+f['decision_hash']+'.json' for f in composition['dependency_graph'].get('joint_frontiers',[]))
  if any(Path(name).name!=name for name in names):raise ValueError('FRAME_MODULE_PATH_ESCAPE')
  paths.extend(base/'compiled-modules'/name for name in sorted(names))
manifest={p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
identity=hashlib.sha256(json.dumps(manifest,sort_keys=True).encode()).hexdigest();target=root/('frame-export-'+identity[:20]+'.tar.gz')
if not target.exists():
 with tarfile.open(target.with_suffix('.partial'),'w:gz',compresslevel=1) as t:
  for name in manifest:t.add(root/name,arcname=name,recursive=False)
  b=json.dumps(manifest).encode();info=tarfile.TarInfo('frame-export-manifest.json');info.size=len(b);t.addfile(info,io.BytesIO(b))
 target.with_suffix('.partial').replace(target)
print(json.dumps({'archive':str(target),'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'files':len(manifest),'bytes':target.stat().st_size}))
'''.replace('PROJECT',repr(str(project))).replace('SOURCE',repr(str(source))).replace('INCLUDE_MODULES',repr(a.with_referenced_modules))
    result=remote(script,timeout=600);archive=a.dispatch.parent/Path(result['archive']).name
    if not archive.exists() or hashlib.sha256(archive.read_bytes()).hexdigest()!=result['sha256']:
        subprocess.run(['scp','-q',HOST+':'+result['archive'],str(archive)],check=True,timeout=600)
    if hashlib.sha256(archive.read_bytes()).hexdigest()!=result['sha256']:raise ValueError('FRAME_ARCHIVE_HASH')
    with tarfile.open(archive) as t:
        manifest=json.loads(t.extractfile('frame-export-manifest.json').read())
        for name,sha in manifest.items():
            target=(ROOT/name).resolve()
            if not target.is_relative_to((ROOT/str(source)).resolve()):raise ValueError('FRAME_OUTPUT_SCOPE')
            if os.name=='nt':target=Path('\\\\?\\'+str(target))
            data=t.extractfile(name).read()
            if hashlib.sha256(data).hexdigest()!=sha:raise ValueError('FRAME_FILE_HASH')
            if target.exists() and target.read_bytes()!=data:raise ValueError('FRAME_EXISTING_EVIDENCE_DIFFERS')
            target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
    (a.dispatch.parent/'frame-fetch-receipt.json').write_text(json.dumps({**result,'manifest':manifest,'all_bytes_verified':True},indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result))


if __name__=='__main__':main()
