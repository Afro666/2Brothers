"""Forecast backtest on the synthetic kitchen history (issue #136).

    python -m env.backtest                  # 20 kitchens x 12 weeks, seeds 1-3
    python -m env.backtest --write          # also writes env/BACKTEST.md

Each method forecasts daily demand per kitchen and product, and the same reference
ordering policy orders from that forecast. So the numbers show both how accurate a
method is and what its errors cost: under-order (stock-out days, unmet demand, lost
covers) and over-order (waste) are reported separately. The first 3 weeks are warm-up
(orders use the recipe forecast, nothing is scored).

Demand here is true demand (used + short), which a real kitchen does not see during a
stock-out; the engine corrects for that separately (#33).
"""

import argparse
import random
import statistics
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from env.catalog import PRODUCTS
from env.history import Forecaster, supplier_fill
from env.kitchens import make_kitchens
from env.policies import reference
from env.sim import KitchenState, Order, actual_covers, lost_covers, serve_day

START = date(2026, 8, 17)
WARMUP_DAYS = 21
SLOW_ZERO_SHARE = 0.5  # slow mover: no demand on at least half of the open days


class Recipe:
    """The engine's view: forecast covers x recipe quantity on that day's menu."""
    name = "recipe"

    def __init__(self, kitchen):
        self.kitchen = kitchen
        self.covers = Forecaster(kitchen)

    def observe(self, day, covers, demand):
        self.covers.observe(day, covers)

    def use(self, pid, day):
        return self.covers(day) * self.kitchen.usage_per_cover(day).get(pid, 0.0)


class WeekdayMA:
    """Mean of the last 4 same weekdays (knows the weekly rhythm, not the menu)."""
    name = "weekday-ma4"

    def __init__(self, kitchen):
        self.past = defaultdict(list)  # (pid, weekday) -> demands

    def observe(self, day, covers, demand):
        for pid, d in demand.items():
            self.past[pid, day.weekday()] = (self.past[pid, day.weekday()] + [d])[-4:]

    def use(self, pid, day):
        values = self.past.get((pid, day.weekday()))
        return sum(values) / len(values) if values else 0.0

    def has_history(self, pid, day):
        """A measured zero is history; an empty weekday window is not a forecast."""
        return bool(self.past.get((pid, day.weekday())))


class MovingAverage:
    """Flat mean of the last 28 days."""
    name = "ma28"

    def __init__(self, kitchen):
        self.past = defaultdict(list)

    def observe(self, day, covers, demand):
        for pid, d in demand.items():
            self.past[pid] = (self.past[pid] + [d])[-28:]

    def use(self, pid, day):
        values = self.past.get(pid)
        return sum(values) / len(values) if values else 0.0


class SBA:
    """Croston with the Syntetos-Boylan correction, for intermittent demand: smooths the
    size of non-zero demands and the interval between them; daily rate =
    (1 - alpha/2) * size / interval."""
    name = "croston-sba"
    alpha = 0.1

    def __init__(self, kitchen):
        self.size, self.interval, self.since = {}, {}, defaultdict(int)

    def observe(self, day, covers, demand):
        for pid, d in demand.items():
            self.since[pid] += 1
            if d > 1e-9:
                if pid not in self.size:
                    self.size[pid], self.interval[pid] = d, float(self.since[pid])
                else:
                    a = self.alpha
                    self.size[pid] += a * (d - self.size[pid])
                    self.interval[pid] += a * (self.since[pid] - self.interval[pid])
                self.since[pid] = 0

    def use(self, pid, day):
        if pid not in self.size:
            return 0.0
        return (1 - self.alpha / 2) * self.size[pid] / self.interval[pid]


METHODS = [Recipe, WeekdayMA, MovingAverage, SBA]


def run_kitchen(kitchen, method_cls, seed: int, weeks: int, shortages: bool = False):
    """One kitchen through the whole period. Returns per-product records and totals."""
    demand_rng = random.Random(f"backtest-demand-{seed}-{kitchen.id}")
    fill = supplier_fill(random.Random(f"backtest-fill-{seed}-{kitchen.id}")) if shortages else None
    state = KitchenState(kitchen)
    warm, method = Recipe(kitchen), method_cls(kitchen)
    for pid in kitchen.products:  # opening stock: 3 days of planned use, fresh
        daily = sum(warm.use(pid, START + timedelta(days=i)) for i in range(7)) / 7
        state.add(pid, 3 * daily, START)

    per = defaultdict(lambda: defaultdict(float))  # pid -> metric -> value
    open_days = 0
    lost = 0.0
    week_forecast = {}
    for i in range(weeks * 7):
        day = START + timedelta(days=i)
        scored = i >= WARMUP_DAYS
        if scored and day.weekday() == 0:  # Monday: forecast the week ahead
            week = [day + timedelta(days=j) for j in range(7)]
            week_forecast = {pid: sum(method.use(pid, d) for d in week) for pid in kitchen.products}
        state.receive(day, fill)
        covers = actual_covers(kitchen, day, demand_rng)
        served = serve_day(state, day, covers, demand_rng)
        demand = {pid: served.get(pid, (0.0, 0.0))[0] for pid in kitchen.products}
        if scored:
            open_days += covers > 0
            lost += lost_covers(kitchen, day, covers, served)
            for pid in kitchen.products:
                d, got = served.get(pid, (0.0, 0.0))
                p = per[pid]
                p["actual"] += d
                p["zero_days"] += covers > 0 and d <= 1e-9
                p["short_eur"] += (d - got) * PRODUCTS[pid].price / PRODUCTS[pid].pack
                p["stockout_days"] += d - got > 1e-6
                if day.weekday() == 6 and pid in week_forecast:  # Sunday: close the week
                    p["abs_err"] += abs(week_forecast[pid] - p["week_actual"] - d)
                    p["err"] += week_forecast[pid] - p["week_actual"] - d
                    p["scored_actual"] += p["week_actual"] + d
                    p["week_actual"] = 0.0
                else:
                    p["week_actual"] += d
        warm.observe(day, covers, demand)
        method.observe(day, covers, demand)
        for pid, qty in state.expire(day).items():
            if scored:
                per[pid]["waste_eur"] += qty * PRODUCTS[pid].price / PRODUCTS[pid].pack

        delivery = day + timedelta(days=1)
        if delivery.weekday() in kitchen.type.delivery_days:
            source = method if i + 1 >= WARMUP_DAYS else warm
            lines = reference(state, day, delivery, warm.covers, demand=source.use)
            if lines:
                state.place(Order(f"{kitchen.id}-{i}", day, delivery, lines))
    return per, open_days, lost


def classify(pid, p, open_days) -> str:
    if open_days and p["zero_days"] / open_days >= SLOW_ZERO_SHARE:
        return "slow"
    return PRODUCTS[pid].abc


def backtest(seed: int, kitchens: int = 20, weeks: int = 12, shortages: bool = False) -> dict:
    """{method: {"classes": {class: metrics}, "lost_covers": float}} for one seed."""
    out = {}
    all_kitchens = make_kitchens(kitchens, seed)
    for method_cls in METHODS:
        acc = defaultdict(lambda: defaultdict(float))
        lost_total = 0.0
        for k in all_kitchens:
            per, open_days, lost = run_kitchen(k, method_cls, seed, weeks, shortages)
            lost_total += lost
            for pid, p in per.items():
                for cls in (classify(pid, p, open_days), "all"):
                    for key in ("abs_err", "err", "scored_actual", "short_eur", "waste_eur", "stockout_days"):
                        acc[cls][key] += p[key]
                    acc[cls]["series"] += 1
        classes = {}
        for cls, a in acc.items():
            base = a["scored_actual"] or 1.0
            classes[cls] = {"wape": a["abs_err"] / base, "bias": a["err"] / base,
                            "stockout_days": a["stockout_days"], "short_eur": a["short_eur"],
                            "waste_eur": a["waste_eur"], "series": a["series"]}
        out[method_cls.name] = {"classes": classes, "lost_covers": lost_total}
    return out


def _ms(values, fmt):
    if len(values) == 1:
        return format(values[0], fmt)
    return f"{format(statistics.mean(values), fmt)} ± {format(statistics.stdev(values), fmt)}"


def report(results: list) -> str:
    """Markdown tables, mean ± sd over seeds."""
    names = list(results[0])
    lines = ["## Run-to-run noise first (recipe method, same settings, different seeds)", "",
             "| seed | WAPE all | lost covers | waste EUR |", "|---|---|---|---|"]
    for seed, r in enumerate(results, 1):
        c = r["recipe"]["classes"]["all"]
        lines.append(f"| {seed} | {c['wape']:.1%} | {r['recipe']['lost_covers']:.0f} | {c['waste_eur']:.0f} |")
    lines += ["", "## Methods (mean ± sd over seeds)", "",
              "| method | lost covers | WAPE all | bias all | stock-out days | unmet EUR | waste EUR |",
              "|---|---|---|---|---|---|---|"]
    for n in names:
        get = lambda k: [r[n]["classes"]["all"][k] for r in results]  # noqa: E731
        lines.append(f"| {n} | {_ms([r[n]['lost_covers'] for r in results], '.0f')} | "
                     f"{_ms([x * 100 for x in get('wape')], '.1f')}% | {_ms([x * 100 for x in get('bias')], '+.1f')}% | "
                     f"{_ms(get('stockout_days'), '.0f')} | {_ms(get('short_eur'), '.0f')} | {_ms(get('waste_eur'), '.0f')} |")
    lines += ["", "## Per class (mean over seeds)", "",
              "| class | series | method | WAPE | bias | stock-out days | unmet EUR | waste EUR |",
              "|---|---|---|---|---|---|---|---|"]
    for cls in ("A", "B", "C", "slow"):
        for n in names:
            rows = [r[n]["classes"].get(cls) for r in results if cls in r[n]["classes"]]
            if not rows:
                continue
            m = lambda k: statistics.mean(x[k] for x in rows)  # noqa: E731
            lines.append(f"| {cls} | {m('series'):.0f} | {n} | {m('wape'):.1%} | {m('bias'):+.1%} | "
                         f"{m('stockout_days'):.0f} | {m('short_eur'):.0f} | {m('waste_eur'):.0f} |")
    return "\n".join(lines)


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description="Forecast backtest on the kitchen history")
    p.add_argument("--seeds", type=int, default=3)
    p.add_argument("--kitchens", type=int, default=20)
    p.add_argument("--weeks", type=int, default=12)
    p.add_argument("--write", action="store_true", help="write env/BACKTEST.md")
    p.add_argument("--shortages", action="store_true",
                   help="keep Valio partial/missing deliveries (default off: isolates forecast error)")
    a = p.parse_args(argv)
    results = [backtest(s, a.kitchens, a.weeks, a.shortages) for s in range(1, a.seeds + 1)]
    text = report(results)
    print(text)
    if a.write:
        path = Path(__file__).with_name("BACKTEST.md")
        old = path.read_text(encoding="utf-8") if path.exists() else ""
        if FINDINGS in old and GENERATED in old:  # hand-written findings survive a rewrite
            findings = old[old.index(FINDINGS):old.index(GENERATED)]
        else:
            findings = FINDINGS + "\n\n(write the conclusions here)\n\n"
        text = findings + GENERATED + "\n\n" + text
        path.write_text(
            "# Forecast backtest\n\n" + HEADER.format(seeds=a.seeds, kitchens=a.kitchens, weeks=a.weeks,
                                                      shortages="on" if a.shortages else "off")
            + "\n" + text + "\n", encoding="utf-8")


FINDINGS = "## Findings"
GENERATED = "<!-- generated by python -m env.backtest --write; edit above this line -->"

HEADER = """Generated by `python -m env.backtest --write` ({kitchens} kitchens, {weeks} weeks, seeds
1-{seeds}; the first 3 weeks are warm-up). Each method forecasts daily demand per kitchen
and product; the same reference policy orders from it. WAPE and bias are on weekly
totals (forecast made Monday for Mon-Sun). Slow movers: no demand on at least half of the
open days (e.g. salmon in a school with a 5-day menu rotation), reported apart from A/B/C.
Valio supply shortages: {shortages} (off isolates forecast error; `--shortages` keeps them).
"""

if __name__ == "__main__":
    main()
