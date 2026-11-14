"""Product search over the one `products` collection, on Atlas Search.

`search_products(db, query, filters)` follows docs/contract.md. The index
definition is store/search_index.json; `ensure_search_index` creates it.
Atlas Search does not run locally: the query builder is unit-tested, and the
ranking is checked against the live cluster (store/tests/test_search_live.py).
"""

from __future__ import annotations

import json
from pathlib import Path
import re

from pymongo.operations import SearchIndexModel

INDEX_NAME = "products_search"
MAX_LIMIT = 50
# Ranking tiers: every query word in one name, then a size written in the query,
# then plain text relevance. The constants only need to be larger than a text score.
ALL_WORDS_BOOST = 200
SIZE_BOOST = 100

# The 14 EU allergens by GS1 code, plus three single ingredients people ask for.
# `gluten` covers the gluten cereals but not oats (GO): gluten-free oats exist.
ALLERGENS = {
    "gluten": ["AW", "UW", "NR", "GB", "GS", "GK"],
    "crustaceans": ["AC"], "eggs": ["AE"], "fish": ["AF"], "peanuts": ["AP"],
    "soy": ["AY"], "milk": ["AM"],
    "nuts": ["AN", "SA", "SC", "SH", "SM", "SP", "SR", "ST", "SW"],
    "celery": ["BC"], "mustard": ["BM"], "sesame": ["AS"], "sulphites": ["AU"],
    "lupin": ["NL"], "molluscs": ["UM"],
    "lactose": ["ML"], "wheat": ["UW"], "oats": ["GO"],
}
_NAME_BY_CODE = {codes[0]: name for name, codes in ALLERGENS.items()}
_KNOWN_CODES = {code for codes in ALLERGENS.values() for code in codes}

_UNITS = {"l": ("L", 1), "dl": ("L", 0.1), "cl": ("L", 0.01), "ml": ("L", 0.001),
          "kg": ("KG", 1), "g": ("KG", 0.001)}
_SIZE = re.compile(r"(?<![\w.,])(\d+(?:[.,]\d+)?)\s*(kg|g|dl|cl|ml|l)(?![\w])", re.IGNORECASE)
_TEXT_PATHS = ["names.en", "names.fi", "names.sv", "brand"]
_NAME_PATHS = ["names.en", "names.fi", "names.sv"]


def allergen_codes(wanted) -> list[str]:
    """Names ('milk') or GS1 codes ('AM') -> GS1 codes. An unknown one is an error:
    silently ignoring a misspelt allergen would return unsafe products."""
    codes = []
    for item in wanted or []:
        key = str(item).strip()
        if key.lower() in ALLERGENS:
            codes += ALLERGENS[key.lower()]
        elif key.upper() in _KNOWN_CODES:
            codes.append(key.upper())
        else:
            raise ValueError(f"unknown allergen: {item!r}")
    return sorted(set(codes))


def _size(value, unit) -> dict:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError("pack_size.value must be a number")
    if str(unit).lower() not in _UNITS:
        raise ValueError(f"pack_size.unit must be one of {sorted(_UNITS)}")
    unit, factor = _UNITS[str(unit).lower()]
    value = float(str(value).replace(",", ".")) * factor
    if value <= 0:
        raise ValueError("pack_size.value must be positive")
    return {"value": round(value, 6), "unit": unit}


def parse_query(query: str) -> tuple[str, dict | None]:
    """'lactose free milk 1 l' -> ('lactose free milk', {'value': 1.0, 'unit': 'L'})."""
    query = query or ""
    match = _SIZE.search(query)
    if not match:
        return " ".join(query.split()), None
    text = query[:match.start()] + " " + query[match.end():]
    return " ".join(text.split()), _size(match.group(1), match.group(2))


def _size_clause(size: dict) -> dict:
    """Same unit and the value within 1%: 1 l matches 1.0 l, not 1.5 l."""
    return {"compound": {"filter": [
        {"equals": {"path": "net_content.unit", "value": size["unit"]}},
        {"range": {"path": "net_content.value",
                   "gte": size["value"] * 0.99, "lte": size["value"] * 1.01}}]}}


def build_pipeline(query: str, filters: dict | None = None, limit: int = 20,
                   kitchen_id: str | None = None) -> list[dict]:
    """The aggregation pipeline for one search. Pure, so it can be tested offline.

    Catalog rows have no `kitchen_id`; an own product belongs to one kitchen. A search
    sees the catalog plus the asking kitchen's own products, never another kitchen's.
    """
    filters = dict(filters or {})
    unknown = set(filters) - {"exclude_allergens", "allergen_strictness", "require_labels",
                              "temperature", "category", "pack_size", "supplier_id"}
    if unknown:
        raise ValueError(f"unknown filters: {sorted(unknown)}")
    strictness = filters.get("allergen_strictness", "declared")
    if strictness not in ("declared", "strict"):
        raise ValueError("allergen_strictness must be 'declared' or 'strict'")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_LIMIT:
        raise ValueError(f"limit must be an integer from 1 to {MAX_LIMIT}")
    for name in ("require_labels", "exclude_allergens"):
        if filters.get(name) is not None and not isinstance(filters[name], (list, tuple)):
            raise ValueError(f"{name} must be a list of strings")

    text, text_size = parse_query(query)
    compound: dict = {"filter": [], "mustNot": [], "should": []}
    catalog = {"compound": {"must": [{"exists": {"path": "supplier_id"}}],
                            "mustNot": [{"exists": {"path": "kitchen_id"}}]}}
    scope = [catalog]
    if kitchen_id is not None:
        scope.append({"equals": {"path": "kitchen_id", "value": str(kitchen_id)}})
    scope_clause = {"compound": {"should": scope, "minimumShouldMatch": 1}}
    for path in ("temperature", "category", "supplier_id"):
        if filters.get(path) is not None:
            compound["filter"].append({"equals": {"path": path, "value": str(filters[path])}})
    for label in filters.get("require_labels") or []:
        compound["filter"].append({"equals": {"path": "labels", "value": str(label)}})
    if filters.get("pack_size") is not None:
        wanted = filters["pack_size"]
        if not isinstance(wanted, dict):
            raise ValueError("pack_size must be {value, unit}")
        compound["filter"].append(_size_clause(_size(wanted.get("value"), wanted.get("unit"))))
    elif text_size:
        boost = _size_clause(text_size)
        boost["compound"]["score"] = {"constant": {"value": SIZE_BOOST}}
        compound["should"].append(boost)

    codes = allergen_codes(filters.get("exclude_allergens"))
    if codes:
        levels = ["contains", "may_contain"] + (["undeclared"] if strictness == "strict" else [])
        for level in levels:
            compound["mustNot"].append({"in": {"path": f"allergens.{level}", "value": codes}})
        if strictness == "strict":
            compound["mustNot"].append({"equals": {"path": "allergen_data_known", "value": False}})

    if text:
        fuzzy = {"maxEdits": 1, "prefixLength": 1}  # one typo, not in the first letter
        compound["must"] = [{"text": {"query": text, "path": _TEXT_PATHS, "fuzzy": fuzzy}}]
        compound["should"] += [
            {"text": {"query": text, "path": _NAME_PATHS, "fuzzy": fuzzy, "matchCriteria": "all",
                      "score": {"constant": {"value": ALL_WORDS_BOOST}}}},
            {"text": {"query": text, "path": _TEXT_PATHS}},  # exact words beat near misses
            {"phrase": {"query": text, "path": _NAME_PATHS, "slop": 2,
                        "score": {"boost": {"value": 3}}}}]
    elif not compound["filter"] and not compound["mustNot"]:
        raise ValueError("give a query or at least one filter")
    compound["filter"].append(scope_clause)
    compound = {key: value for key, value in compound.items() if value}
    return [
        {"$search": {"index": INDEX_NAME, "compound": compound}},
        {"$limit": limit},
        {"$project": {"raw": 0}},
        {"$addFields": {"score": {"$meta": "searchScore"}}},
    ]


def _reasons(doc: dict, text: str, size: dict | None, codes: list[str]) -> list[str]:
    """Short, human-readable notes on why this row is here and what to watch."""
    reasons = []
    content = doc.get("net_content")
    if size and content and content["unit"] == size["unit"] \
            and abs(content["value"] - size["value"]) <= 0.01 * size["value"]:
        reasons.append(f"size {size['value']:g} {size['unit']} matches")
        if doc.get("net_content_source") == "name":
            reasons.append("size read from the name")
    elif size and not content:
        reasons.append("size unknown")
    if text and any(text.lower() in name.lower() for name in (doc.get("names") or {}).values()):
        reasons.append(f'name contains "{text}"')
    if codes:
        if not doc.get("allergen_data_known"):
            reasons.append("allergen data missing")
        for code in sorted(set(codes) & set((doc.get("allergens") or {}).get("undeclared", []))):
            reasons.append(f"{_NAME_BY_CODE.get(code, code)} undeclared")
    return reasons


def search_products(db, query: str = "", filters: dict | None = None, limit: int = 20,
                    kitchen_id: str | None = None) -> list[dict]:
    """Best match first. Each row is the product row plus `score` and `match_reasons`.

    Pass the authenticated `kitchen_id` to include that kitchen's own products.
    """
    pipeline = build_pipeline(query, filters, limit, kitchen_id)
    text, text_size = parse_query(query)
    filters = filters or {}
    size = (_size(filters["pack_size"]["value"], filters["pack_size"]["unit"])
            if filters.get("pack_size") else text_size)
    codes = allergen_codes(filters.get("exclude_allergens"))
    rows = []
    for doc in db.products.aggregate(pipeline):
        doc["product_id"] = doc.pop("_id")
        doc["match_reasons"] = _reasons(doc, text, size, codes)
        rows.append(doc)
    return rows


def ensure_search_index(db) -> str:
    """Create the Atlas Search index, or update it when the committed definition
    changed. Returns its status; Atlas builds in the background until `READY`."""
    definition = json.loads(Path(__file__).with_name("search_index.json").read_text())
    existing = list(db.products.list_search_indexes(INDEX_NAME))
    if not existing:
        db.products.create_search_index(SearchIndexModel(definition=definition, name=INDEX_NAME))
        return "CREATED"
    if existing[0].get("latestDefinition") != definition:
        db.products.update_search_index(INDEX_NAME, definition)
        return "UPDATING"
    return existing[0].get("status", "UNKNOWN")
