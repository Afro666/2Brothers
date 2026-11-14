"""Newsvendor sizing for perishables, and prediction intervals (#432). Pure, no I/O.

How professionals size food that spoils: not "mean + Z x sigma for a fixed service level",
but the demand quantile at the critical ratio

    CR = cu / (cu + co)

cu = what one missing unit costs (guests not served), co = what one unit too many costs
(the part that will expire, plus a small holding cost for the part that keeps).
Cheap milk that stops a whole breakfast: CR near 1, order high. An expensive garnish that
spoils in two days: CR low, order close to the forecast.

The demand distribution comes from the kitchen's own forecast errors when there are enough
(empirical quantiles of actual / forecast); otherwise a normal with the given CV.
"""

from __future__ import annotations

from statistics import NormalDist

MIN_RESIDUALS = 20          # below this, the normal fallback is used
CR_FLOOR, CR_CEIL = 0.50, 0.995


def critical_ratio(cost_short: float, cost_over: float) -> float:
    """cu / (cu + co), kept inside [0.50, 0.995]: never plan to run out on purpose, and
    never chase a 100% service level that no stock can give."""
    if cost_short < 0 or cost_over < 0:
        raise ValueError("costs must be nonnegative")
    if cost_short + cost_over == 0:
        return CR_FLOOR
    return min(CR_CEIL, max(CR_FLOOR, cost_short / (cost_short + cost_over)))


def cost_over(unit_cost: float, period_days: float, shelf_life_days: float,
              holding_rate: float = 0.02) -> float:
    """Cost of one unit too many. If it cannot be used before it expires (shelf life no
    longer than the period it was bought for) the whole unit is lost; otherwise only the
    share of shelf life it blocks, plus a small holding cost."""
    if shelf_life_days <= 0:
        raise ValueError("shelf life must be positive")
    if shelf_life_days <= period_days:
        return unit_cost
    return unit_cost * (holding_rate + min(1.0, period_days / shelf_life_days) * 0.5)


def _quantile(sorted_values: list[float], q: float) -> float:
    if not sorted_values:
        raise ValueError("no values")
    pos = q * (len(sorted_values) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_values) - 1)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (pos - lo)


def demand_quantile(forecast: float, q: float, *, ratios: list[float] | None = None,
                    cv: float = 0.15) -> float:
    """The q-quantile of demand around a forecast. `ratios` are past actual / forecast
    values for this kitchen and product class; with fewer than MIN_RESIDUALS the normal
    fallback with coefficient of variation `cv` is used. Never below zero."""
    if forecast < 0:
        raise ValueError("forecast must be nonnegative")
    if not 0 < q < 1:
        raise ValueError("q must be between 0 and 1")
    clean = sorted(r for r in (ratios or []) if r is not None and r >= 0)
    if len(clean) >= MIN_RESIDUALS:
        return forecast * _quantile(clean, q)
    return max(0.0, forecast * (1 + NormalDist().inv_cdf(q) * cv))


def interval(forecast: float, *, ratios: list[float] | None = None, cv: float = 0.15) -> dict:
    """p10 / p50 / p90 for the forecast band on the screen."""
    return {"p10": round(demand_quantile(forecast, 0.10, ratios=ratios, cv=cv), 3),
            "p50": round(demand_quantile(forecast, 0.50, ratios=ratios, cv=cv), 3),
            "p90": round(demand_quantile(forecast, 0.90, ratios=ratios, cv=cv), 3)}


def order_up_to(forecast: float, cost_short: float, cost_over_unit: float, *,
                ratios: list[float] | None = None, cv: float = 0.15,
                shelf_cap: float | None = None) -> tuple[float, float]:
    """(target stock for the period, critical ratio). `shelf_cap` is what can be used
    before it expires: the target never goes above it."""
    cr = critical_ratio(cost_short, cost_over_unit)
    target = demand_quantile(forecast, cr, ratios=ratios, cv=cv)
    if shelf_cap is not None:
        target = min(target, shelf_cap)
    return target, cr


def why(product: str, cr: float, cost_short: float, cost_over_unit: float) -> str:
    return (f"{product}: ordered at the {cr * 100:.0f}% demand level, because one unit short costs "
            f"{cost_short:.2f} EUR and one unit too many costs {cost_over_unit:.2f} EUR.")
