# Valio adapter

From the repository root, install with `python -m pip install -e .` and export
`VALIO_API_KEY` in your shell (or load your local `.env` before starting Python).

```python
from gateway.valio_client import ValioClient

client = ValioClient()
client.ping()
prices = client.price(["462775", "462921"], "2026-11-16")
stock = client.availability(["462775", "462921"], "2026-11-16")
```

Requests use bounded 1,000-code chunks, a 30-second bounded cache and up to two
retries for network errors, HTTP 429 and 5xx. Only read operations are implemented.
Do not use this retry policy for gateway order placement. Check each price row's
`error` flag. Both stock sentinels become `availableAmount: null` with
`unknown_stock: true`. `closingTime` includes a timezone; `cutoff_passed` is
recomputed even on cache hits. Missing cutoffs or stock never produce an
`orderable: true` result. This is a preliminary upstream check, not mandate consent.
`orderable` also requires a valid `availableDate` no later than the requested date.
Later dates remain visible in the response for proposing a different delivery,
but must not be treated as fulfilment of the original deadline.

Unknown-stock policy (#48): `orderable` means the upstream data confirms a line
can fulfil the requested delivery, not whether it may appear in a proposal.
Terminal and Stock products with either sentinel remain in the returned
`products`/`scheduleLines`, with `availableAmount: null`, `unknown_stock: true`
and `orderable: false`, even with a future cutoff. Catalog discovery and proposal
screens must keep these products visible and label the quantity as unconfirmed;
they must not discard a product simply because this flag is false. A human can
review the proposal, but supplier confirmation is required before placement.
Allergen, delivery cutoff and other refusal guards still apply. A missing stock
value is treated the same way; measured zero stock is unavailable, not unknown.

Run offline tests: `python -m unittest discover -s gateway/tests -v`.
Fixtures are small responses recorded from the challenge API, without credentials.

## Remote MCP at /mcp (#280)

The gateway app also serves the same seven Buyer tools over MCP streamable HTTP at
`/mcp`, so Claude, Codex or any MCP client can be the Buyer:

```bash
claude mcp add --transport http kitchen-buyer https://<gateway-host>/mcp   --header "Authorization: Bearer $GATEWAY_AGENT_TOKEN"
```

- **Agent token only.** No token, a wrong token or the human token gets `401
  UNAUTHENTICATED` (`WWW-Authenticate: Bearer`). A person approves in the inbox, never
  through MCP; approve, reject and cancel are not tools.
- **Same rules as the HTTP API.** Each tool call runs the gateway's own `/tools/*` route
  in-process with the agent token: same validation, refusals (`NEEDS_APPROVAL`,
  `TOTAL_MISMATCH` ...), principal and audit trail. Errors reach the client as MCP tool
  errors carrying only the gateway's short error code.
- **Stateless JSON** (no server-side MCP session), so any worker can answer.
- Checked with the official MCP Python client over real HTTP (uvicorn): tools listed,
  `get_offer` -> `simulate_order` (`NEEDS_APPROVAL`) -> `request_approval` = `PENDING`;
  the human token is refused. Tests: `gateway/tests/test_mcp_http.py`.

## MCP adapter (#21)

Start the stdio MCP server with `python -m gateway.mcp_server`. Set
`GATEWAY_BASE_URL` for the team HTTP gateway, defaulting to localhost port 8000.
No upstream API key is sent to the gateway. Keep it on a trusted internal network;
public deployment needs authentication and tenant authorization in the gateway.
The shared routes and fields live in `docs/contract.md` (contract PR #51).

For an isolated demo, explicitly run `python -m gateway.mcp_server --mock`.
This simulates a pending milk approval, never a live purchase. The real HTTP
gateway is a separate dependency (#19/#25); it is not implemented by this adapter.

All seven tools have typed inputs and restrictive descriptions. There are no
approve/cancel tools or model-supplied quantities. Mutation requests are sent
once; ambiguous transport failures must be reconciled before another attempt.
The mock has no persistence and is intended only for demos and tests.

Both mutation HTTP requests carry a nonempty `idempotency_key` in the JSON body,
as specified in contract PR #85. The approval adapter generates its stable key
internally, so the MCP `request_approval` tool still takes only `offer_id`.
Header-only keys are rejected by the mock. This convention changes no consent,
retry, or replay behavior.

Tests use an actual SDK MCP client and HTTP mock transport, plus a subprocess
stdio handshake. Run the same unittest command above after installing the project.

## HTTP gateway (#19)

`gateway/app.py` (FastAPI) serves the contract routes; the logic is in
`gateway/service.py`. Run locally: `two-brothers-gateway` (port 8000), with
`VALIO_API_KEY`, `MONGODB_URI`, `GATEWAY_AGENT_TOKEN` and `GATEWAY_HUMAN_TOKEN` set.

The milk flow, end to end:

1. `POST /v1/kitchens/{k}/proposals` with `product_ids`, `quantity`, `unit`,
   `requested_date`, `idempotency_key`: live Valio price and stock, the engine sizes
   every line, a 15-minute offer snapshot is stored, an approval is opened (PENDING).
2. `GET /v1/kitchens/{k}/proposals/{id}`: lines with `why`, `expected_total`, mandate
   reasons and warnings, excluded products, a cheaper alternative if there is one.
3. `POST .../approve` with the `expected_total` the person saw (human token + `X-User`
   only). The gateway re-reads live prices and stock: if anything moved, 409
   `TOTAL_MISMATCH` with the new total, and nothing is placed. Otherwise the attempt is
   written first, then the order (outcome `CONFIRMED`, status `SENT`: placed in our
   gateway; Valio has no order endpoint). A replay returns the same order.
4. `GET .../orders`, `GET .../audit`: the order and every step.

Buyer agent routes: `POST /v1/kitchens/{k}/needs` (the app stores the need), then
`/tools/get_offer` (the model picks products; the gateway sizes them from the need),
`/tools/simulate_order`, `/tools/request_approval`. `/tools/place_order` only returns
an order a person already approved; otherwise 403 `NEEDS_APPROVAL`.

Image: `docker build -f gateway/Dockerfile .` (context is the repo root).
Tests: `python -m pytest gateway/tests/test_gateway_app.py`.

## API tokens (#271)

A person (human session) creates a token for one kitchen:
`POST /v1/kitchens/{k}/tokens {"name": "claude", "scopes": ["kitchen:read", "kitchen:propose"]}`.
The token (`tkb_...`) is returned once; only its SHA-256 is stored. `GET .../tokens` lists
them (prefix, scopes, last used), `DELETE .../tokens/{id}` revokes. `kitchen:approve` is
refused: a token can never approve. A token acts only for its own kitchen (403
`KITCHEN_SCOPE`), and a missing scope gives 403 `SCOPE_REQUIRED`. Create and revoke are
audit entries. A token with `kitchen:propose` can also drive `/mcp`:

    claude mcp add --transport http kitchen-buyer https://<host>/gateway/mcp --header "Authorization: Bearer tkb_..."

## Webhooks (#277)

An approver registers a receiver for one kitchen:
`POST /v1/kitchens/{k}/webhooks {"url": "https://example.com/hook", "events": ["order.placed"]}`.
The answer carries the `secret` (`whsec_...`) once; `GET .../webhooks` never shows it.
`DELETE .../webhooks/{id}` removes the hook and its log. At most 10 hooks per kitchen.
Create and delete are audit entries.

Events: `proposal.ready`, `proposal.approved`, `proposal.rejected`, `order.placed`,
`total_mismatch`, `recall.alert`. They come from the audit trail (`Gateway._audit`), so a
webhook says what the audit log says.

A delivery is a JSON POST: `{"id", "event", "kitchen_id", "at", "data"}` with the headers
`X-TKB-Event`, `X-TKB-Delivery` and `X-TKB-Signature: sha256=<hex>`. The signature is the
HMAC-SHA256 of the raw body with the hook secret. Check it before you trust the body:

    expected = "sha256=" + hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    ok = hmac.compare_digest(expected, request.headers["X-TKB-Signature"])

Any 2xx answer is a success. Otherwise the gateway tries again: at most 3 attempts, 3 seconds
each, with a short backoff. Deliveries run in a background thread; a receiver that is slow or
down never delays or fails an order. `POST .../webhooks/{id}/test` sends one signed `ping`;
`GET .../webhooks/{id}/deliveries` shows the last 50 deliveries (event, attempts, status code,
never a body).

The URL must be `https`. Private, loopback and link-local addresses and internal host names
are refused, at registration and again at delivery time; redirects are not followed. For a
receiver on your own machine set `GATEWAY_WEBHOOKS_DEV=true`: then `http://localhost` and
`http://127.0.0.1` are allowed. Never set it in production.

## Agent discovery (#293)

`GET /.well-known/agent-card.json` (an A2A-style agent card) and `GET /llms.txt` (Markdown
for an LLM) need no token. `gateway/discovery.py` builds both from the running app on every
request: a skill is listed only when its route is registered, the MCP tool names and
descriptions come from the mounted MCP server, the scopes from `gateway/tokens.py`, and the
URLs from the request plus `GATEWAY_PUBLIC_PREFIX` (the prefix the proxy strips: `/gateway`
on the deployed site, set in `deploy/compose.yaml`). The card says plainly that the gateway
does not serve the A2A message protocol; it points at HTTP + JSON and MCP. Caddy serves both
files at the site root too. A token must come in through `/gateway/*`: on `/api/*` the
server replaces the `Authorization` header with the demo person's session.
The copy-paste curl sequence and the MCP client config are in `docs/byoa.md`.
Tests: `gateway/tests/test_discovery.py`.

## Sign-in (#270)

`POST /v1/auth/login {email, password}` sets an httpOnly, SameSite=Strict session cookie
(12 hours; Secure over HTTPS). `GET /v1/me`, `POST /v1/auth/logout`,
`POST /v1/auth/change-password {current_password, new_password}` (10+ characters; ends
every other session). Passwords are scrypt hashes; five wrong tries lock the account for
five minutes; an unknown email and a wrong password give the same answer.

Roles: `approver` approves, rejects and manages tokens; `chef` asks; `viewer` reads
(403 `ROLE_REQUIRED` otherwise). A session is bound to its kitchen.

The first approver comes from the server `.env`: `DEMO_USER_EMAIL`, `DEMO_USER_PASSWORD`.
Set `GATEWAY_REQUIRE_LOGIN=true` to switch off the shared human token: then only a signed-in
person can approve (the open demo stops being open). The Buyer agent token is not affected.

## Conformance kit (#286)

Any agent builder can check a running gateway's trust rules with an agent-level token:

    python -m gateway.conformance --base-url https://<host>/gateway --token <token> [--markdown | --json]

Twelve live checks (no order is placed, no approval is opened): no token no access, the
gateway sizes the order from the stored need and ignores a quantity from the model,
`place_order` without a human approval is refused, an agent token cannot approve, reject
or create tokens, no cancel or edit route exists, a kitchen token cannot read another
kitchen, the MCP server exposes no approve tool. Exit code 1 on any FAIL. The offline
golden scenarios S01-S13 are `python -m gateway.scenarios`.
## Standing-order drift (#377)

`gateway/drift_routes.py` serves the two contract routes from `store.drift`:

- `GET /v1/kitchens/{k}/drift` (`kitchen:read`): `{"week": "<Monday>", "warnings": [...]}`,
  biggest change first. `week` is the Monday of the last full week, also with no warnings.
  A warning carries `product_name` when the catalog knows the product.
- `GET /v1/suppliers/{s}/demand/drift` (`supplier:demand`): the same shape over every
  kitchen whose consent names the supplier, each warning with `kitchen_id` and
  `kitchen_name`. A kitchen without active consent is never read. No token can hold
  `supplier:demand` yet, so today only a person's session reaches this route.
- A database failure is 503 `DRIFT_UNAVAILABLE`, without the driver's message.

The aggregation needs Atlas or MongoDB 7; the tests replace it
(`gateway/tests/test_drift_routes.py`).

## Trust routes (#711)

`gateway/trust_routes.py` serves the four contract routes over `store.trust`
(docs/contract.md, "Trust: audit verification and the live event stream"):

- `GET /v1/kitchens/{k}/audit/verify` (`kitchen:read`): the chain check.
- `GET /v1/kitchens/{k}/audit/chain?limit=` (`kitchen:read`): this kitchen's newest entries
  (1 to 100, default 20), oldest first, each `{seq, prev_hash, hash, event}`; `event` is the
  `GET /audit` entry. The Trust screen shows these lines.
- `POST /v1/kitchens/{k}/audit/demo-tamper` and `.../audit/demo-restore`: a person with
  the role `approver`, the synthetic `demo-kitchen` only (403 `DEMO_ONLY` otherwise). Each
  one that changes a row writes an audit entry (`audit_demo_tamper`, `audit_demo_restore`)
  with the person and `tampered_seq`. That entry is also the replay store: the same
  `idempotency_key` answers the stored result.
- `GET /v1/kitchens/{k}/events` (`kitchen:read`): server-sent events, one MongoDB change
  stream per connection. `: connected` at once, `: ping` after 5 s without a message.
  The stream ends after 10 minutes (the client connects again) and at most 16 are open
  per gateway process. The change stream is closed when the client leaves.
- A change stream needs a replica set (Atlas has one). On a standalone MongoDB, and when
  16 streams are open, the answer is 503 `EVENTS_UNAVAILABLE`.
- Caddy needs no setting: `reverse_proxy` flushes a `text/event-stream` at once, also with
  `encode` on (checked with caddy:2 in front of a local gateway).

Local check with a real change stream:
`docker run -d --rm -p 27047:27017 mongo:7 --replSet rs0`, `rs.initiate()` in `mongosh`,
then `MONGODB_URI=mongodb://localhost:27047/?directConnection=true`.

## Earned auto-approve (#299)

Off by default. `GET /v1/kitchens/{k}/auto-approve` shows the setting and the learning
progress (weeks, human decisions, edit rate). `PUT` with `{"enabled": true, "limit_eur": "500"}`
works only for an approver and only after the learning period: 4 weeks, 20 human decisions,
at most 10% of approved proposals edited (409 `LEARNING_PERIOD` before that; limit at most
2,000 EUR). Then a routine proposal is approved without waiting: total under the limit, no
warning, confirmed stock on every line, nothing excluded or short, and every product already
on 3 human-approved, unedited orders. Substitutes, unknown stock, allergen or cut-off issues,
recalls, events and new products always wait for a person. The order is recorded as
`auto-approve (rule set by <person>)`, the audit entry `auto_approved` carries the evidence,
and the same live re-check applies (a moved price still refuses). Auto-approvals never count
as learning. `{"enabled": false}` switches it off at once.
## Onboarding lookup (#375)

`POST /v1/onboarding/lookup` with `{"email": ...}` or `{"website": ...}` (a person's
session only; 403 `HUMAN_SESSION_REQUIRED` for the agent and API tokens). `gateway/onboarding.py`
makes one Context.dev call, `POST /v1/brand/retrieve` (`by_email` / `by_domain`), and
returns `domain`, `found` and `name`, `logo_url`, `colors`, `address`, `kitchen_type`,
`opening_hours`, each as `{value, source}`. An unknown field is `null`, never a guess.

- `CONTEXT_DEV_API_KEY` comes from the server environment and is sent only as the bearer
  header to Context.dev. It is never logged or returned. Without it: 502.
- The gateway never fetches the address the person typed: it checks that it is an email
  or a public domain name and passes only that to Context.dev.
- 422 `FREE_EMAIL` (free or disposable mailbox), 422 `INVALID_QUERY`, 502
  `LOOKUP_UNAVAILABLE` (down, slow, out of credits, no key), 200 `found: false` when
  Context.dev does not know the domain. Nothing is saved, nothing is cached.
- `opening_hours` is always `null` for now: the optional scrape call is not made.
- Each lookup costs Context.dev credits (10 for the recorded call).

Tests replace the HTTP call and use one recorded, trimmed answer
(`gateway/tests/fixtures/context_brand_retrieve.json`): `gateway/tests/test_onboarding.py`.

## Several suppliers in one proposal (#73)

`gateway/suppliers.py` holds one adapter per supplier kind. Each gives the engine the
same thing: `offers(product_ids, measure, requested_date) -> (offers, skipped, tax)`.

- `ValioAdapter`: live Valio price and availability (the logic that was in `Gateway._offers`).
- `ManualAdapter`: a supplier with adapter `manual` or `csv`. Its price list is the
  kitchen's own products for that supplier (`unit_price_eur`, `pack_size_in_base_units`).
  Stock is always unknown, so every line has `unknown_stock: true`. The cut-off comes
  from the supplier's terms: the next order day whose `cutoff_time` is still ahead, plus
  `lead_time_days`, must reach the requested date. If it cannot, the product is excluded
  ("order cut-off has passed"). If one of the three terms is unknown, it is excluded too
  ("no cut-off time known").

A request may name products of several suppliers. A catalog product belongs to
`sup-valio`; an own product belongs to its `supplier_id`. The engine plans the whole
request as before. The simulation then also returns `blocks`, one per supplier that has
a line:

```json
{"supplier_id": "sup-bakery", "name": "Leipomo Demo", "lines": [],
 "total_ex_vat": "58.80", "vat": null, "mov_gap": "41.20", "delivery_fee": "9.50",
 "expected_total": "68.30"}
```

- `mov_gap` and `delivery_fee` come from that supplier's user-set terms. An unknown term
  gives `null`, never zero. `vat` is `null` for an own product (no VAT rate is stored).
- The top-level `expected_total` is the sum of the block totals. The top-level `mov_gap`
  and `delivery_fee` are those of the block when there is one supplier, and `null` when
  there are several.
- `discount_tiers`: the tier with the highest `min_qty` at or below the line quantity, in
  the line's unit, sets the unit price. The line's `why` names the tier.
- Approve is still one human yes and one order; the order stores `blocks`. A line with
  unknown stock still returns 409 `STOCK_UNKNOWN`, so a block of a manual supplier cannot
  be placed until a supplier confirmation exists.

## Recall list and "check now" (#358)

`gateway/recalls_view.py` serves `GET /v1/kitchens/{k}/recalls` (`kitchen:read`) and
`POST /v1/kitchens/{k}/recalls/check` (`kitchen:write`: a person who is not a viewer; body
`idempotency_key`). Both answer `{"last_check": ..., "alerts": [...]}`; the shape is in
`docs/contract.md`, "Recall alerts (Context.dev)", the alert fields in `docs/recall-contract.md`.

- Views only: the match is `monitor.recalls.scan`, the hold and the replacement proposal are
  `monitor.proposals.apply_notices`, the alerts are the rows of `store.recalls`.
- A check makes one Context.dev call (the Ruokavirasto list, one attempt,
  `RECALL_CHECK_TIMEOUT_S`, default 45 s). No key, slow, down or a wrong answer: it uses the
  recording `monitor/fixtures/ruokavirasto.json` and says `source: "recording"` with the
  reason in `live_error`. The notice pages always come from the recording; a live list
  counts the notices it has not read (`notices_unread`).
- The `recall_check` audit entry is also the idempotency record: a repeat key scrapes and
  applies nothing. A check never orders, approves or cancels.
- Demo: `python -m demo.recall_demo` makes the open coffee proposal the check blocks.

## Kitchen planning routes (#74)

`gateway/kitchen_routes.py`, all under `/v1/kitchens/{k}`:

| Route | Who | What |
|---|---|---|
| `GET/POST /suppliers`, `GET/PUT/DELETE /suppliers/{id}` | read / write | Suppliers and their user-set terms (null = unknown) |
| `GET/POST /recipes`, `GET/PUT/DELETE /recipes/{id}` | read / write | Ingredients with `qty_per_portion`, `unit`, `yield_pct` |
| `GET/POST /products`, `GET/PUT/DELETE /products/{id}` | read / write | The kitchen's own products |
| `GET/PUT /menu-plans/{YYYY-Www}` | read / write | `days: [{date, meal, recipe_id, covers}]`; an empty week returns `days: []` |
| `POST /stock-counts`, `GET /stock` | write / read | A null count is "not counted", never zero; replay by `idempotency_key` |
| `GET /demand?from=&to=` | read | Per product and day: `gross_need` (covers x recipe / yield), `net_need` (null when stock is unknown), `why`, `source` (`menu_plan`, else the stored forecast: `history`), plus `problems` |
| `GET/PUT /settings` | read / approver | Engine settings; decimals as strings |
| `GET/PUT /sharing` | read / approver | `{supplier_id, share_forecast}`; each change is an audit entry |

"write" = a signed-in person who is not a viewer, or an API token with the new scope
`kitchen:write` (a POS or stock system). The Buyer agent token cannot write. `on_order` is
0 with `on_order_known: false` until open orders are converted to kitchen units.

## Supplier demand view (#33)

`GET /v1/suppliers/{supplier_id}/demand?from=&to=[&product=]` and
`GET .../demand/shortage-risk?from=&to=` (at most 14 days). Per product and day: the forecast
`demand` summed over the kitchens whose consent names this supplier (`kitchens`, `by_kitchen`),
the supplier's live `available` in kitchen units (null when unknown), `shortage`, `risk`
(`OK`, `SHORT`, `UNKNOWN`) and `suggested_buy`. A kitchen without active consent is in no sum
and no list. The Buyer agent token cannot read it (403).

## Signed offers (#290)

Every offer and proposal carries `signature` (a JWS, EdDSA) and `offer_hash`. The signed
claims: offer id, kitchen, delivery date, as-of and valid-until times, each line (product,
quantity, unit, unit price, `stock: confirmed | unknown`), the total and the `offer_hash`.
The public key is at `/.well-known/jwks.json` (no token). Check one offer:

    python -m gateway.verify_offer --base-url https://<host>/gateway --offer offer.json

A changed line, price or total, another key or an expired offer fails (exit code 1). The
approved order stores the `offer_hash`; `place_order` for any other offer is 409
`APPROVAL_MISMATCH`. The key comes from `GATEWAY_SIGNING_KEY` (base64 of 32 bytes) or is
created once and kept in the database. A signed JWT mandate is the next step, not in this PR.

## An order for the menu plan (#74)

`POST /v1/kitchens/{k}/proposals` with `{"from": "2026-11-16", "to": "2026-11-22",
"requested_date": "2026-11-16", "idempotency_key": "..."}` (no products, no text) proposes
one order for everything the menu plan needs in that window, net of counted stock. Each
product is sized by the engine for its own need and measure; the proposal has one total, the
supplier blocks, one approval. `request.needs` lists the need per product (`stock_counted:
false` when the stock was never counted: then the full need is proposed, not a guess);
`shortfalls` lists what cannot be covered per product; 422 `NOTHING_NEEDED` when stock covers
the plan. Approve, reject, signing and the live re-check work as for any proposal.
