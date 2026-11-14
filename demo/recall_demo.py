"""The open proposal the recall demo needs: the recalled coffee on the demo kitchen (#358).

    python -m demo.recall_demo             # on the server: docker compose ... exec gateway python -m demo.recall_demo
    python -m demo.recall_demo --key again # a second proposal (the default key replays the first)

It asks the gateway for 5 kg of 461332 (Kulta Katriina filter coffee) for the first day from
next Monday whose order cut-off has not passed (`--date` to pick one), as a
person would on the Requests page: a live Valio quote, a READY proposal, a pending
approval. It orders nothing. Then "Check recalls now" in the inbox has a line to block.

It says so when the proposal does not hold the coffee, with the gateway's reason. The usual
one is BLOCKED_BY_RECALL: an earlier check already recorded the recall, so new quotes leave
the coffee out. The banner then needs the proposal that check held, not a new one.
"""

from __future__ import annotations

import argparse
from datetime import date, timedelta

DEMO_ID = "demo-kitchen"
COFFEE = "461332"


def next_monday(today: date) -> date:
    return today + timedelta(days=7 - today.weekday())


def open_day(gateway, today: date, days: int = 10) -> date:
    """The first delivery day from next Monday on whose Valio order cut-off has not passed.
    Read-only (one availability call per day tried), so a passed cut-off never leaves a
    REJECTED proposal behind (2026-11-14: Monday's cut-off had passed on Saturday)."""
    start = next_monday(today)
    for offset in range(days):
        day = start + timedelta(days=offset)
        try:
            rows = gateway.valio.availability([COFFEE], day.isoformat())["products"]
        except Exception:
            return start                    # no live answer: keep the old rule, the quote says why
        row = next((r for r in rows if r.get("productId") == COFFEE), {})
        if row.get("cutoff_passed") is not True and row.get("scheduleLines"):
            return day
    return start


def seed(gateway, *, today: date, key: str | None = None, kitchen_id: str = DEMO_ID,
         day: date | None = None) -> dict:
    """Create (or replay) the coffee proposal through the gateway; return what to print."""
    day = day or open_day(gateway, today)
    proposal = gateway.create_proposal(kitchen_id, {
        "product_ids": [COFFEE], "quantity": "5", "unit": "KG", "requested_date": day.isoformat(),
        "text": "5 kg Kulta Katriina filter coffee for the breakfast buffet",
        "idempotency_key": key or f"recall-demo-{day.isoformat()}"}, "demo-seed")
    lines = [line["product_id"] for line in proposal["lines"]]
    return {"proposal_id": proposal["proposal_id"], "status": proposal["status"], "lines": lines,
            "has_coffee": COFFEE in lines,
            "excluded": [row for row in proposal.get("excluded") or [] if row["product_id"] == COFFEE]}


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--key", help="idempotency key; a new key makes a new proposal")
    p.add_argument("--today", type=date.fromisoformat, default=date.today())
    p.add_argument("--date", type=date.fromisoformat, default=None,
                   help="delivery day (default: the first day from next Monday whose cut-off has not passed)")
    a = p.parse_args(argv)
    from gateway.service import Gateway
    from gateway.valio_client import ValioClient
    from store.db import get_db
    out = seed(Gateway(get_db(), ValioClient()), today=a.today, key=a.key, day=a.date)
    print(out)
    if not out["has_coffee"]:
        raise SystemExit(f"The proposal does not hold {COFFEE}: {out['excluded'] or out['status']}. "
                         "The recall check will have nothing new to block.")


if __name__ == "__main__":
    main()
