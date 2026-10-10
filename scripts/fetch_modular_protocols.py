"""Fetch completed protocol evidence without touching running sibling output."""
from pathlib import Path,PurePosixPath
import argparse,hashlib,json,subprocess,tarfile
from server_strategy_job import remote,HOST
ROOT=Path(__file__).resolve().parents[1]
SOURCE_ROOT='artifacts/demos/neutral-modular-20261007'


def main():
    p=argparse.ArgumentParser();p.add_argument('--dispatch',type=Path,required=True);p.add_argument('--components',nargs='+',required=True)
    p.add_argument('--destination',default='artifacts/demos/neutral-modular-ready-20261007');a=p.parse_args()
    if not set(a.components)<={'T','TDG','REJECT_RETRY'}:raise ValueError('COMPONENT_SCOPE')
    destination=(ROOT/a.destination).resolve()
    if not destination.is_relative_to((ROOT/'artifacts/demos').resolve()):raise ValueError('DESTINATION_SCOPE')
    project=PurePosixPath(json.loads(a.dispatch.read_bytes())['project'])
    if not project.is_relative_to('/home/yyq/na-platform-simulation/R7/T704'):raise ValueError('JOB_SCOPE')
    script='''from pathlib import Path
import hashlib,json,tarfile,io
root=Path(PROJECT);base=root/SOURCE_ROOT/'protocols';files={};retained={}
for name in COMPONENTS:
 folder=base/name
 if json.loads((folder/'summary.json').read_bytes())['status']!='passed':raise ValueError('COMPONENT_INCOMPLETE')
 for p in sorted(folder.rglob('*')):
  if not p.is_file():continue
  rel=p.relative_to(root).as_posix();record={'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size}
  if p.name.startswith('checkpoint') or p.name.endswith('.tmp') or 'recovery-before-resume' in p.parts:retained[rel]=record
  else:files[rel]=record
manifest={'schema_version':'CompletedModularProtocolExport/0.1','project':str(root),'components':COMPONENTS,'files':files,'retained_on_server':retained}
identity=hashlib.sha256(json.dumps(manifest,sort_keys=True).encode()).hexdigest();archive=root/('completed-modular-'+identity[:20]+'.tar.gz')
if not archive.exists():
 with tarfile.open(archive.with_suffix('.partial'),'w:gz',compresslevel=1) as t:
  for rel in files:t.add(root/rel,arcname=rel,recursive=False)
  raw=json.dumps(manifest).encode();info=tarfile.TarInfo('protocol-export-manifest.json');info.size=len(raw);t.addfile(info,io.BytesIO(raw))
 archive.with_suffix('.partial').replace(archive)
print(json.dumps({'archive':str(archive),'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'file_count':len(files)}))
'''.replace('PROJECT',repr(str(project))).replace('SOURCE_ROOT',repr(SOURCE_ROOT)).replace('COMPONENTS',repr(a.components))
    result=remote(script,timeout=600);archive=a.dispatch.parent/PurePosixPath(result['archive']).name
    if not archive.exists() or hashlib.sha256(archive.read_bytes()).hexdigest()!=result['sha256']:
        subprocess.run(['scp','-q',HOST+':'+result['archive'],str(archive)],check=True,timeout=600)
    if hashlib.sha256(archive.read_bytes()).hexdigest()!=result['sha256']:raise ValueError('ARCHIVE_BYTES_CHANGED')
    with tarfile.open(archive) as t:
        manifest=json.loads(t.extractfile('protocol-export-manifest.json').read())
        for rel,record in manifest['files'].items():
            relative=PurePosixPath(rel).relative_to(SOURCE_ROOT);target=(destination/str(relative)).resolve()
            if not target.is_relative_to(destination/'protocols'):raise ValueError('EXTRACTION_SCOPE')
            raw=t.extractfile(t.getmember(rel)).read()
            if hashlib.sha256(raw).hexdigest()!=record['sha256']:raise ValueError('OUTPUT_BYTES_CHANGED')
            if target.exists() and target.read_bytes()!=raw:raise ValueError('EXISTING_EVIDENCE_DIFFERS '+str(target))
            target.parent.mkdir(parents=True,exist_ok=True)
            if not target.exists():target.write_bytes(raw)
    receipt={**result,'manifest':manifest,'destination':str(destination),'all_exported_bytes_verified':True,'compilation_started':False}
    path=a.dispatch.parent/('modular-fetch-'+'-'.join(a.components)+'.json');path.write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in receipt.items() if k!='manifest'},ensure_ascii=False))


if __name__=='__main__':main()
