"""Check a delivery from a photo of its note (#362):
POST /v1/kitchens/{kitchen_id}/orders/{order_id}/delivery-note/photo.

Built like gateway/stock_photo.py: this route checks who asks, the order and the image,
hands the photo to the Buyer worker's POST /delivery-note (the model key lives there),
and answers the checked lines (docs/contract.md "Check a delivery from a photo of its
note"). It stores nothing but one audit entry, without the image or the note's text.
The call is made once and never retried.
"""
from __future__ import annotations

import os
import time

import httpx
from fastapi import Depends, Request

from gateway.service import GatewayError
from gateway.stock_photo import MODEL_NAME, STATUS as PHOTO_STATUS, WORKER_TIMEOUT, _image
from store import orders

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
                    statuses=counts, complete=answer["complete"], duration_ms=duration_ms)
        return {"model": MODEL_NAME, "duration_ms": duration_ms, "saved": False, "order_id": order_id, **answer}
