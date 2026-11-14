"""Onboarding lookup (#375): POST /v1/onboarding/lookup. Contract: docs/contract.md,
"Onboarding lookup (Context.dev)".

The kitchen types its work email or its website; one Context.dev call
(`POST /v1/brand/retrieve`) returns the profile fields to pre-fill. Rules:

- The key (`CONTEXT_DEV_API_KEY`) stays on the server: never logged, never returned.
- Nothing is saved: no database write, no cache.
- A field Context.dev did not return is `{"value": null, "source": null}`. Never a guess.
- The person's text is never fetched by the gateway; only a checked domain or email is
  sent to Context.dev.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, Request

from gateway.service import GatewayError

API = "https://api.context.dev/v1/brand/retrieve"
SOURCE = {"provider": "Context.dev", "endpoint": "POST /v1/brand/retrieve"}
TIMEOUT = 20            # seconds; a cold domain can take more than 10 s (contract)
MAX_BODY = 2_000_000    # bytes read from Context.dev; a brand answer is a few kB
FIELDS = ("name", "logo_url", "colors", "address", "kitchen_type", "opening_hours")
ADDRESS_PARTS = ("street", "postal_code", "city", "country")

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


def lookup(data: dict) -> dict:
    domain, payload = parse_query(data)
    key = (os.environ.get("CONTEXT_DEV_API_KEY") or "").strip()
    if not key:
        raise _unavailable()
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


# ---- cost guard (#604): the demo site is open, and every lookup is a paid Context.dev call --
# Nothing is saved (the contract's promise): the cache and the counter live in this process only.
CACHE_TTL_S = 600          # the same business within 10 minutes is answered from memory
MAX_CALLS = 20             # paid calls per window, for the whole site
WINDOW_S = 600
_cache: dict[str, tuple[float, dict]] = {}
_calls: list[float] = []


def reset_cost_guard() -> None:
    _cache.clear()
    _calls.clear()


def guarded_lookup(data: dict, now=None) -> dict:
    """`lookup`, but a repeated query is answered from memory and the site makes at most
    MAX_CALLS paid calls per WINDOW_S; past that it answers 429, without calling Context.dev."""
    import json
    import time
    now = time.monotonic() if now is None else now
    domain, payload = parse_query(data)          # validates first: a bad query never costs
    key = json.dumps([domain, payload], sort_keys=True, default=str)
    hit = _cache.get(key)
    if hit and hit[0] > now:
        return hit[1]
    _calls[:] = [t for t in _calls if t > now - WINDOW_S]
    if len(_calls) >= MAX_CALLS:
        raise GatewayError(429, "RATE_LIMITED", "Too many lookups right now. Try again in a few minutes.")
    _calls.append(now)
    result = lookup(data)
    if len(_cache) > 200:
        _cache.clear()
    _cache[key] = (now + CACHE_TTL_S, result)
    return result


def mount_onboarding(app: FastAPI, principal, body) -> None:
    @app.post("/v1/onboarding/lookup")
    async def onboarding_lookup(request: Request, who=Depends(principal)):
        if who.kind != "human":
            raise GatewayError(403, "HUMAN_SESSION_REQUIRED", "only a person can look a business up")
        data = await body(request)
        from starlette.concurrency import run_in_threadpool
        return await run_in_threadpool(guarded_lookup, data)
