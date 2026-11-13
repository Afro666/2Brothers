"""Demand corrections and safety stock."""

from __future__ import annotations

import math


def stockout_adjusted(used: float, days_in_stock: int, days_total: int, cap: float = 1.8) -> tuple[float, bool]:
    """Demand seen during a stock-out is undercounted (S10).

    Divide by the in-stock share, capped at `cap` x the raw number so one odd week does not
    over-order. Returns (demand, adjusted).
    """
    if days_total <= 0 or days_in_stock < 0 or days_in_stock > days_total:
        raise ValueError("days_in_stock must be between 0 and days_total")
    if days_in_stock == days_total or used <= 0:
        return float(used), False
    if days_in_stock == 0:
        return float(used) * cap, True
    scaled = used / (days_in_stock / days_total)
    return min(scaled, used * cap), True


def safety_stock(z: float, lead_time_days: float, daily_demand: float,
                 sigma_daily: float = 0.0, sigma_lead_time: float = 0.0) -> float:
    """Z * sqrt(LT * sigma_d^2 + d^2 * sigma_LT^2)."""
    if lead_time_days < 0 or daily_demand < 0 or sigma_daily < 0 or sigma_lead_time < 0:
        raise ValueError("inputs must be nonnegative")
    return z * math.sqrt(lead_time_days * sigma_daily ** 2 + daily_demand ** 2 * sigma_lead_time ** 2)
