import json
from pathlib import Path
import tempfile
import unittest
from qec_schedule.hardware import load_hardware_config
from qec_schedule.sweep import apply_overrides, load_sweep, run_sweep


class SweepTests(unittest.TestCase):
    def setUp(self):
        self.config = load_hardware_config('configs/hardware_default.yaml')

    def test_invalid_parameters_fail_before_output(self):
        for override in ({'timing': {'move_speed': 0}}, {'aod': {'max_x_tones': True}},
                         {'zone_capacities': {'typo': 2}}, {'devices': {'device/aod': 0}},
                         {'rydberg_parallel_pairs': 0},
                         {'entanglement': {'max_parallel_pairs': 0}},
                         {'measurement': {'typo': 4}}, {'typo': 1}):
            with self.assertRaises(ValueError):
                apply_overrides(self.config, override)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                run_sweep(self.config, [{'id': '../escape', 'overrides': {}}], directory)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_baseline_speed_and_reproducibility(self):
        cases = load_sweep('configs/sweep_default.yaml')[:3]
        with tempfile.TemporaryDirectory() as directory:
            rows = run_sweep(self.config, cases, directory)
            self.assertGreater(rows[1]['total_execution_time_us'], rows[0]['total_execution_time_us'])
            self.assertLess(rows[2]['total_execution_time_us'], rows[0]['total_execution_time_us'])
            self.assertEqual(json.loads((Path(directory) / 'sweep.json').read_text())['results'], rows)
            for case in cases:
                self.assertTrue((Path(directory) / case['id'] / 'trace.json').exists())
            self.assertTrue((Path(directory) / 'sweep.csv').exists())
        self.assertEqual(self.config.timing.move_speed, 1)

    def test_resource_limits_change_epoch_metrics_and_rows_keep_configuration(self):
        cases = [
            {'id': 'baseline', 'overrides': {}},
            {'id': 'tone_limited', 'overrides': {'aod': {'max_x_tones': 1, 'max_y_tones': 1}}},
            {'id': 'pair_limited', 'overrides': {'rydberg_parallel_pairs': 3}},
            {'id': 'measurement_limited', 'overrides': {'measurement': {'max_parallel_atoms': 4}}},
        ]
        with tempfile.TemporaryDirectory() as directory:
            rows = run_sweep(self.config, cases, directory)
        result = {row['case']: row for row in rows}
        self.assertGreater(result['tone_limited']['movement_epoch_count'],
                           result['baseline']['movement_epoch_count'])
        self.assertGreater(result['tone_limited']['total_execution_time_us'],
                           result['baseline']['total_execution_time_us'])
        self.assertGreater(result['pair_limited']['rydberg_epoch_count'],
                           result['baseline']['rydberg_epoch_count'])
        self.assertEqual(result['pair_limited']['max_cz_pairs_per_rydberg_epoch'], 3)
        self.assertGreater(result['measurement_limited']['imaging_epoch_count'],
                           result['baseline']['imaging_epoch_count'])
        self.assertEqual(result['measurement_limited']['max_measurement_batch_size'], 4)
        for row in rows:
            self.assertIsInstance(row['configuration'], dict)
            self.assertIn('timing', row['configuration'])
            self.assertIn('aod', row['configuration'])
            self.assertIn('zones', row['configuration'])
            self.assertIn('diagnostic_counts', row)
            self.assertIn('decision_count', row)
            self.assertIn('infeasibility_diagnostics', row)
            self.assertIn('aod_x_tone_utilization', row)
            self.assertIn('aod_y_tone_utilization', row)
            self.assertIn('entanglement_occupancy', row)
            self.assertIn('measurement_occupancy', row)
