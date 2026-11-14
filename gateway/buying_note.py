"""A buying note for the supplier's planner (#1176, docs/contract.md "Buying note for the
supplier's planner").

Plain code picks the shortage rows; Nemotron (in the worker, which holds the key) writes one
line per row; plain code checks every number of every line against its own row before the
note is shown. One failed line drops the whole note, and the page shows the table only.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP
import hashlib
import json
import os
import time

import httpx
from fastapi import Depends, Request
from jsonschema import ValidationError, validate
from starlette.concurrency import run_in_threadpool

from agent.buying_note import LANGUAGES, MAX_ROWS, SCHEMA
from gateway.claim_check import check_sentence, numbers_in, strip_names as _strip, value
from gateway.service import GatewayError
from gateway.stock_photo import MODEL_NAME
from gateway.supplier_routes import shortage_rows, window

CACHE_SECONDS = 300
DROPPED_CACHE_SECONDS = 30
WORKER_TIMEOUT = 35       # seconds; the worker stops its one call at 30
STATUS = {"BUYING_NOTE_UNAVAILABLE": 503, "BUYING_NOTE_TIMEOUT": 504, "REPLY_INVALID": 502}
MODEL_FIELDS = ("product_id", "product_name", "date", "unit", "demand", "kitchens", "available",
                "shortage", "suggested_buy", "risk")
VALUES = ("demand", "available", "shortage", "suggested_buy", "kitchens")


def presentation_row(row: dict) -> dict:
    """Round note facts only; the worker and checker receive this same copy."""
    out = {k: row.get(k) for k in MODEL_FIELDS}
    quantum = {"PCS": "1", "ST": "1", "KG": "0.1", "L": "0.1"}.get(row.get("unit"))
    if quantum is not None:
        for key in ("demand", "available", "shortage", "suggested_buy"):
            if out[key] is not None:
                amount = Decimal(out[key])
                # A real gap is never shown as 0: shortage and buy round up to the unit quantum.
                up = key in ("shortage", "suggested_buy") and amount > 0
                rounded = amount.quantize(Decimal(quantum), rounding=ROUND_CEILING if up else ROUND_HALF_UP)
                text = format(rounded, "f") if rounded else "0"
                out[key] = text.rstrip("0").rstrip(".") if "." in text else text
    return out


def error(code: str) -> GatewayError:
    return GatewayError(STATUS.get(code, 503), code if code in STATUS else "BUYING_NOTE_UNAVAILABLE",
                        "The buying note could not be written; the table below is complete")


def pick(rows: list[dict]) -> list[dict]:
    """SHORT rows by the largest shortage, then UNKNOWN rows by the largest demand; at most 8.
    The model sees only the documented fields: never by_kitchen or a kitchen name."""
    short = sorted((r for r in rows if r["risk"] == "SHORT"),
                   key=lambda r: (-Decimal(r["shortage"]), r["date"], r["product_id"]))
    unknown = sorted((r for r in rows if r["risk"] == "UNKNOWN"),
                     key=lambda r: (-Decimal(r["demand"]), r["date"], r["product_id"]))
    return [{"row": i, **presentation_row(r)}
            for i, r in enumerate((short + unknown)[:MAX_ROWS])]


def check(reply, rows: list[dict], lang: str) -> tuple[list[dict] | None, str | None]:
    """(note, None) when every line passes, else (None, the first rule that failed)."""
    try:
        validate({k: v for k, v in reply.items() if k != "model"}, SCHEMA)
    except (ValidationError, AttributeError):
        return None, "REPLY_INVALID"
    note, used = [], set()
    for line in reply["lines"]:
        if line["row"] >= len(rows):
            return None, "ROW_UNKNOWN"
        row = rows[line["row"]]
        if line["product_id"] != row["product_id"]:
            return None, "PRODUCT_MISMATCH"
        if line["row"] in used:
            return None, "ROW_REPEATED"
        used.add(line["row"])
        name = [row.get("product_name") or ""]
        if row["risk"] == "UNKNOWN":
            # Unknown availability is never a gap: only the kitchen count may be written.
            allowed = [row["kitchens"]]
            demand = value(row["demand"])
            if demand != value(row["kitchens"]) and demand in numbers_in(_strip(line["text"], name), lang):
                return None, "GAP_FOR_UNKNOWN"
        else:
            allowed = [row[k] for k in VALUES]
        failed = check_sentence(line["text"], line["numbers"], allowed, lang, strip=name)
        if failed:
            return None, failed
        note.append({"product_id": row["product_id"], "product_name": row.get("product_name"),
                     "date": row["date"], "risk": row["risk"], "text": line["text"].strip()})
    return note, None


async def write_note(supplier_id: str, lang: str, rows: list[dict]) -> dict:
    url, token = os.environ.get("BUYER_WORKER_URL", ""), os.environ.get("GATEWAY_AGENT_TOKEN", "")
    if not url or not token:
        raise error("BUYING_NOTE_UNAVAILABLE")
    try:
        async with httpx.AsyncClient(timeout=WORKER_TIMEOUT, follow_redirects=False, trust_env=False) as client:
            r = await client.post(url.rstrip("/") + "/buying-note",
                                  json={"supplier_id": supplier_id, "lang": lang, "rows": rows},
                                  headers={"Authorization": "Bearer " + token})
        data = r.json()
    except httpx.TimeoutException:
        raise error("BUYING_NOTE_TIMEOUT") from None
    except (httpx.HTTPError, ValueError):
        raise error("BUYING_NOTE_UNAVAILABLE") from None
    if not r.is_success:
        detail = data.get("error") if isinstance(data, dict) else None
        raise error(detail.get("code") if isinstance(detail, dict) else "BUYING_NOTE_UNAVAILABLE")
    return data


def mount_buying_note(app, gw, principal, worker=None, *, clock=time.monotonic) -> None:
    cache: dict[str, tuple[float, dict]] = {}
    busy: set[str] = set()

    @app.get("/v1/suppliers/{supplier_id}/demand/buying-note")
    async def buying_note(supplier_id: str, request: Request, who=Depends(principal)):
        who.need_supplier("supplier:demand")
        start, end = window(request)
        lang = request.query_params.get("lang", "en")
        if lang not in LANGUAGES:
            raise GatewayError(422, "INVALID_REQUEST", "lang must be en or fi")
        answer = await run_in_threadpool(shortage_rows, gw().db, gw().valio, supplier_id, start, end)
        rows = pick(answer["rows"])
        base = {"supplier_id": supplier_id, "from": start.isoformat(), "to": end.isoformat(), "lang": lang,
                "model": MODEL_NAME, "rows_used": len(rows)}
        if not rows:
            return {**base, "duration_ms": 0, "cached": False, "note": [], "dropped": None}
        key = hashlib.sha256(json.dumps([supplier_id, base["from"], base["to"], lang, rows],
                                        sort_keys=True).encode()).hexdigest()
        hit = cache.get(key)
        ttl = DROPPED_CACHE_SECONDS if hit and hit[1]['note'] is None else CACHE_SECONDS
        if hit and clock() - hit[0] < ttl:
            return {**hit[1], "cached": True}
        if supplier_id in busy:
            raise GatewayError(429, "BUYING_NOTE_BUSY", "a buying note is already being written for this supplier")
        busy.add(supplier_id)
        started = clock()
        try:
            try:
                reply = await (worker or write_note)(supplier_id, lang, rows)
            except GatewayError as exc:
                if exc.code != "REPLY_INVALID":
                    raise
                reply = None
            note, dropped = check(reply, rows, lang) if isinstance(reply, dict) else (None, "REPLY_INVALID")
            result = {**base, "duration_ms": round((clock() - started) * 1000), "cached": False,
                      "note": note, "dropped": dropped}
            for old in [k for k, (at, result) in cache.items()
                        if clock() - at >= (DROPPED_CACHE_SECONDS if result['note'] is None else CACHE_SECONDS)]:
                cache.pop(old, None)
            cache[key] = (clock(), result)
            return result
        finally:
            busy.discard(supplier_id)
