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
                         {'typo': 1}):
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
