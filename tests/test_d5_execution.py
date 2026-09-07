from pathlib import Path
import unittest

from qec_schedule.hardware import load_hardware_config
from qec_schedule.qec import create_code
from qec_schedule.simulation import run_cycle
from qec_schedule.trace import validate_epoch_trace


class DistanceFiveExecutionTests(unittest.TestCase):
    def test_expanded_configuration_runs_unbounded_dynamic_batches(self):
        root = Path(__file__).resolve().parents[1]
        config = load_hardware_config(root / "configs" / "hardware_d5.yaml")
        trace, result = run_cycle(config, code=create_code(distance=5))

        self.assertTrue(validate_epoch_trace(trace))
        self.assertEqual(result["physical_gate_count"], 336)
        self.assertEqual(result["rydberg_epoch_count"], 4)
        self.assertEqual(result["max_cz_pairs_per_rydberg_epoch"], 20)
        self.assertEqual(result["max_measurement_batch_size"], 24)
        self.assertEqual(result["aod_x_tones_max"], 20)
        self.assertEqual(result["diagnostic_counts"], {})
        zones = {zone["id"]: zone for zone in trace["initial_state"]["zones"]}
        self.assertIsNone(zones["entangling"]["entangling_geometry"]["max_parallel_pairs"])
        self.assertIsNone(zones["entangling"]["entangling_geometry"]["max_atoms"])
        self.assertIsNone(zones["measurement"]["measurement_geometry"]["max_parallel_atoms"])


if __name__ == "__main__":
    unittest.main()
