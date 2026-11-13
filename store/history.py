"""Time-series history, forecasts and forecast-sharing consent.

Load the synthetic history from `env/history.py`:
`python -m env.history --seed 1 && python -m store.history [--dir env/out/history]`.

Time-series collections (`timeField: "ts"`, `metaField: "meta"`): `kitchen_stock`,
`covers`, `orders_history`, `deliveries`, `forecasts`, `feedback`. Quantities are in
kitchen units (`L`, `KG`, `PCS`), as docs/contract.md says.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, time, timezone
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

def save_forecasts(db, rows: list[dict]) -> int:
    """Rows from the engine: `kitchen_id`, `product_id`, `date`, `need`, `unit`, `why`."""
    docs = [{"ts": _day(row["date"]),
             "meta": {"kitchen_id": row["kitchen_id"], "product_id": row["product_id"]},
             "need": Decimal(str(row["need"])), "unit": row["unit"], "why": row.get("why")}
            for row in rows]
    if docs:
        db.forecasts.insert_many(docs)
    return len(docs)


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


# Stock counts from the kitchen (POST /stock-counts)

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
