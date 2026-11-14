"""Golden scenarios S01-S13 (docs/scenarios.md) as one pass table.

    python -m gateway.scenarios            # table
    python -m gateway.scenarios --markdown # table for a README or a slide
    python -m gateway.scenarios --json

Each case runs at the most realistic layer that exists today: the HTTP gateway (test
database, recorded Valio answers), the engine, or the catalog flattener. Expected values
are the `decision` blocks of docs/scenarios.md. Statuses:

- PASS: numbers and reason codes match.
- PARTIAL: the numbers match, some reason codes are not emitted yet.
- FAIL: a number or a decision differs from docs/scenarios.md.
- NOT BUILT: the feature does not exist yet; the row names the issue.
- ERROR: the check itself crashed (a bug, never hidden).

No live calls, no secrets: safe for CI and for a demo laptop.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal as D
import json
import os
from pathlib import Path
import sys
from typing import Callable

from engine import Item, KitchenParams, Offer, allergen_codes, pack_info, plan_request, replenish, stockout_adjusted
from engine.quantity import cover_limit
from engine.urgency import Urgency

MON = date(2026, 11, 16)
P = KitchenParams()
FIX = Path(__file__).parent / "tests" / "fixtures"
NOW = datetime(2026, 11, 13, 20, 10, tzinfo=timezone.utc)   # Fri 22:10 Helsinki, as in the doc


@dataclass
class Result:
    id: str
    title: str
    layer: str
    status: str = "PASS"
    checks: list[str] = field(default_factory=list)    # what was checked and held
    problems: list[str] = field(default_factory=list)  # numbers or decisions that differ
    missing_codes: list[str] = field(default_factory=list)

    def expect(self, label: str, got, want) -> None:
        if got == want:
            self.checks.append(f"{label} = {want}")
        else:
            self.problems.append(f"{label}: got {got}, docs/scenarios.md says {want}")

    def codes(self, got, want) -> None:
        self.missing_codes = [c for c in want if c not in set(got)]

    def finish(self) -> "Result":
        if self.problems:
            self.status = "FAIL"
        elif self.missing_codes:
            self.status = "PARTIAL"
        return self


# ---- helpers ----------------------------------------------------------------------

def _row(pid, sales, base, units, lot=0.01):
    return {"id": pid, "salesUnit": sales, "baseUnit": base, "allowedLotSize": lot,
            "units": [{"unitId": u, "sizeInBaseUnits": s} for u, s in units]}


def _offer(pid, name, product, price, cmp, cmp_unit, available, cutoff_passed, measure=None, allergen_data_known=True):
    pack = pack_info(product, price=D(price), comparison_price=D(cmp) if cmp else None,
                     comparison_unit=cmp_unit, measure=measure)
    return Offer(pid, name, pack, D(price), None if available is None else D(available), cutoff_passed, MON,
                 allergen_data_known=allergen_data_known)


def _lines(plan):
    return [(ln.product_id, f"{ln.quantity.normalize():f}") for ln in plan.lines]


class _Gateway:
    """The real FastAPI app on a test database with the recorded Valio answers."""

    RAW = {
        "462775": _row("462775", "ST", "ST", [("KI", 12.0), ("ST", 1.0)]),
        "462921": _row("462921", "KI", "ST", [("KI", 5.0), ("ST", 1.0)]),
        "463335": _row("463335", "ST", "ST", [("KI", 5.0), ("ST", 1.0)]),
    }

    def __init__(self):
        import mongomock
        from fastapi.testclient import TestClient

        from gateway.app import create_app
        from gateway.service import Gateway
        from gateway.valio_client import ValioClient

        os.environ.setdefault("GATEWAY_HUMAN_TOKEN", "scenario-human-token")
        os.environ.setdefault("GATEWAY_AGENT_TOKEN", "scenario-agent-token")
        self.human = {"Authorization": f"Bearer {os.environ['GATEWAY_HUMAN_TOKEN']}", "X-User": "scenario"}
        self.agent = {"Authorization": f"Bearer {os.environ['GATEWAY_AGENT_TOKEN']}"}
        self.price = json.loads((FIX / "price.json").read_text())
        self.avail = json.loads((FIX / "availability.json").read_text())
        self.db = mongomock.MongoClient(tz_aware=True)["scenarios"]
        for pid, raw in self.RAW.items():
            self.db.products.insert_one({"_id": pid, "names": {"en": f"milk {pid}"}, "raw": raw})
        valio = ValioClient("scenario-not-a-real-key", transport=self._transport, ttl=0, now=lambda: NOW)
        self.client = TestClient(create_app(Gateway(self.db, valio, now=lambda: NOW)))
        self.k = "/v1/kitchens/demo-kitchen"

    def _transport(self, path, payload, headers):
        data = deepcopy(self.price if path == "/api/price" else self.avail)
        data["products"] = [p for p in data["products"] if p["productId"] in payload["products"]]
        return data

    def reprice(self, pid, value):
        for p in self.price["products"]:
            if p["productId"] == pid:
                p["catalogPrice"]["value"] = value
                p["comparisonPrice"]["value"] = value

    def milk(self, quantity, key):
        r = self.client.post(self.k + "/proposals", headers=self.agent, json={
            "product_ids": ["462775", "462921", "463335"], "quantity": quantity, "unit": "L",
            "requested_date": MON.isoformat(), "idempotency_key": key,
            "text": f"{quantity} L lactose-free milk by Monday"})
        r.raise_for_status()
        return r.json()

    def approve(self, proposal, key, total=None):
        return self.client.post(f"{self.k}/proposals/{proposal['proposal_id']}/approve", headers=self.human,
                                json={"expected_total": total or proposal["expected_total"], "idempotency_key": key})


# ---- the cases --------------------------------------------------------------------

def s01() -> Result:
    r = Result("S01", "Milk: split order, passed cut-off, unknown stock", "gateway HTTP")
    p = _Gateway().milk("1000", "s01")
    r.expect("lines", [(ln["product_id"], ln["quantity"]) for ln in p["lines"]],
             [("462775", "51"), ("463335", "949")])
    r.expect("total ex VAT (option B)", p["total_ex_vat"], "1459.67")
    r.expect("option A total", (p.get("alternative") or {}).get("total_ex_vat"), "1400.00")
    r.expect("cut-off passed excluded", "462921" in {e["product_id"] for e in p["excluded"]}, True)
    r.expect("verdict", p["mandate"]["verdict"], "NEEDS_APPROVAL")
    r.codes(p["mandate"]["reason_codes"], ["CLOSING_PASSED", "STOCK_UNKNOWN", "SUBSTITUTE_FAT_LEVEL"])
    return r.finish()


def s02() -> Result:
    r = Result("S02", "Partial stock, good-better-best", "engine")
    ph7 = _offer("465138", "PH7 gluten free oat bread", _row("465138", "KI", "KI", [("KI", 1)]),
                 "64.27", "7.65", "KG", "16", False, measure="KI", allergen_data_known=False)   # allergen_data: none
    plan = plan_request(D(20), "KI", [ph7], MON, P)
    r.expect("lines", _lines(plan), [("465138", "16")])
    r.expect("total", f"{plan.total:f}", "1028.32")
    r.expect("shortfall cases", f"{plan.shortfall.normalize():f}", "4")
    r.codes(plan.reason_codes, ["PARTIAL_STOCK", "SUBSTITUTE_NEEDS_OK", "ALLERGEN_DATA_MISSING"])
    r.checks.append("substitute 462300 x 84 by weight: not built (#281)")
    return r.finish()


def s03() -> Result:
    return Result("S03", "Allergen-safe substitute for a school", "-", "NOT BUILT",
                  problems=["kitchen allergen rules refusing a substitute: #16 mandate, #281 substitutes"])


def _minimal_record(pid, name, allergens):
    """Only the fields store.products.flatten reads for allergens (no challenge data copied)."""
    values = [{"id": code, "unit": "CONTAINS"} for code in allergens]
    return {"id": pid, "salesUnit": "ST", "baseUnit": "ST", "units": [{"unitId": "ST", "sizeInBaseUnits": 1.0}],
            "synkkaData": {"names": [{"language": "en", "value": name}],
                           "classifications": [{"name": "allergen", "values": values}] if values else []}}


def s04() -> Result:
    from store.products import flatten

    r = Result("S04", "Missing allergen data is not allergen-free", "catalog (store.products)")
    small = flatten(_minimal_record("463968", "Castelli Parmesan Reggiano 125 g PDO", []))
    big = flatten(_minimal_record("469648", "Castelli Parmigiano Reggiano 200 g", ["AM"]))
    r.expect("125 g allergen data known", small["allergen_data_known"], False)
    r.expect("125 g says no allergens", small["no_declarable_allergens"], False)
    r.expect("200 g lists milk", big["allergens"]["contains"], ["AM"])
    r.expect("200 g needs no flag", allergen_codes(big), ())
    r.codes(allergen_codes(small), ["ALLERGEN_DATA_MISSING"])
    r.checks.append("allergen card answer ('unknown, check the pack'): not built")
    return r.finish()


def s05() -> Result:
    r = Result("S05", "Above the budget warning (event order)", "engine")
    steak = _offer("461423", "Snellman hanger steak", _row("461423", "KG", "KG", [("KG", 1), ("KI", 1)], lot=10),
                   "19.93", "19.93", "KG", None, False)
    plan = plan_request(D(115), "KG", [steak], MON, P, event=True)
    r.expect("lines", _lines(plan), [("461423", "120")])
    r.expect("total", f"{plan.total:f}", "2391.60")
    r.codes([*plan.reason_codes, *plan.warnings],
            ["OVER_BUDGET_WARNING", "LOT_SIZE_ROUNDED", "STOCK_UNKNOWN", "EVENT_LINE"])
    return r.finish()


def s06() -> Result:
    return Result("S06", "Just under free delivery: pad with wanted lines", "-", "NOT BUILT",
                  problems=["MOV padding with lines the engine wants (MOV_PADDED): no issue yet"])


def s07() -> Result:
    r = Result("S07", "Price moved between quote and approval", "gateway HTTP")
    gw = _Gateway()
    p = gw.milk("51", "s07")
    gw.reprice("462775", 3.57)
    first = gw.approve(p, "s07-a1")
    r.expect("old yes is refused", (first.status_code, first.json()["error"]["code"]), (409, "TOTAL_MISMATCH"))
    r.expect("orders placed on the old yes", gw.db.orders.count_documents({}), 0)
    fresh = gw.client.get(f"{gw.k}/proposals/{p['proposal_id']}", headers=gw.human).json()
    again = gw.approve(fresh, "s07-a2")
    r.expect("new total, new yes, one order", (again.status_code, gw.db.orders.count_documents({})), (200, 1))
    r.codes(["TOTAL_MISMATCH"], ["TOTAL_MISMATCH"])
    r.checks.append("on the milk fixture (462775) instead of Oatly: same rule, recorded prices")
    return r.finish()


def s08() -> Result:
    r = Result("S08", "Standing-order drift", "engine")
    esl = pack_info(_row("469549", "ST", "ST", [("KI", 20), ("ST", 1)]), price=D("1.00"),
                    comparison_price=D("1.00"), comparison_unit="L", measure="L")
    line = replenish(Item("469549", esl, daily_demand=20, lead_time_days=0, review_days=7, on_hand=120,
                          safety_stock=20, category="fresh_dairy", standing_order=D(200)), P)
    r.expect("this week qty", f"{line.quantity.normalize():f}", "40")
    r.codes(line.reason_codes, ["STANDING_ORDER_DRIFT"])
    r.checks.append("proposing the standing order 200 -> 140: not built")
    return r.finish()


def s09() -> Result:
    r = Result("S09", "Stock count missing: unknown sorts with urgent", "engine")
    esl = pack_info(_row("469549", "ST", "ST", [("KI", 20), ("ST", 1)]), price=D("1.00"),
                    comparison_price=D("1.00"), comparison_unit="L", measure="L")
    line = replenish(Item("469549", esl, daily_demand=12, lead_time_days=1, review_days=2, on_hand=None,
                          safety_stock=12, category="fresh_dairy"), P)
    r.expect("draft qty (sized as if empty)", f"{line.quantity.normalize():f}", "48")
    r.expect("urgency top", line.urgency <= Urgency.BEFORE_NEXT_DELIVERY, True)
    r.codes(line.reason_codes, ["STOCK_COUNT_MISSING"])
    return r.finish()


def s10() -> Result:
    r = Result("S10", "Demand hidden by a stock-out", "engine")
    weekly, adjusted = stockout_adjusted(30, days_in_stock=3, days_total=7, cap=P.stockout_cap)
    r.expect("adjusted forecast L/week", round(weekly, 2), 54.0)
    oat = pack_info(_row("470863", "ST", "ST", [("KI", 6), ("ST", 1)]), price=D("1.40"),
                    comparison_price=D("1.40"), comparison_unit="L", measure="L")
    line = replenish(Item("470863", oat, daily_demand=weekly / 7, lead_time_days=0, review_days=7, on_hand=0,
                          safety_stock=0, category="dry",
                          demand_codes=("STOCKOUT_ADJUSTED",) if adjusted else ()), P)
    r.expect("qty", f"{line.quantity.normalize():f}", "54")
    r.expect("total", f"{(line.quantity * D('1.40')).quantize(D('0.01')):f}", "75.60")
    r.codes(line.reason_codes, ["STOCKOUT_ADJUSTED"])
    return r.finish()


def s11() -> Result:
    r = Result("S11", "Inbound is not an emergency; the cover ceiling", "engine")
    parm = pack_info(_row("469648", "ST", "ST", [("ST", 1)]), measure="ST")
    item = Item("469648", parm, daily_demand=4, lead_time_days=3, review_days=1, on_hand=10, on_order=30,
                safety_stock=6, category="dry")
    line = replenish(item, P)
    r.expect("order now", f"{line.quantity.normalize():f}", "0")
    check = cover_limit(item, KitchenParams.from_dict({"max_cover_days": {"dry": 14}}), extra=150)
    r.expect("max within ceiling", round(check["max_extra"]), 34)   # 4 x (3 + 14) + 6 - 40 (Aron, 2026-11-14)
    r.expect("days of cover for 150", int(check["days_of_cover"]), 47)
    r.codes([*line.reason_codes, *check["reason_codes"]], ["POSITION_OK", "COVER_CEILING"])
    return r.finish()


def s12() -> Result:
    r = Result("S12", "Bad pack data (10 kg carrot sack)", "engine")
    carrot = _offer("460708", "Carrot 10 kg sack", _row("460708", "ST", "ST", [("PAL", 60), ("KI", 1), ("ST", 1)]),
                    "11.18", "1.12", "KG", "20", False)
    plan = plan_request(D(50), "KG", [carrot], MON, P)
    r.expect("lines", _lines(plan), [("460708", "5")])
    r.expect("total", f"{plan.total:f}", "55.90")
    r.codes(plan.reason_codes, ["PACK_SIZE_DERIVED"])
    return r.finish()


def s13() -> Result:
    r = Result("S13", "Duplicate send (idempotency)", "gateway HTTP")
    gw = _Gateway()
    p = gw.milk("51", "s13")
    first, replay = gw.approve(p, "s13-key"), gw.approve(p, "s13-key")
    same = first.status_code == 200 and replay.json().get("order_id") == first.json().get("order_id")
    r.expect("replay with the same key returns the stored order", same, True)
    r.expect("orders stored", gw.db.orders.count_documents({}), 1)
    r.checks.append("timeout after send -> UNCONFIRMED, never auto-retried: agent and MCP adapter tests")
    return r.finish()


CASES: list[Callable[[], Result]] = [s01, s02, s03, s04, s05, s06, s07, s08, s09, s10, s11, s12, s13]


def run() -> list[Result]:
    results = []
    for case in CASES:
        try:
            results.append(case())
        except Exception as exc:  # a crash is a result, never hidden
            name = case.__name__.upper()
            results.append(Result(name, "check crashed", "-", "ERROR", problems=[f"{type(exc).__name__}: {exc}"]))
    return results


def _detail(r: Result) -> str:
    parts = list(r.problems)
    if r.missing_codes:
        parts.append("codes not emitted yet: " + ", ".join(r.missing_codes))
    return "; ".join(parts) or "; ".join(r.checks[:2])


def table(results: list[Result], markdown: bool = False) -> str:
    counts = {s: sum(r.status == s for r in results) for s in ("PASS", "PARTIAL", "FAIL", "NOT BUILT", "ERROR")}
    summary = ", ".join(f"{n} {s}" for s, n in counts.items() if n)
    if markdown:
        rows = ["| Case | What | Layer | Result | Detail |", "|---|---|---|---|---|"]
        rows += [f"| {r.id} | {r.title} | {r.layer} | **{r.status}** | {_detail(r)} |" for r in results]
        return "\n".join([*rows, "", summary])
    width = max(len(r.title) for r in results)
    rows = [f"{r.id}  {r.status:<9}  {r.title:<{width}}  {_detail(r)}" for r in results]
    return "\n".join([*rows, "", summary])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--markdown", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    results = run()
    if args.json:
        print(json.dumps([asdict(r) for r in results], indent=2))
    else:
        print(table(results, markdown=args.markdown))
    return 1 if any(r.status == "ERROR" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
