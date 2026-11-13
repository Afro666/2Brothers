"""Time-series history, forecasts and forecast-sharing consent.

Load the synthetic history from `env/history.py`:
`python -m env.history --seed 1 && python -m store.history [--dir env/out/history]`.

Time-series collections (`timeField: "ts"`, `metaField: "meta"`): `kitchen_stock`,
`covers`, `orders_history`, `deliveries`, `forecasts`. Quantities are in kitchen
units (`L`, `KG`, `PCS`), as docs/contract.md says.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, time, timezone
from decimal import Decimal
from pathlib import Path

from bson import json_util

from store.db import get_db

SERIES = {"stock": "kitchen_stock", "covers": "covers", "orders": "orders_history",
          "deliveries": "deliveries"}
_JSON = json_util.DEFAULT_JSON_OPTIONS.with_options(tz_aware=True)


def ensure_history_collections(db) -> None:
    """Create the time-series collections and the consent index. Safe to run again."""
    existing = set(db.list_collection_names())
    for name in (*SERIES.values(), "forecasts"):
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
                granted_by: str) -> dict:
    """Grant or revoke forecast sharing. `granted_by` is a human user, never the Buyer."""
    if not granted_by:
        raise ValueError("granted_by is required")
    now = datetime.now(timezone.utc)
    change = ({"share_forecast": True, "granted_at": now, "granted_by": granted_by,
               "revoked_at": None} if share_forecast
              else {"share_forecast": False, "revoked_at": now})
    db.sharing.update_one({"kitchen_id": kitchen_id, "supplier_id": supplier_id},
                          {"$set": {**change, "scope": "forecast_only"}}, upsert=True)
    return db.sharing.find_one({"kitchen_id": kitchen_id, "supplier_id": supplier_id}, {"_id": 0})


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
    """Per day: summed demand and how many kitchens it covers."""
    collection, quantity = {
        # What the kitchen needed that day: what it used plus what it could not serve.
        "history": (db.kitchen_stock, {"$add": ["$used", "$short"]}),
        "forecast": (db.forecasts, "$need"),
    }[source]
    rows = collection.aggregate([
        {"$match": {**match, "meta.product_id": str(product_id),
                    "ts": {"$gte": _day(start), "$lte": _day(end, end=True)}}},
        {"$group": {"_id": {"date": {"$dateToString": {"format": "%Y-%m-%d", "date": "$ts"}},
                            "unit": "$unit"},
                    "demand": {"$sum": quantity}, "kitchens": {"$addToSet": "$meta.kitchen_id"}}},
        {"$sort": {"_id.date": 1}},
    ])
    return [{"product_id": str(product_id), "date": row["_id"]["date"], "unit": row["_id"]["unit"],
             "demand": row["demand"], "kitchens": len(row["kitchens"])} for row in rows]


def kitchen_demand(db, kitchen_id: str, product_id: str, start, end,
                   source: str = "history") -> list[dict]:
    """One kitchen's daily demand for one product, `start` to `end` inclusive."""
    return _demand(db, source, {"meta.kitchen_id": kitchen_id}, product_id, start, end)


def supplier_demand(db, supplier_id: str, product_id: str, start, end,
                    source: str = "history") -> list[dict]:
    """Daily demand summed over the kitchens that share their forecast with this supplier.

    The rows say how many kitchens the sum covers, never which ones.
    """
    kitchens = consenting_kitchens(db, supplier_id)
    return _demand(db, source, {"meta.kitchen_id": {"$in": kitchens}}, product_id, start, end)


def main() -> None:
    parser = argparse.ArgumentParser(description="Load the synthetic kitchen history.")
    parser.add_argument("--dir", type=Path, default=Path("env/out/history"))
    args = parser.parse_args()
    for name, count in load_history(get_db(), args.dir).items():
        print(f"{name}: {count} rows")


if __name__ == "__main__":
    main()
