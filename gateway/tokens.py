"""API tokens per kitchen (#271): for Claude over MCP, scripts and other agents.

- Shown once at creation; only the SHA-256 is stored, plus an 8-character prefix for display.
- Scopes: `kitchen:read`, `kitchen:propose`. `kitchen:approve` can never be on a token:
  approving is a person's act in the inbox (docs/contract.md, trust rule).
- One token = one kitchen. Revoked or unknown -> 401.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import secrets
from uuid import uuid4

SCOPES = ("kitchen:read", "kitchen:propose")
PREFIX = "tkb_"
TOUCH_EVERY = timedelta(minutes=1)   # last_used_at is written at most once a minute


class TokenError(ValueError):
    pass


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _out(doc: dict) -> dict:
    return {"token_id": doc["_id"], "name": doc["name"], "scopes": doc["scopes"],
            "prefix": doc["prefix"], "created_at": doc["created_at"].isoformat(),
            "created_by": doc["created_by"],
            "last_used_at": doc["last_used_at"].isoformat() if doc.get("last_used_at") else None,
            "revoked_at": doc["revoked_at"].isoformat() if doc.get("revoked_at") else None}


def create(db, kitchen_id: str, name: str, scopes: list[str], created_by: str,
           now: datetime | None = None) -> dict:
    name = (name or "").strip()
    if not name or len(name) > 80:
        raise TokenError("name: 1 to 80 characters")
    if not scopes or not isinstance(scopes, list):
        raise TokenError("scopes: at least one of " + ", ".join(SCOPES))
    if "kitchen:approve" in scopes:
        raise TokenError("kitchen:approve cannot be given to a token: only a person approves")
    unknown = sorted(set(scopes) - set(SCOPES))
    if unknown:
        raise TokenError("unknown scopes: " + ", ".join(unknown))
    token = PREFIX + secrets.token_urlsafe(32)
    now = now or datetime.now(timezone.utc)
    doc = {"_id": uuid4().hex, "kitchen_id": kitchen_id, "name": name,
           "scopes": sorted(set(scopes)), "hash": _hash(token), "prefix": token[:8],
           "created_at": now, "created_by": created_by, "last_used_at": None, "revoked_at": None}
    db.api_tokens.create_index("hash", unique=True)
    db.api_tokens.insert_one(doc)
    return {**_out(doc), "token": token}     # the only time the secret leaves the gateway


def list_tokens(db, kitchen_id: str) -> list[dict]:
    return [_out(d) for d in db.api_tokens.find({"kitchen_id": kitchen_id}).sort("created_at", -1)]


def revoke(db, kitchen_id: str, token_id: str, now: datetime | None = None) -> dict | None:
    now = now or datetime.now(timezone.utc)
    doc = db.api_tokens.find_one({"_id": token_id, "kitchen_id": kitchen_id})
    if doc is None:
        return None
    if doc.get("revoked_at") is None:
        db.api_tokens.update_one({"_id": token_id}, {"$set": {"revoked_at": now}})
        doc["revoked_at"] = now
    return _out(doc)


def verify(db, token: str, now: datetime | None = None) -> dict | None:
    """The active token's record, or None. Never raises on a bad token."""
    if not token or not token.startswith(PREFIX) or len(token) > 200:
        return None
    doc = db.api_tokens.find_one({"hash": _hash(token), "revoked_at": None})
    if doc is None:
        return None
    now = now or datetime.now(timezone.utc)
    last = doc.get("last_used_at")
    if last is not None and last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    if last is None or now - last > TOUCH_EVERY:
        db.api_tokens.update_one({"_id": doc["_id"]}, {"$set": {"last_used_at": now}})
    return doc
