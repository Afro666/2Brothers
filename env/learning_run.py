"""Measure whether learned chef corrections transfer across chained Kitchen Weeks."""

import argparse
import math
import statistics
from datetime import date, timedelta

from env import policies
from env.catalog import PRODUCTS
from env.chef import Chef, Habits, apply_truth
from env.learn import correction_ratio, declined
from env.week import RULES, START, KitchenWeek


def _shortages(env, habit_products: set) -> int:
    """Count only habit-product shortages, separately from the env's total score."""
    return sum(1 for pid in env.last_day.get("short", {}) if pid in habit_products)


def _mark_ran_out(rows: list, day: date, short: dict) -> None:
    """Flag cuts followed by unmet demand within two days of their delivery."""
    for row in rows:
        if row["to_qty"] >= row["from_qty"] or row["product_id"] not in short:
            continue
        delivery = date.fromisoformat(row["day"])
        if delivery <= day <= delivery + timedelta(days=2):
            row["ran_out"] = True


def run_arm(seed: int, kitchen_type: str, weeks: int, learning: bool) -> list:
    """Run one arm with fresh stock each week and persistent correction history."""
    env = KitchenWeek(seed=seed, kitchen_type=kitchen_type)
    env.reset()
    habits = Habits.for_kitchen(env.kitchen, seed)
    chef = Chef(habits, seed)
    rows, reports = [], []

    for week in range(weeks):
        env = KitchenWeek(seed=seed, kitchen_type=kitchen_type, start=START + timedelta(days=7 * week))
        obs, done = env.reset(), False
        apply_truth(env, habits)
        habit_products = set(habits.factor) | habits.removed
        week_rows, habit_stockouts = [], 0
        while not done:
            action = {}
            if obs["order_for"]:
                delivery = date.fromisoformat(obs["order_for"])
                ratios = {pid: correction_ratio(rows, pid) for pid in env.kitchen.products} if learning else {}
                hidden = declined(rows) if learning else set()

                def believed(pid, day):
                    use = env.forecast(day) * env.believed_usage(day).get(pid, 0.0)
                    return use * (ratios.get(pid) or 1.0)

                proposal = policies.reference(
                    env.state, env.today, delivery, env.forecast, env.unavailable, demand=believed
                )
                for pid in hidden:
                    proposal.pop(pid, None)
                # What the engine proposes without any learning: the chef aims at the true need
                # from it, and the learner divides by it (in the product: the stored
                # forecast_need), so a learned correction is never applied twice.
                baseline = proposal if not learning else policies.reference(
                    env.state, env.today, delivery, env.forecast, env.unavailable,
                    demand=lambda pid, day: env.forecast(day) * env.believed_usage(day).get(pid, 0.0))
                order, edited = chef.edit(env, proposal, baseline)
                rows.extend(edited)
                week_rows.extend(edited)
                total = sum(PRODUCTS[pid].price * units for pid, units in order.items())
                action = {"order": order, "request_approval": total > env.rules.auto_limit}
            obs, _, done, _ = env.step(action)
            habit_stockouts += _shortages(env, habit_products)
            _mark_ran_out(rows, env.today, env.last_day.get("short", {}))

        changes = [row for row in week_rows
                   if row["kind"] == "qty_changed" and row["from_qty"] > 0 and row["to_qty"] > 0]
        report = env.report()
        reports.append({
            "week": week + 1,
            "edits": sum(row["reason"] != "IN_STOCK" for row in week_rows),
            "reasoned_edits": sum(row["reason"] is not None and row["reason"] != "IN_STOCK"
                                  for row in week_rows),
            "noise": sum(row["reason"] is None for row in week_rows),
            "mean_log_change": (statistics.mean(abs(math.log(row["to_qty"] / row["from_qty"]))
                                                for row in changes) if changes else 0.0),
            "score": report["score"],
            "lost_covers": report["lost_covers"],
            "waste": report["waste"],
            "habit_stockout_days": habit_stockouts,
        })
    return reports


def _mean(rows: list, key: str) -> float:
    return statistics.mean(row[key] for row in rows) if rows else 0.0


def _summary(name: str, rows: list) -> str:
    selected = [row for row in rows if 3 <= row["week"] <= 4]
    return (f"{name}: weeks 3-4 | edits {_mean(selected, 'edits'):.2f} | "
            f"score {_mean(selected, 'score'):.2f} | lost covers {_mean(selected, 'lost_covers'):.2f} | "
            f"waste {_mean(selected, 'waste'):.2f} | "
            f"habit stock-out days {_mean(selected, 'habit_stockout_days'):.2f}")


def _parse_seeds(value: str) -> list:
    parts = value.split("-", 1)
    try:
        first, last = int(parts[0]), int(parts[-1])
    except ValueError as exc:
        raise argparse.ArgumentTypeError("seeds must be a positive integer or range such as 1-5") from exc
    if first < 1 or last < first:
        raise argparse.ArgumentTypeError("seeds must be a positive integer or range such as 1-5")
    return list(range(first, last + 1))


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=_parse_seeds, default=[1, 2, 3, 4, 5])
    parser.add_argument("--weeks", type=int, default=4)
    parser.add_argument("--kitchen", choices=sorted(RULES) + ["all"], default="all")
    args = parser.parse_args(argv)
    if args.weeks < 1:
        parser.error("--weeks must be positive")
    kitchens = sorted(RULES) if args.kitchen == "all" else [args.kitchen]
    names = ("engine", "engine+learning")
    results = {name: [] for name in names}
    for kitchen in kitchens:
        for seed in args.seeds:
            for name in names:
                results[name].extend(run_arm(seed, kitchen, args.weeks, name.endswith("+learning")))

    print("| Arm | Week | Chef edits | Noise | Mean abs log change | Score | Lost covers | Waste | Habit stock-out days |")
    print("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for name in names:
        for week in range(1, args.weeks + 1):
            rows = [row for row in results[name] if row["week"] == week]
            print(f"| {name} | {week} | {_mean(rows, 'edits'):.2f} | {_mean(rows, 'noise'):.2f} | "
                  f"{_mean(rows, 'mean_log_change'):.3f} | {_mean(rows, 'score'):.2f} | "
                  f"{_mean(rows, 'lost_covers'):.2f} | {_mean(rows, 'waste'):.2f} | "
                  f"{_mean(rows, 'habit_stockout_days'):.2f} |")
    print()
    for name in names:
        print(_summary(name, results[name]))


if __name__ == "__main__":
    main()
