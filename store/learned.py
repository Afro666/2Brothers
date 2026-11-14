"""Learned-fact overrides: the only rows that switch a computed fact off.

Facts themselves are recomputed from feedback and delivery observations, so an
override names the fact evidence version and stays off until new evidence forms a
new id (contract, "Disable, privacy and audit").
"""

from __future__ import annotations

from pymongo.errors import DuplicateKeyError

COLLECTION = "learned_overrides"


def ensure_indexes(db) -> None:
    """One override per kitchen and fact version."""
    db[COLLECTION].create_index([("kitchen_id", 1), ("fact_id", 1)], unique=True)


def disabled_ids(db, kitchen_id: str) -> set[str]:
    """Fact ids this kitchen switched off."""
    ensure_indexes(db)
    return {row["fact_id"] for row in db[COLLECTION].find(
        {"kitchen_id": kitchen_id, "active": False}, {"fact_id": 1})}


def disable(db, kitchen_id: str, fact_id: str, by: str, at) -> bool:
    """Switch a fact off once; True only when this call changed its state."""
    ensure_indexes(db)
    row = db[COLLECTION].find_one({"kitchen_id": kitchen_id, "fact_id": fact_id})
    if row is not None:
        if row.get("active") is False:
            return False
        changed = db[COLLECTION].update_one(
            {"_id": row["_id"], "active": {"$ne": False}},
            {"$set": {"active": False, "by": by, "at": at}})
        return changed.modified_count == 1
    try:
        db[COLLECTION].insert_one({"kitchen_id": kitchen_id, "fact_id": fact_id,
                                   "active": False, "by": by, "at": at})
        return True
    except DuplicateKeyError:
        return False
