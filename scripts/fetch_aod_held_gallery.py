"""Copy byte-verified completed evidence; leave recovery checkpoints on server."""
from pathlib import Path, PurePosixPath
import argparse, hashlib, json, subprocess, tarfile
from server_strategy_job import remote, HOST

ROOT = Path(__file__).resolve().parents[1]
SOURCE = 'artifacts/demos/aod-held-cz-20261007'


def main():
    global SOURCE
    p = argparse.ArgumentParser()
    p.add_argument('--dispatch', type=Path, required=True)
    p.add_argument('--complete', action='store_true')
    p.add_argument('--protocols-only', action='store_true')
    p.add_argument('--source', default=SOURCE)
    a = p.parse_args()
    source=PurePosixPath(a.source)
    if source.is_absolute() or '..' in source.parts or not source.is_relative_to('artifacts/demos'):
        raise ValueError('OUTPUT_SCOPE')
    SOURCE=source.as_posix()
    record = json.loads(a.dispatch.read_bytes())
    if (a.complete or a.protocols_only) and not (a.dispatch.parent / 'held-cz-fetch-upstream.json').is_file():
        raise ValueError('FETCH_UPSTREAM_FIRST')
    project = PurePosixPath(record['project'])
    if not project.is_relative_to('/home/yyq/na-platform-simulation/R7/T704'):
        raise ValueError('JOB_SCOPE')
    script = '''from pathlib import Path
import hashlib,json,tarfile,io
root=Path(PROJECT);base=root/SOURCE;complete=__COMPLETE__;job_receipts=__JOB_RECEIPTS__
status=json.loads((base/'status.json').read_bytes())
if complete and status['status']!='passed':raise ValueError('JOB_INCOMPLETE')
catalog=json.loads((base/'catalog.json').read_bytes())
names=[x['id'] for x in catalog['components'] if x['kind']=='physical']+['SE_PAIR']
for n in names:
 if json.loads((base/n/'summary.json').read_bytes())['status']!='passed':raise ValueError('COMPONENT_INCOMPLETE '+n)
files={};retained={}
paths=[base/n for n in names]+[base/'compiled-modules',base/'catalog.json',base/'shor-coverage.json']+list(base.glob('*-tests.log'))
if complete:
 paths=[base/'protocols',base/'status.json']
 for extra in ('parallel-examples','residency-and-frame-complete.json','cohort-acceptance.json','joint-parallel-acceptance.json','proof-seal.json','proof-storage-tests.log'):
  if (base/extra).exists():paths.append(base/extra)
 if job_receipts:paths += [root/'scripts/outputs/T704/worker-receipt.json',root/'scripts/outputs/T704/source-inventory.json',root/'scripts/outputs/T704/job/status.json']
for folder in paths:
 if not folder.exists():raise ValueError('MISSING_OUTPUT '+str(folder))
 for f in sorted(folder.rglob('*')) if folder.is_dir() else [folder]:
  if not f.is_file():continue
  rel=f.relative_to(root).as_posix();v={'sha256':hashlib.sha256(f.read_bytes()).hexdigest(),'bytes':f.stat().st_size}
  if f.name.startswith('checkpoint') or f.name.endswith('.tmp'):retained[rel]=v
  else:files[rel]=v
manifest={'schema_version':'CompletedHeldCZExport/0.1','project':str(root),'complete':complete,'worker_receipts_included':job_receipts,'files':files,'retained_on_server':retained}
identity=hashlib.sha256(json.dumps(manifest,sort_keys=True).encode()).hexdigest();archive=root/('held-cz-export-'+identity[:20]+'.tar.gz')
if not archive.exists():
 with tarfile.open(archive.with_suffix('.partial'),'w:gz',compresslevel=1) as t:
  for rel in files:t.add(root/rel,arcname=rel,recursive=False)
  raw=json.dumps(manifest).encode();info=tarfile.TarInfo('export-manifest.json');info.size=len(raw);t.addfile(info,io.BytesIO(raw))
 archive.with_suffix('.partial').replace(archive)
print(json.dumps({'archive':str(archive),'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'file_count':len(files),'archive_bytes':archive.stat().st_size}))
'''.replace('PROJECT', repr(str(project))).replace('SOURCE', repr(SOURCE)).replace('__COMPLETE__', repr(a.complete or a.protocols_only)).replace('__JOB_RECEIPTS__',repr(a.complete))
    result = remote(script, timeout=600)
    archive = a.dispatch.parent / PurePosixPath(result['archive']).name
    if not archive.exists() or hashlib.sha256(archive.read_bytes()).hexdigest() != result['sha256']:
        subprocess.run(['scp', '-q', HOST + ':' + result['archive'], str(archive)], check=True, timeout=600)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != result['sha256']:
        raise ValueError('ARCHIVE_BYTES_CHANGED')
    with tarfile.open(archive) as t:
        manifest = json.loads(t.extractfile('export-manifest.json').read())
        for rel, entry in manifest['files'].items():
            if rel.startswith(SOURCE + '/'):
                target = (ROOT / rel).resolve()
                if not target.is_relative_to((ROOT / SOURCE).resolve()):
                    raise ValueError('OUTPUT_SCOPE')
            elif rel.startswith('scripts/outputs/T704/'):
                target = a.dispatch.parent / 'held-cz-receipt' / PurePosixPath(rel).relative_to('scripts/outputs/T704')
            else:
                raise ValueError('UNEXPECTED_OUTPUT')
            raw = t.extractfile(t.getmember(rel)).read()
            if hashlib.sha256(raw).hexdigest() != entry['sha256']:
                raise ValueError('FILE_BYTES_CHANGED')
            if target.exists() and target.read_bytes() != raw:
                raise ValueError('EXISTING_EVIDENCE_DIFFERS ' + str(target))
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                target.write_bytes(raw)
    receipt = {**result, 'all_exported_bytes_verified': True, 'compilation_started': False, 'manifest': manifest}
    name = 'held-cz-fetch-complete.json' if a.complete else 'held-cz-fetch-protocols.json' if a.protocols_only else 'held-cz-fetch-upstream.json'
    (a.dispatch.parent / name).write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in receipt.items() if k != 'manifest'}))


if __name__ == '__main__':
    main()
