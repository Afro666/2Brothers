"""Signed order receipt (#290): what a person approved, tied to the signed offer they saw."""

import copy
import json

import jwt as pyjwt
import pytest

from gateway import signing, verify_offer
from gateway.tests.test_gateway_app import AGENT, HUMAN, K, env  # noqa: F401 (fixture)
from gateway.verify_offer import check, check_receipt

ROUTINE = {"product_ids": ["462775"], "quantity": "40", "unit": "L", "requested_date": "2026-11-16"}


@pytest.fixture(autouse=True)
def fresh_key():
    signing._cache.clear()
    yield
    signing._cache.clear()


def placed(client, key="p1"):
    r = client.post(K + "/proposals", headers=AGENT, json={**ROUTINE, "idempotency_key": key})
    assert r.status_code == 200, r.text
    p = r.json()
    done = client.post(f"{K}/proposals/{p['proposal_id']}/approve", headers=HUMAN,
                       json={"expected_total": p["expected_total"], "idempotency_key": "a-" + key})
    assert done.status_code == 200, done.text
    return p, done.json()


def test_a_placed_order_carries_a_receipt_that_verifies_against_the_public_jwks(env):
    client, _, db = env
    keys = client.get("/.well-known/jwks.json").json()
    p, order = placed(client)
    ok, message, claims = check_receipt(order, keys)
    assert ok, message
    assert claims["type"] == "order_receipt" and claims["iss"] == signing.ISSUER
    assert claims["sub"] == order["order_id"] and claims["kitchen_id"] == "demo-kitchen"
    assert claims["offer_id"] == p["offer_id"] and claims["offer_hash"] == p["offer_hash"]
    assert claims["expected_total"] == order["expected_total"] and claims["currency"] == "EUR"
    assert claims["lines"] == [{"product_id": ln["product_id"], "quantity": str(ln["quantity"]), "unit": ln["unit"]}
                               for ln in order["lines"]]
    assert claims["approved_by"] == db.orders.find_one({})["approved_by"]
    assert isinstance(claims["iat"], int) and "exp" not in claims
    header = pyjwt.get_unverified_header(order["receipt"])
    assert header["alg"] == "EdDSA" and header["kid"] == keys["keys"][0]["kid"]   # the offers' key


def test_the_receipt_never_claims_that_the_supplier_accepted(env):
    client, _, _ = env
    _, order = placed(client)
    _, _, claims = check_receipt(order, client.get("/.well-known/jwks.json").json())
    assert claims["supplier_outcome"] == "NOT_SENT"
    assert "not" in claims["supplier_note"].lower() and claims["supplier_must_confirm"] == []
    assert not {"status", "outcome"} & set(claims)        # no "SENT" or "CONFIRMED" under our signature


def test_every_order_answer_carries_the_same_receipt(env):
    client, _, _ = env
    p, order = placed(client)
    assert order["receipt"]
    one = client.get(f"{K}/orders/{order['order_id']}", headers=HUMAN).json()
    listed = client.get(K + "/orders", headers=HUMAN).json()["orders"][0]
    again = client.post(f"{K}/proposals/{p['proposal_id']}/approve", headers=HUMAN,
                        json={"expected_total": p["expected_total"], "idempotency_key": "a-p1"}).json()
    tool = client.post("/tools/place_order", headers=AGENT, json={
        "offer_id": p["offer_id"], "expected_total": p["expected_total"], "idempotency_key": "x"}).json()
    assert one["receipt"] == listed["receipt"] == again["receipt"] == tool["receipt"] == order["receipt"]


def test_a_changed_receipt_fails_verification(env):
    client, _, _ = env
    keys = client.get("/.well-known/jwks.json").json()
    p, order = placed(client)
    more = copy.deepcopy(order)
    more["lines"][0]["quantity"] = "400"
    assert check_receipt(more, keys)[0] is False                                  # a line changed
    cheaper = {**order, "expected_total": "0.01"}
    assert check_receipt(cheaper, keys)[0] is False                               # the total changed
    assert check_receipt({**order, "order_id": "another"}, keys)[0] is False      # another order
    head, body, sig = order["receipt"].split(".")
    forged = ".".join([head, body, sig[:-4] + ("AAAA" if not sig.endswith("AAAA") else "BBBB")])
    assert check_receipt({**order, "receipt": forged}, keys)[0] is False          # the signature changed
    claims = pyjwt.decode(order["receipt"], options={"verify_signature": False})
    other = signing.Ed25519PrivateKey.generate()
    fake = pyjwt.encode({**claims, "supplier_outcome": "ACCEPTED"}, other, algorithm="EdDSA",
                        headers={"kid": keys["keys"][0]["kid"]})
    assert check_receipt({**order, "receipt": fake}, keys)[0] is False            # another key
    assert check_receipt({**order, "receipt": p["signature"]}, keys)[0] is False  # an offer is not a receipt
    assert check({**p, "signature": order["receipt"]}, keys, check_expiry=False)[0] is False   # nor the reverse
    assert check_receipt({**order, "receipt": None}, keys)[0] is False


def test_a_signing_failure_is_logged_and_the_order_is_still_placed(env, monkeypatch, caplog):
    client, _, db = env

    def broken(*a, **k):
        raise ValueError("secret-seed-must-not-appear")
    monkeypatch.setattr(signing, "sign_receipt", broken)
    with caplog.at_level("WARNING", logger="gateway.service"):
        _, order = placed(client)      # still 200
    assert order["receipt"] is None and order["outcome"] == "CONFIRMED"
    assert "receipt signing failed: ValueError" in caplog.text
    assert "secret-seed" not in caplog.text
    assert db.orders.find_one({}).get("receipt") is None


def test_an_order_from_before_receipts_answers_null(env):
    client, _, db = env
    _, order = placed(client)
    db.orders.update_one({}, {"$unset": {"receipt": ""}})
    assert client.get(f"{K}/orders/{order['order_id']}", headers=HUMAN).json()["receipt"] is None


def test_the_command_line_checks_a_receipt(env, monkeypatch, tmp_path, capsys):
    client, _, _ = env
    keys = client.get("/.well-known/jwks.json").json()
    _, order = placed(client)

    class Answer:
        def json(self):
            return keys
    monkeypatch.setattr(verify_offer.httpx, "get", lambda url, timeout: Answer())
    good = tmp_path / "order.json"
    good.write_text(json.dumps(order), encoding="utf-8")
    assert verify_offer.main(["--base-url", "http://gateway", "--receipt", str(good)]) == 0
    assert '"supplier_outcome": "NOT_SENT"' in capsys.readouterr().out
    bad = tmp_path / "changed.json"
    bad.write_text(json.dumps({**order, "expected_total": "1.00"}), encoding="utf-8")
    assert verify_offer.main(["--base-url", "http://gateway", "--receipt", str(bad)]) == 1
