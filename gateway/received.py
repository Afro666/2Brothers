"""One-tap delivery confirmation (#1304).

POST /v1/kitchens/{kitchen_id}/orders/{order_id}/received is a person's own observation:
the whole order arrived on a local calendar day. It writes a delivery result only; the
supplier-side order status and stock stay exactly as they were.
"""

from __future__ import annotations

from datetime import date
from zoneinfo import ZoneInfo

from fastapi import Depends, Request
from starlette.concurrency import run_in_threadpool

from gateway.delivery_note import delivery_context, manual_lines
from gateway.service import GatewayError
from store import delivery_results, orders

HELSINKI = ZoneInfo("Europe/Helsinki")
PLACED_STATUSES = ("SENT", "CONFIRMED", "PARTIAL")
FIELDS = {"idempotency_key", "delivery_date", "complete"}


def _error(status: int, code: str, message: str) -> GatewayError:
    return GatewayError(status, code, message)


def _person(who, kitchen_id: str) -> str:
    """A chef or approver in a signed-in human session; never a token or a viewer."""
    who.need("kitchen:write", kitchen_id)
    if who.kind != "human":
        raise _error(403, "HUMAN_SESSION_REQUIRED",
                     "only a human chef or approver can confirm a delivery")
    if who.role not in ("chef", "approver"):
        raise _error(403, "ROLE_REQUIRED", "only a chef or approver can confirm a delivery")
    return who.name


def _delivery_date(data: dict, today: date) -> str:
    value = data.get("delivery_date")
    if not isinstance(value, str):
        raise _error(422, "INVALID_REQUEST", "delivery_date must be YYYY-MM-DD")
    try:
        day = date.fromisoformat(value)
    except ValueError:
        raise _error(422, "INVALID_REQUEST", "delivery_date must be YYYY-MM-DD") from None
    if day > today:
        raise _error(422, "INVALID_REQUEST", "delivery_date cannot be in the future")
    return day.isoformat()


def _statuses(result: dict) -> dict[str, int]:
    counts: dict[str, int] = {}
    for line in result["lines"]:
        counts[line["status"]] = counts.get(line["status"], 0) + 1
    return counts


def mount_received(app, gw, principal, body) -> None:
    @app.post("/v1/kitchens/{kitchen_id}/orders/{order_id}/received")
    async def received(kitchen_id: str, order_id: str, request: Request,
                       who=Depends(principal)):
        person = _person(who, kitchen_id)
        data = await body(request)
        if set(data) != FIELDS or data.get("complete") is not True:
            raise _error(422, "INVALID_REQUEST",
                         "exactly idempotency_key, delivery_date and complete:true are required")
        key = data.get("idempotency_key")
        if not isinstance(key, str) or not key.strip():
            raise _error(422, "INVALID_REQUEST", "idempotency_key must be a nonempty string")
        today = gw().now().astimezone(HELSINKI).date()
        day = _delivery_date(data, today)
        order = orders.get_order(gw().db, order_id)
        if order is None or order.get("kitchen_id") != kitchen_id:
            raise _error(404, "ORDER_NOT_FOUND", "no such order in this kitchen")
        if order.get("outcome") != "CONFIRMED" or order.get("status") not in PLACED_STATUSES:
            raise _error(409, "NOT_PENDING", "this order was not placed successfully")
        context = delivery_context(gw().db, order)
        try:
            # save_received may wait for a pending same-key save (time.sleep): keep it off
            # the event loop so other requests do not stall.
            result, created = await run_in_threadpool(
                delivery_results.save_received, gw().db, kitchen_id=kitchen_id, order_id=order_id, idempotency_key=key,
                delivery_date=day, supplier_id=context["supplier_id"],
                requested_date=context["requested_date"], ordered_at=context["ordered_at"],
                checked_by=person, checked_at=gw().now(),
                lines=manual_lines(order, context))
        except delivery_results.IdempotencyConflict:
            raise _error(409, "IDEMPOTENCY_KEY_REUSED",
                         "this idempotency_key was used for another delivery") from None
        if created:
            gw()._audit(kitchen_id, "delivery_result_saved", person, order_id=order_id,
                        result_id=result["result_id"], revision=result["revision"],
                        statuses=_statuses(result))
        return {"saved": True, "order_id": order_id, "result": result}
