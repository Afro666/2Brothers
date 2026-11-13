"""The `products` collection: one row per product from any source.

`flatten()` turns one raw Valio catalog record into our snake_case row and keeps
the full record under `raw`. Field paths were checked against the real catalog
(see store/README.md); nothing here reads a path that was not seen in the data.
"""

from __future__ import annotations

import re

from pymongo import ReplaceOne

VALIO_SUPPLIER_ID = "valio_aimo"
NO_DECLARABLE_ALLERGENS = "X99"  # GS1: "does not contain declaration obligatory allergens"

# temperatureCondition has no legend. 1-4, 7 and 8 match the storage tags on 99% of
# products; 5, 6 and 9 match nothing and stay unknown until Valio explains them.
_TEMPERATURE_BY_CODE = {1: "chilled", 2: "chilled", 3: "chilled", 4: "chilled",
                        7: "frozen", 8: "ambient"}
_TEMPERATURE_BY_TAG = {"coolTemperature": "chilled", "freezeTemperature": "frozen",
                       "warmTemperature": "ambient"}

# GS1 unit code -> (our unit, factor). Pieces (H87) and portions (PTN) are not sizes.
_MEASURES = {"LTR": ("L", 1), "MLT": ("L", 0.001), "CLT": ("L", 0.01),
             "KGM": ("KG", 1), "GRM": ("KG", 0.001)}
_NAME_UNITS = {"l": ("L", 1), "ltr": ("L", 1), "dl": ("L", 0.1), "cl": ("L", 0.01),
               "ml": ("L", 0.001), "kg": ("KG", 1), "g": ("KG", 0.001), "gr": ("KG", 0.001)}
_NAME_SIZE = re.compile(
    r"(?<![\w,.])(?:(\d+)\s*[x×*]\s*)?e?(\d+(?:[.,]\d+)?)\s*(kg|gr|g|ltr|l|dl|cl|ml)(?![a-zäöå])",
    re.IGNORECASE)


def _size_from_name(name: str, pack_sizes: set) -> tuple[float, str] | None:
    """'1 l', '500g', '7X1,2KG' (= 8.4 kg). A leading count that equals a pack size
    ('12x1 l' sold in cases of 12) is the case count, not part of the piece."""
    match = _NAME_SIZE.search(name)
    if not match:
        return None
    count, number, unit = match.groups()
    unit, factor = _NAME_UNITS[unit.lower()]
    value = float(number.replace(",", ".")) * factor
    if count and int(count) not in pack_sizes:
        value *= int(count)
    return value, unit


def _net_content(raw: dict, names: dict) -> tuple[dict | None, str | None]:
    """Net content of one base unit, as `{value, unit}` in l or kg, and where it came from."""
    units = raw.get("units") or []
    found = None
    if raw.get("baseUnit") == "KG":
        found = (1.0, "KG", "base_unit")  # sold by weight: one base unit is one kilogram
    conversions = (raw.get("synkkaData") or {}).get("unitConversions") or []
    if not found and conversions:
        conversion = conversions[0]
        # `volume` is really "net content" and may be in grams; fall back to netWeight.
        measure = next((conversion[key] for key in ("volume", "netWeight")
                        if (conversion.get(key) or {}).get("unit") in _MEASURES), None)
        kind = conversion.get("synkkaPackagingType")
        case = next((u["sizeInBaseUnits"] for u in units if u["unitId"] == "KI"), None)
        if measure and (kind == "BASE_UNIT_OR_EACH" or (kind == "CASE" and case)):
            unit, factor = _MEASURES[measure["unit"]]
            value = measure["value"] * factor
            found = ((value, unit, "synkka") if kind == "BASE_UNIT_OR_EACH"
                     else (value / case, unit, "synkka_case"))
    if not found:
        pack_sizes = {u["sizeInBaseUnits"] for u in units if u["sizeInBaseUnits"] > 1}
        for language in ("en", "fi", "sv"):
            size = _size_from_name(names.get(language, ""), pack_sizes)
            if size:
                found = (*size, "name")  # a guess: wrong for some non-food and multi-packs
                break
    if not found or found[0] <= 0:
        return None, None
    return {"value": round(found[0], 6), "unit": found[1]}, found[2]


def flatten(raw: dict, reliability: float | None = None, carbon: float | None = None) -> dict:
    """One raw Valio record -> one `products` document. Pure: no I/O."""
    synkka = raw.get("synkkaData") or {}
    values = {c["name"]: c.get("values") or [] for c in synkka.get("classifications") or []}
    names = {n["language"]: n["value"].strip() for n in synkka.get("names") or []
             if n["language"] in ("en", "fi", "sv") and n.get("value")}

    levels = {"CONTAINS": set(), "MAY_CONTAIN": set(), "UNDECLARED": set()}
    none_declared = False
    for value in values.get("allergen", []):
        if value["id"] == NO_DECLARABLE_ALLERGENS:
            none_declared = True
        else:  # a level we have never seen is treated as the worst one
            levels.get(value.get("unit"), levels["CONTAINS"]).add(value["id"])
    contains = levels["CONTAINS"]
    may_contain = levels["MAY_CONTAIN"] - contains
    claimed_free = {value["id"] for value in values.get("nonAllergen", [])}
    # When the record contradicts itself, the riskier statement wins.
    free_from = claimed_free - contains - may_contain
    undeclared = levels["UNDECLARED"] - contains - may_contain - free_from

    label_values = values.get("packagingMarkedLabel", [])
    tags = [v["id"] for v in label_values if v["id"] in _TEMPERATURE_BY_TAG]
    claims = sorted({value["id"] for value in values.get("nutritionalClaim", [])})
    code = raw.get("temperatureCondition")
    temperature = _TEMPERATURE_BY_CODE.get(code)
    if temperature is None and len(tags) == 1:
        temperature = _TEMPERATURE_BY_TAG[tags[0]]

    lot_size = raw.get("allowedLotSize")
    net_content, net_content_source = _net_content(raw, names)
    return {
        "_id": str(raw["id"]),
        "source": "valio",
        "supplier_id": VALIO_SUPPLIER_ID,
        "names": names,
        "brand": (synkka.get("brand") or "").strip() or None,
        "category": raw.get("category"),
        "vendor": raw.get("vendorName"),
        "country": raw.get("countryOfOrigin"),
        "base_unit": raw.get("baseUnit"),
        "sales_unit": raw.get("salesUnit"),
        "lot_size": None if lot_size in (None, 0.01) else lot_size,  # 0.01 = no lot rule
        "units": [{"unit": u["unitId"], "size_in_base_units": u["sizeInBaseUnits"],
                   "gtin": u.get("gtin")} for u in raw.get("units") or []],
        "net_content": net_content,
        "net_content_source": net_content_source,
        "allergens": {"contains": sorted(contains), "may_contain": sorted(may_contain),
                      "undeclared": sorted(undeclared)},
        # No allergen and no free-from statement at all means unknown, never allergen-free.
        "allergen_data_known": bool(values.get("allergen") or claimed_free),
        "no_declarable_allergens": none_declared and not contains and not may_contain,
        "free_from": sorted(free_from),
        "claims": claims,
        "lactose_free": (("FREE_FROM_LACTOSE" in claims or "ML" in claimed_free)
                         and "ML" not in contains | may_contain),
        "labels": sorted(v["id"] for v in label_values if v["id"] not in _TEMPERATURE_BY_TAG),
        "temperature": temperature,
        "temperature_condition": code,
        "min_temperature_c": synkka.get("minTemperature"),
        "max_temperature_c": synkka.get("maxTemperature"),
        "reliability": reliability,
        "carbon_kg_co2e_per_kg": carbon,
        "substitutions": [s["substituteProduct"] for s in raw.get("substitutions") or []],
        "raw": raw,
    }


def upsert_products(db, docs: list[dict], batch_size: int = 500) -> int:
    """Insert or replace by `_id`, in batches. Running it again changes nothing."""
    for start in range(0, len(docs), batch_size):
        batch = docs[start:start + batch_size]
        db.products.bulk_write(
            [ReplaceOne({"_id": doc["_id"]}, doc, upsert=True) for doc in batch], ordered=False)
    return len(docs)


def get_product(db, product_id: str, raw: bool = False) -> dict | None:
    """One product by code (a string). The bulky `raw` record only on request."""
    doc = db.products.find_one({"_id": str(product_id)}, None if raw else {"raw": 0})
    if doc is not None:
        doc["product_id"] = doc.pop("_id")
    return doc
