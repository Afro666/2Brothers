"""Internal worker endpoint for the delivery-note check (#362): POST /delivery-note.

The gateway's `POST /v1/kitchens/{k}/orders/{order_id}/delivery-note/photo` hands the
photo to this worker, because the model key (VERDA_INFERENCE_KEY) lives here. The reading
and the check are agent/vision.py and agent/receiving.py, unchanged: this file loads the
stored order and the catalog's pack sizes, reads the note once with the live Nemotron
model and answers in the contract's shape (docs/contract.md "Check a delivery from a
photo of its note").

It writes nothing. An unreadable quantity or code stays unknown, never zero.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import hmac
import os
import re

from fastapi import Request

from agent.model import Nemotron
from agent.receiving import INSTRUCTION, NOTE_SCHEMA, match_delivery
from agent.shelf_service import MAX_IMAGE_BYTES, MODEL_NAME, TIMEOUT, _Watched
from agent.usage import emit
from agent.vision import VisionError, image_part, read_image

CODE = re.compile(r"^\d{6}$")


def stored_order(db, kitchen_id: str, order_id: str) -> dict | None:
    """The kitchen's order as `match_delivery` wants its lines; None if not this kitchen's."""
    from store.orders import get_order
    order = get_order(db, order_id)
    if order is None or order.get("kitchen_id") != kitchen_id:
        return None
    return {"lines": [{"product_id": str(ln["product_id"]), "quantity": str(ln["quantity"]),
                       "unit": ln["unit"]} for ln in order.get("lines") or []]}


def catalog_units(db, product_ids) -> dict:
    """Per product its base unit and pack sizes in base units, from the catalog's raw row.
    A product the catalog does not know is left out: its quantity stays unknown."""
    from store.products import get_product
    out = {}
    for pid in dict.fromkeys(product_ids):
        raw = (get_product(db, pid, raw=True) or {}).get("raw") or {}
        if raw.get("baseUnit") and raw.get("units"):
            out[pid] = {"base_unit": raw["baseUnit"],
                        "units": {u["unitId"]: u["sizeInBaseUnits"] for u in raw["units"]}}
    return out


def contract_answer(result: dict) -> dict:
    return {"model": MODEL_NAME,
            "note": {"order_ref": result["order_ref"], "delivery_date": result["delivery_date"]},
            "complete": result["complete"], "lines": result["lines"], "not_ordered": result["not_ordered"]}


class DeliveryNoteReader:
    def __init__(self, db, error, *, model_factory=Nemotron, timeout=TIMEOUT):
        self.db, self.error, self.model_factory, self.timeout = db, error, model_factory, timeout

    async def read(self, kitchen_id: str, order_id: str, image: bytes) -> dict:
        if len(image) > MAX_IMAGE_BYTES:
            raise self.error(413, "IMAGE_TOO_LARGE")
        try:
            image_part(image)
        except VisionError:
            raise self.error(422, "NOT_AN_IMAGE") from None
        order = stored_order(self.db, kitchen_id, order_id)
        if order is None:
            raise self.error(404, "ORDER_NOT_FOUND")
        try:
            model = self.model_factory()
        except ValueError:                          # no VERDA_INFERENCE_KEY in this container
            raise self.error(503, "VISION_NOT_CONFIGURED") from None
        watched = _Watched(model)
        try:
            note = await asyncio.wait_for(read_image(watched, image, INSTRUCTION, NOTE_SCHEMA, "delivery_note"),
                                          timeout=self.timeout)
        except asyncio.TimeoutError:
            raise self.error(504, "VISION_TIMEOUT") from None
        except VisionError:
            if watched.failed:
                raise self.error(503, "VISION_UNAVAILABLE") from None
            raise self.error(502, "VISION_REPLY_INVALID") from None
        finally:
            emit(getattr(model, "meter", None), run="delivery_note")
            await model.close()
        codes = [ln["product_id"] for ln in order["lines"]]
        codes += [ln["product_code"] for ln in note["lines"] if CODE.match(ln["product_code"])]
        order["catalog"] = catalog_units(self.db, codes)
        # An ordered product the catalog lacks: no pack sizes, so its line is UNKNOWN, never a crash.
        for pid in order["lines"]:
            order["catalog"].setdefault(pid["product_id"], {"base_unit": "unknown", "units": {}})
        return contract_answer(match_delivery(order, note))


def mount_delivery_note(app, error, reader=None) -> None:
    """Add POST /delivery-note to the worker app; `reader` is for tests."""
    state = {}

    @app.post("/delivery-note")
    async def delivery_note(request: Request):
        token = os.environ.get("GATEWAY_AGENT_TOKEN", "")
        given = request.headers.get("authorization", "")
        if not token or not hmac.compare_digest(given.encode(), ("Bearer " + token).encode()):
            raise error(401, "UNAUTHENTICATED")
        try:
            body = await request.json()
        except ValueError:
            raise error(422, "INVALID_REQUEST") from None
        if (not isinstance(body, dict) or not isinstance(body.get("image_base64"), str)
                or not isinstance(body.get("order_id"), str) or not body["order_id"]):
            raise error(422, "INVALID_REQUEST")
        kitchen = os.environ.get("GATEWAY_KITCHEN_ID", "demo-kitchen")
        if body.get("kitchen_id") != kitchen:
            raise error(403, "KITCHEN_SCOPE")
        if len(body["image_base64"]) > MAX_IMAGE_BYTES * 4 // 3 + 4:
            raise error(413, "IMAGE_TOO_LARGE")
        try:
            image = base64.b64decode(body["image_base64"], validate=True)
        except (binascii.Error, ValueError):
            raise error(422, "INVALID_REQUEST") from None
        current = reader
        if current is None:
            if not state:
                from store.db import get_db
                state["reader"] = DeliveryNoteReader(get_db(), error)
            current = state["reader"]
        try:
            return await current.read(kitchen, body["order_id"], image)
        except error:
            raise
        except Exception:
            raise error(503, "VISION_UNAVAILABLE") from None
