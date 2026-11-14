"""Standing-order drift: catch portion and cost creep before an order renews (#377).

A kitchen's weekly order per product, divided by the guests it served that week, should
stay about flat. When the last full week is well above the weeks before it, portions or
prices are creeping. One Atlas aggregation does the work on the time-series collections:

1. `orders_history` lines, summed per product and ISO week (`$dateTrunc`).
2. The same week's guests from `covers` (`$lookup` into the time-series collection).
3. Quantity and spend per 100 guests.
4. `$setWindowFields`: the mean of the previous `baseline_weeks` weeks, per product.

`flag()` then turns each product's last week into a warning, or nothing. It is plain
Python, so the rules are tested offline; the pipeline itself runs on Atlas only
(mongomock has neither `$dateTrunc` nor `$setWindowFields`).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from bson.decimal128 import Decimal128

THRESHOLD = 0.15        # 15% above the baseline is drift
BASELINE_WEEKS = 4
MIN_BASELINE_WEEKS = 3  # fewer weeks of history: not enough to call anything drift


def _monday(day: datetime) -> datetime:
    start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    return start - timedelta(days=start.weekday())


def pipeline(kitchen_id: str, since: datetime, until: datetime,
             baseline_weeks: int = BASELINE_WEEKS) -> list[dict]:
    """The aggregation over `orders_history`, from `since` (inclusive) to `until` (exclusive)."""
    week = {"$dateTrunc": {"date": "$ts", "unit": "week", "startOfWeek": "monday"}}
    window = {"documents": [-baseline_weeks, -1]}
    return [
        {"$match": {"meta.kitchen_id": kitchen_id, "ts": {"$gte": since, "$lt": until}}},
        {"$unwind": "$lines"},
        {"$group": {"_id": {"product_id": "$lines.product_id", "week": week},
                    "qty": {"$sum": "$lines.qty"},
                    "spend": {"$sum": {"$toDecimal": "$lines.line_total"}},
                    "unit": {"$first": "$lines.sales_unit"}}},
        {"$lookup": {
            "from": "covers",
            "let": {"week": "$_id.week"},
            "pipeline": [
                {"$match": {"meta.kitchen_id": kitchen_id, "$expr": {"$and": [
                    {"$gte": ["$ts", "$$week"]},
                    {"$lt": ["$ts", {"$dateAdd": {"startDate": "$$week", "unit": "week",
                                                  "amount": 1}}]}]}}},
                {"$group": {"_id": None, "covers": {"$sum": "$covers"}}}],
            "as": "guests"}},
        {"$set": {"product_id": "$_id.product_id", "week": "$_id.week",
                  "covers": {"$ifNull": [{"$first": "$guests.covers"}, 0]}}},
        # A week without guests says nothing about portions: leave it out of the window.
        {"$match": {"covers": {"$gt": 0}}},
        {"$set": {"qty_per_100": {"$multiply": [{"$divide": ["$qty", "$covers"]}, 100]},
                  "spend_per_100": {"$multiply": [{"$divide": ["$spend", "$covers"]}, 100]}}},
        {"$setWindowFields": {
            "partitionBy": "$product_id", "sortBy": {"week": 1},
            "output": {"baseline_qty": {"$avg": "$qty_per_100", "window": window},
                       "baseline_spend": {"$avg": "$spend_per_100", "window": window},
                       "baseline_weeks": {"$count": {}, "window": window}}}},
        {"$project": {"_id": 0, "guests": 0}},
        {"$sort": {"product_id": 1, "week": 1}},
    ]


def _number(value):
    if isinstance(value, Decimal128):
        return value.to_decimal()
    return value


def _change(now, before) -> float | None:
    if now is None or before in (None, 0):
        return None
    return float((Decimal(str(now)) - Decimal(str(before))) / Decimal(str(before)))


def _rate(value) -> str:
    """One decimal for a rate of 1 or more, two below it: 0.15 and 0.09 must not both
    read "0.1" next to "+63%"."""
    number = float(value)
    return f"{number:.1f}" if abs(number) >= 1 else f"{number:.2f}"


def flag(row: dict, threshold: float = THRESHOLD) -> dict | None:
    """A warning for one product's week, or None when it is within the threshold.

    `portion_creep`: more ordered per guest. `cost_creep`: the same amount per guest
    costs more (a price rise). A drop is not flagged: ordering less is not a risk a
    renewal would hide. Missing history is not drift: it returns None.
    """
    row = {key: _number(value) for key, value in row.items()}
    if (row.get("baseline_weeks") or 0) < MIN_BASELINE_WEEKS:
        return None
    qty = _change(row.get("qty_per_100"), row.get("baseline_qty"))
    spend = _change(row.get("spend_per_100"), row.get("baseline_spend"))
    if qty is not None and qty >= threshold:
        kind, change = "portion_creep", qty
    elif spend is not None and spend >= threshold:
        kind, change = "cost_creep", spend
    else:
        return None
    unit = row.get("unit") or "units"
    if kind == "portion_creep":
        why = (f"{_rate(row['qty_per_100'])} {unit} per 100 guests last week, "
               f"{_rate(row['baseline_qty'])} on average over the "
               f"{row['baseline_weeks']} weeks before (+{change:.0%}). "
               "Check portions before this order renews.")
    else:
        why = (f"EUR {float(row['spend_per_100']):.2f} per 100 guests last week, "
               f"EUR {float(row['baseline_spend']):.2f} on average over the "
               f"{row['baseline_weeks']} weeks before (+{change:.0%}) for the same amount. "
               "The price went up.")
    return {"product_id": str(row["product_id"]), "week": row["week"], "kind": kind,
            "change": round(change, 3), "unit": unit,
            "qty_per_100": round(float(row["qty_per_100"]), 2),
            "baseline_qty": round(float(row["baseline_qty"]), 2),
            "spend_per_100": round(float(row["spend_per_100"]), 2),
            "baseline_spend": round(float(row["baseline_spend"]), 2),
            "baseline_weeks": row["baseline_weeks"], "why": why}


def standing_order_drift(db, kitchen_id: str, now: datetime | None = None,
                         baseline_weeks: int = BASELINE_WEEKS,
                         threshold: float = THRESHOLD) -> list[dict]:
    """Drift warnings for the last full week before `now`, biggest change first."""
    now = now or datetime.now(timezone.utc)
    until = _monday(now)                      # the current, unfinished week is left out
    last = until - timedelta(weeks=1)
    since = until - timedelta(weeks=baseline_weeks + 1)
    rows = db.orders_history.aggregate(pipeline(kitchen_id, since, until, baseline_weeks))
    warnings = [warning for row in rows
                if _as_utc(row["week"]) == last and (warning := flag(row, threshold))]
    return sorted(warnings, key=lambda warning: -warning["change"])


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def main() -> None:
    """`python -m store.drift --kitchen K01 [--now 2026-11-16]`: print the warnings."""
    import argparse

    from store.db import get_db

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--kitchen", required=True)
    parser.add_argument("--now", help="ISO date; default today")
    parser.add_argument("--threshold", type=float, default=THRESHOLD)
    args = parser.parse_args()
    now = (datetime.fromisoformat(args.now).replace(tzinfo=timezone.utc)
           if args.now else None)
    warnings = standing_order_drift(get_db(), args.kitchen, now=now, threshold=args.threshold)
    for warning in warnings:
        print(f"{warning['product_id']} {warning['kind']}: {warning['why']}")
    if not warnings:
        print("no drift")


if __name__ == "__main__":
    main()
