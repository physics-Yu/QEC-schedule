"""Record chunk adapter and resource-boundary follow-ups independently of v1."""
import io,json,sys,time,unittest
from hashlib import sha256
from pathlib import Path

root=Path(__file__).resolve().parents[2];out=root/'knowledge/roles/R6/evidence/T605'
names=['test_history_validation.py','test_resources.py']
sources=list((root/'src/na_pipeline/validation').glob('*.py'))+list((root/'src/na_pipeline/runtime').glob('*.py'))+[root/'tests/validation'/n for n in names]
before={p.relative_to(root).as_posix():sha256(p.read_bytes()).hexdigest() for p in sources}
class Result(unittest.TextTestResult):
    def __init__(self,*args,**kwargs):super().__init__(*args,**kwargs);self.records=[]
    def addSuccess(self,test):super().addSuccess(test);self.records.append({'test':test.id(),'status':'passed'})
    def addFailure(self,test,err):super().addFailure(test,err);self.records.append({'test':test.id(),'status':'failed'})
    def addError(self,test,err):super().addError(test,err);self.records.append({'test':test.id(),'status':'error'})
suite=unittest.TestSuite(unittest.defaultTestLoader.discover(str(root/'tests/validation'),pattern=n) for n in names);stream=io.StringIO();start=time.perf_counter();result=unittest.TextTestRunner(stream=stream,verbosity=2,resultclass=Result).run(suite)
report={'schema_version':'R6HistoryTests/0.1','kb_revision':'kb-0006','passed':result.wasSuccessful(),'tests_run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'seconds':time.perf_counter()-start,'python':sys.version,'cases':result.records,'source_byte_sha256':before,'source_unchanged':all(sha256((root/p).read_bytes()).hexdigest()==v for p,v in before.items()),'full_program_passed':False,'scope':'chunk integrity/dedup fixtures, real public-runtime low-level fixture emission, and resource boundary fixtures; not five-window or full Shor acceptance'}
(out/'history-test-results.json').write_bytes((json.dumps(report,ensure_ascii=False,indent=2)+'\n').encode('utf-8'));(out/'history-unittest.txt').write_bytes(stream.getvalue().encode('utf-8'))
print(json.dumps({k:v for k,v in report.items() if k not in ('cases','source_byte_sha256')},ensure_ascii=False))
if not result.wasSuccessful():print(stream.getvalue())
raise SystemExit(0 if result.wasSuccessful() else 1)
