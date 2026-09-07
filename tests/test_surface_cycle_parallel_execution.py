"""R9 public end-to-end assertions for the epoch trace."""
from collections import Counter
import json
from pathlib import Path
import unittest

from qec_schedule.hardware import load_hardware_config
from qec_schedule.simulation import run_cycle
from qec_schedule.trace import frame_at, metrics, validate_trace


CONFIG = Path(__file__).resolve().parents[1] / "configs/hardware_default.yaml"


class SurfaceCycleParallelExecutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.trace, cls.result = run_cycle(load_hardware_config(CONFIG))

    def test_public_cycle_is_epoch_centric_and_complete(self):
        self.assertEqual(self.trace["schema_version"], 2)
        self.assertTrue(validate_trace(self.trace))
        self.assertEqual(metrics(self.trace), self.result)
        self.assertEqual(self.result["physical_gate_count"], 104)
        self.assertEqual(self.result["max_cz_pairs_per_rydberg_epoch"], 6)
        self.assertEqual(self.result["max_measurement_batch_size"], 8)
        self.assertEqual(Counter(epoch["type"] for epoch in self.trace["epochs"])["RYDBERG"], 4)
        self.assertEqual(sum(epoch["pair_count"] for epoch in self.trace["epochs"]
                             if epoch["type"] == "RYDBERG"), 24)
        self.assertTrue(any(epoch["type"] == "AOD_MOVEMENT" and epoch["batch_size"] > 1
                            for epoch in self.trace["epochs"]))
        self.assertEqual(frame_at(self.trace, self.trace["duration"])["atoms"],
                         self.trace["final_state"]["atoms"])
        self.assertEqual(json.loads(json.dumps(self.trace))["epochs"], self.trace["epochs"])


if __name__ == "__main__":
    unittest.main()
