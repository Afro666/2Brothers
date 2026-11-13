# Contract between areas

## Valio upstream API

Source: the authenticated [Valio event portal](https://junction26.valioaimo.fi/)
and its `/openapi.json`, retrieved 2026-11-13. Local reference files live in
`vendor/valio/` and are excluded from Git locally. These are challenge datasets;
the portal says they must not be used outside this challenge.

Base URL: `https://junction26.valioaimo.fi`.
Every `/api` request requires `X-API-Key`, loaded server-side from
`VALIO_API_KEY`. `VALIO_PORTAL_PASSWORD` authenticates the resource portal,
not API requests. Never send either credential to the frontend or put it in logs.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/ping` | API connectivity check |
| POST | `/api/price` | Prices for selected products and delivery date |
| POST | `/api/availability` | Availability for selected products and delivery date |
| GET | `/api/products/download` | Product data download link |
| GET | `/api/delivery-reliability/download` | Reliability data download link |
| GET | `/api/carbon-footprint/download` | Carbon data download link |

The upstream specification has no order-placement endpoint. Any order simulation,
approval, or placement implemented by our gateway is a team-owned interface and
must not be described as an upstream order submission.

### Shared price and availability request

```json
{
  "customer": "123",
  "requestedDate": "2026-11-16",
  "products": ["460013", "460063"]
}
```

All three fields are required. `customer` and product codes are strings;
`requestedDate` is a date in `YYYY-MM-DD` format. Send between 1 and 1,000
product codes per request. Invalid requests return HTTP 422 with validation
details. Query only needed products and split larger lists into bounded chunks.
Customer identity does not affect this challenge's results, although real prices
and availability are customer-specific.

### Price response

Top-level required fields: `customerId`, `currency`, `pricingDate`, `products`.
Each product requires `productId`, `quantity`, `netPriceFound`, and `error`.
Optional pricing fields may be absent or null; do not treat these as zero prices.

- `quantity` is always 1.0 in the challenge.
- `catalogPrice` contains `value` before tax, `valueWithTax`, `currency`,
  `validFrom`, and `validTo`.
- `priceWithTax` contains the tax-inclusive `value`, currency, and validity dates.
- `comparisonPrice` has the same fields as `catalogPrice`; `comparisonUnit`
  is KG or L and supports comparison between different pack sizes.
- `tax` contains `taxRate` in percent and `taxValue` in the currency.
- `listPrice` is the price before a customer-specific price or discount.
- `netPriceFound` identifies customer-specific net pricing versus catalog pricing.
- `error: true` means no price was found for that product, even in an HTTP 200
  response. Check per-product errors before calculating totals.

### Availability response

Top-level required fields: `timeNow`, `requestedDate`, `products`.
`timeNow` is server time in Helsinki; `requestedDate` is the requested date at
midnight. Product entries are returned in request order, but join on `productId`.
Each entry requires `productId`, `salesBlock`, and `scheduleLines`;
`closingTime` and `logisticModel` may be absent or null.

- `closingTime` is the order cut-off for delivery on `availableDate`.
  If `closingTime` is at or before now, that delivery cannot be fulfilled even
  when `availableDate` matches the request. Interpret timestamps in Helsinki.
- A product-level or schedule-level `salesBlock: true` means it cannot be ordered.
- `scheduleLines` is empty when the product cannot currently be delivered on any
  date; otherwise the challenge returns exactly one line.
- A line requires `salesBlock`, `availableAmount`, and `salesUnit`.
  `availableDate` may be absent or null. Its value is the earliest available date
  and can differ from the requested date.
- `availableAmount` is expressed in `salesUnit`. Zero means unavailable.
- Both `999999` and `9999999999` are unknown-stock sentinels for any product type,
  including Terminal and Stock. Neither is a measured quantity. Missing or null
  stock also means unknown, not zero.

#### Gateway availability normalization

The raw Valio API above does not provide the following derived flags. The gateway
adapter normalizes each schedule line with a sentinel, missing or null amount to
`availableAmount: null`, `unknown_stock: true`, and `orderable: false`. This rule
applies to both Terminal and Stock products even when their cutoff is in the
future. Measured zero remains zero: unavailable, but not unknown.

The adapter retains these products and schedule lines. UI and agent consumers
must keep them visible in proposals, labelled as unconfirmed stock, rather than
hide them because `orderable` is false. `orderable` describes confirmed upstream
fulfilment for the requested deadline; it is not permission to show a proposal
or consent to place an order. Supplier availability must be confirmed before
placement; human approval alone does not confirm stock. Cutoff, delivery-date,
sales-block and other refusal guards still apply. A true flag likewise does not
bypass the required human approval or the gateway's placement checks.

### Static datasets

| File | Meaning |
|---|---|
| `valio_aimo_junction26_product_data.json` | Product catalog and product codes |
| `valio_aimo_junction26_product_data_schema.json` | JSON Schema for the catalog |
| `valio_aimo_junction26_delivery_reliability.csv` | Historical delivered-versus-ordered ratio, between 0 and 1 |
| `valio_aimo_junction26_carbon_footprint.csv` | Product-group average in `AVG kg CO2-eq/kg` |

Join these datasets by product code, preserving codes as strings. Reliability and
carbon values do not exist for every product; missing values mean unknown.
Carbon values estimate a product group's footprint, not an individual product's
measurement. Nutrition and allergen completeness varies; missing information
must not be interpreted as evidence that an allergen is absent.

## Team gateway interfaces

These are team-owned HTTP interfaces, not Valio endpoints. The MCP adapter uses
the gateway at `GATEWAY_BASE_URL` (default `http://127.0.0.1:8000`). Until the
gateway implementation lands, integration tests use an in-process mock HTTP
transport implementing this contract. Production deployment must restrict access
to trusted server processes; these routes must not be exposed publicly without
gateway authentication and tenant authorization. Never send Valio keys here.

All request and response bodies are JSON objects. Errors use an HTTP 4xx/5xx
status and `{"error": {"code": "TOTAL_MISMATCH", "message": "..."}}`.
IDs are opaque strings. Currency amounts are decimal strings in EUR, never
binary floats. Timestamps use ISO 8601 with an offset. The gateway validates every
input, mandate and authenticated kitchen; model arguments are untrusted.

| MCP tool | Method and path | Request / query fields | Success response fields |
|---|---|---|---|
| `search_products` | POST `/tools/search_products` | `query: string`, `filters: object` | `products: object[]` |
| `get_offer` | POST `/tools/get_offer` | `product_ids: string[]`, `requested_date: YYYY-MM-DD`, `need_id: string` | `offer_id`, `valid_until`, `lines: object[]` |
| `simulate_order` | POST `/tools/simulate_order` | `offer_id: string` | `offer_id`, `expected_total`, `currency`, `mandate: object`, `lines: object[]` |
| `place_order` | POST `/tools/place_order` | `offer_id`, `expected_total: decimal string`, `idempotency_key` | `order_id`, `outcome`, `status` |
| `request_approval` | POST `/tools/request_approval` | `offer_id: string` | `approval_id`, `status: PENDING` |
| `get_order_status` | GET `/tools/get_order_status` | `order_id: string` | `order_id`, `status`, `outcome` |
| `get_audit_log` | GET `/tools/get_audit_log` | `run_id: string` | `events: object[]` |

The trusted application/engine creates `need_id` before invoking the buyer agent.
The gateway loads quantities from that stored need; neither `get_offer` nor
`simulate_order` accepts quantities invented by the model. Offer lines include
`product_id`, `quantity`, `unit`, `why`, `available_date`, `unknown_stock` and
`cutoff_passed`. Unknown stock is never represented as a measured sentinel value.
`expected_total` includes fees and tax. Simulation also includes `mov_gap` and
`delivery_fee` as decimal strings. Expired offers must be refreshed and simulated.

`mandate.verdict` is exactly `AUTO`, `NEEDS_APPROVAL`, or `REFUSED`;
`mandate.reasons` is a list of human-readable strings. For example, the milk case:

```json
{
  "offer_id": "milk-offer-1",
  "expected_total": "149.02",
  "currency": "EUR",
  "mov_gap": "0.00",
  "delivery_fee": "0.00",
  "mandate": {
    "verdict": "NEEDS_APPROVAL",
    "reasons": ["Only 51 L is confirmed for Monday; the remaining stock is unknown."]
  },
  "lines": [{
    "product_id": "462775", "quantity": "51", "unit": "ST",
    "why": "51 one-litre units confirmed; the full 1,000 L request cannot be met.",
    "available_date": "2026-11-16", "unknown_stock": false, "cutoff_passed": false
  }]
}
```

This example is a deterministic mock scenario, not a live quote or a complete
fulfilment. The agent requests approval and reports a pending decision. It never
claims the full milk request was fulfilled.

`place_order` independently enforces the mandate and recorded human approval,
offer validity, unchanged total (tolerance EUR 0.005), and stock/cutoff guards.
It persists an attempt and payload hash before any commit. The agent cannot
approve, cancel, release, or bypass an order. A requested approval remains pending
until an authorized human acts through the approval UI, outside these tools.

`outcome` is `CONFIRMED`, `NOT_SENT`, `UNCONFIRMED` or `SENT_READ_FAILED`.
Only `CONFIRMED` means an order is known to have been placed in our gateway.
`NOT_SENT` may be retried explicitly; the other failure outcomes require status
reconciliation or human intervention. All mutation requests carry stable
idempotency keys; `request_approval` uses `Idempotency-Key` in its HTTP header,
while `place_order` carries it in the JSON body. Replays return the stored result;
key reuse with a different payload is rejected. Adapters never automatically
retry either mutation after an ambiguous transport failure.

### Agent audit ingestion

POST `/audit/events` accepts `event_id`, `run_id`, `type`, `tool`, `arguments`,
and `result` (JSON object fields). Types are `tool_call_started` and
`tool_call_finished`. `event_id` is an idempotency key: exact replays do not append
twice; different content under the same key is rejected. The gateway adds its own
timestamp, authenticated principal and kitchen scope, and returns
`{"event_id": "...", "stored": true}` only after durable storage through the
shared repository module. Never accept the model's identity or timestamp as fact.

The buyer records a start event before dispatch and a finish event after every
attempt, including errors. Audit failure stops the agent; no new tool is called.
If finish logging fails after a mutation, the final result must flag human
reconciliation rather than repeat the mutation. Arguments/results contain only
allowlisted tool fields: no credentials, authorization headers or raw HTTP error
bodies. Local traces supplement durable gateway audit; they do not replace it.
