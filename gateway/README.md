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
