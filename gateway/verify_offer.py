"""Verify one signed offer or one signed order receipt against a gateway's public key (#290).

    python -m gateway.verify_offer --base-url https://<host>/gateway --offer offer.json
    python -m gateway.verify_offer --base-url https://<host>/gateway --receipt order.json

`offer.json` is what `get_offer`, `simulate_order` or a proposal returned (it has
`signature`). `order.json` is one order answer (it has `receipt`). Prints the signed
claims; exit code 1 when the signature, the issuer, the expiry or the content does not
match. No token is needed: the key is public.
"""

from __future__ import annotations

import argparse
import json
import sys

import httpx
import jwt

from gateway.signing import RECEIPT_TYPE, offer_hash, receipt_matches, verify


def check(offer: dict, keys: dict, *, check_expiry: bool = True) -> tuple[bool, str, dict]:
    token = offer.get("signature")
    if not token:
        return False, "the offer has no signature", {}
    try:
        claims = verify(token, keys, check_expiry=check_expiry)
    except jwt.ExpiredSignatureError:
        return False, "the offer has expired: ask for a new one", {}
    except jwt.InvalidTokenError as exc:
        return False, f"signature not valid: {exc}", {}
    if claims.get("type") == RECEIPT_TYPE or "requested_date" not in claims:
        return False, "this signature is not an offer", {}
    shown = offer_hash(offer, claims["requested_date"])
    if shown != claims["offer_hash"]:
        return False, "the lines or total shown differ from what was signed", claims
    return True, "valid: the lines, prices, stock states and total are what the gateway signed", claims


def check_receipt(order: dict, keys: dict) -> tuple[bool, str, dict]:
    token = order.get("receipt")
    if not token:
        return False, "the order has no receipt", {}
    try:
        claims = verify(token, keys)
    except jwt.InvalidTokenError as exc:
        return False, f"signature not valid: {exc}", {}
    if claims.get("type") != RECEIPT_TYPE:
        return False, "this signature is not an order receipt", {}
    if not receipt_matches(order, claims):
        return False, "the order, lines or total shown differ from what was signed", claims
    return True, ("valid: the gateway signed this order, its lines, total and approver. "
                  f"Supplier outcome: {claims.get('supplier_outcome')}"), claims


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", required=True)
    what = parser.add_mutually_exclusive_group(required=True)
    what.add_argument("--offer", help="path to the offer or proposal JSON")
    what.add_argument("--receipt", help="path to the order JSON (it has `receipt`)")
    parser.add_argument("--ignore-expiry", action="store_true")
    args = parser.parse_args(argv)
    keys = httpx.get(args.base_url.rstrip("/") + "/.well-known/jwks.json", timeout=20).json()
    with open(args.offer or args.receipt, encoding="utf-8") as f:
        shown = json.load(f)
    if args.receipt:
        ok, message, claims = check_receipt(shown, keys)
    else:
        ok, message, claims = check(shown, keys, check_expiry=not args.ignore_expiry)
    print(message)
    if claims:
        print(json.dumps(claims, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
