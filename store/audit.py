"""Insert-only, hash-chained audit log shared by agent, gateway and human events.

There are no update or delete functions on purpose. Each entry stores the hash of
the entry before it, so a changed or removed entry breaks every later hash. The newest
`seq` and `hash` are also kept in their own document (`audit_head`), so entries cut
from the end, or a rewritten end, fail the verify too.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json

from bson.decimal128 import Decimal128
from pymongo.errors import DuplicateKeyError

GENESIS = "0" * 64
HEAD = "head"  # the one document of `audit_head`
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


def as_read(value):
    """A value read back from Mongo, with naive datetimes marked UTC.

    A db handle without `tz_aware=True` returns naive datetimes; Mongo stores UTC.
    """
    if isinstance(value, datetime) and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    if isinstance(value, dict):
        return {key: as_read(item) for key, item in value.items()}
    if isinstance(value, list):
        return [as_read(item) for item in value]
    return value


def _out(doc: dict) -> dict:
    doc.pop("_id", None)
    return doc


def append_event(db, event: dict, server: dict | None = None) -> dict:
    """Append one event and return the stored entry; see `append_event_new`."""
    return append_event_new(db, event, server)[0]


def append_event_new(db, event: dict, server: dict | None = None) -> tuple[dict, bool]:
    """Append one event; return the stored entry and whether this call appended it.

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
            return _out(stored), False
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
        except DuplicateKeyError:
            continue  # another writer took this seq or this event_id: read again
        _advance_head(db, entry)
        return entry, True
    raise RuntimeError("audit log append kept losing the race; nothing was stored")


def _advance_head(db, entry: dict) -> None:
    """Move the chain head to this entry. It only moves forward."""
    try:
        db.audit_head.update_one(
            {"_id": HEAD, "seq": {"$lt": entry["seq"]}},
            {"$set": {"seq": entry["seq"], "hash": entry["hash"], "at": entry["stored_at"]}},
            upsert=True)
    except DuplicateKeyError:
        pass  # the head is already at a later entry: another writer was faster


def chain_head(db) -> dict | None:
    """`{seq, hash, at}` of the newest entry as the head document holds it, or None for a
    log that has had no append since the head exists. For the gateway to sign and show."""
    head = db.audit_head.find_one({"_id": HEAD})
    return {key: head[key] for key in ("seq", "hash", "at")} if head else None


def list_events(db, *, kitchen_id: str | None = None, run_id: str | None = None,
                order_id: str | None = None, limit: int = 1000) -> list[dict]:
    """The newest `limit` entries in chain order, optionally for one kitchen, agent run or order."""
    query = {}
    if kitchen_id is not None:
        query["server.kitchen_id"] = kitchen_id
    if run_id is not None:
        query["event.run_id"] = run_id
    if order_id is not None:
        query["event.order_id"] = order_id
    # Newest first for the limit: the oldest `limit` would freeze a long log at its start (#1266).
    return [_out(doc) for doc in db.audit_log.find(query).sort("_id", -1).limit(limit)][::-1]


def verify_entries(entries) -> dict:
    """Check a chain given in `seq` order. `broken_at` is the first bad `seq`."""
    prev, expected, count = GENESIS, 1, 0
    for entry in entries:
        if (entry["seq"] != expected or entry["prev_hash"] != prev
                or entry["hash"] != entry_hash(as_read(entry))):
            return {"ok": False, "length": count, "broken_at": entry["seq"]}
        prev, expected, count = entry["hash"], expected + 1, count + 1
    return {"ok": True, "length": count, "broken_at": None}


def verify_chain(db) -> dict:
    """Check every hash, then the end against the head document: a log that stops before
    the head was cut (`broken_at` is the first missing `seq`), and another hash at the
    head's `seq` is a rewritten end. A log without a head yet is checked as before.
    """
    # shortcut: the head is in the same database, so whoever can write there can move it
    # too; the gateway must sign it and show it outside (contract, "Trust") to close that.
    result = verify_entries(db.audit_log.find().sort("_id", 1))
    head = chain_head(db)
    if result["ok"] and head:
        if result["length"] < head["seq"]:
            return {"ok": False, "length": result["length"], "broken_at": result["length"] + 1}
        if db.audit_log.find_one({"_id": head["seq"]})["hash"] != head["hash"]:
            return {"ok": False, "length": head["seq"] - 1, "broken_at": head["seq"]}
    return result
