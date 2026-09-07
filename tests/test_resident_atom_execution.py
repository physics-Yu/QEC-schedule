"""R8 acceptance tests for multi-layer resident atoms."""
from pathlib import Path
import unittest

from qec_schedule.hardware import build_initial_state, load_hardware_config
from qec_schedule.lowering import GateLowerer
from qec_schedule.qec import create_code
from qec_schedule.scheduler import RuntimeScheduler


CONFIG = Path(__file__).resolve().parents[1] / "configs/hardware_default.yaml"


class ResidentAtomExecutionTests(unittest.TestCase):
    def test_interaction_layers_keep_residents_until_lifecycle_boundary(self):
        config = load_hardware_config(CONFIG)
        code = create_code()
        state = build_initial_state(code, config)
        plan = GateLowerer().lower(code.syndrome_round(), state)
        trace = RuntimeScheduler(config).run(plan, state)

        rydberg = [epoch for epoch in trace["epochs"] if epoch["type"] == "RYDBERG"]
        self.assertEqual(len(rydberg), 4)
        snapshots = {snapshot["epoch_id"]: snapshot["state"]
                     for snapshot in trace["state_snapshots"] if snapshot["epoch_id"]}
        for epoch in rydberg:
            residents = [atom for atom in snapshots[epoch["id"]]["atoms"]
                         if atom["zone"] == "entangling"]
            self.assertGreaterEqual(len(residents), 10)

        self.assertFalse(any(epoch["purpose"] == "RETURN_AFTER_ENTANGLE"
                             for epoch in trace["epochs"]))
        self.assertTrue(any(epoch["purpose"] == "RETURN_DATA"
                            for epoch in trace["epochs"]))
        self.assertTrue(any(epoch["purpose"] == "FINAL_RETURN"
                            for epoch in trace["epochs"]))


if __name__ == "__main__":
    unittest.main()
