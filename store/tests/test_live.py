"""Checks against a real cluster, in a throwaway database that is dropped at the end.

Run with `STORE_LIVE_TESTS=1 python -m unittest store.tests.test_live -v`.
Skipped otherwise, so the offline test run never touches the network.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal
import os
import unittest
from uuid import uuid4

from store import audit, orders
from store.db import ensure_indexes, get_db


@unittest.skipUnless(os.environ.get("STORE_LIVE_TESTS") == "1", "set STORE_LIVE_TESTS=1")
class LiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = get_db(f"two_brothers_test_{uuid4().hex[:8]}")
        ensure_indexes(cls.db)
        ensure_indexes(cls.db)  # running it again must not fail

    @classmethod
    def tearDownClass(cls):
        cls.db.client.drop_database(cls.db.name)

    def test_audit_chain_stays_linear_under_concurrent_writers(self):
        events = [{"event_id": f"c{n}", "run_id": "race", "total": Decimal("149.02"),
                   "at": datetime(2026, 11, 13, 22, 5, 1, 123456, tzinfo=timezone.utc)}
                  for n in range(12)]
        with ThreadPoolExecutor(6) as pool:
            entries = list(pool.map(lambda e: audit.append_event(self.db, e), events))
        self.assertEqual(len({e["seq"] for e in entries}), 12)
        self.assertTrue(audit.verify_chain(self.db)["ok"])
        again = audit.append_event(self.db, events[0])
        self.assertEqual(again["seq"], entries[0]["seq"])
        with self.assertRaises(audit.AuditConflict):
            audit.append_event(self.db, {**events[0], "run_id": "other"})
        self.assertEqual(len(audit.list_events(self.db, run_id="race")), 12)
        audit.append_event(self.db, {"event_id": "k"}, {"kitchen_id": "k1"})
        self.assertEqual(len(audit.list_events(self.db, kitchen_id="k1")), 1)

    def test_order_attempt_is_idempotent_and_money_stays_decimal(self):
        offer = orders.save_offer(self.db, {"lines": [{"product_id": "000001",
                                                       "unit_price": Decimal("2.57"),
                                                       "available_amount": None}]})
        self.assertEqual(orders.get_offer(self.db, offer["offer_id"])["lines"][0]["unit_price"],
                         Decimal("2.57"))
        args = dict(kitchen_id="k1", idempotency_key=uuid4().hex, offer_id=offer["offer_id"],
                    expected_total=Decimal("149.02"), lines=[], payload_hash="h1")
        order, created = orders.record_attempt(self.db, **args)
        replay, created_again = orders.record_attempt(self.db, **args)
        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertEqual(replay["order_id"], order["order_id"])
        self.assertEqual(replay["expected_total"], Decimal("149.02"))
        self.assertIsNone(replay["outcome"])
        other, other_created = orders.record_attempt(self.db, **{**args, "kitchen_id": "k2"})
        self.assertTrue(other_created)  # the same key in another kitchen is another order
        with self.assertRaises(orders.IdempotencyConflict):
            orders.record_attempt(self.db, **{**args, "payload_hash": "h2"})
        done = orders.set_outcome(self.db, order["order_id"], outcome="CONFIRMED", status="SENT")
        self.assertEqual(orders.get_order(self.db, order["order_id"])["outcome"], "CONFIRMED")
        self.assertEqual(done["status"], "SENT")
        self.assertEqual([o["order_id"] for o in orders.list_orders(self.db, "k1")],
                         [order["order_id"]])

    def test_approval_is_decided_by_a_human_once(self):
        key = uuid4().hex
        approval, created = orders.request_approval(self.db, kitchen_id="k1", idempotency_key=key,
                                                    offer_id="o1", reasons=["Only 51 L is confirmed."])
        same, created_again = orders.request_approval(
            self.db, kitchen_id="k1", idempotency_key=key, offer_id="o1",
            reasons=["Only 51 L is confirmed."])
        self.assertEqual((created, created_again), (True, False))
        self.assertEqual(same["approval_id"], approval["approval_id"])
        self.assertEqual(approval["status"], "PENDING")
        with self.assertRaises(orders.IdempotencyConflict):
            orders.request_approval(self.db, kitchen_id="k1", idempotency_key=key, offer_id="o2")
        pending = orders.list_approvals(self.db, "k1", status="PENDING")
        self.assertIn(approval["approval_id"], [a["approval_id"] for a in pending])
        self.assertEqual(orders.list_approvals(self.db, "k2"), [])
        decided = orders.decide_approval(self.db, approval["approval_id"], status="APPROVED",
                                         decided_by="chef@example.test", note="ok")
        self.assertEqual(decided["note"], "ok")
        self.assertEqual(decided["decided_by"], "chef@example.test")
        self.assertIsNotNone(decided["decided_at"])
        with self.assertRaises(orders.NotPending):
            orders.decide_approval(self.db, approval["approval_id"], status="REJECTED",
                                   decided_by="chef@example.test")


if __name__ == "__main__":
    unittest.main()
