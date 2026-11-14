"""Give the seeded menu entries the meal of their recipe, and change nothing else (#1618).

    python -m demo.fix_meals                          # dry run: how many entries would change
    python -m demo.fix_meals --apply                  # write the meals
    python -m demo.fix_meals --kitchen demo-kitchen --apply

Before #1618 the seed wrote every menu entry as "lunch", even the breakfast buffet. This
command fixes that in place, without re-running the whole seed: per ISO week it reads the
menu plan and changes only `meal`, only for entries the seed made (`recipe_id` of a seed
recipe, `env-...`) that still say "lunch". Dates, recipes, covers and every entry a person
made stay as they were. Orders, proposals, stock, forecasts and the demo delivery data are
not read or written. Safe to run again: a second run changes nothing. It refuses a kitchen
that is not synthetic.
"""

from __future__ import annotations

import argparse

from demo.seed import meal_of
from env.kitchens import RECIPES, TYPES

SEEDED = {f"env-{name}": name for name in RECIPES}


def fix(db, kitchen_id: str, *, apply: bool) -> dict:
    from store.repository import Repository
    kitchen = db.kitchens.find_one({"_id": kitchen_id}) or {}
    if kitchen.get("synthetic") is not True or kitchen.get("type") not in TYPES:
        raise ValueError(f"{kitchen_id} is not a synthetic demo kitchen; nothing changed")
    kind = TYPES[kitchen["type"]]
    repo = Repository(db)
    weeks = entries = 0
    for plan in repo.menu_plans.list(kitchen_id):
        days, changed = [], 0
        for day in plan["days"]:
            recipe = SEEDED.get(day.get("recipe_id"))
            meal = meal_of(recipe, kind) if recipe and day.get("meal") == "lunch" else day.get("meal")
            changed += meal != day.get("meal")
            days.append({**day, "meal": meal})
        if changed:
            weeks += 1
            entries += changed
            if apply:
                repo.menu_plans.put(kitchen_id, plan["week"], days)
    return {"weeks": weeks, "entries": entries, "applied": apply}


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--kitchen", default="demo-kitchen")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    from store.db import get_db
    out = fix(get_db(), args.kitchen, apply=args.apply)
    verb = "changed" if args.apply else "would change (dry run: add --apply to write)"
    print(f"{args.kitchen}: {out['entries']} menu entries in {out['weeks']} weeks {verb}")


if __name__ == "__main__":
    main()
