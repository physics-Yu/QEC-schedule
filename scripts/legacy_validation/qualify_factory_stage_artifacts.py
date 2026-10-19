"""R7-dispatched read-only verification of the already compiled first stage."""
from pathlib import Path
from hashlib import sha256
import argparse,gzip,json,sys,time

from na_pipeline.validation.dag_factory import validate_factory_initialize

root=Path(__file__).resolve().parents[2]

def digest_file(path):
    with path.open('rb') as f:return __import__('hashlib').file_digest(f,'sha256').hexdigest()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--manifest',required=True);args=parser.parse_args()
    manifest=json.loads((root/args.manifest).read_bytes())
    out=(root/manifest.get('output_directory','knowledge/roles/R6/evidence/T605/factory-stage-validation-v1')).resolve()
    if not out.is_relative_to((root/'knowledge/roles/R6/evidence/T605').resolve()):raise ValueError('Output must stay in R6 evidence')
    out.mkdir(parents=True,exist_ok=True)
    def save(name,value):(out/name).write_bytes((json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
    files={role:root/item['path'] for role,item in manifest['inputs'].items()}
    for role,path in files.items():
        if not path.resolve().is_relative_to(root) or digest_file(path)!=manifest['inputs'][role]['byte_sha256']: raise ValueError('Frozen input mismatch: '+role)
    sources=list((root/'src/na_pipeline/validation').glob('*.py'))+[Path(__file__)]
    before={p.relative_to(root).as_posix():digest_file(p) for p in sources}
    for path,value in manifest['verifier_source_byte_sha256'].items():
        if digest_file(root/path)!=value:raise ValueError('Verifier source changed after dispatch preparation: '+path)
    started=time.perf_counter();payload={}
    for role in ('input','physical_plan','execution','observation'):
        with gzip.open(files[role],'rt',encoding='utf-8') as f:payload[role]=json.load(f)
        print(json.dumps({'stage':'loaded_frozen_input','role':role,'recompiled':False,'search_calls':0}),flush=True)
    report=validate_factory_initialize(payload['input'],payload['physical_plan'],payload['execution'],payload['observation']);save('report.json',report)
    receipt={'schema_version':'R6FrozenFactoryStageVerification/0.1','scope':report['scope'],'passed':report['passed'],'scoped_pass':report['scoped_pass'],'full_program_passed':False,
      'wall_seconds':time.perf_counter()-started,'source_before':before,'source_unchanged':all(digest_file(root/p)==v for p,v in before.items()),
      'input_byte_sha256':{item['path']:item['byte_sha256'] for item in manifest['inputs'].values()},'inputs_unchanged':all(digest_file(files[role])==item['byte_sha256'] for role,item in manifest['inputs'].items()),
      'python':sys.version,'executable':sys.executable,'recompiled':False,'reran_placer':False,'search_calls':0,'failures':report['failures'],'unverified':report['unverified']}
    save('receipt.json',receipt)
    # R7 owns the supervisor's stdout artifact and already exports it. This
    # preserves R6 file ownership without extending R7's output-path allowlist.
    print('R6_VALIDATION_ARTIFACTS_JSON='+json.dumps({'report':report,'receipt':receipt},ensure_ascii=False,separators=(',',':')),flush=True)
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
