"""A second, independent agent on the gateway's public MCP endpoint (#286, docs/byoa.md).

    python -m demo.second_agent --make-token          # the open demo site: make a token, use it, revoke it
    KITCHEN_TOKEN=tkb_... python -m demo.second_agent # your own token
    python -m demo.second_agent --base-url https://31-22-104-201.sslip.io --kitchen demo-kitchen

It is not the team's Buyer and uses none of the gateway's code: only the public `mcp`
client library and the standard library. It does what any outside agent would do with a
kitchen token: read the agent card, list the tools, search, get an offer, simulate, ask
for approval. Then it tries what it must not be able to do: approve its own proposal.
The gateway has to refuse that. Each step prints one line, so the output is the proof.

What it writes on the site: one need and one proposal that waits for a person. With
`--make-token` also one token, which it revokes at the end. It never prints the token.
Needs the MCP client library (`pip install mcp`); it is not a dependency of the app.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import date, timedelta
import json
import os
import sys
import urllib.error
import urllib.request

AGENT_NAME = "second-agent-demo"


def next_monday(today: date) -> date:
    """The Monday after today; a Monday itself gives the one a week later."""
    return today + timedelta(days=(7 - today.weekday()) or 7)


def call(method: str, url: str, token: str | None = None, body: dict | None = None) -> tuple[int, dict]:
    """One JSON request with the standard library. Returns (status, body)."""
    headers = {"Content-Type": "application/json", "User-Agent": "second-agent-demo/0.1"}
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(url, method=method, headers=headers,
                                     data=None if body is None else json.dumps(body).encode())
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as error:
        raw = error.read()
        try:
            return error.code, json.loads(raw) if raw.strip() else {}
        except ValueError:
            return error.code, {}


def error_code(body: dict) -> str:
    error = body.get("error") if isinstance(body, dict) else None
    return (error or {}).get("code", "") if isinstance(error, dict) else ""


def pick_products(rows: list[dict], limit: int = 3) -> list[str]:
    """Up to `limit` product ids, the ones that can still arrive first. The agent chooses
    products; it never chooses a quantity."""
    ranked = sorted(rows, key=lambda row: 0 if row.get("can_arrive") else 1)
    return [str(row["product_id"]) for row in ranked[:limit] if row.get("product_id")]


def tool_json(result) -> dict:
    """The JSON object of an MCP tool result (structured content, or the first text part)."""
    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict):
        return structured.get("result", structured) if set(structured) == {"result"} else structured
    for part in getattr(result, "content", None) or []:
        text = getattr(part, "text", None)
        if text:
            try:
                return json.loads(text)
            except ValueError:
                return {"text": text}
    return {}


async def run(base: str, kitchen: str, token: str, query: str, quantity: str, unit: str, day: str,
              say=print) -> dict:
    from mcp import ClientSession                       # optional tool, not an app dependency
    from mcp.client.streamable_http import streamablehttp_client

    gateway = base + "/gateway"
    status, card = call("GET", base + "/.well-known/agent-card.json")
    skills = [skill.get("id") or skill.get("name") for skill in card.get("skills", [])]
    say(f"1. agent card            HTTP {status}, {len(skills)} skills, approve among them: "
        f"{any('approv' in str(s).lower() and 'request' not in str(s).lower() for s in skills)}")

    status, me = call("GET", gateway + "/v1/me", token)
    say(f"2. who am I              HTTP {status}, kind {me.get('kind')}, can_approve {me.get('can_approve')}, "
        f"scopes {sorted(me.get('scopes') or [])}")

    status, need = call("POST", f"{gateway}/v1/kitchens/{kitchen}/needs", token,
                        {"quantity": quantity, "unit": unit, "requested_date": day, "text": f"{quantity} {unit} {query}"})
    say(f"3. store the need        HTTP {status}, {need.get('quantity')} {need.get('unit')} for {need.get('requested_date')}")
    if status != 200:
        raise SystemExit(f"the need was refused: {error_code(need) or status}")

    out = {"need_id": need["need_id"]}
    async with streamablehttp_client(gateway + "/mcp", headers={"Authorization": "Bearer " + token}) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = sorted(tool.name for tool in (await session.list_tools()).tools)
            say(f"4. MCP tools/list        {len(tools)} tools: {', '.join(tools)}")
            say(f"                         an approve tool exists: {any(name.startswith('approve') for name in tools)}")

            found = tool_json(await session.call_tool("search_products", {"query": query, "need_id": need["need_id"]}))
            rows = found.get("products") or found.get("results") or []
            ids = pick_products(rows)
            say(f"5. MCP search_products   {len(rows)} products ({found.get('search', 'text')} search), "
                f"{sum(1 for row in rows if row.get('can_arrive'))} can arrive; the agent picks {ids}")
            if not ids:
                raise SystemExit("the search found no product")

            offer = tool_json(await session.call_tool("get_offer", {
                "product_ids": ids, "requested_date": day, "need_id": need["need_id"]}))
            lines = offer.get("lines") or []
            say(f"6. MCP get_offer         offer {str(offer.get('offer_id'))[:8]}..., {len(lines)} line(s): "
                + "; ".join(f"{line.get('quantity')} x {line.get('product_id')}" for line in lines))
            if not offer.get("offer_id"):
                raise SystemExit("no offer came back")

            sim = tool_json(await session.call_tool("simulate_order", {"offer_id": offer["offer_id"]}))
            verdict = (sim.get("mandate") or {}).get("verdict")
            say(f"7. MCP simulate_order    total {sim.get('expected_total')} {sim.get('currency', '')}, "
                f"mandate verdict {verdict}")

            asked = tool_json(await session.call_tool("request_approval", {"offer_id": offer["offer_id"]}))
            proposal_id = asked.get("proposal_id") or asked.get("approval_id")
            say(f"8. MCP request_approval  status {asked.get('status')}, proposal {str(proposal_id)[:8]}... "
                f"waits for a person")
            out.update({"offer_id": offer["offer_id"], "proposal_id": asked.get("proposal_id"),
                        "expected_total": sim.get("expected_total"), "verdict": verdict, "tools": tools})

    if out.get("proposal_id"):
        status, refused = call("POST", f"{gateway}/v1/kitchens/{kitchen}/proposals/{out['proposal_id']}/approve",
                               token, {"expected_total": out.get("expected_total"),
                                       "idempotency_key": "second-agent-tries-to-approve"})
        say(f"9. the agent tries to approve its own proposal: HTTP {status} {error_code(refused)}")
        out["approve_status"], out["approve_code"] = status, error_code(refused)
        status, proposal = call("GET", f"{gateway}/v1/kitchens/{kitchen}/proposals/{out['proposal_id']}", token)
        say(f"10. the proposal after that: {proposal.get('status')}, order {proposal.get('order_id')}")
        out["final_status"] = proposal.get("status")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", default="https://31-22-104-201.sslip.io")
    parser.add_argument("--kitchen", default="demo-kitchen")
    parser.add_argument("--query", default="lactose-free milk")
    parser.add_argument("--quantity", default="40")
    parser.add_argument("--unit", default="L")
    parser.add_argument("--date", default=next_monday(date.today()).isoformat())
    parser.add_argument("--make-token", action="store_true",
                        help="create a token on the open demo site, and revoke it at the end")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    token, token_id = os.environ.get("KITCHEN_TOKEN", ""), None
    if args.make_token:
        status, made = call("POST", f"{base}/api/v1/kitchens/{args.kitchen}/tokens", None,
                            {"name": AGENT_NAME, "scopes": ["kitchen:read", "kitchen:propose"]})
        if status != 200 or not made.get("token"):
            sys.exit(f"no token: HTTP {status} {error_code(made)} (is login switched on? then pass KITCHEN_TOKEN)")
        token, token_id = made["token"], made.get("token_id")
        print(f"0. token made            scopes {made.get('scopes')} (the value is not printed)")
    if not token:
        sys.exit("set KITCHEN_TOKEN, or pass --make-token on the open demo site")
    try:
        try:
            out = asyncio.run(run(base, args.kitchen, token, args.query, args.quantity, args.unit, args.date))
        except ImportError:
            sys.exit("the MCP client library is not installed: pip install mcp")
        ok = out.get("approve_status") == 403 and out.get("final_status") not in ("APPROVED", None)
        print("RESULT: " + ("an outside agent reached a waiting proposal over MCP, and could not approve it"
                            if ok else "CHECK THE LINES ABOVE: something is not as expected"))
        if not ok:
            sys.exit(1)
    finally:
        if token_id:
            status, _ = call("DELETE", f"{base}/api/v1/kitchens/{args.kitchen}/tokens/{token_id}")
            print(f"11. token revoked        HTTP {status}")


if __name__ == "__main__":
    main()
