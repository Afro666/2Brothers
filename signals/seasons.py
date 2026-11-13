"""Finnish ingredient calendar; advisory only, with deliberately strict matching."""
from __future__ import annotations

import json
import re
import unicodedata
from datetime import date
from importlib.resources import files


def calendar() -> dict:
    """Read a fresh copy so callers cannot mutate subsequent lookups."""
    return json.loads(files("signals").joinpath("finland_seasons.json").read_text(encoding="utf-8"))


def _normal(text: str) -> str:
    return " ".join(re.findall(r"[^\W\d_]+", unicodedata.normalize("NFKC", text).casefold()))


def _ingredient(text: str, brand: str = "") -> str:
    # Strip only known packaging/quality words, never arbitrary suffixes (e.g. jam).
    text = re.sub(r"\b\d+(?:[.,]\d+)?\s*(?:kg|g|kpl|pcs)\b", " ", text.casefold())
    text = _normal(text)
    if brand and text.startswith(_normal(brand) + " "):
        text = text[len(_normal(brand)):].strip()
    return " ".join(w for w in text.split() if w not in {
        "fresh", "tuore", "tuoreet", "färsk", "färska", "organic", "luomu",
        "finnish", "suomalainen", "kotimainen", "kotimaiset", "wild", "villi",
    })


def match_product(product: str | dict) -> dict | None:
    """Match plain ingredients or store.products rows; unknown/ambiguous = None.

    Only exact ingredient aliases after removing known packaging words qualify.
    Numeric catalog categories are intentionally not guessed. Species-level fish
    matches require a wild-caught product flag, since farming is not seasonal.
    """
    if isinstance(product, str):
        names, categories, brand = [product], [], ""
    elif isinstance(product, dict):
        if product.get("temperature") == "frozen":
            return None
        if product.get("country") not in (None, "", "FI", "Finland", "Suomi"):
            return None
        localized = product.get("names") or {}
        names = list(localized.values()) if isinstance(localized, dict) else []
        names += [product.get("name", "")]
        categories = [product.get("category", "")]
        brand = product.get("brand") or ""
    else:
        return None
    normalized = {_ingredient(n, brand) for n in names if isinstance(n, str) and n.strip()}
    categories = {_normal(c) for c in categories if isinstance(c, str)}
    matches = []
    for entry in calendar()["items"]:
        aliases = {_normal(a) for a in entry["aliases"]}
        # Category-only matching is safe only when no name is supplied: a name
        # such as strawberry jam must never be overridden by a berries category.
        if not ((normalized and normalized <= aliases) or (not normalized and categories & aliases)):
            continue
        if entry["kind"] == "wild_fish" and isinstance(product, dict):
            if product.get("production_method") != "wild_caught":
                continue
        matches.append(entry)
    return matches[0] if len(matches) == 1 else None


def season_info(product: str | dict, on: date) -> dict | None:
    """Regional timing, not evidence of a particular product's freshness/price."""
    if not isinstance(on, date):
        raise TypeError("on must be a date")
    entry = match_product(product)
    if entry is None:
        return None
    return {
        "ingredient": entry["id"], "region": "FI", "date": on.isoformat(),
        "in_season": on.month in entry["harvest_months"],
        "peak": (on.month in entry["peak_months"]) if entry["peak_months"] else None,
        "storage_season": on.month in entry["storage_months"],
        "notes": entry["notes"], "sources": entry["sources"],
        "requires_chef_approval": True,
    }


def in_season(product: str | dict, on: date) -> bool | None:
    """True/False for known ingredients; None when no safe match exists."""
    info = season_info(product, on)
    return info["in_season"] if info else None


def chef_suggestions(products: list[dict], on: date) -> list[dict]:
    """Candidates for a chef to assess, without proposing an automatic swap.

    Require explicit Finnish origin; availability, price, allergens and culinary
    suitability must still be checked by the caller/chef.
    """
    result = []
    for product in products:
        if product.get("country") not in ("FI", "Finland", "Suomi"):
            continue
        info = season_info(product, on)
        if info and info["in_season"]:
            result.append({"product_id": product.get("product_id", product.get("_id")), **info})
    return result
