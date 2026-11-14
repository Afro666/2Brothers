"""Kitchen planning routes (#74, docs/contract.md "Kitchen side"): stock, own products,
recipes, menu plans, suppliers, settings, forecast sharing and future demand.

Thin HTTP over store.Repository and store.history; the numbers come from engine.menu_demand.
Reads need `kitchen:read`. Writes need a person who is not a viewer, or a token with
`kitchen:write` (a POS or inventory system pushing counts). Settings and sharing change only
by an approver. Every write is an audit entry.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from fastapi import Depends, Request

from gateway.service import GatewayError


def _json(value):
    """Decimals as strings, datetimes as ISO: the contract's wire format."""
    if isinstance(value, dict):
        return {k: _json(v) for k, v in value.items() if k != "_id"}
    if isinstance(value, (list, tuple)):
        return [_json(v) for v in value]
    if isinstance(value, Decimal):
        return f"{value.normalize():f}" if value == value.to_integral() else f"{value:f}"
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if type(value).__name__ == "Decimal128":
        return _json(value.to_decimal())
    return value


def register(app, gw, principal, body) -> None:
    k = "/v1/kitchens/{kitchen_id}"

    def repo():
        from store.repository import Repository
        return Repository(gw().db)

    def reader(who, kitchen_id: str) -> None:
        who.need("kitchen:read", kitchen_id)

    def writer(who, kitchen_id: str) -> str:
        who.need("kitchen:write", kitchen_id)
        return who.name

    def approver(who, kitchen_id: str) -> str:
        who.need("kitchen:read", kitchen_id)
        if not who.human:
            raise GatewayError(403, "HUMAN_SESSION_REQUIRED", "only an approver can change this")
        return who.human

    def guarded(fn):
        """Store validation errors become 422 with the store's own sentence."""
        try:
            return fn()
        except GatewayError:
            raise
        except (ValueError, TypeError, KeyError) as exc:
            raise GatewayError(422, "INVALID_REQUEST", str(exc)[:300]) from None

    # ---- generic CRUD for suppliers, recipes and own products --------------------------
    def crud(path: str, name: str, collection):
        @app.get(k + path, name=f"list_{name}")
        def list_all(kitchen_id: str, who=Depends(principal)):
            reader(who, kitchen_id)
            return {name: _json(collection().list(kitchen_id))}

        @app.get(k + path + "/{item_id}", name=f"get_{name}")
        def get_one(kitchen_id: str, item_id: str, who=Depends(principal)):
            reader(who, kitchen_id)
            item = collection().get(kitchen_id, item_id)
            if item is None:
                raise GatewayError(404, "NOT_FOUND", f"no such entry in {name}")
            return _json(item)

        @app.post(k + path, name=f"create_{name}")
        async def create(kitchen_id: str, request: Request, who=Depends(principal)):
            actor = writer(who, kitchen_id)
            data = await body(request)
            data.pop("idempotency_key", None)
            item = guarded(lambda: collection().create(kitchen_id, data))
            gw()._audit(kitchen_id, f"{name}_created", actor, name=item.get("name"))
            return _json(item)

        @app.put(k + path + "/{item_id}", name=f"update_{name}")
        async def update(kitchen_id: str, item_id: str, request: Request, who=Depends(principal)):
            actor = writer(who, kitchen_id)
            data = await body(request)
            data.pop("idempotency_key", None)
            item = guarded(lambda: collection().update(kitchen_id, item_id, data))
            if item is None:
                raise GatewayError(404, "NOT_FOUND", f"no such entry in {name}")
            gw()._audit(kitchen_id, f"{name}_changed", actor, name=item.get("name"))
            return _json(item)

        @app.delete(k + path + "/{item_id}", name=f"delete_{name}")
        def delete(kitchen_id: str, item_id: str, who=Depends(principal)):
            actor = writer(who, kitchen_id)
            if not collection().delete(kitchen_id, item_id):
                raise GatewayError(404, "NOT_FOUND", f"no such entry in {name}")
            gw()._audit(kitchen_id, f"{name}_deleted", actor, item_id=item_id)
            return {"deleted": True}

    crud("/suppliers", "suppliers", lambda: repo().suppliers)
    crud("/recipes", "recipes", lambda: repo().recipes)
    crud("/products", "products", lambda: repo().own_products)

    # ---- menu plans ---------------------------------------------------------------------
    @app.get(k + "/menu-plans/{week}")
    def get_menu_plan(kitchen_id: str, week: str, who=Depends(principal)):
        reader(who, kitchen_id)
        plan = repo().menu_plans.get(kitchen_id, week)
        return _json(plan or {"kitchen_id": kitchen_id, "week": week, "days": []})

    @app.put(k + "/menu-plans/{week}")
    async def put_menu_plan(kitchen_id: str, week: str, request: Request, who=Depends(principal)):
        actor = writer(who, kitchen_id)
        data = await body(request)
        plan = guarded(lambda: repo().menu_plans.put(kitchen_id, week, data.get("days")))
        gw()._audit(kitchen_id, "menu_plan_changed", actor, week=week, entries=len(plan["days"]))
        return _json(plan)

    # ---- stock --------------------------------------------------------------------------
    @app.post(k + "/stock-counts")
    async def stock_count(kitchen_id: str, request: Request, who=Depends(principal)):
        from store.history import record_stock_count
        actor = writer(who, kitchen_id)
        data = await body(request)
        key = data.get("idempotency_key")
        if not isinstance(key, str) or not key.strip():
            raise GatewayError(422, "INVALID_REQUEST", "idempotency_key is required")
        done = gw().db.stock_count_keys.find_one({"_id": f"{kitchen_id}:{key}"})
        if done:
            return {"stock_count_id": done["stock_count_id"], "stored": done["stored"]}

        def store():
            counted_at = datetime.fromisoformat(str(data.get("counted_at")))
            return record_stock_count(gw().db, kitchen_id, counted_at, data.get("counts") or [],
                                      data.get("source") or "manual")
        stored = guarded(store)
        count_id = f"{kitchen_id}:{key}"
        gw().db.stock_count_keys.insert_one({"_id": count_id, "stock_count_id": count_id, "stored": stored})
        gw()._audit(kitchen_id, "stock_counted", actor, lines=stored, source=data.get("source") or "manual")
        return {"stock_count_id": count_id, "stored": stored}

    def stock_items(kitchen_id: str) -> list[dict]:
        return _stock_items(gw().db, kitchen_id)


    @app.get(k + "/stock")
    def stock(kitchen_id: str, who=Depends(principal)):
        reader(who, kitchen_id)
        return {"as_of": gw().now().isoformat(), "items": _json(_named(gw().db, stock_items(kitchen_id)))}

    # ---- future demand ------------------------------------------------------------------
    @app.get(k + "/demand")
    def demand(kitchen_id: str, request: Request, who=Depends(principal)):
        reader(who, kitchen_id)
        q = request.query_params

        def window():
            start, end = date.fromisoformat(q.get("from", "")), date.fromisoformat(q.get("to", ""))
            if end < start or (end - start).days > 62:
                raise ValueError("from must be on or before to, at most 62 days apart")
            return start, end
        start, end = guarded(window)
        rows, problems = demand_rows(gw().db, kitchen_id, start, end)
        return {"from": start.isoformat(), "to": end.isoformat(), "rows": _json(_named(gw().db, rows)),
                "problems": problems}

    # ---- settings and sharing: an approver only -----------------------------------------
    @app.get(k + "/settings")
    def get_settings(kitchen_id: str, who=Depends(principal)):
        reader(who, kitchen_id)
        from engine.params import KitchenParams
        base = KitchenParams()
        # `defaults` is what the engine uses for every field the kitchen has not set.
        defaults = {"service_level": base.service_level, "max_cover_days": base.max_cover_days,
                    "stockout_cap": base.stockout_cap, "budget_warning_order_eur": base.budget_warning_order_eur,
                    "budget_warning_week_eur": base.budget_warning_week_eur}
        return {**_json(repo().settings.get(kitchen_id)), "defaults": _json(defaults)}

    @app.put(k + "/settings")
    async def put_settings(kitchen_id: str, request: Request, who=Depends(principal)):
        person = approver(who, kitchen_id)
        data = await body(request)
        data.pop("idempotency_key", None)
        after, changed = guarded(lambda: repo().settings.put(kitchen_id, data))
        if changed:
            gw()._audit(kitchen_id, "settings_changed", person, changed=_json(changed))
        return _json(after)

    @app.get(k + "/sharing")
    def get_sharing(kitchen_id: str, who=Depends(principal)):
        from store.history import list_sharing
        reader(who, kitchen_id)
        return {"sharing": _json(list_sharing(gw().db, kitchen_id))}

    @app.put(k + "/sharing")
    async def put_sharing(kitchen_id: str, request: Request, who=Depends(principal)):
        from store.history import list_sharing, set_sharing
        person = approver(who, kitchen_id)
        data = await body(request)
        if not data.get("supplier_id") or not isinstance(data.get("share_forecast"), bool):
            raise GatewayError(422, "INVALID_REQUEST", "supplier_id and share_forecast (true or false) are required")
        guarded(lambda: set_sharing(gw().db, kitchen_id, str(data["supplier_id"]), data["share_forecast"], person))
        return {"sharing": _json(list_sharing(gw().db, kitchen_id))}


def _named(db, rows: list[dict]) -> list[dict]:
    """Add `product_name` where the catalog or the kitchen's own products know it; a product
    without a name keeps only its id (never an invented name)."""
    ids = sorted({row["product_id"] for row in rows})
    names = {d["_id"]: (d.get("names") or {}).get("en")
             for d in db.products.find({"_id": {"$in": ids}}, {"names": 1})} if ids else {}
    return [{**row, "product_name": names.get(row["product_id"])} for row in rows]


def _stock_items(db, kitchen_id: str) -> list[dict]:
    from store.history import current_stock
    items = []
    for row in current_stock(db, kitchen_id):
        on_hand = row.get("on_hand")
        on_hand = None if on_hand is None else Decimal(str(on_hand))
        # Open orders are in supplier units; they are not converted to kitchen units yet,
        # so `on_order` is 0 and `on_order_known` says so (never a silent zero).
        items.append({"product_id": row["product_id"], "unit": row["unit"], "on_hand": on_hand,
                      "counted_at": row.get("counted_at"), "on_order": Decimal(0),
                      "on_order_known": False, "position": on_hand, "next_delivery_date": None})
    return items


def demand_rows(db, kitchen_id: str, start: date, end: date) -> tuple[list[dict], list[str]]:
    """Per product and day: gross and net need from the menu plan; days without a plan use
    the stored forecast. Shared by GET /demand and the "propose an order for this plan" path."""
    from datetime import timezone

    from engine.menu_demand import gross_needs, net_needs, weeks_between
    from store.repository import Repository
    r = Repository(db)
    recipes = {x["recipe_id"]: x for x in r.recipes.list(kitchen_id)}
    entries = [day for week in weeks_between(start, end)
               for day in (r.menu_plans.get(kitchen_id, week) or {}).get("days", [])
               if start.isoformat() <= day["date"] <= end.isoformat()]
    rows, problems = gross_needs(entries, recipes)
    for row in rows:
        row["source"] = "menu_plan"
    planned_days = {row["date"] for row in rows}
    lo = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
    hi = datetime.combine(end, datetime.max.time(), tzinfo=timezone.utc)
    for f in db.forecasts.find({"meta.kitchen_id": kitchen_id, "ts": {"$gte": lo, "$lte": hi}}):
        day = f["ts"].date().isoformat()
        if day not in planned_days:
            rows.append({"product_id": f["meta"]["product_id"], "date": day, "unit": f["unit"],
                         "covers": None, "gross_need": Decimal(str(f["need"])),
                         "why": f.get("why") or "forecast from history", "source": "history"})
    stock = {item["product_id"]: (item["unit"], item["position"]) for item in _stock_items(db, kitchen_id)}
    return net_needs(rows, stock, problems), problems
