"""Users, password sign-in and sessions (#270).

- Passwords: hashlib.scrypt with a per-user salt; never stored or logged in clear.
- Sessions: a random token in an httpOnly, Secure, SameSite=Strict cookie; only its SHA-256
  is stored; 12 hours. Changing the password ends every other session.
- Roles: approver (approves and rejects), chef (asks and edits), viewer (reads).
- Five wrong passwords lock the account for five minutes.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import secrets

from pymongo.errors import DuplicateKeyError

ROLES = ("approver", "chef", "viewer")
COOKIE = "tkb_session"
SESSION_TTL = timedelta(hours=12)
MAX_FAILS, LOCK = 5, timedelta(minutes=5)
MIN_PASSWORD = 10
_SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1, "dklen": 32}


class AuthError(ValueError):
    def __init__(self, code: str, message: str, status: int = 401):
        super().__init__(message)
        self.code, self.status = code, status


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    return value.replace(tzinfo=timezone.utc) if value is not None and value.tzinfo is None else value


def _digest(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)


def _sha(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _check_password(password) -> str:
    if not isinstance(password, str) or len(password) < MIN_PASSWORD or len(password) > 200:
        raise AuthError("WEAK_PASSWORD", f"the password needs at least {MIN_PASSWORD} characters", 422)
    return password


def _out(user: dict) -> dict:
    return {"email": user["_id"], "name": user["name"], "role": user["role"], "kitchen_id": user["kitchen_id"]}


def create_user(db, email: str, password: str, *, name: str, role: str, kitchen_id: str) -> dict:
    email = (email or "").strip().lower()
    if "@" not in email or len(email) > 200:
        raise AuthError("INVALID_REQUEST", "email is not valid", 422)
    if role not in ROLES:
        raise AuthError("INVALID_REQUEST", "role must be one of " + ", ".join(ROLES), 422)
    salt = secrets.token_bytes(16)
    doc = {"_id": email, "name": (name or email).strip()[:100], "role": role, "kitchen_id": kitchen_id,
           "salt": salt, "password": _digest(_check_password(password), salt),
           "fails": 0, "locked_until": None, "created_at": _now()}
    db.users.insert_one(doc)
    return _out(doc)


def seed_user(db, email: str | None, password: str | None, kitchen_id: str) -> bool:
    """The first approver, from the server .env. Does nothing if unset or already there."""
    if not email or not password or db.users.find_one({"_id": email.strip().lower()}):
        return False
    try:
        create_user(db, email, password, name="Demo approver", role="approver", kitchen_id=kitchen_id)
    except DuplicateKeyError:   # a concurrent first login inserted it first
        return False
    return True


def _check_lock(user: dict, now: datetime) -> None:
    locked = _aware(user.get("locked_until"))
    if locked and locked > now:
        raise AuthError("ACCOUNT_LOCKED", "too many wrong passwords; try again in a few minutes", 429)


def _password_ok(user: dict, password) -> bool:
    return isinstance(password, str) and hmac.compare_digest(_digest(password, user["salt"]), user["password"])


def _count_fail(db, user: dict, now: datetime) -> None:
    fails = user.get("fails", 0) + 1
    change = {"fails": fails}
    if fails >= MAX_FAILS:
        change = {"fails": 0, "locked_until": now + LOCK}
    db.users.update_one({"_id": user["_id"]}, {"$set": change})


def login(db, email: str, password: str, now: datetime | None = None) -> tuple[dict, str]:
    """(user, session token). The same error for an unknown email and a wrong password."""
    now = now or _now()
    email = (email or "").strip().lower()
    user = db.users.find_one({"_id": email})
    if user is None:
        _digest(password if isinstance(password, str) else "", b"0" * 16)   # same work either way
        raise AuthError("INVALID_LOGIN", "wrong email or password")
    _check_lock(user, now)
    if not _password_ok(user, password):
        _count_fail(db, user, now)
        raise AuthError("INVALID_LOGIN", "wrong email or password")
    db.users.update_one({"_id": email}, {"$set": {"fails": 0, "locked_until": None}})
    token = secrets.token_urlsafe(32)
    db.sessions.insert_one({"_id": _sha(token), "email": email, "created_at": now, "expires_at": now + SESSION_TTL})
    return _out(user), token


def session_user(db, token: str | None, now: datetime | None = None) -> dict | None:
    if not token or len(token) > 200:
        return None
    session = db.sessions.find_one({"_id": _sha(token)})
    if session is None or _aware(session["expires_at"]) <= (now or _now()):
        return None
    user = db.users.find_one({"_id": session["email"]})
    return _out(user) if user else None


def logout(db, token: str | None) -> None:
    if token:
        db.sessions.delete_one({"_id": _sha(token)})


def change_password(db, email: str, current: str, new: str, keep_token: str | None = None,
                    now: datetime | None = None) -> None:
    """A wrong current password counts toward the lockout, as in login."""
    now = now or _now()
    user = db.users.find_one({"_id": email})
    if user is None:
        raise AuthError("INVALID_LOGIN", "the current password is wrong")
    _check_lock(user, now)
    if not _password_ok(user, current):
        _count_fail(db, user, now)
        raise AuthError("INVALID_LOGIN", "the current password is wrong")
    if current == new:
        raise AuthError("WEAK_PASSWORD", "the new password must differ from the current one", 422)
    salt = secrets.token_bytes(16)
    db.users.update_one({"_id": email}, {"$set": {"salt": salt, "password": _digest(_check_password(new), salt)}})
    keep = _sha(keep_token) if keep_token else None
    db.sessions.delete_many({"email": email, "_id": {"$ne": keep}})
