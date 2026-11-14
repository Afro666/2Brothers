"""Check a delivered package's allergen label from a photo (#1175, docs/contract.md "Check a
package's allergen label from a photo"). Shown to a person, stored nowhere: the catalog,
the order and the stock never change, and "unknown" in the catalog stays unknown."""
from __future__ import annotations

import os
import time

import httpx
from fastapi import Depends, Request
from jsonschema import ValidationError

from agent.label import compare
from gateway.service import GatewayError
from gateway.stock_photo import MODEL_NAME, STATUS, WORKER_TIMEOUT, _image
from store import orders
from store.products import get_product


def error(code: str) -> GatewayError:
    return GatewayError(STATUS.get(code, 503), code, "The label could not be read; read it yourself")


async def read_label(kitchen_id: str, encoded: str) -> dict:
    url, token = os.environ.get("BUYER_WORKER_URL", ""), os.environ.get("GATEWAY_AGENT_TOKEN", "")
    if not url or not token:
        raise error("VISION_NOT_CONFIGURED")
    try:
        async with httpx.AsyncClient(timeout=WORKER_TIMEOUT, follow_redirects=False, trust_env=False) as client:
            r = await client.post(url.rstrip("/") + "/label-photo",
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


def _in_order(order: dict, product_id: str) -> bool:
    return any(str(line.get("product_id")) == product_id
               for key in ("lines", "items") for line in (order.get(key) or []) if isinstance(line, dict))


def mount_label_photo(app, gw, principal, worker=None) -> None:
    busy: set[str] = set()

    @app.post("/v1/kitchens/{kitchen_id}/orders/{order_id}/label/photo")
    async def label_photo(kitchen_id: str, order_id: str, request: Request, who=Depends(principal)):
        who.need("kitchen:write", kitchen_id)
        encoded, body = await _image(request, with_body=True)
        order = orders.get_order(gw().db, order_id)
        if order is None or order.get("kitchen_id") != kitchen_id:
            raise GatewayError(404, "ORDER_NOT_FOUND", "no such order in this kitchen")
        product_id = body.get("product_id")
        row = get_product(gw().db, product_id) if isinstance(product_id, str) and product_id else None
        if row is None or row.get("kitchen_id") not in (None, kitchen_id):
            raise GatewayError(404, "PRODUCT_NOT_FOUND", "no such product")
        if kitchen_id in busy:
            raise GatewayError(429, "LABEL_PHOTO_BUSY", "a label for this kitchen is being read; wait for it")
        busy.add(kitchen_id)
        started = time.monotonic()
        try:
            raw = await (worker or read_label)(kitchen_id, encoded)
            try:
                answer = compare({k: v for k, v in raw.items() if k != "model"}, row,
                                 gw()._allergen_rule(kitchen_id))
            except (ValidationError, ValueError, TypeError, KeyError, AttributeError):
                raise error("VISION_REPLY_INVALID") from None
            duration = round((time.monotonic() - started) * 1000)
            gw()._audit(kitchen_id, "label_photo_read", who.name, order_id=order_id, product_id=product_id,
                        outcome=answer["outcome"], product_check=answer["product_check"],
                        counts={"excluded_hits": len(answer["excluded_hits"]),
                                "differences": len(answer["differences"]),
                                "please_check": len(answer["please_check"])},
                        model=MODEL_NAME, duration_ms=duration)
            return {"model": MODEL_NAME, "duration_ms": duration, "order_id": order_id, "product_id": product_id,
                    "in_order": _in_order(order, product_id), **answer}
        except GatewayError as exc:
            gw()._audit(kitchen_id, "label_photo_failed", who.name, code=exc.code, order_id=order_id,
                        model=MODEL_NAME, duration_ms=round((time.monotonic() - started) * 1000))
            raise
        finally:
            busy.discard(kitchen_id)
