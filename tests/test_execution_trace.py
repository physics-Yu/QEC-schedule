import copy
import json
import unittest
from qec_schedule.hardware import load_hardware_config
from qec_schedule.simulation import run_cycle
from qec_schedule.trace import validate_trace, metrics, frame_at


class TraceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = load_hardware_config('configs/hardware_default.yaml')
        cls.trace, cls.result = run_cycle(cls.config)

    def test_roundtrip_and_utilization(self):
        trace = json.loads(json.dumps(self.trace, allow_nan=False))
        self.assertTrue(validate_trace(trace))
        self.assertEqual(metrics(trace), self.result)
        self.assertTrue(all(0 <= u <= 1 + 1e-8 for u in self.result['resource_utilization'].values()))
        self.assertAlmostEqual(self.result['total_ready_wait_us'], self.result['blocked_task_time_us'])
        samples = self.result['physical_gate_parallelism']
        self.assertEqual(sum(s['N_executed'] for s in samples), self.result['physical_gate_count'])
        self.assertTrue(all(s['N_executed'] <= s['N_ready'] for s in samples))
        self.assertTrue(all(s['P'] is None or 0 <= s['P'] <= 1 for s in samples))
        self.assertEqual(self.result['max_pairs_per_pulse'], 2)

    def test_reject_overlap_dependency_and_capacity_corruption(self):
        trace = copy.deepcopy(self.trace)
        trace['resource_spans'].append(copy.deepcopy(next(s for s in trace['resource_spans'] if 'device/aod' in s['resources'])))
        with self.assertRaisesRegex(ValueError, 'capacity'):
            validate_trace(trace)
        trace = copy.deepcopy(self.trace)
        a = next(a for a in trace['actions'] if a['dependencies'])
        a['start_time'], a['end_time'] = 0, a['duration']
        with self.assertRaisesRegex(ValueError, 'Dependency'):
            validate_trace(trace)

    def test_move_interpolation_and_final_frame(self):
        a = next(a for a in self.trace['actions'] if a['type'] == 'MOVE')
        frame = frame_at(self.trace, (a['start_time'] + a['end_time']) / 2)
        atom = next(x for x in frame['atoms'] if x['atom_id'] == a['atoms'][0])
        for actual, start, end in zip(atom['position'], a['sources'][0]['position'], a['targets'][0]['position']):
            self.assertAlmostEqual(actual, (start + end) / 2)
        self.assertEqual(frame_at(self.trace, self.trace['duration'])['atoms'], self.trace['final_state']['atoms'])

    def test_three_rounds_and_alternative_primitive(self):
        for primitive in ('CZ', 'CNOT'):
            trace, result = run_cycle(self.config, rounds=3, primitive=primitive)
            self.assertTrue(validate_trace(trace))
            self.assertEqual(result['action_count'], 1320)
            self.assertEqual(sum(a['type'] == 'MEASURE' for a in trace['actions']), 24)

    def test_replaceable_code(self):
        from test_step1 import RepetitionCode
        trace, result = run_cycle(self.config, code=RepetitionCode())
        self.assertTrue(validate_trace(trace))
        self.assertEqual(sum(a['type'] == 'MEASURE' for a in trace['actions']), 2)
