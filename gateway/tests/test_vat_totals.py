"""VAT per line and totals incl VAT (#1603): unknown VAT never becomes 0 % or the ex-VAT sum."""

from decimal import Decimal

import pytest

pytest.importorskip("mongomock")
pytest.importorskip("fastapi")

from bson.decimal128 import Decimal128  # noqa: E402

from gateway.tests.test_gateway_app import AGENT, HUMAN, K, env, milk  # noqa: E402, F401
from gateway.tests.test_multi_supplier import BAKERY_DAYS, OAT, bakery, propose  # noqa: E402
from store import orders  # noqa: E402


def drop_tax(fake, pid):
    for p in fake.price_data["products"]:
        if p["productId"] == pid:
            p.pop("tax", None)


def test_valio_lines_carry_the_live_rate_and_totals_incl_vat(env):
    client, _, _ = env
    p = milk(client, quantity="51")
    assert all((ln["vat_rate"], ln["vat_source"]) == ("13.5", "valio_price") for ln in p["lines"])
    assert p["vat_unknown"] == []
    assert Decimal(p["total_incl_vat"]) == Decimal(p["total_ex_vat"]) + Decimal(p["vat"])
    assert p["total_incl_vat"] != p["total_ex_vat"]
    (block,) = p["blocks"]
    assert (block["total_incl_vat"], block["vat_unknown"]) == (p["total_incl_vat"], [])


def test_a_price_without_tax_rate_takes_the_catalog_rate(env):
    client, fake, db = env
    drop_tax(fake, "462775")
    db.products.update_one({"_id": "462775"}, {"$set": {"vat_code": "MEDIUM", "vat_rate": "13.5"}})
    line = milk(client, quantity="51")["lines"][0]
    assert (line["product_id"], line["vat_rate"], line["vat_source"]) == ("462775", "13.5", "catalog")


def test_no_rate_anywhere_is_unknown_never_zero(env):
    client, fake, _ = env
    drop_tax(fake, "462775")                      # and the test catalog row has no vat_rate
    p = milk(client, quantity="51")
    line = p["lines"][0]
    assert (line["product_id"], line["vat_rate"], line["vat_source"]) == ("462775", None, None)
    assert p["vat"] is None and p["total_incl_vat"] is None
    assert p["vat_unknown"] == ["462775"]
    # The approve figure stays the ex-VAT sum plus what is known; it is never called incl VAT.
    assert p["expected_total"] == p["total_ex_vat"]
    assert any("VAT for Valio Aimo is not known" in r for r in p["mandate"]["reasons"])


def test_one_unknown_line_makes_incl_vat_unknown_and_keeps_the_known_vat_in_the_approve_figure(env):
    client, _, db = env
    bakery(db, BAKERY_DAYS)                       # the oat drink has no entered rate
    p = propose(client)
    assert p["vat_unknown"] == [OAT] and p["vat"] is None and p["total_incl_vat"] is None
    valio, bread = p["blocks"]
    assert valio["vat_unknown"] == [] and Decimal(valio["total_incl_vat"]) > Decimal(valio["total_ex_vat"])
    assert bread["vat_unknown"] == [OAT] and bread["total_incl_vat"] is None
    known_vat = Decimal(valio["vat"])
    assert Decimal(p["expected_total"]) == Decimal(p["total_ex_vat"]) + known_vat


def test_an_entered_rate_on_an_own_product_is_used(env):
    client, _, db = env
    bakery(db, BAKERY_DAYS)
    db.products.update_one({"_id": OAT}, {"$set": {"vat_rate": "13.5", "vat_source": "entered"}})
    p = propose(client)
    oat = next(ln for ln in p["lines"] if ln["product_id"] == OAT)
    assert (oat["vat_rate"], oat["vat_source"]) == ("13.5", "entered")
    assert p["vat_unknown"] == [] and p["total_incl_vat"] is not None


def test_order_answer_has_its_own_totals_and_line_rates(env):
    client, _, _ = env
    p = milk(client, quantity="51")
    r = client.post(f"{K}/proposals/{p['proposal_id']}/approve", headers=HUMAN,
                    json={"expected_total": p["expected_total"], "idempotency_key": "a1"})
    assert r.status_code == 200, r.text
    order = client.get(f"{K}/orders/{r.json()['order_id']}", headers=HUMAN).json()
    assert (order["total_ex_vat"], order["vat"], order["total_incl_vat"]) == (
        p["total_ex_vat"], p["vat"], p["total_incl_vat"])
    assert order["vat_unknown"] == [] and order["expected_total"] == p["expected_total"]
    assert all(ln["vat_source"] == "valio_price" for ln in order["lines"])


def demo_like_order(db, lines):
    """An order placed without a proposal and without line rates (the DEMO-1198 shape)."""
    order, _ = orders.record_attempt(
        db, kitchen_id="demo-kitchen", idempotency_key="demo-k", offer_id="demo-k",
        expected_total=Decimal128("178.09"), lines=lines, approved_by="demo-seed",
        blocks=[{"supplier_id": "sup-valio", "name": "Valio Aimo",
                 "product_ids": [ln["product_id"] for ln in lines]}], supplier_must_confirm=[])
    orders.set_outcome(db, order["order_id"], outcome="CONFIRMED", status="SENT")
    return order["order_id"]


LINES = [{"product_id": "463982", "quantity": "3", "unit": "KI", "unit_price": "31.01", "total": "93.03",
          "unknown_stock": False, "reason_codes": []},
         {"product_id": "460838", "quantity": "1", "unit": "KI", "unit_price": "29.06", "total": "29.06",
          "unknown_stock": False, "reason_codes": []},
         {"product_id": "463335", "quantity": "40", "unit": "ST", "unit_price": "1.40", "total": "56.00",
          "unknown_stock": False, "reason_codes": []}]


def test_live_bug_order_without_proposal_shows_ex_vat_and_never_calls_it_incl_vat(env):
    """Order a39ccb6d (DEMO-1198): the page showed ex VAT "price unknown" and the ex-VAT sum
    EUR 178.09 as "incl VAT". The order answer now has its own totals."""
    client, _, db = env
    db.products.insert_many([{"_id": "463982", "names": {"en": "eggs"}, "vat_code": "MEDIUM", "vat_rate": "13.5"},
                             {"_id": "460838", "names": {"en": "cherry tomato"}, "vat_code": None, "vat_rate": None}])
    db.products.update_one({"_id": "463335"}, {"$set": {"vat_code": "MEDIUM", "vat_rate": "13.5"}})
    order = client.get(f"{K}/orders/{demo_like_order(db, LINES)}", headers=HUMAN).json()
    assert order["total_ex_vat"] == "178.09"
    assert order["vat_unknown"] == ["460838"]            # fresh vegetables: no vatCode in the catalog
    assert order["vat"] is None and order["total_incl_vat"] is None
    assert order["delivery_fee"] is None                 # the order stored no fee: unknown
    rates = {ln["product_id"]: (ln["vat_rate"], ln["vat_source"]) for ln in order["lines"]}
    assert rates == {"463982": ("13.5", "catalog"), "460838": (None, None), "463335": ("13.5", "catalog")}


def test_order_without_proposal_and_every_rate_known_has_incl_vat(env):
    client, _, db = env
    db.products.insert_one({"_id": "463982", "names": {"en": "eggs"}, "vat_code": "MEDIUM", "vat_rate": "13.5"})
    order = client.get(f"{K}/orders/{demo_like_order(db, LINES[:1])}", headers=HUMAN).json()
    assert (order["total_ex_vat"], order["vat"], order["total_incl_vat"]) == ("93.03", "12.56", "105.59")


def test_order_list_has_the_same_totals(env):
    client, _, db = env
    db.products.insert_one({"_id": "463982", "names": {"en": "eggs"}, "vat_code": "MEDIUM", "vat_rate": "13.5"})
    demo_like_order(db, LINES[:1])
    (order,) = client.get(f"{K}/orders", headers=HUMAN).json()["orders"]
    assert order["total_incl_vat"] == "105.59"


def test_decision_summary_says_vat_is_unknown(env):
    client, fake, _ = env
    drop_tax(fake, "462775")
    totals = milk(client, quantity="51")["decision_summary"]["totals"]
    assert "VAT unknown" in totals and "VAT EUR None" not in totals
