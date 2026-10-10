"""Reporting for T604; strategy evidence never inherits old slice acceptance."""
from .checker import _hash


class StrategyAudit:
    def __init__(self,kind,inputs):
        self.kind,self.inputs=kind,inputs
        self.failures=[]; self.unverified=[]; self.checks=[]; self.metrics={}

    def fail(self,code,message,**where):
        self.failures.append({'code':code,'message':message,**where})

    def need(self,code,message,**where):
        self.unverified.append({'code':code,'message':message,**where})

    def check(self,name,fn):
        before=len(self.failures); pending=len(self.unverified)
        try: value=fn()
        except (KeyError,ValueError,TypeError,IndexError,AttributeError) as exc:
            self.fail('STRATEGY_FIELD_INVALID',f'{type(exc).__name__}: {exc}',check=name)
            value=None
        self.checks.append({'id':name,'status':'failed' if len(self.failures)>before else 'unverified' if len(self.unverified)>pending else 'passed'})
        return value

    def report(self):
        hashes={}
        for key,value in self.inputs.items():
            if value is not None:
                try: hashes[key]=_hash(value)
                except (ValueError,TypeError): self.fail('NON_JSON_INPUT',f'{key} must be finite JSON')
        return {'schema_version':'StrategyValidationReport/0.1.0','artifact_id':f'R6/{self.kind}/{_hash(hashes)[:20]}',
                'provenance':{'producer':'R6','task':'T604','kb_revision':'kb-0005','plan_revision':'plan-0007'},
                'scope':self.kind,'passed':not self.failures and not self.unverified,'scoped_pass':not self.failures,
                'checks':self.checks,'failures':self.failures,'unverified':self.unverified,'metrics':self.metrics,'input_hashes':hashes,
                'quantum_state_simulated':False,'hardware_executed':False,'sampled':False,
                'out_of_scope':['noise','fault_tolerance','physical_hardware','factory_production','full_Shor','user_visual_acceptance']}
