"""Golden scenarios from docs/scenarios.md. Offers are the live values of 2026-11-13 22:04."""

import json
from datetime import date
from decimal import Decimal as D

import pytest

from engine import Item, KitchenParams, Offer, pack_info, plan_request, replenish, stockout_adjusted
from engine.packs import PackDataError, to_sales_units
from engine.quantity import cover_limit
from engine.urgency import Urgency

MON = date(2026, 11, 16)
P = KitchenParams()


def row(pid, sales, base, units, lot=0.01):
    return {"id": pid, "salesUnit": sales, "baseUnit": base, "allowedLotSize": lot,
            "units": [{"unitId": u, "sizeInBaseUnits": s} for u, s in units]}


def offer(pid, name, product, price, cmp, cmp_unit, available, cutoff_passed, measure=None):
    pack = pack_info(product, price=D(price), comparison_price=D(cmp) if cmp else None,
                     comparison_unit=cmp_unit, measure=measure)
    return Offer(pid, name, pack, D(price), None if available is None else D(available),
                 cutoff_passed, MON)


# ---- S01 milk: split order, passed cut-off, unknown stock ----------------------------

def milk_offers():
    return [
        offer("462775", "Arla 1 L fat free", row("462775", "ST", "ST", [("KI", 12), ("ST", 1)]),
              "2.57", "2.57", "L", "51", False),
        offer("463335", "Valio Eila 3% 1 L", row("463335", "ST", "ST", [("KI", 5), ("ST", 1)]),
              "1.40", "1.40", "L", None, False),
        offer("462921", "Valio Eila organic 1 L", row("462921", "KI", "ST", [("KI", 5), ("ST", 1)]),
              "10.97", "2.19", "L", None, True),
        offer("463038", "Valio Eila 10 L novobox", row("463038", "KI", "ST", [("KI", 2), ("ST", 1)]),
              "31.31", "1.57", "L", None, True),
        offer("464179", "Arla 10 L novobox", row("464179", "ST", "ST", [("ST", 1)]),
              "27.22", "2.72", "L", None, True),
    ]


def test_s01_milk_split_confirmed_first():
    plan = plan_request(D(1000), "L", milk_offers(), MON, P)
    assert [(ln.product_id, ln.quantity) for ln in plan.lines] == [("462775", D(51)), ("463335", D(949))]
    assert plan.total == D("1459.67")
    assert plan.shortfall == 0
    assert {pid for pid, _ in plan.excluded} == {"462921", "463038", "464179"}
    assert set(plan.reason_codes) >= {"CLOSING_PASSED", "PARTIAL_STOCK", "STOCK_UNKNOWN"}
    assert plan.lines[1].unknown_stock and not plan.lines[0].unknown_stock
    assert "not confirmed" in plan.lines[1].why


def test_s01_alternative_all_cheapest():
    alt = plan_request(D(1000), "L", milk_offers(), MON, P).alternative
    assert alt is not None
    assert [(ln.product_id, ln.quantity) for ln in alt.lines] == [("463335", D(1000))]
    assert alt.total == D("1400.00")


def test_s01_case_of_five_converts_litres():
    o = milk_offers()[2]
    assert o.pack.size == 5 and o.pack.derived


# ---- S02 partial stock --------------------------------------------------------------

def test_s02_partial_stock_shortfall():
    ph7 = offer("465138", "PH7 gluten free oat bread", row("465138", "KI", "KI", [("KI", 1)]),
                "64.27", "7.65", "KG", "16", False, measure="KI")
    plan = plan_request(D(20), "KI", [ph7], MON, P)
    assert plan.lines[0].quantity == 16
    assert plan.total == D("1028.32")
    assert plan.shortfall == 4
    assert "PARTIAL_STOCK" in plan.reason_codes


# ---- S05 lot size + budget warning --------------------------------------------------

def test_s05_lot_size_and_budget_warning():
    steak = offer("461423", "Snellman hanger steak", row("461423", "KG", "KG", [("KG", 1), ("KI", 1)], lot=10),
                  "19.93", "19.93", "KG", None, False)
    plan = plan_request(D(115), "KG", [steak], MON, P)
    assert plan.lines[0].quantity == 120
    assert plan.total == D("2391.60")
    assert "LOT_SIZE_ROUNDED" in plan.reason_codes and "STOCK_UNKNOWN" in plan.reason_codes
    assert plan.warnings == ("OVER_BUDGET_WARNING",)


def test_budget_warning_is_user_set():
    steak = offer("461423", "Snellman hanger steak", row("461423", "KG", "KG", [("KG", 1)], lot=10),
                  "19.93", "19.93", "KG", None, False)
    params = KitchenParams.from_dict({"budget_warning_order_eur": "3000"})
    assert plan_request(D(115), "KG", [steak], MON, params).warnings == ()


# ---- S12 bad pack data --------------------------------------------------------------

def test_s12_carrot_sack_is_ten_kilos():
    carrot = offer("460708", "Carrot 10 kg sack", row("460708", "ST", "ST", [("PAL", 60), ("KI", 1), ("ST", 1)]),
                   "11.18", "1.12", "KG", "20", False)
    assert carrot.pack.size == 10
    plan = plan_request(D(50), "KG", [carrot], MON, P)
    assert plan.lines[0].quantity == 5
    assert plan.total == D("55.90")
    assert "PACK_SIZE_DERIVED" in plan.reason_codes


def test_pack_without_comparison_price_stops():
    with pytest.raises(PackDataError):
        pack_info(row("471283", "KI", "ST", [("KI", 40), ("ST", 1)]), price=D("18.99"),
                  comparison_price=None, comparison_unit=None, measure="KG")


# ---- S09-S11 replenishment ----------------------------------------------------------

ESL = pack_info(row("469549", "ST", "ST", [("KI", 20), ("ST", 1)]), price=D("1.00"),
                comparison_price=D("1.00"), comparison_unit="L", measure="L")


def test_s09_missing_count_is_urgent_and_sized_as_empty():
    item = Item("469549", ESL, daily_demand=12, lead_time_days=1, review_days=2, on_hand=None,
                safety_stock=12, category="fresh_dairy")
    line = replenish(item, P)
    assert line.quantity == 48
    assert line.urgency == Urgency.BEFORE_NEXT_DELIVERY
    assert "STOCK_COUNT_MISSING" in line.reason_codes
    assert "count it before sending" in line.why


def test_s10_stockout_adjusted_demand():
    weekly, adjusted = stockout_adjusted(30, days_in_stock=3, days_total=7, cap=P.stockout_cap)
    assert adjusted and weekly == pytest.approx(54)
    oat = pack_info(row("470863", "ST", "ST", [("KI", 6), ("ST", 1)]), price=D("1.40"),
                    comparison_price=D("1.40"), comparison_unit="L", measure="L")
    item = Item("470863", oat, daily_demand=weekly / 7, lead_time_days=0, review_days=7, on_hand=0,
                safety_stock=0, category="dry", demand_codes=("STOCKOUT_ADJUSTED",),
                demand_note="stock-out adjusted from 30 L/week")
    line = replenish(item, P)
    assert line.quantity == 54
    assert "STOCKOUT_ADJUSTED" in line.reason_codes


def test_stockout_cap_is_user_set():
    weekly, _ = stockout_adjusted(30, 3, 7, cap=KitchenParams.from_dict({"stockout_cap": 1.5}).stockout_cap)
    assert weekly == pytest.approx(45)


def test_s11_inbound_is_not_an_emergency():
    parm = pack_info(row("469648", "ST", "ST", [("KI", 12), ("ST", 1)]), measure="ST")
    item = Item("469648", parm, daily_demand=4, lead_time_days=3, review_days=1, on_hand=10,
                on_order=30, safety_stock=6, category="dry")
    line = replenish(item, P)
    assert line.quantity == 0
    assert line.reason_codes == ("POSITION_OK",)
    assert "= 22 ST" in line.why   # 4 x (3 + 1) + 6


def test_s11_on_hand_alone_would_look_urgent():
    parm = pack_info(row("469648", "ST", "ST", [("ST", 1)]), measure="ST")
    item = Item("469648", parm, daily_demand=4, lead_time_days=3, review_days=1, on_hand=10,
                on_order=0, safety_stock=6, category="dry")
    line = replenish(item, P)
    assert line.quantity > 0 and line.urgency == Urgency.BEFORE_NEXT_DELIVERY


def test_s08_standing_order_drift_sizes_to_usage():
    item = Item("469549", ESL, daily_demand=20, lead_time_days=0, review_days=7, on_hand=120,
                safety_stock=20, category="fresh_dairy")
    assert replenish(item, P).quantity == 40


def test_s11_cover_ceiling_stops_cheap_hoarding():
    parm = pack_info(row("469648", "ST", "ST", [("ST", 1)]), measure="ST")
    item = Item("469648", parm, daily_demand=4, lead_time_days=3, review_days=1, on_hand=10,
                on_order=30, safety_stock=6, category="dry")
    params = KitchenParams.from_dict({"max_cover_days": {"dry": 14}})
    check = cover_limit(item, params, extra=150)
    assert check["max_extra"] == pytest.approx(34)        # 4 x (3 + 14) + 6 - 40, review 1 < 14
    assert check["over_ceiling"] and check["reason_codes"] == ("COVER_CEILING",)
    assert check["days_of_cover"] == pytest.approx(47.5)
    assert not cover_limit(item, params, extra=30)["over_ceiling"]


def test_cover_limit_zero_demand_gives_json_safe_none():
    parm = pack_info(row("469648", "ST", "ST", [("ST", 1)]), measure="ST")
    item = Item("469648", parm, daily_demand=0, lead_time_days=3, review_days=1, on_hand=10,
                safety_stock=0, category="dry")
    check = cover_limit(item, KitchenParams.from_dict({}), extra=5)
    assert check["days_of_cover"] is None
    json.dumps(check, allow_nan=False)


def test_rounding_up_to_lot():
    info = pack_info(row("x", "KG", "KG", [("KG", 1)], lot=2.5), measure="KG")
    assert to_sales_units(D(6), info) == (D("7.5"), True)
    assert to_sales_units(D(5), info) == (D(5), False)


def test_unknown_class_gets_a_level():
    assert P.z(None) == P.z("A") > P.z("C")


# ---- #274 compare more than price ----------------------------------------------------

def _milk(pid, price, available="100", reliability=None, carbon=None):
    product = row(pid, "ST", "ST", [("ST", 1)])
    pack = pack_info(product, price=D(price), comparison_price=D(price), comparison_unit="L", measure="L")
    return Offer(pid, f"milk {pid}", pack, D(price), D(available), False, MON,
                 reliability=reliability, carbon=carbon)


def test_reliable_offer_beats_slightly_cheaper_unreliable_one():
    cheap = _milk("A", "1.00", reliability=0.80)
    solid = _milk("B", "1.02", reliability=0.99)
    plan = plan_request(D(50), "L", [cheap, solid], MON, P)
    assert plan.lines[0].product_id == "B"
    assert "delivery reliability 99% vs 80%" in plan.lines[0].why
    assert plan.lines[0].reliability == 0.99


def test_outside_the_band_price_wins():
    cheap = _milk("A", "1.00", reliability=0.80)
    solid = _milk("B", "1.10", reliability=0.99)
    assert plan_request(D(50), "L", [cheap, solid], MON, P).lines[0].product_id == "A"


def test_unknown_reliability_is_never_best_then_carbon_decides():
    unknown = _milk("A", "1.00", reliability=None)
    known = _milk("B", "1.01", reliability=0.90)
    assert plan_request(D(50), "L", [unknown, known], MON, P).lines[0].product_id == "B"
    green = _milk("C", "1.02", reliability=0.90, carbon=1.1)
    plan = plan_request(D(50), "L", [known.__class__(**{**known.__dict__, "carbon": 1.6}), green], MON, P)
    assert plan.lines[0].product_id == "C" and "lower carbon" in plan.lines[0].why
