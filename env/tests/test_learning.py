import unittest

from env.chef import Chef, Habits, apply_truth
from env.learn import correction_ratio, declined
from env.learning_run import run_arm
from env.week import KitchenWeek


def row(pid="460478", kind="qty_changed", before=40, after=20, reason="TOO_MUCH", **extra):
    value = {"kind": kind, "product_id": pid, "from_qty": before, "to_qty": after,
             "reason": reason, "day": "2026-11-16"}
    value.update(extra)
    return value


class LearnTest(unittest.TestCase):
    def test_correction_ratio(self):
        rows = [row() for _ in range(4)]
        self.assertEqual(correction_ratio(rows, "460478"), 0.5)
        self.assertIsNone(correction_ratio([row(reason="IN_STOCK") for _ in range(4)], "460478"))
        self.assertIsNone(correction_ratio(rows[:2], "460478"))
        self.assertEqual(correction_ratio([row(after=8) for _ in range(3)], "460478"), 0.3)
        self.assertIsNone(correction_ratio(rows[:2] + [row(ran_out=True), row(ran_out=True)], "460478"))

    def test_declined(self):
        rows = [row(kind="line_removed", after=0) for _ in range(3)]
        self.assertEqual(declined(rows), {"460478"})
        self.assertEqual(declined([row(kind="line_removed", after=0, reason="IN_STOCK")
                                   for _ in range(3)]), set())


class ChefTest(unittest.TestCase):
    def setUp(self):
        self.env = KitchenWeek(seed=1, kitchen_type="restaurant")
        self.env.reset()
        self.habits = Habits.for_kitchen(self.env.kitchen, 1)

    def test_habits_are_deterministic(self):
        other = KitchenWeek(seed=1, kitchen_type="restaurant")
        other.reset()
        self.assertEqual(self.habits, Habits.for_kitchen(other.kitchen, 1))

    def test_habit_product_moves_toward_factor(self):
        pid = next(pid for pid, factor in self.habits.factor.items() if factor == 0.5)
        self.env.state.lots[pid] = []
        final, rows = Chef(self.habits, 1, noise=0).edit(self.env, {pid: 10})
        self.assertLess(final[pid], 10)
        self.assertEqual(rows[0]["reason"], "TOO_MUCH")

    def test_well_stocked_product_is_cut(self):
        pid = next(iter(self.habits.factor))
        apply_truth(self.env, self.habits)
        self.env.state.add(pid, 100000, self.env.today)
        final, rows = Chef(self.habits, 1, noise=0).edit(self.env, {pid: 10})
        self.assertEqual(final[pid], 0)
        self.assertEqual(rows[0]["reason"], "IN_STOCK")

    def test_noise_has_no_reason(self):
        pid = next(pid for pid in self.env.kitchen.products if pid not in self.habits.factor
                   and pid not in self.habits.removed)
        self.env.state.lots[pid] = []
        final, rows = Chef(self.habits, 1, noise=1).edit(self.env, {pid: 100})
        self.assertNotEqual(final[pid], 100)
        self.assertIsNone(rows[0]["reason"])

    def test_truth_changes_use_not_belief(self):
        pid = next(iter(self.habits.factor))
        day = self.env.start
        original = self.env.kitchen.usage_per_cover
        before = original(day)[pid]
        apply_truth(self.env, self.habits)
        self.assertEqual(self.env.kitchen.usage_per_cover(day)[pid], before * self.habits.factor[pid])
        self.assertEqual(self.env.believed_usage(day), original(day))


class LearningRunTest(unittest.TestCase):
    def test_learning_reduces_edits_without_more_habit_stockouts(self):
        plain = run_arm(seed=1, kitchen_type="restaurant", weeks=3, learning=False)
        learned = run_arm(seed=1, kitchen_type="restaurant", weeks=3, learning=True)
        self.assertLess(learned[2]["edits"], plain[2]["edits"])
        self.assertLessEqual(learned[2]["habit_stockout_days"], plain[2]["habit_stockout_days"])


if __name__ == "__main__":
    unittest.main()
