"""Persist independent T602 evidence without changing the T601 slice report."""
from hashlib import sha256
import io,json,platform,sys,time,unittest,zipfile
from pathlib import Path

from na_pipeline.frontend import build_shor15,postprocess_phase
from na_pipeline.qec import build_two_block_slice
from na_pipeline.validation import audit_shor15,audit_surface17
from na_pipeline.validation.checker import _hash

root=Path(__file__).resolve().parents[2]
out=root/'knowledge/roles/R6/evidence/semantics'; out.mkdir(parents=True,exist_ok=True)
source_root=root/'src/na_pipeline'
sources={str(p.relative_to(source_root)).replace('\\','/'):sha256(p.read_bytes()).hexdigest() for p in source_root.rglob('*.py')}
logical=build_shor15(); physical=build_two_block_slice()
cases=[postprocess_phase([(y>>(7-i))&1 for i in range(8)],N=N,a=a) for N,a in [(15,2),(21,2),(21,3)] for y in range(256)]
start=time.perf_counter(); frontend=audit_shor15(logical,cases); front_time=time.perf_counter()-start
start=time.perf_counter(); qec=audit_surface17(physical); qec_time=time.perf_counter()-start
stream=io.StringIO(); start=time.perf_counter()
suite=unittest.defaultTestLoader.discover(str(Path(__file__).parent),pattern='test_semantics.py')
result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite); test_time=time.perf_counter()-start
(out/'unittest.txt').write_bytes(stream.getvalue().encode('utf-8'))
bundle={'logical.json':logical,'physical.json':physical,'postprocess-cases.json':cases}
archive=out/'semantic-inputs.zip'
with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED) as saved:
    for name,value in bundle.items(): saved.writestr(name,json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8'))
manifest={'task':'T602','kb_revision':'kb-0004','python':sys.version,'executable':sys.executable,'host':platform.node(),'source_file_sha256':sources,'input_sha256':{name:_hash(value) for name,value in bundle.items()},'archive_sha256':sha256(archive.read_bytes()).hexdigest(),'tests':{'run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'seconds':test_time},'audit_seconds':{'frontend':front_time,'surface17':qec_time},'static_audits_passed':frontend['passed'] and qec['passed'],'quantum_state_simulated':False,'hardware_executed':False,'budget':{'execution_host':'local','workers':1,'scope':'96 basis labels of complete 32x32 operators; 5 interval 2x2 words; 2619 symbolic Pauli labels; no search or state sampling'}}
for name,value in [('shor15-report',frontend),('surface17-report',qec),('manifest',manifest)]:
    (out/(name+'.json')).write_bytes((json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode('utf-8'))
print(json.dumps({'tests':manifest['tests'],'static_audits_passed':manifest['static_audits_passed'],'frontend_failures':frontend['failures'][:3],'qec_failures':qec['failures'][:3]},ensure_ascii=False,indent=2))
raise SystemExit(0 if result.wasSuccessful() and manifest['static_audits_passed'] else 1)
