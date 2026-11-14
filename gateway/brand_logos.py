"""Brand logos (docs/contract.md, "Product pictures: kind icons and brand logos").

The catalog has no product photos, so a product shows a kind icon, or its brand's logo
when Context.dev knows the brand. Two parts:

- `GET /v1/brands/logos?name=...` reads the `brand_logos` rows (store/brand_logos.py).
  It never calls Context.dev: a page view on the open demo spends no credits.
- `python -m gateway.brand_logos --limit 20` is the operator's command that asks
  Context.dev, once per brand, by name (the catalog has brand names, not domains).
  It is capped (at most 30 calls a run), stops before the shared key runs low, and keeps
  a logo only when Context.dev's title or domain is the brand itself.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, Query

from gateway import onboarding
from gateway.service import GatewayError
from store import brand_logos as stored

SOURCE = {"provider": "Context.dev", "endpoint": "POST /v1/brand/retrieve"}
MAX_NAMES = 50
MAX_NAME_LENGTH = 100
ASKABLE = (3, 30)               # Context.dev's by_name takes 3 to 30 characters
DEFAULT_LIMIT, MAX_LIMIT = 10, 30
CREDIT_FLOOR = 300              # the recall monitor and the onboarding lookup share the key
MAX_FAILURES = 3
STOP_STATUSES = (401, 402, 429)
# icon with its own background, light icon, light logo, dark icon, dark logo, own-background logo
_ORDER = (("icon", "has_opaque_background"), ("icon", "light"), ("logo", "light"),
          ("icon", "dark"), ("logo", "dark"), ("logo", "has_opaque_background"))
_BACKGROUND = {"has_opaque_background": "own", "light": "light", "dark": "dark"}

_post = onboarding._post        # one POST to Context.dev: (status, body). Tests replace it.


# ---- the route ------------------------------------------------------------------------

def _iso(moment: datetime | None) -> str | None:
    if moment is None:
        return None
    if moment.tzinfo is None:       # a client without `tz_aware` reads UTC as a naive datetime
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds")


def answer_row(name: str, row: dict | None) -> dict:
    """The contract row for one brand name."""
    if row is None:
        return {"brand": name, "status": "not_checked", "logo_url": None, "background": None,
                "domain": None, "checked_at": None, "source": None}
    found = row.get("status") == "found"
    return {"brand": name, "status": "found" if found else "none",
            "logo_url": row.get("logo_url") if found else None,
            "background": row.get("background") if found else None,
            "domain": row.get("domain") if found else None,
            "checked_at": _iso(row.get("checked_at")),
            "source": dict(SOURCE) if found else None}


def clean_names(names: list[str]) -> list[str]:
    """The asked names, trimmed and without repeats; 422 for a query the contract refuses."""
    if not names or len(names) > MAX_NAMES:
        raise GatewayError(422, "INVALID_REQUEST", f"name: 1 to {MAX_NAMES} brand names")
    out = []
    for name in names:
        name = name.strip()
        if not name or len(name) > MAX_NAME_LENGTH:
            raise GatewayError(422, "INVALID_REQUEST", f"name: 1 to {MAX_NAME_LENGTH} characters")
        if name not in out:
            out.append(name)
    return out


def logos(db, names: list[str]) -> dict:
    from pymongo.errors import PyMongoError
    names = clean_names(names)
    try:
        rows = stored.get_many(db, names)
    except PyMongoError:
        raise GatewayError(503, "LOGOS_UNAVAILABLE", "the logo list cannot be read now") from None
    return {"logos": [answer_row(name, rows.get(name)) for name in names]}


def mount_brand_logos(app: FastAPI, gw, principal) -> None:
    @app.get("/v1/brands/logos")
    def brand_logos(name: list[str] = Query(default=[]), who=Depends(principal)):
        who.need("kitchen:read")
        return logos(gw().db, name)


# ---- asking Context.dev ---------------------------------------------------------------

def _compact(text) -> str:
    return "".join(ch for ch in str(text or "").lower() if ch.isalnum())


def matches(name: str, title, domain) -> bool:
    """True when Context.dev's answer is this brand: the same title, or the brand as the
    first label of the domain, both compared without case, spaces and punctuation."""
    want = _compact(name)
    if not want:
        return False
    host = str(domain or "").lower().strip().removeprefix("www.")
    return _compact(title) == want or (bool(host) and _compact(host.split(".")[0]) == want)


def pick_logo(logos_field) -> tuple[str | None, str | None]:
    """(https URL, background) of the logo the contract prefers; (None, None) without one."""
    usable = [logo for logo in logos_field if isinstance(logo, dict) and isinstance(logo.get("url"), str)
              and logo["url"].startswith("https://")] if isinstance(logos_field, list) else []
    for kind, mode in _ORDER:
        for logo in usable:
            if logo.get("type") == kind and logo.get("mode") == mode:
                return logo["url"], _BACKGROUND[mode]
    return None, None


def _remaining(body: dict) -> float | None:
    meta = body.get("key_metadata") if isinstance(body, dict) else None
    value = meta.get("credits_remaining") if isinstance(meta, dict) else None
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def warm(db, key: str, *, limit: int, brands: list[str] | None = None, now=None) -> dict:
    """Ask Context.dev about at most `limit` brands that have no row yet: the named ones,
    else the catalog brands with the most products. Returns what happened, per brand."""
    now = now or (lambda: datetime.now(timezone.utc))
    report: dict = {"brands": [], "calls": 0, "credits_remaining": None, "stopped": None}
    if not key:
        report["stopped"] = "no CONTEXT_DEV_API_KEY"
        return report
    limit = max(0, min(limit, MAX_LIMIT))
    if brands is None:
        todo = stored.unchecked_brands(db, limit)
    else:
        names = list(dict.fromkeys(name.strip() for name in brands if name.strip()))
        done = stored.get_many(db, names)
        todo = [name for name in names if name not in done][:limit]
    failures = 0
    for name in todo:
        if not ASKABLE[0] <= len(name) <= ASKABLE[1]:
            stored.put(db, name, status="none", checked_at=now())
            report["brands"].append({"brand": name, "status": "none", "why": "Context.dev cannot take this name"})
            continue
        try:
            report["calls"] += 1
            status, body = _post({"type": "by_name", "name": name, "country_gl": "fi"}, key)
        except (OSError, ValueError):
            status, body = None, {}
        left = _remaining(body)
        if left is not None:
            report["credits_remaining"] = left
        if status in STOP_STATUSES:
            report["stopped"] = f"Context.dev answered {status}"
            break
        brand = body.get("brand") if status == 200 else None
        if isinstance(brand, dict):
            url, background = pick_logo(brand.get("logos"))
            ok = url is not None and matches(name, brand.get("title"), brand.get("domain"))
            if ok:
                stored.put(db, name, status="found", checked_at=now(), logo_url=url,
                           background=background, domain=str(brand.get("domain") or "") or None)
            else:
                stored.put(db, name, status="none", checked_at=now())
            report["brands"].append({"brand": name, "status": "found" if ok else "none",
                                     "title": brand.get("title"), "domain": brand.get("domain")})
            failures = 0
        elif status == 422 or (status in (400, 404) and "NOT_FOUND" in onboarding._codes(body)):
            stored.put(db, name, status="none", checked_at=now())
            report["brands"].append({"brand": name, "status": "none", "why": "Context.dev does not know it"})
            failures = 0
        else:
            failures += 1                  # network, timeout, 5xx: nothing stored, ask again later
            report["brands"].append({"brand": name, "status": "not_checked", "why": f"failed ({status})"})
            if failures >= MAX_FAILURES:
                report["stopped"] = "three failed calls in a row"
                break
        if left is not None and left < CREDIT_FLOOR:
            report["stopped"] = f"fewer than {CREDIT_FLOOR} credits remain"
            break
    return report


def _limit(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError("a whole number") from None
    if not 1 <= value <= MAX_LIMIT:
        raise argparse.ArgumentTypeError(f"1 to {MAX_LIMIT}")
    return value


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m gateway.brand_logos",
        description="Ask Context.dev for the logos of catalog brands that have none yet (costs credits).")
    parser.add_argument("--limit", type=_limit, default=DEFAULT_LIMIT,
                        help=f"at most this many brands (default {DEFAULT_LIMIT}, at most {MAX_LIMIT})")
    parser.add_argument("--brand", action="append", help="ask about this brand (repeat it); else the biggest brands")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    from store.db import get_db
    report = warm(get_db(), (os.environ.get("CONTEXT_DEV_API_KEY") or "").strip(),
                  limit=args.limit, brands=args.brand)
    for row in report["brands"]:
        print(f"{row['brand']}: {row['status']}"
              + (f" ({row.get('domain')})" if row.get("domain") else "")
              + (f" - {row['why']}" if row.get("why") else ""))
    print(f"calls: {report['calls']}; credits left: {report['credits_remaining']}; "
          f"stopped: {report['stopped'] or 'no'}")
    return 0 if report["stopped"] in (None, f"fewer than {CREDIT_FLOOR} credits remain") else 1


if __name__ == "__main__":
    raise SystemExit(main())
