"""Forecast accuracy: is the prediction true? Pure functions, no I/O.

Lesson from the production engine and env/BACKTEST.md: judge a forecast by weekly error
AND by what its errors cost. Under-order (stock-outs) and over-order (waste) are reported
separately; a near-zero bias can hide a wrong daily shape.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date


def iso_week(day: date) -> str:
    y, w, _ = day.isocalendar()
    return f"{y}-W{w:02d}"


def accuracy(pairs: list[tuple[str, date, float, float]]) -> dict:
    """`pairs`: (product_id, day, predicted, actual). Errors are per product and week.

    Returns totals: predicted, actual, WAPE (sum |p - a| / sum a), bias ((sum p - sum a) / sum a),
    under (sum of actual above predicted) and over (sum of predicted above actual).
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
    return {"predicted": round(pred, 2), "actual": round(act, 2),
            "wape": round(abs_err / base, 4), "bias": round((pred - act) / base, 4),
            "under": round(under, 2), "over": round(over, 2), "series": len(weekly)}


def accuracy_by_week(pairs: list[tuple[str, date, float, float]]) -> list[dict]:
    """One `accuracy` row per ISO week, oldest first."""
    by_week: dict[str, list] = defaultdict(list)
    for row in pairs:
        by_week[iso_week(row[1])].append(row)
    return [{"week": week, **accuracy(rows)} for week, rows in sorted(by_week.items())]
