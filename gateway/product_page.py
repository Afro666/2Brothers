"""One product's page (#1603): GET /v1/kitchens/{kitchen_id}/catalog/products/{product_id}.

Contract: docs/contract.md, "Product page". Read only. Every part names its source. Unknown
stays unknown: an allergen list of a product without allergen data is not "free from", a
missing nutrition table is null, Valio's 999999 stock is `unknown`, and a Valio error never
fails the page (`live.error`). The live price and stock come from the same Valio client the
Buyer uses, so its cache and rate limit apply.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi import Depends, FastAPI

from engine.nutrition import per_100
from gateway.service import GatewayError
from gateway.suppliers import KITCHEN_TZ, VALIO, vat_rate
from gateway.valio_client import ValioBusy
from store import demo_delivery
from store.products import get_product, get_products
from store.search import ALLERGENS

log = logging.getLogger(__name__)

CATALOG = "Valio product data"
LIVE = "Valio price and availability API"
LANGUAGES = ("en", "fi", "sv")
ORDERS_SHOWN = 5
DEMAND_DAYS = 14
# A name for every GS1 code, not only the first of its group (review of #1625): the group's first
# code is the group itself; the others say which grain or nut, with the group in brackets.
_SPECIFIC = {"UW": "wheat (gluten)", "NR": "rye (gluten)", "GB": "barley (gluten)",
             "GS": "spelt (gluten)", "GK": "kamut (gluten)", "SA": "almond (nuts)",
             "SC": "cashew (nuts)", "SH": "hazelnut (nuts)", "SM": "macadamia (nuts)",
             "SP": "pecan (nuts)", "SR": "Brazil nut (nuts)", "ST": "pistachio (nuts)",
             "SW": "walnut (nuts)"}
ALLERGEN_NAMES = {**{code: name for name, codes in ALLERGENS.items() for code in codes},
                  **{codes[0]: name for name, codes in ALLERGENS.items()}, **_SPECIFIC}


def _num(value) -> str | None:
    """A number from the data as a decimal string; None stays None."""
    if value is None:
        return None
    if hasattr(value, "to_decimal"):
        value = value.to_decimal()
    return f"{Decimal(str(value)).normalize():f}"


def _plain(value):
    """A stored row as JSON can carry it: a Decimal128 (an own product's price) is a decimal string."""
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if hasattr(value, "to_decimal") or isinstance(value, Decimal):
        return _num(value)
    return value


def _texts(items) -> dict | None:
    """[{value, language}] -> {en, fi, sv} (the ones present); None when there are none."""
    out = {i["language"]: i["value"].strip() for i in items or []
           if isinstance(i, dict) and i.get("language") in LANGUAGES and (i.get("value") or "").strip()}
    return out or None


def _about(raw: dict | None) -> dict | None:
    if not raw:
        return None
    synkka = raw.get("synkkaData") or {}
    ingredients = [names for names in (_texts(i.get("names")) for i in synkka.get("ingredients") or [])
                   if names]
    producers = [p.get("name") for p in synkka.get("producers") or [] if p.get("name")]
    return {"marketing_text": _texts(synkka.get("marketingTexts")),
            "key_ingredients": _texts(synkka.get("keyIngredients")),
            "ingredients": ingredients,
            "storage_instructions": _texts(synkka.get("storageInstructions")),
            "preparation_instructions": _texts(synkka.get("preparationInstructions")),
            "usage_instructions": _texts(synkka.get("usageInstructions")),
            "producer": producers[0] if producers else None,
            "source": CATALOG}


def _allergens(row: dict) -> dict:
    """The row's allergen data (store/products.py `flatten`) with a name per known code."""
    data = row.get("allergens") or {}

    def named(codes):
        return [{"code": code, "name": ALLERGEN_NAMES.get(code)} for code in codes or []]

    own = row.get("source") == "own"
    return {"known": row.get("allergen_data_known") is True,
            "contains": named(data.get("contains")), "may_contain": named(data.get("may_contain")),
            "free_from": named(row.get("free_from")), "undeclared": named(data.get("undeclared")),
            "no_declarable_allergens": row.get("no_declarable_allergens") is True,
            "source": "entered by the kitchen" if own else f"{CATALOG}, allergen classification"}


def _nutrition(raw: dict | None) -> dict | None:
    label = per_100(raw)
    if label is None:
        return None
    basis = label.pop("basis")
    return {"basis": basis, "per": "100", "values": {k: _num(v.quantize(Decimal("0.1"))) for k, v in label.items()},
            "source": f"{CATALOG}, nutritionalContent"}


def _units(row: dict) -> dict:
    return {"sales_unit": row.get("sales_unit"), "base_unit": row.get("base_unit"), "lot_size": row.get("lot_size"),
            "units": row.get("units") or [], "net_content": row.get("net_content"),
            "net_content_source": row.get("net_content_source"),
            "source": "entered by the kitchen" if row.get("source") == "own" else CATALOG}


def _unknown_live(day: date, error: str) -> dict:
    return {"date": day.isoformat(), "price_ex_vat": None, "price_incl_vat": None, "per": None,
            "tax_rate": None, "comparison_price": None, "comparison_unit": None, "stock": None,
            "error": error, "source": LIVE}


def _live(gw, row: dict, day: date) -> dict:
    """The live price and stock for `day`, as the Buyer reads them. Never raises."""
    pid = row["product_id"]
    try:
        price = next((p for p in gw.valio.price([pid], day.isoformat())["products"]
                      if p.get("productId") == pid), {})
        stock = next((p for p in gw.valio.availability([pid], day.isoformat())["products"]
                      if p.get("productId") == pid), {})
    except ValioBusy:
        return _unknown_live(day, "SUPPLIER_BUSY")
    except Exception as exc:  # never the message: it can carry upstream text
        log.warning("product page: Valio read failed: %s", type(exc).__name__)
        return _unknown_live(day, "VALIO_UNAVAILABLE")
    priced = not price.get("error") and (price.get("catalogPrice") or {}).get("value") is not None
    rate, _ = vat_rate(price, row) if priced else (None, None)
    lines = stock.get("scheduleLines") or []
    first = lines[0] if lines else {}
    unknown = bool(first.get("unknown_stock"))
    return {
        "date": day.isoformat(),
        "price_ex_vat": _num((price.get("catalogPrice") or {}).get("value")) if priced else None,
        "price_incl_vat": _num((price.get("priceWithTax") or {}).get("value")
                               or (price.get("catalogPrice") or {}).get("valueWithTax")) if priced else None,
        "per": row.get("sales_unit") if priced else None,
        "tax_rate": _num(rate),
        "comparison_price": _num((price.get("comparisonPrice") or {}).get("value")) if priced else None,
        "comparison_unit": price.get("comparisonUnit") if priced else None,
        # Valio (14 Nov): 999999 or more is unknown; no schedule line is not available.
        "stock": {"available": None if unknown else _num(first.get("availableAmount", 0)),
                  "unknown": unknown, "available_date": first.get("availableDate"),
                  "orderable": bool(first.get("orderable")), "cutoff_passed": stock.get("cutoff_passed"),
                  "closing_time": stock.get("closingTime")},
        "error": None, "source": LIVE,
    }


def _recall(db, kitchen_id: str, pid: str) -> dict:
    alerts = [{"event_id": a["_id"], "match": a.get("match"), "status": a.get("status", "active"),
               "title": (a.get("recall") or {}).get("title"), "detected_at": a.get("detected_at")}
              for a in db.recall_alerts.find({"kitchen_id": kitchen_id, "product_id": pid})]
    held = any(a["status"] != "dismissed" and a["match"] in ("exact", "possible") for a in alerts)
    return {"status": "BLOCKED_BY_RECALL" if held else "CLEAR", "alerts": alerts,
            "source": "this kitchen's recall alerts"}


def _per_measure(entry: dict) -> Decimal | None:
    content, price = entry.get("net_content") or {}, entry.get("price_ex_vat")
    if price is None or not content.get("value"):
        return None
    return Decimal(price) / Decimal(str(content["value"]))


def _supplier_entry(supplier: dict | None, supplier_id: str, product: dict, price, per, price_source,
                    rate, stock_known: bool, demo: dict) -> dict:
    supplier = supplier or {}
    terms = supplier.get("terms") or {}
    pid = product["product_id"]
    own_demo, supplier_demo = (demo.get("products") or {}).get(pid) or {}, demo.get("supplier") or {}
    lead, lead_source = next(((v, s) for v, s in ((own_demo.get("lead_time_days"), "demo"),
                                                  (terms.get("lead_time_days"), "supplier_terms"),
                                                  (supplier_demo.get("lead_time_days"), "demo"))
                              if v is not None), (None, None))
    return {"supplier_id": supplier_id,
            "name": supplier.get("name") or ("Valio Aimo" if supplier_id == VALIO else supplier_id),
            "adapter": supplier.get("adapter") or ("valio_api" if supplier_id == VALIO else None),
            "product_id": pid, "product_name": (product.get("names") or {}).get("en"),
            "price_ex_vat": price, "per": per, "price_source": price_source, "vat_rate": rate,
            "stock_known": stock_known, "net_content": product.get("net_content"),
            "lead_time_days": None if lead is None else int(Decimal(_num(lead))), "lead_time_source": lead_source,
            "order_days": terms.get("order_days") or supplier_demo.get("order_days"),
            "cutoff_time": terms.get("cutoff_time") or supplier_demo.get("cutoff_time"),
            "free_delivery_threshold_eur": _num(terms.get("free_delivery_threshold_eur")),
            "delivery_fee_eur": _num(terms.get("delivery_fee_eur")),
            "terms_source": "supplier_terms" if terms else None}


def _suppliers(gw, kitchen_id: str, row: dict, live: dict | None, day: date) -> list[dict]:
    """Valio (for a catalog product) first, then the own products that are the same product,
    cheapest per litre or kilo first; unknown prices last."""
    db = gw.db
    anchor = row["product_id"] if row.get("source") != "own" else row.get("catalog_product_id")
    owns = list(db.products.find({"source": "own", "kitchen_id": kitchen_id,
                                  "$or": [{"_id": row["product_id"]}, *([{"catalog_product_id": anchor}] if anchor else [])]},
                                 {"raw": 0, "embedding": 0}))
    owns = [_plain({**own, "product_id": own.pop("_id")}) for own in owns]
    rows = {s.get("supplier_id"): s for s in db.suppliers.find({"kitchen_id": kitchen_id})}
    valio_row = next((s for s in rows.values() if s.get("adapter") == "valio_api"), None)
    out = []
    catalog = row if row.get("source") != "own" else (get_products(db, [anchor], kitchen_id) or [None])[0] if anchor else None
    if catalog is not None and catalog.get("source") != "own":
        if live is None or row.get("source") == "own":
            live = _live(gw, catalog, day)
        stock = live.get("stock") or {}
        out.append(_supplier_entry(valio_row, VALIO, catalog, live.get("price_ex_vat"), live.get("per"),
                                   "Valio price API" if live.get("price_ex_vat") else None,
                                   live.get("tax_rate") or catalog.get("vat_rate"),
                                   bool(stock) and not stock.get("unknown"),
                                   demo_delivery.lookup(db, kitchen_id, VALIO, [catalog["product_id"]])))
    others = []
    for own in owns:
        sid = own.get("supplier_id")
        others.append(_supplier_entry(rows.get(sid), sid, own, _num(own.get("unit_price_eur")), own.get("sales_unit"),
                                      own.get("price_source") or "entered", own.get("vat_rate"), False,
                                      demo_delivery.lookup(db, kitchen_id, sid, [own["product_id"]])))
    others.sort(key=lambda e: (_per_measure(e) is None, _per_measure(e) or Decimal(0), e["supplier_id"]))
    if row.get("source") == "own":       # an own product's page: its own supplier first
        others.sort(key=lambda e: e["product_id"] != row["product_id"])
        return others[:1] + out + others[1:]
    return out + others


def _line(lines, pid):
    return next((ln for ln in lines or [] if str(ln.get("product_id")) == pid), None)


def _when(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


def _kitchen(gw, kitchen_id: str, pid: str, today: date) -> dict:
    db = gw.db
    placed = []
    for order in db.orders.find({"kitchen_id": kitchen_id, "lines.product_id": pid}).sort(
            "created_at", -1).limit(ORDERS_SHOWN):
        line = _line(order.get("lines"), pid) or {}
        placed.append({"order_id": order["_id"], "created_at": _when(order.get("created_at")),
                       "quantity": line.get("quantity"), "unit": line.get("unit"), "total": line.get("total"),
                       "status": order.get("status"), "outcome": order.get("outcome")})
    ready = {p["offer_id"]: p for p in db.proposals.find({"kitchen_id": kitchen_id, "status": "READY"},
                                                         {"offer_id": 1, "created_at": 1})
             .sort("created_at", -1).limit(200)}     # the newest 200, never a random 200 (#1632)
    waiting = []
    for offer in db.offers.find({"_id": {"$in": list(ready)}, "simulation.lines.product_id": pid},
                                {"simulation.lines": 1}) if ready else []:
        line, proposal = _line(offer["simulation"]["lines"], pid) or {}, ready[offer["_id"]]
        waiting.append({"proposal_id": proposal["_id"], "created_at": _when(proposal.get("created_at")),
                        "quantity": line.get("quantity"), "unit": line.get("unit"), "total": line.get("total")})
    waiting.sort(key=lambda w: str(w["created_at"] or ""), reverse=True)
    waiting = waiting[:ORDERS_SHOWN]
    count = next(iter(db.kitchen_stock.find({"meta.kitchen_id": kitchen_id, "meta.product_id": pid})
                      .sort("ts", -1).limit(1)), None)
    stock = None if count is None else {"on_hand": _num(count.get("on_hand")), "unit": count.get("unit"),
                                        "counted_at": _when(count.get("ts"))}
    recipes = []
    for recipe in db.recipes.find({"kitchen_id": kitchen_id, "ingredients.product_id": pid}):
        item = _line(recipe.get("ingredients"), pid) or {}
        recipes.append({"recipe_id": recipe.get("recipe_id") or recipe.get("_id"), "name": recipe.get("name"),
                        "qty_per_portion": _num(item.get("qty_per_portion")), "unit": item.get("unit")})
    return {"orders": placed, "proposals_waiting": waiting, "stock": stock, "recipes": recipes,
            "demand": _demand(gw, kitchen_id, pid, today)}


def _demand(gw, kitchen_id: str, pid: str, today: date) -> dict | None:
    from gateway.kitchen_routes import demand_rows
    end = today + timedelta(days=DEMAND_DAYS - 1)
    try:
        rows, _ = demand_rows(gw.db, kitchen_id, today, end, today, tz=KITCHEN_TZ)
    except Exception as exc:   # a demand problem never fails the page
        log.warning("product page: demand failed: %s", type(exc).__name__)
        return None
    mine = [r for r in rows if r.get("product_id") == pid and r.get("gross_need") is not None]
    if not mine:
        return None
    units = {r.get("unit") for r in mine}
    return {"from": today.isoformat(), "to": end.isoformat(), "unit": units.pop() if len(units) == 1 else None,
            "gross_need": _num(sum((Decimal(str(r["gross_need"])) for r in mine), Decimal(0))) if len(units) <= 1 else None,
            "days": len({r["date"] for r in mine}), "source": "menu plan and forecast"}


# The row's `vat_source` is a code (#1609); the page's `vat.source` is a label like its other sources.
_VAT_LABELS = {"catalog": f"{CATALOG}, vatCode", "entered": "entered by the kitchen",
               f"{CATALOG}, vatCode": f"{CATALOG}, vatCode"}   # a row not yet rewritten by store.vat


def _vat(row: dict) -> dict:
    rate = row.get("vat_rate")
    label = _VAT_LABELS.get(row.get("vat_source")) if rate is not None else None
    return {"code": row.get("vat_code"), "rate": rate, "source": label}


def product_page(gw, kitchen_id: str, product_id: str, day: date | None = None) -> dict:
    rows = get_products(gw.db, [product_id], kitchen_id)
    if not rows:
        raise GatewayError(404, "PRODUCT_NOT_FOUND", "no such product in the catalogs or this kitchen's products")
    row = _plain(rows[0])
    own = row.get("source") == "own"
    today = gw.now().astimezone(KITCHEN_TZ).date()
    day = day or today + timedelta(days=1)
    raw = None if own else (get_product(gw.db, row["product_id"], raw=True) or {}).get("raw")
    live = None if own else _live(gw, row, day)
    return {
        "product_id": row["product_id"],
        "product": row,
        "about": _about(raw),
        "allergens": _allergens(row),
        "nutrition": _nutrition(raw),
        "storage": {"temperature": row.get("temperature"), "min_temperature_c": row.get("min_temperature_c"),
                    "max_temperature_c": row.get("max_temperature_c"),
                    "source": None if own else CATALOG},
        "origin": {"country": row.get("country"), "source": None if own else f"{CATALOG}, countryOfOrigin"},
        "vat": _vat(row),
        "units": _units(row),
        "live": live,
        "recall": _recall(gw.db, kitchen_id, row["product_id"]),
        "suppliers": _suppliers(gw, kitchen_id, row, live, day),
        "kitchen": _kitchen(gw, kitchen_id, row["product_id"], today),
    }


def mount_product_page(app: FastAPI, gw, principal) -> None:
    @app.get("/v1/kitchens/{kitchen_id}/catalog/products/{product_id}")
    def get_product_page(kitchen_id: str, product_id: str, date: str | None = None, who=Depends(principal)):
        who.need("kitchen:read", kitchen_id)
        try:
            day = datetime.strptime(date, "%Y-%m-%d").date() if date else None
        except ValueError:
            raise GatewayError(422, "INVALID_REQUEST", "date must be YYYY-MM-DD") from None
        return product_page(gw(), kitchen_id, product_id, day)
