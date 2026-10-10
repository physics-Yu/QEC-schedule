"""Persist T601 tests and small mutated fixtures under the R6 write scope."""
import io
import json
from pathlib import Path
import sys
import time
import unittest

from test_validation import fixture, action, pickup
from na_pipeline.validation import validate

out = Path(__file__).resolve().parents[2] / 'knowledge' / 'roles' / 'R6' / 'evidence'
out.mkdir(parents=True, exist_ok=True)

class Result(unittest.TextTestResult):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.records=[]
    def addSuccess(self,test):
        super().addSuccess(test); self.records.append({'test':test.id(),'status':'passed'})
    def addFailure(self,test,err):
        super().addFailure(test,err); self.records.append({'test':test.id(),'status':'failed'})
    def addError(self,test,err):
        super().addError(test,err); self.records.append({'test':test.id(),'status':'error'})

stream=io.StringIO()
suite=unittest.defaultTestLoader.discover(str(Path(__file__).parent),pattern='test_validation.py')
started=time.perf_counter()
result=unittest.TextTestRunner(stream=stream,verbosity=2,resultclass=Result).run(suite)
elapsed=time.perf_counter()-started
(out/'unittest.txt').write_bytes(stream.getvalue().encode('utf-8'))
test_report={'kb_revision':'kb-0004','contract':'IF-MVP-001/0.2.1-draft','tests_run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'wall_seconds':elapsed,'python':sys.version,'executable':sys.executable,'cases':result.records}
(out/'test-results.json').write_bytes((json.dumps(test_report,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
examples=[]
p,d=fixture([[0.,0.],[2.,0.],[4.,0.]])
action(p,'gate',['a0','a1','a2'],0,1,{'name':'CZ','broadcast':True,'zone_id':'storage_entanglement','pairs':[['a0','a1'],['a1','a2']]})
examples.append(('all-geometric-edges-but-multibody',p,d,'MULTIBODY_BROADCAST_UNSUPPORTED'))
p,d=fixture([[0.,0.],[10.,10.]])
pickup(p,0,0,'r0','c0'); pickup(p,1,200,'r1','c1')
action(p,'move',['a0','a1'],400,410,{'aod_group':'data','interpolation':'linear','trajectories':[{'atom_id':'a0','from_um':[0.,0.],'to_um':[10.,0.],'row_id':'r0','column_id':'c0'},{'atom_id':'a1','from_um':[10.,10.],'to_um':[0.,10.],'row_id':'r1','column_id':'c1'}]})
examples.append(('axis-order-crossing-with-disjoint-atom-paths',p,d,'AXIS_CROSSING'))
p,d=fixture([[0.,0.]])
pickup(p,0,0,'r0','c0')
action(p,'drop',['a0'],200,400,{'from_trap_id':'ad0','to_trap_id':'missing-trap','aod_group':'data','row_id':'r0','column_id':'c0','position_um':[0.,0.]})
examples.append(('wrong-drop-target',p,d,'DROP_TARGET'))
payload=[]
for name,p,d,expected in examples:
    report=validate(p,d)
    payload.append({'id':name,'fixture':True,'expected_failure':expected,'device':d,'atom_program':p,'report':report})
    if expected not in {failure['code'] for failure in report['failures']}:
        raise AssertionError(name)
(out/'rejected-fixtures.json').write_bytes((json.dumps(payload,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
print(json.dumps({key:value for key,value in test_report.items() if key!='cases'},indent=2))
raise SystemExit(0 if result.wasSuccessful() else 1)
