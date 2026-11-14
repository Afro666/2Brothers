import unittest
from datetime import date, timedelta
import json
from pathlib import Path
from unittest.mock import patch

from env.covers import Current, RidgeCovers, ETSCovers, MODELS, SELECTED, demo_forecaster
from env.covers_backtest import feedback_value, report, run, select
from env.kitchens import make_kitchens
from signals.covers import CoverSignals


class CoversTest(unittest.TestCase):
    def setUp(self):
        self.kitchen = make_kitchens(20, 1)[10]
        self.start = date(2026, 8, 17)

    def test_point_in_time_and_kitchen_isolation(self):
        rows = [dict(kitchen_id=self.kitchen.id, date="2026-09-01", as_of="2026-08-31",
                     weather={"temperature_2m_max": 10}, reservations=100),
                dict(kitchen_id=self.kitchen.id, date="2026-09-01", as_of="2026-09-02",
                     weather={"temperature_2m_max": 99}, reservations=999),
                dict(kitchen_id="other", date="2026-09-01", as_of="2026-08-31", reservations=999)]
        signals = CoverSignals(self.kitchen, rows)
        rows[0]["weather"]["temperature_2m_max"] = 999
        day = date(2026, 9, 1)
        row = signals.snapshot(day, date(2026, 8, 31))
        self.assertEqual(row["reservations"], 100)
        self.assertEqual(row["weather"]["temperature_2m_max"], 10)
        self.assertEqual(signals.snapshot(day, date(2026, 8, 30)), {})

    def test_zero_and_unknown_are_different_and_calendar_is_present(self):
        day = date(2026, 12, 25)
        empty = CoverSignals(self.kitchen).features(day, day)
        known = CoverSignals(self.kitchen, [dict(kitchen_id=self.kitchen.id,
            date=day.isoformat(), as_of=day.isoformat(), reservations=0)]).features(day, day)
        self.assertEqual(empty[9], 1.)  # Finnish public holiday
        self.assertNotEqual(empty, known)
        school = make_kitchens(1, 1)[0]
        self.assertEqual(CoverSignals(school).features(date(2026, 10, 12), day)[10], 1.)

    def test_cold_start_closed_days_and_chronology(self):
        school = make_kitchens(1, 1)[0]
        model = RidgeCovers(school)
        self.assertEqual(model(self.start), Current(school)(self.start))
        self.assertEqual(model(date(2026, 8, 22)), 0.)
        model.observe(self.start, 300)
        with self.assertRaises(ValueError):
            model.observe(self.start, 999)
        with self.assertRaises(ValueError):
            model(self.start)

    def test_model_learns_bookings_without_future_revision(self):
        rows = []
        for i in range(70):
            day = self.start + timedelta(days=i)
            rows.append(dict(kitchen_id=self.kitchen.id, date=day.isoformat(),
                             as_of=(day - timedelta(days=1)).isoformat(),
                             reservations=(100 if i % 2 else 200)))
        model = RidgeCovers(self.kitchen, CoverSignals(self.kitchen, rows))
        for i in range(56):
            day = self.start + timedelta(days=i)
            covers = self.kitchen.base_covers * self.kitchen.factor(day) + (50 if i % 2 == 0 else -50)
            model.observe(day, covers)
        high, low = self.start + timedelta(days=56), self.start + timedelta(days=63)
        high_residual = model(high) - self.kitchen.base_covers * self.kitchen.factor(high)
        low_residual = model(low) - self.kitchen.base_covers * self.kitchen.factor(low)
        self.assertGreater(high_residual, low_residual + 20)
        revision = dict(kitchen_id=self.kitchen.id, date=high.isoformat(),
                        as_of=(high + timedelta(days=1)).isoformat(), reservations=100000)
        revised = RidgeCovers(self.kitchen, CoverSignals(self.kitchen, rows + [revision]))
        for d, c in model.history:
            revised.observe(d, c)
        self.assertEqual(revised(high), model(high))

    def test_rollout_is_deterministic(self):
        first = run(self.kitchen, RidgeCovers, 1, weeks=5)
        self.assertEqual(first, run(self.kitchen, RidgeCovers, 1, weeks=5))
        self.assertGreater(first["actual"], 0)
        self.assertAlmostEqual(first["cost_eur"], first["lost_covers"] * 4 + first["waste_eur"])

    def test_cost_gate_ignores_wape_and_requires_holdout(self):
        rows = [dict(seed=s, kitchen_type="hotel", model=m, cost_eur=c,
                     lost_covers=c, waste_eur=c, abs_error=100 if m == "ridge" else 0)
                for s in range(1, 7) for m, c in (("current", 100), ("ridge", 80), ("ets", 110))]
        self.assertEqual(select(rows)["hotel"], "ridge")
        self.assertEqual(select(rows, complete=False)["hotel"], "current")
        rows[-2]["cost_eur"] = 101
        self.assertEqual(select(rows)["hotel"], "current")

    def test_demo_uses_selected_model(self):
        with patch.dict(SELECTED, hotel="ridge"):
            self.assertIsInstance(demo_forecaster(self.kitchen), RidgeCovers)

    def test_unknown_calendar_and_boolean_measurements(self):
        day = date(2026, 9, 1)
        signals = CoverSignals(self.kitchen, [dict(kitchen_id=self.kitchen.id,
            date=day.isoformat(), as_of=day.isoformat(), is_school_holiday=None,
            occupancy=True, reservations=True, events_flag=True,
            weather={"temperature_2m_max": True, "precipitation_sum": None})])
        values = signals.features(day, day)
        self.assertEqual(values[11:15], [0., 0., 0., 0.])
        self.assertEqual(values[15:17], [1., 1.])
        self.assertEqual(values[17:], [0., 0., 0., 0.])

    def test_demo_signal_alias_is_joined_to_the_internal_kitchen(self):
        from demo.seed import build, DEMO_ID
        today = date(2026, 9, 7)
        seen = []
        class Inspect(Current):
            name = "inspect"
            def __init__(self, kitchen, signals=None):
                super().__init__(kitchen)
                seen.append(signals.snapshot(today, today).get("reservations"))
        with patch.dict(MODELS, inspect=Inspect), patch.dict(SELECTED, hotel="inspect"):
            build(seed=1, today=today, future_weeks=0, kitchens=10, signal_rows=[dict(
                kitchen_id=DEMO_ID, date=today.isoformat(), as_of=today.isoformat(), reservations=123)])
        self.assertEqual(seen, [123, 123])

    def test_demo_signal_rows_may_be_a_one_shot_iterator(self):
        from demo.seed import build, DEMO_ID
        today = date(2026, 9, 7)
        rows = [dict(kitchen_id=DEMO_ID, date=today.isoformat(), as_of=today.isoformat(), reservations=123)]
        seen = []
        class Inspect(Current):
            name = "inspect"
            def __init__(self, kitchen, signals=None):
                super().__init__(kitchen)
                seen.append(signals.snapshot(today, today).get("reservations"))
        outs = []
        with patch.dict(MODELS, inspect=Inspect), patch.dict(SELECTED, hotel="inspect"):
            for given in (rows, iter(rows)):
                outs.append(build(seed=1, today=today, future_weeks=0, kitchens=10, signal_rows=given))
        self.assertEqual(seen, [123, 123, 123, 123])
        self.assertEqual(outs[0], outs[1])

    def test_demo_explodes_selected_covers_into_recipe_quantities(self):
        from demo.seed import build, DEMO_ID

        class FixedCovers(Current):
            name = "fixed-test"

            def __call__(self, day):
                return 100 if self.kitchen.is_open(day) else 0

        today = date(2026, 9, 7)
        hotel = make_kitchens(10, 1)[9]
        with patch.dict(MODELS, {"fixed-test": FixedCovers}), patch.dict(SELECTED, hotel="fixed-test"):
            data = build(seed=1, today=today, future_weeks=0, kitchens=10)
        forecasts = [r for r in data["forecasts"] if r["kitchen_id"] == DEMO_ID and
                     r["date"] == today.isoformat()]
        self.assertTrue(forecasts)
        for row in forecasts:
            self.assertEqual(row["need"], round(100 * hotel.usage_per_cover(today).get(row["product_id"], 0), 3))
            self.assertIn("fixed-test", row["why"])

    def test_deployment_matches_completed_backtest(self):
        text = Path(__file__).parents[1].joinpath("BACKTEST.md").read_text(encoding="utf-8")
        section = text.split("## Covers models v2 (#433)", 1)[1]
        self.assertIn("Comparison: complete.", section)
        selection = json.loads(section.split("Selection: `", 1)[1].split("`", 1)[0])
        self.assertEqual(selection, SELECTED)

    def test_incomplete_report_does_not_claim_a_winner_or_chef_benefit(self):
        rows = [dict(seed=s, kitchen_type="hotel", model=m, cost_eur=100,
                     lost_covers=10, waste_eur=60, actual=100, abs_error=5)
                for s in range(1, 7) for m in ("current", "ridge")]
        text = report(rows, complete=False)
        self.assertIn("BLOCKED", text)
        self.assertIn("ETS not run", text)
        self.assertIn('"hotel": "current"', text)
        self.assertIn('"scored": 0', text)
        self.assertIn("hotel, ridge: 4, 5, 6", text)

    def test_ets_executes_statsmodels_when_available(self):
        try:
            import statsmodels  # noqa: F401
        except ImportError:
            self.skipTest("statsmodels unavailable; full comparison is blocked")
        model = ETSCovers(self.kitchen)
        for i in range(28):
            day = self.start + timedelta(days=i)
            model.observe(day, round(self.kitchen.base_covers * self.kitchen.factor(day)))
        self.assertGreaterEqual(model(self.start + timedelta(days=35)), 0)


class FeedbackTest(unittest.TestCase):
    def test_fva_better_worse_unmatched_and_units(self):
        row = dict(kitchen_id="k", proposal_id="p", product_id="milk", unit="L",
                   kind="qty_changed", from_qty=10, to_qty=15, ts="2026-09-01T00:00:00+00:00")
        outcome = dict(kitchen_id="k", proposal_id="p", product_id="milk", unit="L",
                       actual_qty=16, resolved_at="2026-09-03T00:00:00+00:00")
        result = feedback_value([dict(row, outcome=outcome),
                                 dict(row, to_qty=1, outcome=outcome), row,
                                 dict(row, outcome=dict(outcome, unit="KG")),
                                 dict(row, outcome=dict(outcome, resolved_at=row["ts"]))])
        self.assertEqual((result["scored"], result["unscorable"]), (2, 3))
        self.assertEqual((result["improved"], result["worsened"]), (1, 1))
        self.assertEqual(result["by_unit"]["L"]["fva"], -4)


if __name__ == "__main__":
    unittest.main()
