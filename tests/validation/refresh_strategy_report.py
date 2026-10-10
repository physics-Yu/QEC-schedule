"""Recheck saved production inputs without compiling or executing them again."""
from hashlib import sha256
import gzip,json,sys,time
from pathlib import Path
from na_pipeline.validation import validate_strategy_run

root=Path(__file__).resolve().parents[2]; out=root/'knowledge/roles/R6/evidence/T604'
archive=out/'inputs.json.gz'; bundle=json.loads(gzip.decompress(archive.read_bytes()))
started=time.perf_counter()
report=validate_strategy_run(bundle['run'],bundle['device'],strategies=bundle['strategies'],enola_evidence=bundle['enola_evidence'])
old=out/'run-report-current.json'; counter_failure=out/'routing-counter-before-fix.json'
if old.exists() and not counter_failure.exists():
    previous=json.loads(old.read_bytes())
    if any(f['code']=='ROUTING_SEARCH_COUNTER_MISMATCH' for f in previous['failures']): counter_failure.write_bytes(old.read_bytes())
raw=(json.dumps(report,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
for name in ('run-report.json','run-report-current.json'): (out/name).write_bytes(raw)
receipt={'schema_version':'R6ValidationRefresh/0.1','passed':report['passed'],'wall_seconds':time.perf_counter()-started,'input_archive_sha256':sha256(archive.read_bytes()).hexdigest(),'report_sha256':sha256(raw).hexdigest(),'source_byte_sha256':{str(p.relative_to(root)):sha256(p.read_bytes()).hexdigest() for p in root.glob('src/na_pipeline/validation/*.py')},'scope':'Rechecked saved immutable producer inputs with final R6 binding-semantic and cycle-metric checks; no recompilation or runtime replay','supersedes':'The report embedded in inputs.json.gz; producer inputs and independent observations are unchanged','python':sys.version,'executable':sys.executable}
(out/'validation-refresh.json').write_bytes((json.dumps(receipt,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
print(json.dumps({k:v for k,v in receipt.items() if k!='source_byte_sha256'},ensure_ascii=False,indent=2))
if not report['passed']: print(json.dumps({'failures':report['failures'][:8],'unverified':report['unverified']},ensure_ascii=False,indent=2))
raise SystemExit(0 if report['passed'] else 1)
