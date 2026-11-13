"""Demo data: synthetic history back to August, plans and forecasts four weeks ahead (#275).

    python -m demo.seed --dry-run              # build everything, print counts, write nothing
    python -m demo.seed                        # load into MONGODB_URI (idempotent)
    python -m demo.seed --today 2026-11-15 --future-weeks 4 --seed 1

What it makes, from env/ (Maciek's kitchen simulation, real Valio products and prices):
- 20 kitchens; the first hotel is renamed `demo-kitchen` (a hotel chain asks for the milk,
  as in Valio's brief). Four in five share their forecast with Valio.
- History from Mon 2026-08-17 up to yesterday: covers, stock counts, orders, deliveries.
- Forecasts, so the prediction can be proven: for each past week, the forecast as it was
  made the Monday before (engine: forecast covers x recipe; baseline: weekday average of
  real demand), and from today, the engine's forecast for the next weeks.
- demo-kitchen's recipes and menu plans for every week, past and future.
Nothing after today is an actual: the future has plans and forecasts only.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
import tempfile
import json

from env.backtest import WeekdayMA
from env.catalog import PRODUCTS
from env.history import Forecaster, simulate_kitchen
from env.kitchens import RECIPES, make_kitchens
from env.policies import POLICIES

START = date(2026, 8, 17)
DEMO_ID = "demo-kitchen"
VALIO = "sup-valio"
MEAL = "lunch"


def _day(row: dict) -> date:
    return datetime.fromisoformat(row["ts"]["$date"].replace("Z", "")).date()


def build(seed: int, today: date, future_weeks: int, kitchens: int = 20) -> dict:
    """Everything in memory. Pure apart from reading env/; deterministic for a seed."""
    end = today + timedelta(days=7 * future_weeks + (6 - today.weekday()))
    days = (end - START).days + 1
    all_k = make_kitchens(kitchens, seed)
    demo = next(k for k in all_k if k.type.name == "hotel")
    rename = {demo.id: DEMO_ID}
    out = defaultdict(list)
    for k in all_k:
        kid = rename.get(k.id, k.id)
        rows = simulate_kitchen(k, START, days, seed, POLICIES["reference"])
        actual_covers = {_day(r): r["covers"] for r in rows["covers"]}
        demand = defaultdict(dict)                      # day -> pid -> used + short
        for r in rows["stock"]:
            demand[_day(r)][r["meta"]["product_id"]] = r["used"] + r["short"]
        for name, items in rows.items():
            for r in items:
                if _day(r) >= today:
                    continue                            # the future has no actuals
                r["meta"]["kitchen_id"] = kid
                out[name].append(r)
        out["kitchens"].append({"kitchen_id": kid, "name": "Hotel Demo Helsinki" if kid == DEMO_ID else k.name,
                                "type": k.type.name, "city": k.city, "base_covers": k.base_covers,
                                "delivery_weekdays": list(k.type.delivery_days), "products": k.products})

        engine, baseline = Forecaster(k), WeekdayMA(k)
        for i in range(days):
            day = START + timedelta(days=i)
            if day < today and day.weekday() == 0:
                horizon = [day + timedelta(days=j) for j in range(7)]
            elif day == today:
                horizon = [day + timedelta(days=j) for j in range((end - day).days + 1)]
            else:
                horizon = []
            for target in horizon:
                if target >= today and day != today:
                    continue                            # future days: forecast made today
                use = k.usage_per_cover(target)
                for pid in k.products:
                    unit = PRODUCTS[pid].unit
                    need = round(engine(target) * use.get(pid, 0.0), 3)
                    out["forecasts"].append({
                        "kitchen_id": kid, "product_id": pid, "date": target.isoformat(), "need": need,
                        "unit": unit, "method": "engine", "made_on": day.isoformat(),
                        "why": f"{round(engine(target))} covers forecast x menu recipe quantity"})
                    if target < today:
                        out["baseline"].append({
                            "kitchen_id": kid, "product_id": pid, "date": target.isoformat(),
                            "need": round(baseline.use(pid, target), 3), "unit": unit,
                            "method": "weekday-average", "made_on": day.isoformat(),
                            "why": "mean of the last 4 same weekdays"})
            if day < today:
                engine.observe(day, actual_covers[day])
                baseline.observe(day, actual_covers[day], demand[day])

        if kid == DEMO_ID:
            out["recipes"] = [{"recipe_id": f"env-{name}", "name": name.replace("_", " ").capitalize(),
                               "portions": 1,
                               "ingredients": [{"product_id": pid, "qty_per_portion": str(q),
                                                "unit": PRODUCTS[pid].unit} for pid, q in items.items()]}
                              for name, items in RECIPES.items()]
            plan = Forecaster(k)
            weeks = defaultdict(list)
            for i in range(days):
                day = START + timedelta(days=i)
                if k.is_open(day):
                    covers = round(plan(day))
                    for recipe, share in k.menu(day):
                        y, w, _ = day.isocalendar()
                        weeks[f"{y}-W{w:02d}"].append({"date": day.isoformat(), "meal": MEAL,
                                                       "recipe_id": f"env-{recipe}",
                                                       "covers": max(round(covers * share), 0)})
                if day < today:
                    plan.observe(day, actual_covers[day])
            out["menu_plans"] = [{"week": w, "days": d} for w, d in sorted(weeks.items())]
    return out


def load(db, data: dict) -> dict:
    """Write `data` through the store (repository module). Safe to run again."""
    from store.history import load_history, save_forecasts, seed_sharing
    from store.repository import Repository

    ids = [k["kitchen_id"] for k in data["kitchens"]]
    with tempfile.TemporaryDirectory() as tmp:
        for name in ("kitchens", "stock", "covers", "orders", "deliveries"):
            with open(Path(tmp) / f"{name}.jsonl", "w", encoding="utf-8") as f:
                for row in data[name]:
                    f.write(json.dumps(row) + "\n")
        counts = load_history(db, Path(tmp))
    for name, rows in (("forecasts", data["forecasts"]), ("forecast_baseline", data["baseline"])):
        db[name].delete_many({"meta.kitchen_id": {"$in": ids}})
        counts[name] = save_forecasts(db, rows, collection=name)
    repo = Repository(db)
    for recipe in data["recipes"]:
        repo.recipes.delete(DEMO_ID, recipe["recipe_id"])
        repo.recipes.create(DEMO_ID, recipe)
    for plan in data["menu_plans"]:
        repo.menu_plans.put(DEMO_ID, plan["week"], plan["days"])
    counts["recipes"], counts["menu_plans"] = len(data["recipes"]), len(data["menu_plans"])
    counts["sharing"] = len(seed_sharing(db, ids, VALIO))
    return counts


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--today", type=date.fromisoformat, default=date.today())
    p.add_argument("--future-weeks", type=int, default=4)
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args(argv)
    data = build(a.seed, a.today, a.future_weeks)
    if a.dry_run:
        print({k: len(v) for k, v in data.items()})
        return
    from store.db import get_db
    print(load(get_db(), data))


if __name__ == "__main__":
    main()
