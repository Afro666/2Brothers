"""Partial fill (#288): order the confirmed stock now, and say what happens to the rest."""

from dataclasses import replace
from datetime import date
from decimal import Decimal as D

from engine import KitchenParams, PartialFill, partial_fill, plan_request
from engine.tests.test_scenarios import MON, milk_offers, offer, row

P = KitchenParams()
WED = date(2026, 11, 18)
THU = date(2026, 11, 19)


def later_milk(pid, name, available, on, price="1.90", cutoff_passed=False):
    made = offer(pid, name, row(pid, "ST", "ST", [("ST", 1)]), price, price, "L", available, cutoff_passed)
    return replace(made, available_date=on)


# ---- S01 milk: 51 L now, 949 L held --------------------------------------------------

def test_s01_partial_orders_51_now_and_holds_949():
    part = plan_request(D(1000), "L", milk_offers(), MON, P).partial
    assert isinstance(part, PartialFill)
    assert (part.need, part.measure, part.remaining) == (D(1000), "L", D(949))
    now = part.now
    assert (now.kind, now.quantity, now.deliver_on) == ("NOW", D(51), MON)
    assert [(ln.product_id, ln.quantity, ln.unknown_stock) for ln in now.lines] == [("462775", D(51), False)]
    assert now.total == D("131.07")
    assert len(part.rest) == 1
    hold = part.rest[0]
    assert (hold.kind, hold.quantity, hold.deliver_on, hold.lines, hold.total) == ("HOLD", D(949), None, (), None)
    assert part.reason_codes == ("PARTIAL_STOCK", "PACK_SIZE_DERIVED")   # litres come from the price ratio


def test_s01_partial_why_names_both_parts():
    part = plan_request(D(1000), "L", milk_offers(), MON, P).partial
    assert part.now.why == ("Order 51 L now for 2026-11-16: 51 ST of Arla 1 L fat free, all the stock "
                            "Valio confirms for that date, EUR 131.07 ex VAT.")
    assert part.rest[0].why == ("Hold the remaining 949 L until Valio confirms stock: "
                                "no offer shows confirmed stock for a later delivery date.")
    assert part.why == f"{part.now.why} {part.rest[0].why}"
    assert "51 L" in part.why and "949 L" in part.why


def test_s01_unknown_stock_is_never_counted_as_covered():
    part = partial_fill(D(1000), "L", milk_offers(), MON)
    used = {ln.product_id for p in (part.now, *part.rest) for ln in p.lines}
    assert used == {"462775"}          # 463335 (stock unknown) is in the main plan, never here
    assert not any(ln.unknown_stock for p in (part.now, *part.rest) for ln in p.lines)


def test_main_plan_and_alternative_are_unchanged_by_the_partial_option():
    plan = plan_request(D(1000), "L", milk_offers(), MON, P)
    assert [(ln.product_id, ln.quantity) for ln in plan.lines] == [("462775", D(51)), ("463335", D(949))]
    assert plan.total == D("1459.67") and plan.alternative.total == D("1400.00")
    assert plan.alternative.partial is None


# ---- the rest on a later delivery ----------------------------------------------------

def test_rest_goes_on_the_earliest_later_date_with_confirmed_stock():
    offers = milk_offers() + [later_milk("470001", "Later milk Thu", "2000", THU, price="1.50"),
                              later_milk("470002", "Later milk Wed", "2000", WED)]
    part = partial_fill(D(1000), "L", offers, MON)
    assert len(part.rest) == 1
    later = part.rest[0]
    assert (later.kind, later.quantity, later.deliver_on) == ("LATER", D(949), WED)   # earliest, not cheapest
    assert [(ln.product_id, ln.quantity) for ln in later.lines] == [("470002", D(949))]
    assert later.total == D("1803.10")
    assert later.why == ("The remaining 949 L can come on 2026-11-18: 949 ST of Later milk Wed, "
                         "confirmed in stock for that date, EUR 1803.10 ex VAT.")
    assert "51 L" in part.why and "949 L" in part.why and "2026-11-18" in part.why


def test_later_stock_that_is_short_leaves_a_hold_for_the_last_part():
    offers = milk_offers() + [later_milk("470002", "Later milk Wed", "600", WED)]
    part = partial_fill(D(1000), "L", offers, MON)
    later, hold = part.rest
    assert (later.kind, later.quantity, later.deliver_on, later.total) == ("LATER", D(600), WED, D("1140.00"))
    assert later.why == ("600 L of the remaining 949 L can come on 2026-11-18: 600 ST of Later milk Wed, "
                         "confirmed in stock for that date, EUR 1140.00 ex VAT.")
    assert (hold.kind, hold.quantity) == ("HOLD", D(349))
    assert hold.why == ("Hold the last 349 L until Valio confirms stock: "
                        "no offer shows more confirmed stock for a later delivery date.")
    assert part.now.quantity + later.quantity + hold.quantity == part.need


def test_later_offer_needs_confirmed_stock_and_an_open_cutoff():
    offers = milk_offers() + [later_milk("470003", "Unknown later", None, WED),
                              later_milk("470004", "Cut-off passed later", "2000", WED, cutoff_passed=True),
                              replace(later_milk("470005", "No cut-off later", "2000", WED), cutoff_passed=None),
                              replace(later_milk("470006", "Blocked later", "2000", WED), sales_block=True),
                              later_milk("470007", "Empty later", "0", WED)]
    part = partial_fill(D(1000), "L", offers, MON)
    assert [p.kind for p in part.rest] == ["HOLD"]
    assert part.rest[0].quantity == D(949)


# ---- when there is no partial option -------------------------------------------------

def test_no_partial_when_confirmed_stock_covers_the_need():
    assert plan_request(D(51), "L", milk_offers(), MON, P).partial is None
    assert plan_request(D(40), "L", milk_offers(), MON, P).partial is None


def test_no_partial_when_nothing_is_confirmed_for_the_date():
    unknown_only = [o for o in milk_offers() if o.available is None]
    assert plan_request(D(1000), "L", unknown_only, MON, P).partial is None


# ---- S02: the shortfall gets a plan too ----------------------------------------------

def test_s02_partial_16_cases_now_and_4_held():
    ph7 = offer("465138", "PH7 gluten free oat bread", row("465138", "KI", "KI", [("KI", 1)]),
                "64.27", "7.65", "KG", "16", False, measure="KI")
    part = plan_request(D(20), "KI", [ph7], MON, P).partial
    assert (part.now.quantity, part.now.total) == (D(16), D("1028.32"))
    assert [(p.kind, p.quantity) for p in part.rest] == [("HOLD", D(4))]
    assert "16 KI" in part.why and "4 KI" in part.why


def test_event_request_marks_the_partial_lines():
    part = plan_request(D(1000), "L", milk_offers(), MON, P, event=True).partial
    assert "EVENT_LINE" in part.now.lines[0].reason_codes
