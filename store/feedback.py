"""Human corrections to proposals, kept as learning data (time series `feedback`).

One row per change: a quantity changed, a line removed or added, a rejection with its
reason, an approval. The corrected number is the label the forecast learns from, and
a product a kitchen keeps removing should stop being proposed.

Outcomes live separately: the `feedback` series is append-only, so a later stock count
is joined to its row by `feedback_id`, never written into the row.
"""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from decimal import Decimal
from uuid import uuid4

from store.repository import KITCHEN_UNITS, _decimal, _from_store, _to_store

KINDS = ("qty_changed", "line_removed", "line_added", "rejected", "approved")
CHANGE_KINDS = ("qty_changed", "line_removed", "line_added")
REASONS = ("TOO_MUCH", "TOO_LITTLE", "IN_STOCK", "MENU_CHANGED", "BUDGET", "OTHER")
NOTE_MAX = 200
DECLINES_TO_STOP = 3


def _row(change: dict) -> dict:
    kind = change.get("kind")
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}")
    product = change.get("product_id")
    if kind in CHANGE_KINDS and not product:
        raise ValueError(f"{kind} needs product_id")
    before = _decimal(change.get("from_qty"), "from_qty")
    after = _decimal(change.get("to_qty"), "to_qty")
    if kind == "qty_changed" and (before is None or after is None or before == after):
        raise ValueError("qty_changed needs different from_qty and to_qty")
    reason = change.get("reason")
    note = change.get("note")
    if kind == "rejected" and not reason:
        raise ValueError("rejected needs a reason")
    if kind in CHANGE_KINDS and reason is not None and reason not in REASONS:
        raise ValueError(f"reason must be one of {REASONS}")
    if note is not None:
        if not isinstance(note, str) or len(note) > NOTE_MAX:
            raise ValueError(f"note must be a string of at most {NOTE_MAX} characters")
        if reason != "OTHER":
            raise ValueError("note is only allowed with OTHER")
    unit = change.get("unit")
    if unit is not None and unit not in KITCHEN_UNITS and not str(unit).isupper():
        raise ValueError("unit must be a kitchen unit or a supplier unit code")
    context = change.get("context")
    if context is not None and not isinstance(context, dict):
        raise ValueError("context must be an object")
    return {"kind": kind, "product_id": None if product is None else str(product),
            "from_qty": before, "to_qty": after, "unit": unit, "reason": reason,
            "note": note, "total": _decimal(change.get("total"), "total"),
            "context": context}


def record_feedback(db, kitchen_id: str, proposal_id: str, changes: list[dict],
                    user: str) -> int:
    """Store one row per change a human made to a proposal. Returns how many."""
    if not user:
        raise ValueError("user is required: feedback is what a human did")
    now = datetime.now(timezone.utc)
    rows = []
    for change in changes:
        row = _row(change)  # validate everything before writing anything
        row["feedback_id"] = change.get("feedback_id") or uuid4().hex
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


def _as_datetime(value) -> datetime | None:
    """`since` accepts an ISO date, an ISO timestamp or a datetime; naive means UTC."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, date):
        return datetime.combine(value, time.min, tzinfo=timezone.utc)
    text = str(value).replace("Z", "+00:00")
    try:
        return _as_datetime(datetime.fromisoformat(text))
    except ValueError:
        return datetime.combine(date.fromisoformat(text), time.min, tzinfo=timezone.utc)


def _qty(value) -> str | None:
    return None if value is None else f"{Decimal(str(value)).normalize():f}"


def _iso(value) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else value


def _context_out(value) -> dict | None:
    if not isinstance(value, dict):
        return None
    return {"forecast_need": _qty(value.get("forecast_need")),
            "stock_position": _qty(value.get("stock_position")),
            "covers": value.get("covers"), "requested_date": value.get("requested_date"),
            "made_by": value.get("made_by"), "offer_id": value.get("offer_id")}


def _outcome_out(value: dict | None) -> dict:
    value = value or {}
    return {"next_count_at": _iso(value.get("next_count_at")),
            "next_count": _qty(value.get("next_count")),
            "ran_out": value.get("ran_out")}


def changes_for(db, kitchen_id: str, product_id: str | None = None, since=None,
                reasons: list[str] | None = None) -> list[dict]:
    """Joined change rows (feedback + its outcome), oldest first, as the contract's JSON.

    Legacy rows without `feedback_id` get an unknown outcome and are never joined by
    product: an outcome belongs to one row, not to everything that names the product.
    """
    query = {"meta.kitchen_id": kitchen_id}
    if product_id is not None:
        query["meta.product_id"] = str(product_id)
    start = _as_datetime(since)
    if start is not None:
        query["ts"] = {"$gte": start}
    if reasons is not None:
        query["reason"] = {"$in": list(reasons)}
    docs = [_from_store(doc) for doc in db.feedback.find(query, {"_id": 0}).sort("ts", 1)]
    ids = [doc.get("feedback_id") for doc in docs if doc.get("feedback_id")]
    outcomes = {row["feedback_id"]: row for row in db.feedback_outcomes.find(
        {"kitchen_id": kitchen_id, "feedback_id": {"$in": ids}})}
    rows = []
    for doc in docs:
        meta = doc.pop("meta")
        row = {"feedback_id": doc.get("feedback_id"), "ts": _iso(doc.get("ts")),
               "kitchen_id": meta["kitchen_id"], "proposal_id": doc.get("proposal_id"),
               "product_id": meta.get("product_id"), "user": doc.get("user"),
               "kind": doc.get("kind"), "from_qty": _qty(doc.get("from_qty")),
               "to_qty": _qty(doc.get("to_qty")), "unit": doc.get("unit"),
               "reason": doc.get("reason"), "note": doc.get("note"),
               "context": _context_out(doc.get("context")),
               "outcome": _outcome_out(outcomes.get(doc.get("feedback_id")))}
        if doc.get("kind") in ("approved", "rejected"):
            row["total"] = _qty(doc.get("total"))
        rows.append(row)
    return rows


def fill_outcomes(db, kitchen_id: str) -> int:
    """Link each change row without an outcome to the next stock count after its date.

    A count says what is on hand, not whether the kitchen ran out; `ran_out` stays null.
    Rows without a later count wait for one, and an existing outcome is never rewritten.
    """
    known = {row["feedback_id"] for row in db.feedback_outcomes.find(
        {"kitchen_id": kitchen_id}, {"feedback_id": 1})}
    written = 0
    query = {"meta.kitchen_id": kitchen_id, "kind": {"$in": list(CHANGE_KINDS)}}
    for doc in db.feedback.find(query).sort("ts", 1):
        feedback_id = doc.get("feedback_id")
        product_id = (doc.get("meta") or {}).get("product_id")
        if not feedback_id or feedback_id in known or not product_id:
            continue
        row = _from_store(doc)
        context = row.get("context") or {}
        day = context.get("requested_date")
        try:
            day = date.fromisoformat(str(day))
        except ValueError:
            day = row["ts"].date()
        after = datetime.combine(day, time.min, tzinfo=timezone.utc)
        count = db.kitchen_stock.find_one(
            {"meta.kitchen_id": kitchen_id, "meta.product_id": str(product_id),
             "ts": {"$gt": after}}, sort=[("ts", 1)])
        if count is None:
            continue
        count = _from_store(count)
        outcome = _to_store({
            "_id": f"{kitchen_id}:{feedback_id}", "kitchen_id": kitchen_id,
            "feedback_id": feedback_id, "next_count_at": count["ts"],
            "next_count": count.get("on_hand"), "ran_out": None})
        db.feedback_outcomes.update_one({"_id": outcome["_id"]},
                                        {"$setOnInsert": outcome}, upsert=True)
        known.add(feedback_id)
        written += 1
    return written


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
