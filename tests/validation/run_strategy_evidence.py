"""Persist independent T604 regression and R8 case closure evidence."""
from hashlib import sha256
import io,json,sys,time,unittest
from pathlib import Path

root=Path(__file__).resolve().parents[2]
out=root/'knowledge/roles/R6/evidence/T604'


class Result(unittest.TextTestResult):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs); self.records=[]
    def addSuccess(self,test):
        super().addSuccess(test); self.records.append({'test':test.id(),'status':'passed'})
    def addFailure(self,test,err):
        super().addFailure(test,err); self.records.append({'test':test.id(),'status':'failed'})
    def addError(self,test,err):
        super().addError(test,err); self.records.append({'test':test.id(),'status':'error'})


def main():
    stream=io.StringIO(); started=time.perf_counter()
    suite=unittest.defaultTestLoader.discover(str(Path(__file__).parent),pattern='test_strategies.py')
    result=unittest.TextTestRunner(stream=stream,verbosity=2,resultclass=Result).run(suite)
    elapsed=time.perf_counter()-started
    (out/'unittest.txt').write_bytes(stream.getvalue().encode('utf-8'))
    cases=json.loads((root/'knowledge/roles/R8/enola-review-cases.json').read_text(encoding='utf-8'))['cases']
    closure=[]
    for case in cases:
        case_id=case['id']; matched=[r for r in result.records if 'test_'+case_id[:3]+'_' in r['test']]
        closure.append({'id':case_id,'status':'not_applicable' if case_id.startswith('K09') else 'passed' if matched and all(r['status']=='passed' for r in matched) else 'not_passed','tests':matched,'scope':case.get('scope','independent verifier negative case'),'fixture':True,'note':'Upstream codegen is not called by this function-kernel path' if case_id.startswith('K09') else 'Executed under R6 ownership; R8 original knowledge fixture remains unchanged'})
    source_paths=[*root.glob('src/na_pipeline/validation/*.py'),Path(__file__),Path(__file__).with_name('test_strategies.py')]
    report={'schema_version':'R6StrategyTestEvidence/0.1','kb_revision':'kb-0005','plan_revision':'plan-0007','tests_run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'passed':result.wasSuccessful(),'wall_seconds':elapsed,'python':sys.version,'executable':sys.executable,'cases':result.records,'R8_case_closure':closure,'inputs_sha256':sha256((out/'inputs.json.gz').read_bytes()).hexdigest(),'source_byte_sha256':{str(p.relative_to(root)):sha256(p.read_bytes()).hexdigest() for p in source_paths},'quantum_state_simulated':False,'hardware_executed':False}
    (out/'test-results.json').write_bytes((json.dumps(report,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
    print(stream.getvalue())
    print(json.dumps({k:v for k,v in report.items() if k not in ('cases','source_byte_sha256','R8_case_closure')},ensure_ascii=False,indent=2))
    return 0 if result.wasSuccessful() else 1


if __name__=='__main__': raise SystemExit(main())
