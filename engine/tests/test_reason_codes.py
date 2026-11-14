"""Reason codes from docs/contract.md the scenarios need: EVENT_LINE (S05),
STANDING_ORDER_DRIFT (S08), ALLERGEN_DATA_MISSING (S02, S04)."""

from datetime import date
from decimal import Decimal as D

from engine import Item, KitchenParams, Offer, allergen_codes, pack_info, plan_request, replenish
from engine.packs import PackInfo

MON = date(2026, 11, 16)
P = KitchenParams()
KG = PackInfo("KG", "KG", D(1), D(10), derived=False)
LITRE = PackInfo("ST", "L", D(1), D(1), derived=False)


def steak(**kw):
    return Offer("461423", "hanger steak", KG, D("19.93"), None, False, MON, **kw)


def test_event_request_marks_every_line_event_line():
    plan = plan_request(D(115), "KG", [steak()], MON, P, event=True)
    assert "EVENT_LINE" in plan.reason_codes
    assert all("EVENT_LINE" in ln.reason_codes for ln in plan.lines)
    assert "EVENT_LINE" not in plan_request(D(115), "KG", [steak()], MON, P).reason_codes


def test_offer_without_allergen_data_is_flagged():
    plan = plan_request(D(20), "KG", [steak(allergen_data_known=False)], MON, P)
    assert "ALLERGEN_DATA_MISSING" in plan.reason_codes
    assert "ALLERGEN_DATA_MISSING" in plan.lines[0].reason_codes
    assert "ALLERGEN_DATA_MISSING" not in plan_request(D(20), "KG", [steak()], MON, P).reason_codes


def test_unknown_allergen_data_is_never_safe():
    assert allergen_codes({"allergen_data_known": False, "no_declarable_allergens": False}) == ("ALLERGEN_DATA_MISSING",)
    assert allergen_codes({}) == ("ALLERGEN_DATA_MISSING",)          # field missing: unknown
    assert allergen_codes({"allergen_data_known": True}) == ()
    assert allergen_codes({"allergen_data_known": False, "no_declarable_allergens": True}) == ()


def item(**kw):
    base = dict(daily_demand=20, lead_time_days=0, review_days=7, on_hand=120, safety_stock=20)
    return Item("469549", LITRE, **{**base, **kw})


def test_standing_order_that_no_longer_matches_usage_drifts():
    line = replenish(item(standing_order=D(200)), P)
    assert line.quantity == 40
    assert "STANDING_ORDER_DRIFT" in line.reason_codes
    assert line.numbers["standing_order"] == D(200)
    assert "Standing order 200 ST no longer matches usage" in line.why
    assert "propose_standing_order" in line.numbers and "a person changes it" in line.why


def test_standing_order_close_to_usage_is_fine():
    assert "STANDING_ORDER_DRIFT" not in replenish(item(standing_order=D(145)), P).reason_codes   # usage 140
    assert "STANDING_ORDER_DRIFT" not in replenish(item(), P).reason_codes


def test_a_standing_order_equal_to_usage_never_suggests_itself():
    """#803: standing 140, demand 20/day, review 7 days, lots of stock: no drift, no suggestion."""
    for on_hand in (120, 500):
        line = replenish(item(on_hand=on_hand, standing_order=D(140)), P)
        assert "STANDING_ORDER_DRIFT" not in line.reason_codes
        assert "propose_standing_order" not in line.numbers and "Suggested" not in line.why


def test_standing_order_when_nothing_is_needed_also_drifts():
    line = replenish(item(on_hand=500, standing_order=D(200)), P)
    assert line.quantity == 0
    assert line.reason_codes == ("POSITION_OK", "STANDING_ORDER_DRIFT")


def test_allergen_rule_hits_only_known_excluded_codes():
    from engine import allergen_rule_hits
    oatly = {"allergens": {"contains": ["AW", "GO"], "may_contain": [], "undeclared": []}}
    trace = {"allergens": {"contains": [], "may_contain": ["AW"], "undeclared": []}}
    assert allergen_rule_hits(oatly, ("AW",)) == ("AW",)
    assert allergen_rule_hits(trace, ("AW",)) == ("AW",)            # may contain counts
    assert allergen_rule_hits(oatly, ()) == ()                       # no rule, no hit
    assert allergen_rule_hits({}, ("AW",)) == ()                     # unknown: ALLERGEN_DATA_MISSING instead
