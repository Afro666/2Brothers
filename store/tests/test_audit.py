from datetime import datetime, timedelta, timezone
from decimal import Decimal
import unittest

from bson.decimal128 import Decimal128
from pymongo.errors import DuplicateKeyError

from store.audit import (AuditConflict, append_event, canonical, entry_hash, list_events,
                         verify_chain)


class FakeCursor(list):
    def sort(self, key, direction):
        return FakeCursor(sorted(self, key=lambda d: d[key], reverse=direction < 0))

    def limit(self, n):
        return FakeCursor(self[:n])


class FakeAuditLog:
    """Just enough of a collection for audit.py: unique `_id` and `event.event_id`."""

    def __init__(self, lose_races=0):
        self.docs, self.lose_races = [], lose_races

    def find_one(self, query=None, sort=None):
        if sort:
            return dict(max(self.docs, key=lambda d: d["_id"])) if self.docs else None
        wanted = query["event.event_id"]
        return next((dict(d) for d in self.docs if d["event"]["event_id"] == wanted), None)

    def insert_one(self, doc):
        if self.lose_races:
            # Another writer appends first and takes the seq this caller computed.
            self.lose_races -= 1
            rival = {**doc, "event": {"event_id": f"rival-{doc['_id']}"}}
            rival["hash"] = entry_hash(rival)
            self.docs.append(rival)
            raise DuplicateKeyError("seq taken")
        if any(d["_id"] == doc["_id"] or d["event"]["event_id"] == doc["event"]["event_id"]
               for d in self.docs):
            raise DuplicateKeyError("duplicate")
        self.docs.append(dict(doc))

    def find(self, query=None):
        query = query or {}
        return FakeCursor(dict(d) for d in self.docs
                          if all(d["event"].get(k.split(".")[1]) == v for k, v in query.items()))


class FakeDb:
    def __init__(self, **kw):
        self.audit_log = FakeAuditLog(**kw)


def event(n, **extra):
    return {"event_id": f"e{n}", "run_id": "run-1", "type": "tool_call_started",
            "tool": "get_offer", "arguments": {"need_id": "n1"}, "result": {}, **extra}


class AuditTests(unittest.TestCase):
    def test_chain_links_and_verifies(self):
        db = FakeDb()
        entries = [append_event(db, event(n)) for n in range(3)]
        self.assertEqual([e["seq"] for e in entries], [1, 2, 3])
        self.assertEqual(entries[0]["prev_hash"], "0" * 64)
        self.assertEqual(entries[2]["prev_hash"], entries[1]["hash"])
        self.assertEqual(verify_chain(db), {"ok": True, "length": 3, "broken_at": None})

    def test_exact_replay_is_not_appended_twice(self):
        db = FakeDb()
        first = append_event(db, event(1), {"principal": "agent"})
        again = append_event(db, event(1), {"principal": "someone-else"})
        self.assertEqual(again["seq"], first["seq"])
        self.assertEqual(again["server"], {"principal": "agent"})
        self.assertEqual(len(db.audit_log.docs), 1)

    def test_same_id_with_different_content_is_rejected(self):
        db = FakeDb()
        append_event(db, event(1))
        with self.assertRaises(AuditConflict):
            append_event(db, event(1, tool="place_order"))
        self.assertEqual(len(db.audit_log.docs), 1)

    def test_event_id_is_required(self):
        for bad in ({}, {"event_id": ""}, {"event_id": 7}):
            with self.assertRaises(ValueError):
                append_event(FakeDb(), bad)

    def test_losing_the_race_for_a_seq_retries_with_the_next_one(self):
        db = FakeDb(lose_races=2)
        entry = append_event(db, event(1))
        self.assertEqual(entry["seq"], 3)
        self.assertEqual(verify_chain(db), {"ok": True, "length": 3, "broken_at": None})

    def test_changed_entry_breaks_the_chain(self):
        db = FakeDb()
        for n in range(3):
            append_event(db, event(n))
        db.audit_log.docs[1]["event"]["tool"] = "place_order"
        self.assertEqual(verify_chain(db), {"ok": False, "length": 1, "broken_at": 2})

    def test_removed_entry_breaks_the_chain(self):
        db = FakeDb()
        for n in range(3):
            append_event(db, event(n))
        del db.audit_log.docs[1]
        self.assertEqual(verify_chain(db)["broken_at"], 3)

    def test_list_events_filters_by_run_and_order(self):
        db = FakeDb()
        append_event(db, event(1))
        append_event(db, event(2, run_id="run-2", order_id="o1"))
        self.assertEqual([e["seq"] for e in list_events(db, run_id="run-2")], [2])
        self.assertEqual([e["seq"] for e in list_events(db, order_id="o1")], [2])
        self.assertEqual(len(list_events(db)), 2)
        self.assertNotIn("_id", list_events(db)[0])

    def test_canonical_survives_the_mongo_round_trip(self):
        helsinki = timezone(timedelta(hours=2))
        sent = datetime(2026, 11, 13, 22, 5, 1, 123456, tzinfo=helsinki)
        read_back = datetime(2026, 11, 13, 20, 5, 1, 123000, tzinfo=timezone.utc)
        self.assertEqual(canonical({"at": sent, "total": Decimal("149.02")}),
                         canonical({"total": Decimal128("149.02"), "at": read_back}))

    def test_naive_timestamps_and_unknown_types_are_refused(self):
        with self.assertRaises(TypeError):
            canonical({"at": datetime(2026, 11, 13)})
        with self.assertRaises(TypeError):
            append_event(FakeDb(), event(1, arguments={"blob": b"x"}))


if __name__ == "__main__":
    unittest.main()
