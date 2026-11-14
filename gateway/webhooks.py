"""Webhooks per kitchen (#277): the gateway tells a developer's server what happened.

- A person registers an https URL and the events it wants. The secret (`whsec_...`) is
  shown once at creation; it stays stored, because every delivery is signed with it.
- A delivery is one JSON POST with `X-TKB-Event` and
  `X-TKB-Signature: sha256=<HMAC-SHA256 of the raw body with the hook secret>`.
- At most 3 attempts with a short backoff, 3 seconds each. The delivery log keeps the
  status code only, never a body.
- Nothing here may break an order: `dispatch` and `deliver` never raise.
- SSRF: https only, no private or link-local address, no internal host name; the
  receiver's addresses are checked again at delivery time and redirects are not followed.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import socket
import threading
import time
from typing import Callable
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

EVENTS = ("proposal.ready", "proposal.approved", "proposal.rejected", "order.placed",
          "total_mismatch", "recall.alert")
PING = "ping"                      # sent by POST .../test only; not a subscription
# Audit kind (Gateway._audit) -> the events a developer sees.
KIND_EVENTS = {
    "proposal_created": ("proposal.ready",),
    "approval_requested": ("proposal.ready",),
    "order_placed": ("proposal.approved", "order.placed"),
    "proposal_rejected": ("proposal.rejected",),
    "total_mismatch": ("total_mismatch",),
    "recall_proposal_blocked": ("recall.alert",),
}
MAX_HOOKS = 10
MAX_ATTEMPTS = 3
BACKOFF = (0.5, 2.0)               # seconds before attempt 2 and attempt 3
TIMEOUT = 3.0
SECRET_PREFIX = "whsec_"
DEV_HOSTS = ("localhost", "127.0.0.1")
INTERNAL_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home", ".corp", ".intranet",
                     ".home.arpa")

Send = Callable[[str, bytes, dict], int]


class WebhookError(ValueError):
    pass


def _dev() -> bool:
    """http://localhost receivers are for a developer's own machine, never for production."""
    return os.environ.get("GATEWAY_WEBHOOKS_DEV", "").lower() == "true"


def _public(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    mapped = getattr(ip, "ipv4_mapped", None)
    return (mapped or ip).is_global


def check_url(url: str) -> str:
    """The URL if a hook may point at it; WebhookError otherwise."""
    if not isinstance(url, str) or not url or len(url) > 2000 or url != url.strip():
        raise WebhookError("url: an https URL, at most 2000 characters")
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower().rstrip(".")
        parts.port                                  # a bad port raises here
    except ValueError:
        raise WebhookError("url: not a valid URL") from None
    if not host or parts.username is not None or parts.password is not None:
        raise WebhookError("url: a host is required, and no user or password in the URL")
    if parts.scheme == "http" and host in DEV_HOSTS and _dev():
        return url
    if parts.scheme != "https":
        raise WebhookError("url: https only")
    try:
        ipaddress.ip_address(host)
        literal = True
    except ValueError:
        literal = False
    if literal:
        if not _public(host):
            raise WebhookError("url: a private, loopback or link-local address is refused")
        return url
    if "." not in host or host.endswith(INTERNAL_SUFFIXES) or host.replace(".", "").isdigit() \
            or host.startswith("0x"):
        raise WebhookError("url: an internal host name is refused")
    return url


def _checked_address(url: str) -> str | None:
    """Resolve the host once and return the one address to connect to. Every address it
    resolves to must be public. None for the dev exception (http://localhost)."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower().rstrip(".")
    if parts.scheme == "http" and host in DEV_HOSTS and _dev():
        return None
    infos = socket.getaddrinfo(host, parts.port or 443, type=socket.SOCK_STREAM)
    if not infos or not all(_public(info[4][0]) for info in infos):
        raise WebhookError("receiver resolves to a private address")
    return infos[0][4][0]


def http_send(url: str, body: bytes, headers: dict) -> int:
    """The real sender: one POST, 3 seconds, no redirects. Returns the status code.

    The connection goes to the address that was checked, not to a second DNS answer
    (#562: a short-TTL record could answer public for the check and private for the
    POST). The Host header and the TLS name (SNI, certificate check) stay the host name.
    """
    import httpx
    check_url(url)
    address = _checked_address(url)
    if address is None:
        return httpx.post(url, content=body, headers=headers, timeout=TIMEOUT,
                          follow_redirects=False).status_code
    parts = urlsplit(url)
    host = (parts.hostname or "").lower().rstrip(".")
    ip = f"[{address}]" if ":" in address else address
    pinned = urlunsplit((parts.scheme, ip + (f":{parts.port}" if parts.port else ""), parts.path or "/",
                         parts.query, ""))
    netloc = host + (f":{parts.port}" if parts.port else "")
    with httpx.Client(timeout=TIMEOUT, follow_redirects=False, trust_env=False) as client:
        request = client.build_request("POST", pinned, content=body, headers={**headers, "Host": netloc},
                                       extensions={"sni_hostname": host})
        return client.send(request).status_code


def sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _out(doc: dict) -> dict:
    return {"webhook_id": doc["_id"], "url": doc["url"], "events": doc["events"],
            "created_at": doc["created_at"].isoformat(), "created_by": doc["created_by"]}


def register(db, kitchen_id: str, url: str, events: list[str], created_by: str,
             now: datetime | None = None) -> dict:
    url = check_url(url)
    if not events or not isinstance(events, list) or not all(isinstance(e, str) for e in events):
        raise WebhookError("events: at least one of " + ", ".join(EVENTS))
    unknown = sorted(set(events) - set(EVENTS))
    if unknown:
        raise WebhookError("unknown events: " + ", ".join(unknown))
    if db.webhooks.count_documents({"kitchen_id": kitchen_id}) >= MAX_HOOKS:
        raise WebhookError(f"at most {MAX_HOOKS} webhooks per kitchen")
    secret = SECRET_PREFIX + secrets.token_urlsafe(32)
    doc = {"_id": uuid4().hex, "kitchen_id": kitchen_id, "url": url, "events": sorted(set(events)),
           "secret": secret, "created_at": now or datetime.now(timezone.utc), "created_by": created_by}
    db.webhooks.insert_one(doc)
    return {**_out(doc), "secret": secret}      # the only time the secret leaves the gateway


def list_hooks(db, kitchen_id: str) -> list[dict]:
    return [_out(d) for d in db.webhooks.find({"kitchen_id": kitchen_id}).sort("created_at", -1)]


def get(db, kitchen_id: str, hook_id: str) -> dict | None:
    doc = db.webhooks.find_one({"_id": hook_id, "kitchen_id": kitchen_id})
    return _out(doc) if doc else None


def delete(db, kitchen_id: str, hook_id: str) -> dict | None:
    doc = db.webhooks.find_one_and_delete({"_id": hook_id, "kitchen_id": kitchen_id})
    if doc is None:
        return None
    db.webhook_deliveries.delete_many({"hook_id": hook_id, "kitchen_id": kitchen_id})
    return _out(doc)


def _delivery_out(row: dict) -> dict:
    return {"delivery_id": row["_id"], "event": row["event"], "at": row["at"].isoformat(),
            "attempts": row["attempts"], "status": row["status"], "ok": row["ok"], "error": row["error"]}


def deliveries(db, kitchen_id: str, hook_id: str, limit: int = 50) -> list[dict]:
    rows = db.webhook_deliveries.find({"hook_id": hook_id, "kitchen_id": kitchen_id})
    return [_delivery_out(r) for r in rows.sort("at", -1).limit(limit)]


def _deliver_one(db, hook: dict, event: str, payload: dict, send: Send, sleep: Callable[[float], None],
                 attempts: int) -> dict:
    delivery_id = uuid4().hex
    now = datetime.now(timezone.utc)
    body = json.dumps({"id": delivery_id, "event": event, "kitchen_id": hook["kitchen_id"],
                       "at": now.isoformat(), "data": payload},
                      separators=(",", ":"), sort_keys=True, default=str).encode()
    headers = {"Content-Type": "application/json", "User-Agent": "trusted-kitchen-buyer-webhook/1",
               "X-TKB-Event": event, "X-TKB-Delivery": delivery_id,
               "X-TKB-Signature": sign(hook["secret"], body)}
    status, error, tries = None, None, 0
    for attempt in range(attempts):
        if attempt:
            sleep(BACKOFF[min(attempt - 1, len(BACKOFF) - 1)])
        tries += 1
        try:
            status, error = int(send(hook["url"], body, headers)), None
        except Exception as exc:                      # the class name only: never a body or a URL
            status, error = None, type(exc).__name__
        if status is not None and 200 <= status < 300:
            break
    row = {"_id": delivery_id, "hook_id": hook["_id"], "kitchen_id": hook["kitchen_id"], "event": event,
           "at": now, "attempts": tries, "status": status, "error": error,
           "ok": status is not None and 200 <= status < 300}
    db.webhook_deliveries.insert_one(row)
    return _delivery_out(row)


def deliver(db, kitchen_id: str, event: str, payload: dict, send: Send | None = None, *,
            sleep: Callable[[float], None] = time.sleep, hook_id: str | None = None,
            attempts: int = MAX_ATTEMPTS) -> list[dict]:
    """POST `event` to every hook of the kitchen subscribed to it (or to `hook_id` alone,
    whatever it subscribes to: the test ping). Returns the delivery log rows. Never raises."""
    out: list[dict] = []
    try:
        query = {"kitchen_id": kitchen_id, "_id": hook_id} if hook_id else {"kitchen_id": kitchen_id, "events": event}
        hooks = list(db.webhooks.find(query))
    except Exception:
        return out
    for hook in hooks:
        try:
            out.append(_deliver_one(db, hook, event, payload, send or http_send, sleep,
                                    max(1, min(attempts, MAX_ATTEMPTS))))
        except Exception:
            continue                                  # one broken hook never stops the others
    return out


def run_async(job: Callable[[], None]) -> None:
    """Deliveries run beside the request, never inside it."""
    threading.Thread(target=job, name="webhook-delivery", daemon=True).start()


def dispatch(db, kitchen_id: str, kind: str, data: dict) -> None:
    """Called once for every audit event (Gateway._audit). Maps the audit kind to webhook
    events and delivers them in a background thread. Never raises, never waits for a receiver."""
    try:
        events = KIND_EVENTS.get(kind)
        if not events:
            return
        wanted = [e for e in events if db.webhooks.count_documents({"kitchen_id": kitchen_id, "events": e}, limit=1)]
        if not wanted:
            return
        payload = dict(data)

        def job() -> None:
            for event in wanted:
                deliver(db, kitchen_id, event, payload)

        run_async(job)
    except Exception:
        return
