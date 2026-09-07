"""R5 axis execution and explicit trajectory tests."""
import unittest

from qec_schedule.hardware import AODPlanner, AODController, Bounds, Position, Translation


class AODAxisTrajectoryTests(unittest.TestCase):
    def setUp(self):
        self.movements = (Translation("a", Position(2, 2), Position(12, 12)),
                          Translation("b", Position(5, 5), Position(15, 15)))

    def test_simultaneous_duration_is_axis_maximum(self):
        controller = AODController(4, 4, Bounds(0, 0, 30, 30),
                                   max_speed_x=2, max_speed_y=5)
        program = AODPlanner(controller).plan(self.movements)
        self.assertEqual(program.duration, 5)
        self.assertTrue(all(t.start_time == 0 for t in program.x_trajectories + program.y_trajectories))

    def test_sequential_axis_modes_expose_orthogonal_phases(self):
        x_then_y = AODPlanner(AODController(4, 4, Bounds(0, 0, 30, 30),
                                             axis_execution="x_then_y", max_speed_x=2, max_speed_y=5)).plan(self.movements)
        y_then_x = AODPlanner(AODController(4, 4, Bounds(0, 0, 30, 30),
                                             axis_execution="y_then_x", max_speed_x=2, max_speed_y=5)).plan(self.movements)
        self.assertEqual(x_then_y.duration, 7)
        self.assertEqual(y_then_x.duration, 7)
        self.assertTrue(all(t.start_time == 5 for t in x_then_y.y_trajectories))
        self.assertTrue(all(t.start_time == 2 for t in y_then_x.x_trajectories))


if __name__ == "__main__":
    unittest.main()
