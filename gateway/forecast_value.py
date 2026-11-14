"""Units and prices per kitchen unit for the forecast check (#1618).

The forecast check gives short and waste per kitchen unit and in euros, never one sum
over kg, l and pieces. The unit is the one the kitchen counts in (`kitchen_stock.unit`).
The price per kitchen unit is the latest `orders_history` line price (per sales unit)
divided by the kitchen units in one sales unit, as the deliveries show it:
`kitchen_stock.received` (kitchen units) over `deliveries.delivered_qty` (sales units) on
the same days. No order or no delivery: no price, never a guess.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation


def _num(value) -> float:
    try:
        return float(str(value)) if value is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def units_and_prices(db, kitchen_id: str, start: date, end: date) -> tuple[dict, dict]:
    """({product: kitchen unit}, {product: Decimal EUR per kitchen unit}) for one kitchen."""
    lo = datetime.combine(start, time.min, tzinfo=timezone.utc)
    hi = datetime.combine(end, time.max, tzinfo=timezone.utc)
    window = {"meta.kitchen_id": kitchen_id, "ts": {"$gte": lo, "$lte": hi}}
    units: dict[str, str] = {}
    received: dict[tuple, float] = defaultdict(float)
    for row in db.kitchen_stock.find(window, {"meta": 1, "ts": 1, "unit": 1, "received": 1}):
        pid = row["meta"]["product_id"]
        if row.get("unit"):
            units.setdefault(pid, row["unit"])
        if _num(row.get("received")) > 0:
            received[(pid, row["ts"].date())] += _num(row["received"])
    delivered: dict[tuple, float] = defaultdict(float)
    for row in db.deliveries.find(window, {"meta": 1, "ts": 1, "delivered_qty": 1}):
        if _num(row.get("delivered_qty")) > 0:
            delivered[(row["meta"]["product_id"], row["ts"].date())] += _num(row["delivered_qty"])
    kitchen_units: dict[str, float] = defaultdict(float)
    sales_units: dict[str, float] = defaultdict(float)
    for key, qty in delivered.items():
        if key in received:
            kitchen_units[key[0]] += received[key]
            sales_units[key[0]] += qty
    latest: dict[str, Decimal] = {}
    orders = db.orders_history.find({"meta.kitchen_id": kitchen_id, "ts": {"$lte": hi}},
                                    {"ts": 1, "lines": 1}).sort("ts", 1)
    for order in orders:
        for line in order.get("lines") or []:
            try:
                price = Decimal(str(line.get("unit_price")))
            except (InvalidOperation, TypeError, ValueError):
                continue
            if line.get("product_id") and price.is_finite() and price >= 0:
                latest[line["product_id"]] = price
    prices = {}
    for pid, price in latest.items():
        if sales_units.get(pid) and kitchen_units.get(pid):
            pack = Decimal(str(round(kitchen_units[pid] / sales_units[pid], 6)))
            if pack > 0:
                prices[pid] = price / pack
    return units, prices
