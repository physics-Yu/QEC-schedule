"""Check the fixed R5 five-window artifacts without rerunning any compiler."""
from pathlib import Path
from hashlib import sha256
import gzip,json,sys,time

from na_pipeline.validation.dag_session import validate_session_run

root=Path(__file__).resolve().parents[2]; current=root/'examples/scenarios/T505-dag-session-fixed-runtime'; old=root/'examples/scenarios/T505-dag-session-v1'
out=root/'knowledge/roles/R6/evidence/T605'; out.mkdir(parents=True,exist_ok=True)
def read(path): return json.loads(gzip.decompress(path.read_bytes()))

started=time.perf_counter(); files=[]
device=read(old/'device.json.gz'); logical=read(old/'logical-dag.json.gz'); placement=read(old/'patch-placement.json.gz'); physical=read(old/'physical-bundle.json.gz')
windows=[]
for path in sorted(current.glob('window-*.json.gz')):
    value=read(path); original=(root/value['original_compiled_artifact']).resolve()
    if not original.is_relative_to(old): raise ValueError('Unexpected compiled artifact reference outside the fixed source directory')
    frozen=read(original); value['physical_plan']=frozen['physical_plan']; windows.append(value); files.extend([path,original])
trace=read(current/'event-trace.json.gz'); schedule=read(current/'logical-schedule.json.gz')
files.extend([old/name for name in ('device.json.gz','logical-dag.json.gz','patch-placement.json.gz','physical-bundle.json.gz')]); files.extend([current/name for name in ('event-trace.json.gz','logical-schedule.json.gz','receipt.json')])
inputs={str(p.relative_to(root)):sha256(p.read_bytes()).hexdigest() for p in files}
source_paths=list((root/'src/na_pipeline/validation').glob('*.py')); before={str(p.relative_to(root)):sha256(p.read_bytes()).hexdigest() for p in source_paths}
bundle={'scope':'four_patch_clifford_example','device':device,'logical_dag':logical,'physical_bundle':physical,'patch_placement':placement,'initial_state':placement['initial_state'],'windows':windows,'event_trace':trace,'logical_schedule':schedule,'fixture':False}
print(json.dumps({'stage':'loaded_fixed_inputs','windows':len(windows),'actions':trace['stats']['action_count'],'source_byte_sha256':inputs},ensure_ascii=False),flush=True)
report=validate_session_run(bundle)
(out/'fixed-session-report.json').write_bytes((json.dumps(report,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
after={str(p.relative_to(root)):sha256(p.read_bytes()).hexdigest() for p in source_paths}
receipt={'scope':'fixed five-window four-patch source/geometry/causality only; not full resource world or Shor','passed':report['passed'],'seconds':time.perf_counter()-started,'failures':report['failures'][:12],'unverified':report['unverified'],'input_byte_sha256':inputs,'source_before':before,'source_after':after,'source_unchanged':before==after,'inputs_unchanged':all(sha256((root/p).read_bytes()).hexdigest()==value for p,value in inputs.items()),'python':sys.version,'executable':sys.executable,'recompiled':False,'reran_placer':False,'quantum_state_simulated':False,'hardware_executed':False}
(out/'fixed-session-receipt.json').write_bytes((json.dumps(receipt,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
print(json.dumps({k:v for k,v in receipt.items() if k not in ('source_before','source_after','input_byte_sha256')},ensure_ascii=False,indent=2),flush=True)
raise SystemExit(0 if report['passed'] else 1)
