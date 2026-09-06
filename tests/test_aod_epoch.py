"""R6 AOD movement epoch IR tests."""
import unittest

from qec_schedule.execution import AODMovementEpoch
from qec_schedule.hardware import AODPlanner, AODController, Bounds, Position, Translation


class AODEpochTests(unittest.TestCase):
    def test_epoch_contains_one_shared_aod_resource_and_atom_locks(self):
        controller = AODController(8, 8, Bounds(0, 0, 50, 50))
        program = AODPlanner(controller).plan(
            (Translation("a", Position(1, 1), Position(5, 8)),
             Translation("b", Position(2, 2), Position(12, 9)))
        )
        epoch = AODMovementEpoch.create("epoch/aod/0", ("transport/a", "transport/b"), program)
        requirements = {requirement.resource: requirement.units for requirement in epoch.resource_requirements}
        self.assertEqual(requirements["device/aod"], 1)
        self.assertEqual(requirements["atom/a"], 1)
        self.assertEqual(requirements["atom/b"], 1)
        self.assertEqual(epoch.source_positions["a"], Position(1, 1))
        self.assertEqual(epoch.target_positions["b"], Position(12, 9))
        self.assertEqual(epoch.to_dict()["type"], "AOD_MOVEMENT")


if __name__ == "__main__":
    unittest.main()
