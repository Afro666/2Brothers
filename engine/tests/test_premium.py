"""The limit on what the main plan pays for confirmed stock (engine/premium.py)."""

from decimal import Decimal as D

import pytest

from engine import KitchenParams, plan_request
from engine.premium import over_premium
from engine.tests.test_scenarios import MON, milk_offers, offer, row


def live_milk():
    """What Valio answered for the 20 candidates on 2026-11-14, cut to the three that matter."""
    return [
        offer("463380", "Arla Cafe milk 1 L UHT", row("463380", "ST", "ST", [("ST", 1)]),
              "2.65", "2.65", "L", "698", False),
        # 100 x 2 cl portion cups: 2 L a case, 7.55 EUR per litre, plenty in stock.
        offer("463203", "Arla Portion milk 100x2 cl", row("463203", "KI", "KI", [("KI", 1)]),
              "15.09", "7.545", "L", "5000", False),
        offer("464237", "Valio coffee milk 1 l UHT", row("464237", "ST", "ST", [("ST", 1)]),
              "1.30", "1.30", "L", None, False),
    ]


def test_dear_confirmed_stock_is_left_out_and_the_rest_goes_to_the_cheapest():
    plan = plan_request(D(1000), "L", live_milk(), MON)
    assert [(ln.product_id, ln.quantity) for ln in plan.lines] == [("463380", D(698)), ("464237", D(302))]
    assert plan.shortfall == 0
    assert plan.total == D("2242.30")                       # was 4685.61 with the portion cups
    reason = dict(plan.excluded)["463203"]
    assert "confirmed in stock" in reason and "5.8 times the cheapest (1.30 EUR per L)" in reason
    assert "limit is 3 times" in reason
    assert "STOCK_UNKNOWN" in plan.reason_codes


def test_the_partial_fill_does_not_use_the_dear_stock_either():
    part = plan_request(D(1000), "L", live_milk(), MON).partial
    assert part is not None and part.now.quantity == D(698) and part.remaining == D(302)


def test_the_golden_milk_case_is_unchanged():
    """S01: 2.57 for confirmed stock against 1.40 is 1.84 times, inside the limit of 3."""
    plan = plan_request(D(1000), "L", milk_offers(), MON)
    assert [(ln.product_id, ln.quantity) for ln in plan.lines] == [("462775", D(51)), ("463335", D(949))]
    assert "462775" not in dict(plan.excluded)


def test_dear_stock_is_used_when_nothing_else_covers_the_need():
    offers = [o for o in live_milk() if o.product_id != "464237"]      # no unconfirmed fallback
    cheap = offer("463335", "Valio Eila 3% 1 L", row("463335", "ST", "ST", [("ST", 1)]),
                  "1.40", "1.40", "L", "10", False)
    plan = plan_request(D(1000), "L", [*offers, cheap], MON)
    assert plan.shortfall == 0
    assert "463203" in [ln.product_id for ln in plan.lines]             # dear stock beats no stock
    assert "CERTAINTY_PREMIUM_HIGH" in plan.warnings
    assert "463203" not in dict(plan.excluded)


def test_the_limit_is_a_kitchen_setting_and_none_switches_it_off():
    off = KitchenParams.from_dict({"certainty_premium_max": None})
    plan = plan_request(D(1000), "L", live_milk(), MON, off)
    assert "463203" in [ln.product_id for ln in plan.lines]
    strict = KitchenParams.from_dict({"certainty_premium_max": "1.5"})
    plan = plan_request(D(1000), "L", live_milk(), MON, strict)
    assert [ln.product_id for ln in plan.lines] == ["464237"]           # 2.65 is 2.04 times: out too
    with pytest.raises(ValueError):
        KitchenParams.from_dict({"certainty_premium_max": "0.5"})


def test_over_premium_never_names_unconfirmed_stock_and_handles_empty():
    assert over_premium([], "L") == {}
    dear_unknown = offer("X", "Unconfirmed and dear", row("X", "ST", "ST", [("ST", 1)]),
                         "9.00", "9.00", "L", None, False)
    assert over_premium([*live_milk(), dear_unknown], "L").keys() == {"463203"}


def test_a_price_move_inside_the_limit_keeps_the_same_products():
    """The gateway re-plans at approval. A moved price must change the total, not the basket,
    as long as the confirmed offer stays inside the limit (2.57 -> 3.57 is 2.55 times)."""
    moved = [offer("462775", "Arla 1 L fat free", row("462775", "ST", "ST", [("KI", 12), ("ST", 1)]),
                   "3.57", "3.57", "L", "51", False), *milk_offers()[1:]]
    before = plan_request(D(51), "L", milk_offers(), MON)
    after = plan_request(D(51), "L", moved, MON)
    assert [ln.product_id for ln in after.lines] == [ln.product_id for ln in before.lines] == ["462775"]
    assert after.total > before.total


def test_a_price_move_beyond_the_limit_changes_the_plan_and_says_why():
    """9.99 for the confirmed milk is 7.1 times the cheapest: the plan no longer takes it."""
    moved = [offer("462775", "Arla 1 L fat free", row("462775", "ST", "ST", [("KI", 12), ("ST", 1)]),
                   "9.99", "9.99", "L", "51", False), *milk_offers()[1:]]
    plan = plan_request(D(51), "L", moved, MON)
    assert [ln.product_id for ln in plan.lines] == ["463335"]
    assert "STOCK_UNKNOWN" in plan.reason_codes
    assert "7.1 times the cheapest" in dict(plan.excluded)["462775"]
