"""Nutrition from the catalog's own label data (GS1, per 100 g or 100 ml). Pure, no I/O.

Valio's catalog carries the nutrition table of about 12,000 of its 17,500 products. This
module reads it and adds it up: per recipe portion, per menu day and per order. A product
without label data is unknown, never zero: every total says how much of it is known.
"""

from __future__ import annotations

from decimal import Decimal

# GS1 nutrient codes -> our field names.
CODES = {"ENER-E14": "kcal", "PRO-": "protein_g", "FAT": "fat_g", "FASAT": "saturated_fat_g",
         "CHOAVL": "carbs_g", "SUGAR-": "sugar_g", "FIBTG": "fibre_g", "SALTEQ": "salt_g"}
FIELDS = tuple(CODES.values())
KJ_PER_KCAL = Decimal("4.184")


def per_100(raw: dict | None) -> dict | None:
    """The label per 100 g or 100 ml: {"basis": "g" | "ml", "kcal": Decimal, ...}; None when the
    product has no usable table. A nutrient the label leaves out is absent, not 0."""
    rows = ((raw or {}).get("synkkaData") or {}).get("nutritionalContent") or []
    out: dict = {}
    basis = None
    for row in rows:
        unit = row.get("basisQuantityUnit")
        quantity = row.get("basisQuantity")
        if unit not in ("GRM", "MLT") or not quantity or row.get("value") is None:
            continue                               # per portion ("PTN") cannot be scaled: skipped
        scale = Decimal(100) / Decimal(str(quantity))
        value = Decimal(str(row["value"])) * scale
        field = CODES.get(row.get("id"))
        if field:
            out[field] = value
            basis = "g" if unit == "GRM" else "ml"
        elif row.get("id") == "ENER-KJO" and "kcal" not in out:
            out["_kj"] = value
            basis = basis or ("g" if unit == "GRM" else "ml")
    if "kcal" not in out and "_kj" in out:
        out["kcal"] = out["_kj"] / KJ_PER_KCAL
    out.pop("_kj", None)
    if "kcal" not in out or basis is None:
        return None
    return {"basis": basis, **out}


def amount_in_basis(quantity: Decimal, unit: str, label: dict, net_content: dict | None) -> Decimal | None:
    """`quantity` of a product in kitchen units (KG, L, PCS) as grams or millilitres of the
    label's basis. A litre is taken as a kilo and a kilo as a litre (density about 1, true
    within a few percent for milk, cream, oil-free drinks); a piece needs the product's net
    content. None when it cannot be known."""
    if unit in ("KG", "L"):
        return quantity * 1000
    if unit == "PCS" and net_content and net_content.get("value") and net_content.get("unit") in ("KG", "L"):
        return quantity * Decimal(str(net_content["value"])) * 1000
    return None


def _add(total: dict, label: dict, amount: Decimal) -> None:
    for field in FIELDS:
        if field in label:
            total[field] = total.get(field, Decimal(0)) + label[field] * amount / 100


def _round(total: dict) -> dict:
    return {k: (v.quantize(Decimal("1")) if k == "kcal" else v.quantize(Decimal("0.1"))) for k, v in total.items()}


def recipe_portion(recipe: dict, products: dict[str, dict]) -> dict:
    """Nutrition of one portion as eaten: the recipe's quantity per portion (the yield is
    what is bought, not what is eaten). `products`: product_id -> {"raw", "net_content", "name"}.
    Returns totals, `known_ingredients`, `unknown` (product ids with no label or no amount)
    and `complete` (every ingredient known)."""
    total: dict = {}
    unknown: list[str] = []
    known = 0
    for item in recipe.get("ingredients") or []:
        pid = str(item["product_id"])
        product = products.get(pid) or {}
        label = per_100(product.get("raw"))
        amount = amount_in_basis(Decimal(str(item["qty_per_portion"])), item["unit"], label or {},
                                 product.get("net_content")) if label else None
        if label is None or amount is None:
            unknown.append(pid)
            continue
        _add(total, label, amount)
        known += 1
    return {"per_portion": _round(total), "known_ingredients": known, "unknown": unknown,
            "complete": not unknown and known > 0}


def menu_days(entries: list[dict], recipes: dict[str, dict], products: dict[str, dict]) -> list[dict]:
    """Per day of a menu plan: covers, planned kcal (covers x portion) and kcal per cover.
    `complete` is false when a recipe has an ingredient without label data or covers are missing."""
    portions = {rid: recipe_portion(r, products) for rid, r in recipes.items()}
    days: dict[str, dict] = {}
    for entry in entries:
        day = days.setdefault(str(entry["date"]), {"date": str(entry["date"]), "covers": 0,
                                                   "kcal": Decimal(0), "protein_g": Decimal(0), "complete": True})
        portion = portions.get(str(entry.get("recipe_id")))
        covers = entry.get("covers")
        if portion is None or covers is None or "kcal" not in portion["per_portion"]:
            day["complete"] = False
            continue
        day["covers"] = max(day["covers"], int(covers))       # the busiest dish: the day's guests
        day["kcal"] += portion["per_portion"]["kcal"] * covers
        day["protein_g"] += portion["per_portion"].get("protein_g", Decimal(0)) * covers
        day["complete"] = day["complete"] and portion["complete"]
    out = []
    for day in sorted(days.values(), key=lambda d: d["date"]):
        per_cover = (day["kcal"] / day["covers"]).quantize(Decimal("1")) if day["covers"] else None
        out.append({**day, "kcal": day["kcal"].quantize(Decimal("1")),
                    "protein_g": day["protein_g"].quantize(Decimal("1")), "kcal_per_cover": per_cover})
    return out


def order_lines(lines: list[dict], products: dict[str, dict]) -> dict:
    """Energy and macros of what was ordered. Each line: product_id, quantity (sales units),
    unit. `products[pid]` also needs `per_sales_unit` (kitchen units in one sales unit) and
    `kitchen_unit` (KG, L or PCS). Returns totals and how many lines are known."""
    total: dict = {}
    known, unknown = 0, []
    for line in lines:
        pid = str(line.get("product_id"))
        product = products.get(pid) or {}
        label = per_100(product.get("raw"))
        per = product.get("per_sales_unit")
        if label is None or per is None:
            unknown.append(pid)
            continue
        amount = amount_in_basis(Decimal(str(line["quantity"])) * Decimal(str(per)),
                                 product.get("kitchen_unit") or "KG", label, product.get("net_content"))
        if amount is None:
            unknown.append(pid)
            continue
        _add(total, label, amount)
        known += 1
    return {"total": _round(total), "known_lines": known, "unknown": unknown}
