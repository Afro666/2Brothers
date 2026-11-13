import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from env.catalog import PRODUCTS
from env.history import generate
from env.kitchens import RECIPES, TYPES, make_kitchens
from env.sim import KitchenState


class CatalogTest(unittest.TestCase):
    def test_recipes_use_known_products(self):
        for recipe, items in RECIPES.items():
            for pid in items:
                self.assertIn(pid, PRODUCTS, recipe)

    def test_kitchen_mix(self):
        kitchens = make_kitchens(20, seed=1)
        types = {k.type.name for k in kitchens}
        self.assertEqual(types, set(TYPES))
        self.assertEqual(len({k.id for k in kitchens}), 20)


class StockTest(unittest.TestCase):
    def test_fifo_and_expiry(self):
        kitchen = make_kitchens(1, seed=1)[0]
        pid = kitchen.products[0]
        state = KitchenState(kitchen)
        state.add(pid, 2.0, date(2026, 9, 1), shelf_life=2)  # usable 1-2 Sep
        state.add(pid, 3.0, date(2026, 9, 1), shelf_life=5)
        self.assertEqual(state.consume(pid, 1.5), 1.5)
        self.assertEqual(state.expire(date(2026, 9, 2)), {pid: 0.5})
        self.assertAlmostEqual(state.on_hand(pid), 3.0)
        self.assertEqual(state.consume(pid, 10), 3.0)  # cannot serve more than stock


class HistoryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.tmp.name)
        cls.rows = generate(cls.out, seed=7, kitchens=20, weeks=3)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_files_written(self):
        for name in ("covers", "stock", "orders", "deliveries", "kitchens", "products", "recipes"):
            lines = (self.out / f"{name}.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertTrue(lines, name)
            json.loads(lines[0])

    def test_no_negative_stock(self):
        for r in self.rows["stock"]:
            for field in ("on_hand", "used", "short", "wasted", "received"):
                self.assertGreaterEqual(r[field], 0, r)

    def test_schools_closed_at_weekends(self):
        for c in self.rows["covers"]:
            if c["meta"]["type"] == "school":
                weekday = date.fromisoformat(c["ts"]["$date"][:10]).weekday()
                if weekday >= 5:
                    self.assertEqual(c["covers"], 0)

    def test_deterministic(self):
        with tempfile.TemporaryDirectory() as other:
            again = generate(Path(other), seed=7, kitchens=20, weeks=3)
        self.assertEqual(again["orders"], self.rows["orders"])

    def test_reference_serves_most_demand(self):
        used = sum(r["used"] for r in self.rows["stock"])
        short = sum(r["short"] for r in self.rows["stock"])
        self.assertLess(short / (used + short), 0.08)

    def test_do_nothing_runs_out(self):
        with tempfile.TemporaryDirectory() as other:
            rows = generate(Path(other), seed=7, kitchens=20, weeks=3, policy="do-nothing")
        used = sum(r["used"] for r in rows["stock"])
        short = sum(r["short"] for r in rows["stock"])
        self.assertGreater(short / (used + short), 0.5)
        self.assertEqual(rows["orders"], [])


if __name__ == "__main__":
    unittest.main()
