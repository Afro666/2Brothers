"""Signed offers (#290): verifiable claims, tampering refused, approval bound to one offer."""

import copy

import pytest

from gateway import signing
from gateway.tests.test_gateway_app import AGENT, HUMAN, K, env  # noqa: F401 (fixture)
from gateway.verify_offer import check

ROUTINE = {"product_ids": ["462775"], "quantity": "40", "unit": "L", "requested_date": "2026-11-16"}


@pytest.fixture(autouse=True)
def fresh_key():
    signing._cache.clear()
    yield
    signing._cache.clear()


def proposal(client, key="p1", **changes):
    r = client.post(K + "/proposals", headers=AGENT, json={**ROUTINE, **changes, "idempotency_key": key})
    assert r.status_code == 200, r.text
    return r.json()


def test_offer_verifies_against_the_public_jwks_without_a_token(env):
    client, _, _ = env
    keys = client.get("/.well-known/jwks.json").json()
    assert keys["keys"][0]["alg"] == "EdDSA" and "d" not in keys["keys"][0]      # public part only
    p = proposal(client)
    ok, message, claims = check(p, keys, check_expiry=False)
    assert ok, message
    assert claims["sub"] == p["offer_id"] and claims["kitchen_id"] == "demo-kitchen"
    assert claims["lines"][0]["stock"] == "confirmed" and claims["expected_total"] == p["expected_total"]


def test_unknown_stock_is_signed_as_unknown_never_as_confirmed(env):
    client, _, _ = env
    p = proposal(client, product_ids=["463335"], quantity="10")
    _, _, claims = check(p, client.get("/.well-known/jwks.json").json(), check_expiry=False)
    assert claims["lines"][0]["stock"] == "unknown"


def test_a_tampered_offer_is_refused(env):
    client, _, _ = env
    keys = client.get("/.well-known/jwks.json").json()
    p = proposal(client)
    cheaper = copy.deepcopy(p)
    cheaper["lines"][0]["unit_price"] = "0.10"
    assert check(cheaper, keys, check_expiry=False)[0] is False                  # content changed
    forged = copy.deepcopy(p)
    head, body, sig = forged["signature"].split(".")
    forged["signature"] = ".".join([head, body, sig[:-4] + ("AAAA" if not sig.endswith("AAAA") else "BBBB")])
    assert check(forged, keys, check_expiry=False)[0] is False                   # signature changed
    other = signing.Ed25519PrivateKey.generate()
    import jwt as pyjwt
    fake = pyjwt.encode({"iss": signing.ISSUER, "sub": "x"}, other, algorithm="EdDSA", headers={"kid": keys["keys"][0]["kid"]})
    assert check({**p, "signature": fake}, keys, check_expiry=False)[0] is False  # another key
    assert check({**p, "signature": None}, keys)[0] is False


def test_the_same_numbers_hash_the_same_in_any_spelling():
    a = {"expected_total": "116.68", "lines": [{"product_id": "1", "quantity": "40", "unit": "ST", "unit_price": "2.50"}]}
    b = {"expected_total": 116.68, "lines": [{"product_id": "1", "quantity": 40, "unit": "ST", "unit_price": 2.5}]}
    assert signing.offer_hash(a, "2026-11-16") == signing.offer_hash(b, "2026-11-16")
    assert signing.offer_hash(a, "2026-11-16") != signing.offer_hash(a, "2026-11-17")


def test_an_approval_for_one_offer_cannot_place_another(env):
    client, _, db = env
    p = proposal(client)
    done = client.post(f"{K}/proposals/{p['proposal_id']}/approve", headers=HUMAN,
                       json={"expected_total": p["expected_total"], "idempotency_key": "a1"})
    assert done.status_code == 200, done.text
    order = db.orders.find_one({})
    assert order["offer_hash"] == p["offer_hash"]
    ok = client.post("/tools/place_order", headers=AGENT, json={
        "offer_id": p["offer_id"], "expected_total": p["expected_total"], "idempotency_key": "x"})
    assert ok.status_code == 200
    db.offers.update_one({"_id": p["offer_id"]}, {"$set": {"offer_hash": "0" * 64}})   # a different offer under the same id
    bad = client.post("/tools/place_order", headers=AGENT, json={
        "offer_id": p["offer_id"], "expected_total": p["expected_total"], "idempotency_key": "x"})
    assert bad.status_code == 409 and bad.json()["error"]["code"] == "APPROVAL_MISMATCH"


def test_a_signing_failure_is_logged_and_the_quote_still_works(env, monkeypatch, caplog):
    client, _, _ = env

    def broken(*a, **k):
        raise ValueError("secret-seed-must-not-appear")
    monkeypatch.setattr(signing, "sign_offer", broken)
    with caplog.at_level("WARNING", logger="gateway.service"):
        p = proposal(client)    # still 200
    assert p.get("signature") is None
    assert "offer signing failed: ValueError" in caplog.text
    assert "secret-seed" not in caplog.text


def test_a_signing_failure_still_sets_offer_hash_and_keeps_approval_mismatch(env, monkeypatch):
    """#753: no signature must not mean no APPROVAL_MISMATCH check."""
    client, _, db = env

    def broken(*a, **k):
        raise ValueError("no key")
    monkeypatch.setattr(signing, "sign_offer", broken)
    p = proposal(client)
    assert p.get("signature") is None and p["offer_hash"]
    done = client.post(f"{K}/proposals/{p['proposal_id']}/approve", headers=HUMAN,
                       json={"expected_total": p["expected_total"], "idempotency_key": "a1"})
    assert done.status_code == 200, done.text
    assert db.orders.find_one({})["offer_hash"] == p["offer_hash"]
    db.offers.update_one({"_id": p["offer_id"]}, {"$set": {"offer_hash": "0" * 64}})
    bad = client.post("/tools/place_order", headers=AGENT, json={
        "offer_id": p["offer_id"], "expected_total": p["expected_total"], "idempotency_key": "x"})
    assert bad.status_code == 409 and bad.json()["error"]["code"] == "APPROVAL_MISMATCH"
