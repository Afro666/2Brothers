"""Check a delivery from a photo of its note (#362, #1304):
POST /v1/kitchens/{kitchen_id}/orders/{order_id}/delivery-note/photo.

Built like gateway/stock_photo.py: this route checks who asks, the order and the image,
hands the photo to the Buyer worker's POST /delivery-note (the model key lives there),
and answers the checked lines (docs/contract.md "Check a delivery from a photo of its
note"). The structured observation is saved durably before `saved: true`; the image and
the note's text are never stored. The call is made once and never retried.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
import os
import time

import httpx
from fastapi import Depends, Request

from gateway.service import GatewayError
from gateway.stock_photo import MODEL_NAME, STATUS as PHOTO_STATUS, WORKER_TIMEOUT, _image
from store import delivery_results, orders

LINE_STATUSES = ("RECEIVED", "SHORT", "MISSING", "UNKNOWN")
OTHER_STATUSES = ("SUBSTITUTE", "EXTRA", "UNREADABLE")
BY_HAND = "nothing was read, check the delivery by hand"
MESSAGES = {
    "IMAGE_TOO_LARGE": "the image is larger than 4 MB; make the photo smaller and try again",
    "NOT_AN_IMAGE": "the image must be PNG or JPEG",
    "KITCHEN_SCOPE": "the vision worker serves another kitchen",
    "ORDER_NOT_FOUND": "no such order in this kitchen",
    "VISION_NOT_CONFIGURED": "no vision model is configured on this server; check the delivery by hand",
    "VISION_UNAVAILABLE": "the vision model could not be reached; " + BY_HAND,
    "VISION_REPLY_INVALID": "the vision model answered outside its schema; " + BY_HAND,
    "VISION_TIMEOUT": "the vision model did not answer in time; " + BY_HAND,
}
STATUS = {**PHOTO_STATUS, "ORDER_NOT_FOUND": 404}


def _error(code: str) -> GatewayError:
    return GatewayError(STATUS[code], code, MESSAGES[code])


async def read_delivery_note(kitchen_id: str, order_id: str, image_base64: str) -> dict:
    """One call to the worker's POST /delivery-note; its answer or a GatewayError."""
    url = os.environ.get("BUYER_WORKER_URL", "")
    token = os.environ.get("GATEWAY_AGENT_TOKEN", "")
    if not url or not token:
        raise _error("VISION_NOT_CONFIGURED")
    try:
        async with httpx.AsyncClient(timeout=WORKER_TIMEOUT, follow_redirects=False, trust_env=False) as client:
            response = await client.post(url.rstrip("/") + "/delivery-note",
                                         json={"kitchen_id": kitchen_id, "order_id": order_id,
                                               "image_base64": image_base64},
                                         headers={"Authorization": "Bearer " + token})
        data = response.json()
    except httpx.TimeoutException:
        raise _error("VISION_TIMEOUT") from None
    except (httpx.HTTPError, ValueError):
        raise _error("VISION_UNAVAILABLE") from None
    if not response.is_success:
        failed = data.get("error", {}) if isinstance(data, dict) else {}
        code = failed.get("code") if isinstance(failed, dict) else None
        raise _error(code if isinstance(code, str) and code in STATUS else "VISION_UNAVAILABLE")
    return data


def _answer(data) -> dict:
    """The worker's answer in the contract's shape, or VISION_REPLY_INVALID."""
    ok = (isinstance(data, dict) and isinstance(data.get("lines"), list)
          and isinstance(data.get("not_ordered"), list) and isinstance(data.get("note"), dict)
          and all(isinstance(ln, dict) and ln.get("status") in LINE_STATUSES for ln in data["lines"])
          and all(isinstance(ln, dict) and ln.get("status") in OTHER_STATUSES for ln in data["not_ordered"]))
    if not ok:
        raise _error("VISION_REPLY_INVALID")
    others = [{**ln, "needs_approval": ln["status"] == "SUBSTITUTE"} for ln in data["not_ordered"]]
    complete = all(ln["status"] == "RECEIVED" for ln in data["lines"]) and not others
    return {"note": {"order_ref": str(data["note"].get("order_ref") or "unknown")[:60],
                     "delivery_date": str(data["note"].get("delivery_date") or "unknown")[:20]},
            "complete": complete, "lines": data["lines"], "not_ordered": others}


CENT = Decimal("0.01")
QTY = Decimal("0.001")
SHORTFALL = ("SHORT", "MISSING")


def _dec(value) -> Decimal | None:
    """A finite Decimal from the stored order or the worker's answer; None when it is not one."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return number if number.is_finite() else None


def _text(x: Decimal) -> str:
    return format(x.quantize(QTY, ROUND_HALF_UP).normalize(), "f")


def _supplier_name(order: dict) -> str | None:
    blocks = order.get("blocks") or []
    if len(blocks) == 1 and isinstance(blocks[0], dict) and isinstance(blocks[0].get("name"), str):
        return blocks[0]["name"] or None
    return None


def _id(value) -> str | None:
    text = None if value is None else str(value).strip()
    return None if not text or text.lower() == "unknown" else text


def _unit(value) -> str | None:
    text = value.strip() if isinstance(value, str) else ""
    return text if text and text.lower() != "unknown" else None


def _supplier_by_product(order: dict) -> dict[str, str]:
    """The order's own supplier split, keyed by product; the model never supplies this."""
    out: dict[str, str] = {}
    for block in order.get("blocks") or []:
        if not isinstance(block, dict) or not block.get("supplier_id"):
            continue
        supplier = _id(block["supplier_id"])
        for product_id in block.get("product_ids") or []:
            out.setdefault(_id(product_id), supplier)
        for line in block.get("lines") or []:
            if isinstance(line, dict) and line.get("product_id") is not None:
                out.setdefault(_id(line["product_id"]), supplier)
    for line in order.get("lines") or []:
        if isinstance(line, dict) and line.get("supplier_id") is not None:
            out.setdefault(_id(line.get("product_id")), _id(line["supplier_id"]))
    return {key: value for key, value in out.items() if key is not None and value is not None}


def _top_supplier(order: dict, by_product: dict[str, str]) -> str | None:
    """The one supplier of the order; only a genuinely mixed order loses the top-level id."""
    suppliers = set(by_product.values())
    for block in order.get("blocks") or []:
        supplier = _id(block.get("supplier_id")) if isinstance(block, dict) else None
        if supplier:
            suppliers.add(supplier)
    supplier = _id(order.get("supplier_id"))
    if supplier:
        suppliers.add(supplier)
    return next(iter(suppliers)) if len(suppliers) == 1 else None


def _requested_date(db, order: dict):
    """The trusted request date: the stored order, its receipt, else its offer."""
    value = order.get("requested_date")
    receipt = order.get("receipt") or {}
    if value is None and isinstance(receipt, dict):
        value = receipt.get("requested_date")
    if value is None and order.get("offer_id"):
        offer = orders.get_offer(db, order["offer_id"]) or {}
        value = (offer.get("request") or {}).get("requested_date")
        if value is None:
            value = offer.get("requested_date")
    return value


def delivery_context(db, order: dict) -> dict:
    """Identity, requested date and order timestamp from stored data, never the model."""
    by_product = _supplier_by_product(order)
    return {"supplier_id": _top_supplier(order, by_product),
            "supplier_by_product": by_product,
            "requested_date": _requested_date(db, order),
            "ordered_at": order.get("ordered_at") or order.get("created_at")}


def observation_lines(order: dict, answer_lines: list, context: dict) -> list[dict]:
    """One observation line per original order product; the order keeps quantity and unit."""
    seen = {}
    for line in answer_lines:
        if isinstance(line, dict) and line.get("product_id") is not None:
            seen.setdefault(_id(line["product_id"]), line)
    out = []
    for stored in order.get("lines") or []:
        if not isinstance(stored, dict):
            continue
        product_id = _id(stored.get("product_id"))
        observed = seen.get(product_id) or {}
        status = observed.get("status") if observed.get("status") in LINE_STATUSES else "UNKNOWN"
        out.append({"supplier_id": context["supplier_by_product"].get(product_id,
                                                                     context["supplier_id"]),
                    "product_id": product_id, "status": status,
                    "ordered": stored.get("quantity"),
                    "delivered": _delivered(observed, stored),
                    "unit": _unit(stored.get("unit"))})
    return out


def _delivered(observed: dict, stored: dict):
    """The worker's base quantity in the order's unit; null when that conversion is unknown."""
    if observed.get("status") == "UNKNOWN":
        return None
    received = _dec(observed.get("received"))
    unit, base = _unit(stored.get("unit")), _unit(observed.get("base_unit"))
    if received is None:
        return None
    if isinstance(unit, str) and unit and base == unit:
        return received
    ordered, wanted = _dec(observed.get("ordered")), _dec(stored.get("quantity"))
    if ordered is None or ordered <= 0 or wanted is None or not isinstance(unit, str) or not unit:
        return None
    return _text(received * wanted / ordered)


def manual_lines(order: dict, context: dict) -> list[dict]:
    """One tap means every known ordered quantity arrived; unknown stays unknown."""
    out = []
    for stored in order.get("lines") or []:
        if not isinstance(stored, dict):
            continue
        product_id = _id(stored.get("product_id"))
        quantity, unit = _dec(stored.get("quantity")), _unit(stored.get("unit"))
        known = quantity is not None and unit is not None
        out.append({"supplier_id": context["supplier_by_product"].get(product_id,
                                                                     context["supplier_id"]),
                    "product_id": product_id,
                    "status": "RECEIVED" if known else "UNKNOWN",
                    "ordered": stored.get("quantity"),
                    "delivered": stored.get("quantity") if known else None,
                    "unit": unit if known else None})
    return out


def not_ordered_lines(answer_lines: list, context: dict) -> list[dict]:
    """Only the observed exception fields; lots and best-before text stay transient."""
    out = []
    for line in answer_lines:
        if not isinstance(line, dict) or line.get("status") not in OTHER_STATUSES:
            continue
        product_id = _id(line.get("product_id"))
        out.append({"supplier_id": context["supplier_by_product"].get(product_id,
                                                                     context["supplier_id"]),
                    "product_id": product_id, "status": line["status"],
                    "delivered": line.get("received"),
                    "unit": _unit(line.get("base_unit")) or _unit(line.get("unit"))})
    return out


def claim(order: dict, lines: list) -> tuple[list, dict]:
    """The value of every short or missing line at the stored order's own price, and one
    total (#1198, docs/contract.md). Plain code: the model gives no price and no value.
    The worker answers one line per order line, in the order's order; a line whose product
    is not the stored line's gets no price."""
    stored = order.get("lines") or []
    out, total, qty, units = [], Decimal(0), Decimal(0), set()
    counted = not_valued = 0
    qty_known = True
    for i, ln in enumerate(lines):
        row = stored[i] if i < len(stored) and isinstance(stored[i], dict) else {}
        if str(row.get("product_id")) != str(ln.get("product_id")):
            row = {}
        order_qty, price, unit = _dec(row.get("quantity")), _dec(row.get("unit_price")), row.get("unit")
        ordered, missing = _dec(ln.get("ordered")), _dec(ln.get("missing"))
        in_order_unit = (missing * order_qty / ordered
                         if missing is not None and order_qty is not None and ordered and ordered > 0 else None)
        value = None
        if ln["status"] == "RECEIVED":
            value = Decimal("0.00")
        elif ln["status"] in SHORTFALL and in_order_unit is not None and price is not None:
            value = (in_order_unit * price).quantize(CENT, ROUND_HALF_UP)
        if ln["status"] in SHORTFALL:
            counted += 1
            if value is None:
                not_valued += 1
            else:
                total += value
            if in_order_unit is None or not unit:
                qty_known = False
            else:
                qty += in_order_unit
                units.add(unit)
        elif ln["status"] == "UNKNOWN":
            not_valued += 1
        out.append({**ln, "order_quantity": None if order_qty is None else _text(order_qty),
                    "order_unit": unit if isinstance(unit, str) and unit else None,
                    "missing_order_qty": None if in_order_unit is None else _text(in_order_unit),
                    "unit_price": None if price is None else f"{price:f}",     # as stored: the value uses it
                    "claim_eur": None if value is None else f"{value:f}"})
    one_unit = counted > 0 and qty_known and len(units) == 1
    return out, {"currency": "EUR", "total_eur": f"{total.quantize(CENT, ROUND_HALF_UP):f}", "lines": counted,
                 "quantity": _text(qty) if one_unit else None, "unit": next(iter(units)) if one_unit else None,
                 "not_valued": not_valued, "supplier_name": _supplier_name(order)}


def mount_delivery_note(app, gw, principal, worker=None) -> None:
    busy: set[str] = set()      # one model read per kitchen at a time, like the shelf photo (#839)

    @app.post("/v1/kitchens/{kitchen_id}/orders/{order_id}/delivery-note/photo")
    async def delivery_note_photo(kitchen_id: str, order_id: str, request: Request, who=Depends(principal)):
        # kitchen:write: a person who is not a viewer, or a kitchen token. Never the Buyer.
        who.need("kitchen:write", kitchen_id)
        encoded = await _image(request)
        order = orders.get_order(gw().db, order_id)
        if order is None or order.get("kitchen_id") != kitchen_id:
            raise _error("ORDER_NOT_FOUND")
        if kitchen_id in busy:
            raise GatewayError(429, "DELIVERY_NOTE_BUSY", "a delivery note for this kitchen is being read; wait for it")
        busy.add(kitchen_id)
        started = time.monotonic()
        try:
            answer = _answer(await (worker or read_delivery_note)(kitchen_id, order_id, encoded))
        except GatewayError as exc:
            gw()._audit(kitchen_id, "delivery_note_failed", who.name, code=exc.code, order_id=order_id,
                        model=MODEL_NAME, duration_ms=round((time.monotonic() - started) * 1000))
            raise
        finally:
            busy.discard(kitchen_id)
        duration_ms = round((time.monotonic() - started) * 1000)
        counts: dict[str, int] = {}
        for ln in [*answer["lines"], *answer["not_ordered"]]:
            counts[ln["status"]] = counts.get(ln["status"], 0) + 1
        # Who, which order, how many lines per status, how long. Never the image or the note's text.
        gw()._audit(kitchen_id, "delivery_note_read", who.name, order_id=order_id, model=MODEL_NAME,
                    statuses=counts, complete=answer["complete"],
                    needs_approval=sum(1 for ln in answer["not_ordered"] if ln["needs_approval"]),
                    duration_ms=duration_ms)
        lines, total = claim(order, answer["lines"])
        context = delivery_context(gw().db, order)
        try:
            result = delivery_results.save_observation(
                gw().db, kitchen_id=kitchen_id, order_id=order_id,
                supplier_id=context["supplier_id"], requested_date=context["requested_date"],
                ordered_at=context["ordered_at"], delivery_date=answer["note"]["delivery_date"],
                checked_by=who.name, checked_at=gw().now(), source="photo",
                lines=observation_lines(order, answer["lines"], context),
                not_ordered=not_ordered_lines(answer["not_ordered"], context))
        except ValueError as exc:
            raise GatewayError(422, "INVALID_REQUEST", str(exc)[:200]) from None
        saved_counts: dict[str, int] = {}
        for ln in [*result["lines"], *result["not_ordered"]]:
            saved_counts[ln["status"]] = saved_counts.get(ln["status"], 0) + 1
        gw()._audit(kitchen_id, "delivery_result_saved", who.name, order_id=order_id,
                    result_id=result["result_id"], revision=result["revision"],
                    statuses=saved_counts)
        return {"model": MODEL_NAME, "duration_ms": duration_ms, "saved": True, "order_id": order_id,
                **answer, "lines": lines, "claim": total}
