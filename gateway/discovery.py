"""Agent discovery (#293): `/.well-known/agent-card.json` and `/llms.txt`.

Both are built from the running app on every request, so they cannot drift from it:
- a skill is listed only when its route is registered on this app;
- the MCP tool names and their descriptions come from the mounted MCP server;
- the scopes come from gateway/tokens.py, the version and title from the FastAPI app;
- the URLs come from the request (host, scheme) plus `GATEWAY_PUBLIC_PREFIX`, the path
  prefix the reverse proxy strips before the gateway (`/gateway` on the deployed site).

No token is needed to read them, and they hold no secret and no kitchen data.

The card follows the shape of an A2A agent card (name, url, provider, skills,
securitySchemes) so a client can discover the gateway. The gateway does NOT serve the
A2A message protocol; the card says so and points at what is served: HTTP + JSON and MCP.
"""

from __future__ import annotations

import os
import re

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from gateway import tokens

CARD_PATH = "/.well-known/agent-card.json"
LLMS_PATH = "/llms.txt"
REPO = "https://github.com/Afro666/2Brothers"
CONTRACT = REPO + "/blob/main/docs/contract.md"
BYOA = REPO + "/blob/main/docs/byoa.md"
K = "/v1/kitchens/{kitchen_id}"

SCOPE_TEXT = {
    "kitchen:read": "search the catalog; read proposals, orders and the audit log of the token's kitchen",
    "kitchen:propose": "store a need, get an offer, simulate it and ask a person to approve it",
}

# (id, method, path, scope, name, description when there is no MCP tool of that name, tags)
SKILLS = (
    ("search_products", "POST", "/tools/search_products", "kitchen:read", "Search products",
     "Find catalog products by text and filters.", ["catalog", "search"]),
    ("create_need", "POST", K + "/needs", "kitchen:propose", "Store the need",
     "Store what the kitchen needs (quantity, unit, requested_date). Quantities live here, "
     "never in an agent's later calls.", ["need"]),
    ("get_offer", "POST", "/tools/get_offer", "kitchen:propose", "Get offer",
     "Live price and stock for the chosen products, sized by the gateway from the stored need.",
     ["offer", "price", "stock"]),
    ("simulate_order", "POST", "/tools/simulate_order", "kitchen:propose", "Simulate order",
     "The exact total and the mandate verdict for an offer. Places nothing.", ["simulate", "total"]),
    ("request_approval", "POST", "/tools/request_approval", "kitchen:propose", "Propose order",
     "Open a pending proposal for a person to approve in the inbox.", ["propose", "approval"]),
    ("place_order", "POST", "/tools/place_order", "kitchen:propose", "Read the approved order",
     "Returns the order only after a person approved the proposal; otherwise 403 NEEDS_APPROVAL.",
     ["order"]),
    ("get_order_status", "GET", "/tools/get_order_status", "kitchen:read", "Order status",
     "Read the status and outcome of an order.", ["order", "status"]),
    ("get_audit_log", "GET", "/tools/get_audit_log", "kitchen:read", "Audit log",
     "Read the audit events of one run.", ["audit"]),
)

# What a token can never do. Listed so an agent does not look for it.
HUMAN_ONLY = (
    ("approve", "POST", K + "/proposals/{proposal_id}/approve"),
    ("reject", "POST", K + "/proposals/{proposal_id}/reject"),
    ("manage_tokens", "POST", K + "/tokens"),
)

_HOST = re.compile(r"[A-Za-z0-9.\-\[\]:]{1,255}")


def _routes(app: FastAPI) -> set[tuple[str, str]]:
    return {(method, route.path) for route in app.routes
            for method in (getattr(route, "methods", None) or ())}


def _site(request: Request) -> str:
    """The public origin as the caller typed it. A header that is not a host name is dropped."""
    proto = (request.headers.get("x-forwarded-proto") or request.url.scheme).split(",")[0].strip()
    host = request.headers.get("host") or ""
    if proto not in ("http", "https"):
        proto = "http"
    if not _HOST.fullmatch(host):
        host = "localhost"
    return f"{proto}://{host}"


def _prefix() -> str:
    prefix = "/" + os.environ.get("GATEWAY_PUBLIC_PREFIX", "").strip("/")
    return "" if prefix == "/" or not re.fullmatch(r"(/[A-Za-z0-9._\-]+)+", prefix) else prefix


async def _mcp_tools(app: FastAPI) -> dict[str, str]:
    """Tool name -> description, from the mounted MCP server. Empty when /mcp is not served."""
    server = getattr(app.state, "mcp", None)
    path = getattr(getattr(server, "settings", None), "streamable_http_path", None)
    if server is None or not any(getattr(r, "path", None) == path for r in app.routes):
        return {}
    return {tool.name: " ".join((tool.description or "").split()) for tool in await server.list_tools()}


async def describe(app: FastAPI, request: Request) -> dict:
    """Everything both files say, read from the app as it runs."""
    base = _site(request) + _prefix()
    routes = _routes(app)
    mcp = await _mcp_tools(app)
    skills = [{
        "id": sid, "name": name, "description": mcp.get(sid) or fallback, "tags": tags,
        "method": method, "path": path, "url": base + path, "scope": scope,
        "mcp_tool": sid if sid in mcp else None,
    } for sid, method, path, scope, name, fallback, tags in SKILLS if (method, path) in routes]
    return {
        "name": app.title, "version": app.version, "site": _site(request), "base": base,
        "skills": skills,
        "human_only": [{"id": hid, "method": method, "path": path}
                       for hid, method, path in HUMAN_ONLY if (method, path) in routes],
        "scopes": {scope: SCOPE_TEXT.get(scope, "") for scope in tokens.SCOPES},
        "openapi": base + app.openapi_url if app.openapi_url else None,
        "docs": base + app.docs_url if app.docs_url else None,
        "mcp": base + app.state.mcp.settings.streamable_http_path if mcp else None,
        "mcp_tools": sorted(mcp),
        "token_route": K + "/tokens" if ("POST", K + "/tokens") in routes else None,
        "permissions": base + K + "/permissions" if ("GET", K + "/permissions") in routes else None,
    }


def agent_card(d: dict) -> dict:
    interfaces = [{"transport": "HTTP+JSON", "url": d["base"], "openapi": d["openapi"]}]
    if d["mcp"]:
        interfaces.append({"transport": "MCP (streamable HTTP, stateless JSON)", "url": d["mcp"],
                           "tools": d["mcp_tools"]})
    scopes = sorted(d["scopes"])
    return {
        "name": d["name"],
        "description": (
            "Purchasing gateway for a professional kitchen over Valio Aimo's catalog, prices and "
            "stock. Any agent with this URL and a kitchen token can search products, get an offer, "
            "simulate it and propose an order. A person approves every order in the approval "
            "inbox; no token can approve."),
        "url": d["base"],
        "version": d["version"],
        "provider": {"organization": "2Brothers (Junction 2026, Valio Aimo challenge)", "url": REPO},
        "documentationUrl": d["base"] + LLMS_PATH,
        "preferredTransport": "HTTP+JSON",
        "additionalInterfaces": interfaces,
        "capabilities": {
            "streaming": False, "pushNotifications": False, "stateTransitionHistory": False,
            "a2aMessaging": False,
            "note": ("Discovery card in the A2A agent-card shape. The gateway does not serve the "
                     "A2A message protocol: call the skills over HTTP + JSON or as MCP tools."),
        },
        "defaultInputModes": ["application/json"],
        "defaultOutputModes": ["application/json"],
        "securitySchemes": {"bearer": {
            "type": "http", "scheme": "bearer",
            "description": (
                f"Authorization: Bearer <kitchen API token, starts with {tokens.PREFIX}>. One token "
                "acts for one kitchen. A signed-in person creates and revokes it"
                + (f" (POST {d['token_route']})" if d["token_route"] else "")
                + ". The scope kitchen:approve does not exist for tokens."),
            "scopes": d["scopes"],
        }},
        "security": [{"bearer": scopes}],
        "skills": d["skills"],
        "humanOnly": [{**h, "reason": "only a signed-in person; a token gets 403 HUMAN_SESSION_REQUIRED"}
                      for h in d["human_only"]],
        "links": {"openapi": d["openapi"], "docs": d["docs"], "mcp": d["mcp"], "permissions": d["permissions"],
                  "llms_txt": d["base"] + LLMS_PATH, "agent_card": d["base"] + CARD_PATH,
                  "contract": CONTRACT, "how_to": BYOA, "source": REPO},
    }


def llms_txt(d: dict) -> str:
    base = d["base"]
    by_id = {s["id"]: s for s in d["skills"]}

    def call(sid: str) -> str:
        s = by_id.get(sid)
        return f"`{s['method']} {s['path']}` (scope `{s['scope']}`)" if s else "(not served by this gateway)"

    lines = [
        f"# {d['name']}",
        "",
        "> A purchasing gateway for a professional kitchen over Valio Aimo's catalog, live prices "
        "and stock. Bring your own agent: with this URL and a kitchen token, any agent can search, "
        "get an offer, simulate it and propose an order. A person approves every order.",
        "",
        f"- Base URL: {base}",
        f"- Version: {d['version']}",
        "- Requests and answers are JSON. Money is a decimal string in EUR. IDs are opaque strings.",
        "- An error is `{\"error\": {\"code\": \"...\", \"message\": \"...\"}}` with a 4xx status.",
        "",
        "## Token",
        "",
        "- Send `Authorization: Bearer <token>` on every call. This file and the agent card need no token.",
        f"- A kitchen token starts with `{tokens.PREFIX}` and acts for one kitchen only (403 `KITCHEN_SCOPE` elsewhere).",
        "- Scopes: " + "; ".join(f"`{scope}`: {text}" for scope, text in d["scopes"].items()) + ".",
        "- A missing scope gives 403 `SCOPE_REQUIRED`. There is no approve scope for a token.",
    ]
    if d["token_route"]:
        lines.append(
            f"- A signed-in person creates the token: `POST {d['token_route']}` with "
            "`{\"name\": \"my-agent\", \"scopes\": [\"kitchen:read\", \"kitchen:propose\"]}`. "
            "The token is shown once. An agent cannot create a token for itself.")
    lines += [
        f"- Check a token: `GET {base}/v1/me`.",
        "",
        "## The flow: 5 steps",
        "",
        f"1. Search: {call('search_products')}. Body `{{\"query\": \"lactose-free milk\", \"filters\": {{}}, \"limit\": 5}}`. "
        "Answer: `products[]`, each with a `product_id`.",
        f"2. Offer: first store the need, {call('create_need')}, body "
        "`{\"quantity\": \"40\", \"unit\": \"L\", \"requested_date\": \"YYYY-MM-DD\", \"text\": \"...\"}` "
        f"-> `need_id`. Then {call('get_offer')}, body "
        "`{\"need_id\": \"...\", \"product_ids\": [\"...\"]}` -> `offer_id`, `valid_until`, `lines[]`. "
        "The gateway sizes every line from the stored need; you choose products, not quantities.",
        f"3. Simulate: {call('simulate_order')}, body `{{\"offer_id\": \"...\"}}` -> `expected_total`, "
        "`mandate.verdict` (`NEEDS_APPROVAL` or `REFUSED`), `mandate.reasons`, `lines[]`, `excluded[]`. "
        "Nothing is placed.",
        f"4. Propose: {call('request_approval')}, body `{{\"offer_id\": \"...\", \"idempotency_key\": \"...\"}}` "
        "-> `proposal_id`, `approval_id`, `status: PENDING`.",
        "5. A person approves or rejects the proposal in the approval inbox of the web app"
        + (f" ({d['site']}/)" if d["site"] != base else "") + ". Your work ends at `PENDING`: report it as pending.",
        "",
        "## Rules an agent must know",
        "",
        "- Unknown stock is not stock. A line with `unknown_stock: true` is not confirmed; never report it as available. Measured zero is unavailable.",
        "- You can never approve. Approve, reject and token management need a signed-in person; "
        "a token gets 403 `HUMAN_SESSION_REQUIRED`"
        + (" on " + ", ".join(f"`{h['method']} {h['path']}`" for h in d["human_only"]) if d["human_only"] else "")
        + ". There is no MCP tool for them.",
        "- Totals come from simulate. Quote `expected_total` and line totals exactly as the gateway returns them; never compute or round your own.",
        "- Quantities come from the stored need. `get_offer` and `simulate_order` take no quantity.",
        "- Idempotency keys: every write that creates something takes a nonempty `idempotency_key` in the JSON body (not a header). "
        "The same key with the same body returns the stored result; the same key with another body gives 409 `IDEMPOTENCY_KEY_REUSED`.",
        "- After a timeout on a write, read the state before you send again; never resend blindly.",
        "- `REFUSED` is final for that offer (an allergen rule, a passed cut-off, a sales block). Do not work around it.",
        "- An offer is valid until `valid_until` (about 15 minutes). After that: 409 `OFFER_EXPIRED`, get a new offer.",
    ]
    if "place_order" in by_id:
        lines.append(f"- {call('place_order')} only returns an order a person already approved; before that it is 403 `NEEDS_APPROVAL`.")
    lines += ["", "## Every skill this gateway serves", ""]
    lines += [f"- `{s['id']}`: `{s['method']} {s['url']}`, scope `{s['scope']}`"
              + (", also an MCP tool" if s["mcp_tool"] else ", HTTP only") + f". {s['description']}"
              for s in d["skills"]]
    lines += ["", "## Links", ""]
    if d["openapi"]:
        lines.append(f"- OpenAPI: {d['openapi']}" + (f" (try it: {d['docs']})" if d["docs"] else ""))
    if d["mcp"]:
        lines.append(f"- MCP (streamable HTTP, same bearer token with `kitchen:propose`): {d['mcp']} "
                     f"with the tools {', '.join('`' + t + '`' for t in d['mcp_tools'])}")
        if "create_need" in by_id and "create_need" not in d["mcp_tools"]:
            lines.append("  MCP has no tool that stores a need, on purpose: the kitchen's app (or one HTTP call) "
                         "stores it and gives the agent the `need_id`.")
    if d["permissions"]:
        lines.append(f"- What an agent does alone, what a person signs off, what it can never do: `GET {d['permissions']}` (scope `kitchen:read`)")
    lines += [
        f"- Agent card: {base}{CARD_PATH}",
        f"- Contract (every field and error code): {CONTRACT}",
        f"- Copy-paste curl sequence and MCP client config: {BYOA}",
        f"- Source: {REPO}",
        "",
    ]
    return "\n".join(lines)


def mount_discovery(app: FastAPI) -> None:
    @app.get(CARD_PATH, include_in_schema=False)
    async def card(request: Request) -> JSONResponse:
        return JSONResponse(agent_card(await describe(app, request)),
                            headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "public, max-age=300"})

    @app.get(LLMS_PATH, include_in_schema=False)
    async def llms(request: Request) -> PlainTextResponse:
        return PlainTextResponse(llms_txt(await describe(app, request)),
                                 headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "public, max-age=300"})
