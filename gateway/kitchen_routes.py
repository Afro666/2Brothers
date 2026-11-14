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
from store.history import forecasts_between


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
        from store.history import StockCountBusy, record_stock_count, stock_count_once
        actor = writer(who, kitchen_id)
        data = await body(request)
        key = data.get("idempotency_key")
        if not isinstance(key, str) or not key.strip():
            raise GatewayError(422, "INVALID_REQUEST", "idempotency_key is required")

        def store():
            counted_at = datetime.fromisoformat(str(data.get("counted_at")))
            return record_stock_count(gw().db, kitchen_id, counted_at, data.get("counts") or [],
                                      data.get("source") or "manual")
        try:
            count_id, stored, replayed = guarded(lambda: stock_count_once(gw().db, kitchen_id, key, store))
        except StockCountBusy:
            raise GatewayError(409, "IDEMPOTENCY_IN_PROGRESS", "this count is being stored now; try again") from None
        if replayed:
            return {"stock_count_id": count_id, "stored": stored}
        gw()._audit(kitchen_id, "stock_counted", actor, lines=stored, source=data.get("source") or "manual")
        return {"stock_count_id": count_id, "stored": stored}

    def stock_items(kitchen_id: str) -> list[dict]:
        return _stock_items(gw().db, kitchen_id, gw().now().date())


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
        rows, problems = demand_rows(gw().db, kitchen_id, start, end, gw().now().date())
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
                    "budget_warning_week_eur": base.budget_warning_week_eur,
                    "certainty_premium_max": base.certainty_premium_max,
                    # off and none until a person sets them (#631, #380)
                    "approve_unconfirmed_manual": False, "standing_orders": {}}
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


# Net content units scaled to a kitchen unit: (kitchen unit, factor).
_CONTENT_UNITS = {"l": ("L", Decimal(1)), "ml": ("L", Decimal("0.001")),
                  "kg": ("KG", Decimal(1)), "g": ("KG", Decimal("0.001"))}


def _content_per_base_unit(content: dict | None, kitchen_unit: str | None) -> Decimal | None:
    """How much of the kitchen unit one base unit holds, or None when the units do not match.
    No net content means one base unit is one piece, so it only fits a kitchen counting in PCS."""
    kitchen_unit = (kitchen_unit or "").upper()
    if not content or content.get("value") is None:
        return Decimal(1) if kitchen_unit == "PCS" else None
    unit, factor = _CONTENT_UNITS.get(str(content.get("unit") or "").lower(), (None, None))
    if unit is None or unit != kitchen_unit:
        return None
    return Decimal(str(content["value"])) * factor


def _open_orders(db, kitchen_id: str, today: date,
                 kitchen_units: dict[str, str] | None = None) -> tuple[dict, dict, set]:
    """What is on order per product, in kitchen units (`kitchen_units`: the unit the kitchen
    counts each product in): approved orders whose delivery day is today or later. Returns
    (quantity per product, next delivery day per product, products whose order line cannot be
    converted to kitchen units: for those on order is unknown)."""
    kitchen_units = kitchen_units or {}
    qty: dict[str, Decimal] = {}
    due: dict[str, date] = {}
    unknown: set[str] = set()
    orders = list(db.orders.find({"kitchen_id": kitchen_id, "outcome": "CONFIRMED",
                                  "status": {"$in": ["SENT", "CONFIRMED", "PARTIAL"]}}))
    if not orders:
        return qty, due, unknown
    days = {p["_id"]: (p.get("request") or {}).get("requested_date")
            for p in db.proposals.find({"_id": {"$in": [o.get("proposal_id") for o in orders]}}, {"request": 1})}
    ids = sorted({ln.get("product_id") for o in orders for ln in o.get("lines", [])})
    docs = {d["_id"]: d for d in db.products.find({"_id": {"$in": ids}}, {"units": 1, "net_content": 1})}
    for order in orders:
        try:
            delivery = date.fromisoformat(str(days.get(order.get("proposal_id"))))
        except ValueError:
            continue                        # no delivery day known: not counted as on order
        if delivery < today:
            continue                        # the day has passed: it is in the next stock count
        for line in order.get("lines", []):
            pid = line.get("product_id")
            doc = docs.get(pid) or {}
            sizes = {u.get("unit"): u.get("size_in_base_units") for u in doc.get("units") or []}
            base_units = sizes.get(line.get("unit"))
            content = _content_per_base_unit(doc.get("net_content"), kitchen_units.get(pid))
            if base_units is None or content is None:
                unknown.add(pid)
                continue
            per = Decimal(str(base_units)) * content
            qty[pid] = qty.get(pid, Decimal(0)) + Decimal(str(line.get("quantity"))) * per
            due[pid] = min(due.get(pid, delivery), delivery)
    return qty, due, unknown


def _stock_items(db, kitchen_id: str, today: date | None = None) -> list[dict]:
    from store.history import current_stock
    rows = current_stock(db, kitchen_id)
    qty, due, unknown = _open_orders(db, kitchen_id, today or datetime.now().date(),
                                     {row["product_id"]: row["unit"] for row in rows})
    items = []
    for row in rows:
        pid = row["product_id"]
        on_hand = row.get("on_hand")
        on_hand = None if on_hand is None else Decimal(str(on_hand))
        known = pid not in unknown
        # An order line that cannot be converted to kitchen units makes `on_order` unknown
        # (null with `on_order_known: false`), never a silent zero.
        on_order = qty.get(pid, Decimal(0)) if known else None
        position = None if on_hand is None or on_order is None else on_hand + on_order
        items.append({"product_id": pid, "unit": row["unit"], "on_hand": on_hand,
                      "counted_at": row.get("counted_at"), "on_order": on_order, "on_order_known": known,
                      "position": position, "next_delivery_date": due.get(pid)})
    return items


def demand_rows(db, kitchen_id: str, start: date, end: date,
                today: date | None = None) -> tuple[list[dict], list[str]]:
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
    for f in forecasts_between(db, kitchen_id, lo, hi):
        day = f["ts"].date().isoformat()
        if day not in planned_days:
            rows.append({"product_id": f["meta"]["product_id"], "date": day, "unit": f["unit"],
                         "covers": None, "gross_need": Decimal(str(f["need"])),
                         "why": f.get("why") or "forecast from history", "source": "history"})
    stock = {item["product_id"]: item["position"] for item in _stock_items(db, kitchen_id, today)}
    return net_needs(rows, stock), problems
