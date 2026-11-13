"""Urgency tiers. A missing value is never "safe": unknown sorts with urgent."""

from __future__ import annotations

from enum import IntEnum


class Urgency(IntEnum):
    GUESTS_TODAY = 0          # runs out today: guests are affected
    BEFORE_NEXT_DELIVERY = 1  # runs out before the next delivery can arrive (or stock unknown)
    DUE_NOW = 2               # position is under the reorder point
    CAN_WAIT = 3


def urgency(on_hand: float | None, position: float | None, daily_demand: float,
            lead_time_days: float, reorder_point: float) -> Urgency:
    if on_hand is None or position is None:
        return Urgency.BEFORE_NEXT_DELIVERY
    if daily_demand <= 0:
        return Urgency.CAN_WAIT
    if on_hand < daily_demand:
        return Urgency.GUESTS_TODAY
    if position < daily_demand * lead_time_days:
        return Urgency.BEFORE_NEXT_DELIVERY
    if position < reorder_point:
        return Urgency.DUE_NOW
    return Urgency.CAN_WAIT
