"""Replenishment: how much to order for one product, and why (S08-S11)."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from engine.demand import safety_stock
from engine.packs import PackInfo, to_sales_units
from engine.params import KitchenParams
from engine.urgency import Urgency, urgency


@dataclass(frozen=True)
class Item:
    """One product in one kitchen. Quantities are in `pack.measure` (L, KG or ST)."""

    product_id: str
    pack: PackInfo
    daily_demand: float
    lead_time_days: float
    review_days: float                 # days from this delivery to the next one
    on_hand: float | None              # None: the stock count is empty (S09)
    on_order: float = 0.0
    abc: str | None = None
    category: str | None = None
    sigma_daily: float = 0.0
    sigma_lead_time: float = 0.0
    safety_stock: float | None = None  # a fixed value overrides the formula
    demand_note: str = ""              # e.g. "stock-out adjusted from 30" (S10)
    demand_codes: tuple[str, ...] = ()
    standing_order: Decimal | None = None   # in sales units per delivery (S08)


DRIFT_TOLERANCE = Decimal("0.10")          # standing order more than 10% off the need: drift


def _drift(item: Item, qty: Decimal) -> str | None:
    """S08: a standing order that no longer matches usage. The engine only flags it;
    a person changes the standing order."""
    s = item.standing_order
    if s is None or s <= 0 or abs(s - qty) <= s * DRIFT_TOLERANCE:
        return None
    return (f" Standing order {_fmt(s)} {item.pack.sales_unit} no longer matches usage: "
            f"this delivery needs {_fmt(qty)}.")


@dataclass(frozen=True)
class LinePlan:
    product_id: str
    quantity: Decimal                  # in sales units
    unit: str
    urgency: Urgency
    reason_codes: tuple[str, ...]
    why: str
    numbers: dict = field(default_factory=dict)


def _fmt(x: float | Decimal) -> str:
    d = Decimal(str(round(float(x), 2))).normalize()
    return f"{d:f}"


def replenish(item: Item, params: KitchenParams) -> LinePlan:
    d, lt = item.daily_demand, item.lead_time_days
    if d < 0 or lt < 0 or item.review_days < 0 or item.on_order < 0:
        raise ValueError("demand, lead time, review days and on order must be nonnegative")
    ss = item.safety_stock if item.safety_stock is not None else safety_stock(
        params.z(item.abc), lt, d, item.sigma_daily, item.sigma_lead_time)
    # Kitchens order on delivery days, so this is periodic review: order up to what lasts
    # until the delivery after this one arrives (lead time + review days) plus safety stock.
    cover = lt + item.review_days
    target = d * cover + ss
    codes: list[str] = list(item.demand_codes)
    unknown = item.on_hand is None
    on_hand = 0.0 if unknown else float(item.on_hand)
    position = on_hand + item.on_order
    tier = urgency(item.on_hand, None if unknown else position, d, lt, target)
    m = item.pack.measure
    numbers = {"daily_demand": d, "safety_stock": round(ss, 2), "order_up_to": round(target, 2),
               "on_hand": item.on_hand, "on_order": item.on_order, "position": position}
    if item.standing_order is not None:
        numbers["standing_order"] = item.standing_order

    if unknown:
        codes.append("STOCK_COUNT_MISSING")
    elif position >= target:
        codes.append("POSITION_OK")
        why = (f"No order now: position {_fmt(position)} {m} (on hand {_fmt(on_hand)} + on order "
               f"{_fmt(item.on_order)}) covers {_fmt(cover)} days of {_fmt(d)} {m}/day + safety "
               f"{_fmt(ss)} = {_fmt(target)} {m}.")
        drift = _drift(item, Decimal(0))
        if drift:
            codes.append("STANDING_ORDER_DRIFT")
            why += drift
        return LinePlan(item.product_id, Decimal(0), item.pack.sales_unit, tier, tuple(codes), why, numbers)

    need = max(target - position, 0.0)
    qty, rounded = to_sales_units(Decimal(str(need)), item.pack)
    if rounded:
        codes.append("LOT_SIZE_ROUNDED")
    if item.pack.derived:
        codes.append("PACK_SIZE_DERIVED")
    numbers.update({"target": round(target, 2), "need": round(need, 2)})

    demand = f"{_fmt(d)} {m}/day" + (f" ({item.demand_note})" if item.demand_note else "")
    stock = ("stock count missing, sized as if empty; count it before sending" if unknown
             else f"on hand {_fmt(on_hand)} + on order {_fmt(item.on_order)}")
    why = (f"{_fmt(qty)} {item.pack.sales_unit}: {demand} x {_fmt(cover)} days + safety "
           f"{_fmt(ss)} {m}, {stock}.")
    drift = _drift(item, qty)
    if drift:
        codes.append("STANDING_ORDER_DRIFT")
        why += drift
    return LinePlan(item.product_id, qty, item.pack.sales_unit, tier, tuple(codes), why, numbers)


def cover_limit(item: Item, params: KitchenParams, extra: float) -> dict:
    """Check a quantity a person wants on top (S11 "it's cheap, get 150", or MOV padding).

    The ceiling is lead time + the category's max days of cover + safety stock, but never
    less than what lasts to the next delivery. Returns the most that fits and the days of
    cover `extra` would give; above the ceiling the line carries COVER_CEILING.
    """
    d, lt = item.daily_demand, item.lead_time_days
    ss = item.safety_stock if item.safety_stock is not None else safety_stock(
        params.z(item.abc), lt, d, item.sigma_daily, item.sigma_lead_time)
    on_hand = 0.0 if item.on_hand is None else float(item.on_hand)
    position = on_hand + item.on_order
    ceiling = d * (lt + max(item.review_days, params.cover_days(item.category))) + ss
    after = position + extra
    days = after / d if d > 0 else float("inf")
    return {"max_extra": max(ceiling - position, 0.0), "ceiling": ceiling,
            "days_of_cover": days, "over_ceiling": after > ceiling,
            "reason_codes": ("COVER_CEILING",) if after > ceiling else ()}
