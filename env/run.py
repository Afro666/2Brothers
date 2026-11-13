"""Run a policy through Kitchen Week and print the score.

    python -m env.run --policy reference --seed 1
    python -m env.run --policy all --seeds 10 --kitchen hotel
"""

import argparse
import json
import statistics

from env import policies
from env.catalog import PRODUCTS
from env.week import RULES, KitchenWeek


def reference(env, obs) -> dict:
    """The engine: order what `policies.reference` computes, ask approval when the
    total is over the mandate limit."""
    if not obs["order_for"]:
        return {}
    from datetime import date
    lines = policies.reference(env.state, env.today, date.fromisoformat(obs["order_for"]), env.forecast,
                               env.unavailable)
    total = sum(PRODUCTS[p].price * u for p, u in lines.items())
    return {"order": lines, "request_approval": total > env.rules.auto_limit}


def do_nothing(env, obs) -> dict:
    return {}


def stop_early(env, obs) -> dict:
    """Behaves like the reference until Tuesday, then declares it is done."""
    if obs["today"] >= "2026-11-17":
        return {"stop": True}
    return reference(env, obs)


def ignore_notices(env, obs) -> dict:
    """The reference, but it does not read Valio's stock-out notice."""
    if not obs["order_for"]:
        return {}
    from datetime import date
    lines = policies.reference(env.state, env.today, date.fromisoformat(obs["order_for"]), env.forecast)
    total = sum(PRODUCTS[p].price * u for p, u in lines.items())
    return {"order": lines, "request_approval": total > env.rules.auto_limit}


def over_order(env, obs) -> dict:
    """Orders three times the reference and never asks for approval."""
    action = reference(env, obs)
    return {"order": {p: 3 * u for p, u in action.get("order", {}).items()}}


POLICIES = {"reference": reference, "do-nothing": do_nothing, "stop-early": stop_early,
            "ignore-notices": ignore_notices,
            "over-order": over_order}


def run(policy, seed: int = 1, kitchen: str = "restaurant") -> KitchenWeek:
    env = KitchenWeek(seed=seed, kitchen_type=kitchen)
    obs, done = env.reset(), False
    while not done:
        obs, _, done, _ = env.step(policy(env, obs))
    return env


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description="Kitchen Week: score an ordering policy")
    p.add_argument("--policy", choices=sorted(POLICIES) + ["all"], default="reference")
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--seeds", type=int, default=1, help="run seeds seed..seed+N-1, print mean and sd")
    p.add_argument("--kitchen", choices=sorted(RULES), default="restaurant")
    p.add_argument("--json", action="store_true", help="print the full report as JSON")
    a = p.parse_args(argv)
    names = sorted(POLICIES) if a.policy == "all" else [a.policy]
    seeds = range(a.seed, a.seed + a.seeds)

    if len(names) == 1 and a.seeds == 1:
        env = run(POLICIES[names[0]], a.seed, a.kitchen)
        r = env.report()
        if a.json:
            print(json.dumps({**r, "events": env.score.events}, indent=2))
            return
        print(f"Kitchen Week | {env.kitchen.name} | policy {names[0]} | seed {a.seed}")
        print(f"Valio stock-out: {env.stockout[0]} from {env.stockout[1]} to {env.stockout[2]}")
        for key, val in r.items():
            print(f"  {key:17} {val}")
        for e in env.score.events:
            print(f"  - {e}")
        print(f"score {r['score']:.2f}")
        return

    print(f"Kitchen Week | {a.kitchen} | seeds {a.seed}..{a.seed + a.seeds - 1}")
    print(f"{'policy':12} {'score mean':>11} {'sd':>8} {'lost cov':>9} {'waste':>8} {'penalty':>8}")
    for name in names:
        reports = [run(POLICIES[name], s, a.kitchen).report() for s in seeds]
        scores = [r["score"] for r in reports]
        sd = statistics.stdev(scores) if len(scores) > 1 else 0.0
        mean = lambda k: statistics.mean(r[k] for r in reports)  # noqa: E731
        print(f"{name:12} {statistics.mean(scores):11.0f} {sd:8.0f} {mean('lost_covers'):9.1f} "
              f"{mean('waste'):8.0f} {mean('mandate_penalty'):8.0f}")


if __name__ == "__main__":
    main()
