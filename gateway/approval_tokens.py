"""Personal approval tokens (decision 2026-11-14): one person approves from their own chat.

- Stands for one person (an account in `users`, role approver) and one kitchen.
- Only approve and reject (plus read). It never proposes, so the credential that proposes
  is never the one that approves. Everything else a person does in the web stays a session's.
- Short-lived: 8 hours by default, at most 24. Revocable. Expired or revoked -> 401.
- Shown once at creation; only the SHA-256 is stored, plus an 8-character prefix for display.
- Agent and kitchen API tokens (gateway/tokens.py) still never approve.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import secrets
from uuid import uuid4

PREFIX = "tka_"
KIND = "personal_approval"
VIA = "personal_token"
DEFAULT_HOURS, MAX_HOURS = 8, 24
CLI = "operator-cli"
TOUCH_EVERY = timedelta(minutes=1)


class ApprovalTokenError(ValueError):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code = status, code


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _aware(value: datetime | None) -> datetime | None:
    return value.replace(tzinfo=timezone.utc) if value is not None and value.tzinfo is None else value


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _iso(value: datetime | None) -> str | None:
    return _aware(value).isoformat() if value is not None else None


def _out(doc: dict) -> dict:
    return {"token_id": doc["_id"], "kind": KIND, "name": doc["name"], "person": doc["person"],
            "kitchen_id": doc["kitchen_id"], "prefix": doc["prefix"],
            "created_at": _iso(doc["created_at"]), "created_by": doc["created_by"],
            "expires_at": _iso(doc["expires_at"]), "last_used_at": _iso(doc.get("last_used_at")),
            "revoked_at": _iso(doc.get("revoked_at"))}


def hours_of(value) -> int:
    if value is None:
        return DEFAULT_HOURS
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_HOURS:
        raise ApprovalTokenError(422, "INVALID_REQUEST", f"hours: a whole number from 1 to {MAX_HOURS}")
    return value


def create(db, person: str, kitchen_id: str, created_by: str, *, hours=None, name=None,
           now: datetime | None = None) -> dict:
    """A new token for `person` in `kitchen_id`. The account must exist and be an approver of
    that kitchen (or of every kitchen). The answer holds `token`: the only time it leaves."""
    hours = hours_of(hours)
    name = "chat" if name is None else name
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 80:
        raise ApprovalTokenError(422, "INVALID_REQUEST", "name: 1 to 80 characters")
    email = (person or "").strip().lower()
    user = db.users.find_one({"_id": email}) if email else None
    if user is None:
        raise ApprovalTokenError(404, "UNKNOWN_PERSON", "no account with this email")
    if user["role"] != "approver":
        raise ApprovalTokenError(403, "ROLE_REQUIRED", "only an approver can have an approval token")
    if user["kitchen_id"] is not None and user["kitchen_id"] != kitchen_id:
        raise ApprovalTokenError(403, "KITCHEN_SCOPE", "this person belongs to another kitchen")
    token = PREFIX + secrets.token_urlsafe(32)
    now = now or datetime.now(timezone.utc)
    doc = {"_id": uuid4().hex, "kind": KIND, "name": name.strip(), "person": email,
           "kitchen_id": kitchen_id, "hash": _hash(token), "prefix": token[:8],
           "created_at": now, "created_by": created_by, "expires_at": now + timedelta(hours=hours),
           "last_used_at": None, "revoked_at": None}
    db.approval_tokens.create_index("hash", unique=True)
    db.approval_tokens.insert_one(doc)
    return {**_out(doc), "token": token}


def list_tokens(db, kitchen_id: str | None = None, person: str | None = None) -> list[dict]:
    """`person` set: only that person's own tokens (the web); None: all (the operator command)."""
    query = {} if kitchen_id is None else {"kitchen_id": kitchen_id}
    if person is not None:
        query["person"] = person.strip().lower()
    return [_out(d) for d in db.approval_tokens.find(query).sort("created_at", -1)]


def revoke(db, kitchen_id: str | None, token_id: str, now: datetime | None = None,
           person: str | None = None) -> dict | None:
    """`kitchen_id` None: any kitchen (the operator command). `person` set: only their own."""
    query = {"_id": token_id} if kitchen_id is None else {"_id": token_id, "kitchen_id": kitchen_id}
    if person is not None:
        query["person"] = person.strip().lower()
    doc = db.approval_tokens.find_one(query)
    if doc is None:
        return None
    if doc.get("revoked_at") is None:
        now = now or datetime.now(timezone.utc)
        db.approval_tokens.update_one({"_id": token_id}, {"$set": {"revoked_at": now}})
        doc["revoked_at"] = now
    return _out(doc)


def verify(db, token: str, now: datetime | None = None) -> tuple[dict, dict] | None:
    """(token row, the person's account now), or None: unknown, revoked, expired, an
    account that is gone, or an account now in another kitchen. Never raises on a bad token."""
    if not isinstance(token, str) or not token.startswith(PREFIX) or len(token) > 200:
        return None
    doc = db.approval_tokens.find_one({"hash": _hash(token), "revoked_at": None})
    if doc is None:
        return None
    now = now or datetime.now(timezone.utc)
    if _aware(doc["expires_at"]) <= now:
        return None
    user = db.users.find_one({"_id": doc["person"]})
    if user is None:
        return None
    if user.get("kitchen_id") is not None and user["kitchen_id"] != doc["kitchen_id"]:
        return None   # moved to another kitchen since the token was made
    last = _aware(doc.get("last_used_at"))
    if last is None or now - last > TOUCH_EVERY:
        db.approval_tokens.update_one({"_id": doc["_id"]}, {"$set": {"last_used_at": now}})
    return doc, user
