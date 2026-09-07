"""R7 resource sensitivity tests."""
from dataclasses import replace
from pathlib import Path
import unittest

from qec_schedule.hardware import build_initial_state, load_hardware_config
from qec_schedule.lowering import GateLowerer
from qec_schedule.qec import create_code
from qec_schedule.scheduler import RuntimeScheduler


CONFIG = Path(__file__).resolve().parents[1] / "configs/hardware_default.yaml"


class RuntimeResourceDegradationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = load_hardware_config(CONFIG)
        cls.code = create_code()
        cls.state = build_initial_state(cls.code, cls.config)
        cls.plan = GateLowerer().lower(cls.code.syndrome_round(), cls.state)

    def test_rydberg_pair_limit_splits_interaction_layers(self):
        trace = RuntimeScheduler(self.config, rydberg_parallel_pairs=3).run(self.plan, self.state)
        rydberg = [epoch for epoch in trace["epochs"] if epoch["type"] == "RYDBERG"]
        self.assertEqual(len(rydberg), 8)
        self.assertEqual({epoch["pair_count"] for epoch in rydberg}, {3})

    def test_measurement_capacity_splits_imaging(self):
        original = next(zone for zone in self.config.zones if zone.id == "measurement")
        geometry = replace(original.measurement_geometry, max_parallel_atoms=4)
        zones = tuple(replace(zone, capacity=4 if zone.id == "measurement" else zone.capacity,
                              measurement_geometry=geometry if zone.id == "measurement"
                              else zone.measurement_geometry)
                      for zone in self.config.zones)
        config = replace(self.config, zones=zones)
        state = build_initial_state(self.code, config)
        plan = GateLowerer().lower(self.code.syndrome_round(), state)
        trace = RuntimeScheduler(config).run(plan, state)
        imaging = [epoch for epoch in trace["epochs"] if epoch["type"] == "IMAGING"]
        self.assertEqual([epoch["measurement_batch_size"] for epoch in imaging], [4, 4])


if __name__ == "__main__":
    unittest.main()
