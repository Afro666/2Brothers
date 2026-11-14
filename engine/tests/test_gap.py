"""S02: fill a short order's gap by weight, not by case count."""
from dataclasses import replace
from datetime import date
from decimal import Decimal as D

from engine import KitchenParams, Offer, pack_info, plan_request
from engine.gap import fill_gap, gap_in_measure

MON = date(2026, 11, 16)
P = KitchenParams()


def row(pid, unit):
    return {"id": pid, "salesUnit": unit, "baseUnit": unit, "allowedLotSize": 1,
            "units": [{"unitId": unit, "sizeInBaseUnits": 1.0}]}


def offer(pid, unit, price, cmp, measure, available):
    pack = pack_info(row(pid, unit), price=D(price), comparison_price=D(cmp), comparison_unit="KG", measure=measure)
    return Offer(pid, pid, pack, D(price), None if available is None else D(available), False, MON)


BREAD = offer("465138", "KI", "64.27", "7.65", "KI", "16")       # 8.4 kg per case, 16 in stock
BREAD_KG = pack_info(row("465138", "KI"), price=D("64.27"), comparison_price=D("7.65"),
                     comparison_unit="KG", measure="KG")
ROLLS = offer("462300", "BAG", "3.58", "8.95", "KG", None)       # 0.4 kg bags


def test_the_gap_is_converted_to_kilos():
    plan = plan_request(D(20), "KI", [BREAD], MON, P)
    assert plan.shortfall == D(4)
    assert gap_in_measure(plan, BREAD_KG) == D("33.6")


def test_the_substitute_is_sized_by_weight_and_needs_a_yes():
    plan = plan_request(D(20), "KI", [BREAD], MON, P)
    sub = fill_gap(plan, BREAD_KG, [ROLLS], MON, P)
    assert [(ln.product_id, ln.quantity) for ln in sub.lines] == [("462300", D(84))]
    assert sub.total == D("300.72")
    assert "SUBSTITUTE_NEEDS_OK" in sub.reason_codes
    assert all("SUBSTITUTE_NEEDS_OK" in ln.reason_codes for ln in sub.lines)


def test_no_gap_or_no_substitute_gives_nothing():
    full = plan_request(D(10), "KI", [BREAD], MON, P)
    assert fill_gap(full, BREAD_KG, [ROLLS], MON, P) is None
    short = plan_request(D(20), "KI", [BREAD], MON, P)
    assert fill_gap(short, BREAD_KG, [], MON, P) is None


def test_unlinked_measures_give_nothing():
    bread_by_kg = offer("465138", "KI", "64.27", "7.65", "KG", "2")   # 2 cases x 8.4 kg in stock
    plan = plan_request(D(50), "KG", [bread_by_kg], MON, P)
    assert plan.measure == "KG" and plan.shortfall > 0
    assert BREAD_KG.sales_unit == "KI"
    assert gap_in_measure(plan, BREAD_KG) is None
    assert fill_gap(plan, BREAD_KG, [ROLLS], MON, P) is None


def test_a_zero_pack_size_gives_nothing():
    plan = plan_request(D(20), "KI", [BREAD], MON, P)
    no_size = replace(BREAD_KG, size=D(0))
    assert gap_in_measure(plan, no_size) is None
    assert fill_gap(plan, no_size, [ROLLS], MON, P) is None
