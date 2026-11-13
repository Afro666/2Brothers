"""The one repository module: the only code that talks to MongoDB.

Collections (shapes from issue #72):
- suppliers: name, adapter (valio_api|manual|csv), free_delivery_threshold_eur,
  delivery_fee_eur, order_days, cutoff_time, lead_time_days. Terms are user-set;
  missing terms stay None, no default comes from Valio.
- own_products: name, unit, pack_size, price_eur, supplier_id, allergens
  (None = unknown, never "free-from").
- recipes: name, items [{product_id, qty_per_portion}].
- menu_plans: date (YYYY-MM-DD), meal, recipe_id, covers.

Documents use a string `id` (stored as Mongo `_id`). Functions return plain dicts.
"""

from __future__ import annotations

import os
import uuid
from typing import Any, Callable

ADAPTERS = ("valio_api", "manual", "csv")
SUPPLIER_TERMS = (
    "free_delivery_threshold_eur",
    "delivery_fee_eur",
    "order_days",
    "cutoff_time",
    "lead_time_days",
)


def connect(uri: str | None = None, db_name: str | None = None):
    """Return a pymongo Database from MONGODB_URI (and optional MONGODB_DB)."""
    from pymongo import MongoClient

    uri = uri or os.environ.get("MONGODB_URI")
    if not uri:
        raise RuntimeError("MONGODB_URI is not set")
    return MongoClient(uri)[db_name or os.environ.get("MONGODB_DB", "two_brothers")]


def _require(doc: dict, *fields: str) -> None:
    missing = [f for f in fields if doc.get(f) in (None, "")]
    if missing:
        raise ValueError(f"missing fields: {', '.join(missing)}")


def _check_supplier(doc: dict, partial: bool) -> None:
    if not partial:
        _require(doc, "name", "adapter")
    if "adapter" in doc and doc["adapter"] not in ADAPTERS:
        raise ValueError(f"adapter must be one of {ADAPTERS}")


def _check_own_product(doc: dict, partial: bool) -> None:
    if not partial:
        _require(doc, "name", "unit", "supplier_id")
    allergens = doc.get("allergens")
    if allergens is not None and not isinstance(allergens, list):
        raise ValueError("allergens must be a list or None (unknown)")


def _check_recipe(doc: dict, partial: bool) -> None:
    if not partial:
        _require(doc, "name")
    for item in doc.get("items", []):
        _require(item, "product_id", "qty_per_portion")
        if item["qty_per_portion"] <= 0:
            raise ValueError("qty_per_portion must be > 0")


def _check_menu_plan(doc: dict, partial: bool) -> None:
    if not partial:
        _require(doc, "date", "meal", "recipe_id", "covers")
    if "covers" in doc and (not isinstance(doc["covers"], int) or doc["covers"] < 0):
        raise ValueError("covers must be an int >= 0")


class _Collection:
    def __init__(self, coll, check: Callable[[dict, bool], None], defaults: dict):
        self._coll = coll
        self._check = check
        self._defaults = defaults

    @staticmethod
    def _out(doc: dict | None) -> dict | None:
        if doc is None:
            return None
        doc = dict(doc)
        doc["id"] = doc.pop("_id")
        return doc

    def create(self, data: dict) -> dict:
        doc = {**self._defaults, **{k: v for k, v in data.items() if k not in ("id", "_id")}}
        self._check(doc, False)
        doc["_id"] = data.get("id") or uuid.uuid4().hex
        self._coll.insert_one(doc)
        return self._out(doc)

    def get(self, doc_id: str) -> dict | None:
        return self._out(self._coll.find_one({"_id": doc_id}))

    def list(self, **filters: Any) -> list[dict]:
        return [self._out(d) for d in self._coll.find(filters).sort("_id")]

    def update(self, doc_id: str, changes: dict) -> dict | None:
        changes = {k: v for k, v in changes.items() if k not in ("id", "_id")}
        self._check(changes, True)
        if not changes:
            return self.get(doc_id)
        result = self._coll.update_one({"_id": doc_id}, {"$set": changes})
        return self.get(doc_id) if result.matched_count else None

    def delete(self, doc_id: str) -> bool:
        return self._coll.delete_one({"_id": doc_id}).deleted_count == 1


class Repository:
    """CRUD for suppliers, own products, recipes and menu plans."""

    def __init__(self, db=None):
        db = db if db is not None else connect()
        self.suppliers = _Collection(
            db["suppliers"], _check_supplier, {t: None for t in SUPPLIER_TERMS}
        )
        self.own_products = _Collection(
            db["own_products"],
            _check_own_product,
            {"pack_size": None, "price_eur": None, "allergens": None},
        )
        self.recipes = _Collection(db["recipes"], _check_recipe, {"items": []})
        self.menu_plans = _Collection(db["menu_plans"], _check_menu_plan, {})
