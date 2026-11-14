"""Recall list and "check now" (#358). Contract: docs/contract.md, "Recall alerts (Context.dev)".

- GET  /v1/kitchens/{kitchen_id}/recalls        (`kitchen:read`)
- POST /v1/kitchens/{kitchen_id}/recalls/check  (`kitchen:write`, body `idempotency_key`)

Both are views. The kitchen that is matched is `store.recalls.context`: the products on its
open proposals, in its counted stock and in its recipes. An alert for a product no open
proposal holds has `proposals: []` and says in `where` why it matters ("in stock: 3.253 KG").
The matching is `monitor.recalls.scan`, the hold and the replacement
proposal are `monitor.proposals.apply_notices`, the alerts are the rows `store.recalls`
keeps. This module adds three things: one bounded Context.dev call for the live notice
list, the honest `last_check` (live or recording), and the audit entry of the check, which
is also the idempotency record.

A check never orders, approves or cancels. Unknown is never "no recalls": `last_check` is
null until a check ran, and notices the recording does not hold are counted, not hidden.

Each scrape costs Context.dev credits and up to 45 s of a worker thread (#652), so: one
check runs at a time per kitchen, and a check asked for while the kitchen's newest one is
younger than the cooldown answers from that one (`reused: true`) without scraping. A
cooldown answer only reads: it does not match, hold, plan or write an audit entry.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from fastapi import Depends, FastAPI, Request

from gateway.limits import KeyedLocks, TooMany, env_number
from gateway.service import Gateway, GatewayError, _hash
from monitor.recalls import LIST_SCHEMA, LIST_URL, ContextDev, parse_date
from store import audit, recalls
from store.products import get_products

RECORDING = Path(__file__).resolve().parent.parent / "monitor" / "fixtures" / "ruokavirasto.json"
VIA = "Context.dev /v1/web/scrape (json)"
# A live list scrape took 30 s on 2026-11-14 (102 notices, JSON extraction): 20 s would never be live.
DEFAULT_TIMEOUT, MAX_TIMEOUT = 45.0, 120.0
COOLDOWN_S = 60             # RECALL_CHECK_COOLDOWN_S: a newer check than this is reused; 0 = off
LOCK_WAIT_SLACK_S = 30      # RECALL_CHECK_LOCK_WAIT_S overrides: the scrape timeout plus this
BUSY_RETRY_S = 10           # Retry-After of 429 RECALL_CHECK_BUSY
# One check at a time per kitchen. Process-local: it holds for the one gateway process the
# demo runs; a second process would not see this lock (the audit cooldown still would).
# Keyed by kitchen, and the cooldown reads only that kitchen's audit entry, so one kitchen's
# check or alerts never answer another kitchen.
_LOCKS = KeyedLocks()
CHECK_FIELDS = ("source", "live_error", "fetched_at", "details_fetched_at", "via",
                "notices_scanned", "scanned_since", "notices_listed", "notices_unread")


def _timeout() -> float:
    """Seconds for the one Context.dev call: RECALL_CHECK_TIMEOUT_S, above 0 and at most 120."""
    try:
        value = float(os.environ.get("RECALL_CHECK_TIMEOUT_S", ""))
    except ValueError:
        return DEFAULT_TIMEOUT
    return min(value, MAX_TIMEOUT) if value > 0 else DEFAULT_TIMEOUT


def _recording() -> dict:
    """The saved scrape. Without it nothing can be matched, so the check is unavailable."""
    try:
        data = json.loads(RECORDING.read_text(encoding="utf-8"))
        notices = data["notices"]
        if not isinstance(notices, list) or not all(isinstance(n, dict) and n.get("url") for n in notices):
            raise ValueError("notices")
    except (OSError, ValueError, KeyError, TypeError):
        raise GatewayError(502, "RECALL_CHECK_UNAVAILABLE",
                           "the recall check has no notices to read; recalls are unknown") from None
    return data


def _page(url: str) -> str:
    """One notice page, however the list wrote its link (relative, with or without a slash)."""
    return urlsplit(urljoin(LIST_URL, url.strip())).path.rstrip("/").casefold()


def _live_list() -> tuple[list[dict] | None, str | None]:
    """The notices on the Ruokavirasto list now: one Context.dev call, one attempt.

    Returns (rows with a `url`, None), or (None, why) when the list could not be read. `why` is a fixed
    code; the upstream message is never passed on (it can carry the request)."""
    try:
        client = ContextDev()
    except RuntimeError:
        return None, "NO_KEY"
    try:
        answer = client.scrape_json(LIST_URL, LIST_SCHEMA, attempts=1, timeout=_timeout())
    except TimeoutError:
        return None, "TIMEOUT"
    except OSError as exc:      # URLError wraps a socket timeout in `reason`
        return None, "TIMEOUT" if isinstance(getattr(exc, "reason", None), TimeoutError) else "UPSTREAM_ERROR"
    except (RuntimeError, ValueError):
        return None, "UPSTREAM_ERROR"
    rows = answer.get("recalls") if isinstance(answer, dict) else None
    rows = [row for row in rows if isinstance(row, dict) and isinstance(row.get("url"), str)
            and row["url"].strip()] if isinstance(rows, list) else []
    if not rows:
        return None, "BAD_ANSWER"   # an empty or shapeless list is not "no recalls"
    return rows, None


def fetch_notices(now_iso: str) -> tuple[list[dict], dict]:
    """The notices to match and how they were obtained (the `last_check` facts).

    The notice pages always come from the recording: a check makes one call, the list. A
    live list says the data is current and counts the notices the recording has not read.
    The recording starts at `scanned_since`; older notices on the list were left out on
    purpose when it was made, so they are listed, not "unread"."""
    saved = _recording()
    notices = saved["notices"]
    rows, why = _live_list()
    recorded_at = saved.get("fetched_at")
    dates = [day for day in (parse_date(notice.get("date")) for notice in notices) if day]
    since = min(dates) if dates else None
    facts = {"source": "recording", "live_error": why, "fetched_at": recorded_at,
             "details_fetched_at": recorded_at, "via": saved.get("via") or VIA,
             "notices_scanned": len(notices), "scanned_since": since.isoformat() if since else None,
             "notices_listed": None, "notices_unread": None}
    if rows is not None:
        known = {_page(notice["url"]) for notice in notices}
        listed = {_page(row["url"]): parse_date(row.get("date")) for row in rows}
        # No date on the list, or no window to compare with: it may be new, so it counts.
        unread = [page for page, day in listed.items()
                  if page not in known and (day is None or since is None or day >= since)]
        facts.update(source="live", live_error=None, fetched_at=now_iso, via=VIA,
                     notices_listed=len(listed), notices_unread=len(unread))
    return notices, facts


def _last_check(entry: dict | None) -> dict | None:
    if entry is None:
        return None
    event = entry["event"]
    return {"checked_at": entry["server"].get("at"), "checked_by": event.get("actor"),
            **{field: event.get(field) for field in CHECK_FIELDS}}


def _replacement(gw: Gateway, kitchen_id: str, proposal_id: str | None) -> dict | None:
    """A short copy of the separate replacement proposal; None when there is none to read."""
    if not proposal_id:
        return None
    try:
        doc = gw.get_proposal(kitchen_id, proposal_id)
    except GatewayError:
        return None
    names = {row["product_id"]: (row.get("names") or {}).get("en")
             for row in get_products(gw.db, [line["product_id"] for line in doc["lines"]], kitchen_id)}
    return {"proposal_id": doc["proposal_id"], "status": doc["status"],
            "expected_total": doc["expected_total"], "currency": doc["currency"],
            "lines": [{"product_id": line["product_id"], "product_name": names.get(line["product_id"]),
                       "quantity": line["quantity"], "unit": line["unit"]} for line in doc["lines"]]}


def recall_view(gw: Gateway, kitchen_id: str, entry: dict | None = None) -> dict:
    """`{last_check, alerts}`: the stored alerts, each with the proposals that carry it."""
    by_event: dict[str, list[dict]] = {}
    copies: dict[str, dict | None] = {}
    for doc in recalls.carrying(gw.db, kitchen_id):
        replacement_id = doc.get("replacement_proposal_id")
        if replacement_id not in copies:
            copies[replacement_id] = _replacement(gw, kitchen_id, replacement_id)
        row = {"proposal_id": doc["_id"], "status": doc["status"],
               "replacement_proposal_id": replacement_id,
               "recall_replan_error": doc.get("recall_replan_error"),
               "replacement": copies[replacement_id]}
        for event_id in dict.fromkeys(alert["event_id"] for alert in doc["recall_alerts"]):
            by_event.setdefault(event_id, []).append(row)
    entry = entry or recalls.check_entry(gw.db, kitchen_id)
    return {"last_check": _last_check(entry),
            "alerts": [{**alert, "proposals": by_event.get(alert["event_id"], [])}
                       for alert in recalls.alerts(gw.db, kitchen_id)]}


def _fresh(entry: dict | None, now: datetime) -> bool:
    """True when this kitchen's newest check is younger than the cooldown."""
    cooldown = env_number("RECALL_CHECK_COOLDOWN_S", COOLDOWN_S)
    if entry is None or cooldown <= 0:
        return False
    try:
        age = (now - datetime.fromisoformat(entry["server"]["at"])).total_seconds()
    except (KeyError, TypeError, ValueError):       # no readable time: check again
        return False
    return 0 <= age < cooldown


def run_check(gw: Gateway, kitchen_id: str, body: dict, actor: str) -> dict:
    key = body.get("idempotency_key")
    if not isinstance(key, str) or not 1 <= len(key.strip()) <= 200:
        raise GatewayError(422, "INVALID_REQUEST", "idempotency_key: a string of 1 to 200 characters")
    event_id = "recall-check:" + _hash([kitchen_id, key.strip()])
    stored = recalls.check_entry(gw.db, kitchen_id, event_id)
    if stored is not None:      # a replay: no scrape, nothing applied
        return recall_view(gw, kitchen_id, stored)
    wait = env_number("RECALL_CHECK_LOCK_WAIT_S", _timeout() + LOCK_WAIT_SLACK_S)
    with _LOCKS.hold(kitchen_id, wait) as held:
        if not held:    # the running check did not end in time: say so, never "no recalls"
            raise TooMany("RECALL_CHECK_BUSY",
                          "a recall check is already running for this kitchen; try again shortly",
                          BUSY_RETRY_S)
        return _check(gw, kitchen_id, event_id, actor)


def _check(gw: Gateway, kitchen_id: str, event_id: str, actor: str) -> dict:
    """One check, with the kitchen's lock held."""
    stored = recalls.check_entry(gw.db, kitchen_id, event_id)
    if stored is not None:      # the same key, sent twice at once: the first one stands
        return recall_view(gw, kitchen_id, stored)
    newest = recalls.check_entry(gw.db, kitchen_id)
    if _fresh(newest, gw.now()):
        # Cooldown: read only. The key is not recorded; after the cooldown it runs a check.
        return {**recall_view(gw, kitchen_id, newest), "reused": True}
    now_iso = gw.now().isoformat()
    notices, facts = fetch_notices(now_iso)
    from monitor.proposals import apply_notices     # imports the agent package: only when used
    apply_notices(gw, kitchen_id, notices)
    view = recall_view(gw, kitchen_id)
    event = {"event_id": event_id, "kind": "recall_check", "actor": actor, **facts,
             "alerts": [alert["event_id"] for alert in view["alerts"]],
             "proposals_held": sorted({row["proposal_id"] for alert in view["alerts"]
                                       for row in alert["proposals"] if row["status"] == "BLOCKED_BY_RECALL"})}
    try:
        audit.append_event(gw.db, event, {"kitchen_id": kitchen_id, "at": now_iso})
    except audit.AuditConflict:     # the same key, sent twice at once: the first one stands
        pass
    return recall_view(gw, kitchen_id, recalls.check_entry(gw.db, kitchen_id, event_id))


def mount_recalls(app: FastAPI, gw, principal, body) -> None:
    @app.get("/v1/kitchens/{kitchen_id}/recalls")
    def list_recalls(kitchen_id: str, who=Depends(principal)):
        who.need("kitchen:read", kitchen_id)
        return recall_view(gw(), kitchen_id)

    @app.post("/v1/kitchens/{kitchen_id}/recalls/check")
    async def check_recalls(kitchen_id: str, request: Request, who=Depends(principal)):
        who.need("kitchen:write", kitchen_id)
        if who.kind == "human" and who.role == "viewer":
            raise GatewayError(403, "ROLE_REQUIRED", "a viewer can read recalls, not run a check")
        data = await body(request)
        # The scrape and the Valio quotes block: off the event loop, like a sync route.
        from starlette.concurrency import run_in_threadpool
        try:
            return await run_in_threadpool(run_check, gw(), kitchen_id, data, who.name)
        except TooMany as busy:
            return busy.answer()        # 429 with Retry-After; app.py's handler has no headers
