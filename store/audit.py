"""Insert-only, hash-chained audit log shared by agent, gateway and human events.

There are no update or delete functions on purpose. Each entry stores the hash of
the entry before it, so a changed or removed entry breaks every later hash.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json

from bson.decimal128 import Decimal128
from pymongo.errors import DuplicateKeyError

GENESIS = "0" * 64
_HASHED = ("seq", "prev_hash", "event", "server", "stored_at")


class AuditConflict(Exception):
    """The `event_id` was already stored with different content."""


def _default(value):
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise TypeError("audit timestamps must be timezone-aware")
        value = value.astimezone(timezone.utc)
        # Mongo keeps milliseconds; hash what will be read back.
        return value.replace(microsecond=value.microsecond // 1000 * 1000).isoformat()
    if isinstance(value, (Decimal, Decimal128)):
        return str(value)
    raise TypeError(f"cannot store {type(value).__name__} in the audit log")


def canonical(value) -> str:
    """One stable text form, equal before the insert and after reading back."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      default=_default)


def entry_hash(entry: dict) -> str:
    body = {key: entry[key] for key in _HASHED}
    return hashlib.sha256(canonical(body).encode()).hexdigest()


def _out(doc: dict) -> dict:
    doc.pop("_id", None)
    return doc


def append_event(db, event: dict, server: dict | None = None) -> dict:
    """Append one event and return the stored entry.

    `event` is what the client sent; it must hold a string `event_id`. An exact
    replay returns the stored entry and appends nothing; the same `event_id` with
    other content raises `AuditConflict`. `server` holds what the gateway adds
    itself (its timestamp, the authenticated principal, the kitchen); a replay does
    not compare it.
    """
    event_id = event.get("event_id")
    if not isinstance(event_id, str) or not event_id:
        raise ValueError("event_id must be a nonempty string")
    content = canonical(event)
    server = server or {}
    canonical(server)
    for _ in range(50):
        stored = db.audit_log.find_one({"event.event_id": event_id})
        if stored:
            if canonical(stored["event"]) != content:
                raise AuditConflict(event_id)
            return _out(stored)
        last = db.audit_log.find_one(sort=[("_id", -1)])
        entry = {
            "seq": last["seq"] + 1 if last else 1,
            "prev_hash": last["hash"] if last else GENESIS,
            "event": event,
            "server": server,
            "stored_at": datetime.now(timezone.utc),
        }
        entry["hash"] = entry_hash(entry)
        try:
            db.audit_log.insert_one({"_id": entry["seq"], **entry})
            return entry
        except DuplicateKeyError:
            continue  # another writer took this seq or this event_id: read again
    raise RuntimeError("audit log append kept losing the race; nothing was stored")


def list_events(db, *, kitchen_id: str | None = None, run_id: str | None = None,
                order_id: str | None = None, limit: int = 1000) -> list[dict]:
    """Entries in chain order, optionally for one kitchen, agent run or order."""
    query = {}
    if kitchen_id is not None:
        query["server.kitchen_id"] = kitchen_id
    if run_id is not None:
        query["event.run_id"] = run_id
    if order_id is not None:
        query["event.order_id"] = order_id
    return [_out(doc) for doc in db.audit_log.find(query).sort("_id", 1).limit(limit)]


def verify_entries(entries) -> dict:
    """Check a chain given in `seq` order. `broken_at` is the first bad `seq`."""
    prev, expected, count = GENESIS, 1, 0
    for entry in entries:
        if (entry["seq"] != expected or entry["prev_hash"] != prev
                or entry["hash"] != entry_hash(entry)):
            return {"ok": False, "length": count, "broken_at": entry["seq"]}
        prev, expected, count = entry["hash"], expected + 1, count + 1
    return {"ok": True, "length": count, "broken_at": None}


def verify_chain(db) -> dict:
    # shortcut: entries cut from the end are not detected; anchor the latest hash
    # outside the database (a signed daily digest) when this leaves the hackathon.
    return verify_entries(db.audit_log.find().sort("_id", 1))
