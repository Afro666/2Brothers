"""Trust screen: verify, the demo tamper and restore (mongomock), the change stream (live)."""

import os
import unittest
from uuid import uuid4

from store import audit, trust

try:
    import mongomock
except ImportError:  # the `test` extra is not installed
    mongomock = None


def seed(db):
    db.kitchens.insert_one({"_id": "demo-kitchen", "synthetic": True})
    db.kitchens.insert_one({"_id": "real-kitchen"})
    for n, kitchen in enumerate(["demo-kitchen", "real-kitchen", "demo-kitchen"]):
        audit.append_event(db, {"event_id": f"e{n}", "kind": "proposal_created", "actor": "buyer"},
                           {"kitchen_id": kitchen})


@unittest.skipUnless(mongomock, "install the test extra: pip install -e '.[test]'")
class TamperDemoTests(unittest.TestCase):
    def setUp(self):
        self.db = mongomock.MongoClient(tz_aware=True)["test"]
        seed(self.db)

    def test_verify_reports_the_chain_and_this_kitchens_share(self):
        self.assertEqual(trust.verify(self.db, "demo-kitchen"),
                         {"ok": True, "length": 3, "broken_at": None, "kitchen_entries": 2})
        self.assertEqual(trust.verify(self.db, "real-kitchen")["kitchen_entries"], 1)

    def test_tamper_breaks_the_chain_and_restore_mends_it_exactly(self):
        before = list(self.db.audit_log.find().sort("_id", 1))
        self.assertEqual(trust.tamper(self.db, "demo-kitchen"), {"seq": 3, "tampered": True})
        broken = trust.verify(self.db, "demo-kitchen")
        self.assertEqual((broken["ok"], broken["broken_at"]), (False, 3))
        with self.assertRaises(ValueError):  # one tampered row at a time
            trust.tamper(self.db, "demo-kitchen")
        self.assertEqual(trust.restore(self.db, "demo-kitchen"), {"seq": 3, "restored": True})
        self.assertEqual(list(self.db.audit_log.find().sort("_id", 1)), before)
        self.assertTrue(trust.verify(self.db, "demo-kitchen")["ok"])
        self.assertEqual(trust.restore(self.db, "demo-kitchen"), {"seq": None, "restored": False})

    def test_only_the_synthetic_demo_kitchen_can_be_tampered(self):
        self.db.kitchens.insert_one({"_id": "other-demo", "synthetic": True})
        for kitchen in ("real-kitchen", "other-demo", "nobody"):
            with self.assertRaises(PermissionError):
                trust.tamper(self.db, kitchen)
            with self.assertRaises(PermissionError):
                trust.restore(self.db, kitchen)
        self.db.kitchens.update_one({"_id": "demo-kitchen"}, {"$set": {"synthetic": False}})
        with self.assertRaises(PermissionError):  # a real kitchen that happens to have the name
            trust.tamper(self.db, "demo-kitchen")
        self.assertTrue(trust.verify(self.db, "demo-kitchen")["ok"])

    def test_nothing_to_tamper_is_an_error_not_a_silent_success(self):
        self.db.audit_log.delete_many({"server.kitchen_id": "demo-kitchen"})
        with self.assertRaises(ValueError):
            trust.tamper(self.db, "demo-kitchen")
        self.assertIsNone(self.db.audit_tamper_demo.find_one({}))


@unittest.skipUnless(os.environ.get("STORE_LIVE_TESTS") == "1", "set STORE_LIVE_TESTS=1")
class LiveTrustTests(unittest.TestCase):
    """Change streams need a real replica set: a throwaway database, dropped after."""

    @classmethod
    def setUpClass(cls):
        from store.db import get_db
        cls.db = get_db(f"two_brothers_test_{uuid4().hex[:8]}")
        seed(cls.db)

    @classmethod
    def tearDownClass(cls):
        cls.db.client.drop_database(cls.db.name)

    def test_tamper_and_restore_on_real_mongo(self):
        seq = trust.tamper(self.db, "demo-kitchen")["seq"]
        self.assertEqual(trust.verify(self.db, "demo-kitchen")["broken_at"], seq)
        trust.restore(self.db, "demo-kitchen")
        self.assertTrue(trust.verify(self.db, "demo-kitchen")["ok"])

    def test_the_stream_carries_this_kitchens_changes_only(self):
        events = trust.watch_kitchen(self.db, "demo-kitchen", max_await_ms=500)
        try:
            self.db.proposals.insert_one({"_id": "p-other", "kitchen_id": "real-kitchen", "status": "READY"})
            self.db.proposals.insert_one({"_id": "p1", "kitchen_id": "demo-kitchen", "status": "PENDING"})
            self.db.proposals.update_one({"_id": "p1"}, {"$set": {"status": "READY"}})
            self.db.approvals.insert_one({"_id": "a1", "kitchen_id": "demo-kitchen", "status": "PENDING"})
            self.db.orders.insert_one({"_id": "o1", "kitchen_id": "demo-kitchen"})  # not watched
            audit.append_event(self.db, {"event_id": "live-1", "kind": "proposal_ready"},
                               {"kitchen_id": "demo-kitchen"})
            seen = []
            for _ in range(40):
                event = next(events)
                if event is not None:
                    seen.append((event["collection"], event["operation"],
                                 event["document"].get("status") or event["document"]["event"]["kind"]))
                if len(seen) == 4:
                    break
            self.assertEqual(seen, [("proposals", "insert", "PENDING"), ("proposals", "update", "READY"),
                                    ("approvals", "insert", "PENDING"),
                                    ("audit_log", "insert", "proposal_ready")])
            self.assertIsNone(next(events))  # quiet: a heartbeat, not a hang
        finally:
            events.close()


if __name__ == "__main__":
    unittest.main()
