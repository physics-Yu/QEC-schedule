"""R6 batched imaging epoch tests."""
from pathlib import Path
import unittest

from qec_schedule.compiler import MeasureRequest
from qec_schedule.execution import ImagingEpoch
from qec_schedule.hardware import build_initial_state, load_hardware_config
from qec_schedule.lowering import GateLowerer
from qec_schedule.planner import SpatialPlanner
from qec_schedule.qec import create_code


CONFIG = Path(__file__).resolve().parents[1] / "configs/hardware_default.yaml"


class ImagingEpochTests(unittest.TestCase):
    def test_eight_measure_requests_become_one_imaging_epoch(self):
        config = load_hardware_config(CONFIG)
        code = create_code()
        state = build_initial_state(code, config)
        plan = GateLowerer().lower(code.syndrome_round(), state)
        requests = tuple(request for request in plan.requests if isinstance(request, MeasureRequest))
        placements = SpatialPlanner().plan_measurement(requests, state)
        epoch = ImagingEpoch.create("epoch/imaging/0", requests, placements)
        self.assertEqual(len(epoch.atoms), 8)
        self.assertEqual(len(epoch.measurement_keys), 8)
        self.assertEqual(sum(requirement.resource == "device/imaging" for requirement in epoch.resource_requirements), 1)
        self.assertEqual(len([requirement for requirement in epoch.resource_requirements
                              if requirement.resource.startswith("atom/")]), 8)
        self.assertEqual(epoch.to_dict()["type"], "IMAGING")


if __name__ == "__main__":
    unittest.main()
