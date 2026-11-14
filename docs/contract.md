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
- A line requires `salesBlock` and `salesUnit`. `availableAmount` may be absent
  or null: that is unknown stock (see the sentinel rule below), never zero.
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
| `search_products` | POST `/tools/search_products` | `query: string`, `filters: object`, `limit: integer` (see below) | `products: object[]` |
| `get_offer` | POST `/tools/get_offer` | `product_ids: string[]`, `requested_date: YYYY-MM-DD`, `need_id: string` | `offer_id`, `valid_until`, `lines: object[]` |
| `simulate_order` | POST `/tools/simulate_order` | `offer_id: string` | `offer_id`, `expected_total`, `currency`, `mandate: object`, `lines: object[]` |
| `place_order` | POST `/tools/place_order` | `offer_id`, `expected_total: decimal string`, `idempotency_key: string` | `order_id`, `outcome`, `status` |
| `request_approval` | POST `/tools/request_approval` | `offer_id: string`, `idempotency_key: string` | `approval_id`, `status: PENDING` |
| `get_order_status` | GET `/tools/get_order_status` | `order_id: string` | `order_id`, `status`, `outcome` |
| `get_audit_log` | GET `/tools/get_audit_log` | `run_id: string` | `events: object[]` |

**Remote MCP (#280).** The same seven tools are also served over MCP streamable HTTP at
`POST /mcp` (stateless, JSON responses), same names, arguments and results as above.
Only the agent bearer token (`Authorization: Bearer <agent token>`) is accepted; any
other caller, the human token included, gets `401 UNAUTHENTICATED` with
`WWW-Authenticate: Bearer`. Each call runs the `/tools/*` route above with the agent
principal, so every refusal and audit entry is the same. There is no approve, reject or
cancel tool.

The trusted application/engine creates `need_id` before invoking the buyer agent.
The gateway loads quantities from that stored need; neither `get_offer` nor
`simulate_order` accepts quantities invented by the model. Offer lines include
`product_id`, `quantity`, `unit`, `why`, `available_date`, `unknown_stock` and
`cutoff_passed`. Unknown stock is never represented as a measured sentinel value.
`expected_total` includes fees and tax. Simulation also includes `mov_gap` and
`delivery_fee` as decimal strings. Expired offers must be refreshed and simulated.

**Decision record (#282).** Every proposal (list and detail) carries
`decision_summary`: `asked` (string), `searched` (string), `chosen` (string[]),
`left_out` (string[]), `totals` (string), `decide` (string[]) and `text` (all of it, one
line per part). It is built from the stored request and simulation only; every number in
it is the gateway's own string, never recomputed. Each new proposal also writes an audit
event with `kind: "decision_summary"`, `proposal_id`, `offer_id` and `summary` (= `text`).

`mandate.verdict` is exactly `NEEDS_APPROVAL` or `REFUSED`. There is no `AUTO`
verdict: the Buyer proposes and a human approves every order (decision 2026-11-13
23:00). `REFUSED` is only for a hard rule (an allergen rule, a passed cut-off, a sales
block, a product outside the kitchen's suppliers). `mandate.reasons` is a list of
human-readable strings; `mandate.reason_codes` and `mandate.warnings` use the codes in
"Reason codes" below. A warning (for example `OVER_BUDGET_WARNING`) is shown on the
approval card; it never blocks and never approves. For example, the milk case:

```json
{
  "offer_id": "milk-offer-1",
  "expected_total": "149.02",
  "currency": "EUR",
  "mov_gap": "0.00",
  "delivery_fee": "0.00",
  "mandate": {
    "verdict": "NEEDS_APPROVAL",
    "reasons": ["Only 51 L is available for Monday; the full 1,000 L request cannot be met."],
    "reason_codes": ["PARTIAL_STOCK"],
    "warnings": []
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

`place_order` independently enforces the mandate and a recorded human approval
(always required),
offer validity, unchanged total (tolerance EUR 0.005), and stock/cutoff guards.
It persists an attempt and payload hash before any commit. The agent cannot
approve, cancel, release, or bypass an order. A requested approval remains pending
until an authorized human acts through the approval UI, outside these tools.

`outcome` is `CONFIRMED`, `NOT_SENT`, `UNCONFIRMED` or `SENT_READ_FAILED`.
Only `CONFIRMED` means an order is known to have been placed in our gateway.
`NOT_SENT` may be retried explicitly; the other failure outcomes require status
reconciliation or human intervention. All mutation requests carry stable
idempotency keys: both `request_approval` and `place_order` require a nonempty
`idempotency_key` string in the JSON body, scoped to the authenticated kitchen
and operation. The `Idempotency-Key` HTTP header is not a supported alternative.
The approval adapter generates this field; it is not an extra model argument.
Replays return the stored result;
key reuse with a different payload is rejected. Adapters never automatically
retry either mutation after an ambiguous transport failure.

### `search_products`: filters and the product row

Request: `query` (string, may be empty when a filter is set) and `filters`
(object, every field optional). `limit` (integer, default 20, maximum 50) is a
third top-level field.

| Filter | Type | Meaning |
|---|---|---|
| `exclude_allergens` | string[] | Allergen names or GS1 codes, for example `"milk"` or `"AM"`. Removes every product that lists one of them as CONTAINS or MAY_CONTAIN. |
| `allergen_strictness` | `"declared"` (default) or `"strict"` | `declared` keeps products without allergen data and marks them unknown. `strict` also removes them, and removes products that list an excluded allergen as `undeclared`. |
| `require_labels` | string[] | Label ids such as `EU_ORGANIC_FARMING`; the product must carry all of them. |
| `temperature` | `"ambient"`, `"chilled"` or `"frozen"` | Storage class. |
| `category` | string | The 5-character category code. |
| `pack_size` | `{value: number, unit}` | Net content of one base unit; `unit` is `L`, `DL`, `CL`, `ML`, `KG` or `G` (upper or lower case is accepted). A hard filter. |
| `supplier_id` | string | Only this supplier's products. |

Allergen names are the 14 EU allergens: `gluten` (AW), `crustaceans` (AC), `eggs`
(AE), `fish` (AF), `peanuts` (AP), `soy` (AY), `milk` (AM), `nuts` (AN), `celery`
(BC), `mustard` (BM), `sesame` (AS), `sulphites` (AU), `lupin` (NL), `molluscs`
(UM); plus `lactose` (ML), `wheat` (UW) and `oats` (GO). `gluten` also covers the
wheat, rye, barley, spelt and kamut codes, and `nuts` the single-nut codes. `gluten`
does not cover oats: gluten-free oats exist. An unknown name is a 422, never ignored.

When `pack_size` is absent, a size written in the query ("milk 1 l", "500 g") is
read from the text and only raises the rank of products with that size.

The search covers the supplier catalogs and the authenticated kitchen's own products.
It never returns another kitchen's own products. The kitchen comes from the
authenticated caller, never from a request field.

Response: `products`, best match first. Each row is the product row below plus
`score` (number) and `match_reasons` (short strings, for example `"size 1 L matches"`,
`"allergen data missing"`, `"size read from the name"`).

Product row (the catalog row from the shared repository, without the raw record):

| Field | Type | Notes |
|---|---|---|
| `product_id` | string | Product code. Always a string. |
| `source`, `supplier_id` | string | `source` is `valio`, `csv` or `own`. |
| `kitchen_id` | string | Only on `own` rows: the kitchen the product belongs to. |
| `unit_price_eur` | decimal string or null | Only on `own` rows: the price the kitchen entered. Catalog prices come from `get_offer`. |
| `names` | `{en?, fi?, sv?}` | For Valio products `fi` is always there; `sv` is missing on 8%. An own product has one entered name, repeated under all three. |
| `brand` | string or null | Null on 18% of the Valio catalog. |
| `category` | string | A 5-character code. The data has no category names: the UI shows the code. |
| `vendor`, `country` | string or null | `country` is a lower-case ISO alpha-2 code. |
| `base_unit`, `sales_unit` | string | Valio unit codes: `ST` piece, `KI` case, `KG`. |
| `units` | `{unit, size_in_base_units, gtin}[]` | Pack hierarchy, in base units. |
| `lot_size` | number or null | Order in multiples of this many sales units; null means no rule. |
| `net_content` | `{value, unit}` or null | Of one base unit, in `L` or `KG` (see "Units" below). A case of 12 x 1 L is 1 L. |
| `net_content_source` | string or null | `synkka` (measured piece), `synkka_case` (measured case, divided), `base_unit` (sold by weight), `entered` (typed in by the kitchen for an own product), `name` (read from the product name: a guess, verify before relying on it). |
| `allergens` | `{contains, may_contain, undeclared}` | Lists of GS1 codes. `undeclared` is the supplier's "not declared" level; it is not a free-from claim. |
| `allergen_data_known` | boolean | False on 46% of the Valio catalog. False means unknown: show "unknown", never "none". |
| `no_declarable_allergens` | boolean | The supplier states that no declarable allergen is present. |
| `free_from` | string[] | GS1 codes the supplier claims the product is free from. |
| `claims` | string[] | For example `FREE_FROM_LACTOSE`, `VEGAN`, `LOW_LACTOSE`. |
| `lactose_free` | boolean | A lactose-free claim and no lactose listed. Lactose-free milk still contains milk (`AM`). |
| `labels` | string[] | For example `GOODS_FROM_FINLAND_BLUE_SWAN`, `EU_ORGANIC_FARMING`. |
| `temperature` | string or null | `ambient`, `chilled`, `frozen`; null when unknown. |
| `reliability` | number or null | Delivered versus ordered, 0 to 1. |
| `carbon_kg_co2e_per_kg` | number or null | Product-group average, not this product's own figure. |
| `substitutions` | string[] | Product codes Valio suggests. A kitchen's allergen rule still wins. |

The contract is snake_case. The web client maps these rows to its own camelCase
types in `web/src/api/`.

### Stored rows: order, approval, audit entry

What the shared repository keeps, and what list and detail routes return. Money
and quantities are decimal strings on the wire.

- **Order:** `order_id`, `kitchen_id`, `offer_id`, `idempotency_key`, `expected_total`,
  `lines`, `payload_hash`, `status`, `outcome`, `created_at`, `updated_at`. The row is
  written before any send, with `status` and `outcome` null; both are set when the
  attempt ends.
- **Approval:** `approval_id`, `kitchen_id`, `offer_id`, `idempotency_key`, `status`
  (`PENDING`, `APPROVED`, `REJECTED`), `reasons` (string[]), `requested_at`,
  `decided_by`, `decided_at`, and `reason` on a rejection. Decided once, by a human.
- **Audit entry:** `seq` (1, 2, 3 ...), `prev_hash`, `hash`, `stored_at`, `event` (what
  the client sent: `event_id`, `run_id`, `type`, `tool`, `arguments`, `result`, and
  `order_id` when the event belongs to an order) and `server` (what the gateway adds:
  `kitchen_id`, `principal`, its own timestamp). `hash` covers the whole entry and
  the previous entry's hash, so a changed or removed entry is detectable.

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

## Product API: kitchens and suppliers

Moved from `docs/api.md` (agreed 2026-11-13). One REST API (OpenAPI) and the MCP
server for the Buyer agent; both call the same gateway code. The rules in "Team
gateway interfaces" (JSON bodies, error shape, decimal-string EUR, ISO 8601, opaque
IDs) apply here too. Base path: `/v1`.

### Auth and the trust rule

- Every organisation (kitchen or supplier) gets API keys with scopes.
- Scopes: `kitchen:read`, `kitchen:write` (stock, menus, products, suppliers),
  `kitchen:propose`, `kitchen:approve`, `supplier:read-orders`, `supplier:confirm`,
  `supplier:demand`.
- **`kitchen:approve` is only on a human user session.** No API key and no agent MCP
  token can hold it. The Buyer proposes; it never approves. A call to approve or reject
  without a human session returns 403 `HUMAN_SESSION_REQUIRED`.
- Every mutation (POST, PUT, DELETE) carries a nonempty `idempotency_key` string in
  the JSON body, scoped to the organisation and the route. The same rules as the
  gateway tools apply: a replay returns the stored result, reuse with a different
  payload returns 409 `IDEMPOTENCY_KEY_REUSED`, no header alternative.
- Every call is in the audit log: who (user, API key or agent), what, when, and the
  figure that was shown.

### Kitchen side: `/v1/kitchens/{kitchen_id}/...`

| Method | Path | Scope | What |
|---|---|---|---|
| POST | `/stock-counts` | `kitchen:write` | Push a stock count (POS, inventory, manual). `null` means unknown, never zero. |
| GET | `/stock` | `kitchen:read` | Current stock and position (on hand + on order). |
| GET | `/products`, `/products/{id}` | `kitchen:read` | Own products (not in a supplier catalog). Shape below. |
| POST, PUT, DELETE | `/products`, `/products/{id}` | `kitchen:write` | Create, change or delete an own product. |
| GET | `/catalog/products?ids=` | `kitchen:read` | Product rows by code, for screens that hold product codes (recipes, orders). `ids` is 1 to 200 codes, comma-separated. Returns `{"products": [...]}` in the order asked, each in the product row shape of `search_products` (no `score`, no `match_reasons`). Covers the supplier catalogs and this kitchen's own products, never another kitchen's. A code that is not found is left out; it is not an error. Proposed; the gateway does not serve it yet. |
| GET | `/recipes`, `/recipes/{id}` | `kitchen:read` | Recipe = products x quantity per portion, with yield; allergens rolled up. |
| POST, PUT, DELETE | `/recipes`, `/recipes/{id}` | `kitchen:write` | Create, change or delete a recipe. |
| GET | `/menu-plans/{week}` | `kitchen:read` | The week's menu plan (shape below). |
| PUT | `/menu-plans/{week}` | `kitchen:write` | Menus per day: recipe + expected covers. `week` is ISO `YYYY-Www`. |
| GET | `/demand?from=&to=` | `kitchen:read` | Future need per product and day, from the menu plan and history. |
| GET | `/suppliers`, `/suppliers/{id}` | `kitchen:read` | Suppliers and their terms: free-delivery threshold, fee, order days, cut-off, lead time, discount tiers. User-set; demo values are placeholders. |
| POST, PUT, DELETE | `/suppliers`, `/suppliers/{id}` | `kitchen:write` | Create, change or delete a supplier and its terms. |
| POST | `/proposals` | `kitchen:propose` | Ask the Buyer: free text ("1,000 L milk by Monday") or a demand window `from`/`to`. Returns `proposal_id`, `status: PENDING`. |
| GET | `/proposals/{id}` | `kitchen:read` | Lines with `why`, one block per supplier, simulated totals (`expected_total`, `mov_gap`, `delivery_fee`), mandate reasons, warnings. |
| POST | `/proposals/{id}/approve` | `kitchen:approve` (human) | Body: `blocks: [{supplier_id, expected_total}]` + `idempotency_key`. A total that moved returns 409 `TOTAL_MISMATCH`; nothing is sent. |
| POST | `/proposals/{id}/reject` | `kitchen:approve` (human) | Body: `reason` (string) + `idempotency_key`. The reason feeds the engine and `env/`. |
| GET | `/orders`, `/orders/{id}` | `kitchen:read` | Order `status` and the gateway `outcome` (below). |
| GET | `/sharing` | `kitchen:read` | The kitchen's consent records (shape below). |
| PUT | `/sharing` | `kitchen:write` | Consent: which suppliers may see this kitchen's forecast. Every change is an audit entry. |
| GET | `/settings` | `kitchen:read` | Kitchen settings: how the engine sizes orders and what the Buyer may propose. Shape below. |
| PUT | `/settings` | `kitchen:write` (human) | Change settings. Only the fields in the body change. Every change is an audit entry. Proposed; the gateway does not serve these two routes yet. |
| GET | `/audit` | `kitchen:read` | Every step: who, what, when, the figure shown. |
| GET | `/audit/verify` | `kitchen:read` | Check the audit hash chain now. Shape below. Proposed, like the next three rows; the gateway does not serve them yet. |
| POST | `/audit/demo-tamper` | `kitchen:approve` (human) | Demo only: edit one audit row of the synthetic demo kitchen, so `/audit/verify` shows the break. 403 `DEMO_ONLY` for any other kitchen. |
| POST | `/audit/demo-restore` | `kitchen:approve` (human) | Demo only: put the tampered row back exactly as it was. |
| GET | `/events` | `kitchen:read` | Server-sent events: this kitchen's new and changed proposals, approvals and audit entries, as they happen. Shape below. |

Proposal `status`: `PENDING`, `READY`, `APPROVED`, `REJECTED`, `EXPIRED`. An approved
proposal places one order per supplier block, through the same `place_order` guards.

Order `status` is the supplier side of the order: `SENT`, `CONFIRMED`, `PARTIAL`,
`REJECTED`, `UNCONFIRMED`. The order `outcome` is the gateway result from "Team gateway
interfaces": `CONFIRMED`, `NOT_SENT`, `UNCONFIRMED`, `SENT_READ_FAILED`. An outcome of
`NOT_SENT` means no order exists at the supplier, so it has no order `status`.

### Chef substitute choices

A proposal may include `substitute_options` (default `[]`), up to three distinct
engine-backed baskets considered after partial stock, unknown stock or a passed
cutoff. Supplier-linked alternatives are considered before catalog fallback.

| Field | Type | Meaning |
|---|---|---|
| `tier` | `good`, `better`, `best` | Presentation order; not a guarantee that an option is superior. Fewer choices are allowed. |
| `source` | `original`, `supplier`, `catalog` | Requested basket, supplier link, or catalog fallback. |
| `offer_id` | string | This option's stored engine offer; refresh if expired. |
| `expected_total`, `currency` | decimal string, `EUR` | Exact simulated total for this basket. |
| `lines` | offer-line array | Engine-owned `product_id`, decimal-string `quantity`, `unit`, `why`, `unknown_stock`. |
| `why` | string | Short deterministic explanation, including unknown stock/allergen data. |
| `requires_chef_approval` | `true` | Choices never select, approve or place themselves. |
| `stock_confirmed` | boolean | False if any line has unconfirmed stock. Approval cannot override it. |
| `allergen_data_known` | boolean | False if any retained original line has unknown allergen data; never label it safe. |

Options use the same trusted need/date. A partial-stock option can combine the
original and substitute products so the engine converts the gap by base unit,
not by assuming supplier packs are interchangeable. A candidate that the engine
excludes (cutoff, wrong unit, etc.) is not offered. Selecting a preference is not
an applied edit: re-simulate the selected basket and obtain human approval to its
exact total through the existing workflow before placement.

The trusted worker reads `kitchen_settings.excluded_allergens` through `store`:
an explicit string array of supported allergen names/GS1 codes, including `[]`
when the kitchen explicitly has no exclusions. Missing/malformed policy disables
automatic substitute assessment. The model cannot supply or relax this policy.
AW expands to the individual gluten cereals; GO oats remain distinct.
CONTAINS, MAY_CONTAIN and UNDECLARED matches are refused. Unknown allergen data
is excluded for substitutes and for restricted kitchens. An unrestricted
kitchen's specifically requested original may remain visible as unknown for
chef review. Own-product lookups remain scoped to that kitchen.

### Supplier side

**We call them (adapter contract).** Each supplier is one adapter with the same five
calls: `catalog`, `price(products, date)`, `availability(products, date)`, `place_order`,
`order_status`. Valio Aimo is the live adapter. The `manual` and `csv` adapters use the
price list the kitchen entered: stock is unknown, and the order goes out by e-mail or PDF.

**They call us:** `/v1/suppliers/{supplier_id}/...`

| Method | Path | Scope | What |
|---|---|---|---|
| GET | `/orders` | `supplier:read-orders` | Orders that kitchens approved for this supplier. |
| POST | `/orders/{id}/confirm` | `supplier:confirm` | Body: `result: FULL \| PARTIAL \| REJECTED`, `lines` (required for `PARTIAL`), `idempotency_key`. |
| GET | `/demand?from=&to=&product=` | `supplier:demand` | Forecast demand across kitchens that consented, per product and day. |
| GET | `/demand/shortage-risk` | `supplier:demand` | Products where forecast demand is above the supplier's stated availability. |
| POST | `/offers` | `supplier:read-orders` | Proactive offer to a kitchen (substitute, promotion). It shows up as a suggestion, never as an order. |

A supplier only sees demand from kitchens whose `/sharing` consent names it.

### Body shapes: stock and demand

Proposed for the routes above. Quantities are decimal strings in the stated `unit`.
`null` means unknown, never zero.

**Units.** There are two unit lists, both upper-case, and a field uses exactly one:

- **Kitchen units: `L`, `KG`, `PCS`.** Used by every `unit` in stock counts, stock,
  demand and supplier demand rows, by recipe `unit`, and by `net_content.unit` in the
  product row (`L` or `KG` only). They match Valio's `comparisonUnit`. A product with a
  net content is counted in that unit (milk in `L`); a product without one is counted
  in `PCS`, which is one base unit. Rows for the same product always use the same unit,
  so quantities can be summed across kitchens. A request with another spelling
  (`l`, `Litre`, `kg`) is a 422, never silently converted.
- **Supplier unit codes: `ST`, `KI`, `KG`, `BAG` ...** Used by offer and order lines
  (`unit`), `base_unit`, `sales_unit`, `units[]` and discount tiers. They name a pack,
  not a measure. To go from supplier units to kitchen units, multiply the quantity in
  base units by `net_content.value`.

`POST /v1/kitchens/{kitchen_id}/stock-counts`

```json
{
  "idempotency_key": "count-2026-11-13-22",
  "counted_at": "2026-11-13T22:00:00+02:00",
  "source": "manual",
  "counts": [
    {"product_id": "469549", "on_hand": "120", "unit": "L"},
    {"product_id": "470863", "on_hand": null, "unit": "L"}
  ]
}
```

`source` is `manual`, `pos` or `csv`. A `null` count is stored as "not counted".
Response: `{"stock_count_id": "...", "stored": 2}`.

`GET /v1/kitchens/{kitchen_id}/stock` returns `as_of` and `items`:

| Field | Type | Notes |
|---|---|---|
| `product_id`, `unit` | string | |
| `on_hand` | decimal string or null | The last count; null when never counted or counted as unknown. |
| `counted_at` | timestamp or null | |
| `on_order` | decimal string | Approved orders not yet delivered. |
| `position` | decimal string or null | `on_hand` + `on_order`; null when `on_hand` is null. |
| `next_delivery_date` | date or null | |

`GET /v1/kitchens/{kitchen_id}/demand?from=&to=` returns `from`, `to` and `rows`, one
per product and day:

| Field | Type | Notes |
|---|---|---|
| `product_id`, `date`, `unit` | string | |
| `covers` | integer or null | Expected guests that day. |
| `gross_need` | decimal string | Covers x recipe quantity. |
| `net_need` | decimal string or null | `gross_need` minus stock and stock on order; null when the stock is unknown. |
| `source` | `"menu_plan"` or `"history"` | Where the forecast comes from. |

`GET /v1/suppliers/{supplier_id}/demand?from=&to=&product=` returns `from`, `to` and
`rows`, one per product and delivery day, across kitchens that consented:

| Field | Type | Notes |
|---|---|---|
| `product_id`, `date`, `unit` | string | |
| `demand` | decimal string | Sum of the kitchens' `net_need`. |
| `kitchens` | integer | How many consenting kitchens the sum covers. |
| `by_kitchen` | `{kitchen_id, kitchen_name, demand}[]` | One entry per consenting kitchen with demand that day; `demand` above is their sum. A kitchen without active consent appears nowhere: not in the sum, not in this list. |
| `available` | decimal string or null | The supplier's stated availability; null when unknown. |
| `shortage` | decimal string or null | `demand` minus `available` when positive; null when `available` is null. |
| `risk` | `"OK"`, `"SHORT"` or `"UNKNOWN"` | `UNKNOWN` when `available` is null. |
| `suggested_buy` | decimal string or null | What the supplier should buy to cover the shortage. |

`GET /v1/suppliers/{supplier_id}/demand/shortage-risk` returns the same rows, only
those whose `risk` is not `OK`.

### Trust: audit verification and the live event stream

`GET /audit/verify` recomputes every hash of the audit chain:

```json
{"ok": true, "length": 412, "broken_at": null, "broken_kitchen_id": null, "kitchen_entries": 57}
```

- `length` counts the entries checked up to the first broken one. The chain is one for
  all kitchens; `kitchen_entries` is how many entries belong to this kitchen.
- `broken_at` is the `seq` of the first entry that was changed or removed, else null.
- `broken_kitchen_id` is the kitchen of the entry at `broken_at` when that entry itself
  was edited. It is null when the chain is intact, and when an entry is missing or
  relinked: then nobody can say whose entry it was.
- Because the chain is shared, a break shows for **every** kitchen. While the demo
  kitchen is tampered, every kitchen's `/audit/verify` answers `ok: false` with
  `broken_kitchen_id: "demo-kitchen"`. A kitchen whose id differs from
  `broken_kitchen_id` shows "the break is in another kitchen's entry (the demo), not
  in yours"; a null `broken_kitchen_id` with `ok: false` is shown as a break.

`POST /audit/demo-tamper` answers `{"seq": 412, "tampered": true}`: it edited that entry
(it adds a field `tampered` to the event). `/audit/verify` then answers `ok: false`,
`broken_at: 412`. `POST /audit/demo-restore` answers `{"seq": 412, "restored": true}`, or
`{"seq": null, "restored": false}` when nothing was tampered. Both take
`idempotency_key` like every mutation.

- Only the synthetic demo kitchen (`demo-kitchen`) can be tampered. Any other kitchen
  gets 403 `DEMO_ONLY`. This is a demonstration that a change is detected; the audit
  log has no other way to change or delete an entry.
- A forgotten tamper heals itself: the next `/audit/verify` (from any kitchen) or
  `/audit/demo-tamper` restores a tampered row that is older than 10 minutes.
- One tampered row at a time: a second tamper before a restore is 409 `ALREADY_TAMPERED`.
  A demo kitchen without audit entries is 409 `NOTHING_TO_TAMPER`.

`GET /events` is a `text/event-stream`. Each message:

```
event: proposal
data: {"operation": "insert", "document": {"proposal_id": "...", "status": "PENDING"}}
```

- `event` is `proposal`, `approval` or `audit`. `operation` is `insert`, `update` or
  `replace`. `document` is the whole row after the change, in the shape the matching
  read route returns (`GET /proposals/{id}`, the approval row, a `GET /audit` entry).
- Only this kitchen's rows are sent. A comment line (`: ping`) arrives every few seconds
  when nothing happens, so a dropped connection is noticed.
- Nothing is replayed after a reconnect: the client loads the lists again, then listens.
- The browser's `EventSource` cannot send an `Authorization` header; the web client
  reads the stream with `fetch`.

### Webhooks (both sides)

`proposal.ready`, `proposal.approved`, `order.sent`, `order.unconfirmed`,
`order.confirmed`, `price.changed`, `recall.alert` (Context.dev), `demand.changed`
(supplier). Each delivery carries an `event_id`; receivers treat a repeat `event_id` as
a replay.

### Data shapes

Supplier terms are set by the user per supplier. No default comes from Valio; demo
values are placeholders. Amounts are decimal strings in EUR; quantities are decimal
strings in the stated unit.

**Supplier**

```json
{
  "supplier_id": "sup-valio",
  "name": "Valio Aimo",
  "adapter": "valio_api",
  "terms": {
    "free_delivery_threshold_eur": "300.00",
    "delivery_fee_eur": "25.00",
    "order_days": ["MON", "TUE", "WED", "THU", "FRI"],
    "cutoff_time": "15:00",
    "lead_time_days": 1,
    "discount_tiers": [
      {"product_id": "469549", "min_qty": "100", "unit": "ST", "unit_price_eur": "0.95"}
    ]
  }
}
```

- `adapter` is `valio_api`, `manual` or `csv`. `manual` and `csv` suppliers have unknown
  stock; their offer lines carry `unknown_stock: true`.
- Any `terms` field may be null: unknown, never zero. A null `free_delivery_threshold_eur`
  means no free-delivery threshold is known, so the engine does not pad.
- `cutoff_time` is the kitchen's local time (`HH:MM`). For Valio products, Valio's own
  `closingTime` wins.
- `discount_tiers`: price per quantity break. The tier with the highest `min_qty` at or
  below the line quantity applies. A tier without `product_id` applies to every product
  of that supplier.

**Own product** (a product not in a supplier catalog)

```json
{
  "product_id": "own-7f3a",
  "name": "Rye sourdough loaf 800 g",
  "supplier_id": "sup-bakery",
  "unit": "ST",
  "base_unit": "KG",
  "pack_size_in_base_units": "0.8",
  "unit_price_eur": "4.20",
  "allergens": [{"code": "AW", "level": "CONTAINS"}],
  "allergen_data": "ENTERED"
}
```

- `allergen_data` is `ENTERED` or `UNKNOWN`. An empty `allergens` list with `UNKNOWN`
  means unknown, never "free from".
- Codes are the GS1 allergen codes the Valio catalog uses; `level` is `CONTAINS` or
  `MAY_CONTAIN`.

**Recipe**

```json
{
  "recipe_id": "rec-soup-1",
  "name": "Carrot soup",
  "portions": 1,
  "ingredients": [
    {"product_id": "460708", "qty_per_portion": "0.100", "unit": "KG", "yield_pct": "85"}
  ]
}
```

- `qty_per_portion` is the usable quantity on the plate. `yield_pct` is usable weight as
  a percent of bought weight (trim loss); null means 100.
- Bought quantity = `qty_per_portion` / (`yield_pct` / 100). Example: 0.100 kg at 85% =
  0.118 kg bought. Cost per portion uses the bought quantity.
- Recipe allergens are the union of its products' allergens. One product with unknown
  allergen data makes the recipe's allergen data `UNKNOWN`.

**Menu plan** (`PUT /menu-plans/{week}`)

```json
{
  "week": "2026-W47",
  "days": [
    {"date": "2026-11-16", "meal": "lunch", "recipe_id": "rec-soup-1", "covers": 180}
  ]
}
```

- `meal` is `breakfast`, `lunch`, `dinner` or `other`. `covers` is the expected number of
  portions. The engine computes need = covers x bought quantity - stock - on order.

### Consent record (forecast sharing)

One record per kitchen and supplier. `GET /sharing` returns the list; `PUT /sharing`
replaces it.

```json
{
  "kitchen_id": "kit-1",
  "supplier_id": "sup-valio",
  "share_forecast": true,
  "scope": "forecast_only",
  "granted_at": "2026-11-14T00:30:00+02:00",
  "granted_by": "user-42",
  "revoked_at": null
}
```

- `scope` is `forecast_only`: need per product and day. Never menus, recipes, prices from
  other suppliers or stock counts.
- The supplier sees that need **with the kitchen's name**, not only a total (decided
  2026-11-14 by Tymon). The consent text shown to the kitchen says so: "Share our forecast
  with <supplier>. They see our kitchen's name and what we expect to need, never our menus
  or prices." Because the kitchen agreed to be named, there is no minimum group size.
- Consent is active when `share_forecast` is true and `revoked_at` is null. The supplier
  demand routes and the engine's demand aggregation read only kitchens with active
  consent for that supplier.
- `granted_by` is a human user. An API key or the Buyer cannot grant consent.
- Every grant writes an audit event `share_granted`; every revoke writes `share_revoked`.
  Each carries `kitchen_id`, `supplier_id`, `scope`, the user and the time.

### Kitchen settings

`GET /settings` returns every field. Where the kitchen has set nothing, it returns the
engine's default, except `excluded_allergens`, which is `null` until a person sets it.

```json
{
  "service_level": {"A": "0.975", "B": "0.95", "C": "0.90"},
  "max_cover_days": {"fresh_dairy": 4, "vegetables": 4, "meat": 3, "fish": 2,
                     "frozen": 21, "dry": 30, "other": 14},
  "stockout_cap": "1.8",
  "budget_warning_order_eur": "1500.00",
  "budget_warning_week_eur": "5000.00",
  "excluded_allergens": ["AP", "AN", "AS"]
}
```

| Field | Type | Rule |
|---|---|---|
| `service_level` | `{A, B, C}` of decimal strings | A fraction above 0 and below 1 per demand class (A = menu-critical). The UI shows percent: 97.5 % is `"0.975"`. A value of 0, 1 or more is a 422. |
| `max_cover_days` | object of integers | Never order more than this many days of cover. Keys are the engine's categories: `fresh_dairy`, `vegetables`, `meat`, `fish`, `frozen`, `dry`, `other`. Each at least 1. Another key is a 422, never ignored. |
| `stockout_cap` | decimal string | Demand seen during a stock-out is scaled up by at most this factor. From 1 to 3. |
| `budget_warning_order_eur`, `budget_warning_week_eur` | decimal string or null | Above it the approval shows `OVER_BUDGET_WARNING`. `null` means no warning. A warning only: a person approves every order anyway. |
| `excluded_allergens` | string[] or null | GS1 codes or the allergen names of `search_products`. A product that lists one as CONTAINS, MAY_CONTAIN or UNDECLARED is refused. `[]` means the kitchen has explicitly no exclusions. `null` means nobody has set the policy yet: unknown, not "none". |

`PUT /settings` takes any subset of these fields plus `idempotency_key`. A field that is
left out keeps its value, so a partial save can never drop the allergen policy.
`excluded_allergens` cannot be set back to `null`. The answer is the full settings as
`GET` returns them.

- Only a human user session may change settings; an API key or the Buyer's token gets
  403 `HUMAN_SESSION_REQUIRED`. The settings decide what the Buyer may propose, so the
  Buyer cannot relax them.
- Each change writes one audit entry `settings_changed` with the user and, per changed
  field, the value before and after.
- The web client maps its own names to these: `serviceLevelPercent` (percent) to
  `service_level` (fraction), `maxDaysOfCover` to `max_cover_days`, `stockOutDemandCap`
  to `stockout_cap`, `budgetWarningPerOrderExVat` / `budgetWarningPerWeekExVat` to the
  two budget fields, `excludedAllergens` to `excluded_allergens`.

## Daily weather and holiday signals

`signals.weather` writes `daily_signals` through `store.signals`; forecast/engine
consumers read through that repository, not MongoDB directly. Each snapshot has
84 completed local days before `as_of`, and 14 days starting at `as_of`.

| Field | Type | Meaning |
|---|---|---|
| `kitchen_id` | string | Kitchen scope; callers supply the authenticated kitchen. |
| `date`, `as_of` | `YYYY-MM-DD` strings | Signal day and issue date, in the kitchen timezone. |
| `country`, `timezone` | strings | Holiday country (demo: `FI`) and IANA zone (`Europe/Helsinki`). |
| `latitude`, `longitude` | numbers | Requested kitchen coordinates, degrees. |
| `kind` | `model_history` or `forecast` | History before `as_of`; forecast on/after it. |
| `weather.temperature_2m_max`, `weather.temperature_2m_min` | number or null | Daily maximum/minimum, degrees Celsius. |
| `weather.precipitation_sum` | number or null | Daily precipitation, millimetres. |
| `weather.weather_code` | number or null | WMO weather code. |
| `weather_complete` | boolean | True only when all four weather fields are non-null. |
| `is_weekend`, `is_public_holiday` | booleans | Separate calendar flags; neither implies a demand adjustment. |
| `holiday_names` | string[] | Public holiday names in English; empty on ordinary days. |
| `units` | object | Weather field keys mapped to `°C`, `°C`, `mm`, `wmo code`, respectively. |
| `weather_source`, `holiday_source` | strings | `Open-Meteo` and `python-holidays/<installed-version>`. |
| `source_url` | URL string | Weather request, including location, timezone and date window. |
| `fetched_at` | ISO 8601 timestamp with offset | When this snapshot was collected. |

These physical measurements use JSON numbers, not the decimal money strings used
by purchasing. Null is unknown, never zero. Past weather is archived **model
output**, not station observations or a historical forecast as issued then.

The unique key is `(kitchen_id, date, as_of)`. Recollection on one issue date
updates that vintage; a new issue date retains earlier vintages. Read exactly
one issue date with:

```python
store.signals.list_daily(db, kitchen_id, start: date, end: date, *, as_of: date)
```

Returns a list of the rows above, sorted by `date`, without MongoDB `_id`.
`start` and `end` are inclusive Python `datetime.date` values; `as_of` is required.
Missing days remain missing, with no forward-fill or substitution from another
vintage. Backtests must respect `fetched_at`: today's historical model rows are
not evidence that those values were available to the buyer in the past.

## Reason codes

Engine, gateway, web and agent use exactly these strings in `mandate.reason_codes`,
`mandate.warnings` and line reasons. Source: `docs/scenarios.md`.

| Code | Meaning |
|---|---|
| `CLOSING_PASSED` | `closingTime` is at or before now for this delivery |
| `STOCK_UNKNOWN` | availability is a sentinel (999999 or 9999999999), missing or null |
| `PARTIAL_STOCK` | less is available than needed |
| `SUBSTITUTE_NEEDS_OK` | a substitute changes the product; a human agrees |
| `SUBSTITUTE_FAT_LEVEL` | the substitute has a different fat level |
| `ALLERGEN_RULE` | a kitchen allergen rule refuses a product (`REFUSED` for that line) |
| `ALLERGEN_DATA_MISSING` | no allergen data; treated as unknown |
| `OVER_BUDGET_WARNING` | total is above the kitchen's budget warning. A warning only: a human approves every order anyway. Replaces `OVER_SPEND_LIMIT`. |
| `LOT_SIZE_ROUNDED` | quantity rounded up to `allowedLotSize` or pack |
| `EVENT_LINE` | one-off demand, kept out of the base forecast |
| `MOV_PADDED` | lines pulled forward to reach free delivery |
| `TOTAL_MISMATCH` | gateway total differs from the figure the human approved |
| `STANDING_ORDER_DRIFT` | standing order no longer matches usage |
| `STOCK_COUNT_MISSING` | kitchen stock count is empty |
| `STOCKOUT_ADJUSTED` | demand scaled up for days out of stock |
| `POSITION_OK` | on hand + on order is enough; no order now |
| `COVER_CEILING` | more would exceed the maximum days of cover |
| `PACK_SIZE_DERIVED` | pack size derived because the pack data is missing or wrong |
| `UNCONFIRMED` | the send may have landed; a human checks |

## place_order outcomes

| `outcome` | Meaning | What the caller does |
|---|---|---|
| `CONFIRMED` | The order is known to be placed in our gateway | Show it; done |
| `NOT_SENT` | The request never left; nothing exists at the supplier | May retry explicitly, with the same `idempotency_key` |
| `UNCONFIRMED` | It may already have been applied | Stop; a human checks the order status. Never resend |
| `SENT_READ_FAILED` | It landed; only reading the answer failed | Re-read the order status. Never resend |

Refusals before any send are errors, not outcomes: `TOTAL_MISMATCH` (409: re-simulate
and ask the human again), `HUMAN_SESSION_REQUIRED` (403), `IDEMPOTENCY_KEY_REUSED`
(409). No adapter retries a POST automatically.
