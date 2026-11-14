"""Standing-order drift: the rules offline, the Atlas pipeline against a real cluster.

The live part runs with `STORE_LIVE_TESTS=1` (it needs `$dateTrunc` and
`$setWindowFields`, which mongomock does not have), in a throwaway database.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import os
import unittest
from uuid import uuid4

from bson.decimal128 import Decimal128

from store import drift

WEEK = datetime(2026, 11, 2, tzinfo=timezone.utc)  # a Monday


def row(qty_per_100, baseline_qty, spend_per_100=10, baseline_spend=10, weeks=4):
    return {"product_id": "462775", "week": WEEK, "unit": "ST",
            "qty_per_100": qty_per_100, "baseline_qty": baseline_qty,
            "spend_per_100": Decimal128(str(spend_per_100)),
            "baseline_spend": Decimal128(str(baseline_spend)), "baseline_weeks": weeks}


class FlagTests(unittest.TestCase):
    def test_portion_creep_is_flagged_with_the_numbers(self):
        warning = drift.flag(row(12.0, 10.0))
        self.assertEqual(warning["kind"], "portion_creep")
        self.assertEqual(warning["change"], 0.2)
        self.assertIn("12.0 ST per 100 guests", warning["why"])
        self.assertIn("+20%", warning["why"])

    def test_small_rates_keep_two_decimals_so_the_change_is_visible(self):
        """Live on 2026-11-14: 0.15 against 0.09 read "0.1 ... 0.1 ... (+63%)"."""
        warning = drift.flag(row(0.15, 0.092))
        self.assertIn("0.15 ST per 100 guests last week, 0.09 on average", warning["why"])
        self.assertIn("+63%", warning["why"])

    def test_cost_creep_when_the_amount_is_flat(self):
        warning = drift.flag(row(10.0, 10.0, spend_per_100="13.00", baseline_spend="10.00"))
        self.assertEqual(warning["kind"], "cost_creep")
        self.assertIn("price went up", warning["why"])

    def test_within_threshold_or_a_drop_is_not_drift(self):
        self.assertIsNone(drift.flag(row(11.0, 10.0)))
        self.assertIsNone(drift.flag(row(5.0, 10.0, spend_per_100=5)))

    def test_short_history_is_never_drift(self):
        self.assertIsNone(drift.flag(row(30.0, 10.0, weeks=2)))
        self.assertIsNone(drift.flag(row(30.0, None, weeks=None)))

    def test_zero_baseline_is_not_a_division_error(self):
        self.assertIsNone(drift.flag(row(5.0, 0, spend_per_100=0, baseline_spend=0)))


class PipelineShapeTests(unittest.TestCase):
    def test_pipeline_uses_atlas_time_series_stages(self):
        stages = [next(iter(stage)) for stage in drift.pipeline("k1", WEEK, WEEK)]
        self.assertEqual(stages[:3], ["$match", "$unwind", "$group"])
        self.assertIn("$lookup", stages)
        self.assertIn("$setWindowFields", stages)
        window = next(s for s in drift.pipeline("k1", WEEK, WEEK, baseline_weeks=3)
                      if "$setWindowFields" in s)["$setWindowFields"]
        self.assertEqual(window["output"]["baseline_qty"]["window"], {"documents": [-3, -1]})


@unittest.skipUnless(os.environ.get("STORE_LIVE_TESTS") == "1", "set STORE_LIVE_TESTS=1")
class LiveDriftTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from store.db import get_db
        from store.history import ensure_history_collections
        cls.db = get_db(f"two_brothers_test_{uuid4().hex[:8]}")
        ensure_history_collections(cls.db)
        # Five full weeks before `now`: milk flat at 10 per 100 guests, then 14 (portion
        # creep). Coffee flat in amount, but the last week costs 30% more (cost creep).
        cls.now = WEEK + timedelta(weeks=5, days=2)
        orders, covers = [], []
        for n in range(5):
            monday = WEEK + timedelta(weeks=n)
            milk = 28 if n == 4 else 20
            coffee_price = Decimal("13.00") if n == 4 else Decimal("10.00")
            for day in range(7):
                covers.append({"ts": monday + timedelta(days=day),
                               "meta": {"kitchen_id": "K01", "type": "hotel"}, "covers": 200 // 7
                               + (200 % 7 if day == 0 else 0)})
            orders.append({"ts": monday + timedelta(days=1, hours=14),
                           "meta": {"kitchen_id": "K01"}, "order_id": f"K01-{n}",
                           "lines": [{"product_id": "462775", "qty": milk, "sales_unit": "ST",
                                      "unit_price": Decimal128("2.57"),
                                      "line_total": Decimal128(str(Decimal("2.57") * milk))},
                                     {"product_id": "461332", "qty": 2, "sales_unit": "KI",
                                      "unit_price": Decimal128(str(coffee_price)),
                                      "line_total": Decimal128(str(coffee_price * 2))}]})
        # Another kitchen's creep must not show up for K01.
        orders.append({"ts": WEEK + timedelta(weeks=4, days=1), "meta": {"kitchen_id": "K02"},
                       "order_id": "K02-0", "lines": [{"product_id": "462775", "qty": 999,
                                                       "sales_unit": "ST",
                                                       "line_total": Decimal128("1")}]})
        cls.db.covers.insert_many(covers)
        cls.db.orders_history.insert_many(orders)

    @classmethod
    def tearDownClass(cls):
        cls.db.client.drop_database(cls.db.name)

    def test_finds_portion_and_cost_creep_in_the_last_full_week(self):
        warnings = drift.standing_order_drift(self.db, "K01", now=self.now)
        by_product = {w["product_id"]: w for w in warnings}
        self.assertEqual(set(by_product), {"462775", "461332"})
        self.assertEqual(by_product["462775"]["kind"], "portion_creep")
        self.assertAlmostEqual(by_product["462775"]["qty_per_100"], 14.0)
        self.assertAlmostEqual(by_product["462775"]["baseline_qty"], 10.0)
        self.assertEqual(by_product["462775"]["baseline_weeks"], 4)
        self.assertEqual(by_product["461332"]["kind"], "cost_creep")
        self.assertEqual(warnings[0]["product_id"], "462775")  # biggest change first

    def test_unknown_kitchen_has_no_warnings(self):
        self.assertEqual(drift.standing_order_drift(self.db, "nobody", now=self.now), [])


if __name__ == "__main__":
    unittest.main()
