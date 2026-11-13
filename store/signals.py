"""Daily physical weather measurements and holiday flags; all Mongo access stays here."""
from datetime import date


def save_daily(db, rows):
    rows = list(rows)
    for row in rows:
        if not row.get("kitchen_id"):
            raise ValueError("kitchen_id is required")
        for field in ("date", "as_of"):
            date.fromisoformat(row[field])
        if row.get("kind") not in ("model_history", "forecast"):
            raise ValueError("invalid signal kind")
    collection = db.daily_signals
    collection.create_index([("kitchen_id", 1), ("date", 1), ("as_of", 1)], unique=True)
    for row in rows:
        key = {k: row[k] for k in ("kitchen_id", "date", "as_of")}
        collection.update_one(key, {"$set": {k: v for k, v in row.items() if k != "_id"}}, upsert=True)
    return len(rows)


def list_daily(db, kitchen_id, start: date, end: date, *, as_of: date):
    """Read one exact issue-date snapshot, avoiding accidental mixing of vintages."""
    query = {"kitchen_id": kitchen_id, "as_of": as_of.isoformat(),
             "date": {"$gte": start.isoformat(), "$lte": end.isoformat()}}
    return list(db.daily_signals.find(query, {"_id": 0}).sort("date", 1))
