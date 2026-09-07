"""R6 batched Rydberg epoch tests."""
from pathlib import Path
import unittest

from qec_schedule.compiler import EntangleRequest
from qec_schedule.execution import RydbergEpoch
from qec_schedule.hardware import Position, build_initial_state, load_hardware_config
from qec_schedule.lowering import GateLowerer
from qec_schedule.planner import PairPlacement, SpatialPlanner
from qec_schedule.qec import create_code


CONFIG = Path(__file__).resolve().parents[1] / "configs/hardware_default.yaml"


class RydbergEpochTests(unittest.TestCase):
    def test_six_entangle_requests_become_one_epoch(self):
        config = load_hardware_config(CONFIG)
        code = create_code()
        state = build_initial_state(code, config)
        plan = GateLowerer().lower(code.syndrome_round(), state)
        requests = tuple(request for request in plan.requests
                         if isinstance(request, EntangleRequest) and request.metadata["slot"] == 0)
        placements = SpatialPlanner().plan_entanglement(requests, state)
        epoch = RydbergEpoch.create("epoch/rydberg/0", requests, placements)
        self.assertEqual(len(epoch.pairs), 6)
        self.assertEqual(len(epoch.request_ids), 6)
        self.assertEqual(sum(requirement.resource == "device/rydberg" for requirement in epoch.resource_requirements), 1)
        self.assertEqual(len([requirement for requirement in epoch.resource_requirements
                              if requirement.resource.startswith("atom/")]), 12)
        self.assertEqual(epoch.to_dict()["pairs"], [list(pair) for pair in epoch.pairs])

    def test_overlapping_pairs_are_rejected(self):
        request = EntangleRequest("r", "r", ("a", "b"), ())
        bad = PairPlacement("r", "a", "b", Position(0, 0), Position(1, 0))
        # Use two requests with one shared atom to exercise epoch validation.
        other = EntangleRequest("s", "s", ("b", "c"), ())
        other_bad = PairPlacement("s", "b", "c", Position(3, 0), Position(4, 0))
        with self.assertRaises(ValueError):
            RydbergEpoch.create("epoch/rydberg/bad", (request, other), (bad, other_bad))


if __name__ == "__main__":
    unittest.main()
