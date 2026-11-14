"""Sample learning history for the demo kitchen (#1305): a learned line on stage.

    python -m demo.learning_seed --dry-run      # pick the product, print what it would write
    python -m demo.learning_seed                # write the sample rows (once; a repeat writes nothing)
    python -m demo.learning_seed --product 461903

The tool learns from the reasons people give when they change a plan proposal
(docs/contract.md, "Learning from kitchen changes and deliveries"). A fresh demo kitchen
has no such history, so "Propose order for this week" shows no learned line. This writes
**sample data**, clearly marked: four approved plan proposals where a person cut one
product to about half of the engine's forecast with the reason "too much". That is what
the correction-ratio rule needs (at least 3 approved rows in 8 weeks), so the next plan
proposal for that product carries a `learned` line with its evidence and an undo.

Every row is labelled: user `sample-data (demo seed)`, proposal ids `sample-learning-*`,
feedback ids `sample-learning-*`. Only the store writes (store/feedback.py); no proposal,
order or stock is created. Switching the learned fact off (PUT /learned/{id}) is the undo.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

DEMO_ID = "demo-kitchen"
USER = "sample-data (demo seed)"
PREFIX = "sample-learning"
RATIO = Decimal("0.5")        # the person keeps cutting this product to about half
ROWS = 4                      # more than the rule's minimum of 3


def pick_product(db, kitchen_id: str, today: date) -> dict | None:
    """The product with the largest need in next week's plan: the one the weekly
    proposal will show. None when the plan needs nothing."""
    from gateway.kitchen_routes import demand_rows
    start = today + timedelta(days=(7 - today.weekday()) % 7 or 7)       # next Monday
    rows, _ = demand_rows(db, kitchen_id, start, start + timedelta(days=6), today, timezone.utc)
    totals: dict[tuple[str, str], Decimal] = {}
    for row in rows:
        need = row.get("net_need")
        need = row.get("gross_need") if need is None else need
        if need is None or Decimal(str(need)) <= 0:
            continue
        key = (row["product_id"], row["unit"])
        totals[key] = totals.get(key, Decimal(0)) + Decimal(str(need))
    if not totals:
        return None
    (product_id, unit), need = max(totals.items(), key=lambda kv: kv[1])
    return {"product_id": product_id, "unit": unit, "need": need}


def sample_rows(product: dict, today: date) -> list[tuple[str, list[dict]]]:
    """(proposal_id, rows) pairs: per sample proposal, one 'too much' cut and its approval."""
    base = product["need"].quantize(Decimal("1")) if product["need"] >= 1 else product["need"]
    base = base if base > 0 else Decimal(1)
    out = []
    for i in range(1, ROWS + 1):
        proposal_id = f"{PREFIX}-{i}"
        requested = (today - timedelta(weeks=ROWS - i + 1)).isoformat()
        cut = (base * RATIO).normalize()
        change = {"kind": "qty_changed", "product_id": product["product_id"], "unit": product["unit"],
                  "from_qty": f"{base.normalize():f}", "to_qty": f"{cut:f}", "reason": "TOO_MUCH",
                  "feedback_id": f"{proposal_id}-change",
                  "context": {"forecast_need": f"{base.normalize():f}", "stock_position": None, "covers": None,
                              "requested_date": requested, "made_by": "menu_plan", "offer_id": None}}
        approved = {"kind": "approved", "feedback_id": f"{proposal_id}-approved"}
        out.append((proposal_id, [change, approved]))
    return out


def already_seeded(db, kitchen_id: str) -> bool:
    return db.feedback.count_documents({"meta.kitchen_id": kitchen_id, "user": USER}, limit=1) > 0


def seed(db, kitchen_id: str = DEMO_ID, today: date | None = None, product_id: str | None = None,
         dry_run: bool = False) -> dict:
    """Write the sample rows once. Returns what it did (or would do)."""
    from store.feedback import record_feedback
    today = today or datetime.now(timezone.utc).date()
    if already_seeded(db, kitchen_id):
        return {"kitchen_id": kitchen_id, "written": 0, "note": "sample learning history already present"}
    product = ({"product_id": product_id, "unit": "ST", "need": Decimal(10)} if product_id
               else pick_product(db, kitchen_id, today))
    if product is None:
        return {"kitchen_id": kitchen_id, "written": 0, "note": "next week's plan needs nothing; pass --product"}
    plan = sample_rows(product, today)
    if dry_run:
        return {"kitchen_id": kitchen_id, "written": 0, "would_write": sum(len(r) for _, r in plan),
                "product_id": product["product_id"], "unit": product["unit"],
                "from_qty": plan[0][1][0]["from_qty"], "to_qty": plan[0][1][0]["to_qty"]}
    # One sample proposal a week, the newest a week ago: real-looking evidence dates, all
    # inside the rule's 8-week window and never after "today".
    written = 0
    for i, (proposal_id, rows) in enumerate(plan):
        at = datetime.combine(today - timedelta(weeks=ROWS - i), datetime.min.time(), timezone.utc).replace(hour=10)
        written += record_feedback(db, kitchen_id, proposal_id, rows, USER, at=at)
    return {"kitchen_id": kitchen_id, "written": written, "product_id": product["product_id"],
            "unit": product["unit"], "from_qty": plan[0][1][0]["from_qty"], "to_qty": plan[0][1][0]["to_qty"]}


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--kitchen", default=DEMO_ID)
    p.add_argument("--product", help="the product to learn for (default: the largest need next week)")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args(argv)
    from store.db import get_db
    print(seed(get_db(), a.kitchen, product_id=a.product, dry_run=a.dry_run))


if __name__ == "__main__":
    main()
