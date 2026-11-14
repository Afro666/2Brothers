"""Future demand from the menu plan (#74). Pure, no I/O.

Need per product and day = covers on the menu x recipe quantity per portion / yield.
Yield matters: 100 g of peeled carrot on the plate at 85% yield is 118 g bought.
Net need takes the kitchen's stock off day by day; unknown stock gives an unknown net need
(None), never a guess.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal


def gross_needs(menu_days: list[dict], recipes: dict[str, dict]) -> tuple[list[dict], list[str]]:
    """`menu_days`: {date, recipe_id, covers}; `recipes`: recipe_id -> {name, ingredients}.

    Returns (rows, problems). One row per product and day: product_id, date, unit, covers
    (guests eating a dish with it), gross_need, why. A menu entry without covers or with an
    unknown recipe is a problem that is reported, not a zero.
    """
    need: dict[tuple[str, str, str], Decimal] = defaultdict(Decimal)
    covers: dict[tuple[str, str, str], int] = defaultdict(int)
    parts: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    problems: list[str] = []
    for entry in menu_days:
        recipe = recipes.get(str(entry.get("recipe_id")))
        if recipe is None:
            problems.append(f"{entry.get('date')}: recipe {entry.get('recipe_id')} does not exist")
            continue
        guests = entry.get("covers")
        if guests is None:
            problems.append(f"{entry.get('date')}: no covers for {recipe.get('name', entry['recipe_id'])}")
            continue
        for item in recipe.get("ingredients") or []:
            qty = Decimal(str(item["qty_per_portion"]))
            usable = Decimal(str(item["yield_pct"])) if item.get("yield_pct") is not None else Decimal(100)
            bought = qty * 100 / usable
            key = (str(item["product_id"]), str(entry["date"]), item["unit"])
            need[key] += bought * guests
            covers[key] += int(guests)
            note = f"{guests} x {qty.normalize():f} {item['unit']} ({recipe.get('name', entry['recipe_id'])}"
            note += f", {usable.normalize():f}% yield)" if usable != 100 else ")"
            parts[key].append(note)
    rows = [{"product_id": pid, "date": day, "unit": unit, "covers": covers[(pid, day, unit)],
             "gross_need": total.quantize(Decimal("0.001")), "why": " + ".join(parts[(pid, day, unit)])}
            for (pid, day, unit), total in sorted(need.items(), key=lambda kv: (kv[0][1], kv[0][0]))]
    return rows, problems


def net_needs(rows: list[dict], stock: dict[str, Decimal | None]) -> list[dict]:
    """Add `net_need` to each row: what is still missing after the stock (on hand plus on
    order) is used up day by day. `stock[product_id]` None, or a product not in `stock`,
    means unknown: then net_need is None."""
    left = dict(stock)
    out = []
    for row in sorted(rows, key=lambda r: (r["date"], r["product_id"])):
        pid = row["product_id"]
        have = left.get(pid)
        if have is None:
            out.append({**row, "net_need": None})
            continue
        used = min(have, row["gross_need"])
        left[pid] = have - used
        out.append({**row, "net_need": row["gross_need"] - used})
    return out


def weeks_between(start: date, end: date) -> list[str]:
    """ISO weeks (`YYYY-Www`) touched by the range, in order."""
    seen, out, day = set(), [], start
    while day <= end:
        y, w, _ = day.isocalendar()
        key = f"{y}-W{w:02d}"
        if key not in seen:
            seen.add(key)
            out.append(key)
        day = date.fromordinal(day.toordinal() + 1)
    return out
