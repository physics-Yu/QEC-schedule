"""Fetch immutable completed component evidence while sibling jobs continue.

Large resumable checkpoints remain at the recorded server path. No compilation
is launched and no live status file is mixed into a completed component export.
"""
from pathlib import Path,PurePosixPath
import argparse,hashlib,json,subprocess,tarfile
from server_strategy_job import remote,HOST
ROOT=Path(__file__).resolve().parents[1]

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--dispatch',type=Path,required=True);ap.add_argument('--components',nargs='+',required=True);a=ap.parse_args()
    if not set(a.components)<={'T','TDG','REJECT_RETRY'}:raise ValueError('Unknown component export')
    d=json.loads(a.dispatch.read_bytes());project=PurePosixPath(d['project'])
    if not project.is_relative_to('/home/yyq/na-platform-simulation/R7/T704'):raise ValueError('Invalid job root')
    code='''from pathlib import Path
import hashlib,json,tarfile,io
root=Path(PROJECT);base=root/'artifacts/demos/logical-components-20261007/protocols'
files={};retained={}
for name in COMPONENTS:
 folder=base/name
 summary=json.loads((folder/'summary.json').read_bytes())
 if summary['status']!='passed':raise ValueError('Component not completed')
 for p in sorted(folder.rglob('*')):
  if not p.is_file():continue
  rel=p.relative_to(root).as_posix()
  rec={'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size}
  if p.name.startswith('checkpoint') or p.name.endswith('.tmp'):retained[rel]=rec
  else:files[rel]=rec
manifest={'schema_version':'completed-component-export/0.1','project':str(root),'components':COMPONENTS,'files':files,'retained_on_server':retained}
identity=hashlib.sha256(json.dumps(manifest,sort_keys=True).encode()).hexdigest()
archive=root/('completed-components-'+identity[:20]+'.tar.gz')
if not archive.exists():
 temp=archive.with_suffix('.partial')
 with tarfile.open(temp,'w:gz',compresslevel=1) as t:
  for rel in files:t.add(root/rel,arcname=rel,recursive=False)
  raw=json.dumps(manifest).encode();i=tarfile.TarInfo('component-export-manifest.json');i.size=len(raw);t.addfile(i,io.BytesIO(raw))
 temp.replace(archive)
print(json.dumps({'archive':str(archive),'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'files':len(files),'retained_checkpoints':len(retained)}))
'''.replace('PROJECT',repr(str(project))).replace('COMPONENTS',repr(a.components))
    result=remote(code,timeout=600);target=a.dispatch.parent/PurePosixPath(result['archive']).name
    if not target.exists() or hashlib.sha256(target.read_bytes()).hexdigest()!=result['sha256']:
        subprocess.run(['scp','-q',HOST+':'+result['archive'],str(target)],check=True,timeout=600)
    assert hashlib.sha256(target.read_bytes()).hexdigest()==result['sha256']
    with tarfile.open(target) as t:
        manifest=json.loads(t.extractfile('component-export-manifest.json').read())
        for rel,rec in manifest['files'].items():
            member=t.getmember(rel)
            if not member.isfile():raise ValueError('Non-file output rejected')
            p=(ROOT/rel).resolve()
            if not p.is_relative_to((ROOT/'artifacts/demos/logical-components-20261007/protocols').resolve()):raise ValueError('Output escape')
            raw=t.extractfile(member).read();assert hashlib.sha256(raw).hexdigest()==rec['sha256']
            if p.exists() and p.read_bytes()!=raw:raise ValueError('Refusing to replace changed local evidence '+rel)
            p.parent.mkdir(parents=True,exist_ok=True)
            if not p.exists():p.write_bytes(raw)
    receipt={**result,'all_output_bytes_verified':True,'manifest':manifest,'archive_local':str(target.resolve())}
    (a.dispatch.parent/('component-fetch-'+'-'.join(a.components)+'.json')).write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in receipt.items() if k!='manifest'}))

if __name__=='__main__':main()
