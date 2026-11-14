"""What the Trust screen and the live inbox need (#367).

- `verify`: is the audit chain intact?
- `tamper` / `restore`: a demo that edits one audit row of the synthetic demo kitchen,
  so a person can watch `verify` find the break, and then puts the exact row back.
  `store.audit` itself still has no update and no delete.
- `watch_kitchen`: a change stream over one kitchen's proposals, approvals and audit
  entries, for the gateway to send on as server-sent events.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from store import audit

DEMO_KITCHEN = "demo-kitchen"
WATCHED = ("proposals", "approvals", "audit_log")
TAMPER_NOTE = "this row was edited after it was written (tamper demo)"
# The chain is one for all kitchens, so a tampered demo row shows as a break to every
# kitchen. A forgotten demo must not stay: after this long it restores itself.
TAMPER_TTL = timedelta(minutes=10)


def verify(db, kitchen_id: str) -> dict:
    """`ok`, `length` and `broken_at` of the audit chain, whose row broke it, and how
    many entries are this kitchen's. The chain is one for all kitchens: that is what
    makes it linear, and why a break shows for every kitchen.

    `broken_kitchen_id` names the kitchen of the broken row when that row itself was
    edited (the tamper demo: `demo-kitchen`), so another kitchen's screen can say the
    break is not in its own entries. It is None when the chain is intact, and when a
    row is missing or relinked, because then nobody can say whose row it was.
    """
    _heal(db)
    result = audit.verify_chain(db)
    kitchen = None
    if not result["ok"]:
        entry = db.audit_log.find_one({"_id": result["broken_at"]})
        if entry and entry["hash"] != audit.entry_hash(entry):
            kitchen = (entry.get("server") or {}).get("kitchen_id")
    return {**result, "broken_kitchen_id": kitchen,
            "kitchen_entries": db.audit_log.count_documents({"server.kitchen_id": kitchen_id})}


def _put_back(db, saved: dict) -> None:
    db.audit_log.replace_one({"_id": saved["original"]["_id"]}, saved["original"])
    db.audit_tamper_demo.delete_one({"_id": saved["_id"]})


def _heal(db) -> None:
    """Restore a demo tamper that somebody forgot."""
    saved = db.audit_tamper_demo.find_one({"_id": DEMO_KITCHEN})
    if saved and datetime.now(timezone.utc) - saved["tampered_at"] > TAMPER_TTL:
        _put_back(db, saved)


def _demo_only(db, kitchen_id: str) -> None:
    kitchen = db.kitchens.find_one({"_id": kitchen_id}) or {}
    if kitchen_id != DEMO_KITCHEN or kitchen.get("synthetic") is not True:
        raise PermissionError("the tamper demo only runs on the synthetic demo kitchen")


def tamper(db, kitchen_id: str) -> dict:
    """Edit the demo kitchen's newest audit row, keeping the original for `restore`.

    Refused for any other kitchen, and while an earlier tamper is not restored. A
    tamper left for more than `TAMPER_TTL` is restored first.
    """
    _demo_only(db, kitchen_id)
    _heal(db)
    if db.audit_tamper_demo.find_one({"_id": kitchen_id}):
        raise ValueError("a row is already tampered; restore it first")
    entry = db.audit_log.find_one({"server.kitchen_id": kitchen_id}, sort=[("_id", -1)])
    if entry is None:
        raise ValueError("the demo kitchen has no audit entries yet")
    # The original is saved before the edit: a crash in between leaves nothing changed.
    db.audit_tamper_demo.insert_one({"_id": kitchen_id, "original": entry,
                                     "tampered_at": datetime.now(timezone.utc)})
    db.audit_log.update_one({"_id": entry["_id"]}, {"$set": {"event.tampered": TAMPER_NOTE}})
    return {"seq": entry["seq"], "tampered": True}


def restore(db, kitchen_id: str) -> dict:
    """Put the tampered row back exactly as it was. Does nothing when none is tampered."""
    _demo_only(db, kitchen_id)
    saved = db.audit_tamper_demo.find_one({"_id": kitchen_id})
    if saved is None:
        return {"seq": None, "restored": False}
    _put_back(db, saved)
    return {"seq": saved["original"]["seq"], "restored": True}


def watch_kitchen(db, kitchen_id: str, max_await_ms: int = 1000):
    """Open a change stream now; return an iterator over this kitchen's new and changed
    proposals, approvals and audit entries.

    Each item is `{"collection", "operation", "document"}`, or None when nothing
    happened for `max_await_ms`: a heartbeat, so the caller can notice a closed
    connection. Call `.close()` on the iterator when the client goes away.
    """
    pipeline = [{"$match": {
        "ns.coll": {"$in": list(WATCHED)},
        "operationType": {"$in": ["insert", "update", "replace"]},
        "$or": [{"fullDocument.kitchen_id": kitchen_id},
                {"fullDocument.server.kitchen_id": kitchen_id}]}}]
    stream = db.watch(pipeline, full_document="updateLookup", max_await_time_ms=max_await_ms)
    return KitchenEvents(stream)


class KitchenEvents:
    """The iterator `watch_kitchen` returns. `close()` always closes the change stream,
    also when the iterator was never advanced (a generator's `with` would not run then)."""

    def __init__(self, stream):
        self._stream = stream

    def __iter__(self):
        return self

    def __next__(self):
        if not self._stream.alive:
            self.close()
            raise StopIteration
        change = self._stream.try_next()
        return None if change is None else {
            "collection": change["ns"]["coll"], "operation": change["operationType"],
            "document": change["fullDocument"]}

    def close(self) -> None:
        self._stream.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        self.close()
