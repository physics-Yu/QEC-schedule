"""R11 regression tests for epoch metrics and scheduler diagnostics."""
import unittest

from qec_schedule.hardware import load_hardware_config
from qec_schedule.simulation import run_cycle
from qec_schedule.trace import metrics


class EpochMetricsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.trace, cls.result = run_cycle(load_hardware_config('configs/hardware_default.yaml'))

    def test_metrics_are_published_on_the_trace(self):
        self.assertEqual(self.trace['metrics'], self.result)
        self.assertEqual(metrics(self.trace), self.result)
        for key in (
            'total_execution_time_us', 'total_movement_time_us',
            'total_rydberg_time_us', 'total_imaging_time_us',
            'total_idle_time_us', 'mean_atoms_per_aod_epoch',
            'max_atoms_per_aod_epoch', 'mean_cz_pairs_per_rydberg_epoch',
            'max_cz_pairs_per_rydberg_epoch', 'mean_measurement_batch_size',
            'aod_x_tone_utilization', 'aod_y_tone_utilization',
            'entanglement_occupancy', 'measurement_occupancy',
            'diagnostic_counts',
        ):
            self.assertIn(key, self.result)
        for key in ('aod_utilization', 'rydberg_utilization', 'imaging_utilization',
                    'aod_x_tone_utilization', 'aod_y_tone_utilization',
                    'entanglement_occupancy', 'measurement_occupancy'):
            self.assertGreaterEqual(self.result[key], 0)
            self.assertLessEqual(self.result[key], 1)

    def test_each_dispatch_decision_exposes_batch_diagnostics(self):
        self.assertTrue(self.trace['decisions'])
        for decision in self.trace['decisions']:
            self.assertIn('ready_requests', decision)
            self.assertIn('selected', decision)
            self.assertEqual(decision['selected_count'], len(decision['selected']))
            self.assertEqual(decision['scheduled_request_count'], len(decision['selected']))
            self.assertEqual(decision['successful_batch_count'], decision['started'])
            self.assertEqual(decision['batch_size'], len(decision['selected']))
            self.assertEqual(decision['rejection_count'], len(decision['rejections']))
            self.assertIsInstance(decision['rejections'], list)


if __name__ == '__main__':
    unittest.main()
