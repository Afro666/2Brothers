"""Read-only recall dry run: which products of a kitchen the recorded notices match (#1076).

    python -m demo.recall_dry_run                       # demo-kitchen, the recorded notices
    python -m demo.recall_dry_run --kitchen hotel --expect 461332
    on the server: docker compose ... run --rm -T --no-deps gateway python -m demo.recall_dry_run

It builds the kitchen exactly as "Check recalls now" does (`store.recalls.context`: open
proposals, counted stock, recipes) and runs `monitor.recalls.scan` on the recording the
check reads (`monitor/fixtures/ruokavirasto.json`). It prints every alert with its match
level, why and where. It never calls `remember`, never holds a proposal, never writes an
audit entry and never scrapes: the live check is one-shot (`$setOnInsert`), so a false
alert must be found here first.

Exit code 0 when the products with an `exact` or `possible` alert are exactly `--expect`
(default 461332, the recalled coffee), else 1. A `review` alert never blocks a proposal; it
is listed, and with `--strict` it counts as unexpected too.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from monitor.recalls import scan
from store import recalls

RECORDING = Path(__file__).resolve().parent.parent / "monitor" / "fixtures" / "ruokavirasto.json"
DEMO_ID = "demo-kitchen"
COFFEE = "461332"
BLOCKING = ("exact", "possible")      # store/recalls.py blocked_ids


def dry_run(db, kitchen_id: str, notices: list, now: datetime) -> tuple[dict, list]:
    """`(kitchen, alerts)`: the check's context and its alerts; reads only."""
    kitchen, _ = recalls.context(db, kitchen_id)
    return kitchen, scan(notices, kitchen, now)


def verdict(alerts: list, expect: set, strict: bool = False) -> dict:
    """Which alerting products were expected, unexpected or missing."""
    levels = BLOCKING + (("review",) if strict else ())
    found = {a["product_id"] for a in alerts if a["match"] in levels}
    return {"expected": sorted(found & expect), "unexpected": sorted(found - expect),
            "missing": sorted(expect - found), "ok": found == expect}


def report(kitchen: dict, alerts: list, result: dict, notices: int) -> list[str]:
    out = [f"{kitchen['kitchen_id']}: {len(kitchen['products'])} products scanned "
           f"({len(kitchen['stock'])} in stock, {len(kitchen['recipes'])} in recipes, "
           f"{len(kitchen['proposal'])} on open proposals); {notices} notices; {len(alerts)} alert(s)"]
    for a in sorted(alerts, key=lambda a: (a["match"], a["product_id"])):
        out.append(f"- [{a['match']}] {a['product_id']} {a['product_name']} <- "
                   f"{a['recall']['recalled_product']} ({a['recall']['date']})")
        out.append(f"    why: {a['why']}")
        out.append(f"    where: {'; '.join(a['where']) or 'nowhere'}")
    out.append(f"expected: {', '.join(result['expected']) or 'none'}; "
               f"unexpected: {', '.join(result['unexpected']) or 'none'}; "
               f"missing: {', '.join(result['missing']) or 'none'}")
    out.append("OK: only the expected products would alert" if result["ok"]
               else "NOT OK: the live check would alert differently")
    return out


def main(argv=None, db=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--kitchen", default=DEMO_ID)
    p.add_argument("--fixture", type=Path, default=RECORDING, help="recorded notices (the check's own)")
    p.add_argument("--expect", default=COFFEE, help="comma-separated product codes that should alert")
    p.add_argument("--now", type=datetime.fromisoformat, default=None, help="scan time (default: now)")
    p.add_argument("--strict", action="store_true", help="count review alerts as unexpected too")
    a = p.parse_args(argv)
    now = a.now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    notices = json.loads(a.fixture.read_text(encoding="utf-8"))["notices"]
    if db is None:
        from store.db import get_db
        db = get_db()
    kitchen, alerts = dry_run(db, a.kitchen, notices, now)
    result = verdict(alerts, {c.strip() for c in a.expect.split(",") if c.strip()}, a.strict)
    print("\n".join(report(kitchen, alerts, result, len(notices))))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
