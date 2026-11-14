"""Measure whether learned chef corrections transfer across chained Kitchen Weeks."""

import argparse
import math
import statistics
from datetime import date, timedelta
from pathlib import Path

from env import policies
from env.catalog import PRODUCTS
from env.chef import Chef, Habits, apply_truth
from env.learn import correction_ratio, declined
from env.week import RULES, START, KitchenWeek

# The Nemotron arms (#1309 part 2): the Buyer of #365 (v3, thinking off) sizes the order
# itself; the memory arm also gets the learned facts in its system prompt (agent/memory.py).
LLM_MODEL = "nemotron-nothink-v3"
# Kitchen Week only: in the product the engine sizes every line; here the model does, so it
# is told what a correction fact means for its own number.
BENCHMARK_NOTE = ("In this benchmark you size the order yourself. A CORRECTION_RATIO fact means this "
                  "kitchen's chef keeps changing your quantity for that product to about `value` times "
                  "the expected use; a DECLINED_PRODUCT fact means the chef removes it, so do not order it.")


def learned_facts(rows: list, products, day: str) -> list:
    """The env learner's facts in the agent.memory shape, from the chef's rows so far."""
    facts = []
    for pid in products:
        ratio = correction_ratio(rows, pid)
        if ratio is not None:
            n = sum(1 for r in rows if r.get("product_id") == pid and r.get("reason") in ("TOO_MUCH", "TOO_LITTLE"))
            facts.append({"id": f"cr-{pid}", "kind": "CORRECTION_RATIO", "active": True, "product_id": pid,
                          "name": PRODUCTS[pid].name, "value": round(ratio, 2),
                          "evidence": {"rows": n, "last": day}})
    for pid in sorted(declined(rows)):
        facts.append({"id": f"dp-{pid}", "kind": "DECLINED_PRODUCT", "active": True, "product_id": pid,
                      "name": PRODUCTS[pid].name, "value": 1, "evidence": {"rows": 3, "last": day}})
    return facts


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


def run_arm(seed: int, kitchen_type: str, weeks: int, learning: bool, policy=None) -> list:
    """Run one arm with fresh stock each week and persistent correction history.

    `policy`: an env.llm.LLMPolicy that sizes the order instead of the engine (the Nemotron
    arms). With `learning`, it gets the learned facts as kitchen memory in its prompt."""
    env = KitchenWeek(seed=seed, kitchen_type=kitchen_type)
    env.reset()
    habits = Habits.for_kitchen(env.kitchen, seed)
    chef = Chef(habits, seed)
    rows, reports = [], []
    if policy is not None:
        policy.begin(env)        # one log and one token count for the whole arm, all weeks

    for week in range(weeks):
        env = KitchenWeek(seed=seed, kitchen_type=kitchen_type, start=START + timedelta(days=7 * week))
        obs, done = env.reset(), False
        apply_truth(env, habits)
        # The model's calculator sees what the engine believes, never the patched truth.
        env.believed_expected_use = (lambda pid, day, env=env:
                                     env.forecast(day) * env.believed_usage(day).get(pid, 0.0))
        habit_products = set(habits.factor) | habits.removed
        week_rows, habit_stockouts = [], 0
        while not done:
            action = {}
            if obs["order_for"]:
                delivery = date.fromisoformat(obs["order_for"])
                plain = (lambda pid, day: env.forecast(day) * env.believed_usage(day).get(pid, 0.0))
                if policy is not None:
                    if learning:
                        from agent.memory import kitchen_memory, prompt_block
                        facts = learned_facts(rows, env.kitchen.products, obs["today"])
                        block = prompt_block(kitchen_memory(facts, env.kitchen.products, []))
                        policy.memory = (block + "\n" + BENCHMARK_NOTE) if block else ""
                    proposal = dict((policy(env, obs) or {}).get("order") or {})
                    # The chef judges only its habit products on a model's proposal: a model
                    # quantity that differs from the engine's elsewhere is not a chef edit.
                    engine = policies.reference(env.state, env.today, delivery, env.forecast,
                                                env.unavailable, demand=plain)
                    baseline = {pid: (engine.get(pid, units) if pid in habit_products else units)
                                for pid, units in proposal.items()}
                else:
                    ratios = {pid: correction_ratio(rows, pid) for pid in env.kitchen.products} if learning else {}
                    hidden = declined(rows) if learning else set()

                    def believed(pid, day):
                        return plain(pid, day) * (ratios.get(pid) or 1.0)

                    proposal = policies.reference(
                        env.state, env.today, delivery, env.forecast, env.unavailable, demand=believed
                    )
                    for pid in hidden:
                        proposal.pop(pid, None)
                    # What the engine proposes without any learning: the chef aims at the true need
                    # from it, and the learner divides by it (in the product: the stored
                    # forecast_need), so a learned correction is never applied twice.
                    baseline = proposal if not learning else policies.reference(
                        env.state, env.today, delivery, env.forecast, env.unavailable, demand=plain)
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
    if policy is not None:
        policy.end(env)
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
    parser.add_argument("--nemotron", action="store_true",
                        help="also run the Nemotron arms (paid model calls; needs VERDA_INFERENCE_KEY)")
    args = parser.parse_args(argv)
    if args.weeks < 1:
        parser.error("--weeks must be positive")
    kitchens = sorted(RULES) if args.kitchen == "all" else [args.kitchen]
    names = ("engine", "engine+learning") + (("nemotron", "nemotron+memory") if args.nemotron else ())
    results = {name: [] for name in names}
    tokens = {name: 0 for name in names}
    for kitchen in kitchens:
        for seed in args.seeds:
            for name in names:
                policy = None
                if name.startswith("nemotron"):
                    from env.llm import LLMPolicy
                    policy = LLMPolicy(LLM_MODEL, out=Path("env/out/learning") / name)
                results[name].extend(run_arm(seed, kitchen, args.weeks,
                                             name.endswith(("+learning", "+memory")), policy))
                if policy is not None:
                    tokens[name] += policy.tokens

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
    for name in names:
        if tokens[name]:
            print(f"{name}: {tokens[name]} model tokens")


if __name__ == "__main__":
    main()
