"""Verify the complete archived five-window history, never rerun the compiler."""
import argparse,gzip,json,sys,time
from hashlib import file_digest
from pathlib import Path

from na_pipeline.validation import validate_session_run

root=Path(__file__).resolve().parents[2]
def digest(path):
    with path.open('rb') as f:return file_digest(f,'sha256').hexdigest()
def read(path):
    with gzip.open(path,'rt',encoding='utf-8') as f:return json.load(f)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--manifest',required=True);args=parser.parse_args();manifest=json.loads((root/args.manifest).read_bytes())
    paths={role:root/record['path'] for role,record in manifest['inputs'].items()}
    for role,path in paths.items():
        if not path.resolve().is_relative_to(root) or digest(path)!=manifest['inputs'][role]['byte_sha256']:raise ValueError('Frozen source changed: '+role)
    for path,value in manifest['verifier_source_byte_sha256'].items():
        if digest(root/path)!=value:raise ValueError('Frozen verifier changed: '+path)
    out=(root/manifest['output_directory']).resolve()
    if not out.is_relative_to((root/'knowledge/roles/R6/evidence/T605').resolve()):raise ValueError('R6 output scope required')
    out.mkdir(parents=True,exist_ok=True)
    sources=list((root/'src/na_pipeline/validation').glob('*.py'))+[Path(__file__)];before={p.relative_to(root).as_posix():digest(p) for p in sources};start=time.perf_counter();windows=[]
    for i in range(5):
        window=read(paths[f'window_{i}']);original=(root/window['original_compiled_artifact']).resolve()
        if original!=paths[f'compiled_window_{i}'].resolve():raise ValueError('Window changed its original compiled source')
        window['physical_plan']=read(original)['physical_plan'];windows.append(window)
        print(json.dumps({'stage':'loaded_original_window','index':i,'recompiled':False}),flush=True)
    placement=read(paths['placement']);bundle={'scope':'four_patch_clifford_example_with_verified_history_chunks','fixture':False,'device':read(paths['device']),'logical_dag':read(paths['logical_dag']),'physical_bundle':read(paths['physical_bundle']),'patch_placement':placement,'initial_state':placement['initial_state'],'windows':windows,'event_trace':read(paths['event_trace']),'logical_schedule':read(paths['logical_schedule']),'archive_root':str(paths['history_0'].parent.resolve())}
    report=validate_session_run(bundle)
    receipt={'schema_version':'R6ChunkedSessionVerification/0.1','scope':report['scope'],'passed':report['passed'],'full_program_passed':False,'seconds':time.perf_counter()-start,'source_before':before,'source_unchanged':all(digest(root/p)==h for p,h in before.items()),'input_byte_sha256':{record['path']:record['byte_sha256'] for record in manifest['inputs'].values()},'inputs_unchanged':all(digest(paths[role])==record['byte_sha256'] for role,record in manifest['inputs'].items()),'failures':report['failures'],'unverified':report['unverified'],'python':sys.version,'executable':sys.executable,'recompiled':False,'reran_placer':False,'search_calls':0,'archive_validation':'all five chunk bytes/chains; exact archived actions; identical retained suffix deduplicated before complete geometry/source/causality verification'}
    for name,value in (('report',report),('receipt',receipt)):(out/(name+'.json')).write_bytes((json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
    print(json.dumps({k:v for k,v in receipt.items() if k not in ('source_before','input_byte_sha256')},ensure_ascii=False),flush=True)
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
