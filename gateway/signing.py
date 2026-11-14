"""Signed offers (#290): an outside agent can check our price and stock claims, and a human
"yes" covers exactly one order.

- Every offer is a JWS (EdDSA / Ed25519): products, prices, stock state (confirmed or
  unknown), as-of time, valid-until, total, and `offer_hash` over the exact lines and total.
- The public key is at `/.well-known/jwks.json`. `python -m gateway.verify_offer` checks one.
- The approval stores the `offer_hash` it approved; placement refuses any other offer.

Key: `GATEWAY_SIGNING_KEY` (base64 of a 32-byte Ed25519 seed) from the server .env. Without
it, a key is created once and kept in the database, so offers still verify after a restart.
"""

from __future__ import annotations

import base64
from datetime import datetime
import hashlib
import json
import os

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ISSUER = "trusted-kitchen-buyer"
_cache: dict[str, Ed25519PrivateKey] = {}


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _private(db) -> Ed25519PrivateKey:
    if "key" in _cache:
        return _cache["key"]
    seed_b64 = os.environ.get("GATEWAY_SIGNING_KEY", "")
    if seed_b64:
        seed = base64.b64decode(seed_b64)
        if len(seed) != 32:
            raise ValueError("GATEWAY_SIGNING_KEY must be base64 of 32 bytes")
    else:
        doc = db.gateway_keys.find_one({"_id": "offer-signing"})
        if doc is None:
            raw = Ed25519PrivateKey.generate().private_bytes(
                serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
            try:
                db.gateway_keys.insert_one({"_id": "offer-signing", "seed": raw})
            except Exception:
                pass                       # another worker created it first: read that one
            doc = db.gateway_keys.find_one({"_id": "offer-signing"})
        seed = bytes(doc["seed"])
    _cache["key"] = Ed25519PrivateKey.from_private_bytes(seed)
    return _cache["key"]


def _public_raw(db) -> bytes:
    return _private(db).public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def kid(db) -> str:
    return hashlib.sha256(_public_raw(db)).hexdigest()[:16]


def jwks(db) -> dict:
    return {"keys": [{"kty": "OKP", "crv": "Ed25519", "x": _b64url(_public_raw(db)),
                      "kid": kid(db), "use": "sig", "alg": "EdDSA"}]}


def _num(value) -> str | None:
    """One spelling per number, so "1.40", "1.4" and 1.4 hash the same."""
    if value is None:
        return None
    from decimal import Decimal
    d = Decimal(str(value)).normalize()
    return f"{d:f}"


def offer_hash(simulation: dict, requested_date: str) -> str:
    """One hash over what a person approves: every line (product, quantity, unit, price),
    the total and the delivery date. Anything else may differ; these may not."""
    core = {"requested_date": requested_date, "expected_total": _num(simulation.get("expected_total")),
            "lines": [[ln.get("product_id"), _num(ln.get("quantity")), ln.get("unit"), _num(ln.get("unit_price"))]
                      for ln in simulation.get("lines", [])]}
    return hashlib.sha256(json.dumps(core, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def sign_offer(db, *, offer_id: str, kitchen_id: str, simulation: dict, requested_date: str,
               as_of: datetime, valid_until: datetime) -> tuple[str, str]:
    """(compact JWS, offer_hash)."""
    digest = offer_hash(simulation, requested_date)
    claims = {
        "iss": ISSUER, "sub": offer_id, "kitchen_id": kitchen_id, "requested_date": requested_date,
        "iat": int(as_of.timestamp()), "exp": int(valid_until.timestamp()),
        "source": "Valio Aimo price and availability API, read at iat",
        "currency": "EUR", "expected_total": simulation.get("expected_total"),
        "lines": [{"product_id": ln.get("product_id"), "quantity": str(ln.get("quantity")), "unit": ln.get("unit"),
                   "unit_price": str(ln.get("unit_price")),
                   "stock": "unknown" if ln.get("unknown_stock") is not False else "confirmed"}
                  for ln in simulation.get("lines", [])],
        "offer_hash": digest,
    }
    token = jwt.encode(claims, _private(db), algorithm="EdDSA", headers={"kid": kid(db)})
    return token, digest


def verify(token: str, keys: dict, *, check_expiry: bool = True) -> dict:
    """Claims of a valid offer signature; raises jwt.InvalidTokenError otherwise."""
    header = jwt.get_unverified_header(token)
    key = next((k for k in keys.get("keys", []) if k.get("kid") == header.get("kid")), None)
    if key is None:
        raise jwt.InvalidTokenError("no key with this kid in the JWKS")
    public = jwt.algorithms.OKPAlgorithm.from_jwk(json.dumps(key))
    return jwt.decode(token, public, algorithms=["EdDSA"], issuer=ISSUER,
                      options={"verify_exp": check_expiry})
