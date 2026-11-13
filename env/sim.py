"""Day-by-day kitchen stock simulation with shelf life.

Order of one day: morning delivery arrives -> guests eat (FIFO by expiry) -> expired
lots are thrown away -> stock is counted -> orders for the next delivery are placed.
Quantities are kitchen units (L, KG, PCS); orders and deliveries are sales units.
"""

import math
import random
from dataclasses import dataclass
from datetime import date, timedelta

from env.catalog import PRODUCTS
from env.kitchens import Kitchen


@dataclass
class Lot:
    qty: float
    last_day: date  # last day this lot may be used


@dataclass
class Order:
    order_id: str
    placed: date
    delivery: date
    lines: dict  # product_id -> sales units


class KitchenState:
    def __init__(self, kitchen: Kitchen):
        self.kitchen = kitchen
        self.lots = {pid: [] for pid in kitchen.products}
        self.orders = {}  # delivery date -> [Order]

    # ---- stock ----
    def add(self, pid: str, qty: float, day: date, shelf_life: int = None) -> None:
        life = PRODUCTS[pid].shelf_life if shelf_life is None else shelf_life
        self.lots[pid].append(Lot(qty, day + timedelta(days=life - 1)))
        self.lots[pid].sort(key=lambda lot: lot.last_day)

    def on_hand(self, pid: str) -> float:
        return sum(lot.qty for lot in self.lots[pid])

    def usable_on(self, pid: str, day: date) -> float:
        """Stock on hand that is still usable on `day`."""
        return sum(lot.qty for lot in self.lots[pid] if lot.last_day >= day)

    def on_order(self, pid: str, through: date) -> float:
        """Kitchen units ordered and arriving on or before `through`."""
        pack = PRODUCTS[pid].pack
        return sum(
            o.lines.get(pid, 0) * pack
            for d, orders in self.orders.items() if d <= through for o in orders
        )

    def consume(self, pid: str, need: float) -> float:
        """Use up to `need` from the oldest lots first. Returns the amount served."""
        served = 0.0
        lots = self.lots[pid]
        while lots and served < need - 1e-12:
            take = min(lots[0].qty, need - served)
            lots[0].qty -= take
            served += take
            if lots[0].qty <= 1e-12:
                lots.pop(0)
        return served

    def expire(self, day: date) -> dict:
        """Throw away lots whose last day is `day` or earlier. Returns waste per product."""
        waste = {}
        for pid, lots in self.lots.items():
            gone = [lot for lot in lots if lot.last_day <= day]
            if gone:
                waste[pid] = sum(lot.qty for lot in gone)
                self.lots[pid] = [lot for lot in lots if lot.last_day > day]
        return waste

    # ---- orders ----
    def place(self, order: Order) -> None:
        self.orders.setdefault(order.delivery, []).append(order)

    def receive(self, day: date, fill=None) -> list:
        """Book today's deliveries. `fill(pid, units) -> delivered units` models supplier
        shortages (default: everything arrives). Returns
        [(order, pid, ordered_units, delivered_units), ...]."""
        out = []
        for order in self.orders.pop(day, []):
            for pid, units in order.lines.items():
                got = units if fill is None else fill(pid, units)
                if got > 0:
                    self.add(pid, got * PRODUCTS[pid].pack, day)
                out.append((order, pid, units, got))
        return out


def next_delivery(kitchen: Kitchen, after: date, max_days: int = 14):
    """First delivery day strictly after `after`."""
    for i in range(1, max_days + 1):
        d = after + timedelta(days=i)
        if d.weekday() in kitchen.type.delivery_days:
            return d
    return None


def actual_covers(kitchen: Kitchen, day: date, rng: random.Random) -> int:
    expected = kitchen.base_covers * kitchen.factor(day)
    if expected <= 0:
        return 0
    return max(0, round(expected * rng.gauss(1.0, 0.08)))


def serve_day(state: KitchenState, day: date, covers: int, rng: random.Random) -> dict:
    """Guests eat. Returns {pid: (demand, served)} in kitchen units."""
    out = {}
    if covers <= 0:
        return out
    for pid, per_cover in state.kitchen.usage_per_cover(day).items():
        demand = covers * per_cover * max(0.0, rng.gauss(1.0, 0.1))
        out[pid] = (demand, state.consume(pid, demand))
    return out


def lost_covers(kitchen: Kitchen, day: date, covers: int, served: dict) -> float:
    """Guests lost on a day. A guest is lost when a menu-critical (A) ingredient of their
    dish is missing; a missing B/C ingredient costs a quarter of that (a worse plate,
    not no plate). `served` is serve_day's {pid: (demand, served)}."""
    from env.kitchens import RECIPES
    share = {}
    for recipe, part in kitchen.menu(day):
        for pid in RECIPES[recipe]:
            share[pid] = min(1.0, share.get(pid, 0.0) + part)
    worst_a = worst_other = 0.0
    for pid, (demand, got) in served.items():
        if demand - got > 1e-6:
            hit = (demand - got) / demand * share.get(pid, 0.0)
            if PRODUCTS[pid].abc == "A":
                worst_a = max(worst_a, hit)
            else:
                worst_other = max(worst_other, hit)
    return covers * min(1.0, worst_a + 0.25 * worst_other)


def round_to_pack(pid: str, qty: float) -> int:
    """Kitchen units -> whole sales units, rounded up."""
    if qty <= 1e-9:
        return 0
    return math.ceil(qty / PRODUCTS[pid].pack - 1e-9)
