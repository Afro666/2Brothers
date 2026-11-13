"""Ordering policies. A policy decides, at the end of a day, what to order for the next
delivery: policy(state, today, delivery_day, forecast) -> {product_id: sales_units}.
`forecast(day) -> expected covers` is what the kitchen believes about future guests."""

import math
from datetime import timedelta

from env.catalog import PRODUCTS
from env.sim import next_delivery, round_to_pack

Z = {"A": 1.96, "B": 1.645, "C": 1.28}  # service level 97.5 / 95 / 90 %
CV = 0.15  # relative day-to-day noise of use (covers x recipe noise)


def project(state, pid, today, until, use):
    """Expected FIFO run of current stock and open orders from tomorrow through `until`
    (inclusive), with expiry. Returns ({day: unmet qty}, usable qty left after `until`)."""
    lots = sorted(([l.qty, l.last_day] for l in state.lots[pid]), key=lambda l: l[1])
    pack, life = PRODUCTS[pid].pack, PRODUCTS[pid].shelf_life
    unmet, day = {}, today + timedelta(days=1)
    while day <= until:
        for order in state.orders.get(day, []):
            if pid in order.lines:
                lots.append([order.lines[pid] * pack, day + timedelta(days=life - 1)])
                lots.sort(key=lambda l: l[1])
        need = use(day)
        for lot in lots:
            take = min(lot[0], need)
            lot[0] -= take
            need -= take
        unmet[day] = need
        lots = [l for l in lots if l[0] > 1e-9 and l[1] > day]
        day += timedelta(days=1)
    return unmet, sum(l[0] for l in lots)


def reference(state, today, delivery, forecast, unavailable=None) -> dict:
    """Deterministic engine stand-in: project stock (FIFO, expiry, open orders) to the
    day before the following delivery, order the expected gap plus safety stock, never
    more than can be used within shelf life, rounded up to whole sales units.
    `unavailable(pid, day)` marks announced supplier stock-outs: then cover until the
    next delivery where the product is available again."""
    kitchen = state.kitchen
    blocked = unavailable or (lambda pid, day: False)
    lines = {}
    for pid in kitchen.products:
        product = PRODUCTS[pid]
        if blocked(pid, delivery):
            continue
        following = next_delivery(kitchen, delivery) or delivery + timedelta(days=7)
        while blocked(pid, following):
            following = next_delivery(kitchen, following) or following + timedelta(days=7)
        period = [delivery + timedelta(days=i) for i in range((following - delivery).days)]
        use = lambda d, pid=pid: forecast(d) * kitchen.usage_per_cover(d).get(pid, 0.0)  # noqa: E731
        per_day = [use(d) for d in period]
        if sum(per_day) <= 0:
            continue
        unmet, left = project(state, pid, today, period[-1], use)
        gap = sum(unmet[d] for d in period)
        safety = Z[product.abc] * CV * math.sqrt(sum(u * u for u in per_day))
        qty = gap + max(0.0, safety - left)
        cap = sum(use(delivery + timedelta(days=i)) for i in range(product.shelf_life))
        units = round_to_pack(pid, min(qty, cap))
        if units:
            lines[pid] = units
    return lines


def do_nothing(state, today, delivery, forecast) -> dict:
    return {}


POLICIES = {"reference": reference, "do-nothing": do_nothing}
