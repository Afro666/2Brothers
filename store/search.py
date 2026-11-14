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
VECTOR_INDEX_NAME = "products_vector"
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
        {"$project": {"raw": 0, "embedding": 0}},
        {"$addFields": {"score": {"$meta": "searchScore"}}},
    ]


def vector_filter(filters: dict | None = None, kitchen_id: str | None = None) -> dict:
    """The same hard filters as the text search, as a `$vectorSearch` pre-filter.

    A similar meaning never overrides a filter: an excluded allergen, a required label
    and the kitchen scope cut rows before any ranking.
    """
    filters = filters or {}
    scope = [{"source": {"$ne": "own"}}]
    if kitchen_id is not None:
        scope.append({"kitchen_id": str(kitchen_id)})
    clauses: list[dict] = [{"$or": scope}]
    for path in ("temperature", "category", "supplier_id"):
        if filters.get(path) is not None:
            clauses.append({path: str(filters[path])})
    for label in filters.get("require_labels") or []:
        clauses.append({"labels": str(label)})
    if filters.get("pack_size") is not None:
        size = _size(filters["pack_size"].get("value"), filters["pack_size"].get("unit"))
        clauses += [{"net_content.unit": size["unit"]},
                    {"net_content.value": {"$gte": size["value"] * 0.99,
                                           "$lte": size["value"] * 1.01}}]
    codes = allergen_codes(filters.get("exclude_allergens"))
    if codes:
        strict = filters.get("allergen_strictness") == "strict"
        for level in ["contains", "may_contain"] + (["undeclared"] if strict else []):
            clauses.append({f"allergens.{level}": {"$nin": codes}})
        if strict:
            clauses.append({"allergen_data_known": {"$ne": False}})
    return {"$and": clauses}


def build_hybrid_pipeline(query: str, query_vector, filters: dict | None = None,
                          limit: int = 20, kitchen_id: str | None = None) -> list[dict]:
    """Text search and vector search over the same filters, fused by rank in Atlas.

    Each side gives its best `MAX_LIMIT` rows; `$rankFusion` merges them by reciprocal
    rank, so a product that words miss but meaning finds still comes up.
    """
    text_side = build_pipeline(query, filters, MAX_LIMIT, kitchen_id)[:2]  # validates too
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_LIMIT:
        raise ValueError(f"limit must be an integer from 1 to {MAX_LIMIT}")
    vector_side = [{"$vectorSearch": {
        "index": VECTOR_INDEX_NAME, "path": "embedding.vector", "queryVector": query_vector,
        "numCandidates": 10 * MAX_LIMIT, "limit": MAX_LIMIT,
        "filter": vector_filter(filters, kitchen_id)}}]
    return [
        {"$rankFusion": {"input": {"pipelines": {"text": text_side, "vector": vector_side}},
                         "scoreDetails": True}},
        {"$limit": limit},
        {"$addFields": {"score": {"$meta": "score"}, "fusion": {"$meta": "scoreDetails"}}},
        {"$project": {"raw": 0, "embedding": 0}},
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
                    kitchen_id: str | None = None, hybrid: bool = False,
                    embedder=None) -> list[dict]:
    """Best match first. Each row is the product row plus `score` and `match_reasons`.

    Pass the authenticated `kitchen_id` to include that kitchen's own products.
    `hybrid=True` adds meaning to words: the query is embedded and the vector search is
    fused with the text search. It needs the embedding service; when that fails, the
    call raises `EmbeddingError` and the caller can ask again without `hybrid`.
    """
    text, text_size = parse_query(query)
    if hybrid and text:
        from store.embeddings import embed, to_binary
        build_pipeline(query, filters, limit, kitchen_id)  # refuse bad input before paying
        vector = to_binary((embedder or embed)([query], "query")[0])
        pipeline = build_hybrid_pipeline(query, vector, filters, limit, kitchen_id)
    else:
        pipeline = build_pipeline(query, filters, limit, kitchen_id)
    filters = filters or {}
    size = (_size(filters["pack_size"]["value"], filters["pack_size"]["unit"])
            if filters.get("pack_size") else text_size)
    codes = allergen_codes(filters.get("exclude_allergens"))
    rows = []
    for doc in db.products.aggregate(pipeline):
        doc["product_id"] = doc.pop("_id")
        doc["match_reasons"] = _reasons(doc, text, size, codes)
        ranks = {side.get("inputPipelineName"): side.get("rank")
                 for side in (doc.pop("fusion", None) or {}).get("details", [])}
        if ranks.get("vector") and not ranks.get("text"):
            doc["match_reasons"].append("similar meaning, no word match")
        rows.append(doc)
    return rows


def _ensure_index(db, name: str, file: str, kind: str) -> str:
    definition = json.loads(Path(__file__).with_name(file).read_text())
    existing = list(db.products.list_search_indexes(name))
    if not existing:
        db.products.create_search_index(
            SearchIndexModel(definition=definition, name=name, type=kind))
        return "CREATED"
    if existing[0].get("latestDefinition") != definition:
        db.products.update_search_index(name, definition)
        return "UPDATING"
    return existing[0].get("status", "UNKNOWN")


def ensure_search_index(db) -> str:
    """Create the Atlas Search index, or update it when the committed definition
    changed. Returns its status; Atlas builds in the background until `READY`."""
    return _ensure_index(db, INDEX_NAME, "search_index.json", "search")


def ensure_vector_index(db) -> str:
    """The same for the Atlas Vector Search index (store/vector_index.json)."""
    return _ensure_index(db, VECTOR_INDEX_NAME, "vector_index.json", "vectorSearch")
