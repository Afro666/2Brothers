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
                         {"ok": True, "length": 3, "broken_at": None, "broken_kitchen_id": None,
                          "kitchen_entries": 2})
        self.assertEqual(trust.verify(self.db, "real-kitchen")["kitchen_entries"], 1)

    def test_tamper_breaks_the_chain_and_restore_mends_it_exactly(self):
        before = list(self.db.audit_log.find().sort("_id", 1))
        self.assertEqual(trust.tamper(self.db, "demo-kitchen"), {"seq": 3, "tampered": True})
        broken = trust.verify(self.db, "demo-kitchen")
        self.assertEqual((broken["ok"], broken["broken_at"]), (False, 3))
        with self.assertRaises(ValueError):  # one tampered row at a time
            trust.tamper(self.db, "demo-kitchen")
        # The chain is shared, so another kitchen sees the break, and whose row it is.
        other = trust.verify(self.db, "real-kitchen")
        self.assertEqual((other["ok"], other["broken_at"], other["broken_kitchen_id"]),
                         (False, 3, "demo-kitchen"))
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

    def test_a_forgotten_tamper_restores_itself(self):
        from datetime import datetime, timedelta, timezone
        trust.tamper(self.db, "demo-kitchen")
        self.assertFalse(trust.verify(self.db, "real-kitchen")["ok"])  # fresh: still broken
        old = datetime.now(timezone.utc) - trust.TAMPER_TTL - timedelta(seconds=1)
        self.db.audit_tamper_demo.update_one({"_id": "demo-kitchen"}, {"$set": {"tampered_at": old}})
        healed = trust.verify(self.db, "real-kitchen")
        self.assertEqual((healed["ok"], healed["broken_kitchen_id"]), (True, None))
        self.assertIsNone(self.db.audit_tamper_demo.find_one({}))
        trust.tamper(self.db, "demo-kitchen")
        self.db.audit_tamper_demo.update_one({"_id": "demo-kitchen"}, {"$set": {"tampered_at": old}})
        self.assertEqual(trust.tamper(self.db, "demo-kitchen")["tampered"], True)  # heals, then tampers
        trust.restore(self.db, "demo-kitchen")
        self.assertTrue(trust.verify(self.db, "demo-kitchen")["ok"])

    def test_a_db_handle_without_tz_aware_works(self):
        from datetime import datetime, timedelta, timezone
        db = mongomock.MongoClient()["naive"]
        seed(db)
        trust.tamper(db, "demo-kitchen")
        self.assertIsNone(db.audit_tamper_demo.find_one({})["tampered_at"].tzinfo)
        self.assertFalse(trust.verify(db, "real-kitchen")["ok"])  # fresh: still broken
        old = datetime.now(timezone.utc) - trust.TAMPER_TTL - timedelta(seconds=1)
        db.audit_tamper_demo.update_one({"_id": "demo-kitchen"}, {"$set": {"tampered_at": old}})
        self.assertTrue(trust.verify(db, "real-kitchen")["ok"])
        self.assertIsNone(db.audit_tamper_demo.find_one({}))

    def test_a_removed_row_is_a_break_nobody_can_attribute(self):
        self.db.audit_log.delete_one({"_id": 2})
        result = trust.verify(self.db, "demo-kitchen")
        self.assertEqual((result["ok"], result["broken_at"], result["broken_kitchen_id"]),
                         (False, 3, None))

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


class FakeStream:
    def __init__(self, changes=()):
        self.changes, self.alive, self.closed = list(changes), True, False

    def try_next(self):
        return self.changes.pop(0) if self.changes else None

    def close(self):
        self.closed, self.alive = True, False


class FakeDb:
    def __init__(self, stream):
        self.stream = stream

    def watch(self, pipeline, **kwargs):
        return self.stream


class WatchKitchenCloseTests(unittest.TestCase):
    def test_close_before_first_next_closes_the_stream(self):
        stream = FakeStream()
        trust.watch_kitchen(FakeDb(stream), "demo-kitchen").close()
        self.assertTrue(stream.closed)

    def test_items_heartbeat_and_end_when_the_stream_dies(self):
        stream = FakeStream([{"ns": {"coll": "proposals"}, "operationType": "insert",
                              "fullDocument": {"_id": "p1"}}])
        with trust.watch_kitchen(FakeDb(stream), "demo-kitchen") as events:
            self.assertEqual(next(events), {"collection": "proposals", "operation": "insert",
                                            "document": {"_id": "p1"}})
            self.assertIsNone(next(events))
            stream.alive = False
            with self.assertRaises(StopIteration):
                next(events)
        self.assertTrue(stream.closed)


if __name__ == "__main__":
    unittest.main()
