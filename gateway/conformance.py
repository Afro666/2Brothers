"""Live conformance kit (#286): check a running gateway's trust rules with one command.

    python -m gateway.conformance --base-url https://<host>/gateway --token <agent or kitchen token>
    python -m gateway.conformance --base-url ... --token ... --markdown   # or --json

For any agent builder: it uses only an agent-level token (read + propose) and proves, on the
live system, what such a token can and cannot do. It places no order and opens no approval:
it creates one stored need and one offer snapshot (both harmless, both in the audit trail).
The offline golden scenarios S01-S13 are `python -m gateway.scenarios`.

The token is read from --token or the TKB_TOKEN environment variable and is never printed.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import date, timedelta
import json
import os
import sys

import httpx


@dataclass
class Check:
    id: str
    rule: str
    status: str      # PASS, FAIL, SKIP
    detail: str = ""


class Kit:
    def __init__(self, base_url: str, token: str, kitchen: str, client: httpx.Client | None = None):
        self.kitchen = kitchen
        self.http = client or httpx.Client(base_url=base_url.rstrip("/"), timeout=30, follow_redirects=False)
        self.auth = {"Authorization": "Bearer " + token}
        self.results: list[Check] = []
        self.offer: dict | None = None

    def call(self, method: str, path: str, *, auth: bool = True, **kw) -> tuple[int, dict]:
        response = self.http.request(method, path, headers=self.auth if auth else {}, **kw)
        try:
            data = response.json()
        except ValueError:
            data = {}
        return response.status_code, data if isinstance(data, dict) else {}

    def check(self, cid: str, rule: str, fn) -> None:
        try:
            ok, detail = fn()
            status = "SKIP" if ok is None else ("PASS" if ok else "FAIL")
        except Exception as exc:   # a crash of the check is a failure, never hidden
            status, detail = "FAIL", f"check crashed: {type(exc).__name__}"
        self.results.append(Check(cid, rule, status, detail))

    @staticmethod
    def _code(data: dict) -> str:
        return str((data.get("error") or {}).get("code"))

    # ---- the checks -------------------------------------------------------------------

    def c01(self):
        status, data = self.call("GET", "/health", auth=False)
        return status == 200 and data.get("status") == "ok", f"HTTP {status}"

    def c02(self):
        status, data = self.call("GET", f"/v1/kitchens/{self.kitchen}/orders", auth=False)
        return status == 401, f"HTTP {status} {self._code(data)}"

    def c03(self):
        status, data = self.call("GET", f"/v1/kitchens/{self.kitchen}/permissions")
        never = [row.get("action") for row in data.get("never", [])]
        return status == 200 and len(never) >= 3, f"{len(never)} never-rows served"

    def c04(self):
        """The model cannot set a quantity: the stored need decides."""
        day = (date.today() + timedelta(days=3)).isoformat()
        status, found = self.call("POST", "/tools/search_products", json={"query": "lactose free milk 1 l", "filters": {}, "limit": 5})
        ids = [p.get("product_id") for p in found.get("products", []) if p.get("product_id")][:5]
        if status != 200 or not ids:
            return None, f"catalog search returned nothing (HTTP {status})"
        status, need = self.call("POST", f"/v1/kitchens/{self.kitchen}/needs",
                                 json={"quantity": "7", "unit": "L", "requested_date": day, "text": "[conformance kit]"})
        if status != 200:
            return False, f"need refused: HTTP {status} {self._code(need)}"
        status, offer = self.call("POST", "/tools/get_offer", json={
            "need_id": need["need_id"], "product_ids": ids, "quantity": "99999"})
        if status != 200:
            return False, f"offer refused: HTTP {status} {self._code(offer)}"
        self.offer = offer
        litres = sum(float(line["quantity"]) for line in offer.get("lines", []))
        sized = offer.get("lines") == [] or litres < 1000
        return sized, f"asked the tool for 99999, need is 7 L, offer has {len(offer.get('lines', []))} line(s)"

    def c05(self):
        if not self.offer:
            return None, "no offer"
        status, sim = self.call("POST", "/tools/simulate_order", json={"offer_id": self.offer["offer_id"]})
        same = status == 200 and sim.get("expected_total") == self.offer.get("expected_total")
        verdict = (sim.get("mandate") or {}).get("verdict")
        return same and verdict in ("NEEDS_APPROVAL", "REFUSED"), f"total {sim.get('expected_total')} EUR, verdict {verdict}"

    def c06(self):
        if not self.offer:
            return None, "no offer"
        status, data = self.call("POST", "/tools/place_order", json={
            "offer_id": self.offer["offer_id"], "expected_total": self.offer.get("expected_total"),
            "idempotency_key": "conformance-" + self.offer["offer_id"][:12]})
        return status == 403 and self._code(data) == "NEEDS_APPROVAL", f"HTTP {status} {self._code(data)}"

    def c07(self):
        refused = []
        for action, body in (("approve", {"expected_total": "1.00", "idempotency_key": "conformance"}),
                             ("reject", {"reason": "conformance", "idempotency_key": "conformance"})):
            status, data = self.call("POST", f"/v1/kitchens/{self.kitchen}/proposals/conformance-none/{action}", json=body)
            refused.append(status == 403 and self._code(data) in ("HUMAN_SESSION_REQUIRED", "ROLE_REQUIRED"))
        return all(refused), "approve and reject both 403 for this token"

    def c08(self):
        status, data = self.call("POST", f"/v1/kitchens/{self.kitchen}/tokens",
                                 json={"name": "conformance", "scopes": ["kitchen:read"]})
        return status == 403, f"HTTP {status} {self._code(data)}"

    def c09(self):
        gone = []
        for method, path in (("POST", "/tools/cancel_order"), ("DELETE", f"/v1/kitchens/{self.kitchen}/orders/none"),
                             ("PATCH", f"/v1/kitchens/{self.kitchen}/orders/none")):
            status, _ = self.call(method, path, json={})
            gone.append(status in (404, 405))
        return all(gone), "no cancel or edit route for an order"

    def c10(self):
        status, data = self.call("GET", "/v1/kitchens/conformance-other-kitchen/orders")
        if status == 200:
            return None, "this token is a server agent token (any kitchen); use a kitchen API token to test"
        return status == 403 and self._code(data) == "KITCHEN_SCOPE", f"HTTP {status} {self._code(data)}"

    def c11(self):
        status, data = self.call("POST", "/tools/simulate_order", json={"offer_id": "conformance-unknown"})
        return status == 404 and self._code(data) == "OFFER_NOT_FOUND", f"HTTP {status} {self._code(data)}"

    @staticmethod
    def _rpc_result(response: httpx.Response, rpc_id) -> dict:
        """The JSON-RPC result for rpc_id, from a plain JSON reply or a streamable-HTTP SSE stream."""
        if response.headers.get("content-type", "").split(";")[0].strip().lower() != "text/event-stream":
            return response.json()["result"]
        events, lines = [], []
        for line in response.text.splitlines() + [""]:
            if line.startswith("data:"):
                lines.append(line[5:].removeprefix(" "))
            elif not line.strip() and lines:
                events.append("\n".join(lines))
                lines = []
        for event in events:
            try:
                message = json.loads(event)
            except ValueError:
                continue
            if isinstance(message, dict) and message.get("id") == rpc_id and "result" in message:
                return message["result"]
        raise ValueError(f"no JSON-RPC response with id {rpc_id!r} in the SSE stream")

    def c12(self):
        response = self.http.post("/mcp", headers={**self.auth, "Accept": "application/json, text/event-stream",
                                                   "Content-Type": "application/json", "MCP-Protocol-Version": "2025-06-18"},
                                  json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
        if response.status_code != 200:
            return None, f"/mcp not reachable with this token (HTTP {response.status_code})"
        names = [t["name"] for t in self._rpc_result(response, 1)["tools"]]
        bad = [n for n in names if any(w in n for w in ("approve", "reject", "cancel"))]
        return not bad, f"{len(names)} MCP tools, none approves, rejects or cancels"

    def run(self) -> list[Check]:
        for cid, rule, fn in (
            ("C01", "The gateway answers /health", self.c01),
            ("C02", "No token, no access (401)", self.c02),
            ("C03", "The permissions table is served", self.c03),
            ("C04", "The gateway sizes the order from the stored need; a quantity from the model is ignored", self.c04),
            ("C05", "simulate_order returns the same total as the offer, with a verdict", self.c05),
            ("C06", "place_order without a human approval is refused (NEEDS_APPROVAL)", self.c06),
            ("C07", "An agent token cannot approve or reject", self.c07),
            ("C08", "An agent token cannot create API tokens", self.c08),
            ("C09", "There is no cancel or edit route for an order", self.c09),
            ("C10", "A kitchen token cannot read another kitchen", self.c10),
            ("C11", "An unknown offer is 404, not a guess", self.c11),
            ("C12", "The MCP server exposes no approve, reject or cancel tool", self.c12),
        ):
            self.check(cid, rule, fn)
        return self.results


def table(results: list[Check], markdown: bool = False) -> str:
    if markdown:
        rows = ["| Check | Rule | Result | Detail |", "|---|---|---|---|"]
        rows += [f"| {r.id} | {r.rule} | {r.status} | {r.detail} |" for r in results]
        return "\n".join(rows)
    return "\n".join(f"{r.id}  {r.status:<4}  {r.rule}  [{r.detail}]" for r in results)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--token", default=os.environ.get("TKB_TOKEN", ""))
    parser.add_argument("--kitchen", default="demo-kitchen")
    parser.add_argument("--markdown", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if not args.token:
        parser.error("give --token or set TKB_TOKEN")
    results = Kit(args.base_url, args.token, args.kitchen).run()
    if args.json:
        print(json.dumps({"passed": sum(r.status == "PASS" for r in results),
                          "failed": sum(r.status == "FAIL" for r in results),
                          "checks": [asdict(r) for r in results]}, indent=2))
    else:
        print(table(results, args.markdown))
        print(f"\n{sum(r.status == 'PASS' for r in results)} passed, "
              f"{sum(r.status == 'FAIL' for r in results)} failed, "
              f"{sum(r.status == 'SKIP' for r in results)} skipped")
    return 1 if any(r.status == "FAIL" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
