"""Standing-order drift routes (#377). Contract: docs/contract.md, "Standing-order drift".

- GET /v1/kitchens/{kitchen_id}/drift (`kitchen:read`): this kitchen's warnings.
- GET /v1/suppliers/{supplier_id}/demand/drift (`supplier:demand`): the warnings of every
  kitchen whose consent names this supplier. A kitchen without consent appears nowhere.

The numbers come from `store.drift.standing_order_drift` (one Atlas aggregation). This
module only shapes the answer: the week, the product name, the kitchen name.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from fastapi import Depends, FastAPI
from pymongo.errors import PyMongoError

from gateway.service import GatewayError
from store.drift import standing_order_drift
from store.history import consenting_kitchens


def last_full_week(now: datetime) -> datetime:
    """The Monday (00:00 UTC) of the last full week before `now`, as store.drift counts it."""
    now = now.astimezone(timezone.utc)
    day = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    return day - timedelta(days=day.weekday(), weeks=1)


@contextmanager
def _unavailable_on_db_error():
    """Any Mongo failure (drift, consent, names) answers 503 DRIFT_UNAVAILABLE (contract)."""
    try:
        yield
    except PyMongoError:
        # Never the driver's message: it can name hosts and collections.
        raise GatewayError(503, "DRIFT_UNAVAILABLE", "drift cannot be computed right now") from None


def _warnings(db, kitchen_id: str, now: datetime) -> list[dict]:
    rows = standing_order_drift(db, kitchen_id, now=now)
    # `week` is one value for the whole answer, not a field of a warning (contract).
    return [{key: value for key, value in row.items() if key != "week"} for row in rows]


def _named(db, warnings: list[dict]) -> list[dict]:
    """Add `product_name` where the catalog knows the product; never an invented name."""
    ids = sorted({warning["product_id"] for warning in warnings})
    names = {doc["_id"]: (doc.get("names") or {}).get("en")
             for doc in db.products.find({"_id": {"$in": ids}}, {"names": 1})} if ids else {}
    return [{**warning, "product_name": names[warning["product_id"]]}
            if names.get(warning["product_id"]) else warning for warning in warnings]


def kitchen_drift(db, kitchen_id: str, now: datetime) -> dict:
    now = now.astimezone(timezone.utc)
    with _unavailable_on_db_error():
        warnings = _named(db, _warnings(db, kitchen_id, now))
    return {"week": last_full_week(now).date().isoformat(), "warnings": warnings}


def supplier_drift(db, supplier_id: str, now: datetime) -> dict:
    now = now.astimezone(timezone.utc)
    with _unavailable_on_db_error():
        kitchens = consenting_kitchens(db, supplier_id)
        names = {doc["_id"]: doc.get("name")
                 for doc in db.kitchens.find({"_id": {"$in": kitchens}}, {"name": 1})} if kitchens else {}
        warnings = [{**warning, "kitchen_id": kitchen_id, "kitchen_name": names.get(kitchen_id)}
                    for kitchen_id in kitchens for warning in _warnings(db, kitchen_id, now)]
        warnings.sort(key=lambda warning: -warning["change"])     # biggest change first
        warnings = _named(db, warnings)
    return {"week": last_full_week(now).date().isoformat(), "warnings": warnings}


def mount_drift(app: FastAPI, gw, principal) -> None:
    @app.get("/v1/kitchens/{kitchen_id}/drift")
    def drift(kitchen_id: str, who=Depends(principal)):
        who.need("kitchen:read", kitchen_id)
        return kitchen_drift(gw().db, kitchen_id, gw().now())

    @app.get("/v1/suppliers/{supplier_id}/demand/drift")
    def demand_drift(supplier_id: str, who=Depends(principal)):
        # No kitchen id on purpose: the answer spans kitchens, and consent decides which.
        who.need_supplier("supplier:demand")
        return supplier_drift(gw().db, supplier_id, gw().now())
