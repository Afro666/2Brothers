"""Valio's own words (challenge Discord, 14 Nov): an availability of 999999 or more means
Valio does not know the stock "and our current logic allows ordering any quantity"; empty
means not available. A person's approval places unknown stock (#1221); the proposal names
the products each supplier must confirm, and the signed receipt marks each line's stock.
Contract: docs/contract.md, "Reason codes" (STOCK_UNKNOWN) and "Signed order receipt"."""

import jwt
import pytest

pytest.importorskip("mongomock")
pytest.importorskip("fastapi")

from gateway import signing  # noqa: E402
from gateway.tests.test_gateway_app import HUMAN, K, env, milk  # noqa: E402, F401
from gateway.tests.test_multi_supplier import OAT, BAKERY_DAYS, approve, bakery, propose  # noqa: E402


def test_the_milk_case_names_what_valio_must_confirm_and_the_receipt_marks_it(env):
    """S01, 1,000 L: 51 L confirmed (462775) + 949 L with Valio's filler (463335)."""
    client, _, db = env
    p = milk(client, quantity="1000")
    assert [(ln["product_id"], ln["quantity"], ln["unknown_stock"]) for ln in p["lines"]] == [
        ("462775", "51", False), ("463335", "949", True)]
    assert "Valio must confirm stock for: milk 463335." in p["mandate"]["reasons"]
    r = approve(client, p, "v1")
    assert r.status_code == 200, r.text
    assert r.json()["supplier_must_confirm"] == ["sup-valio"]
    claims = signing.verify(r.json()["receipt"], signing.jwks(db))
    assert claims["supplier_must_confirm"] == ["sup-valio"]
    assert [(ln["product_id"], ln["stock"]) for ln in claims["lines"]] == [
        ("462775", "confirmed"), ("463335", "unknown")]


def test_a_confirmed_basket_has_no_must_confirm_sentence_and_confirmed_receipt_lines(env):
    client, _, db = env
    p = milk(client, quantity="51")
    assert not any("must confirm stock for" in r for r in p["mandate"]["reasons"])
    r = approve(client, p, "v2")
    assert r.status_code == 200, r.text
    claims = signing.verify(r.json()["receipt"], signing.jwks(db))
    assert {ln["stock"] for ln in claims["lines"]} == {"confirmed"}


def test_a_manual_supplier_is_named_by_its_own_name(env):
    client, _, db = env
    bakery(db, BAKERY_DAYS, adapter="manual")
    p = propose(client, ids=("462775", OAT))
    assert "Leipomo Demo must confirm stock for: Oat drink 1 L." in p["mandate"]["reasons"]
    assert not any(r.startswith("Valio must confirm stock for") for r in p["mandate"]["reasons"])


def test_a_receipt_with_stock_on_its_lines_still_matches_its_order(env):
    client, _, db = env
    r = approve(client, milk(client, quantity="1000"), "v3")
    order = client.get(f"{K}/orders/{r.json()['order_id']}", headers=HUMAN).json()
    claims = jwt.decode(order["receipt"], options={"verify_signature": False})
    assert signing.receipt_matches(order, claims)
