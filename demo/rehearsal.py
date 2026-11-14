"""Rehearsal check: is the live demo ready? One command, one table.

    python -m demo.rehearsal                                   # the public demo site, read-only
    python -m demo.rehearsal --site https://<host> --buyer     # also one real Buyer request

It goes through the public site the way a visitor's browser does (`<site>/api/...`, where the
server adds the demo person's session), so it needs no token and never prints one. Read-only
unless `--buyer` is given: then it asks the Buyer for 200 L of lactose-free milk once (one
Nemotron run, one proposal in the inbox; clear it with `python -m demo.clear_inbox`).
Exit code 1 when a check fails.
"""

from __future__ import annotations

import argparse
from datetime import date, timedelta
import sys
import time

import httpx

SITE = "https://31-22-104-201.sslip.io"
K = "/api/v1/kitchens/demo-kitchen"


def _monday(today: date) -> date:
    return today + timedelta(days=(7 - today.weekday()) % 7 or 7)


class Rehearsal:
    def __init__(self, site: str, client: httpx.Client | None = None, today: date | None = None):
        self.http = client or httpx.Client(base_url=site.rstrip("/"), timeout=60, follow_redirects=True)
        self.today = today or date.today()
        self.retry_wait = 15.0
        # One key per run, so a retried Buyer POST is the same request, never a second proposal.
        self.idempotency_key = f"rehearsal-{int(time.time())}"
        self.rows: list[tuple[str, str, str]] = []

    def get(self, path: str):
        t = time.monotonic()
        r = self.http.get(path)
        try:
            data = r.json()
        except ValueError:
            data = None
        return r.status_code, data, time.monotonic() - t

    def check(self, name: str, fn, retry_on: type[Exception] = httpx.TransportError) -> None:
        status, detail = "FAIL", ""
        for attempt in (1, 2):
            try:
                ok, detail = fn()
                status = "SKIP" if ok is None else ("OK" if ok else "FAIL")
                break
            except retry_on as exc:
                # A deploy restarts the containers for a few seconds: wait once, then it is a real failure.
                status, detail = "FAIL", f"no connection ({type(exc).__name__}); a deploy may be running"
                if attempt == 1:
                    time.sleep(self.retry_wait)
            except Exception as exc:
                status, detail = "FAIL", f"{type(exc).__name__}: {str(exc)[:80]}"
                break
        self.rows.append((name, status, detail))

    # ---- checks -------------------------------------------------------------------------

    def site(self):
        r = self.http.get("/")
        return r.status_code == 200 and "<html" in r.text.lower(), f"HTTP {r.status_code}"

    def gateway(self):
        code, data, secs = self.get("/api/ping")
        return code == 200 and (data or {}).get("status") == "ok", f"HTTP {code} in {secs:.1f} s"

    def inbox(self):
        code, data, _ = self.get(K + "/proposals")
        rows = (data or {}).get("proposals", [])
        waiting = [p for p in rows if p.get("status") in ("READY", "PENDING")]
        approvable = [p for p in waiting if p.get("lines") and all(ln.get("unknown_stock") is False for ln in p["lines"])]
        note = f"{len(waiting)} waiting, {len(approvable)} can be approved now"
        if len(waiting) > 6:
            note += " (many test proposals: run python -m demo.clear_inbox)"
        return code == 200, note

    def planner(self):
        monday = _monday(self.today)
        y, w, _ = monday.isocalendar()
        code, data, _ = self.get(f"{K}/menu-plans/{y}-W{w:02d}")
        days = (data or {}).get("days", [])
        return code == 200 and len(days) > 0, f"week {w}: {len(days)} menu entries"

    def demand(self):
        monday = _monday(self.today)
        code, data, _ = self.get(f"{K}/demand?from={monday}&to={monday + timedelta(days=6)}")
        rows = (data or {}).get("rows", [])
        named = sum(1 for r in rows if r.get("product_name"))
        return code == 200 and len(rows) > 0, f"{len(rows)} need rows, {named} with a product name"

    def stock(self):
        code, data, _ = self.get(K + "/stock")
        items = (data or {}).get("items", [])
        unknown = sum(1 for i in items if i.get("on_hand") is None)
        return code == 200 and len(items) > 0, f"{len(items)} products, {unknown} not counted"

    def suppliers(self):
        code, data, _ = self.get(K + "/suppliers")
        names = [s.get("name") for s in (data or {}).get("suppliers", [])]
        return code == 200 and len(names) >= 1, ", ".join(map(str, names)) or "no suppliers"

    def forecast_proof(self):
        end = self.today - timedelta(days=1)
        code, data, _ = self.get(f"{K}/forecast-accuracy?from={end - timedelta(days=69)}&to={end}")
        methods = (data or {}).get("methods", {})
        ours = (methods.get("engine") or {}).get("total", {}).get("wape")
        base = (methods.get("weekday-average") or {}).get("total", {}).get("wape")
        if code != 200:
            return False, f"HTTP {code}"
        missing = [name for name, v in (("engine", ours), ("weekday average", base)) if v is None]
        if missing:
            return False, f"HTTP {code}, no WAPE for {' and '.join(missing)}"
        ok = ours < base
        return ok, f"engine {ours:.1%} vs weekday average {base:.1%}" + ("" if ok else " (not better)")

    def valio_view(self):
        monday = _monday(self.today)
        code, data, _ = self.get(f"/api/v1/suppliers/sup-valio/demand?from={monday}&to={monday}")
        rows = (data or {}).get("rows", [])
        short = sum(1 for r in rows if r.get("risk") == "SHORT")
        return code == 200 and len(rows) > 0, f"{(data or {}).get('kitchens_sharing')} kitchens share, {len(rows)} rows, {short} short"

    def permissions(self):
        code, data, _ = self.get(K + "/permissions")
        return code == 200 and len((data or {}).get("never", [])) >= 3, f"{len((data or {}).get('never', []))} never-rows"

    def audit(self):
        code, data, _ = self.get(K + "/audit")
        events = (data or {}).get("events", [])
        untimed = sum(1 for e in events if not e.get("at"))
        return code == 200 and len(events) > 0 and untimed == 0, f"{len(events)} steps, {untimed} without a time"

    def signing(self):
        code, data, _ = self.get("/api/.well-known/jwks.json")
        keys = (data or {}).get("keys", [])
        return code == 200 and bool(keys) and keys[0].get("alg") == "EdDSA", f"HTTP {code}, {len(keys)} key(s)"

    def docs(self):
        code, data, _ = self.get("/api/openapi.json")
        return code == 200 and len((data or {}).get("paths", {})) > 20, f"{len((data or {}).get('paths', {}))} documented paths"

    def buyer(self):
        monday = _monday(self.today)
        t = time.monotonic()
        r = self.http.post(K + "/proposals", json={"text": f"200 L lactose-free milk by {monday}",
                                                   "requested_date": monday.isoformat(),
                                                   "idempotency_key": self.idempotency_key}, timeout=180)
        secs = time.monotonic() - t
        data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        who = "Nemotron Buyer" if data.get("buyer_model") else f"fallback: {(data.get('request') or {}).get('made_by')}"
        ok = r.status_code == 200 and data.get("status") == "READY" and bool(data.get("buyer_model"))
        return ok, f"HTTP {r.status_code} in {secs:.0f} s, {who}, {len(data.get('lines', []))} line(s), {data.get('status')}"

    def run(self, with_buyer: bool) -> list[tuple[str, str, str]]:
        for name, fn in (("Site loads", self.site), ("Gateway answers", self.gateway),
                         ("Approval inbox", self.inbox), ("Menu plan for next week", self.planner),
                         ("Demand from the menu plan", self.demand), ("Stock counts", self.stock),
                         ("Suppliers", self.suppliers), ("Forecast beats the weekday average", self.forecast_proof),
                         ("Valio demand view", self.valio_view), ("Permissions table", self.permissions),
                         ("Activity log", self.audit), ("Offer signing key", self.signing),
                         ("API docs", self.docs)):
            self.check(name, fn)
        if with_buyer:
            # Only a refused connection is retried: after a timeout the server may still be making
            # the proposal, and sending it again would start a second Nemotron run.
            self.check("Buyer makes a proposal", self.buyer, retry_on=httpx.ConnectError)
        else:
            self.rows.append(("Buyer makes a proposal", "SKIP", "add --buyer to run one real request"))
        return self.rows


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--site", default=SITE)
    parser.add_argument("--buyer", action="store_true", help="also make one real Buyer request")
    args = parser.parse_args(argv)
    rows = Rehearsal(args.site).run(args.buyer)
    width = max(len(name) for name, _, _ in rows)
    for name, status, detail in rows:
        print(f"{name:<{width}}  {status:<4}  {detail}")
    failed = sum(1 for _, status, _ in rows if status == "FAIL")
    print(f"\n{sum(1 for _, s, _ in rows if s == 'OK')} ok, {failed} failed, {sum(1 for _, s, _ in rows if s == 'SKIP')} skipped")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
