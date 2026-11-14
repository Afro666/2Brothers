"""Time-series history, forecasts and forecast-sharing consent.

Load the synthetic history from `env/history.py`:
`python -m env.history --seed 1 && python -m store.history [--dir env/out/history]`.

Time-series collections (`timeField: "ts"`, `metaField: "meta"`): `kitchen_stock`,
`covers`, `orders_history`, `deliveries`, `forecasts`, `feedback`. Quantities are in
kitchen units (`L`, `KG`, `PCS`), as docs/contract.md says.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from bson import json_util

from store import audit
from store.db import get_db
from store.repository import KITCHEN_UNITS, _decimal, _from_store, _to_store

SERIES = {"stock": "kitchen_stock", "covers": "covers", "orders": "orders_history",
          "deliveries": "deliveries"}
_JSON = json_util.DEFAULT_JSON_OPTIONS.with_options(tz_aware=True)


def ensure_history_collections(db) -> None:
    """Create the time-series collections and the consent index. Safe to run again."""
    existing = set(db.list_collection_names())
    for name in (*SERIES.values(), "forecasts", "feedback"):
        if name not in existing:
            db.create_collection(name, timeseries={"timeField": "ts", "metaField": "meta",
                                                   "granularity": "hours"})
    db.sharing.create_index([("kitchen_id", 1), ("supplier_id", 1)], unique=True)


def _rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return [json_util.loads(line, json_options=_JSON) for line in handle if line.strip()]


def _money(order: dict) -> dict:
    """The generator writes prices as floats; money is stored as Decimal."""
    order["total_eur"] = Decimal(str(order["total_eur"]))
    for line in order["lines"]:
        line["unit_price"] = Decimal(str(line["unit_price"]))
        line["line_total"] = Decimal(str(line["line_total"]))
    return order


def load_history(db, directory: Path) -> dict[str, int]:
    """Replace the history of the kitchens in `kitchens.jsonl`. Other kitchens' rows stay."""
    ensure_history_collections(db)
    kitchens = _rows(directory / "kitchens.jsonl")
    ids = [kitchen["kitchen_id"] for kitchen in kitchens]
    counts = {}
    for kitchen in kitchens:
        db.kitchens.replace_one({"_id": kitchen["kitchen_id"]},
                                {**kitchen, "_id": kitchen["kitchen_id"], "synthetic": True},
                                upsert=True)
    counts["kitchens"] = len(kitchens)
    for stem, name in SERIES.items():
        rows = _rows(directory / f"{stem}.jsonl")
        if stem == "orders":
            rows = [_money(row) for row in rows]
        # Time-series rows cannot be upserted: delete these kitchens' rows, then insert.
        db[name].delete_many({"meta.kitchen_id": {"$in": ids}})
        for start in range(0, len(rows), 5000):
            db[name].insert_many(rows[start:start + 5000], ordered=False)
        counts[name] = len(rows)
    return counts


# Consent: one record per kitchen and supplier (contract: "Consent record").

def set_sharing(db, kitchen_id: str, supplier_id: str, share_forecast: bool,
                user: str) -> dict | None:
    """Grant or revoke forecast sharing. `user` is a human, never the Buyer or an API key.

    Every real change writes an audit entry (`share_granted` / `share_revoked`) with who
    and when. Asking for the state that already holds changes nothing and logs nothing.
    """
    if not user:
        raise ValueError("user is required")
    key = {"kitchen_id": kitchen_id, "supplier_id": supplier_id}
    current = db.sharing.find_one(key, {"_id": 0})
    active = bool(current and current["share_forecast"] and current["revoked_at"] is None)
    if active == bool(share_forecast):
        return current
    now = datetime.now(timezone.utc)
    change = ({"share_forecast": True, "granted_at": now, "granted_by": user,
               "revoked_at": None} if share_forecast
              else {"share_forecast": False, "revoked_at": now, "revoked_by": user})

    def log() -> None:
        audit.append_event(
            db, {"event_id": uuid4().hex, **key, "scope": "forecast_only", "user": user,
                 "type": "share_granted" if share_forecast else "share_revoked"},
            server={"kitchen_id": kitchen_id, "principal": user})

    # A grant is logged before it takes effect and a revoke after it: if the second
    # write fails, the kitchen is never sharing without an audit entry.
    if share_forecast:
        log()
    db.sharing.update_one(key, {"$set": {**change, "scope": "forecast_only"}}, upsert=True)
    if not share_forecast:
        log()
    return db.sharing.find_one(key, {"_id": 0})


def seed_sharing(db, kitchen_ids: list[str], supplier_id: str) -> list[str]:
    """Demo data: four in five synthetic kitchens share their forecast, every fifth
    does not, so the consent rule is visible. Recorded as granted by `synthetic-seed`."""
    sharing = [kitchen for index, kitchen in enumerate(sorted(kitchen_ids)) if index % 5 != 4]
    for kitchen in sharing:
        set_sharing(db, kitchen, supplier_id, True, "synthetic-seed")
    return sharing


def list_sharing(db, kitchen_id: str) -> list[dict]:
    return list(db.sharing.find({"kitchen_id": kitchen_id}, {"_id": 0}).sort("supplier_id", 1))


def consenting_kitchens(db, supplier_id: str) -> list[str]:
    """Kitchens with active consent for this supplier: shared and not revoked."""
    return sorted(db.sharing.distinct("kitchen_id", {
        "supplier_id": supplier_id, "share_forecast": True, "revoked_at": None}))


# Demand

def save_forecasts(db, rows: list[dict], collection: str = "forecasts") -> int:
    """Rows from the engine: `kitchen_id`, `product_id`, `date`, `need`, `unit`, `why`.

    Optional `method` and `made_on` (the day the forecast was made) let a past forecast be
    compared with what really happened. `collection="forecast_baseline"` keeps a comparison
    method out of `forecasts`, which the Valio demand view sums.
    """
    if collection not in ("forecasts", "forecast_baseline"):
        raise ValueError("collection must be forecasts or forecast_baseline")
    docs = [{"ts": _day(row["date"]),
             "meta": {"kitchen_id": row["kitchen_id"], "product_id": row["product_id"]},
             "need": Decimal(str(row["need"])), "unit": row["unit"], "why": row.get("why"),
             "method": row.get("method"), "made_on": row.get("made_on")}
            for row in rows]
    # Time-series rows cannot be upserted: a re-run replaces the same kitchen/product/day.
    keys = list({(d["meta"]["kitchen_id"], d["meta"]["product_id"], d["ts"]): None
                 for d in docs})
    for start in range(0, len(keys), 1000):
        db[collection].delete_many({"$or": [
            {"meta.kitchen_id": k, "meta.product_id": p, "ts": t}
            for k, p, t in keys[start:start + 1000]]})
    for start in range(0, len(docs), 5000):
        db[collection].insert_many(docs[start:start + 5000], ordered=False)
    return len(docs)


def forecast_vs_actual(db, kitchen_id: str, start, end, collection: str = "forecasts") -> list[tuple]:
    """(product_id, day, predicted, actual) for days that have both a forecast and a count.

    Actual demand is used + short (what the kitchen needed, also during a stock-out).
    The weekday baseline must have observed the product on that weekday before its
    forecast origin. This also removes warm-up placeholders in legacy seeded data.
    """
    if collection not in ("forecasts", "forecast_baseline"):
        raise ValueError("collection must be forecasts or forecast_baseline")
    window = {"meta.kitchen_id": kitchen_id, "ts": {"$gte": _day(start), "$lte": _day(end, end=True)}}
    forecasts = list(db[collection].find(window))
    if collection == 'forecast_baseline':
        forecasts = _with_weekday_history(db, kitchen_id, forecasts)
    predicted = {(d["meta"]["product_id"], d["ts"].date()): float(str(d["need"]))
                 for d in forecasts}
    out = []
    for d in db.kitchen_stock.find({**window, "used": {"$exists": True, "$ne": None}}):
        key = (d["meta"]["product_id"], d["ts"].date())
        if key in predicted:
            out.append((key[0], key[1], predicted[key], float(d["used"]) + float(d.get("short") or 0)))
    return out


def _with_weekday_history(db, kitchen_id: str, forecasts: list[dict]) -> list[dict]:
    """Keep baseline rows with actual history available at issuance, not at the target.

    Older rows without made_on use the documented Monday origin. Training history
    is read independently of the requested display window, and never across kitchens.
    """
    dated = []
    for row in forecasts:
        day = row['ts'].date()
        try:
            origin = date.fromisoformat(row['made_on']) if row.get('made_on') else day - timedelta(days=day.weekday())
        except (TypeError, ValueError):
            continue  # an invalid origin cannot establish point-in-time eligibility
        if origin <= day:
            dated.append((row, origin))
    if not dated:
        return []
    first = {}
    match = {'meta.kitchen_id': kitchen_id,
             'meta.product_id': {'$in': list({r['meta']['product_id'] for r, _ in dated})},
             'ts': {'$lt': _day(max(origin for _, origin in dated))},
             'used': {'$exists': True, '$ne': None}}
    for row in db.kitchen_stock.find(match, {'meta.product_id': 1, 'ts': 1}):
        day = row['ts'].date()
        key = (row['meta']['product_id'], day.weekday())
        first[key] = min(first.get(key, day), day)
    return [row for row, origin in dated
            if first.get((row['meta']['product_id'], row['ts'].weekday()), origin) < origin]


def _day(value, end: bool = False) -> datetime:
    day = date.fromisoformat(value) if isinstance(value, str) else value
    return datetime.combine(day, time.max if end else time.min, tzinfo=timezone.utc)


def _demand(db, source: str, match: dict, product_id: str, start, end) -> list[dict]:
    """Per day: each kitchen's demand, their sum and how many kitchens it covers."""
    collection, quantity = {
        # What the kitchen needed that day: what it used plus what it could not serve.
        "history": (db.kitchen_stock, {"$add": ["$used", "$short"]}),
        "forecast": (db.forecasts, "$need"),
    }[source]
    if source == "history":
        # A stock count alone (no usage) is unknown demand, not zero demand.
        match = {**match, "used": {"$exists": True, "$ne": None}}
    rows = collection.aggregate([
        {"$match": {**match, "meta.product_id": str(product_id),
                    "ts": {"$gte": _day(start), "$lte": _day(end, end=True)}}},
        {"$group": {"_id": {"date": {"$dateToString": {"format": "%Y-%m-%d", "date": "$ts"}},
                            "unit": "$unit", "kitchen_id": "$meta.kitchen_id"},
                    "demand": {"$sum": quantity}}},
        {"$sort": {"_id.date": 1, "_id.kitchen_id": 1}},
    ])
    days: dict = {}
    for row in rows:
        key = row["_id"]
        day = days.setdefault((key["date"], key["unit"]), {
            "product_id": str(product_id), "date": key["date"], "unit": key["unit"],
            "demand": 0, "kitchens": 0, "by_kitchen": []})
        day["demand"] += row["demand"]
        day["kitchens"] += 1
        day["by_kitchen"].append({"kitchen_id": key["kitchen_id"], "demand": row["demand"]})
    return list(days.values())


def kitchen_demand(db, kitchen_id: str, product_id: str, start, end,
                   source: str = "history") -> list[dict]:
    """One kitchen's daily demand for one product, `start` to `end` inclusive."""
    rows = _demand(db, source, {"meta.kitchen_id": kitchen_id}, product_id, start, end)
    return [{key: value for key, value in row.items() if key != "by_kitchen"} for row in rows]


def supplier_demand(db, supplier_id: str, product_id: str, start, end,
                    source: str = "history") -> list[dict]:
    """Daily demand of the kitchens that share their forecast with this supplier.

    Each row has the sum and `by_kitchen`: every consenting kitchen by id and name with
    its own demand. The kitchen agreed to be named when it shared (the consent text says
    so), so there is no minimum group size. A kitchen without active consent appears
    nowhere: not in the sum, not in the list.
    """
    kitchens = consenting_kitchens(db, supplier_id)
    names = {kitchen["_id"]: kitchen.get("name")
             for kitchen in db.kitchens.find({"_id": {"$in": kitchens}}, {"name": 1})}
    rows = _demand(db, source, {"meta.kitchen_id": {"$in": kitchens}}, product_id, start, end)
    for row in rows:
        row["by_kitchen"] = [{"kitchen_id": entry["kitchen_id"],
                              "kitchen_name": names.get(entry["kitchen_id"]),
                              "demand": entry["demand"]} for entry in row["by_kitchen"]]
    return rows


def supplier_forecasts(db, supplier_id: str, start, end,
                       product_id: str | None = None) -> tuple[dict[str, str | None], list[dict]]:
    """The consenting kitchens (id -> name) and their forecast rows, `start` to `end` inclusive.

    Rows: `kitchen_id`, `product_id`, `day` (ISO date), `need` (as stored), `unit`.
    A kitchen without active consent for this supplier is in neither.
    """
    kitchens = consenting_kitchens(db, supplier_id)
    if not kitchens:
        return {}, []
    names = {k: None for k in kitchens}
    names.update({k["_id"]: k.get("name") for k in db.kitchens.find({"_id": {"$in": kitchens}}, {"name": 1})})
    query = {"meta.kitchen_id": {"$in": kitchens}, "ts": {"$gte": _day(start), "$lte": _day(end, end=True)}}
    if product_id:
        query["meta.product_id"] = str(product_id)
    rows = [{"kitchen_id": row["meta"]["kitchen_id"], "product_id": row["meta"]["product_id"],
             "day": row["ts"].date().isoformat(), "need": row["need"], "unit": row["unit"]}
            for row in db.forecasts.find(query)]
    return names, rows


def product_docs(db, product_ids) -> dict[str, dict]:
    """Catalog docs by id with `names`, `units`, `sales_unit` and `net_content` only."""
    return {d["_id"]: d for d in db.products.find(
        {"_id": {"$in": list(product_ids)}}, {"names": 1, "units": 1, "sales_unit": 1, "net_content": 1})}


# Stock counts from the kitchen (POST /stock-counts)

STALE_CLAIM = timedelta(seconds=60)


class StockCountBusy(RuntimeError):
    """The same idempotency key is being stored right now by another request."""


def stock_count_once(db, kitchen_id: str, key: str, store) -> tuple[str, int, bool]:
    """Run `store()` (it writes the count, returns the number of lines) at most once per
    `(kitchen_id, key)`. Returns `(stock_count_id, stored, replayed)`.

    The key row is claimed first, with the key as `_id`, so two replays at the same moment
    cannot both store (#646). A failed store releases the claim, so the key can be retried.
    A claim older than `STALE_CLAIM` (its process died) is taken over.
    """
    from pymongo.errors import DuplicateKeyError
    count_id = f"{kitchen_id}:{key}"
    now = datetime.now(timezone.utc)
    try:
        db.stock_count_keys.insert_one({"_id": count_id, "stock_count_id": count_id, "stored": None,
                                        "claimed_at": now})
    except DuplicateKeyError:
        done = db.stock_count_keys.find_one({"_id": count_id}) or {}
        if done.get("stored") is not None:
            return count_id, done["stored"], True
        claimed = done.get("claimed_at")
        if claimed is not None and claimed.tzinfo is None:
            claimed = claimed.replace(tzinfo=timezone.utc)
        # A claim left by a process that died before storing is taken over (#873).
        if claimed is not None and now - claimed < STALE_CLAIM:
            raise StockCountBusy(count_id) from None
        if not db.stock_count_keys.find_one_and_update(
                {"_id": count_id, "stored": None, "claimed_at": done.get("claimed_at")},
                {"$set": {"claimed_at": now}}):
            raise StockCountBusy(count_id) from None
    try:
        stored = store()
    except BaseException:
        db.stock_count_keys.delete_one({"_id": count_id, "stored": None})
        raise
    db.stock_count_keys.update_one({"_id": count_id}, {"$set": {"stored": stored}})
    return count_id, stored, False


def forecasts_between(db, kitchen_id: str, lo: datetime, hi: datetime) -> list[dict]:
    """The kitchen's stored forecast rows with `lo <= ts <= hi`."""
    return list(db.forecasts.find({"meta.kitchen_id": kitchen_id, "ts": {"$gte": lo, "$lte": hi}}))


def record_stock_count(db, kitchen_id: str, counted_at: datetime, counts: list[dict],
                       source: str = "manual") -> int:
    """Store a stock count: one `kitchen_stock` row per product.

    `on_hand: None` is kept as "not counted": unknown, never zero. Nothing is written
    unless every line is valid.
    """
    if counted_at.tzinfo is None:
        raise ValueError("counted_at must carry a timezone")
    if source not in ("manual", "pos", "csv"):
        raise ValueError("source must be manual, pos or csv")
    rows = []
    for line in counts:
        if not line.get("product_id") or line.get("unit") not in KITCHEN_UNITS:
            raise ValueError(f"each count needs product_id and a unit from {KITCHEN_UNITS}")
        rows.append(_to_store({
            "ts": counted_at, "meta": {"kitchen_id": kitchen_id, "product_id": str(line["product_id"])},
            "unit": line["unit"], "on_hand": _decimal(line.get("on_hand"), "on_hand"),
            "source": source}))
    if rows:
        db.kitchen_stock.insert_many(rows)
    return len(rows)


def current_stock(db, kitchen_id: str) -> list[dict]:
    """The latest count per product: `product_id`, `unit`, `on_hand`, `counted_at`."""
    rows = db.kitchen_stock.aggregate([
        {"$match": {"meta.kitchen_id": kitchen_id}},
        {"$sort": {"ts": -1}},
        {"$group": {"_id": "$meta.product_id", "unit": {"$first": "$unit"},
                    "on_hand": {"$first": "$on_hand"}, "counted_at": {"$first": "$ts"}}},
        {"$sort": {"_id": 1}},
    ])
    return [_from_store({"product_id": row["_id"], "unit": row["unit"],
                         "on_hand": row["on_hand"], "counted_at": row["counted_at"]})
            for row in rows]


def main() -> None:
    parser = argparse.ArgumentParser(description="Load the synthetic kitchen history.")
    parser.add_argument("--dir", type=Path, default=Path("env/out/history"))
    parser.add_argument("--share-with", metavar="SUPPLIER_ID",
                        help="demo: let four in five of these kitchens share with this supplier")
    args = parser.parse_args()
    db = get_db()
    for name, count in load_history(db, args.dir).items():
        print(f"{name}: {count} rows")
    if args.share_with:
        kitchens = [row["kitchen_id"] for row in _rows(args.dir / "kitchens.jsonl")]
        sharing = seed_sharing(db, kitchens, args.share_with)
        print(f"sharing with {args.share_with}: {len(sharing)} of {len(kitchens)} kitchens")


if __name__ == "__main__":
    main()
