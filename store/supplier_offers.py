"""Supplier offers (#374): a suggestion a supplier sent to one kitchen. Never an order.

One row per supplier, kitchen, offered product and date: the `_id` is made from those four,
so two requests at the same moment store one offer, and a later offer for the same four
answers the stored one (also after a "no thanks"). `status` only leaves `OPEN` through
`decide`, a compare-and-set: two clicks decide once.
"""

from __future__ import annotations

import hashlib

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

OPEN, ACCEPTED, DECLINED, EXPIRED = "OPEN", "ACCEPTED", "DECLINED", "EXPIRED"


def ensure_indexes(db) -> None:
    db.supplier_offers.create_index([("supplier_id", 1), ("idempotency_key", 1)], unique=True)
    db.supplier_offers.create_index([("kitchen_id", 1), ("created_at", -1)])


def offer_id(supplier_id: str, kitchen_id: str, product_id: str, requested_date: str) -> str:
    key = "\x1f".join((supplier_id, kitchen_id, product_id, requested_date))
    return hashlib.sha256(key.encode()).hexdigest()[:32]


def by_key(db, supplier_id: str, idempotency_key: str) -> dict | None:
    return db.supplier_offers.find_one({"supplier_id": supplier_id, "idempotency_key": idempotency_key})


def by_id(db, offer: str) -> dict | None:
    return db.supplier_offers.find_one({"_id": offer})


def get(db, kitchen_id: str, offer: str) -> dict | None:
    """One offer of this kitchen; another kitchen's offer is not found."""
    return db.supplier_offers.find_one({"_id": offer, "kitchen_id": kitchen_id})


def insert(db, doc: dict) -> tuple[dict, bool]:
    """Store the offer. `(stored, created)`: when the same offer or the same key is already
    there, the stored row comes back and nothing is written."""
    try:
        db.supplier_offers.insert_one(doc)
        return doc, True
    except DuplicateKeyError:
        stored = by_id(db, doc["_id"]) or by_key(db, doc["supplier_id"], doc["idempotency_key"])
        if stored is None:
            raise
        return stored, False


def list_for_kitchen(db, kitchen_id: str, limit: int = 50) -> list[dict]:
    """Newest first."""
    return list(db.supplier_offers.find({"kitchen_id": kitchen_id}).sort("created_at", -1).limit(limit))


def count_open(db, supplier_id: str, kitchen_id: str, today: str) -> int:
    """Open offers that are not past their date (`today` is YYYY-MM-DD)."""
    return db.supplier_offers.count_documents({
        "supplier_id": supplier_id, "kitchen_id": kitchen_id, "status": OPEN,
        "requested_date": {"$gte": today}})


def decide(db, kitchen_id: str, offer: str, status: str, **fields) -> dict | None:
    """OPEN -> `status`, once. The row after the change, or None when it was not OPEN."""
    if status not in (ACCEPTED, DECLINED):
        raise ValueError("status must be ACCEPTED or DECLINED")
    return db.supplier_offers.find_one_and_update(
        {"_id": offer, "kitchen_id": kitchen_id, "status": OPEN},
        {"$set": {"status": status, **fields}}, return_document=ReturnDocument.AFTER)
