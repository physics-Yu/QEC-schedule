"""R5 tone-budget and spacing checks."""
import unittest

from qec_schedule.hardware import AODPlanner, AODController, Bounds, Position, Translation


class AODToneBudgetTests(unittest.TestCase):
    def test_x_and_y_budgets_are_checked_independently(self):
        movements = (Translation("a", Position(1, 1), Position(5, 3)),
                     Translation("b", Position(2, 2), Position(8, 9)),
                     Translation("c", Position(3, 3), Position(12, 15)))
        with self.assertRaisesRegex(ValueError, "TONE_BUDGET_X"):
            AODPlanner(AODController(2, 3, Bounds(0, 0, 20, 20))).plan(movements)
        with self.assertRaisesRegex(ValueError, "TONE_BUDGET_Y"):
            AODPlanner(AODController(3, 2, Bounds(0, 0, 20, 20))).plan(movements)

    def test_ordering_rule_rejects_line_crossing(self):
        movements = (Translation("a", Position(1, 1), Position(10, 10)),
                     Translation("b", Position(2, 2), Position(5, 5)))
        controller = AODController(4, 4, Bounds(0, 0, 20, 20))
        with self.assertRaisesRegex(ValueError, "AOD_ORDERING"):
            AODPlanner(controller).plan(movements)
        permissive = AODController(4, 4, Bounds(0, 0, 20, 20), ordering_rule="none")
        self.assertTrue(permissive.compatible(movements))


if __name__ == "__main__":
    unittest.main()
