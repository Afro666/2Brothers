"""The wholesaler's view (#33, docs/contract.md "Supplier side"): forecast demand across the
kitchens that agreed to share, against what the supplier can deliver.

- GET /v1/suppliers/{supplier_id}/demand?from=&to=[&product=]
- GET /v1/suppliers/{supplier_id}/demand/shortage-risk?from=&to=   (only rows not OK)

Consent decides everything: a kitchen without active consent for this supplier appears
nowhere, not in a sum and not in a list. Demand is the kitchens' stored forecast (engine:
covers x recipe). Availability is asked live for the products in the answer only, converted
to kitchen units; a sentinel or a missing value is unknown (null), never plenty.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_CEILING, Decimal

from fastapi import Depends, Request

from gateway.service import GatewayError
from store.history import consenting_kitchens

MAX_DAYS = 14


def _q(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.001')).normalize():f}"


def _per_sales_unit(doc: dict) -> Decimal | None:
    """Kitchen units (L, KG or PCS) in one sales unit of a catalog product, or None."""
    sizes = {u.get("unit"): u.get("size_in_base_units") for u in doc.get("units") or []}
    base_units = sizes.get(doc.get("sales_unit"))
    if base_units is None:
        return None
    content = (doc.get("net_content") or {}).get("value")
    return Decimal(str(base_units)) * (Decimal(str(content)) if content else Decimal(1))


def supplier_demand(db, valio, supplier_id: str, start: date, end: date, product: str | None = None) -> dict:
    kitchens = consenting_kitchens(db, supplier_id)
    names = {k["_id"]: k.get("name") for k in db.kitchens.find({"_id": {"$in": kitchens}}, {"name": 1})} if kitchens else {}
    lo = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
    hi = datetime.combine(end, datetime.max.time(), tzinfo=timezone.utc)
    query = {"meta.kitchen_id": {"$in": kitchens}, "ts": {"$gte": lo, "$lte": hi}}
    if product:
        query["meta.product_id"] = str(product)
    total: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
    parts: dict[tuple[str, str], dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    unit: dict[str, str] = {}
    for row in db.forecasts.find(query) if kitchens else []:
        need = Decimal(str(row["need"]))
        if need <= 0:
            continue
        key = (row["meta"]["product_id"], row["ts"].date().isoformat())
        total[key] += need
        parts[key][row["meta"]["kitchen_id"]] += need
        unit[key[0]] = row["unit"]

    products = sorted({pid for pid, _ in total})
    docs = {d["_id"]: d for d in db.products.find({"_id": {"$in": products}},
                                                  {"names": 1, "units": 1, "sales_unit": 1, "net_content": 1})}
    available: dict[tuple[str, str], Decimal | None] = {}
    for day in sorted({d for _, d in total}):
        ids = [pid for pid, d in total if d == day]
        try:
            answer = valio.availability(ids, day)["products"] if valio is not None and ids else []
        except Exception:
            answer = []          # no live answer: availability stays unknown, the demand still shows
        for item in answer:
            lines = item.get("scheduleLines") or []
            amount = lines[0].get("availableAmount") if lines else Decimal(0)
            per = _per_sales_unit(docs.get(item["productId"]) or {})
            known = amount is not None and per is not None and not item.get("salesBlock")
            available[(item["productId"], day)] = Decimal(str(amount)) * per if known else None

    rows = []
    for (pid, day), demand in sorted(total.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        have = available.get((pid, day))
        shortage = None if have is None else max(demand - have, Decimal(0))
        risk = "UNKNOWN" if have is None else ("SHORT" if shortage > 0 else "OK")
        rows.append({
            "product_id": pid, "product_name": ((docs.get(pid) or {}).get("names") or {}).get("en"),
            "date": day, "unit": unit[pid], "demand": _q(demand), "kitchens": len(parts[(pid, day)]),
            "by_kitchen": [{"kitchen_id": k, "kitchen_name": names.get(k), "demand": _q(v)}
                           for k, v in sorted(parts[(pid, day)].items(), key=lambda kv: -kv[1])],
            "available": None if have is None else _q(have),
            "shortage": None if shortage is None else _q(shortage), "risk": risk,
            "suggested_buy": None if shortage is None else _q(shortage.to_integral_value(ROUND_CEILING)),
        })
    return {"supplier_id": supplier_id, "from": start.isoformat(), "to": end.isoformat(),
            "kitchens_sharing": len(kitchens), "rows": rows}


def mount_supplier(app, gw, principal) -> None:
    def window(request: Request) -> tuple[date, date]:
        q = request.query_params
        try:
            start, end = date.fromisoformat(q.get("from", "")), date.fromisoformat(q.get("to", ""))
        except ValueError:
            raise GatewayError(422, "INVALID_REQUEST", "from and to (YYYY-MM-DD) are required") from None
        if end < start or end - start > timedelta(days=MAX_DAYS - 1):
            raise GatewayError(422, "INVALID_REQUEST", f"from must be on or before to, at most {MAX_DAYS} days")
        return start, end

    @app.get("/v1/suppliers/{supplier_id}/demand")
    def demand(supplier_id: str, request: Request, who=Depends(principal)):
        who.need("supplier:demand")
        start, end = window(request)
        return supplier_demand(gw().db, gw().valio, supplier_id, start, end, request.query_params.get("product"))

    @app.get("/v1/suppliers/{supplier_id}/demand/shortage-risk")
    def shortage_risk(supplier_id: str, request: Request, who=Depends(principal)):
        who.need("supplier:demand")
        start, end = window(request)
        answer = supplier_demand(gw().db, gw().valio, supplier_id, start, end)
        answer["rows"] = [row for row in answer["rows"] if row["risk"] != "OK"]
        return answer
