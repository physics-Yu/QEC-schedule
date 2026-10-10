"""Byte-verified fetch of the completed six-block qualification preview."""
from pathlib import Path
import hashlib,json,subprocess,sys,tarfile
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from server_strategy_job import remote,HOST


def main():
    job=ROOT/'scripts/outputs/T704/server/20261008T071210031563Z-t044-dual-array-se-qualification'
    dispatch=json.loads((job/'dispatch.json').read_bytes());project=dispatch['project']
    result=remote('''from pathlib import Path
import hashlib,json,tarfile,io
root=Path(PROJECT);base=root/'artifacts/demos/dual-array-se-20261008'
s=json.loads((root/'scripts/outputs/T704/job/status.json').read_bytes())
if s.get('returncode')!=0 or s['status']!='completed':raise ValueError('INCOMPLETE_QUALIFICATION')
paths=[base/'SE_DUAL_SIX'/n for n in ['summary.json','physical-dag.json','physical-plan.json','atom-program.json','event-trace.json','scenario.json','device.json','validation.json']]
paths+=list((base/'compiled-modules').glob('*.json'))
manifest={p.relative_to(base).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
archive=root/'six-SE-preview.tar.gz'
with tarfile.open(archive,'w:gz') as t:
 for p in paths:t.add(p,arcname=p.relative_to(base).as_posix(),recursive=False)
 b=json.dumps(manifest).encode();info=tarfile.TarInfo('manifest.json');info.size=len(b);t.addfile(info,io.BytesIO(b))
print(json.dumps({'archive':str(archive),'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'manifest':manifest}))
'''.replace('PROJECT',repr(project)))
    archive=job/'six-SE-preview.tar.gz';subprocess.run(['scp','-q',HOST+':'+result['archive'],str(archive)],check=True,timeout=120)
    if hashlib.sha256(archive.read_bytes()).hexdigest()!=result['sha256']:raise ValueError('ARCHIVE_HASH')
    out=ROOT/'artifacts/demos/joint-frontier-preview-20261008';out.mkdir(exist_ok=True)
    with tarfile.open(archive) as t:
        for name,sha in result['manifest'].items():
            relative=Path(name)
            if relative.is_absolute() or '..' in relative.parts or relative.parts[0] not in ('SE_DUAL_SIX','compiled-modules'):raise ValueError('EXPORT_SCOPE')
            target=out/('parallel-examples' if relative.parts[0]=='SE_DUAL_SIX' else '')/relative
            raw=t.extractfile(name).read()
            if hashlib.sha256(raw).hexdigest()!=sha:raise ValueError('FILE_HASH')
            target.parent.mkdir(parents=True,exist_ok=True)
            if target.exists() and target.read_bytes()!=raw:raise ValueError('EXISTING_EVIDENCE_DIFFERS')
            target.write_bytes(raw)
    (out/'fetch-receipt.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    for name,var,value in [('manifest.js','COMPONENT_MANIFEST',{'components':[],'coverage':{},'scope':'six-block preview only; full factory rebuild remains in progress','user_visual_acceptance':'pending'}),('schedules.js','COMPONENT_SCHEDULE_PACKED',{}),('regions.js','COMPONENT_ZONES',{})]:
        (out/name).write_text('window.'+var+'='+json.dumps(value)+';\n',encoding='utf-8')
    (out/'animation-library.html').write_text('',encoding='utf-8')
    from extend_parallel_gallery import build
    build(out,allow_partial=True)

if __name__=='__main__':main()
