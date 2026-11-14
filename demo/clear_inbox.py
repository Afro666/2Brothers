"""Clear test proposals from a kitchen's approval inbox before a demo.

    python -m demo.clear_inbox                         # dry run: lists what would go
    python -m demo.clear_inbox --apply                 # removes them
    python -m demo.clear_inbox --before 2026-11-14T06:00:00+00:00 --kitchen demo-kitchen --apply

Only proposals that are still waiting (READY, PENDING, BLOCKED_BY_RECALL) and were created
before `--before` (default: now) are removed, with their pending approvals. Approved and
rejected proposals, orders and the audit log are never touched. This is not a reject: a
reject is a person's decision and would count in the auto-approve learning numbers. One
audit entry (`demo_inbox_cleared`) records how many were removed and by which command.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from uuid import uuid4

WAITING = ("READY", "PENDING", "BLOCKED_BY_RECALL")


def find(db, kitchen_id: str, before: datetime) -> list[dict]:
    rows = db.proposals.find({"kitchen_id": kitchen_id, "status": {"$in": list(WAITING)},
                              "order_id": None}).sort("created_at", 1)
    out = []
    for row in rows:
        created = row.get("created_at")
        if created is not None and created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        if created is None or created < before:
            out.append(row)
    return out


def clear(db, kitchen_id: str, before: datetime, *, apply: bool, actor: str = "demo.clear_inbox") -> dict:
    rows = find(db, kitchen_id, before)
    listing = [{"proposal_id": r["_id"], "created_at": r.get("created_at"), "created_by": r.get("created_by"),
                "text": (r.get("request") or {}).get("text", "")[:60], "status": r["status"]} for r in rows]
    if not apply or not rows:
        return {"found": len(rows), "removed": 0, "proposals": listing}
    ids = [r["_id"] for r in rows]
    approvals = [r["approval_id"] for r in rows if r.get("approval_id")]
    gone = db.approvals.delete_many({"_id": {"$in": approvals}, "kitchen_id": kitchen_id, "status": "PENDING"}).deleted_count
    removed = db.proposals.delete_many({"_id": {"$in": ids}, "kitchen_id": kitchen_id,
                                        "status": {"$in": list(WAITING)}, "order_id": None}).deleted_count
    from store import audit
    audit.append_event(db, {"event_id": uuid4().hex, "kind": "demo_inbox_cleared", "actor": actor,
                            "proposals_removed": removed, "approvals_removed": gone,
                            "before": before.isoformat()},
                       {"kitchen_id": kitchen_id, "at": datetime.now(timezone.utc).isoformat()})
    return {"found": len(rows), "removed": removed, "approvals_removed": gone, "proposals": listing}


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--kitchen", default="demo-kitchen")
    parser.add_argument("--before", type=datetime.fromisoformat, default=None, help="ISO time with offset; default now")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    before = args.before or datetime.now(timezone.utc)
    if before.tzinfo is None:
        parser.error("--before needs a timezone offset, for example 2026-11-14T06:00:00+00:00")
    from store.db import get_db
    result = clear(get_db(), args.kitchen, before, apply=args.apply)
    for row in result["proposals"]:
        print(row["created_at"], row["status"], row["created_by"], "|", row["text"])
    print(f"{result['found']} waiting proposal(s) found, {result['removed']} removed"
          + ("" if args.apply else " (dry run: add --apply to remove them)"))


if __name__ == "__main__":
    main()
