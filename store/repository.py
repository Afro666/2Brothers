"""Kitchen data in MongoDB, in the shapes of docs/contract.md ("Data shapes").

- suppliers: `supplier_id`, `name`, `adapter`, `terms`. Terms are user-set; a missing
  term stays None (unknown, never zero) and no default comes from Valio.
- recipes: `recipe_id`, `name`, `portions`, `ingredients`.
- menu plans: one document per kitchen and ISO week, replaced as a whole.
- kitchen settings: one document per kitchen; engine parameters under `engine`, the
  allergen policy in `excluded_allergens`, as the gateway and the Buyer already read them.
- own products: rows in `products` with `source: "own"`, in the common product row
  shape, so search covers them. They go in and out in the "Own product" shape.

Every method takes the kitchen first, and every query carries it: one kitchen never
reads or changes another kitchen's rows. Money and quantities are decimal strings on
the wire and `Decimal` here; a binary float is refused. The connection lives in
`store.db`.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
import os
import re
import uuid
from typing import Callable

from bson.decimal128 import Decimal128

from store.search import allergen_codes

ADAPTERS = ("valio_api", "manual", "csv")
WEEKDAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
MEALS = ("breakfast", "lunch", "dinner", "other")
KITCHEN_UNITS = ("L", "KG", "PCS")
SUPPLIER_TERMS = ("free_delivery_threshold_eur", "delivery_fee_eur", "order_days",
                  "cutoff_time", "lead_time_days", "discount_tiers")
DEMAND_CLASSES = ("A", "B", "C")
# The engine's categories (engine/params.py); another key would silently do nothing there.
COVER_CATEGORIES = ("fresh_dairy", "vegetables", "meat", "fish", "frozen", "dry", "other")
BUDGET_WARNINGS = ("budget_warning_order_eur", "budget_warning_week_eur")
SETTINGS = ("service_level", "max_cover_days", "stockout_cap", "certainty_premium_max",
            *BUDGET_WARNINGS, "excluded_allergens")
_CLOCK = re.compile(r"([01]\d|2[0-3]):[0-5]\d")
_WEEK = re.compile(r"\d{4}-W(0[1-9]|[1-4]\d|5[0-3])")


def connect(db_name: str | None = None):
    """The shared database from `store.db`: one client, one Decimal128 codec."""
    from store.db import get_db

    return get_db(db_name or os.environ.get("MONGODB_DB"))


def _require(doc: dict, *fields: str) -> None:
    missing = [f for f in fields if doc.get(f) in (None, "")]
    if missing:
        raise ValueError(f"missing fields: {', '.join(missing)}")


def _objects(value, field: str) -> list[dict]:
    """A list of objects, or empty when missing; anything else is a clear ValueError."""
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError(f"{field} must be a list of objects")
    return value


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


def _count(value, field: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{field} must be an integer of at least {minimum}")
    return value


def _to_store(value):
    """Decimal128 explicitly: a caller may pass a database without the store codec."""
    if isinstance(value, dict):
        return {key: _to_store(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_to_store(item) for item in value]
    return Decimal128(value) if isinstance(value, Decimal) else value


def _from_store(value):
    if isinstance(value, dict):
        return {key: _from_store(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_from_store(item) for item in value]
    return value.to_decimal() if isinstance(value, Decimal128) else value


def supplier_fields(data: dict) -> dict:
    """Validate a supplier body. Any term may be missing or null: unknown, never zero."""
    _require(data, "name", "adapter")
    if data["adapter"] not in ADAPTERS:
        raise ValueError(f"adapter must be one of {ADAPTERS}")
    terms = data.get("terms")
    if terms is None:
        terms = {}
    if not isinstance(terms, dict):
        raise ValueError("terms must be an object")
    unknown = set(terms) - set(SUPPLIER_TERMS)
    if unknown:
        raise ValueError(f"unknown terms: {sorted(unknown)}")
    days = terms.get("order_days")
    if days is not None and (not isinstance(days, list) or set(days) - set(WEEKDAYS)):
        raise ValueError(f"order_days must be a list of {WEEKDAYS}")
    cutoff = terms.get("cutoff_time")
    if cutoff is not None and not _CLOCK.fullmatch(str(cutoff)):
        raise ValueError("cutoff_time must be HH:MM")
    lead = terms.get("lead_time_days")
    tiers = []
    for tier in _objects(terms.get("discount_tiers"), "discount_tiers"):
        _require(tier, "min_qty", "unit", "unit_price_eur")
        tiers.append({"product_id": tier.get("product_id"),  # None: every product
                      "min_qty": _decimal(tier["min_qty"], "min_qty"), "unit": tier["unit"],
                      "unit_price_eur": _decimal(tier["unit_price_eur"], "unit_price_eur")})
    return {"name": str(data["name"]).strip(), "adapter": data["adapter"], "terms": {
        "free_delivery_threshold_eur": _decimal(terms.get("free_delivery_threshold_eur"),
                                                "free_delivery_threshold_eur"),
        "delivery_fee_eur": _decimal(terms.get("delivery_fee_eur"), "delivery_fee_eur"),
        "order_days": days, "cutoff_time": cutoff,
        "lead_time_days": None if lead is None else _count(lead, "lead_time_days"),
        "discount_tiers": tiers}}


def recipe_fields(data: dict) -> dict:
    """Validate a recipe body: products x quantity per portion, with an optional yield."""
    _require(data, "name")
    ingredients = []
    for item in _objects(data.get("ingredients"), "ingredients"):
        _require(item, "product_id", "qty_per_portion", "unit")
        quantity = _decimal(item["qty_per_portion"], "qty_per_portion")
        if quantity <= 0:
            raise ValueError("qty_per_portion must be positive")
        if item["unit"] not in KITCHEN_UNITS:
            raise ValueError(f"unit must be one of {KITCHEN_UNITS}")
        usable = _decimal(item.get("yield_pct"), "yield_pct")  # None means 100
        if usable is not None and not 0 < usable <= 100:
            raise ValueError("yield_pct must be above 0 and at most 100")
        ingredients.append({"product_id": str(item["product_id"]), "qty_per_portion": quantity,
                            "unit": item["unit"], "yield_pct": usable})
    return {"name": str(data["name"]).strip(),
            "portions": _count(data.get("portions", 1), "portions", 1),
            "ingredients": ingredients}


def menu_days(week: str, days: list) -> list[dict]:
    """Validate the days of one ISO week (`YYYY-Www`). Every date must fall in that week."""
    if not _WEEK.fullmatch(str(week)):
        raise ValueError("week must look like 2026-W47")
    checked = []
    for day in _objects(days, "days"):
        _require(day, "date", "meal", "recipe_id")
        iso = date.fromisoformat(str(day["date"])).isocalendar()
        if f"{iso.year}-W{iso.week:02d}" != week:
            raise ValueError(f"{day['date']} is not in week {week}")
        if day["meal"] not in MEALS:
            raise ValueError(f"meal must be one of {MEALS}")
        checked.append({"date": str(day["date"]), "meal": day["meal"],
                        "recipe_id": str(day["recipe_id"]),
                        "covers": _count(day.get("covers"), "covers")})
    return checked


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


def settings_fields(data: dict) -> dict:
    """Validate a kitchen settings body (docs/contract.md, "Kitchen settings").

    Only the fields given come back: a field that is left out keeps its stored value.
    """
    unknown = set(data) - set(SETTINGS)
    if unknown:
        raise ValueError(f"unknown settings: {sorted(unknown)}")
    out: dict = {}

    def table(field: str, keys: tuple) -> dict:
        value = data[field]
        if not isinstance(value, dict) or set(value) - set(keys):
            raise ValueError(f"{field} must be an object with keys from {keys}")
        return value

    if "service_level" in data:
        levels = {key: _decimal(value, "service_level")
                  for key, value in table("service_level", DEMAND_CLASSES).items()}
        if any(level is None or not 0 < level < 1 for level in levels.values()):
            raise ValueError("service_level is a fraction above 0 and below 1 (97.5 % is 0.975)")
        out["service_level"] = levels
    if "max_cover_days" in data:
        out["max_cover_days"] = {key: _count(value, "max_cover_days", 1)
                                 for key, value in table("max_cover_days", COVER_CATEGORIES).items()}
    if "stockout_cap" in data:
        cap = _decimal(data["stockout_cap"], "stockout_cap")
        if cap is None or not 1 <= cap <= 3:
            raise ValueError("stockout_cap must be from 1 to 3")
        out["stockout_cap"] = float(cap)  # a factor, not money; the engine reads a float
    if "certainty_premium_max" in data:
        limit = _decimal(data["certainty_premium_max"], "certainty_premium_max")
        if limit is not None and limit < 1:
            raise ValueError("certainty_premium_max must be at least 1, or null for no limit")
        out["certainty_premium_max"] = limit  # None: no limit
    for field in BUDGET_WARNINGS:
        if field in data:
            out[field] = _decimal(data[field], field)  # None: no warning
    if "excluded_allergens" in data:
        codes = data["excluded_allergens"]
        message = ("excluded_allergens must be a list of GS1 codes or allergen names; "
                   "[] means no exclusions")
        if not isinstance(codes, list) or not all(isinstance(code, str) for code in codes):
            raise ValueError(message)
        try:  # read as the Buyer's AllergenPolicy reads them: AW is the gluten group
            allergen_codes(["gluten" if code.upper() == "AW" else code for code in codes])
        except ValueError:
            raise ValueError(message) from None
        out["excluded_allergens"] = codes
    return out


def _merge(current: dict, changes: dict, fixed: tuple) -> dict:
    """Changes over the current row. A nested object (supplier `terms`) merges one
    level deep, so changing one term does not wipe the others. `fixed` keys stay."""
    merged = dict(current)
    for key, value in changes.items():
        if key in fixed:
            continue
        both = isinstance(value, dict) and isinstance(current.get(key), dict)
        merged[key] = {**current[key], **value} if both else value
    return merged


class _Collection:
    """Kitchen-scoped CRUD. `_id` is `<kitchen_id>:<id>`, so ids only need to be unique
    inside one kitchen (two kitchens may both call a supplier `valio_aimo`)."""

    def __init__(self, coll, id_key: str, fields: Callable[[dict], dict]):
        self._coll, self._id_key, self._fields = coll, id_key, fields

    def _out(self, doc: dict | None) -> dict | None:
        if doc is None:
            return None
        doc = _from_store(doc)
        doc.pop("_id")
        return doc

    def create(self, kitchen_id: str, data: dict) -> dict:
        doc_id = str(data.get(self._id_key) or uuid.uuid4().hex[:12])
        doc = {"_id": f"{kitchen_id}:{doc_id}", "kitchen_id": kitchen_id, self._id_key: doc_id,
               **self._fields(data)}
        self._coll.insert_one(_to_store(doc))
        return self._out(doc)

    def get(self, kitchen_id: str, doc_id: str) -> dict | None:
        return self._out(self._coll.find_one({"_id": f"{kitchen_id}:{doc_id}"}))

    def list(self, kitchen_id: str) -> list[dict]:
        return [self._out(doc) for doc in self._coll.find({"kitchen_id": kitchen_id}).sort("_id")]

    def update(self, kitchen_id: str, doc_id: str, changes: dict) -> dict | None:
        current = self.get(kitchen_id, doc_id)
        if current is None:
            return None
        merged = _merge(current, changes, ("kitchen_id", self._id_key))
        doc = {"_id": f"{kitchen_id}:{doc_id}", "kitchen_id": kitchen_id, self._id_key: doc_id,
               **self._fields(merged)}
        self._coll.replace_one({"_id": doc["_id"]}, _to_store(doc))
        return self._out(doc)

    def delete(self, kitchen_id: str, doc_id: str) -> bool:
        return self._coll.delete_one({"_id": f"{kitchen_id}:{doc_id}"}).deleted_count == 1


class _MenuPlans:
    """One document per kitchen and ISO week; `put` replaces the whole week."""

    def __init__(self, coll):
        self._coll = coll

    def put(self, kitchen_id: str, week: str, days: list) -> dict:
        doc = {"_id": f"{kitchen_id}:{week}", "kitchen_id": kitchen_id, "week": week,
               "days": menu_days(week, days)}
        self._coll.replace_one({"_id": doc["_id"]}, doc, upsert=True)
        return {key: value for key, value in doc.items() if key != "_id"}

    def get(self, kitchen_id: str, week: str) -> dict | None:
        return self._coll.find_one({"_id": f"{kitchen_id}:{week}"}, {"_id": 0})

    def list(self, kitchen_id: str) -> list[dict]:
        return list(self._coll.find({"kitchen_id": kitchen_id}, {"_id": 0}).sort("week", 1))

    def delete(self, kitchen_id: str, week: str) -> bool:
        return self._coll.delete_one({"_id": f"{kitchen_id}:{week}"}).deleted_count == 1


class _Settings:
    """Kitchen settings. Stored as the gateway and the Buyer read them: engine
    parameters under `engine`, the allergen policy in `excluded_allergens`."""

    def __init__(self, coll):
        self._coll = coll

    def get(self, kitchen_id: str) -> dict:
        """What the kitchen has set. A field that was never set is absent (the engine's
        default applies), except `excluded_allergens`, which is None: unknown, not none."""
        doc = _from_store(self._coll.find_one({"_id": kitchen_id}) or {})
        policy = doc.get("excluded_allergens")
        known = isinstance(policy, list) and all(isinstance(code, str) for code in policy)
        return {**(doc.get("engine") or {}), "excluded_allergens": policy if known else None}

    def put(self, kitchen_id: str, changes: dict) -> tuple[dict, dict]:
        """Change the fields given and keep the rest. Returns `(settings, changed)`;
        `changed` maps each field that moved to `{"from", "to"}`, for the audit entry
        the caller writes."""
        fields = settings_fields(changes)
        before = self.get(kitchen_id)
        after = _merge(before, fields, ())
        changed = {field: {"from": before.get(field), "to": after[field]}
                   for field in fields if before.get(field) != after[field]}
        if changed:
            update = {(field if field == "excluded_allergens" else f"engine.{field}"):
                      _to_store(after[field]) for field in changed}
            self._coll.update_one({"_id": kitchen_id}, {"$set": update}, upsert=True)
        return after, changed


class _OwnProducts:
    """Own products live in `products`; this keeps the CRUD the other collections have."""

    def __init__(self, products):
        self._coll = products

    def _query(self, kitchen_id: str, product_id: str) -> dict:
        return {"_id": product_id, "source": "own", "kitchen_id": kitchen_id}

    def create(self, kitchen_id: str, data: dict) -> dict:
        row = own_product_row({**data, "kitchen_id": kitchen_id},
                              data.get("product_id") or f"own-{uuid.uuid4().hex[:12]}")
        self._coll.insert_one(row)
        return own_product_out(row)

    def get(self, kitchen_id: str, product_id: str) -> dict | None:
        return own_product_out(self._coll.find_one(self._query(kitchen_id, product_id)))

    def list(self, kitchen_id: str, supplier_id: str | None = None) -> list[dict]:
        query = {"source": "own", "kitchen_id": kitchen_id}
        if supplier_id is not None:
            query["supplier_id"] = supplier_id
        return [own_product_out(row) for row in self._coll.find(query).sort("_id")]

    def update(self, kitchen_id: str, product_id: str, changes: dict) -> dict | None:
        current = self.get(kitchen_id, product_id)
        if current is None:
            return None
        row = own_product_row(_merge(current, changes, ("product_id", "kitchen_id")), product_id)
        self._coll.replace_one(self._query(kitchen_id, product_id), row)
        return own_product_out(row)

    def delete(self, kitchen_id: str, product_id: str) -> bool:
        return self._coll.delete_one(self._query(kitchen_id, product_id)).deleted_count == 1


class Repository:
    """Suppliers, own products, recipes, menu plans and settings of a kitchen."""

    def __init__(self, db=None):
        db = db if db is not None else connect()
        self.suppliers = _Collection(db["suppliers"], "supplier_id", supplier_fields)
        self.recipes = _Collection(db["recipes"], "recipe_id", recipe_fields)
        self.menu_plans = _MenuPlans(db["menu_plans"])
        self.own_products = _OwnProducts(db["products"])
        self.settings = _Settings(db["kitchen_settings"])
