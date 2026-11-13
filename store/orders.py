"""Offers, orders and approvals. Field names and outcomes follow docs/contract.md.

Money values are `Decimal` (stored as `Decimal128`). A binary float anywhere in a
document is refused, and so is an unknown-stock sentinel: the caller must turn it
into `None` first.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

OUTCOMES = ("CONFIRMED", "NOT_SENT", "UNCONFIRMED", "SENT_READ_FAILED")
DECISIONS = ("APPROVED", "REJECTED")
STOCK_SENTINELS = (999999, 9999999999)


class IdempotencyConflict(Exception):
    """The idempotency key was already used with a different payload."""


class NotPending(Exception):
    """The approval does not exist or was already decided."""


def _check(value) -> None:
    if isinstance(value, dict):
        for item in value.values():
            _check(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _check(item)
    elif isinstance(value, float):
        raise TypeError("binary float refused: use Decimal for money and quantities")
    elif not isinstance(value, bool) and value in STOCK_SENTINELS:
        raise ValueError("unknown-stock sentinel refused: store None for unknown stock")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _out(doc: dict | None, id_key: str) -> dict | None:
    if doc is not None:
        doc[id_key] = doc.pop("_id")
    return doc


def _insert_once(collection, doc: dict, id_key: str, same) -> tuple[dict, bool]:
    """Insert, or return the row already stored under this idempotency key."""
    try:
        collection.insert_one(doc)
        return _out(doc, id_key), True
    except DuplicateKeyError:
        stored = collection.find_one({"kitchen_id": doc["kitchen_id"],
                                      "idempotency_key": doc["idempotency_key"]})
        if not same(stored):
            raise IdempotencyConflict(doc["idempotency_key"]) from None
        return _out(stored, id_key), False


# Offers: price and availability snapshots. Never updated, never expired, so an
# audit entry can always show the offer behind an order.

def save_offer(db, offer: dict) -> dict:
    _check(offer)
    doc = {**offer, "_id": offer.get("offer_id") or uuid4().hex,
           "fetched_at": offer.get("fetched_at") or _now()}
    doc.pop("offer_id", None)
    db.offers.insert_one(doc)
    return _out(doc, "offer_id")


def get_offer(db, offer_id: str) -> dict | None:
    return _out(db.offers.find_one({"_id": offer_id}), "offer_id")


# Orders

def record_attempt(db, *, kitchen_id: str, idempotency_key: str, offer_id: str,
                   expected_total, lines: list, payload_hash: str,
                   **extra) -> tuple[dict, bool]:
    """Write the attempt row. Call this before any send. Returns `(order, created)`.

    A replay with the same `payload_hash` returns the stored order and False; the
    same key with another payload raises `IdempotencyConflict`. Keys are scoped to
    the kitchen. `status` and `outcome` stay None until `set_outcome`.
    """
    now = _now()
    doc = {**extra, "_id": uuid4().hex, "kitchen_id": kitchen_id,
           "idempotency_key": idempotency_key, "offer_id": offer_id,
           "expected_total": expected_total, "lines": lines,
           "payload_hash": payload_hash, "status": None, "outcome": None,
           "created_at": now, "updated_at": now}
    _check(doc)
    return _insert_once(db.orders, doc, "order_id",
                        lambda stored: stored["payload_hash"] == payload_hash)


def set_outcome(db, order_id: str, *, outcome: str, status: str | None,
                **fields) -> dict:
    """Record the gateway `outcome` and the supplier-side order `status`."""
    if outcome not in OUTCOMES:
        raise ValueError(f"outcome must be one of {OUTCOMES}")
    _check(fields)
    doc = db.orders.find_one_and_update(
        {"_id": order_id},
        {"$set": {**fields, "outcome": outcome, "status": status, "updated_at": _now()}},
        return_document=ReturnDocument.AFTER)
    if doc is None:
        raise KeyError(order_id)
    return _out(doc, "order_id")


def get_order(db, order_id: str) -> dict | None:
    return _out(db.orders.find_one({"_id": order_id}), "order_id")


def list_orders(db, kitchen_id: str, limit: int = 100) -> list[dict]:
    """One kitchen's orders, newest first."""
    cursor = db.orders.find({"kitchen_id": kitchen_id}).sort("created_at", -1).limit(limit)
    return [_out(doc, "order_id") for doc in cursor]


# Approvals: a human decides every order. There is no auto-approve.

def request_approval(db, *, kitchen_id: str, idempotency_key: str, offer_id: str,
                     reasons=(), **extra) -> tuple[dict, bool]:
    """Open a PENDING approval. Returns `(approval, created)`; replays are safe."""
    doc = {**extra, "_id": uuid4().hex, "kitchen_id": kitchen_id,
           "idempotency_key": idempotency_key, "offer_id": offer_id, "status": "PENDING", "reasons": list(reasons),
           "requested_at": _now(), "decided_by": None, "decided_at": None}
    _check(doc)
    return _insert_once(db.approvals, doc, "approval_id",
                        lambda stored: stored["offer_id"] == offer_id)


def decide_approval(db, approval_id: str, *, status: str, decided_by: str,
                    **fields) -> dict:
    """Record a human decision. Only a PENDING approval can be decided, once.

    Extra `fields` are stored with it, for example the `reason` of a rejection.
    """
    if status not in DECISIONS:
        raise ValueError(f"status must be one of {DECISIONS}")
    if not decided_by:
        raise ValueError("decided_by is required")
    _check(fields)
    doc = db.approvals.find_one_and_update(
        {"_id": approval_id, "status": "PENDING"},
        {"$set": {**fields, "status": status, "decided_by": decided_by,
                  "decided_at": _now()}},
        return_document=ReturnDocument.AFTER)
    if doc is None:
        raise NotPending(approval_id)
    return _out(doc, "approval_id")


def get_approval(db, approval_id: str) -> dict | None:
    return _out(db.approvals.find_one({"_id": approval_id}), "approval_id")


def list_approvals(db, kitchen_id: str, status: str | None = None,
                   limit: int = 100) -> list[dict]:
    """One kitchen's approvals, oldest first: the inbox shows the longest wait on top."""
    query = {"kitchen_id": kitchen_id}
    if status is not None:
        query["status"] = status
    return [_out(doc, "approval_id")
            for doc in db.approvals.find(query).sort("requested_at", 1).limit(limit)]
