"""Learning rows: server context, joined outcomes and the next stock count (#1302)."""

from datetime import datetime, timezone
from decimal import Decimal
import unittest

from store import feedback, history

try:
    import mongomock
except ImportError:  # the `test` extra is not installed
    mongomock = None

K = "learning-kitchen"


def _context(requested_date="2026-11-14"):
    return {"forecast_need": "40", "stock_position": None, "covers": None,
            "requested_date": requested_date, "made_by": "menu_plan", "offer_id": "o-1"}


def change(feedback_id="fb-1", product_id="900001", reason="TOO_MUCH", **extra):
    return {"feedback_id": feedback_id, "kind": "qty_changed", "product_id": product_id,
            "from_qty": "40", "to_qty": "20", "unit": "L", "reason": reason,
            "context": _context(), **extra}


@unittest.skipUnless(mongomock, "install the test extra: pip install -e '.[test]'")
class LearningTests(unittest.TestCase):
    def setUp(self):
        self.db = mongomock.MongoClient(tz_aware=True)["test"]

    def set_ts(self, feedback_id, when):
        self.db.feedback.update_many({"feedback_id": feedback_id}, {"$set": {"ts": when}})

    def test_fill_outcomes_links_the_first_count_after_the_request_and_is_idempotent(self):
        feedback.record_feedback(self.db, K, "p-1", [change()], "chef-1")
        history.record_stock_count(self.db, K, datetime(2026, 11, 15, 8, tzinfo=timezone.utc),
                                   [{"product_id": "900001", "on_hand": "3", "unit": "L"}])
        history.record_stock_count(self.db, K, datetime(2026, 11, 17, 8, tzinfo=timezone.utc),
                                   [{"product_id": "900001", "on_hand": "8", "unit": "L"}])

        self.assertEqual(feedback.fill_outcomes(self.db, K), 1)
        row = self.db.feedback_outcomes.find_one({"kitchen_id": K, "feedback_id": "fb-1"})
        self.assertEqual(row["next_count_at"], datetime(2026, 11, 15, 8, tzinfo=timezone.utc))
        self.assertEqual(Decimal(str(row["next_count"])), Decimal("3"))
        self.assertIsNone(row["ran_out"])          # a count alone never says the kitchen ran out

        history.record_stock_count(self.db, K, datetime(2026, 11, 18, 8, tzinfo=timezone.utc),
                                   [{"product_id": "900001", "on_hand": "5", "unit": "L"}])
        self.assertEqual(feedback.fill_outcomes(self.db, K), 0)
        row = self.db.feedback_outcomes.find_one({"kitchen_id": K, "feedback_id": "fb-1"})
        self.assertEqual(Decimal(str(row["next_count"])), Decimal("3"))   # never rewritten

    def test_a_count_after_the_request_but_absent_leaves_the_outcome_unknown(self):
        feedback.record_feedback(self.db, K, "p-1", [change(context=_context("2026-11-20"))], "chef-1")
        feedback.record_feedback(self.db, K, "p-2", [{"feedback_id": "fb-approved",
                                                      "kind": "approved", "total": "10.00"}], "chef-1")
        history.record_stock_count(self.db, K, datetime(2026, 11, 15, 8, tzinfo=timezone.utc),
                                   [{"product_id": "900001", "on_hand": "0", "unit": "L"}])

        self.assertEqual(feedback.fill_outcomes(self.db, K), 0)
        row = feedback.changes_for(self.db, K, product_id="900001")[0]
        self.assertEqual(row["outcome"], {"next_count_at": None, "next_count": None, "ran_out": None})

    def test_changes_for_joins_outcomes_only_by_feedback_id(self):
        when = datetime(2026, 11, 14, 10, tzinfo=timezone.utc)
        self.db.feedback.insert_many([
            {"ts": when, "meta": {"kitchen_id": K, "product_id": "900001"}, "proposal_id": "p-old",
             "user": "chef-1", "kind": "qty_changed", "from_qty": "40", "to_qty": "20", "unit": "L"},
            {"ts": when, "meta": {"kitchen_id": K, "product_id": "900001"}, "proposal_id": "p-new",
             "user": "chef-1", "kind": "qty_changed", "from_qty": "40", "to_qty": "20", "unit": "L",
             "feedback_id": "fb-new", "reason": "TOO_MUCH", "context": _context()}])
        self.db.feedback_outcomes.insert_many([
            {"_id": f"{K}:fb-new", "kitchen_id": K, "feedback_id": "fb-new",
             "next_count_at": when, "next_count": 0, "ran_out": None},
            {"_id": f"{K}:fb-old", "kitchen_id": K, "feedback_id": "fb-old",
             "next_count_at": when, "next_count": 7, "ran_out": None}])

        old, new = feedback.changes_for(self.db, K, product_id="900001")
        self.assertEqual(old["outcome"], {"next_count_at": None, "next_count": None, "ran_out": None})
        self.assertEqual(new["outcome"]["next_count"], "0")   # a measured zero is not unknown
        self.assertIsNone(new["outcome"]["ran_out"])

    def test_a_rejection_without_a_reason_is_stored_with_a_null_reason(self):
        for reason in (None, ""):
            feedback.record_feedback(self.db, K, f"p-{reason!r}", [{"kind": "rejected", "reason": reason,
                                                                   "total": "9.99"}], "chef-1")
        rows = feedback.list_feedback(self.db, K)
        self.assertEqual([(row["kind"], row["reason"], row["total"]) for row in rows],
                         [("rejected", None, Decimal("9.99"))] * 2)

    def test_changes_for_is_oldest_first_filters_and_keeps_decision_totals(self):
        feedback.record_feedback(self.db, K, "p-1", [change()], "chef-1")
        feedback.record_feedback(self.db, K, "p-2", [change("fb-other", reason="OTHER",
                                                           note="Event cancelled")], "chef-1")
        feedback.record_feedback(self.db, K, "p-3", [{"feedback_id": "fb-approved", "kind": "approved",
                                                      "total": "12.50"}], "chef-1")
        feedback.record_feedback(self.db, K, "p-4", [{"feedback_id": "fb-rejected", "kind": "rejected",
                                                      "reason": "short week", "total": "9.99"}], "chef-1")
        for feedback_id, hour in (("fb-1", 10), ("fb-other", 11), ("fb-approved", 12), ("fb-rejected", 13)):
            self.set_ts(feedback_id, datetime(2026, 11, 14, hour, tzinfo=timezone.utc))

        rows = feedback.changes_for(self.db, K)
        self.assertEqual([row["reason"] for row in rows], ["TOO_MUCH", "OTHER", None, "short week"])
        self.assertEqual((rows[2]["kind"], rows[2]["total"]), ("approved", "12.5"))
        self.assertEqual((rows[3]["kind"], rows[3]["total"]), ("rejected", "9.99"))
        self.assertEqual(rows[1]["note"], "Event cancelled")
        self.assertEqual(feedback.changes_for(self.db, K, reasons=["TOO_MUCH"]), [rows[0]])
        since = datetime(2026, 11, 14, 11, tzinfo=timezone.utc)
        self.assertEqual([row["feedback_id"] for row in feedback.changes_for(self.db, K, since=since)],
                         ["fb-other", "fb-approved", "fb-rejected"])
        self.assertEqual([row["proposal_id"] for row in feedback.changes_for(self.db, K,
                                                                            product_id="900001")],
                         ["p-1", "p-2"])


if __name__ == "__main__":
    unittest.main()
