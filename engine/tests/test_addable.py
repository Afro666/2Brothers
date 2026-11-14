"""Addable products (#129): what the buyer can add to a proposal, most probable first."""

from dataclasses import replace
from decimal import Decimal as D

from engine import Item, KitchenParams
from engine.addable import Candidate, Timing, rank_addable, rank_key
from engine.packs import PackInfo

P = KitchenParams()
LITRE = PackInfo("ST", "L", D(1), D(1), derived=False)


def cand(pid, *, on_hand, daily=10.0, on_order=0.0, abc="B", price="1.00", review=3.0, lead=1.0):
    item = Item(pid, LITRE, daily_demand=daily, lead_time_days=lead, review_days=review,
                on_hand=on_hand, on_order=on_order, abc=abc, safety_stock=0.0)
    return Candidate(item, name=f"Product {pid}", unit_price=None if price is None else D(price))


def ids(rows):
    return [r.product_id for r in rows]


def test_rank_order_is_one_pinned_key():
    rows = rank_addable([
        cand("plenty", on_hand=500),                 # no action, many days of stock
        cand("month", on_hand=150),                  # can wait, but within a month
        cand("week", on_hand=35),                    # due now: this week
        cand("today", on_hand=5),                    # runs out today
        cand("empty", on_hand=0),                    # nothing available: first
        cand("nocount", on_hand=None),               # empty stock count: urgent (S09)
        cand("unused", on_hand=20, daily=0.0),       # no demand: unknown days, last
    ], P)
    assert ids(rows) == ["empty", "nocount", "today", "week", "month", "plenty", "unused"]
    assert [r.rank for r in rows] == list(range(1, 8))
    assert rows == sorted(rows, key=rank_key)


def test_engine_quantity_before_no_quantity_then_abc_then_weekly_demand():
    rows = rank_addable([
        cand("c_small", on_hand=0, abc="C", daily=5),
        cand("a_small", on_hand=0, abc="A", daily=5),
        cand("a_big", on_hand=0, abc="A", daily=50),
        cand("unknown_abc", on_hand=0, abc=None, daily=5),
    ], P)
    # Missing ABC ranks as A: a missing value is never the safe one.
    assert ids(rows) == ["a_big", "a_small", "unknown_abc", "c_small"]


def test_row_fields_and_why():
    (row,) = rank_addable([cand("m", on_hand=35, price="2.57")], P)
    assert row.timing is Timing.THIS_WEEK
    assert row.suggested_qty == D(5)          # 10/day x 4 days - 35
    assert row.unit == "ST" and row.unit_price == D("2.57") and row.addable
    assert row.on_hand == 35 and row.on_order == 0
    assert row.why == "The engine says order this week: 5 ST."
    assert row.days_of_stock == D("3.5")


def test_no_order_needed_yet_says_days_of_stock():
    (row,) = rank_addable([cand("m", on_hand=90)], P)
    assert row.suggested_qty == 0 and row.timing is Timing.THIS_MONTH
    assert row.why == "No order needed yet: 9 days of stock."


def test_empty_count_is_urgent_and_sized_as_if_empty():
    (row,) = rank_addable([cand("m", on_hand=None, daily=12, review=3, lead=0)], P)
    assert row.timing is Timing.TODAY and row.suggested_qty == D(36)
    assert row.days_of_stock is None
    assert "STOCK_COUNT_MISSING" in row.reason_codes
    assert row.why == "Stock count missing: count it first. Sized as if empty: 36 ST."


def test_row_without_price_cannot_be_added():
    (row,) = rank_addable([cand("m", on_hand=0, price=None)], P)
    assert not row.addable and row.unit_price is None
    assert row.why.endswith("No price yet, so it cannot be added.")


def test_products_already_on_the_proposal_are_left_out():
    rows = rank_addable([cand("a", on_hand=0), cand("b", on_hand=0)], P, on_proposal={"a"})
    assert ids(rows) == ["b"]


def test_on_order_counts_toward_days_of_stock():
    (row,) = rank_addable([cand("m", on_hand=10, on_order=80)], P)
    assert row.days_of_stock == D(9) and row.suggested_qty == 0


def test_quantity_without_demand_still_has_a_timing_and_a_why():
    """#242: safety stock above the position with zero demand used to raise KeyError."""
    item = Item("ss", LITRE, daily_demand=0.0, lead_time_days=1.0, review_days=3.0,
                on_hand=2.0, abc="A", safety_stock=10.0)
    (row,) = rank_addable([Candidate(item, name="ss", unit_price=D("1.00"))], P)
    assert row.suggested_qty == D(8)
    assert row.timing is Timing.THIS_WEEK
    assert row.why == "The engine says order this week: 8 ST."


def test_standing_order_drift_keeps_its_sentence_in_the_row_why():
    """#380: the row writes its own why; the engine's drift sentence must stay in it."""
    c = cand("m", on_hand=35, price="2.57")
    c = Candidate(replace(c.item, standing_order=D(20)), name=c.name, unit_price=c.unit_price)
    (row,) = rank_addable([c], P)
    assert "STANDING_ORDER_DRIFT" in row.reason_codes
    assert row.why == ("The engine says order this week: 5 ST. "
                       "Standing order 20 ST no longer matches usage: this delivery needs 5.")
