"""Users, password sign-in and sessions (#270).

- Passwords: hashlib.scrypt with a per-user salt; never stored or logged in clear.
- Sessions: a random token in an httpOnly, Secure, SameSite=Strict cookie; only its SHA-256
  is stored; 12 hours. Changing the password ends every other session.
- Roles: approver (approves and rejects), chef (asks and edits), viewer (reads).
- An account belongs to one kitchen. `--kitchen all` on the command line makes one for every
  kitchen and the supplier's view: what the open demo's person has, behind a sign-in.
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


def create_user(db, email: str, password: str, *, name: str, role: str, kitchen_id: str | None) -> dict:
    """`kitchen_id` None: an account for every kitchen and the supplier's view (the stage account)."""
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


# ---- command line (#270): accounts are made on the server, passwords are typed, never passed ----

def main(argv=None) -> int:
    """python -m gateway.users add --email a@b.c --role approver   (asks for the password twice)
    python -m gateway.users list
    python -m gateway.users remove --email a@b.c"""
    import argparse
    import getpass

    parser = argparse.ArgumentParser(description="Accounts for the gateway sign-in.")
    sub = parser.add_subparsers(dest="command", required=True)
    add = sub.add_parser("add", help="create an account; the password is typed, not an argument")
    add.add_argument("--email", required=True)
    add.add_argument("--name", default=None)
    add.add_argument("--role", choices=ROLES, default="viewer")
    add.add_argument("--kitchen", default="demo-kitchen",
                     help="the account's kitchen; 'all' = every kitchen and the supplier's view, "
                          "as the open demo's person has (for the stage account)")
    sub.add_parser("list", help="emails, roles and kitchens (never passwords)")
    remove = sub.add_parser("remove", help="delete an account and end its sessions")
    remove.add_argument("--email", required=True)
    args = parser.parse_args(argv)

    from store.db import get_db
    db = get_db()
    if args.command == "list":
        for user in db.users.find({}, {"name": 1, "role": 1, "kitchen_id": 1}).sort("_id", 1):
            print(user["_id"], user["role"], user["kitchen_id"] or "all", user.get("name") or "")
        return 0
    email = args.email.strip().lower()
    if args.command == "remove":
        user = db.users.find_one({"_id": email})
        if user and user["role"] == "approver" and db.users.count_documents(
                {"role": "approver", "kitchen_id": user["kitchen_id"]}) <= 1:
            print("this is the last approver of", user["kitchen_id"] or "all kitchens", "- add another approver first")
            return 1
        gone = db.users.delete_one({"_id": email}).deleted_count
        db.sessions.delete_many({"email": email})
        print("removed" if gone else "no such account")
        return 0 if gone else 1
    if db.users.find_one({"_id": email}):
        print("this email already has an account; remove it first to set a new password")
        return 1
    first = getpass.getpass("Password (at least 10 characters): ")
    if first != getpass.getpass("Again: "):
        print("the two passwords differ; nothing was created")
        return 1
    try:
        user = create_user(db, email, first, name=args.name or email, role=args.role,
                           kitchen_id=None if args.kitchen == "all" else args.kitchen)
    except AuthError as exc:
        print(str(exc))
        return 1
    print("created", user["email"], user["role"], user["kitchen_id"] or "all")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
