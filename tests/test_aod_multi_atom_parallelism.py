"""R5 regression test: unequal 2-D displacements can share one AOD program."""
import unittest

from qec_schedule.hardware import AODPlanner, AODController, Bounds, Position, Translation


class AODMultiAtomParallelismTests(unittest.TestCase):
    def test_twelve_unequal_vectors_fit_one_program(self):
        controller = AODController(12, 12, Bounds(0, 0, 100, 100),
                                   axis_execution="simultaneous", max_speed_x=2, max_speed_y=4)
        translations = tuple(
            Translation(f"a{index}", Position(10 + 3 * index, 10 + index),
                        Position(20 + 3 * index + index % 3, 40 + index * 2))
            for index in range(12)
        )
        program = AODPlanner(controller).plan(translations)
        self.assertEqual(program.atoms, tuple(f"a{index}" for index in range(12)))
        self.assertGreater(len({translation.displacement for translation in translations}), 1)
        self.assertGreater(len(program.x_trajectories), 1)
        self.assertGreater(len(program.y_trajectories), 1)
        self.assertEqual(program.x_tones_used, 12)
        self.assertEqual(program.y_tones_used, 12)
        self.assertEqual(program.duration, max(20 / 2, 41 / 4))

    def test_same_vector_is_not_required_for_parallelism(self):
        controller = AODController(4, 4, Bounds(0, 0, 30, 30))
        movements = (Translation("a", Position(1, 1), Position(4, 8)),
                     Translation("b", Position(2, 2), Position(12, 9)))
        self.assertTrue(controller.compatible(movements))


if __name__ == "__main__":
    unittest.main()
