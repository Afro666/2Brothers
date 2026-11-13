"""Kitchen Week: one seeded week of one kitchen, as an RL environment (issue #23).

    env = KitchenWeek(seed=1)
    obs = env.reset()
    while not done:
        obs, reward, done, info = env.step({"order": {"461903": 6}, "request_approval": False})
    env.report()

One step = the kitchen's 14:00 order decision, then the next day is simulated
(delivery 06:00, service, expiry). The week is Mon 2026-11-16 to Sun 2026-11-22.
Action: {"order": {product_id: sales_units}, "request_approval": bool, "stop": bool}.
"stop" ends the agent's turn early; the remaining days still run with no orders.
"""

import random
from dataclasses import dataclass, field
from datetime import date, timedelta

from env.catalog import PRODUCTS
from env.history import Forecaster
from env.kitchens import RECIPES, make_kitchens
from env.sim import KitchenState, Order, actual_covers, lost_covers, next_delivery, serve_day


@dataclass(frozen=True)
class Rules:
    price_per_cover: float  # menu price share these ingredients earn (ingredients ~35%)
    auto_limit: float  # order total (EUR) the agent may send alone
    hard_cap: float  # above this a human always refuses
    mov: float = 200.0  # minimum order value for free delivery
    delivery_fee: float = 45.0
    goodwill: float = 0.5  # extra penalty per lost cover, as a share of its price
    skip_approval_penalty: float = 300.0  # order over auto_limit sent without approval
    refused_penalty: float = 50.0  # order a human refuses, or a product outside the list
    excess_rate: float = 0.25  # charge on long-life stock left above the opening stock
    perishable_days: int = 7  # shelf life at or under this: leftover charged in full


RULES = {
    "school": Rules(7.0, 2000, 4000),
    "hospital": Rules(9.0, 1500, 3000),
    "hotel": Rules(9.0, 1100, 2200),
    "restaurant": Rules(10.0, 900, 1800),
}
START = date(2026, 11, 16)


@dataclass
class Score:
    revenue: float = 0.0
    food_cost: float = 0.0  # value of food eaten
    waste: float = 0.0  # value of food thrown away (expired)
    excess_stock: float = 0.0  # charge on stock left over at the end
    delivery_fees: float = 0.0
    stockout_penalty: float = 0.0
    mandate_penalty: float = 0.0
    covers: int = 0
    lost_covers: float = 0.0
    stockout_days: int = 0  # under-order: product-days with unmet demand
    wasted_qty: float = 0.0  # over-order: kitchen units thrown away
    orders: int = 0
    approvals: int = 0
    refused: int = 0
    events: list = field(default_factory=list)

    @property
    def total(self) -> float:
        return (self.revenue - self.food_cost - self.waste - self.excess_stock
                - self.delivery_fees - self.stockout_penalty - self.mandate_penalty)


def value(pid: str, qty: float) -> float:
    """EUR value of `qty` kitchen units."""
    p = PRODUCTS[pid]
    return qty * p.price / p.pack


class KitchenWeek:
    def __init__(self, seed: int = 1, kitchen_type: str = "restaurant", start: date = START):
        self.seed, self.kitchen_type, self.start = seed, kitchen_type, start

    # ---- episode ----
    def reset(self) -> dict:
        rng = random.Random(f"week-{self.seed}-{self.kitchen_type}")
        self.rng = rng
        pool = [k for k in make_kitchens(20, self.seed) if k.type.name == self.kitchen_type]
        self.kitchen = rng.choice(pool)
        self.rules = RULES[self.kitchen_type]
        self.state = KitchenState(self.kitchen)
        self.forecast = Forecaster(self.kitchen)
        self.today = self.start - timedelta(days=1)  # Sunday before the week
        self.end = self.start + timedelta(days=6)
        self.score = Score()
        self.stopped = False
        self.last_day = {}

        for pid in self.kitchen.products:  # opening stock: 2-4 days, partly aged
            life = PRODUCTS[pid].shelf_life
            daily = sum(self._expected_use(pid, self.start + timedelta(days=i)) for i in range(7)) / 7
            self.state.add(pid, daily * rng.uniform(2, 4), self.today,
                           shelf_life=max(2, life - rng.randrange(max(1, life // 2))))
        self.opening = {pid: self.state.on_hand(pid) for pid in self.kitchen.products}

        # The mid-week stock-out: Valio cannot deliver one of the kitchen's two most-used
        # menu-critical products Wednesday to Friday. Valio announces it (as its
        # availability API would): a good buyer stocks up before, or plans around it.
        critical = sorted((p for p in self.kitchen.products if PRODUCTS[p].abc == "A"),
                          key=self._week_use, reverse=True)
        self.stockout = (rng.choice(critical[:2]), self.start + timedelta(days=2),
                         self.start + timedelta(days=4))
        return self.observe()

    def unavailable(self, pid: str, day: date) -> bool:
        """True when Valio cannot deliver `pid` on `day`."""
        out_pid, first, last = self.stockout
        return pid == out_pid and first <= day <= last

    def step(self, action: dict = None):
        action = action or {}
        if self.today >= self.end:
            raise RuntimeError("episode is over, call reset()")
        if action.get("stop"):
            self.stopped = True
        if not self.stopped:
            self._order(action)
        before = self.score.total
        self._run_day(self.today + timedelta(days=1))
        while self.stopped and self.today < self.end:
            self._run_day(self.today + timedelta(days=1))
        done = self.today >= self.end
        if done:
            self._close()
        return self.observe(), self.score.total - before, done, {"events": self.last_day.get("events", [])}

    # ---- what the agent sees ----
    def observe(self) -> dict:
        tomorrow = self.today + timedelta(days=1)
        horizon = [self.today + timedelta(days=i) for i in range(1, 8)]
        k = self.kitchen
        return {
            "today": self.today.isoformat(),
            "kitchen": {"id": k.id, "name": k.name, "type": k.type.name,
                        "delivery_weekdays": list(k.type.delivery_days)},
            "order_for": tomorrow.isoformat() if self._can_order(tomorrow) else None,
            "next_delivery": (tomorrow if self._can_order(tomorrow) else next_delivery(k, tomorrow) or tomorrow).isoformat(),
            "rules": {"auto_limit_eur": self.rules.auto_limit, "hard_cap_eur": self.rules.hard_cap,
                      "mov_eur": self.rules.mov, "delivery_fee_eur": self.rules.delivery_fee},
            "stock": {
                pid: {"on_hand": round(self.state.on_hand(pid), 3), "unit": PRODUCTS[pid].unit,
                      "lots": [{"qty": round(l.qty, 3), "last_day": l.last_day.isoformat()}
                               for l in self.state.lots[pid]]}
                for pid in k.products
            },
            "valio_notices": [{"product_id": self.stockout[0], "unavailable_from": self.stockout[1].isoformat(),
                               "unavailable_to": self.stockout[2].isoformat()}],
            "on_order": [
                {"order_id": o.order_id, "delivery": d.isoformat(), "lines": o.lines}
                for d, orders in sorted(self.state.orders.items()) for o in orders
            ],
            "products": {pid: {"name": PRODUCTS[pid].name, "pack": PRODUCTS[pid].pack,
                               "sales_unit": PRODUCTS[pid].sales_unit, "price_eur": PRODUCTS[pid].price,
                               "shelf_life_days": PRODUCTS[pid].shelf_life}
                         for pid in k.products},
            "forecast": [{"date": d.isoformat(), "covers": round(self.forecast(d)),
                          "menu": [r for r, _ in k.menu(d)] if k.is_open(d) else []}
                         for d in horizon],
            "recipes": {r: q for r, q in RECIPES.items()
                        if any(r == m for d in horizon for m, _ in k.menu(d))},
            "yesterday": self.last_day,
        }

    def report(self) -> dict:
        s = self.score
        return {
            "score": round(s.total, 2), "revenue": round(s.revenue, 2), "food_cost": round(s.food_cost, 2),
            "waste": round(s.waste, 2), "excess_stock": round(s.excess_stock, 2),
            "delivery_fees": round(s.delivery_fees, 2), "stockout_penalty": round(s.stockout_penalty, 2),
            "mandate_penalty": round(s.mandate_penalty, 2), "covers": s.covers,
            "lost_covers": round(s.lost_covers, 1), "stockout_days": s.stockout_days,
            "wasted_qty": round(s.wasted_qty, 2), "orders": s.orders, "approvals": s.approvals,
            "refused": s.refused,
        }

    # ---- internals ----
    def _expected_use(self, pid: str, day: date) -> float:
        return self.forecast(day) * self.kitchen.usage_per_cover(day).get(pid, 0.0)

    def _week_use(self, pid: str) -> float:
        return sum(self._expected_use(pid, self.start + timedelta(days=i)) for i in range(7))

    def _can_order(self, delivery: date) -> bool:
        return delivery <= self.end and delivery.weekday() in self.kitchen.type.delivery_days

    def _order(self, action: dict) -> None:
        delivery = self.today + timedelta(days=1)
        lines, s, r = {}, self.score, self.rules
        for pid, units in (action.get("order") or {}).items():
            units = int(units)
            if units <= 0:
                continue
            if pid not in self.kitchen.products:
                s.mandate_penalty += r.refused_penalty
                s.refused += 1
                s.events.append(f"{self.today}: {pid} is not on this kitchen's product list, refused")
                continue
            lines[pid] = units
        if not lines:
            return
        if not self._can_order(delivery):
            s.events.append(f"{self.today}: no delivery on {delivery}, order ignored")
            return
        total = sum(PRODUCTS[pid].price * u for pid, u in lines.items())
        asked = bool(action.get("request_approval"))
        if total > r.hard_cap:
            # Never sent, asked or not; not asking costs more than asking.
            s.refused += 1
            s.approvals += asked
            s.mandate_penalty += r.refused_penalty + (0 if asked else r.skip_approval_penalty)
            how = "human refused" if asked else "gateway refused (no approval asked)"
            s.events.append(f"{self.today}: {how} EUR {total:.0f} (cap {r.hard_cap:.0f})")
            return
        if total > r.auto_limit:
            if asked:
                s.approvals += 1
            else:
                s.mandate_penalty += r.skip_approval_penalty
                s.events.append(f"{self.today}: EUR {total:.0f} sent without approval (limit {r.auto_limit:.0f})")
        if total < r.mov:
            s.delivery_fees += r.delivery_fee
        s.orders += 1
        self.state.place(Order(f"{self.kitchen.id}-W{s.orders:02d}", self.today, delivery, lines))

    def _fill(self, day: date):
        def fill(pid: str, units: int) -> int:
            return 0 if self.unavailable(pid, day) else units
        return fill

    def _run_day(self, day: date) -> None:
        s, k = self.score, self.kitchen
        events = []
        for order, pid, ordered, got in self.state.receive(day, self._fill(day)):
            if got < ordered:
                events.append(f"Valio could not deliver {pid} ({ordered - got} of {ordered} {PRODUCTS[pid].sales_unit})")
        covers = actual_covers(k, day, self.rng)
        served = serve_day(self.state, day, covers, self.rng)
        self.forecast.observe(day, covers)

        short = {}
        for pid, (demand, got) in served.items():
            s.food_cost += value(pid, got)
            if demand - got > 1e-6:
                short[pid] = round(demand - got, 3)
                s.stockout_days += 1
        lost = lost_covers(k, day, covers, served)
        s.covers += covers
        s.lost_covers += lost
        s.revenue += (covers - lost) * self.rules.price_per_cover
        s.stockout_penalty += lost * self.rules.price_per_cover * self.rules.goodwill

        waste = self.state.expire(day)
        for pid, qty in waste.items():
            s.waste += value(pid, qty)
            s.wasted_qty += qty
        if short:
            events.append(f"ran short of {', '.join(sorted(short))}, about {lost:.0f} covers lost")
        s.events += [f"{day}: {e}" for e in events]
        self.today = day
        self.last_day = {"date": day.isoformat(), "covers": covers, "lost_covers": round(lost, 1),
                         "short": short, "wasted": {p: round(q, 3) for p, q in waste.items()},
                         "events": events}

    def _close(self) -> None:
        r = self.rules
        for pid in self.kitchen.products:
            extra = value(pid, max(0.0, self.state.on_hand(pid) - self.opening[pid]))
            rate = 1.0 if PRODUCTS[pid].shelf_life <= r.perishable_days else r.excess_rate
            self.score.excess_stock += extra * rate
