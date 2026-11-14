# Bring your own agent

The gateway works with any agent that has two things: the URL and a kitchen token.
This page shows it twice: with `curl` only, and with an MCP client (Claude Desktop,
Claude Code). Both end in a milk proposal that waits for a person.

- Site: `https://31-22-104-201.sslip.io`
- Gateway base URL (your own bearer token): `https://31-22-104-201.sslip.io/gateway`
- For an agent to read first, no token needed:
  - `https://31-22-104-201.sslip.io/llms.txt`
  - `https://31-22-104-201.sslip.io/.well-known/agent-card.json`
  - `https://31-22-104-201.sslip.io/gateway/openapi.json` (try it: `/gateway/docs`)
- MCP endpoint: `https://31-22-104-201.sslip.io/gateway/mcp`

The two discovery files are written by the gateway from its own routes on every request
(`gateway/discovery.py`). A skill is in them only when its route is served.

Use `/gateway`, not `/api`. `/api` is the web app's path: the server puts the demo
person's session on it, so your own token is ignored there.

## 1. Get a token

A token belongs to one kitchen and has scopes. `kitchen:read` reads; `kitchen:propose`
asks for orders. There is no approve scope: a token can never approve.

A signed-in person creates the token (`POST /v1/kitchens/{kitchen_id}/tokens`). On the
demo site everybody is the demo person, so this one call works without a password:

```bash
curl -s -X POST https://31-22-104-201.sslip.io/api/v1/kitchens/demo-kitchen/tokens \
  -H 'Content-Type: application/json' \
  -d '{"name": "my-agent", "scopes": ["kitchen:read", "kitchen:propose"]}'
```

```json
{"token_id": "3a6ace18...", "name": "my-agent", "scopes": ["kitchen:propose", "kitchen:read"],
 "prefix": "tkb_AbCd", "created_by": "demo-visitor", "token": "tkb_..."}
```

The `token` value is shown once. Keep it out of git. Revoke it with
`DELETE /api/v1/kitchens/demo-kitchen/tokens/<token_id>`. The Settings page of the web
app has a place for tokens, but it does not create them yet (#261): use the call above.

```bash
export BASE=https://31-22-104-201.sslip.io/gateway
export TOKEN=tkb_REPLACE_WITH_YOUR_TOKEN
```

Check it:

```bash
curl -s $BASE/v1/me -H "Authorization: Bearer $TOKEN"
```

```json
{"kind":"token","name":"token:my-agent","role":null,"kitchen_id":"demo-kitchen","can_approve":false,"scopes":["kitchen:propose","kitchen:read"]}
```

## 2. The curl sequence: search, offer, simulate, propose

The outputs below are real: one run against the deployed site on 2026-11-14 (UTC),
trimmed. Prices and stock are live, so your numbers can differ.

### Search

```bash
curl -s -X POST $BASE/tools/search_products -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"query": "lactose free milk 1 l", "limit": 5}'
```

```json
{"products": [
  {"product_id": "469330", "names": {"en": "5 x Arla 1 L lactose free semi-skimmed milk drink Suomesta ESL"}, "sales_unit": "KI", "lactose_free": true, "match_reasons": ["size 1 L matches"]},
  {"product_id": "463380", "names": {"en": "Arla Cafè milk 1 L UHT lactose free"}, "sales_unit": "ST", "lactose_free": true},
  {"product_id": "464073", "names": {"en": "Valio whole milk 1 l lactose free UHT"}, "sales_unit": "ST", "lactose_free": true, "reliability": 1.0, "carbon_kg_co2e_per_kg": 1.1},
  {"product_id": "464119", "names": {"en": "Valio skimmed milk 1 l lactose free UHT"}, "sales_unit": "KI", "lactose_free": true},
  {"product_id": "464237", "names": {"en": "Valio coffee milk 1 l lactose free UHT"}, "sales_unit": "ST", "lactose_free": true}
]}
```

### Offer

The quantity is not an argument of the offer. First store the need; the gateway sizes
every line from it. Your agent chooses products, never quantities.

```bash
curl -s -X POST $BASE/v1/kitchens/demo-kitchen/needs -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"quantity": "40", "unit": "L", "requested_date": "2026-11-16", "text": "40 L lactose-free milk for Monday"}'
```

```json
{"need_id":"d885768b538d4f628b8a22575940639b","quantity":"40","unit":"L","requested_date":"2026-11-16","text":"40 L lactose-free milk for Monday"}
```

Use a delivery date in the future and your own `need_id`. Products 464073 and 463380
come from the search above; 462775 (Arla Milkdrink 1 L lactose free) is the team's demo
milk, added by hand.

```bash
curl -s -X POST $BASE/tools/get_offer -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"need_id": "d885768b538d4f628b8a22575940639b", "product_ids": ["462775", "464073", "463380"]}'
```

```json
{"offer_id": "3d9d3840338049f986c81d66b0ee5b92", "valid_until": "2026-11-14T01:57:42.044953+00:00",
 "currency": "EUR", "total_ex_vat": "102.80", "vat": "13.88", "delivery_fee": null, "mov_gap": null,
 "expected_total": "116.68", "shortfall": "0", "measure": "L",
 "mandate": {"verdict": "NEEDS_APPROVAL", "reasons": [], "reason_codes": ["PACK_SIZE_DERIVED"], "warnings": []},
 "lines": [{"product_id": "462775", "quantity": "40", "unit": "ST", "unit_price": "2.57", "total": "102.80",
   "why": "40 ST of Arla Milkdrink 1L lactose free fat free UHT Suomesta = 40 L, confirmed in stock.",
   "unknown_stock": false, "carbon_kg_co2e_per_kg": 1.1, "available_date": "2026-11-16",
   "cutoff_passed": false, "closing_time": "2026-11-15T17:00:00+02:00"}],
 "excluded": [],
 "alternative": {"total_ex_vat": "65.60", "lines": [{"product_id": "464073", "quantity": "40", "unit": "ST", "total": "65.60",
   "why": "40 ST of Valio whole milk 1 l lactose free UHT = 40 L: cheapest per L (1.64 EUR), but Valio does not report its stock, so it is not confirmed."}]}}
```

Read the `alternative`: the cheaper milk is not chosen, because Valio does not report
its stock. Unknown stock is not stock.

### Simulate

```bash
curl -s -X POST $BASE/tools/simulate_order -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"offer_id": "3d9d3840338049f986c81d66b0ee5b92"}'
```

```json
{"offer_id": "3d9d3840338049f986c81d66b0ee5b92", "expected_total": "116.68", "total_ex_vat": "102.80", "vat": "13.88",
 "shortfall": "0", "mandate": {"verdict": "NEEDS_APPROVAL", "reasons": [], "reason_codes": ["PACK_SIZE_DERIVED"], "warnings": []},
 "lines": [{"product_id": "462775", "quantity": "40", "unit": "ST", "total": "102.80", "unknown_stock": false}]}
```

Nothing is placed. The total your agent may quote is `expected_total`, as it stands here.
`delivery_fee` is null because this kitchen's supplier terms are not set: unknown, not zero.

### Propose

```bash
curl -s -X POST $BASE/tools/request_approval -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"offer_id": "3d9d3840338049f986c81d66b0ee5b92", "idempotency_key": "byoa-milk-2026-11-16-1"}'
```

```json
{"approval_id":"f1394566df0c4d8c9d0351bb9c22756f","proposal_id":"9f461e1ac2ba40ca834177ce3a3e1be5","status":"PENDING"}
```

Send the same call again with the same key and you get the same proposal, not a second
one. The proposal is now in the approval inbox of the web app:

```bash
curl -s $BASE/v1/kitchens/demo-kitchen/proposals/9f461e1ac2ba40ca834177ce3a3e1be5 -H "Authorization: Bearer $TOKEN"
```

```json
{"proposal_id": "9f461e1ac2ba40ca834177ce3a3e1be5", "status": "READY", "expected_total": "116.68", "order_id": null,
 "decision_summary": {"text": "Asked: \"40 L lactose-free milk for Monday\" (40 L for 2026-11-16).\nChecked 3 product(s) with Valio prices and stock for 2026-11-16: 462775, 464073, 463380.\nChosen: 40 ST of 462775 Arla Milkdrink 1L lactose free fat free UHT Suomesta, EUR 102.80 ex VAT: ...\nTotal EUR 116.68 (EUR 102.80 ex VAT + VAT EUR 13.88; delivery fee unknown: supplier terms not set). A cheaper option was also found: EUR 65.60 ex VAT.\nTo decide: Nothing is ordered until a person approves the total of EUR 116.68."}}
```

### A person approves

Your agent stops here. A person opens `https://31-22-104-201.sslip.io/`, reads the card
and approves or rejects. A token that calls `.../approve` gets
`403 HUMAN_SESSION_REQUIRED` (test: `gateway/tests/test_discovery.py`,
`test_approval_is_human_only_and_not_a_skill`).

## 3. An MCP client

The gateway serves MCP over streamable HTTP at `/gateway/mcp` (#280): this is the remote
endpoint, not the stdio server. The same kitchen token works when it has
`kitchen:propose`. The tools are `search_products`, `get_offer`, `simulate_order`,
`request_approval`, `place_order`, `get_order_status` and `get_audit_log`. There is no
approve tool.

Checked on the deployed site with the token from step 1 (2026-11-14):

```bash
curl -s -X POST $BASE/mcp -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}'
```

It answers 200 with the seven tools above. Without a token it answers 401.

### Claude Code

```bash
claude mcp add --transport http kitchen-buyer https://31-22-104-201.sslip.io/gateway/mcp --header "Authorization: Bearer tkb_REPLACE_WITH_YOUR_TOKEN"
```

### Claude Desktop

Claude Desktop's config file starts local programs, so the small `mcp-remote` bridge
(needs Node.js) carries the bearer header to the remote endpoint. Put this in
`claude_desktop_config.json` (Settings, Developer, Edit Config) and restart the app:

```json
{
  "mcpServers": {
    "kitchen-buyer": {
      "command": "npx",
      "args": [
        "-y",
        "mcp-remote",
        "https://31-22-104-201.sslip.io/gateway/mcp",
        "--header",
        "Authorization:${KITCHEN_AUTH}"
      ],
      "env": {
        "KITCHEN_AUTH": "Bearer tkb_REPLACE_WITH_YOUR_TOKEN"
      }
    }
  }
}
```

Not yet run in Claude Desktop itself: the endpoint was checked with raw MCP calls only
(above). The header has no space after the colon on purpose; the space is inside the
`KITCHEN_AUTH` value (Claude Desktop on Windows splits arguments at spaces).

### An independent MCP client, run on the live site

`python -m demo.second_agent --make-token` is a second agent that is not the team's Buyer.
It uses the public `mcp` client library and the Python standard library, and none of the
gateway's code. It does what an outside agent would do, then tries to approve its own
proposal. Output on the live site, 2026-11-14 05:30 UTC:

```
0. token made            scopes ['kitchen:propose', 'kitchen:read'] (the value is not printed)
1. agent card            HTTP 200, 8 skills, approve among them: False
2. who am I              HTTP 200, kind token, can_approve False, scopes ['kitchen:propose', 'kitchen:read']
3. store the need        HTTP 200, 40 L for 2026-11-16
4. MCP tools/list        7 tools: get_audit_log, get_offer, get_order_status, place_order, request_approval, search_products, simulate_order
                         an approve tool exists: False
5. MCP search_products   20 products (text search), 8 can arrive; the agent picks ['473625', '474390', '463380']
6. MCP get_offer         offer 2e8f0aba..., 1 line(s): 40 x 463380
7. MCP simulate_order    total 145.31 EUR, mandate verdict NEEDS_APPROVAL
8. MCP request_approval  status PENDING, proposal aa6f9489... waits for a person
9. the agent tries to approve its own proposal: HTTP 403 HUMAN_SESSION_REQUIRED
10. the proposal after that: READY, order None
RESULT: an outside agent reached a waiting proposal over MCP, and could not approve it
11. token revoked        HTTP 200
```

The agent picked three products; the engine sized one line from the stored need (40 L) and
left the other two out. With login switched on, make the token as a signed-in person and
pass it as `KITCHEN_TOKEN`.

### The need comes first

No MCP tool stores a need, on purpose: quantities come from the kitchen's app, not from
the model. So for an MCP agent, store the need with the one `curl` call in "Offer"
above, then give the agent the `need_id`:

> Use the kitchen-buyer tools. Find lactose-free milk in 1 l packs, get an offer for need
> `<need_id>` (delivery 2026-11-16), simulate it, and ask for approval. Tell me the
> total from the simulation and say that it waits for a person.

## Rules your agent must keep

- Unknown stock is not stock: a line with `unknown_stock: true` is not confirmed.
- The agent never approves. It reports `PENDING` and stops.
- Totals come from `simulate_order`. Never compute or round your own.
- Quantities come from the stored need.
- Every write takes an `idempotency_key` in the JSON body. After a timeout, read the
  state before you send again.
- `REFUSED` is final for that offer.

All fields and error codes: `docs/contract.md`.
