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
        self.assertEqual(self.result['max_cz_pairs_per_rydberg_epoch'], 6)
        self.assertEqual(self.result['max_measurement_batch_size'], 8)
        self.assertGreater(self.result['max_atoms_per_aod_epoch'], 1)
        self.assertEqual(sum(epoch['pair_count'] for epoch in self.trace['epochs']
                             if epoch['type'] == 'RYDBERG'), 24)

    def test_reject_overlap_dependency_and_capacity_corruption(self):
        trace = copy.deepcopy(self.trace)
        trace['resource_spans'].append(copy.deepcopy(trace['resource_spans'][0]))
        with self.assertRaisesRegex(ValueError, 'Duplicate resource span'):
            validate_trace(trace)
        trace = copy.deepcopy(self.trace)
        epoch = next(epoch for epoch in trace['epochs'] if epoch['dependencies'])
        epoch['start_time'], epoch['end_time'] = 0, epoch['duration']
        with self.assertRaisesRegex(ValueError, 'dependency'):
            validate_trace(trace)

    def test_move_interpolation_and_final_frame(self):
        epoch = next(epoch for epoch in self.trace['epochs'] if epoch['type'] == 'AOD_MOVEMENT')
        frame = frame_at(self.trace, (epoch['start_time'] + epoch['end_time']) / 2)
        atom_id = epoch['atoms'][0]
        atom = next(x for x in frame['atoms'] if x['atom_id'] == atom_id)
        for actual, start, end in zip(atom['position'], epoch['source_positions'][atom_id], epoch['target_positions'][atom_id]):
            self.assertAlmostEqual(actual, (start + end) / 2)
        self.assertEqual(frame_at(self.trace, self.trace['duration'])['atoms'], self.trace['final_state']['atoms'])

    def test_three_rounds_and_alternative_primitive(self):
        for primitive in ('CZ', 'CNOT'):
            trace, result = run_cycle(self.config, rounds=3, primitive=primitive)
            self.assertTrue(validate_trace(trace))
            self.assertEqual(result['physical_gate_count'], 312 if primitive == 'CZ' else 168)
            self.assertEqual(sum(epoch['type'] == 'IMAGING' for epoch in trace['epochs']), 3)

    def test_replaceable_code(self):
        from test_step1 import RepetitionCode
        trace, result = run_cycle(self.config, code=RepetitionCode())
        self.assertTrue(validate_trace(trace))
        self.assertEqual(result['max_measurement_batch_size'], 2)
        self.assertEqual(sum(epoch['type'] == 'IMAGING' for epoch in trace['epochs']), 1)
