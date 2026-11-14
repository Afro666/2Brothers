"""Count from a shelf photo (#373): POST /v1/kitchens/{kitchen_id}/stock/photo.

Nemotron 3.5 Super VL reads one photo of a shelf into rows to confirm (docs/contract.md
"Count from a shelf photo"). The model key lives in the Buyer worker's container, so this
route checks who asks and how large the image is, hands it to the worker's POST /shelf
(like gateway/buyer_worker.py), and answers the rows.

It stores no count: the person confirms and the web app calls POST /stock-counts. The
only thing written is one audit entry, without the image. The call is made once and
never retried here.
"""
from __future__ import annotations

import base64
import binascii
import json
import os
import time

import httpx
from fastapi import Depends, Request

from gateway.service import GatewayError

MODEL_NAME = "nemotron-3.5-super-vl"
MAX_BODY_BYTES = 6 * 1024 * 1024
MAX_IMAGE_BYTES = 4 * 1024 * 1024
WORKER_TIMEOUT = 85     # seconds; the worker stops its one vision call at 75
MAGIC = (b"\x89PNG", b"\xff\xd8\xff")
KINDS = ("COUNTED", "PLEASE_COUNT", "UNMATCHED")
MESSAGES = {
    "IMAGE_TOO_LARGE": "the image is larger than 4 MB; make the photo smaller and try again",
    "NOT_AN_IMAGE": "the image must be PNG or JPEG",
    "KITCHEN_SCOPE": "the vision worker serves another kitchen",
    "VISION_NOT_CONFIGURED": "no vision model is configured on this server; count by hand",
    "VISION_UNAVAILABLE": "the vision model could not be reached; nothing was read, count by hand",
    "VISION_REPLY_INVALID": "the vision model answered outside its schema; nothing was read, count by hand",
    "VISION_TIMEOUT": "the vision model did not answer in time; nothing was read, count by hand",
}
STATUS = {"IMAGE_TOO_LARGE": 413, "NOT_AN_IMAGE": 422, "KITCHEN_SCOPE": 403, "VISION_NOT_CONFIGURED": 503,
          "VISION_UNAVAILABLE": 503, "VISION_REPLY_INVALID": 502, "VISION_TIMEOUT": 504}


def _error(code: str) -> GatewayError:
    return GatewayError(STATUS[code], code, MESSAGES[code])


async def read_shelf_photo(kitchen_id: str, image_base64: str) -> dict:
    """One call to the worker's POST /shelf; the worker's answer or a GatewayError."""
    url = os.environ.get("BUYER_WORKER_URL", "")
    token = os.environ.get("GATEWAY_AGENT_TOKEN", "")
    if not url or not token:
        raise _error("VISION_NOT_CONFIGURED")
    try:
        async with httpx.AsyncClient(timeout=WORKER_TIMEOUT, follow_redirects=False, trust_env=False) as client:
            response = await client.post(url.rstrip("/") + "/shelf",
                                         json={"kitchen_id": kitchen_id, "image_base64": image_base64},
                                         headers={"Authorization": "Bearer " + token})
        data = response.json()
    except httpx.TimeoutException:
        raise _error("VISION_TIMEOUT") from None
    except (httpx.HTTPError, ValueError):
        raise _error("VISION_UNAVAILABLE") from None
    if not response.is_success:
        failed = data.get("error", {}) if isinstance(data, dict) else {}
        code = failed.get("code") if isinstance(failed, dict) else None
        # Only the codes of the contract pass; anything else is "could not be reached".
        raise _error(code if isinstance(code, str) and code in STATUS else "VISION_UNAVAILABLE")
    return data


def _rows(data) -> list[dict]:
    """The worker's rows in the contract's shape. Unknown is never a number: a row that
    is not COUNTED leaves here without `packs` and `count`, whatever the worker sent."""
    rows = data.get("rows") if isinstance(data, dict) else None
    if not isinstance(rows, list) or not all(isinstance(r, dict) and r.get("row") in KINDS for r in rows):
        raise _error("VISION_REPLY_INVALID")
    out = []
    for r in rows:
        counted = r["row"] == "COUNTED"
        if counted and not (isinstance(r.get("packs"), int) and isinstance(r.get("count"), str)
                            and isinstance(r.get("product_id"), str)):
            raise _error("VISION_REPLY_INVALID")
        matched = r["row"] != "UNMATCHED"
        out.append({"row": r["row"],
                    "product_id": r.get("product_id") if matched else None,
                    "product_name": r.get("product_name") if matched else None,
                    "label": str(r.get("label") or "")[:120], "confidence": r.get("confidence"),
                    "packs": r["packs"] if counted else None,
                    "pack_size": r.get("pack_size") if matched else None,
                    "count": r["count"] if counted else None,
                    "unit": r.get("unit") if matched else None})
    return out


async def _image(request: Request) -> str:
    """The request's `image_base64`, checked: body and image size, base64, PNG or JPEG."""
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise _error("IMAGE_TOO_LARGE")
    raw = bytearray()
    async for chunk in request.stream():        # never hold more than the limit in memory
        raw.extend(chunk)
        if len(raw) > MAX_BODY_BYTES:
            raise _error("IMAGE_TOO_LARGE")
    try:
        data = json.loads(raw)
    except ValueError:
        raise GatewayError(422, "INVALID_JSON", "body must be a JSON object") from None
    if not isinstance(data, dict):
        raise GatewayError(422, "INVALID_JSON", "body must be a JSON object")
    encoded = data.get("image_base64")
    if not isinstance(encoded, str) or not encoded:
        raise GatewayError(422, "INVALID_REQUEST", "image_base64 is required: the photo as base64")
    try:
        image = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise GatewayError(422, "INVALID_REQUEST", "image_base64 is not base64") from None
    if len(image) > MAX_IMAGE_BYTES:
        raise _error("IMAGE_TOO_LARGE")
    if not image.startswith(MAGIC):
        raise _error("NOT_AN_IMAGE")
    return encoded


def mount_stock_photo(app, gw, principal, shelf_worker=None) -> None:
    # #839: one model read per kitchen at a time. A double tap or a retry loop must not pile
    # up 60-second Nemotron VL calls on the shared credits. One event loop: check-and-add is atomic.
    busy: set[str] = set()

    @app.post("/v1/kitchens/{kitchen_id}/stock/photo")
    async def stock_photo(kitchen_id: str, request: Request, who=Depends(principal)):
        # kitchen:write: a person who is not a viewer, or a kitchen token. Never the Buyer.
        who.need("kitchen:write", kitchen_id)
        encoded = await _image(request)
        if kitchen_id in busy:
            raise GatewayError(429, "STOCK_PHOTO_BUSY", "a shelf photo for this kitchen is being read; wait for it")
        busy.add(kitchen_id)
        started = time.monotonic()
        try:
            rows = _rows(await (shelf_worker or read_shelf_photo)(kitchen_id, encoded))
        except GatewayError as exc:
            gw()._audit(kitchen_id, "stock_photo_failed", who.name, code=exc.code, model=MODEL_NAME,
                        duration_ms=round((time.monotonic() - started) * 1000))
            raise
        finally:
            busy.discard(kitchen_id)
        duration_ms = round((time.monotonic() - started) * 1000)
        # Who, how many rows, how long. Never the image, never the labels the model read.
        gw()._audit(kitchen_id, "stock_photo_read", who.name, model=MODEL_NAME, rows=len(rows),
                    counted=sum(r["row"] == "COUNTED" for r in rows), duration_ms=duration_ms)
        return {"model": MODEL_NAME, "duration_ms": duration_ms, "saved": False, "rows": rows}
