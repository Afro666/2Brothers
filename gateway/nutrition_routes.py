"""Nutrition from the catalog's label data (engine/nutrition.py).

- GET /v1/kitchens/{k}/recipes/{recipe_id}/nutrition: one portion as eaten.
- GET /v1/kitchens/{k}/recipes/nutrition?ids=: the same row for every recipe (or the ids
  asked) with one product lookup for all of them (#1101).
- GET /v1/kitchens/{k}/nutrition?from=&to=: per day of the menu plan the planned energy and
  energy per cover, and for the window what was ordered against what the plan needs.

Read-only. A product without a nutrition table is unknown, never zero: every answer says how
many ingredients or order lines it could count, and `complete` is false when any is missing.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import Depends, Request

from engine import nutrition
from engine.menu_demand import weeks_between
from gateway.kitchen_routes import incoming_orders_query
from gateway.service import GatewayError


def _plain(value):
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if isinstance(value, Decimal):
        return f"{value.normalize():f}"
    return value


def _products(db, ids: list[str]) -> dict[str, dict]:
    out = {}
    fields = {"names": 1, "net_content": 1, "units": 1, "sales_unit": 1, "raw.synkkaData.nutritionalContent": 1}
    for doc in db.products.find({"_id": {"$in": sorted(set(ids))}}, fields) if ids else []:
        content = doc.get("net_content") or {}
        sizes = {u.get("unit"): u.get("size_in_base_units") for u in doc.get("units") or []}
        out[doc["_id"]] = {"raw": doc.get("raw"), "net_content": content or None,
                           "name": (doc.get("names") or {}).get("en"), "sizes": sizes,
                           "kitchen_unit": content.get("unit") if content.get("unit") in ("KG", "L") else None}
    return out


MAX_BATCH_IDS = 200


def _ingredient_ids(recipes: list[dict]) -> list[str]:
    return [str(i["product_id"]) for r in recipes for i in r.get("ingredients") or []]


def _row(recipe: dict, products: dict[str, dict]) -> dict:
    result = nutrition.recipe_portion(recipe, products)
    return {"recipe_id": recipe["recipe_id"], "name": recipe.get("name"), **_plain(result),
            "unknown": [{"product_id": pid, "product_name": (products.get(pid) or {}).get("name")}
                        for pid in result["unknown"]],
            "source": "the products' own nutrition tables (GS1), per 100 g or 100 ml"}


def recipe_nutrition(db, kitchen_id: str, recipe_id: str) -> dict:
    from store.repository import Repository
    recipe = Repository(db).recipes.get(kitchen_id, recipe_id)
    if recipe is None:
        raise GatewayError(404, "NOT_FOUND", "no such recipe")
    return _row({**recipe, "recipe_id": recipe_id}, _products(db, _ingredient_ids([recipe])))


def parse_recipe_ids(raw: str | None) -> list[str] | None:
    """`?ids=`: None when absent (every recipe); 1 to 200 ids, else 422."""
    if raw is None:
        return None
    ids = list(dict.fromkeys(i.strip() for i in raw.split(",") if i.strip()))
    if not 1 <= len(ids) <= MAX_BATCH_IDS:
        raise GatewayError(422, "INVALID_REQUEST", f"ids must be 1 to {MAX_BATCH_IDS} recipe ids, comma-separated")
    return ids


def recipes_nutrition(db, kitchen_id: str, ids: list[str] | None = None) -> dict:
    """Every recipe's row, or the ids asked in that order (an unknown id left out)."""
    from store.repository import Repository
    recipes = Repository(db).recipes.list(kitchen_id)
    if ids is not None:
        by_id = {r["recipe_id"]: r for r in recipes}
        recipes = [by_id[i] for i in ids if i in by_id]
    products = _products(db, _ingredient_ids(recipes))
    return {"recipes": [_row(r, products) for r in recipes]}


def window_nutrition(db, kitchen_id: str, start: date, end: date) -> dict:
    from store.repository import Repository
    repo = Repository(db)
    recipes = {r["recipe_id"]: r for r in repo.recipes.list(kitchen_id)}
    entries = [d for week in weeks_between(start, end)
               for d in (repo.menu_plans.get(kitchen_id, week) or {}).get("days", [])
               if start.isoformat() <= d["date"] <= end.isoformat()]
    ids = [str(i["product_id"]) for r in recipes.values() for i in r.get("ingredients") or []]
    products = _products(db, ids)
    days = nutrition.menu_days(entries, recipes, products)
    planned = sum((d["kcal"] for d in days), Decimal(0))

    # What was ordered for delivery in the window: the orders the stock view counts as incoming
    # (approved and sent), by their proposal's delivery day.
    orders = list(db.orders.find(incoming_orders_query(kitchen_id)))
    delivery = {p["_id"]: (p.get("request") or {}).get("requested_date")
                for p in db.proposals.find({"_id": {"$in": [o.get("proposal_id") for o in orders]}}, {"request": 1})}
    lines = [ln for o in orders if start.isoformat() <= str(delivery.get(o.get("proposal_id")) or "") <= end.isoformat()
             for ln in o.get("lines", [])]
    ordered_products = _products(db, [str(ln.get("product_id")) for ln in lines])
    for line in lines:
        product = ordered_products.get(str(line.get("product_id")))
        if product:
            base_units = product["sizes"].get(line.get("unit"))
            content = (product.get("net_content") or {}).get("value")
            product["per_sales_unit"] = (Decimal(str(base_units)) * Decimal(str(content))
                                         if base_units is not None and content else None)
    ordered = nutrition.order_lines(lines, ordered_products)
    ordered_kcal = ordered["total"].get("kcal")
    ratio = (ordered_kcal / planned).quantize(Decimal("0.01")) if ordered_kcal and planned > 0 else None
    return _plain({
        "from": start.isoformat(), "to": end.isoformat(), "days": days,
        "planned": {"kcal": planned, "complete": bool(days) and all(d["complete"] for d in days)},
        "ordered": {**ordered["total"], "lines": len(lines), "known_lines": ordered["known_lines"],
                    "unknown": ordered["unknown"]},
        "ordered_vs_planned": ratio,
        "note": "Ordered energy is what the approved orders for this window contain; planned energy is "
                "covers x recipe portions. Stock on hand is not in either number.",
    })


def mount_nutrition(app, gw, principal) -> None:
    k = "/v1/kitchens/{kitchen_id}"

    # Before /recipes/{recipe_id} (gateway/kitchen_routes.py) so "nutrition" is never read as an id.
    @app.get(k + "/recipes/nutrition")
    def recipes(kitchen_id: str, request: Request, who=Depends(principal)):
        who.need("kitchen:read", kitchen_id)
        return recipes_nutrition(gw().db, kitchen_id, parse_recipe_ids(request.query_params.get("ids")))

    @app.get(k + "/recipes/{recipe_id}/nutrition")
    def recipe(kitchen_id: str, recipe_id: str, who=Depends(principal)):
        who.need("kitchen:read", kitchen_id)
        return recipe_nutrition(gw().db, kitchen_id, recipe_id)

    @app.get(k + "/nutrition")
    def window(kitchen_id: str, request: Request, who=Depends(principal)):
        who.need("kitchen:read", kitchen_id)
        q = request.query_params
        try:
            start, end = date.fromisoformat(q.get("from", "")), date.fromisoformat(q.get("to", ""))
        except ValueError:
            raise GatewayError(422, "INVALID_REQUEST", "from and to (YYYY-MM-DD) are required") from None
        if end < start or (end - start).days > 62:
            raise GatewayError(422, "INVALID_REQUEST", "from must be on or before to, at most 62 days apart")
        return window_nutrition(gw().db, kitchen_id, start, end)
