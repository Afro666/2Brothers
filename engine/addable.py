"""Addable products (#129): what the buyer can add to a proposal, most probable first.

Pattern from Aron's production purchasing engine (docs/plan.md), no company data.
Pure: the caller loads the kitchen's items and prices; this ranks them.

Rank, one key (`rank_key`), first difference wins:
1. nothing on hand first;
2. rows the engine put a quantity on;
3. timing: today, this week, this month, no action;
4. days of stock, fewest first; unknown last, except an empty stock count, which is
   urgent (S09) and sorts as zero days;
5. ABC class (a missing class ranks as A: a missing value is never the safe one);
6. demand per week, highest first;
7. product code, so the order is stable.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from decimal import ROUND_HALF_UP, Decimal
from enum import IntEnum
from typing import Iterable

from engine.params import KitchenParams
from engine.quantity import Item, replenish
from engine.urgency import Urgency

MONTH_DAYS = 30
_ABC = {"A": 0, "B": 1, "C": 2}


class Timing(IntEnum):
    TODAY = 0
    THIS_WEEK = 1
    THIS_MONTH = 2
    NO_ACTION = 3


_WORDS = {Timing.TODAY: "today", Timing.THIS_WEEK: "this week", Timing.THIS_MONTH: "this month"}


@dataclass(frozen=True)
class Candidate:
    item: Item
    name: str
    unit_price: Decimal | None          # per sales unit, ex VAT; None: cannot be added


@dataclass(frozen=True)
class AddableRow:
    product_id: str
    name: str
    on_hand: float | None
    on_order: float
    suggested_qty: Decimal               # in sales units: what would ship
    unit: str
    unit_price: Decimal | None
    addable: bool
    timing: Timing
    days_of_stock: Decimal | None        # None: unknown (no use, or no stock count)
    abc: str | None
    weekly_demand: Decimal
    reason_codes: tuple[str, ...]
    why: str
    rank: int = 0
    nothing_on_hand: bool = field(default=False, repr=False)


def _n(x: Decimal) -> str:
    return f"{x.normalize():f}"


def _timing(tier: Urgency, days: Decimal | None) -> Timing:
    if tier in (Urgency.GUESTS_TODAY, Urgency.BEFORE_NEXT_DELIVERY):
        return Timing.TODAY
    if tier is Urgency.DUE_NOW:
        return Timing.THIS_WEEK
    if days is not None and days <= MONTH_DAYS:
        return Timing.THIS_MONTH
    return Timing.NO_ACTION


def rank_key(row: AddableRow) -> tuple:
    if row.on_hand is None:
        days = (0, Decimal(0))           # empty stock count: urgent (S09)
    elif row.days_of_stock is None:
        days = (1, Decimal(0))           # unknown: last
    else:
        days = (0, row.days_of_stock)
    return (0 if row.nothing_on_hand else 1, 0 if row.suggested_qty > 0 else 1,
            int(row.timing), days, _ABC.get(row.abc or "A", 0), -row.weekly_demand,
            row.product_id)


def _row(c: Candidate, params: KitchenParams) -> AddableRow:
    item = c.item
    plan = replenish(item, params)
    unknown = item.on_hand is None
    position = Decimal(str(plan.numbers["position"]))
    daily = Decimal(str(item.daily_demand))
    days = None if unknown or daily <= 0 else (position / daily).quantize(Decimal("0.1"), ROUND_HALF_UP)
    qty, unit = plan.quantity, plan.unit
    timing = _timing(plan.urgency, days)
    if qty > 0 and timing > Timing.THIS_WEEK:
        # The engine wants an order (e.g. safety stock above the position with no recent
        # use, #242): that is due now, never "this month" or "no action".
        timing = Timing.THIS_WEEK
    if unknown:
        why = f"Stock count missing: count it first. Sized as if empty: {_n(qty)} {unit}."
    elif qty > 0:
        why = f"The engine says order {_WORDS[timing]}: {_n(qty)} {unit}."
    elif days is None:
        why = "No order needed yet: no recent use."
    else:
        why = f"No order needed yet: {_n(days)} days of stock."
    if c.unit_price is None:
        why += " No price yet, so it cannot be added."
    return AddableRow(
        product_id=item.product_id, name=c.name, on_hand=item.on_hand, on_order=item.on_order,
        suggested_qty=qty, unit=unit, unit_price=c.unit_price, addable=c.unit_price is not None,
        timing=timing, days_of_stock=days, abc=item.abc, weekly_demand=daily * 7,
        reason_codes=plan.reason_codes, why=why,
        nothing_on_hand=not unknown and item.on_hand <= 0)


def rank_addable(candidates: Iterable[Candidate], params: KitchenParams,
                 on_proposal: Iterable[str] = ()) -> list[AddableRow]:
    """Rows for every candidate not already on the proposal, ranked, `rank` from 1."""
    skip = set(on_proposal)
    rows = sorted((_row(c, params) for c in candidates if c.item.product_id not in skip), key=rank_key)
    return [replace(r, rank=i) for i, r in enumerate(rows, start=1)]
