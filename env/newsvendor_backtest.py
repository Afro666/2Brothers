"""Ordering-rule backtest (#432): fixed service level vs newsvendor, same guests.

    python -m env.newsvendor_backtest            # 20 kitchens x 12 weeks, seeds 1-3

Both rules order from the same forecast (covers x recipe) and see the same guests
(same demand seed); only the safety level differs. Cost = lost covers x price per cover
+ waste in EUR. Reported per seed, because the difference must hold on every seed.
"""

import random
import statistics
from datetime import timedelta
from env.backtest import START, Recipe
from env.catalog import PRODUCTS
from env.kitchens import make_kitchens
from env.policies import reference, newsvendor
from env.sim import KitchenState, Order, actual_covers, lost_covers, serve_day

PRICE = 4.0   # EUR a served cover earns on these ingredients (env/week.py rules scale)


def run(kitchen, policy, seed, weeks=12):
    rng = random.Random(f"nv-{seed}-{kitchen.id}")
    state = KitchenState(kitchen)
    warm = Recipe(kitchen)
    for pid in kitchen.products:
        daily = sum(warm.use(pid, START + timedelta(days=i)) for i in range(7)) / 7
        state.add(pid, 3 * daily, START)
    lost = waste = 0.0
    for i in range(weeks * 7):
        day = START + timedelta(days=i)
        state.receive(day, None)
        covers = actual_covers(kitchen, day, rng)
        served = serve_day(state, day, covers, rng)
        if i >= 21:
            lost += lost_covers(kitchen, day, covers, served)
        warm.observe(day, covers, {})
        for pid, qty in state.expire(day).items():
            if i >= 21:
                waste += qty * PRODUCTS[pid].price / PRODUCTS[pid].pack
        delivery = day + timedelta(days=1)
        if delivery.weekday() in kitchen.type.delivery_days:
            lines = policy(state, day, delivery, warm.covers)
            if lines:
                state.place(Order(f"{kitchen.id}-{i}", day, delivery, lines))
    return lost, waste


def compare(seeds=(1, 2, 3), kitchens: int = 20, weeks: int = 12) -> list[dict]:
    """One row per seed: lost covers, waste and total cost for both rules."""
    out = []
    for seed in seeds:
        row = {"seed": seed}
        for name, policy in (("reference", reference), ("newsvendor", newsvendor)):
            lost = waste = 0.0
            for k in make_kitchens(kitchens, seed):
                l, w = run(k, policy, seed, weeks)
                lost += l
                waste += w
            row[name] = {"lost_covers": round(lost), "waste_eur": round(waste),
                         "cost_eur": round(lost * PRICE + waste)}
        out.append(row)
    return out


def main() -> None:
    rows = compare()
    print("| seed | rule | lost covers | waste EUR | total cost EUR |")
    print("|---|---|---|---|---|")
    for row in rows:
        for name in ("reference", "newsvendor"):
            r = row[name]
            print(f"| {row['seed']} | {name} | {r['lost_covers']} | {r['waste_eur']} | {r['cost_eur']} |")
    ref = statistics.mean(r["reference"]["cost_eur"] for r in rows)
    new = statistics.mean(r["newsvendor"]["cost_eur"] for r in rows)
    print()
    print(f"Mean total cost: reference {ref:.0f} EUR, newsvendor {new:.0f} EUR ({(new / ref - 1) * 100:+.1f}%).")


if __name__ == "__main__":
    main()
