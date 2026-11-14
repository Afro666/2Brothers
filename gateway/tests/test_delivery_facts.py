"""#1453: each line shows a cut-off, lead time and reliability with its source; real data wins."""

from datetime import date, datetime
from decimal import Decimal

import pytest

from engine.packs import PackInfo
from engine import Offer
from gateway.suppliers import KITCHEN_TZ, delivery_facts, latest_cutoff

MON = date(2026, 11, 16)
TERMS = {"order_days": ["MON", "TUE", "WED", "THU", "FRI"], "cutoff_time": "17:00", "lead_time_days": 1}
DEMO = {"supplier": {"lead_time_days": 2, "order_days": ["TUE", "FRI"], "cutoff_time": "14:00",
                     "reliability": 0.92},
        "products": {"fish": {"lead_time_days": 1, "reliability": 0.88}}}


def offer(pid, reliability=None):
    pack = PackInfo("ST", "L", Decimal(1), Decimal(1), derived=False)
    return Offer(pid, pid, pack, Decimal(1), None, None, MON, reliability=reliability)


def when(closing=None, available="2026-11-16"):
    return {"available_date": available, "cutoff_passed": None, "closing_time": closing}


def test_latest_cutoff_skips_days_that_are_not_order_days():
    # Monday delivery, 1 day lead: Sunday is no order day, so Friday 17:00.
    assert latest_cutoff(TERMS["order_days"], "17:00", 1, MON) == datetime(2026, 11, 13, 17, 0, tzinfo=KITCHEN_TZ)
    assert latest_cutoff(["TUE"], "14:00", 0, MON) == datetime(2026, 11, 10, 14, 0, tzinfo=KITCHEN_TZ)
    assert latest_cutoff([], "14:00", 0, MON) is None


def test_valio_closing_time_and_csv_reliability_win_over_terms_and_demo():
    facts = delivery_facts({"p": when("2026-11-15T10:00:00+02:00")}, [offer("p", 0.97)], TERMS, DEMO, MON)["p"]
    assert (facts["cutoff_at"], facts["cutoff_source"]) == ("2026-11-15T10:00:00+02:00", "valio")
    assert (facts["delivery_reliability"], facts["reliability_source"]) == ("0.97", "valio")
    assert facts["closing_time"] == "2026-11-15T10:00:00+02:00"      # unchanged


def test_supplier_terms_give_the_cutoff_when_valio_has_none():
    facts = delivery_facts({"p": when()}, [offer("p")], TERMS, {}, MON)["p"]
    assert (facts["cutoff_at"], facts["cutoff_source"]) == ("2026-11-13T17:00:00+02:00", "supplier_terms")
    assert (facts["lead_time_days"], facts["lead_time_source"]) == (1, "supplier_terms")
    assert (facts["delivery_reliability"], facts["reliability_source"]) == (None, None)
    assert facts["closing_time"] is None                              # still Valio's own only


def test_a_demo_product_lead_time_makes_the_cutoff_demo():
    # No supplier terms: the product's demo value is the lead time, so the cut-off is demo too.
    facts = delivery_facts({"fish": when()}, [offer("fish")], {}, DEMO, MON)["fish"]
    assert (facts["lead_time_days"], facts["lead_time_source"]) == (1, "demo")
    assert facts["cutoff_source"] == "demo"
    assert (facts["delivery_reliability"], facts["reliability_source"]) == ("0.88", "demo")


def test_supplier_terms_lead_time_wins_over_a_product_demo_value():
    # #1462: real data always wins; a per-product demo value never hides the supplier's terms.
    demo = {**DEMO, "products": {"fish": {"lead_time_days": 3, "reliability": 0.88}}}
    facts = delivery_facts({"fish": when()}, [offer("fish")], TERMS, demo, MON)["fish"]
    assert (facts["lead_time_days"], facts["lead_time_source"]) == (1, "supplier_terms")
    assert (facts["cutoff_at"], facts["cutoff_source"]) == ("2026-11-13T17:00:00+02:00", "supplier_terms")
    assert (facts["delivery_reliability"], facts["reliability_source"]) == ("0.88", "demo")


def test_a_product_demo_lead_time_wins_over_the_supplier_demo_value():
    demo = {**DEMO, "products": {"fish": {"lead_time_days": 1}}}
    terms = {"order_days": ["MON", "TUE", "WED", "THU", "FRI"], "cutoff_time": "17:00"}   # no lead time
    facts = delivery_facts({"fish": when()}, [offer("fish")], terms, demo, MON)["fish"]
    assert (facts["lead_time_days"], facts["lead_time_source"]) == (1, "demo")
    assert facts["cutoff_source"] == "demo"
    other = delivery_facts({"p": when()}, [offer("p")], terms, demo, MON)["p"]
    assert (other["lead_time_days"], other["lead_time_source"]) == (2, "demo")


def test_no_terms_fall_back_to_the_supplier_demo_values():
    facts = delivery_facts({"p": when()}, [offer("p")], {}, DEMO, MON)["p"]
    # Monday minus 2 days is Saturday; the last demo order day before it is Friday 14:00.
    assert (facts["cutoff_at"], facts["cutoff_source"]) == ("2026-11-13T14:00:00+02:00", "demo")
    assert (facts["delivery_reliability"], facts["reliability_source"]) == ("0.92", "demo")


def test_a_later_available_date_is_the_delivery_date():
    facts = delivery_facts({"p": when(available="2026-11-18")}, [offer("p")], TERMS, {}, MON)["p"]
    assert facts["cutoff_at"] == "2026-11-17T17:00:00+02:00"


def test_nothing_known_stays_unknown_never_zero():
    facts = delivery_facts({"p": when(available=None)}, [offer("p")], {}, {}, MON)["p"]
    assert all(facts[k] is None for k in ("cutoff_at", "cutoff_source", "lead_time_days", "lead_time_source",
                                          "delivery_reliability", "reliability_source"))


pytest.importorskip("mongomock")
pytest.importorskip("fastapi")

from gateway.tests.test_gateway_app import env, milk  # noqa: E402, F401 (fixture)
from store import demo_delivery  # noqa: E402


def test_demo_rows_show_on_lines_and_never_change_the_basket(env):
    client, _, db = env
    before = milk(client, key="before")
    db.kitchens.update_one({"_id": "demo-kitchen"}, {"$set": {"synthetic": True}}, upsert=True)
    demo_delivery.replace(db, "demo-kitchen", [{"supplier_id": "sup-valio", "lead_time_days": 2,
                                                "order_days": ["FRI"], "cutoff_time": "12:00",
                                                "reliability": 0.95}],
                          [{"supplier_id": "sup-valio", "product_id": "462775", "reliability": 0.9}])
    after = milk(client, key="after")
    assert [(ln["product_id"], ln["quantity"]) for ln in after["lines"]] == \
        [(ln["product_id"], ln["quantity"]) for ln in before["lines"]]
    assert after["expected_total"] == before["expected_total"]
    line = next(ln for ln in after["lines"] if ln["product_id"] == "462775")
    assert line["delivery_reliability"] == 0.9 and line["reliability_source"] == "demo"
    assert line["reliability"] is None                                  # Valio's field stays Valio's
    assert line["cutoff_source"] in ("valio", "demo") and line["cutoff_at"]
    assert not any(isinstance(v, float) for ln in db.offers.find_one({"_id": after["offer_id"]})
                   ["simulation"]["lines"] for v in ln.values())


def test_a_manual_supplier_line_gets_its_cutoff_from_its_terms(env):
    from gateway.tests.test_multi_supplier import BAKERY_DAYS, OAT, bakery, propose
    client, _, db = env
    bakery(db, BAKERY_DAYS)
    line = next(ln for ln in propose(client, ids=(OAT,))["lines"] if ln["product_id"] == OAT)
    assert line["closing_time"] is None
    # Monday delivery, 1 day lead, order days Mon-Sat at 14:00: Saturday 14:00.
    assert (line["cutoff_at"], line["cutoff_source"]) == ("2026-11-14T14:00:00+02:00", "supplier_terms")
    assert (line["delivery_reliability"], line["reliability_source"]) == (None, None)


def test_demo_rows_need_a_synthetic_kitchen(env):
    _, _, db = env
    db.kitchens.update_one({"_id": "real-kitchen"}, {"$set": {"synthetic": False}}, upsert=True)
    with pytest.raises(ValueError):
        demo_delivery.replace(db, "real-kitchen", [], [])
