"""R7 acceptance tests for semantic batching and epoch scheduling."""
from collections import Counter
from pathlib import Path
import unittest

from qec_schedule.hardware import build_initial_state, load_hardware_config
from qec_schedule.lowering import GateLowerer
from qec_schedule.qec import create_code
from qec_schedule.scheduler import RuntimeScheduler


CONFIG = Path(__file__).resolve().parents[1] / "configs/hardware_default.yaml"


class RuntimeBatchSchedulerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = load_hardware_config(CONFIG)
        cls.code = create_code()
        cls.state = build_initial_state(cls.code, cls.config)
        cls.plan = GateLowerer().lower(cls.code.syndrome_round(), cls.state)

    def test_default_scheduler_selects_six_pairs_per_interaction_slot(self):
        trace = RuntimeScheduler(self.config).run(self.plan, self.state)
        requests = self.plan.requests_by_id
        rydberg = [epoch for epoch in trace["epochs"] if epoch["type"] == "RYDBERG"]
        self.assertEqual(len(rydberg), 4)
        self.assertEqual([len(epoch["request_ids"]) for epoch in rydberg], [6, 6, 6, 6])
        self.assertEqual([sorted({requests[id].metadata["slot"] for id in epoch["request_ids"]})
                          for epoch in rydberg], [[0], [1], [2], [3]])

        movements = [epoch for epoch in trace["epochs"] if epoch["type"] == "AOD_MOVEMENT"]
        self.assertTrue(any(epoch["batch_size"] > 1 for epoch in movements))
        self.assertTrue(any(len({tuple(target[i] - source[i] for i in (0, 1))
                                 for atom, source in epoch["source_positions"].items()
                                 for target in [epoch["target_positions"][atom]]}) > 1
                          for epoch in movements if epoch["batch_size"] > 1))

        imaging = [epoch for epoch in trace["epochs"] if epoch["type"] == "IMAGING"]
        self.assertEqual([epoch["measurement_batch_size"] for epoch in imaging], [8])
        self.assertEqual(Counter(atom["zone"] for atom in trace["final_state"]["atoms"]),
                         Counter({"storage": 17, "reservoir": 4}))
        self.assertFalse(any(epoch["purpose"] == "RETURN_AFTER_ENTANGLE"
                             for epoch in trace["epochs"]))


if __name__ == "__main__":
    unittest.main()
