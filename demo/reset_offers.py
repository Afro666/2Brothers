"""Start a new round of supplier offers for one kitchen, before a demo (#374).

    python -m demo.reset_offers                       # dry run: the offers of the current round
    python -m demo.reset_offers --apply               # start a new round
    python -m demo.reset_offers --kitchen demo-kitchen --apply

An accepted or declined offer is final: in one round the same supplier, product and day are
offered once. A rehearsal or a recording uses the open offer up, and then the selling agent
has nothing new to offer (ALREADY_OFFERED). This command starts a new round for the kitchen:
from then on the seller may offer the same product and day again, as a new offer with a new
offer_id, so its accept makes a new proposal. Nothing is deleted: offers of earlier rounds,
their proposals, orders and audit lines stay as they were. One audit entry,
`demo_offers_reset`, records the old and the new round. Then run the seller:
`python -m agent.seller --apply --limit 1 --kitchen demo-kitchen --days 14`.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from uuid import uuid4

from store import supplier_offers as offers


def reset(db, kitchen_id: str, *, apply: bool, actor: str = "demo.reset_offers") -> dict:
    current = offers.round_of(db, kitchen_id)
    rows = offers.list_round(db, kitchen_id, current)
    listing = [{"offer_id": row["_id"], "status": row.get("status"), "product": row.get("product_name"),
                "requested_date": row.get("requested_date")} for row in rows]
    if not apply:
        return {"round": current, "new_round": None, "offers": listing}
    new = offers.next_round(db, kitchen_id)
    from store import audit
    audit.append_event(db, {"event_id": uuid4().hex, "kind": "demo_offers_reset", "actor": actor,
                            "old_round": current, "new_round": new, "offers_in_old_round": len(rows)},
                       {"kitchen_id": kitchen_id, "at": datetime.now(timezone.utc).isoformat()})
    return {"round": current, "new_round": new, "offers": listing}


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--kitchen", default="demo-kitchen")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    from store.db import get_db
    out = reset(get_db(), args.kitchen, apply=args.apply)
    for row in out["offers"]:
        print(row["status"], row["requested_date"], row["product"], row["offer_id"])
    if args.apply:
        print(f"round {out['round']} -> {out['new_round']}: the seller may offer again")
    else:
        print(f"round {out['round']}: {len(out['offers'])} offer(s) (dry run: add --apply to start a new round)")


if __name__ == "__main__":
    main()
