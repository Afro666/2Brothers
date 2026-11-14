"""Onboarding lookup (#375): POST /v1/onboarding/lookup. Contract: docs/contract.md,
"Onboarding lookup (Context.dev)".

The kitchen types its work email or its website; one Context.dev call
(`POST /v1/brand/retrieve`) returns the profile fields to pre-fill. Rules:

- The key (`CONTEXT_DEV_API_KEY`) stays on the server: never logged, never returned.
- Nothing is saved: no database write. The answer for a domain stays in this process's
  memory for a few minutes (#604), so the same domain makes no second paid call.
- The open demo cannot drain the credits: a caller gets a few Context.dev calls per minute,
  then 429 `LOOKUP_RATE_LIMITED`. A limit is never answered with an empty profile.
- A field Context.dev did not return is `{"value": null, "source": null}`. Never a guess.
- The person's text is never fetched by the gateway; only a checked domain or email is
  sent to Context.dev.
"""

from __future__ import annotations

import copy
import ipaddress
import json
import os
import re
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, Request

from gateway.limits import KeyedLocks, RateLimit, TooMany, TTLCache, env_number
from gateway.service import GatewayError

API = "https://api.context.dev/v1/brand/retrieve"
SOURCE = {"provider": "Context.dev", "endpoint": "POST /v1/brand/retrieve"}
TIMEOUT = 20            # seconds; a cold domain can take more than 10 s (contract)
MAX_BODY = 2_000_000    # bytes read from Context.dev; a brand answer is a few kB
FIELDS = ("name", "logo_url", "colors", "address", "kitchen_type", "opening_hours")
ADDRESS_PARTS = ("street", "postal_code", "city", "country")
# Credit limits (#604). Each number has an environment override of the same meaning.
CACHE_TTL_S = 600               # ONBOARDING_CACHE_TTL_S: a found brand; 0 = no cache
CACHE_NOT_FOUND_TTL_S = 60      # ONBOARDING_CACHE_NOT_FOUND_TTL_S: `found: false`, briefly
RATE_LIMIT = 10                 # ONBOARDING_RATE_LIMIT: Context.dev calls per caller ...
RATE_WINDOW_S = 60              # ONBOARDING_RATE_WINDOW_S: ... in this many seconds; 0 = no limit

_DOMAIN = re.compile(r"^(?=.{4,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{0,61}[a-z0-9]$")
_LOCAL = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}$")
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
# The four kitchen types, by what an EIC industry line clearly says. `\bhospitals?\b`
# must not match "Hospitality".
_TYPES = (
    ("hotel", re.compile(r"\bhotels?\b|\baccommodations?\b|\blodging\b")),
    ("school", re.compile(r"\b(primary|secondary)\b.*\beducation\b|\bschools?\b")),
    ("hospital", re.compile(r"\bhospitals?\b|\bhealth ?care\b")),
    ("restaurant", re.compile(r"\brestaurants?\b|\bfood ?services?\b")),
)


def _invalid(message: str) -> GatewayError:
    return GatewayError(422, "INVALID_QUERY", message)


def _unavailable() -> GatewayError:
    # One fixed sentence: no upstream text, status or key ever reaches the caller.
    return GatewayError(502, "LOOKUP_UNAVAILABLE", "The lookup is not available right now. Fill in the form by hand.")


def _domain(host: str) -> str:
    host = host.strip().rstrip(".").lower()
    try:
        host = host.encode("idna").decode("ascii")      # hotelli-ähtäri.fi -> xn--...
    except UnicodeError:
        raise _invalid("That is not a website address.") from None
    if host.startswith("www."):
        host = host[4:]
    if not _DOMAIN.match(host):
        raise _invalid("That is not a website address.")
    return host


def parse_query(data: dict) -> tuple[str, dict]:
    """(domain, the Context.dev request body) from `{email}` or `{website}`; else 422."""
    email, website = data.get("email"), data.get("website")
    if (email is None) == (website is None):
        raise _invalid("Send exactly one of email or website.")
    if email is not None:
        if not isinstance(email, str) or len(email) > 254 or email.count("@") != 1:
            raise _invalid("That is not an email address.")
        local, _, host = email.strip().partition("@")
        if not _LOCAL.match(local):
            raise _invalid("That is not an email address.")
        domain = _domain(host)
        return domain, {"type": "by_email", "email": f"{local}@{domain}"}
    if not isinstance(website, str) or not website.strip() or len(website) > 2000:
        raise _invalid("That is not a website address.")
    text = website.strip()
    if "://" not in text:
        text = "https://" + text
    try:
        parts = urlsplit(text)
        host, has_login = parts.hostname or "", parts.username is not None or parts.password is not None
    except ValueError:
        raise _invalid("That is not a website address.") from None
    if parts.scheme.lower() not in ("http", "https") or has_login:
        raise _invalid("That is not a website address.")
    domain = _domain(host)
    return domain, {"type": "by_domain", "domain": domain}


def _post(payload: dict, key: str) -> tuple[int, dict]:
    """One POST to Context.dev: (HTTP status, JSON body). Tests replace this function.

    Raises OSError (network, timeout) or ValueError (not JSON). No retry: the page shows
    a blank form, and the person can try again.
    """
    request = urllib.request.Request(API, data=json.dumps(payload).encode(), method="POST", headers={
        "Authorization": "Bearer " + key, "Content-Type": "application/json",
        "User-Agent": "2brothers-onboarding/0.1"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            status, raw = response.status, response.read(MAX_BODY)
    except urllib.error.HTTPError as error:
        status, raw = error.code, error.read(MAX_BODY)
    try:
        body = json.loads(raw)
    except ValueError:
        body = {}
    return status, body if isinstance(body, dict) else {}


def _codes(body: dict) -> str:
    """The error body as upper-case text: wherever Context.dev puts its error code."""
    return json.dumps(body)[:2000].upper()


def _text(value) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _logo(logos) -> str | None:
    """An https URL: an `icon` or `logo` in light mode first, then any other mode."""
    usable = [logo for logo in logos if isinstance(logo, dict)
              and isinstance(logo.get("url"), str) and logo["url"].startswith("https://")
              and logo.get("type") in ("icon", "logo")] if isinstance(logos, list) else []
    light = [logo for logo in usable if logo.get("mode") == "light"]
    return (light or usable)[0]["url"] if usable else None


def _colors(colors) -> list[str] | None:
    out: list[str] = []
    for color in colors if isinstance(colors, list) else []:
        value = color.get("hex") if isinstance(color, dict) else None
        if isinstance(value, str) and _HEX.match(value) and value.lower() not in out:
            out.append(value.lower())
    return out or None


def _address(address) -> dict | None:
    if not isinstance(address, dict):
        return None
    out = {part: _text(address.get(part)) for part in ADDRESS_PARTS}
    return out if any(out.values()) else None


def _kitchen_type(industries) -> str | None:
    """One of the four types when every matching EIC line says the same one; else None."""
    lines = industries.get("eic") if isinstance(industries, dict) else None
    found = set()
    for line in lines if isinstance(lines, list) else []:
        if not isinstance(line, dict):
            continue
        # The subindustry is the precise line; the industry only counts when there is none.
        text = (_text(line.get("subindustry")) or _text(line.get("industry")) or "").lower()
        found.update(name for name, pattern in _TYPES if pattern.search(text))
    return found.pop() if len(found) == 1 else None


def _field(value) -> dict:
    return {"value": value, "source": dict(SOURCE) if value is not None else None}


def profile(domain: str, brand: dict | None) -> dict:
    """The contract answer. `brand` None: Context.dev does not know the domain."""
    if not isinstance(brand, dict):
        return {"domain": domain, "found": False, **{name: _field(None) for name in FIELDS}}
    return {"domain": domain, "found": True,
            "name": _field(_text(brand.get("title"))),
            "logo_url": _field(_logo(brand.get("logos"))),
            "colors": _field(_colors(brand.get("colors"))),
            "address": _field(_address(brand.get("address"))),
            "kitchen_type": _field(_kitchen_type(brand.get("industries"))),
            # Not in brand/retrieve; the optional scrape for schema.org hours is not made.
            "opening_hours": _field(None)}


def _now() -> float:
    """Seconds on a clock that never goes back. Tests replace this function: no sleeping."""
    return time.monotonic()


class Limits:
    """The cache and the rate limit of one gateway app.

    Process-local on purpose: memory only, never MongoDB (the contract's "saves nothing"),
    empty after a restart, and not shared between gateway processes (the demo runs one).
    The cache holds what Context.dev says about a public domain. It is not kitchen data and
    it is not keyed by caller, so it cannot show one kitchen's data to another; the email's
    local part is never kept."""

    def __init__(self):
        self.cache, self.rate, self.locks = TTLCache(), RateLimit(), KeyedLocks()


def lookup(data: dict, limits: Limits | None = None, caller: str = "") -> dict:
    """The contract answer. With `limits`: from the cache when it has the domain, else one
    Context.dev call counted against `caller`. Only a lookup that would call Context.dev counts."""
    domain, payload = parse_query(data)
    key = (os.environ.get("CONTEXT_DEV_API_KEY") or "").strip()
    if not key:
        raise _unavailable()
    if limits is None:
        return _retrieve(domain, payload, key)
    # By email and by domain are kept apart: a free-mail domain is refused by email
    # (FREE_EMAIL) but is a brand by domain.
    cache_key = (payload["type"], domain)
    # One call at a time per domain: a double click waits, then reads the cache. When the
    # wait runs out the lookup goes on without the lock; the rate limit still counts it.
    with limits.locks.hold(cache_key, TIMEOUT + 5):
        cached = limits.cache.get(cache_key, _now())
        if cached is not None:
            return copy.deepcopy(cached)
        wait = limits.rate.hit(caller, env_number("ONBOARDING_RATE_LIMIT", RATE_LIMIT),
                               env_number("ONBOARDING_RATE_WINDOW_S", RATE_WINDOW_S), _now())
        if wait > 0:
            raise TooMany("LOOKUP_RATE_LIMITED",
                          "Too many lookups. Try again in a moment, or fill in the form by hand.", wait)
        answer = _retrieve(domain, payload, key)     # an error is raised, so it is never cached
        ttl = (env_number("ONBOARDING_CACHE_TTL_S", CACHE_TTL_S) if answer["found"]
               else env_number("ONBOARDING_CACHE_NOT_FOUND_TTL_S", CACHE_NOT_FOUND_TTL_S))
        limits.cache.put(cache_key, copy.deepcopy(answer), ttl, _now())
        return answer


def _retrieve(domain: str, payload: dict, key: str) -> dict:
    """One paid Context.dev call: the profile, or the contract's error."""
    try:
        status, body = _post(payload, key)
    except (OSError, ValueError):
        raise _unavailable() from None
    if status == 200 and isinstance(body.get("brand"), dict):
        return profile(domain, body["brand"])
    codes = _codes(body)
    if "FREE_EMAIL_DETECTED" in codes or "DISPOSABLE_EMAIL_DETECTED" in codes:
        raise GatewayError(422, "FREE_EMAIL", "Type the kitchen's website instead.")
    if status in (400, 404) and "NOT_FOUND" in codes:
        return profile(domain, None)
    if status == 422:
        raise _invalid("Context.dev cannot read that address.")
    raise _unavailable()      # 401, 402 (credits), 408, 429, 5xx, or an answer without a brand


def _caller(who, request: Request) -> str:
    """Who the rate limit counts: a signed-in person by account (they have a kitchen), else
    the client address. The shared demo token's X-User is free text, so it is not an identity."""
    if who.kitchen_id is not None:
        return "user:" + who.name
    return "address:" + _client_address(request)


def _client_address(request: Request) -> str:
    """The visitor's address. Behind Caddy (a private or loopback peer) that is the rightmost
    X-Forwarded-For entry, which Caddy sets itself; a direct client keeps its own address."""
    host = request.client.host if request.client else "unknown"
    try:
        peer = ipaddress.ip_address(host)
    except ValueError:
        return host
    forwarded = request.headers.get("x-forwarded-for", "")
    last = forwarded.split(",")[-1].strip()
    if (peer.is_private or peer.is_loopback) and last:
        return last
    return host


def mount_onboarding(app: FastAPI, principal, body) -> None:
    limits = Limits()       # one per app, so one per gateway process

    @app.post("/v1/onboarding/lookup")
    async def onboarding_lookup(request: Request, who=Depends(principal)):
        if who.kind != "human":
            raise GatewayError(403, "HUMAN_SESSION_REQUIRED", "only a person can look a business up")
        data = await body(request)
        from starlette.concurrency import run_in_threadpool
        try:
            return await run_in_threadpool(lookup, data, limits, _caller(who, request))
        except TooMany as busy:
            return busy.answer()        # 429 with Retry-After; app.py's handler has no headers
