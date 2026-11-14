"""Human corrections to proposals, kept as learning data (time series `feedback`).

One row per change: a quantity changed, a line removed or added, a rejection with its
reason, an approval. The corrected number is the label the forecast learns from, and
a product a kitchen keeps removing should stop being proposed.
"""

from __future__ import annotations

from datetime import datetime, timezone

from store.repository import KITCHEN_UNITS, _decimal, _from_store, _to_store

KINDS = ("qty_changed", "line_removed", "line_added", "rejected", "approved")
DECLINES_TO_STOP = 3


def _row(change: dict) -> dict:
    kind = change.get("kind")
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}")
    product = change.get("product_id")
    if kind in ("qty_changed", "line_removed", "line_added") and not product:
        raise ValueError(f"{kind} needs product_id")
    before = _decimal(change.get("from_qty"), "from_qty")
    after = _decimal(change.get("to_qty"), "to_qty")
    if kind == "qty_changed" and (before is None or after is None or before == after):
        raise ValueError("qty_changed needs different from_qty and to_qty")
    if kind == "rejected" and not change.get("reason"):
        raise ValueError("rejected needs a reason")
    unit = change.get("unit")
    if unit is not None and unit not in KITCHEN_UNITS and not str(unit).isupper():
        raise ValueError("unit must be a kitchen unit or a supplier unit code")
    return {"kind": kind, "product_id": None if product is None else str(product),
            "from_qty": before, "to_qty": after, "unit": unit, "reason": change.get("reason")}


def record_feedback(db, kitchen_id: str, proposal_id: str, changes: list[dict],
                    user: str) -> int:
    """Store one row per change a human made to a proposal. Returns how many."""
    if not user:
        raise ValueError("user is required: feedback is what a human did")
    now = datetime.now(timezone.utc)
    rows = []
    for change in changes:
        row = _row(change)  # validate everything before writing anything
        rows.append(_to_store({
            "ts": now, "meta": {"kitchen_id": kitchen_id, "product_id": row.pop("product_id")},
            "proposal_id": proposal_id, "user": user, **row}))
    if rows:
        db.feedback.insert_many(rows)
    return len(rows)


def list_feedback(db, kitchen_id: str, proposal_id: str | None = None,
                  product_id: str | None = None) -> list[dict]:
    """A kitchen's feedback rows, oldest first, optionally for one proposal or product."""
    query = {"meta.kitchen_id": kitchen_id}
    if proposal_id is not None:
        query["proposal_id"] = proposal_id
    if product_id is not None:
        query["meta.product_id"] = str(product_id)
    rows = []
    for doc in db.feedback.find(query, {"_id": 0}).sort("ts", 1):
        doc = _from_store(doc)
        meta = doc.pop("meta")
        rows.append({"kitchen_id": meta["kitchen_id"], "product_id": meta.get("product_id"), **doc})
    return rows


def declined_products(db, kitchen_id: str, threshold: int = DECLINES_TO_STOP) -> list[str]:
    """Products this kitchen removed from proposals at least `threshold` times.

    The engine should stop proposing them until a human adds one back: a `line_added`
    resets the count, so only removals after the latest add count.
    """
    declines: dict[str, int] = {}
    rows = db.feedback.find(
        {"meta.kitchen_id": kitchen_id, "kind": {"$in": ["line_removed", "line_added"]}},
        {"meta.product_id": 1, "kind": 1}).sort([("ts", 1), ("_id", 1)])
    for row in rows:
        product = row["meta"]["product_id"]
        declines[product] = declines.get(product, 0) + 1 if row["kind"] == "line_removed" else 0
    return sorted(product for product, count in declines.items() if count >= threshold)
