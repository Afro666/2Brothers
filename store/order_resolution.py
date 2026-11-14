"""One atomic write: a person resolves an order whose send result is unknown (#291).

`orders.set_outcome` is unconditional, so two people with different answers could both
win. This claim changes the row only while it is still unknown and unresolved.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pymongo import ReturnDocument

RESOLVABLE = ("UNCONFIRMED", "SENT_READ_FAILED")
RESOLVED = ("CONFIRMED", "NOT_SENT")


def resolve_order(db, kitchen_id: str, order_id: str, *, outcome: str, status: str | None,
                  resolution: dict) -> dict | None:
    """Store `resolution` and the resolved `outcome` on the order, once.

    Returns the updated order, or None when the order is not this kitchen's, is not
    UNCONFIRMED / SENT_READ_FAILED, or already holds a resolution. The row changes in
    place: no second attempt row is written.
    """
    if outcome not in RESOLVED:
        raise ValueError(f"outcome must be one of {RESOLVED}")
    doc = db.orders.find_one_and_update(
        {"_id": order_id, "kitchen_id": kitchen_id, "outcome": {"$in": list(RESOLVABLE)},
         "resolution": None},
        {"$set": {"outcome": outcome, "status": status, "resolution": resolution,
                  "updated_at": datetime.now(timezone.utc)}},
        return_document=ReturnDocument.AFTER)
    if doc is not None:
        doc["order_id"] = doc.pop("_id")
    return doc
