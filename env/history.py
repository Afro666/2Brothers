"""Synthetic order and stock history for many kitchens (issue #32).

    python -m env.history --seed 1 --out env/out/history

Writes JSON Lines files for MongoDB time-series collections; dates use MongoDB
Extended JSON ({"$date": ...}) so `mongoimport` and `bson.json_util` read them as
dates. Field reference: env/README.md.
"""

import argparse
import json
import random
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from pathlib import Path

from env.catalog import PRODUCTS
from env.kitchens import RECIPES, make_kitchens
from env.policies import POLICIES
from env.sim import KitchenState, Order, actual_covers, serve_day

PARTIAL, MISSING = 0.04, 0.015  # chance per delivery line of a Valio shortage


def ts(day: date, hour: int) -> dict:
    return {"$date": datetime.combine(day, time(hour)).isoformat() + "Z"}


def _r(x: float) -> float:
    return round(x, 3)


class Forecaster:
    """Kitchen's own guest forecast: the planned pattern (weekday, season, holidays)
    times the recent level (actual / planned over the last 14 open days)."""

    def __init__(self, kitchen):
        self.kitchen = kitchen
        self.ratios = []

    def observe(self, day: date, covers: int) -> None:
        planned = self.kitchen.base_covers * self.kitchen.factor(day)
        if planned > 0:
            self.ratios = (self.ratios + [covers / planned])[-14:]

    def __call__(self, day: date) -> float:
        level = sum(self.ratios) / len(self.ratios) if self.ratios else 1.0
        return self.kitchen.base_covers * self.kitchen.factor(day) * level


def supplier_fill(rng: random.Random):
    def fill(pid: str, units: int) -> int:
        r = rng.random()
        if r < MISSING:
            return 0
        if r < MISSING + PARTIAL:
            return units // 2
        return units
    return fill


def simulate_kitchen(kitchen, start: date, days: int, seed: int, policy) -> dict:
    # Separate streams: demand (opening stock, covers, recipe noise) must not depend on
    # which lines the policy orders, so every policy sees the same guests.
    rng = random.Random(f"history-{seed}-{kitchen.id}-demand")
    state = KitchenState(kitchen)
    forecast = Forecaster(kitchen)
    fill = supplier_fill(random.Random(f"history-{seed}-{kitchen.id}-supply"))
    rows = defaultdict(list)

    # Opening stock: 2-5 days of expected use, partly aged.
    for pid in kitchen.products:
        daily = sum(
            forecast(start + timedelta(days=i)) * kitchen.usage_per_cover(start + timedelta(days=i)).get(pid, 0)
            for i in range(7)
        ) / 7
        life = PRODUCTS[pid].shelf_life
        state.add(pid, daily * rng.uniform(2, 5), start, shelf_life=max(2, life - rng.randrange(life)))

    order_no = 0
    for i in range(days):
        day = start + timedelta(days=i)
        received = defaultdict(float)
        for order, pid, ordered, got in state.receive(day, fill):
            received[pid] += got * PRODUCTS[pid].pack
            rows["deliveries"].append({
                "ts": ts(day, 6), "meta": {"kitchen_id": kitchen.id, "product_id": pid},
                "order_id": order.order_id, "ordered_qty": ordered, "delivered_qty": got,
                "status": "full" if got == ordered else ("missing" if got == 0 else "partial"),
            })

        covers = actual_covers(kitchen, day, rng)
        planned = forecast(day)
        served = serve_day(state, day, covers, rng)
        forecast.observe(day, covers)
        waste = state.expire(day)
        rows["covers"].append({
            "ts": ts(day, 0), "meta": {"kitchen_id": kitchen.id, "type": kitchen.type.name},
            "covers": covers, "forecast_covers": round(planned),
            "open": kitchen.is_open(day), "menu": [r for r, _ in kitchen.menu(day)] if kitchen.is_open(day) else [],
        })
        for pid in kitchen.products:
            demand, got = served.get(pid, (0.0, 0.0))
            rows["stock"].append({
                "ts": ts(day, 22), "meta": {"kitchen_id": kitchen.id, "product_id": pid},
                "unit": PRODUCTS[pid].unit, "on_hand": _r(state.on_hand(pid)),
                "received": _r(received.get(pid, 0.0)), "used": _r(got),
                "short": _r(demand - got), "wasted": _r(waste.get(pid, 0.0)),
            })

        delivery = day + timedelta(days=1)
        if delivery.weekday() in kitchen.type.delivery_days:
            lines = policy(state, day, delivery, forecast)
            if lines:
                order_no += 1
                order = Order(f"{kitchen.id}-{order_no:04d}", day, delivery, lines)
                state.place(order)
                priced = [
                    {"product_id": pid, "qty": u, "sales_unit": PRODUCTS[pid].sales_unit,
                     "unit_price": PRODUCTS[pid].price, "line_total": round(u * PRODUCTS[pid].price, 2)}
                    for pid, u in sorted(lines.items())
                ]
                rows["orders"].append({
                    "ts": ts(day, 14), "meta": {"kitchen_id": kitchen.id},
                    "order_id": order.order_id, "delivery_date": ts(delivery, 6),
                    "lines": priced, "total_eur": round(sum(l["line_total"] for l in priced), 2),
                })
    return rows


def generate(out: Path, seed: int = 1, kitchens: int = 20, weeks: int = 12,
             start: date = date(2026, 8, 17), policy: str = "reference") -> dict:
    out.mkdir(parents=True, exist_ok=True)
    all_kitchens = make_kitchens(kitchens, seed)
    rows = defaultdict(list)
    for k in all_kitchens:
        for name, items in simulate_kitchen(k, start, weeks * 7, seed, POLICIES[policy]).items():
            rows[name].extend(items)
    rows["kitchens"] = [
        {"kitchen_id": k.id, "name": k.name, "type": k.type.name, "city": k.city,
         "base_covers": k.base_covers, "delivery_weekdays": list(k.type.delivery_days),
         "products": k.products}
        for k in all_kitchens
    ]
    rows["products"] = [
        {"product_id": p.id, "name": p.name, "unit": p.unit, "pack": p.pack,
         "sales_unit": p.sales_unit, "price_eur": p.price, "shelf_life_days": p.shelf_life, "abc": p.abc}
        for p in PRODUCTS.values()
    ]
    rows["recipes"] = [{"recipe": r, "per_cover": q} for r, q in RECIPES.items()]
    for name, items in rows.items():
        with open(out / f"{name}.jsonl", "w", encoding="utf-8", newline="\n") as f:
            for item in items:
                f.write(json.dumps(item, separators=(",", ":")) + "\n")
    return rows


def summary(rows) -> str:
    used = sum(r["used"] for r in rows["stock"])
    short = sum(r["short"] for r in rows["stock"])
    wasted = sum(r["wasted"] for r in rows["stock"])
    by_weekday = defaultdict(list)
    for c in rows["covers"]:
        by_weekday[datetime.fromisoformat(c["ts"]["$date"][:-1]).weekday()].append(c["covers"])
    rhythm = " ".join(
        f"{d}:{sum(v) / len(v):.0f}" for d, v in zip("MTWTFSS", (by_weekday[i] for i in range(7)))
    )
    deliveries = rows["deliveries"]
    lines = [f"{name}.jsonl: {len(items)} rows" for name, items in rows.items()]
    lines += [
        f"avg covers per weekday: {rhythm}",
        f"used {used:.0f}, short {short:.0f} ({short / max(used + short, 1):.1%} of demand), "
        f"wasted {wasted:.0f} ({wasted / max(used + wasted, 1):.1%} of stock out)",
        f"order spend EUR {sum(o['total_eur'] for o in rows['orders']):,.0f}; "
        f"deliveries partial {sum(d['status'] == 'partial' for d in deliveries)}, "
        f"missing {sum(d['status'] == 'missing' for d in deliveries)}",
    ]
    return "\n".join(lines)


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--kitchens", type=int, default=20)
    p.add_argument("--weeks", type=int, default=12)
    p.add_argument("--start", type=date.fromisoformat, default=date(2026, 8, 17))
    p.add_argument("--policy", choices=sorted(POLICIES), default="reference")
    p.add_argument("--out", type=Path, default=Path("env/out/history"))
    a = p.parse_args(argv)
    rows = generate(a.out, a.seed, a.kitchens, a.weeks, a.start, a.policy)
    print(f"wrote {a.out}")
    print(summary(rows))


if __name__ == "__main__":
    main()
