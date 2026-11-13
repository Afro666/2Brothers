"""History, consent and demand on synthetic rows shaped like `env/history.py` output."""

from datetime import datetime, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from store import audit, history

try:
    import mongomock
except ImportError:  # the `test` extra is not installed
    mongomock = None

KITCHENS = ("K01", "K02", "K03", "K04")
DAYS = ("2026-08-17", "2026-08-18", "2026-08-19")


def write_history(directory: Path) -> None:
    """Four kitchens, three days, one product: each kitchen uses 10 L and is 2 L short."""
    def ts(day, hour):
        return {"$date": f"{day}T{hour:02d}:00:00Z"}
    files = {
        "kitchens": [{"kitchen_id": k, "name": f"Test kitchen {k}", "type": "school"}
                     for k in KITCHENS],
        "stock": [{"ts": ts(d, 22), "meta": {"kitchen_id": k, "product_id": "900001"},
                   "unit": "L", "on_hand": 5.0, "received": 0.0, "used": 10.0, "short": 2.0,
                   "wasted": 0.0} for k in KITCHENS for d in DAYS],
        "covers": [{"ts": ts(d, 0), "meta": {"kitchen_id": k, "type": "school"}, "covers": 100,
                    "forecast_covers": 90, "open": True, "menu": []} for k in KITCHENS for d in DAYS],
        "orders": [{"ts": ts(DAYS[0], 14), "meta": {"kitchen_id": k}, "order_id": f"{k}-0001",
                    "delivery_date": ts(DAYS[1], 6), "total_eur": 30.5,
                    "lines": [{"product_id": "900001", "qty": 10, "sales_unit": "ST",
                               "unit_price": 3.05, "line_total": 30.5}]} for k in KITCHENS],
        "deliveries": [{"ts": ts(DAYS[1], 6), "meta": {"kitchen_id": k, "product_id": "900001"},
                        "order_id": f"{k}-0001", "ordered_qty": 10, "delivered_qty": 10,
                        "status": "full"} for k in KITCHENS],
    }
    for stem, rows in files.items():
        (directory / f"{stem}.jsonl").write_text("\n".join(json.dumps(row) for row in rows) + "\n")


class PureTests(unittest.TestCase):
    def test_money_from_the_generator_becomes_decimal(self):
        order = history._money({"total_eur": 30.5, "lines": [{"unit_price": 3.05, "line_total": 30.5}]})
        self.assertEqual(order["total_eur"], Decimal("30.5"))
        self.assertEqual(order["lines"][0]["unit_price"], Decimal("3.05"))

    def test_rows_are_read_with_timezone_aware_dates(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_history(Path(tmp))
            row = history._rows(Path(tmp) / "stock.jsonl")[0]
        self.assertEqual(row["ts"], datetime(2026, 8, 17, 22, tzinfo=timezone.utc))


@unittest.skipUnless(mongomock, "install the test extra: pip install -e '.[test]'")
class ConsentTests(unittest.TestCase):
    def setUp(self):
        self.db = mongomock.MongoClient(tz_aware=True)["test"]

    def test_consent_is_active_only_while_shared_and_not_revoked(self):
        history.set_sharing(self.db, "K01", "valio_aimo", True, "user-1")
        history.set_sharing(self.db, "K02", "valio_aimo", True, "user-2")
        history.set_sharing(self.db, "K02", "other", True, "user-2")
        self.assertEqual(history.consenting_kitchens(self.db, "valio_aimo"), ["K01", "K02"])
        revoked = history.set_sharing(self.db, "K02", "valio_aimo", False, "user-2")
        self.assertFalse(revoked["share_forecast"])
        self.assertIsNotNone(revoked["revoked_at"])
        self.assertEqual(revoked["granted_by"], "user-2")  # who granted it stays on record
        self.assertEqual(history.consenting_kitchens(self.db, "valio_aimo"), ["K01"])
        again = history.set_sharing(self.db, "K02", "valio_aimo", True, "user-3")
        self.assertIsNone(again["revoked_at"])
        self.assertEqual(again["scope"], "forecast_only")
        self.assertEqual(len(history.list_sharing(self.db, "K02")), 2)

    def test_every_consent_change_is_in_the_audit_log_with_who_and_when(self):
        history.set_sharing(self.db, "K01", "valio_aimo", True, "user-1")
        history.set_sharing(self.db, "K01", "valio_aimo", True, "user-9")   # already shared
        history.set_sharing(self.db, "K01", "valio_aimo", False, "user-2")
        history.set_sharing(self.db, "K01", "valio_aimo", False, "user-9")  # already revoked
        history.set_sharing(self.db, "K07", "valio_aimo", False, "user-9")  # never shared
        entries = audit.list_events(self.db, kitchen_id="K01")
        self.assertEqual([(e["event"]["type"], e["event"]["user"]) for e in entries],
                         [("share_granted", "user-1"), ("share_revoked", "user-2")])
        self.assertEqual(entries[0]["event"]["supplier_id"], "valio_aimo")
        self.assertEqual(entries[0]["event"]["scope"], "forecast_only")
        self.assertIsNotNone(entries[0]["stored_at"])
        self.assertTrue(audit.verify_chain(self.db)["ok"])
        self.assertEqual(history.list_sharing(self.db, "K01")[0]["revoked_by"], "user-2")
        self.assertEqual(history.list_sharing(self.db, "K07"), [])
        with self.assertRaises(ValueError):
            history.set_sharing(self.db, "K01", "valio_aimo", True, "")

    def test_demo_seed_leaves_every_fifth_kitchen_out(self):
        kitchens = [f"K{n:02d}" for n in range(1, 21)]
        sharing = history.seed_sharing(self.db, kitchens, "valio_aimo")
        self.assertEqual(len(sharing), 16)
        consenting = history.consenting_kitchens(self.db, "valio_aimo")
        self.assertEqual(consenting, sharing)
        for held_back in ("K05", "K10", "K15", "K20"):
            self.assertNotIn(held_back, consenting)
        self.assertEqual(history.list_sharing(self.db, "K01")[0]["granted_by"], "synthetic-seed")


@unittest.skipUnless(os.environ.get("STORE_LIVE_TESTS") == "1", "set STORE_LIVE_TESTS=1")
class LiveHistoryTests(unittest.TestCase):
    """Time-series collections need a real MongoDB: a throwaway database, dropped after."""

    @classmethod
    def setUpClass(cls):
        from store.db import get_db
        cls.db = get_db(f"two_brothers_test_{uuid4().hex[:8]}")

    @classmethod
    def tearDownClass(cls):
        cls.db.client.drop_database(cls.db.name)

    def test_history_loads_and_demand_sums_over_consenting_kitchens(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_history(Path(tmp))
            first = history.load_history(self.db, Path(tmp))
            second = history.load_history(self.db, Path(tmp))  # loading again must not duplicate
        self.assertEqual(first, second)
        self.assertEqual(first, {"kitchens": 4, "kitchen_stock": 12, "covers": 12,
                                 "orders_history": 4, "deliveries": 4})
        self.assertEqual(self.db.kitchen_stock.count_documents({}), 12)
        self.assertEqual(self.db.kitchen_stock.options()["timeseries"]["timeField"], "ts")
        self.assertEqual(self.db.orders_history.find_one()["total_eur"], Decimal("30.5"))

        one = history.kitchen_demand(self.db, "K01", "900001", DAYS[0], DAYS[1])
        self.assertEqual(one, [
            {"product_id": "900001", "date": DAYS[0], "unit": "L", "demand": 12.0, "kitchens": 1},
            {"product_id": "900001", "date": DAYS[1], "unit": "L", "demand": 12.0, "kitchens": 1}])

        self.assertEqual(history.supplier_demand(self.db, "valio_aimo", "900001", DAYS[0], DAYS[2]), [])
        history.set_sharing(self.db, "K01", "valio_aimo", True, "user-1")
        one = history.supplier_demand(self.db, "valio_aimo", "900001", DAYS[0], DAYS[0])
        self.assertEqual([(row["demand"], row["kitchens"]) for row in one], [(12.0, 1)])  # no floor
        history.set_sharing(self.db, "K02", "valio_aimo", True, "user-2")
        history.set_sharing(self.db, "K03", "valio_aimo", True, "user-3")
        history.set_sharing(self.db, "K03", "valio_aimo", False, "user-3")  # K03 changes its mind
        shared = history.supplier_demand(self.db, "valio_aimo", "900001", DAYS[0], DAYS[2])
        self.assertEqual([(row["date"], row["demand"], row["kitchens"]) for row in shared],
                         [(day, 24.0, 2) for day in DAYS])
        # Consenting kitchens are named; K03 (revoked) and K04 (never shared) appear nowhere.
        self.assertEqual(shared[0]["by_kitchen"], [
            {"kitchen_id": "K01", "kitchen_name": "Test kitchen K01", "demand": 12.0},
            {"kitchen_id": "K02", "kitchen_name": "Test kitchen K02", "demand": 12.0}])
        self.assertNotIn("by_kitchen", history.kitchen_demand(self.db, "K01", "900001",
                                                              DAYS[0], DAYS[0])[0])

        history.save_forecasts(self.db, [{"kitchen_id": k, "product_id": "900001",
                                          "date": "2026-11-16", "need": "14.5", "unit": "L",
                                          "why": "menu plan"} for k in KITCHENS])
        forecast = history.supplier_demand(self.db, "valio_aimo", "900001", "2026-11-16",
                                           "2026-11-16", source="forecast")
        self.assertEqual([(row["demand"], row["kitchens"]) for row in forecast],
                         [(Decimal("29.0"), 2)])


if __name__ == "__main__":
    unittest.main()
