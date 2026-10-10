from pathlib import Path
import json
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'scripts'))
from shor17_factory_demo import build_world, extract_prefix
from na_pipeline.runtime import EventSession, FactoryFleet


class Shor17DemoIntakeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.layout = json.loads((ROOT/'artifacts/demos/shor17-four-factory-layout-20261009/layout.json').read_bytes())

    def test_exact_preview_coordinates_and_zero_ready_entry(self):
        device, req, world = build_world(self.layout)
        session = EventSession(device, world, run_id='test:shor17-intake')
        fleet = FactoryFleet(session, req, reserve_ready=4)
        starts = fleet.start_idle()
        self.assertEqual(len(world['atoms']), 769)
        self.assertEqual(len(starts), 4)
        self.assertTrue(all(s['target_patch'] is None for s in starts))
        self.assertEqual(fleet.inventory(), [])
        self.assertEqual(session.plans, [])
        self.assertEqual(len(fleet.available_data_patches()), 17)
        self.assertEqual({a['aod_group'] for a in world['atoms']}, {'data', 'magic'})

    def test_original_prefix_parameters_ids_and_factory_demand(self):
        source = Path(self.layout['source_files']['circuit.json']['path'])
        prefix = extract_prefix(source, self.layout)
        ops = prefix['operations']
        self.assertEqual([o['source_gate_index'] for o in ops], list(range(16)))
        self.assertEqual([(o['source_gate_index'], o['operation'], o['patches']) for o in ops
                          if o['operation'] in ('T', 'TDG')], [(11, 'TDG', ['q16']), (15, 'T', ['q16'])])
        self.assertFalse(prefix['full_shor'])
        self.assertIn('no_timer', prefix['factory_ready_policy'])


if __name__ == '__main__':
    unittest.main()
