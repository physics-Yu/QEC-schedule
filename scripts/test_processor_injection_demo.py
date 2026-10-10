import unittest
from copy import deepcopy
from types import SimpleNamespace
from run_processor_injection_demo import read,OUT,execute

class InjectionTests(unittest.TestCase):
    def load(self,m):
        d=read(OUT/f'branch-{m}-plan.json.gz');tr=read(OUT/f'branch-{m}-trace.json.gz')
        return SimpleNamespace(initial=d['initial'],actions=d['actions'],lifecycle=tr['lifecycle'],branch=m),d['metadata']
    def test_both_complete_branches(self):
        for m in (0,1):
            p,meta=self.load(m);self.assertTrue(execute(p,meta)[1]['passed'])
    def test_missing_S_rejected(self):
        p,meta=self.load(1);p.actions=[a for a in p.actions if a['payload']['phase']!='条件 S-SE']
        with self.assertRaisesRegex(AssertionError,'CORRECTION_SOURCE_ACTION_MISSING'):execute(p,meta)
    def test_wrong_CNOT_pair_rejected(self):
        p,meta=self.load(0);a=next(a for a in p.actions if a['payload'].get('name')=='CZ' and a['payload']['phase']=='横向逻辑 CNOT');a['payload']['pairs'].pop()
        with self.assertRaisesRegex(AssertionError,'INJECTION_CNOT_CHANGED'):execute(p,meta)
    def test_missing_handoff_rejected(self):
        p,meta=self.load(0);p.actions=[a for a in p.actions if not(a['kind']=='handoff' and a['payload']['owner_to']=='data')]
        with self.assertRaisesRegex(AssertionError,'AOD_OWNER'):execute(p,meta)
    def test_duplicate_consumption_rejected(self):
        p,meta=self.load(0);p.lifecycle.append(deepcopy(next(e for e in p.lifecycle if e['event']=='magic_token_consumed_once')))
        with self.assertRaises(AssertionError):execute(p,meta)
    def test_wrong_declared_measurement_branch_rejected(self):
        p,meta=self.load(0);a=next(a for a in p.actions if a['payload'].get('writes')==['magic-z-0']);a['payload']['measurement_value']=1
        with self.assertRaises(AssertionError):execute(p,meta)

if __name__=='__main__':unittest.main()
