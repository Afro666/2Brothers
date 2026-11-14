"""Covers comparison (#433): python -m env.covers_backtest --write.

No live services. Optional --signals is a JSON array of versioned signal rows;
--feedback is a JSON array of feedback rows with explicitly joined outcomes.
"""
import argparse
from collections import defaultdict
from datetime import date, timedelta
import importlib.util
import json
import random
from pathlib import Path

from env.catalog import PRODUCTS
from env.covers import MODELS
from env.history import Forecaster
from env.kitchens import make_kitchens
from env.policies import reference
from env.sim import KitchenState, Order, actual_covers, lost_covers, serve_day
from signals.covers import CoverSignals

START = date(2026, 8, 17)
MARKER = "## Covers models v2 (#433)"


def run(kitchen, model_cls, seed, weeks=12, rows=()):
    rng = random.Random(f"covers-{seed}-{kitchen.id}")
    model = model_cls(kitchen, CoverSignals(kitchen, rows))
    warm = Forecaster(kitchen)
    state = KitchenState(kitchen)
    for pid in kitchen.products:
        daily = sum(warm(START + timedelta(days=i)) * kitchen.usage_per_cover(
            START + timedelta(days=i)).get(pid, 0) for i in range(7)) / 7
        state.add(pid, daily * 3, START)
    totals = dict(lost_covers=0., waste_eur=0., abs_error=0., actual=0.)
    week_prediction = {}
    for i in range(weeks * 7):
        day = START + timedelta(days=i)
        if i >= 21 and day.weekday() == 0:
            week_prediction = {day + timedelta(days=j): model(day + timedelta(days=j)) for j in range(7)}
        state.receive(day)
        covers = actual_covers(kitchen, day, rng)
        served = serve_day(state, day, covers, rng)
        if i >= 21:
            totals["lost_covers"] += lost_covers(kitchen, day, covers, served)
            totals["abs_error"] += abs(week_prediction[day] - covers)
            totals["actual"] += covers
        model.observe(day, covers)
        warm.observe(day, covers)
        for pid, qty in state.expire(day).items():
            if i >= 21:
                totals["waste_eur"] += qty * PRODUCTS[pid].price / PRODUCTS[pid].pack
        delivery = day + timedelta(days=1)
        if delivery.weekday() in kitchen.type.delivery_days:
            # Same reference ordering policy, same recipe explosion and same guests.
            forecast = model if i + 1 >= 21 else warm
            lines = reference(state, day, delivery, forecast)
            if lines:
                state.place(Order(f"{kitchen.id}-{i}", day, delivery, lines))
    totals["cost_eur"] = 4 * totals["lost_covers"] + totals["waste_eur"]
    return totals


def compare(seeds=range(1, 7), kitchens=20, weeks=12, rows=(), methods=None, progress=None):
    results = []
    for seed in seeds:
        totals = defaultdict(lambda: defaultdict(float))
        for k in make_kitchens(kitchens, seed):
            for name in methods or MODELS:
                metrics = run(k, MODELS[name], seed, weeks, rows)
                for metric, value in metrics.items():
                    totals[k.type.name, name][metric] += value
        for (kind, name), metrics in sorted(totals.items()):
            results.append(dict(seed=seed, kitchen_type=kind, model=name, **metrics))
        if progress:
            progress(seed)
    return results


def select(results, complete=True):
    """Select on seeds 1-3; require cost gains on every holdout seed (4-6).

    Both aggregate holdout lost covers and waste must also fall. No WAPE gate.
    An incomplete comparison never promotes a candidate.
    """
    selected = {}
    for kind in sorted({r["kitchen_type"] for r in results}):
        by = {(r["seed"], r["model"]): r for r in results if r["kitchen_type"] == kind}
        winner = "current"
        if complete and all((s, n) in by for s in range(1, 7) for n in MODELS):
            winner = min(MODELS, key=lambda n: sum(by[s, n]["cost_eur"] for s in range(1, 4)))
            improves = all(by[s, winner]["cost_eur"] < by[s, "current"]["cost_eur"] for s in range(4, 7))
            improves &= all(sum(by[s, winner][m] for s in range(4, 7)) <
                            sum(by[s, "current"][m] for s in range(4, 7))
                            for m in ("lost_covers", "waste_eur"))
            if not improves:
                winner = "current"
        selected[kind] = winner
    return selected


def feedback_value(rows):
    """Score qty_changed feedback only with a caller-joined, matching outcome.

    outcome requires kitchen_id/proposal_id/product_id/unit/actual_qty and a
    resolved_at timestamp later than the edit's ts. Units/horizon must be matched
    by the integration: order quantity edits are not automatically covers edits.
    FVA = |before - actual| - |after - actual|; positive means the edit helped.
    """
    import math
    from datetime import datetime
    result = dict(scored=0, unscorable=0, improved=0, worsened=0, unchanged=0, by_unit={})
    for row in rows:
        try:
            outcome = row["outcome"]
            if row["kind"] != "qty_changed" or any(row[k] != outcome[k] for k in (
                    "kitchen_id", "proposal_id", "product_id", "unit")):
                raise ValueError()
            if not row["unit"] or datetime.fromisoformat(outcome["resolved_at"]) <= datetime.fromisoformat(row["ts"]):
                raise ValueError()
            before, after, actual = (float(v) for v in (row["from_qty"], row["to_qty"], outcome["actual_qty"]))
            if not all(math.isfinite(v) and v >= 0 for v in (before, after, actual)):
                raise ValueError()
        except (KeyError, TypeError, ValueError):
            result["unscorable"] += 1
            continue
        delta = abs(before - actual) - abs(after - actual)
        result["scored"] += 1
        result["improved" if delta > 0 else "worsened" if delta < 0 else "unchanged"] += 1
        unit = result["by_unit"].setdefault(row["unit"], dict(before_abs_error=0., after_abs_error=0., fva=0.))
        unit["before_abs_error"] += abs(before - actual)
        unit["after_abs_error"] += abs(after - actual)
        unit["fva"] += delta
    return result


def report(results, complete, feedback=()):
    lines = [MARKER, "", "Reproduce: `python -m env.covers_backtest --write` (install `.[covers]`).",
             "20 kitchens, 12 weeks, 21-day warm-up; seeds 1-3 selection, 4-6 holdout.",
             "Weekly rolling origins: Monday forecasts Mon-Sun before observing Monday.",
             "Covers WAPE sums daily absolute errors, including closed days. Inventory orders",
             "update daily, with identical demand streams, recipes, reference policy and full supply.",
             "Cost = lost covers × 4 EUR + expired-stock waste EUR (#432 convention).", "",
             "Features: weekday, cyclical ISO week, Finnish public holidays, kitchen school holidays,",
             "temperature, rain, event flag, occupancy and reservations with missing indicators.",
             "Weather uses signals/weather snapshots; only as_of <= last observed day is visible.",
             "Training features use versions available on their observation day. No realized future weather.",
             "The existing synthetic guests contain no weather/events/bookings effects; these inputs",
             "are absent unless --signals supplies archived snapshots. This run cannot validate their benefit.",
             "Ridge models residuals around the planned pattern (alpha=10 fixed before evaluation).",
             "ETS: statsmodels additive level and weekly seasonality. All models use current for cold start.", "",
             "Comparison: " + ("complete." if complete else "**BLOCKED: statsmodels unavailable; ETS not run. No candidate adopted.**"), "",
             "| seed | type | model | covers WAPE | lost covers | waste EUR | cost EUR |",
             "|---|---|---|---|---|---|---|"]
    for r in results:
        lines.append(f"| {r['seed']} | {r['kitchen_type']} | {r['model']} | "
                     f"{r['abs_error'] / max(r['actual'], 1):.1%} | {r['lost_covers']:.1f} | "
                     f"{r['waste_eur']:.1f} | {r['cost_eur']:.1f} |")
    lines += ["", "Holdout cost regressions versus current (seed numbers):"]
    for kind in sorted({r["kitchen_type"] for r in results}):
        by = {(r["seed"], r["model"]): r for r in results if r["kitchen_type"] == kind}
        for model in sorted({r["model"] for r in results} - {"current"}):
            failures = [s for s in range(4, 7) if (s, model) in by and
                        by[s, model]["cost_eur"] >= by[s, "current"]["cost_eur"]]
            lines.append(f"- {kind}, {model}: {', '.join(map(str, failures)) or 'none'}.")
    lines += ["", "Selection: `" + json.dumps(select(results, complete), sort_keys=True) + "`.",
              "Candidates must lower selection cost, lower cost on every holdout seed, and lower",
              "both holdout aggregate lost covers and waste. Otherwise retain current per kitchen type.",
              "demo/seed.py uses env.covers.demo_forecaster for forecasts and menu plans.", "",
              "Human corrections FVA (positive = lower absolute quantity error, reported per unit):",
              "```json", json.dumps(feedback_value(feedback), sort_keys=True), "```",
              "No matched feedback outcomes means no measured chef benefit. Existing feedback rows",
              "need an explicit proposal/product/unit/horizon outcome join; purchase edits alone cannot",
              "be treated as corrected covers or realized demand. --feedback accepts these joined rows."]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--allow-missing-ets", action="store_true", help="provisional report only; never adopts a model")
    parser.add_argument("--signals", type=Path)
    parser.add_argument("--feedback", type=Path)
    args = parser.parse_args()
    complete = importlib.util.find_spec("statsmodels") is not None
    if not complete and not args.allow_missing_ets:
        parser.exit(1, "ETS comparison blocked: install .[covers] (statsmodels missing).\n")
    rows = json.loads(args.signals.read_text()) if args.signals else []
    feedback = json.loads(args.feedback.read_text()) if args.feedback else []
    results = compare(rows=rows, methods=list(MODELS) if complete else ["current", "ridge"],
                      progress=lambda seed: print(f"Completed seed {seed}", flush=True))
    text = report(results, complete, feedback)
    print(text)
    if args.write:
        path = Path(__file__).with_name("BACKTEST.md")
        old = path.read_text(encoding="utf-8").split(MARKER)[0].rstrip()
        path.write_text(old + "\n\n" + text, encoding="utf-8")


if __name__ == "__main__":
    main()
