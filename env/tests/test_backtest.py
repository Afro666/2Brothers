import unittest
from datetime import date

from env.backtest import SBA, WeekdayMA, backtest, report
from env.kitchens import make_kitchens


class MethodsTest(unittest.TestCase):
    def test_sba_on_intermittent_series(self):
        sba = SBA(None)
        day = date(2026, 9, 7)
        for d in [0, 0, 6, 0, 0, 6, 0, 0, 6]:  # 6 every third day = 2 per day
            sba.observe(day, 0, {"p": d})
        self.assertAlmostEqual(sba.use("p", day), (1 - 0.05) * 6 / 3, places=6)
        self.assertEqual(sba.use("unknown", day), 0.0)

    def test_weekday_ma_keeps_last_four(self):
        ma = WeekdayMA(None)
        monday = date(2026, 9, 7)
        for week, d in enumerate([1, 2, 3, 4, 100]):
            ma.observe(monday.replace(day=7 + 7 * week) if week < 4 else date(2026, 10, 5), 0, {"p": d})
        self.assertEqual(ma.use("p", date(2026, 10, 12)), (2 + 3 + 4 + 100) / 4)


class BacktestTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = backtest(seed=1, kitchens=6, weeks=6)

    def test_all_methods_and_classes(self):
        self.assertEqual(set(self.result), {"recipe", "weekday-ma4", "ma28", "croston-sba"})
        for r in self.result.values():
            self.assertIn("all", r["classes"])
            self.assertGreaterEqual(r["lost_covers"], 0)
            for c in r["classes"].values():
                self.assertGreaterEqual(c["wape"], 0)
                self.assertGreaterEqual(c["waste_eur"], 0)

    def test_menu_knowledge_beats_flat_average(self):
        self.assertLess(self.result["recipe"]["lost_covers"], self.result["ma28"]["lost_covers"])

    def test_deterministic(self):
        self.assertEqual(backtest(seed=1, kitchens=6, weeks=6), self.result)

    def test_report_renders(self):
        text = report([self.result])
        self.assertIn("Run-to-run noise", text)
        self.assertIn("| slow |", text)

    def test_kitchens_have_slow_movers(self):
        self.assertTrue(make_kitchens(6, 1))
        self.assertIn("slow", self.result["recipe"]["classes"])


if __name__ == "__main__":
    unittest.main()
