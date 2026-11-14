"""Read a manual supplier's price list from a photo into draft own products (#1174,
docs/contract.md "Read a supplier's price list from a photo"). Writes nothing: a person
checks each row and saves it with the own-product routes."""
from __future__ import annotations

import os
import time

import httpx
from fastapi import Depends, Request
from jsonschema import ValidationError

from agent.price_list import read_rows
from gateway.service import GatewayError
from gateway.stock_photo import MODEL_NAME, STATUS, WORKER_TIMEOUT, _image
from store.repository import Repository

MANUAL = ("manual", "csv")


def error(code: str) -> GatewayError:
    return GatewayError(STATUS.get(code, 503), code, "The price list could not be read; enter the prices by hand")


async def read_price_list(kitchen_id: str, encoded: str) -> dict:
    url, token = os.environ.get("BUYER_WORKER_URL", ""), os.environ.get("GATEWAY_AGENT_TOKEN", "")
    if not url or not token:
        raise error("VISION_NOT_CONFIGURED")
    try:
        async with httpx.AsyncClient(timeout=WORKER_TIMEOUT, follow_redirects=False, trust_env=False) as client:
            r = await client.post(url.rstrip("/") + "/price-list",
                                  json={"kitchen_id": kitchen_id, "image_base64": encoded},
                                  headers={"Authorization": "Bearer " + token})
        data = r.json()
    except httpx.TimeoutException:
        raise error("VISION_TIMEOUT") from None
    except (httpx.HTTPError, ValueError):
        raise error("VISION_UNAVAILABLE") from None
    if not r.is_success:
        detail = data.get("error") if isinstance(data, dict) else None
        code = detail.get("code") if isinstance(detail, dict) else None
        raise error(code if isinstance(code, str) and code in STATUS else "VISION_UNAVAILABLE")
    return data


def mount_price_list_photo(app, gw, principal, worker=None) -> None:
    busy: set[str] = set()

    @app.post("/v1/kitchens/{kitchen_id}/suppliers/{supplier_id}/price-list/photo")
    async def price_list_photo(kitchen_id: str, supplier_id: str, request: Request, who=Depends(principal)):
        who.need("kitchen:write", kitchen_id)
        repo = Repository(gw().db)
        supplier = repo.suppliers.get(kitchen_id, supplier_id)
        if supplier is None:
            raise GatewayError(404, "SUPPLIER_NOT_FOUND", "no such supplier in this kitchen")
        if supplier.get("adapter") not in MANUAL:
            raise GatewayError(422, "SUPPLIER_HAS_API", "this supplier's prices come from its API, not a price list")
        encoded = await _image(request)
        if kitchen_id in busy:
            raise GatewayError(429, "PRICE_LIST_BUSY", "a price list is already being read for this kitchen")
        busy.add(kitchen_id)
        started = time.monotonic()
        try:
            raw = await (worker or read_price_list)(kitchen_id, encoded)
            try:
                data = {k: v for k, v in raw.items() if k != "model"}
                answer = read_rows(data, supplier_id, repo.own_products.list(kitchen_id, supplier_id))
            except (ValidationError, ValueError, TypeError, KeyError, AttributeError):
                raise error("VISION_REPLY_INVALID") from None
            duration = round((time.monotonic() - started) * 1000)
            gw()._audit(kitchen_id, "price_list_photo_read", who.name, supplier_id=supplier_id,
                        statuses={s: sum(r["status"] == s for r in answer["rows"]) for s in ("READ", "PLEASE_CHECK")},
                        truncated=answer["truncated"], model=MODEL_NAME, duration_ms=duration)
            return {"model": MODEL_NAME, "duration_ms": duration, "supplier_id": supplier_id, **answer}
        except GatewayError as exc:
            gw()._audit(kitchen_id, "price_list_photo_failed", who.name, code=exc.code, model=MODEL_NAME,
                        duration_ms=round((time.monotonic() - started) * 1000))
            raise
        finally:
            busy.discard(kitchen_id)
