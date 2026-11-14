"""Multi-supplier proposals (#73): one block per supplier, each with its own user-set terms."""

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

pytest.importorskip("mongomock")
pytest.importorskip("fastapi")

from gateway.suppliers import manual_delivery  # noqa: E402
from gateway.tests.test_gateway_app import AGENT, HUMAN, K, NOW, env  # noqa: E402, F401
from store.repository import Repository  # noqa: E402

KITCHEN = "demo-kitchen"
MON = date(2026, 11, 16)
OAT = "own-oat"
# NOW is Friday 22:10 in Helsinki: Saturday is the next order day, delivery on Sunday.
BAKERY_DAYS = {"order_days": ["MON", "TUE", "WED", "THU", "FRI", "SAT"], "cutoff_time": "14:00",
               "lead_time_days": 1}


def bakery(db, terms, adapter="csv"):
    repo = Repository(db)
    repo.suppliers.create(KITCHEN, {"supplier_id": "sup-bakery", "name": "Leipomo Demo",
                                    "adapter": adapter, "terms": terms})
    repo.own_products.create(KITCHEN, {
        "product_id": OAT, "name": "Oat drink 1 L", "supplier_id": "sup-bakery", "unit": "ST",
        "base_unit": "L", "pack_size_in_base_units": "1", "unit_price_eur": "1.20"})
    return repo


def propose(client, key="m1", quantity="100", ids=("462775", "463335", OAT)):
    r = client.post(K + "/proposals", headers=AGENT, json={
        "product_ids": list(ids), "quantity": quantity, "unit": "L",
        "requested_date": MON.isoformat(), "idempotency_key": key})
    assert r.status_code == 200, r.text
    return r.json()


def test_two_suppliers_give_two_blocks_with_their_own_terms(env):
    client, _, db = env
    repo = bakery(db, {**BAKERY_DAYS, "free_delivery_threshold_eur": "100.00", "delivery_fee_eur": "9.50"})
    repo.suppliers.create(KITCHEN, {"supplier_id": "sup-valio", "name": "Valio Aimo", "adapter": "valio_api",
                                    "terms": {"free_delivery_threshold_eur": "300.00",
                                              "delivery_fee_eur": "25.00"}})
    p = propose(client)
    # The engine plans as before: confirmed Valio stock first, the rest on the cheapest unknown.
    assert [(ln["product_id"], ln["quantity"]) for ln in p["lines"]] == [("462775", "51"), (OAT, "49")]
    valio, bread = p["blocks"]
    assert (valio["supplier_id"], bread["supplier_id"]) == ("sup-valio", "sup-bakery")
    assert [ln["product_id"] for ln in valio["lines"]] == ["462775"]
    assert [ln["product_id"] for ln in bread["lines"]] == [OAT]
    assert (valio["total_ex_vat"], valio["mov_gap"], valio["delivery_fee"]) == ("131.07", "168.93", "25.00")
    assert (bread["total_ex_vat"], bread["mov_gap"], bread["delivery_fee"]) == ("58.80", "41.20", "9.50")
    assert bread["vat"] is None                       # no VAT rate on an own product: unknown, not zero
    assert bread["expected_total"] == "68.30"
    assert Decimal(p["expected_total"]) == Decimal(valio["expected_total"]) + Decimal(bread["expected_total"])
    assert p["total_ex_vat"] == "189.87"
    assert p["mov_gap"] is None and p["delivery_fee"] is None   # several suppliers: read the blocks
    assert any("VAT for Leipomo Demo is not known" in r for r in p["mandate"]["reasons"])


def test_unknown_terms_are_null_not_zero(env):
    client, _, db = env
    bakery(db, BAKERY_DAYS)                           # no threshold, no fee; Valio has no terms at all
    p = propose(client)
    assert len(p["blocks"]) == 2
    for block in p["blocks"]:
        assert block["mov_gap"] is None and block["delivery_fee"] is None
    assert p["blocks"][1]["expected_total"] == "58.80"


def test_one_supplier_keeps_the_top_level_fields(env):
    client, _, db = env
    Repository(db).suppliers.create(KITCHEN, {
        "supplier_id": "sup-valio", "name": "Valio Aimo", "adapter": "valio_api",
        "terms": {"free_delivery_threshold_eur": "300.00", "delivery_fee_eur": "25.00"}})
    p = propose(client, quantity="51", ids=("462775",))
    (block,) = p["blocks"]
    assert block["lines"] == p["lines"]
    for field in ("total_ex_vat", "vat", "mov_gap", "delivery_fee", "expected_total"):
        assert block[field] == p[field], field
    assert p["mov_gap"] == "168.93" and p["delivery_fee"] == "25.00"


def test_discount_tier_lowers_the_unit_price_and_is_named_in_why(env):
    client, _, db = env
    bakery(db, {**BAKERY_DAYS, "discount_tiers": [
        {"min_qty": "10", "unit": "ST", "unit_price_eur": "1.10"},                      # every product
        {"product_id": OAT, "min_qty": "40", "unit": "ST", "unit_price_eur": "1.00"},  # highest break that fits
        {"product_id": OAT, "min_qty": "50", "unit": "ST", "unit_price_eur": "0.90"},  # above 49: not reached
        {"product_id": OAT, "min_qty": "45", "unit": "KI", "unit_price_eur": "0.10"},  # another unit
    ]})
    line = propose(client)["lines"][1]
    assert (line["product_id"], line["quantity"], line["unit_price"], line["total"]) == (OAT, "49", "1.00", "49.00")
    assert "Discount tier applied: from 40 ST the price is 1.00 EUR per ST (list price 1.20)" in line["why"]


def test_tier_without_product_id_applies_to_every_product(env):
    client, _, db = env
    bakery(db, {**BAKERY_DAYS, "discount_tiers": [{"min_qty": "10", "unit": "ST", "unit_price_eur": "1.10"}]})
    line = propose(client)["lines"][1]
    assert line["unit_price"] == "1.10" and "Discount tier applied" in line["why"]
    assert "Discount tier" not in propose(client, key="m2")["lines"][0]["why"]   # the Valio line: not its tier


def test_manual_supplier_lines_are_unknown_stock_and_cannot_be_placed(env):
    client, _, db = env
    bakery(db, BAKERY_DAYS, adapter="manual")
    p = propose(client)
    line = p["blocks"][1]["lines"][0]
    assert line["unknown_stock"] is True and "STOCK_UNKNOWN" in line["reason_codes"]
    assert "Leipomo Demo does not report its stock" in line["why"]
    assert any("Leipomo Demo is a price list the kitchen entered" in r for r in p["mandate"]["reasons"])
    assert not any("Valio does not report" in r for r in p["mandate"]["reasons"])   # the Valio line is confirmed
    # One human yes for the whole proposal; the same guard as before refuses unconfirmed stock.
    r = client.post(f"{K}/proposals/{p['proposal_id']}/approve", headers=HUMAN,
                    json={"expected_total": p["expected_total"], "idempotency_key": "a1"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "STOCK_UNKNOWN", r.text
    assert db.orders.count_documents({}) == 0


def test_order_stores_the_supplier_blocks(env):
    client, _, db = env
    p = propose(client, quantity="51", ids=("462775",))
    r = client.post(f"{K}/proposals/{p['proposal_id']}/approve", headers=HUMAN,
                    json={"expected_total": p["expected_total"], "idempotency_key": "a1"})
    assert r.status_code == 200, r.text
    order = db.orders.find_one({})
    assert order["supplier_id"] == "sup-valio"
    assert order["blocks"] == [{"supplier_id": "sup-valio", "name": "Valio Aimo", "total_ex_vat": p["total_ex_vat"],
                                "vat": p["vat"], "mov_gap": None, "delivery_fee": None,
                                "expected_total": p["expected_total"], "product_ids": ["462775"]}]


def test_manual_cutoff_passed_excludes_the_product(env):
    client, _, db = env
    # Monday to Friday, 14:00: Friday's cut-off passed, next order Monday, delivery Tuesday.
    bakery(db, {**BAKERY_DAYS, "order_days": ["MON", "TUE", "WED", "THU", "FRI"]})
    p = propose(client)
    assert [b["supplier_id"] for b in p["blocks"]] == ["sup-valio"]
    assert {"product_id": OAT, "reason": "order cut-off has passed for this delivery"} in p["excluded"]
    assert "CLOSING_PASSED" in p["mandate"]["reason_codes"]


@pytest.mark.parametrize("missing", ["order_days", "cutoff_time", "lead_time_days"])
def test_manual_unknown_cutoff_terms_exclude_the_product(env, missing):
    client, _, db = env
    bakery(db, {k: v for k, v in BAKERY_DAYS.items() if k != missing})
    p = propose(client)
    assert {"product_id": OAT, "reason": "no cut-off time known: cannot promise this delivery"} in p["excluded"]


def test_own_product_without_price_or_supplier_is_left_out(env):
    client, _, db = env
    repo = Repository(db)
    repo.own_products.create(KITCHEN, {"product_id": "own-x", "name": "Rye loaf", "supplier_id": "sup-gone",
                                       "unit": "ST", "unit_price_eur": "2.00"})
    repo.suppliers.create(KITCHEN, {"supplier_id": "sup-bakery", "name": "Leipomo Demo", "adapter": "manual",
                                    "terms": BAKERY_DAYS})
    repo.own_products.create(KITCHEN, {"product_id": "own-free", "name": "Oat drink", "supplier_id": "sup-bakery",
                                       "unit": "ST", "base_unit": "L", "pack_size_in_base_units": "1"})
    repo.own_products.create(KITCHEN, {"product_id": "own-loaf", "name": "Loaf", "supplier_id": "sup-bakery",
                                       "unit": "ST", "unit_price_eur": "2.00"})
    p = propose(client, ids=("462775", "own-x", "own-free", "own-loaf"))
    reasons = {e["product_id"]: e["reason"] for e in p["excluded"]}
    assert reasons["own-x"] == "supplier sup-gone is not set up"
    assert reasons["own-free"] == "no price entered for Leipomo Demo"
    assert reasons["own-loaf"] == "pack size unknown: no L per ST entered"


def test_manual_delivery_rule():
    def at(hour, day=13):                        # 2026-11-13 is a Friday; hours in UTC (Helsinki is +2)
        return datetime(2026, 11, day, hour, 0, tzinfo=timezone.utc)
    terms = {"order_days": ["FRI"], "cutoff_time": "14:00", "lead_time_days": 3}
    assert manual_delivery(terms, MON, at(11)) == (False, MON)                 # 13:00 local: in time
    assert manual_delivery(terms, MON, at(12)) == (True, date(2026, 11, 23))   # 14:00 local: next Friday
    assert manual_delivery({**terms, "lead_time_days": 4}, MON, at(11)) == (True, date(2026, 11, 17))
    assert manual_delivery({**terms, "lead_time_days": 0}, date(2026, 11, 13), at(11)) == (False, date(2026, 11, 13))
    assert manual_delivery({**terms, "order_days": []}, MON, at(11)) == (None, None)
    assert manual_delivery({**terms, "lead_time_days": None}, MON, at(11)) == (None, None)
    assert manual_delivery({**terms, "cutoff_time": None}, MON, at(11)) == (None, None)
