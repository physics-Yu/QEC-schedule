import json,unittest,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from na_pipeline.runtime.four_zone_layout import build_four_zone_layout,validate_layout,audit_obsolete_resources

class FourZoneTests(unittest.TestCase):
    def setUp(self):
        self.original=json.loads((ROOT/'artifacts/qualification/cnot-t-bottom-20261009/run-v1/layout.json').read_bytes())
    def test_layout_and_removal_preserve_data(self):
        d=build_four_zone_layout(self.original);self.assertTrue(validate_layout(d)['passed'])
        self.assertEqual([a['xy_um'] for a in d['atoms'] if a['aod_group']=='data'],[a['xy_um'] for a in self.original['atoms'] if a['aod_group']=='data'])
        self.assertEqual(len(self.original['atoms']),769)
    def test_live_Y_operation_cannot_be_dropped(self):
        with self.assertRaisesRegex(ValueError,'LIVE_SEMANTICS'):
            audit_obsolete_resources([('bad',{'nodes':[{'id':'gate-Y','kind':'gate','qubits':['F0:Y/d0']}]})])
    def test_feedback_on_removed_reset_cannot_be_dropped(self):
        with self.assertRaisesRegex(ValueError,'LIVE_SEMANTICS'):
            audit_obsolete_resources([('bad',{'nodes':[{'id':'reset-Y','kind':'reset','qubits':['F0:Y/d0'],'reads':['bit']}]})])
    def test_measurement_input_M_must_remain(self):
        d=build_four_zone_layout(self.original)
        for f in d['factories']:self.assertEqual(sum(a['patch']==f['id']+':M' for a in d['atoms']),17)
    def test_beam_resource_domains_are_distinct(self):
        d=build_four_zone_layout(self.original);r=d['device_resources']
        self.assertFalse(set(r['rydberg:data']['zones'])&set(r['rydberg:magic']['zones']))
        self.assertEqual(d['processor_interface']['purpose'],'T_injection_only')

if __name__=='__main__':unittest.main()
