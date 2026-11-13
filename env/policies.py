"""Ordering policies. A policy decides, at the end of a day, what to order for the next
delivery: policy(state, today, delivery_day, forecast) -> {product_id: sales_units}.
`forecast(day) -> expected covers` is what the kitchen believes about future guests."""

import math
from datetime import timedelta

from env.catalog import PRODUCTS
from env.sim import next_delivery, round_to_pack

Z = {"A": 1.96, "B": 1.645, "C": 1.28}  # service level 97.5 / 95 / 90 %
CV = 0.15  # relative day-to-day noise of use (covers x recipe noise)


def reference(state, today, delivery, forecast) -> dict:
    """Deterministic engine stand-in: cover the days until the following delivery,
    plus safety stock, minus usable stock and stock on order; never more than can be
    used within shelf life; round up to whole sales units."""
    kitchen = state.kitchen
    following = next_delivery(kitchen, delivery) or delivery + timedelta(days=7)
    period = [delivery + timedelta(days=i) for i in range((following - delivery).days)]
    lines = {}
    for pid in kitchen.products:
        product = PRODUCTS[pid]
        per_day = [forecast(d) * kitchen.usage_per_cover(d).get(pid, 0.0) for d in period]
        need = sum(per_day)
        if need <= 0:
            continue
        safety = Z[product.abc] * CV * math.sqrt(sum(u * u for u in per_day))
        # Use between now and the delivery is already planned in today's stock; stock
        # that is no longer usable on delivery day does not count.
        gap_days = [today + timedelta(days=i) for i in range(1, (delivery - today).days)]
        before = sum(forecast(d) * kitchen.usage_per_cover(d).get(pid, 0.0) for d in gap_days)
        have = state.usable_on(pid, delivery) + state.on_order(pid, delivery) - before
        shelf_days = [delivery + timedelta(days=i) for i in range(product.shelf_life)]
        cap = sum(forecast(d) * kitchen.usage_per_cover(d).get(pid, 0.0) for d in shelf_days)
        qty = min(need + safety, cap) - max(0.0, have)
        units = round_to_pack(pid, qty)
        if units:
            lines[pid] = units
    return lines


def do_nothing(state, today, delivery, forecast) -> dict:
    return {}


POLICIES = {"reference": reference, "do-nothing": do_nothing}
