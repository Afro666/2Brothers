"""Forecast accuracy: is the prediction true? Pure functions, no I/O.

Lesson from the production engine and env/BACKTEST.md: judge a forecast by weekly error
AND by what its errors cost. Under-order (stock-outs) and over-order (waste) are reported
separately; a near-zero bias can hide a wrong daily shape.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import ROUND_HALF_UP, Decimal


def iso_week(day: date) -> str:
    y, w, _ = day.isocalendar()
    return f"{y}-W{w:02d}"


def _eur(value: Decimal | None) -> str | None:
    return None if value is None else f"{value.quantize(Decimal('0.01'), ROUND_HALF_UP):f}"


def accuracy(pairs: list[tuple[str, date, float, float]], units: dict | None = None,
             prices: dict | None = None) -> dict:
    """`pairs`: (product_id, day, predicted, actual). Errors are per product and week.

    Returns totals: predicted, actual, WAPE (sum |p - a| / sum a), bias ((sum p - sum a) / sum a),
    under (sum of actual above predicted) and over (sum of predicted above actual).
    `units` ({product: kitchen unit}) adds `by_unit`, one row per unit (#1618); `under` and
    `over` are then None when the products have two or more units, never one sum over kg,
    l and pieces. `prices` ({product: Decimal EUR per kitchen unit}) adds euro values for
    the products that have one; `unpriced_series` counts the product-weeks without.
    """
    weekly: dict[tuple[str, str], list[float]] = defaultdict(lambda: [0.0, 0.0])
    for pid, day, predicted, actual in pairs:
        cell = weekly[(pid, iso_week(day))]
        cell[0] += predicted
        cell[1] += actual
    pred = sum(p for p, _ in weekly.values())
    act = sum(a for _, a in weekly.values())
    abs_err = sum(abs(p - a) for p, a in weekly.values())
    under = sum(max(a - p, 0.0) for p, a in weekly.values())
    over = sum(max(p - a, 0.0) for p, a in weekly.values())
    base = act or 1.0
    out = {"predicted": round(pred, 2), "actual": round(act, 2),
           "wape": round(abs_err / base, 4), "bias": round((pred - act) / base, 4),
           "under": round(under, 2), "over": round(over, 2), "series": len(weekly)}
    if units is None:
        return out
    prices = prices or {}
    rows: dict = {}
    unpriced = 0
    for (pid, _), (p, a) in weekly.items():
        row = rows.setdefault(units.get(pid), {"under": 0.0, "over": 0.0, "series": 0,
                                               "under_eur": None, "over_eur": None})
        short, waste = max(a - p, 0.0), max(p - a, 0.0)
        row["under"] += short
        row["over"] += waste
        row["series"] += 1
        price = prices.get(pid)
        if price is None:
            unpriced += 1
            continue
        for key, qty in (("under_eur", short), ("over_eur", waste)):
            row[key] = (row[key] or Decimal(0)) + Decimal(str(round(qty, 6))) * price

    def money_sum(key):
        values = [row[key] for row in rows.values() if row[key] is not None]
        return sum(values, Decimal(0)) if values else None

    if len(rows) > 1:
        out["under"] = out["over"] = None
    out["under_eur"], out["over_eur"] = _eur(money_sum("under_eur")), _eur(money_sum("over_eur"))
    out["unpriced_series"] = unpriced
    out["by_unit"] = [{"unit": unit, "under": round(row["under"], 2), "over": round(row["over"], 2),
                       "series": row["series"], "under_eur": _eur(row["under_eur"]),
                       "over_eur": _eur(row["over_eur"])}
                      for unit, row in sorted(rows.items(), key=lambda item: str(item[0] or ""))]
    return out


def accuracy_by_week(pairs: list[tuple[str, date, float, float]], units: dict | None = None,
                     prices: dict | None = None) -> list[dict]:
    """One `accuracy` row per ISO week, oldest first."""
    by_week: dict[str, list] = defaultdict(list)
    for row in pairs:
        by_week[iso_week(row[1])].append(row)
    return [{"week": week, **accuracy(rows, units, prices)} for week, rows in sorted(by_week.items())]
