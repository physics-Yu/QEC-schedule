"""Regression tests for uncapped default working-region parallelism."""
import unittest

from qec_schedule.hardware import load_hardware_config
from qec_schedule.simulation import run_cycle
from qec_schedule.trace import validate_trace


class UnboundedWorkingRegionTests(unittest.TestCase):
    def test_default_working_regions_have_no_geometry_parallel_caps(self):
        config = load_hardware_config('configs/hardware_default.yaml')
        entangling = next(zone for zone in config.zones if zone.id == 'entangling')
        measurement = next(zone for zone in config.zones if zone.id == 'measurement')
        self.assertIsNone(entangling.entangling_geometry.max_parallel_pairs)
        self.assertIsNone(entangling.entangling_geometry.max_atoms)
        self.assertIsNone(measurement.measurement_geometry.max_parallel_atoms)

        trace, result = run_cycle(config)
        self.assertTrue(validate_trace(trace))
        self.assertEqual(result['max_cz_pairs_per_rydberg_epoch'], 6)
        self.assertEqual(result['max_measurement_batch_size'], 8)
        self.assertEqual(trace['configuration']['zones'][2]['entangling_geometry']['max_atoms'], None)
        self.assertEqual(trace['configuration']['zones'][1]['measurement_geometry']['max_parallel_atoms'], None)


if __name__ == '__main__':
    unittest.main()
