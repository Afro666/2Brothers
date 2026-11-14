"""Delivery timing learned from delivery results, and the safety stock it adds (#1306).

Pure functions: no clock, no database. The gateway passes the kitchen's own current
delivery observations (docs/contract.md, "Outcomes and delivery observations").
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

from engine.demand import safety_stock
from engine.learning import (_belongs_to_supplier, _current_observations, _date, _decimal_string,
                             _evidence, _in_window, _lead_times, _number, _observation_date,
                             _supplier_lines)

MIN_DELIVERIES = 5                  # fewer known deliveries in eight weeks: nothing is learned
LATE_BELOW = Decimal("0.7")         # an on-time rate under this makes a supplier "late"
MAX_SIGMA_DAYS = Decimal(2)         # a wilder spread counts as two days
MAX_SHARE = Decimal("0.25")         # safety stock is at most a quarter of the line's need
_CENT = Decimal("0.01")


def on_time_rate(days_late: list) -> Decimal | None:
    """The share of deliveries that came on the promised day or earlier."""
    if not days_late:
        return None
    return Decimal(sum(1 for days in days_late if days <= 0)) / Decimal(len(days_late))


def mean_days_late(days_late: list) -> Decimal | None:
    """The mean over late deliveries only. An early delivery counts as 0 late days: it
    never cancels another delivery's lateness."""
    if not days_late:
        return None
    late = [Decimal(days) for days in days_late if days > 0]
    return sum(late, Decimal(0)) / Decimal(len(late)) if late else Decimal(0)


def sigma_lead_time(lead_times: list) -> Decimal | None:
    """The population standard deviation of the actual lead times, in days."""
    if not lead_times:
        return None
    values = [Decimal(value) for value in lead_times]
    mean = sum(values, Decimal(0)) / Decimal(len(values))
    variance = sum(((value - mean) ** 2 for value in values), Decimal(0)) / Decimal(len(values))
    return variance.sqrt()


def delivery_timing(kitchen_id: str, supplier_id: str, observations: list, today: date,
                    product_id: str | None = None) -> dict | None:
    """How one supplier delivered to one kitchen in the last eight weeks; with `product_id`,
    only the orders that held that product.

    One current reading per order. A delivery whose lateness nobody knows is left out,
    never counted as on time. None when fewer than five deliveries are known.
    """
    day = _date(today)
    if day is None:
        return None
    known: list[tuple[date, int, Decimal, dict]] = []
    for _, index, observation in _current_observations(observations, kitchen_id):
        when = _observation_date(observation)
        if when is None or not _in_window(when, day):
            continue
        if not _belongs_to_supplier(observation, supplier_id):
            continue
        if product_id is not None and not any(
                str(line.get("product_id")) == str(product_id)
                for line in _supplier_lines(observation, supplier_id)):
            continue
        late = _number(observation.get("days_late"))
        if late is None:
            continue
        known.append((when, index, late, observation))
    if len(known) < MIN_DELIVERIES:
        return None
    known.sort(key=lambda item: (item[0], item[1]))
    lateness = [item[2] for item in known]
    lead_times = _lead_times([item[3] for item in known])
    enough = len(lead_times) >= MIN_DELIVERIES      # a missing order time is never a zero-day lead
    scope = "supplier" if product_id is None else "product"
    late_count = sum(1 for days in lateness if days > 0)
    return {
        "deliveries": len(known),
        "late": late_count,
        "on_time_rate": on_time_rate(lateness),
        "mean_days_late": mean_days_late(lateness),
        "mean_lead_time": (sum(lead_times, Decimal(0)) / Decimal(len(lead_times))
                           if enough else None),
        "sigma_lead_time": sigma_lead_time(lead_times) if enough else None,
        "scope": scope,
        "evidence": {"rows": len(known), "late": late_count, "scope": scope,
                     **{key: value for key, value in
                        _evidence([item[0] for item in known], len(known)).items()
                        if key != "rows"}},
    }


def lead_time_for(term_days, learned_mean) -> Decimal:
    """The lead time the engine gets: the supplier's term, or the learned mean when the two
    differ by a day or more. Unknown on both sides is 0, as the engine's formula needs a number."""
    term, mean = _number(term_days), _number(learned_mean)
    if term is None:
        return mean if mean is not None and mean >= 0 else Decimal(0)
    if mean is not None and mean >= 0 and abs(mean - term) >= 1:
        return mean
    return term


def learned_safety_stock(need, daily_demand, timing: dict | None, fact: dict | None, *,
                         z: float, lead_time_days, unit: str | None = None,
                         ) -> tuple[Decimal, dict | None]:
    """Add the engine's safety stock for a late supplier's lead-time spread to one need.

    Only for an active SUPPLIER_LATE fact whose `timing` shows an on-time rate under 0.7
    and a spread above 0. Capped twice, so a few late deliveries cannot double an order:
    the spread counts for at most two days, and the result is at most a quarter of the need.
    Returns the need unchanged and None when nothing applies.
    """
    need_value = _number(need)
    if need_value is None:
        return need, None
    demand = _number(daily_demand)
    if (not isinstance(fact, dict) or fact.get("active") is not True
            or fact.get("kind") != "SUPPLIER_LATE" or not isinstance(timing, dict)):
        return need_value, None
    rate, sigma = timing.get("on_time_rate"), timing.get("sigma_lead_time")
    if rate is None or rate >= LATE_BELOW or sigma is None or sigma <= 0:
        return need_value, None
    if demand is None or demand <= 0 or need_value <= 0 or z <= 0:
        return need_value, None
    used = min(sigma, MAX_SIGMA_DAYS)
    lead = lead_time_for(lead_time_days, timing.get("mean_lead_time"))
    raw = safety_stock(z, float(lead), float(demand), 0.0, float(used))
    extra = Decimal(str(raw)).quantize(_CENT, rounding=ROUND_HALF_UP)
    limit = (need_value * MAX_SHARE).quantize(_CENT, rounding=ROUND_DOWN)
    capped = sigma > MAX_SIGMA_DAYS or extra > limit
    extra = min(extra, limit)
    if not extra.is_finite() or extra <= 0:
        return need_value, None
    adjusted = need_value + extra
    info = {
        "fact_id": fact.get("id"),
        "kind": "SUPPLIER_LATE",
        "name": fact.get("name"),
        "from_qty": _decimal_string(need_value),
        "to_qty": _decimal_string(adjusted),
        "safety_stock": _decimal_string(extra),
        "sigma_lead_time": float(used.quantize(_CENT, rounding=ROUND_HALF_UP)),
        "capped": capped,
        "evidence": dict(timing.get("evidence") or {}),
    }
    if unit is not None:
        info["unit"] = unit
    return adjusted, info
