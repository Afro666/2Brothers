"""Kitchen data in MongoDB. The connection lives in `store.db`.

Collections (shapes from issue #72):
- suppliers: name, adapter (valio_api|manual|csv), free_delivery_threshold_eur,
  delivery_fee_eur, order_days, cutoff_time, lead_time_days. Terms are user-set;
  missing terms stay None, no default comes from Valio.
- own products: rows in `products` with `source: "own"` and a `kitchen_id`, in the
  common product row shape, so search covers them. `Repository.own_products` takes
  and returns the contract's "Own product" shape.
- recipes: name, items [{product_id, qty_per_portion}].
- menu_plans: date (YYYY-MM-DD), meal, recipe_id, covers.

Documents use a string `id` (stored as Mongo `_id`). Functions return plain dicts.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
import os
import uuid
from typing import Any, Callable

from bson.decimal128 import Decimal128

ADAPTERS = ("valio_api", "manual", "csv")
SUPPLIER_TERMS = (
    "free_delivery_threshold_eur",
    "delivery_fee_eur",
    "order_days",
    "cutoff_time",
    "lead_time_days",
)


def connect(db_name: str | None = None):
    """The shared database from `store.db`: one client, one Decimal128 codec."""
    from store.db import get_db

    return get_db(db_name or os.environ.get("MONGODB_DB"))


def _require(doc: dict, *fields: str) -> None:
    missing = [f for f in fields if doc.get(f) in (None, "")]
    if missing:
        raise ValueError(f"missing fields: {', '.join(missing)}")


def _check_supplier(doc: dict, partial: bool) -> None:
    if not partial:
        _require(doc, "name", "adapter")
    if "adapter" in doc and doc["adapter"] not in ADAPTERS:
        raise ValueError(f"adapter must be one of {ADAPTERS}")


def _decimal(value, field: str) -> Decimal | None:
    """Decimal strings on the wire, `Decimal` in the store, never a binary float."""
    if value is None:
        return None
    if isinstance(value, (float, bool)):
        raise TypeError(f"{field}: binary float refused, send a decimal string")
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        raise ValueError(f"{field} must be a decimal string") from None
    if not number.is_finite() or number < 0:
        raise ValueError(f"{field} must be a nonnegative number")
    return number


def own_product_row(data: dict, product_id: str) -> dict:
    """The contract's own-product body -> a `products` row (the common shape)."""
    _require(data, "kitchen_id", "name", "supplier_id", "unit")
    size = _decimal(data.get("pack_size_in_base_units"), "pack_size_in_base_units")
    measure = data.get("base_unit")
    if (size is None) != (measure is None):
        raise ValueError("give base_unit and pack_size_in_base_units together, or neither")
    if measure is not None and (measure not in ("L", "KG") or size <= 0):
        raise ValueError("base_unit must be L or KG and pack_size_in_base_units positive")
    state = data.get("allergen_data", "UNKNOWN")
    if state not in ("ENTERED", "UNKNOWN"):
        raise ValueError("allergen_data must be ENTERED or UNKNOWN")
    levels = {"CONTAINS": set(), "MAY_CONTAIN": set()}
    for item in data.get("allergens") or []:
        if not isinstance(item, dict) or not item.get("code") or item.get("level") not in levels:
            raise ValueError("allergens must be [{code, level: CONTAINS | MAY_CONTAIN}]")
        levels[item["level"]].add(str(item["code"]).upper())
    contains = levels["CONTAINS"]
    may_contain = levels["MAY_CONTAIN"] - contains
    name = str(data["name"]).strip()
    # Decimal128 explicitly: a caller may pass a database without the store codec.
    price = _decimal(data.get("unit_price_eur"), "unit_price_eur")
    return {
        "_id": product_id, "source": "own", "kitchen_id": data["kitchen_id"],
        "supplier_id": data["supplier_id"],
        # One entered name, indexed under each language's analyzer so search finds it.
        "names": {"en": name, "fi": name, "sv": name},
        "brand": None, "category": None, "vendor": None, "country": None,
        "base_unit": data["unit"], "sales_unit": data["unit"], "lot_size": None,
        "units": [{"unit": data["unit"], "size_in_base_units": 1.0, "gtin": None}],
        "net_content": None if size is None else {"value": float(size), "unit": measure},
        "net_content_source": None if size is None else "entered",
        "allergens": {"contains": sorted(contains), "may_contain": sorted(may_contain),
                      "undeclared": []},
        # UNKNOWN means unknown, never "free from", even with an empty list.
        "allergen_data_known": state == "ENTERED",
        "no_declarable_allergens": state == "ENTERED" and not contains and not may_contain,
        "free_from": [], "claims": [], "lactose_free": False, "labels": [],
        "temperature": None, "reliability": None, "carbon_kg_co2e_per_kg": None,
        "substitutions": [],
        "unit_price_eur": price if price is None else Decimal128(price),
    }


def own_product_out(row: dict | None) -> dict | None:
    """A `products` row with `source: "own"` -> the contract's own-product shape."""
    if row is None:
        return None
    content = row.get("net_content")
    allergens = row["allergens"]
    price = row.get("unit_price_eur")
    return {
        "product_id": row["_id"], "kitchen_id": row["kitchen_id"], "name": row["names"]["en"],
        "supplier_id": row["supplier_id"], "unit": row["base_unit"],
        "base_unit": content["unit"] if content else None,
        "pack_size_in_base_units": Decimal(str(content["value"])) if content else None,
        "unit_price_eur": price.to_decimal() if isinstance(price, Decimal128) else price,
        "allergens": ([{"code": code, "level": "CONTAINS"} for code in allergens["contains"]]
                      + [{"code": code, "level": "MAY_CONTAIN"} for code in allergens["may_contain"]]),
        "allergen_data": "ENTERED" if row["allergen_data_known"] else "UNKNOWN",
    }


class _OwnProducts:
    """Own products live in `products`; this keeps the CRUD the other collections have."""

    def __init__(self, products):
        self._coll = products

    def create(self, data: dict) -> dict:
        row = own_product_row(data, data.get("product_id") or f"own-{uuid.uuid4().hex[:12]}")
        self._coll.insert_one(row)
        return own_product_out(row)

    def get(self, product_id: str) -> dict | None:
        return own_product_out(self._coll.find_one({"_id": product_id, "source": "own"}))

    def list(self, **filters: Any) -> list[dict]:
        """Filter by `kitchen_id` and/or `supplier_id`."""
        unknown = set(filters) - {"kitchen_id", "supplier_id"}
        if unknown:
            raise ValueError(f"unknown filters: {sorted(unknown)}")
        rows = self._coll.find({**filters, "source": "own"}).sort("_id")
        return [own_product_out(row) for row in rows]

    def update(self, product_id: str, changes: dict) -> dict | None:
        current = self.get(product_id)
        if current is None:
            return None
        merged = {**current, **{k: v for k, v in changes.items()
                                if k not in ("product_id", "kitchen_id")}}
        row = own_product_row(merged, product_id)
        self._coll.replace_one({"_id": product_id, "source": "own"}, row)
        return own_product_out(row)

    def delete(self, product_id: str) -> bool:
        return self._coll.delete_one({"_id": product_id, "source": "own"}).deleted_count == 1


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
        self.own_products = _OwnProducts(db["products"])
        self.recipes = _Collection(db["recipes"], _check_recipe, {"items": []})
        self.menu_plans = _Collection(db["menu_plans"], _check_menu_plan, {})
