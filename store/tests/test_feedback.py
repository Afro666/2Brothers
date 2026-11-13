"""Feedback rows and stock counts. mongomock offline; time-series creation is checked live."""

from datetime import datetime, timezone
from decimal import Decimal
import os
import unittest
from uuid import uuid4

from store import feedback, history

try:
    import mongomock
except ImportError:  # the `test` extra is not installed
    mongomock = None

EDITS = [
    {"kind": "qty_changed", "product_id": "900001", "from_qty": "40", "to_qty": "60", "unit": "L"},
    {"kind": "line_removed", "product_id": "900002", "from_qty": "5", "unit": "KG"},
    {"kind": "line_added", "product_id": "900003", "to_qty": "2", "unit": "PCS"},
    {"kind": "approved"},
]


class Scenarios:
    """Shared by the offline (mongomock) and live (Atlas) runs."""

    def k(self, n: int) -> str:
        """A kitchen id of this test only: the live run shares one database."""
        return f"{self._testMethodName}-k{n}"

    def test_an_edited_and_approved_proposal_leaves_one_row_per_change(self):
        self.assertEqual(feedback.record_feedback(self.db, self.k(1), "prop-1", EDITS, "chef-1"), 4)
        feedback.record_feedback(self.db, self.k(2), "prop-9", [{"kind": "approved"}], "chef-2")
        rows = feedback.list_feedback(self.db, self.k(1), proposal_id="prop-1")
        self.assertEqual(sorted(row["kind"] for row in rows),
                         ["approved", "line_added", "line_removed", "qty_changed"])
        changed = next(row for row in rows if row["kind"] == "qty_changed")
        self.assertEqual((changed["from_qty"], changed["to_qty"]), (Decimal("40"), Decimal("60")))
        self.assertEqual((changed["product_id"], changed["unit"], changed["user"]),
                         ("900001", "L", "chef-1"))
        self.assertEqual(changed["kitchen_id"], self.k(1))
        self.assertEqual(len(feedback.list_feedback(self.db, self.k(1), product_id="900002")), 1)
        self.assertEqual(len(feedback.list_feedback(self.db, self.k(2))), 1)  # kitchens stay apart

    def test_a_rejection_keeps_its_reason(self):
        feedback.record_feedback(self.db, self.k(1), "prop-2",
                                 [{"kind": "rejected", "reason": "Too much milk for a short week"}],
                                 "chef-1")
        row = feedback.list_feedback(self.db, self.k(1), proposal_id="prop-2")[0]
        self.assertEqual((row["kind"], row["reason"]), ("rejected", "Too much milk for a short week"))

    def test_three_declines_stop_a_product(self):
        removal = {"kind": "line_removed", "product_id": "900002"}
        for proposal in ("p1", "p2"):
            feedback.record_feedback(self.db, self.k(1), proposal, [removal], "chef-1")
        feedback.record_feedback(self.db, self.k(1), "p3", [{**removal, "product_id": "900005"}], "chef-1")
        self.assertEqual(feedback.declined_products(self.db, self.k(1)), [])
        feedback.record_feedback(self.db, self.k(1), "p4", [removal], "chef-1")
        self.assertEqual(feedback.declined_products(self.db, self.k(1)), ["900002"])
        self.assertEqual(feedback.declined_products(self.db, self.k(2)), [])

    def test_a_bad_change_stores_nothing(self):
        for bad in ({"kind": "edited"}, {"kind": "qty_changed", "product_id": "900001"},
                    {"kind": "qty_changed", "product_id": "900001", "from_qty": "4", "to_qty": "4"},
                    {"kind": "qty_changed", "product_id": "900001", "from_qty": 4.0, "to_qty": "5"},
                    {"kind": "line_removed"}, {"kind": "rejected"},
                    {"kind": "line_added", "product_id": "900001", "unit": "litres"}):
            with self.assertRaises((ValueError, TypeError), msg=bad):
                feedback.record_feedback(self.db, self.k(9), "p", [{"kind": "approved"}, bad], "chef-1")
        with self.assertRaises(ValueError):
            feedback.record_feedback(self.db, self.k(9), "p", [{"kind": "approved"}], "")
        self.assertEqual(feedback.list_feedback(self.db, self.k(9)), [])

    def test_stock_counts_keep_unknown_apart_from_zero(self):
        first = datetime(2026, 11, 13, 20, 0, tzinfo=timezone.utc)
        later = datetime(2026, 11, 14, 20, 0, tzinfo=timezone.utc)
        history.record_stock_count(self.db, self.k(1), first, [
            {"product_id": "900001", "on_hand": "120", "unit": "L"},
            {"product_id": "900002", "on_hand": "0", "unit": "KG"}])
        history.record_stock_count(self.db, self.k(1), later, [
            {"product_id": "900001", "on_hand": None, "unit": "L"}], source="pos")
        stock = {row["product_id"]: row for row in history.current_stock(self.db, self.k(1))}
        self.assertIsNone(stock["900001"]["on_hand"])  # the latest count says "unknown"
        self.assertEqual(stock["900001"]["counted_at"], later)
        self.assertEqual(stock["900002"]["on_hand"], Decimal("0"))  # a measured zero
        self.assertEqual(history.current_stock(self.db, self.k(2)), [])
        for bad in ([{"product_id": "900001", "on_hand": "1", "unit": "l"}],
                    [{"product_id": "", "on_hand": "1", "unit": "L"}],
                    [{"product_id": "900001", "on_hand": 1.5, "unit": "L"}]):
            with self.assertRaises((ValueError, TypeError)):
                history.record_stock_count(self.db, self.k(3), later, bad)
        with self.assertRaises(ValueError):
            history.record_stock_count(self.db, self.k(3), datetime(2026, 11, 14), [])
        self.assertEqual(history.current_stock(self.db, self.k(3)), [])


@unittest.skipUnless(mongomock, "install the test extra: pip install -e '.[test]'")
class OfflineTests(Scenarios, unittest.TestCase):
    def setUp(self):
        self.db = mongomock.MongoClient(tz_aware=True)["test"]


@unittest.skipUnless(os.environ.get("STORE_LIVE_TESTS") == "1", "set STORE_LIVE_TESTS=1")
class LiveTests(Scenarios, unittest.TestCase):
    """The same scenarios on real time-series collections, in a throwaway database."""

    @classmethod
    def setUpClass(cls):
        from store.db import get_db
        cls.db = get_db(f"two_brothers_test_{uuid4().hex[:8]}")
        history.ensure_history_collections(cls.db)

    @classmethod
    def tearDownClass(cls):
        cls.db.client.drop_database(cls.db.name)

    def test_feedback_is_a_time_series_collection(self):
        self.assertEqual(self.db.feedback.options()["timeseries"]["metaField"], "meta")


if __name__ == "__main__":
    unittest.main()
