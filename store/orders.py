"""Offers, orders and approvals. Field names and outcomes follow docs/contract.md.

Money values are `Decimal` (stored as `Decimal128`). A binary float anywhere in a
document is refused, and so is an unknown-stock sentinel: the caller must turn it
into `None` first.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from uuid import uuid4

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from store.audit import canonical

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


def _insert_once(collection, doc: dict, id_key: str) -> tuple[dict, bool]:
    """Insert, or return the row already stored under this kitchen's idempotency key.

    The stored row must carry the same `payload_hash`, else the key was reused.
    """
    try:
        collection.insert_one(doc)
        return _out(doc, id_key), True
    except DuplicateKeyError:
        stored = collection.find_one({"kitchen_id": doc["kitchen_id"],
                                      "idempotency_key": doc["idempotency_key"]})
        if stored["payload_hash"] != doc["payload_hash"]:
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

def attempt_for_key(db, kitchen_id: str, idempotency_key: str) -> dict | None:
    return _out(db.orders.find_one({'kitchen_id': kitchen_id, 'idempotency_key': idempotency_key}), 'order_id')


def record_attempt(db, *, kitchen_id: str, idempotency_key: str, offer_id: str,
                   expected_total, lines: list, **extra) -> tuple[dict, bool]:
    """Write the attempt row. Call this before any send. Returns `(order, created)`.

    The `payload_hash` is computed here from `offer_id`, `expected_total`, `lines`
    and the extra fields, the same way as `request_approval`. A replay with the
    same payload returns the stored order and False; the same key with another
    payload raises `IdempotencyConflict`. Keys are scoped to the kitchen.
    `status` and `outcome` stay None until `set_outcome`.
    """
    payload = {**extra, "offer_id": offer_id, "expected_total": expected_total,
               "lines": lines}
    _check(payload)
    now = _now()
    doc = {**payload, "_id": uuid4().hex, "kitchen_id": kitchen_id,
           "idempotency_key": idempotency_key,
           "payload_hash": hashlib.sha256(canonical(payload).encode()).hexdigest(),
           "status": None, "outcome": None, "created_at": now, "updated_at": now}
    return _insert_once(db.orders, doc, "order_id")


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
    """Open a PENDING approval. Returns `(approval, created)`.

    A replay of the same request returns the stored approval and False. The same
    key with any other content (offer, reasons, extra fields) raises
    `IdempotencyConflict`.
    """
    payload = {**extra, "offer_id": offer_id, "reasons": list(reasons)}
    _check(payload)
    doc = {**payload, "_id": uuid4().hex, "kitchen_id": kitchen_id,
           "idempotency_key": idempotency_key, "status": "PENDING",
           "payload_hash": hashlib.sha256(canonical(payload).encode()).hexdigest(),
           "requested_at": _now(), "decided_by": None, "decided_at": None}
    return _insert_once(db.approvals, doc, "approval_id")


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
