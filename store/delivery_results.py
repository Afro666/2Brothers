"""Versioned delivery observations (#1304).

The contract keeps every reading as an immutable time-series row and lets readers see only
the current version per kitchen and order. delivery_result_current is that selector, so a
recheck advances a revision without making an old reading count twice. Raw photos, note text,
lot codes and best-before text never enter this module.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation
import hashlib
from uuid import uuid4

from pymongo.errors import DuplicateKeyError

from store.audit import canonical

RESULTS = "delivery_results"
CURRENT = "delivery_result_current"
KEYS = "delivery_received_keys"

LINE_STATUSES = ("RECEIVED", "SHORT", "MISSING", "UNKNOWN")
OTHER_STATUSES = ("SUBSTITUTE", "EXTRA", "UNREADABLE")
SOURCES = ("photo", "manual_complete")


class IdempotencyConflict(Exception):
    """The received key was already used for a different order or body."""


def _ensure_indexes(db) -> None:
    db[CURRENT].create_index([("kitchen_id", 1), ("order_id", 1)], unique=True)
    db[KEYS].create_index([("kitchen_id", 1), ("idempotency_key", 1)], unique=True)
    db[RESULTS].create_index([("kitchen_id", 1), ("order_id", 1), ("revision", -1)])
    # Photos omit this field; only received operations need an exactly-once fence.
    db[RESULTS].create_index("_operation_id", unique=True, sparse=True)


def _date(value) -> str | None:
    """An ISO calendar date, or None for an unknown note date."""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if not isinstance(value, str) or value.strip().lower() == "unknown":
        return None
    try:
        return date.fromisoformat(value.strip()).isoformat()
    except ValueError:
        return None


def _timestamp(value) -> str | None:
    """An ISO timestamp with an offset; a naive value is UTC, never local guesswork."""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _qty(value) -> str | None:
    """A finite decimal string, without the binary floats the store refuses."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not number.is_finite():
        return None
    return format(number.normalize(), "f") if number else "0"


def _text(value) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    return None if not text or text.lower() == "unknown" else text


def _status(value, allowed) -> str | None:
    return value if isinstance(value, str) and value in allowed else None


def _line(raw: dict) -> dict:
    return {"supplier_id": _text(raw.get("supplier_id")),
            "product_id": _text(raw.get("product_id")),
            "status": raw["status"], "ordered": _qty(raw.get("ordered")),
            "delivered": _qty(raw.get("delivered")), "unit": _text(raw.get("unit"))}


def _other(raw: dict) -> dict:
    return {"supplier_id": _text(raw.get("supplier_id")),
            "product_id": _text(raw.get("product_id")), "status": raw["status"],
            "delivered": _qty(raw.get("delivered")), "unit": _text(raw.get("unit"))}


def _observation(*, kitchen_id: str, order_id: str, supplier_id, requested_date,
                 ordered_at, delivery_date, checked_by: str, checked_at,
                 source: str, lines: list[dict], not_ordered: list[dict]) -> dict:
    if source not in SOURCES:
        raise ValueError(f"source must be one of {SOURCES}")
    clean_lines = []
    for raw in lines:
        status = _status(raw.get("status"), LINE_STATUSES)
        if status is None:
            raise ValueError(f"line status must be one of {LINE_STATUSES}")
        clean_lines.append(_line({**raw, "status": status}))
    clean_others = []
    for raw in not_ordered:
        status = _status(raw.get("status"), OTHER_STATUSES)
        if status is None:
            raise ValueError(f"not_ordered status must be one of {OTHER_STATUSES}")
        clean_others.append(_other({**raw, "status": status}))
    requested, delivered = _date(requested_date), _date(delivery_date)
    days_late = None
    if requested is not None and delivered is not None:
        days_late = (date.fromisoformat(delivered) - date.fromisoformat(requested)).days
    return {"kitchen_id": kitchen_id, "order_id": order_id,
            "supplier_id": _text(supplier_id), "requested_date": requested,
            "ordered_at": _timestamp(ordered_at), "delivery_date": delivered,
            "days_late": days_late, "checked_by": checked_by,
            "checked_at": _timestamp(checked_at), "source": source,
            "lines": clean_lines, "not_ordered": clean_others}


def _public(doc: dict) -> dict:
    out = deepcopy(doc)
    out.pop("_id", None)
    out.pop("_operation_id", None)
    return out


def _row(db, result_id: str, revision: int) -> dict | None:
    return db[RESULTS].find_one({"_id": f"{result_id}:{revision}"})


def _current(db, kitchen_id: str, order_id: str) -> dict | None:
    doc = db[CURRENT].find_one({"kitchen_id": kitchen_id, "order_id": order_id})
    if doc is not None:
        return doc
    return db[RESULTS].find_one({"kitchen_id": kitchen_id, "order_id": order_id},
                                sort=[("revision", -1)])


APPEND_TRIES = 5


def _move_current(db, kitchen_id: str, order_id: str, result_id: str,
                  revision: int) -> None:
    """Move the selector forward only, so a slower older save cannot move it back."""
    try:
        db[CURRENT].update_one(
            {"kitchen_id": kitchen_id, "order_id": order_id,
             "revision": {"$lt": revision}},
            {"$set": {"result_id": result_id, "revision": revision}}, upsert=True)
    except DuplicateKeyError:
        pass  # the selector already points at this or a newer revision


def _operation_row(db, observation: dict) -> dict | None:
    if not observation.get("_operation_id"):
        return None
    return db[RESULTS].find_one({"kitchen_id": observation["kitchen_id"],
        "order_id": observation["order_id"], "_operation_id": observation["_operation_id"]})


def _recover_operation(db, row: dict) -> dict:
    _move_current(db, row["kitchen_id"], row["order_id"],
                  row["result_id"], int(row["revision"]))
    return _public(row)


def _append(db, observation: dict) -> dict:
    """Write one immutable revision, then move the kitchen+order selector to it.

    Two saves at once can read the same revision; the loser's insert hits the unique _id,
    so it reads the current revision again and takes the next one.
    """
    kitchen_id, order_id = observation["kitchen_id"], observation["order_id"]
    existing = _operation_row(db, observation)
    if existing is not None:
        return _recover_operation(db, existing)
    for _ in range(APPEND_TRIES):
        current = _current(db, kitchen_id, order_id)
        if current is None:
            # Claim the selector at revision 0, so racing first saves share one result_id.
            try:
                db[CURRENT].insert_one({"kitchen_id": kitchen_id, "order_id": order_id,
                                        "result_id": "dr-" + uuid4().hex, "revision": 0})
            except DuplicateKeyError:
                pass
            current = _current(db, kitchen_id, order_id)
        result_id, revision = current["result_id"], int(current["revision"]) + 1
        row = {"_id": f"{result_id}:{revision}", **observation,
               "result_id": result_id, "revision": revision}
        try:
            db[RESULTS].insert_one(row)
        except DuplicateKeyError:
            existing = _operation_row(db, observation)
            if existing is not None:
                return _recover_operation(db, existing)
            # The winner may not have moved the selector yet: move it to the newest row.
            latest = db[RESULTS].find_one({"result_id": result_id},
                                          sort=[("revision", -1)])
            if latest is not None:
                _move_current(db, kitchen_id, order_id, result_id,
                              int(latest["revision"]))
            continue
        _move_current(db, kitchen_id, order_id, result_id, revision)
        return _public(row)
    raise RuntimeError("too many concurrent delivery saves for this order")


def save_observation(db, *, kitchen_id: str, order_id: str, supplier_id,
                     requested_date, ordered_at, delivery_date, checked_by: str,
                     checked_at, source: str, lines: list[dict],
                     not_ordered: list[dict]) -> dict:
    """Append one photo or manual reading and return the stored public observation."""
    _ensure_indexes(db)
    observation = _observation(kitchen_id=kitchen_id, order_id=order_id,
                               supplier_id=supplier_id, requested_date=requested_date,
                               ordered_at=ordered_at, delivery_date=delivery_date,
                               checked_by=checked_by, checked_at=checked_at, source=source,
                               lines=lines, not_ordered=not_ordered)
    return _append(db, observation)


def _payload_hash(order_id: str, delivery_date: str, key: str) -> str:
    payload = {"order_id": order_id, "delivery_date": delivery_date,
               "complete": True, "idempotency_key": key}
    return hashlib.sha256(canonical(payload).encode()).hexdigest()


def save_received(db, *, kitchen_id: str, order_id: str, idempotency_key: str,
                  delivery_date, supplier_id, requested_date, ordered_at,
                  checked_by: str, checked_at, lines: list[dict]) -> tuple[dict, bool]:
    """Save the one-tap observation once. Returns (result, created); a replay is exact."""
    _ensure_indexes(db)
    day = _date(delivery_date)
    if day is None:
        raise ValueError("delivery_date must be an ISO date")
    payload_hash = _payload_hash(order_id, day, idempotency_key)
    key_filter = {"kitchen_id": kitchen_id, "idempotency_key": idempotency_key}
    seen = db[KEYS].find_one(key_filter)
    if seen is not None:
        return _replay(db, key_filter, seen, payload_hash), False

    observation = _observation(kitchen_id=kitchen_id, order_id=order_id,
                               supplier_id=supplier_id, requested_date=requested_date,
                               ordered_at=ordered_at, delivery_date=day,
                               checked_by=checked_by, checked_at=checked_at,
                               source="manual_complete", lines=lines, not_ordered=[])
    # A private durable identity lets retries find a committed append even if finalization fails.
    operation_id = uuid4().hex
    observation["_operation_id"] = operation_id
    try:
        db[KEYS].insert_one({**key_filter, "order_id": order_id, "operation_id": operation_id,
                            "payload_hash": payload_hash, "pending": True,
                            "observation": observation})
    except DuplicateKeyError:
        winner = db[KEYS].find_one(key_filter)
        if winner is None:
            raise RuntimeError("the received key reservation is missing") from None
        return _replay(db, key_filter, winner, payload_hash), False
    # Keep an ambiguous reservation: deleting it could allow a duplicate late write.
    result = _append(db, observation)
    db[KEYS].update_one({**key_filter, "operation_id": operation_id, "pending": True},
                       {"$set": {"result_id": result["result_id"], "revision": result["revision"]},
                        "$unset": {"pending": "", "observation": ""}})
    return result, True


def _replay(db, key_filter: dict, seen: dict, payload_hash: str) -> dict:
    """Resume the reserved observation, or return the key's exact stored result."""
    if seen.get("payload_hash") != payload_hash:
        raise IdempotencyConflict(key_filter["idempotency_key"])
    if seen.get("pending"):
        operation_id, order_id = seen.get("operation_id"), seen.get("order_id")
        stored = None
        if operation_id is not None and order_id is not None:
            stored = db[RESULTS].find_one({"kitchen_id": key_filter["kitchen_id"],
                "order_id": order_id, "_operation_id": operation_id})
        if stored is not None:
            result = _recover_operation(db, stored)
        else:
            observation = seen.get("observation")
            if (not isinstance(observation, dict) or not operation_id
                    or observation.get("_operation_id") != operation_id
                    or observation.get("kitchen_id") != key_filter["kitchen_id"]
                    or observation.get("order_id") != order_id):
                raise RuntimeError("the pending received key has no valid stored snapshot")
            # The unique operation index fences both retries and a still-running writer.
            result = _append(db, observation)
        db[KEYS].update_one({**key_filter, "operation_id": operation_id, "pending": True},
            {"$set": {"result_id": result["result_id"], "revision": result["revision"]},
             "$unset": {"pending": "", "observation": ""}})
        return result
    stored = _row(db, seen["result_id"], seen["revision"])
    if stored is None:
        raise RuntimeError("the saved received result is missing")
    return _public(stored)


def _since_value(value) -> str | None:
    if isinstance(value, datetime):
        return _timestamp(value)
    if isinstance(value, date):
        return _timestamp(datetime.combine(value, time.min, tzinfo=timezone.utc))
    if isinstance(value, str):
        try:
            return _timestamp(datetime.fromisoformat(value.strip().replace("Z", "+00:00")))
        except ValueError:
            try:
                return _timestamp(datetime.combine(date.fromisoformat(value.strip()),
                                                   time.min, tzinfo=timezone.utc))
            except ValueError:
                return None
    return None


def _matches(row: dict, supplier_id: str | None, product_id: str | None) -> bool:
    lines = [*row.get("lines", []), *row.get("not_ordered", [])]
    if supplier_id is not None and not (
            row.get("supplier_id") == supplier_id
            or any(ln.get("supplier_id") == supplier_id for ln in lines)):
        return False
    if product_id is not None and not any(ln.get("product_id") == product_id
                                          for ln in lines):
        return False
    return True


def delivery_history(db, kitchen_id: str, supplier_id: str | None = None,
                     product_id: str | None = None, since=None) -> list[dict]:
    """Current observations for one kitchen, oldest first, optionally by supplier/product."""
    selectors = list(db[CURRENT].find({"kitchen_id": kitchen_id}))
    if selectors:
        rows = [row for sel in selectors
                if (row := _row(db, sel["result_id"], sel["revision"])) is not None]
    else:
        latest = {}
        for row in db[RESULTS].find({"kitchen_id": kitchen_id}):
            key = row.get("order_id")
            if key not in latest or row.get("revision", 0) > latest[key].get("revision", 0):
                latest[key] = row
        rows = list(latest.values())
    floor = _since_value(since) if since is not None else None
    rows = [row for row in rows if _matches(row, supplier_id, product_id)
            and (floor is None or (row.get("checked_at") or "") >= floor)]
    rows.sort(key=lambda row: (row.get("checked_at") or "", row.get("result_id") or "",
                               row.get("revision") or 0))
    return [_public(row) for row in rows]
