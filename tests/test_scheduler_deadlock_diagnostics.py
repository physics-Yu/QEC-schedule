"""R7 structured deadlock diagnostics."""
from dataclasses import replace
from pathlib import Path
import unittest

from qec_schedule.hardware import build_initial_state, load_hardware_config
from qec_schedule.lowering import GateLowerer
from qec_schedule.qec import create_code
from qec_schedule.scheduler import RuntimeScheduler, RuntimeSchedulingError


CONFIG = Path(__file__).resolve().parents[1] / "configs/hardware_default.yaml"


class RuntimeDeadlockDiagnosticsTests(unittest.TestCase):
    def test_zero_entangling_capacity_reports_structured_deadlock(self):
        config = load_hardware_config(CONFIG)
        zones = tuple(replace(zone, capacity=0) if zone.id == "entangling" else zone
                      for zone in config.zones)
        config = replace(config, zones=zones)
        state = build_initial_state(create_code(), config)
        plan = GateLowerer().lower(create_code().syndrome_round(), state)
        with self.assertRaises(RuntimeSchedulingError) as caught:
            RuntimeScheduler(config).run(plan, state)
        self.assertEqual(caught.exception.reason, "DEADLOCK")
        self.assertTrue(caught.exception.diagnostics["rejections"])
        self.assertTrue(any(item["reason"] == "ZONE_CAPACITY"
                            for item in caught.exception.diagnostics["rejections"]))


if __name__ == "__main__":
    unittest.main()
