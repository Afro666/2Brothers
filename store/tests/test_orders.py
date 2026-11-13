from decimal import Decimal
import unittest

from store import orders
from store.db import ensure_indexes

try:
    import mongomock
except ImportError:  # the `test` extra is not installed
    mongomock = None


class GuardTests(unittest.TestCase):
    """The guards run before any database call, so `db=None` is enough here."""

    def test_binary_floats_are_refused_for_money(self):
        with self.assertRaises(TypeError):
            orders.save_offer(None, {"lines": [{"unit_price": 2.57}]})
        with self.assertRaises(TypeError):
            orders.record_attempt(None, kitchen_id="k1", idempotency_key="k", offer_id="o",
                                  expected_total=149.02, lines=[], payload_hash="h")

    def test_stock_sentinels_are_never_stored(self):
        for sentinel in (999999, 9999999999, Decimal("999999")):
            with self.assertRaises(ValueError):
                orders.save_offer(None, {"lines": [{"available_amount": sentinel}]})

    def test_outcome_and_decision_values_follow_the_contract(self):
        with self.assertRaises(ValueError):
            orders.set_outcome(None, "o1", outcome="DONE", status="SENT")
        with self.assertRaises(ValueError):
            orders.decide_approval(None, "a1", status="AUTO", decided_by="chef")
        with self.assertRaises(ValueError):
            orders.decide_approval(None, "a1", status="APPROVED", decided_by="")
        with self.assertRaises(TypeError):
            orders.decide_approval(None, "a1", status="REJECTED", decided_by="chef", budget=1.5)


@unittest.skipUnless(mongomock, "install the test extra: pip install -e '.[test]'")
class IdempotencyTests(unittest.TestCase):
    def setUp(self):
        self.db = mongomock.MongoClient()["test"]
        ensure_indexes(self.db)

    def attempt(self, **over):
        args = dict(kitchen_id="k1", idempotency_key="key-1", offer_id="o1",
                    expected_total="149.02", lines=[], payload_hash="h1")
        return orders.record_attempt(self.db, **{**args, **over})

    def approval(self, **over):
        args = dict(kitchen_id="k1", idempotency_key="key-1", offer_id="o1",
                    reasons=["Only 51 L is confirmed."])
        return orders.request_approval(self.db, **{**args, **over})

    def test_order_keys_are_scoped_to_the_kitchen(self):
        order, created = self.attempt()
        replay, created_again = self.attempt()
        other, created_other = self.attempt(kitchen_id="k2")
        self.assertEqual((created, created_again, created_other), (True, False, True))
        self.assertEqual(replay["order_id"], order["order_id"])
        self.assertNotEqual(other["order_id"], order["order_id"])
        self.assertIsNone(order["status"])
        with self.assertRaises(orders.IdempotencyConflict):
            self.attempt(payload_hash="h2")

    def test_approval_replay_must_carry_the_same_payload(self):
        approval, created = self.approval()
        replay, created_again = self.approval()
        other, created_other = self.approval(kitchen_id="k2")
        self.assertEqual((created, created_again, created_other), (True, False, True))
        self.assertEqual(replay["approval_id"], approval["approval_id"])
        for changed in ({"offer_id": "o2"}, {"reasons": ["Something else."]}, {"order_id": "x"}):
            with self.assertRaises(orders.IdempotencyConflict):
                self.approval(**changed)
        self.assertEqual(len(orders.list_approvals(self.db, "k1")), 1)


if __name__ == "__main__":
    unittest.main()
