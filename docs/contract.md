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

### Valio's rate limit and `SUPPLIER_BUSY` (#1237)

Valio's rule (challenge Discord, 2026-11-14): a few hundred calls a minute is fine,
more than 10 a second is not. Above it Valio answers 429 and blocks the caller for
30 seconds. The gateway's Valio client honours this for the whole server process:

- **Limiter.** At most 5 calls at once, then 4 a second (a token bucket shared by every
  Valio client in the process), so never more than 9 calls in any one second. A call
  waits briefly for its turn. A call that would wait more than 5 seconds is not sent:
  it fails as `SUPPLIER_BUSY`.
- **Rest after a 429.** No call goes to Valio for 30 seconds, or for `Retry-After`
  seconds when Valio sends a longer one (at most 300). A 429 is never retried inside
  that time. 5xx and network errors keep their short retries.
- **Cache first.** An answer still in the client's cache (30 seconds) is served during
  a rest. Only a call that would reach Valio fails.

What a caller sees during a rest:

| Where | Answer |
|---|---|
| A route that needs a live Valio price or stock (`get_offer`, creating or changing a proposal, addable products, a supplier offer) | 503 `SUPPLIER_BUSY` with `retry_after` (whole seconds) in the error body and a `Retry-After` header. Nothing is stored. Try again after `retry_after`. |
| `search_products` with `need_id` | 200; `can_arrive` is `null` (unknown), as for any missing live answer. |
| Supplier planner view (`/demand`) | 200; availability is unknown, `risk` is `UNKNOWN`; the demand still shows. |
| Buyer agent | The `get_offer` tool fails, so the run ends `CANNOT_FULFIL` and says the tool failed; nothing is ordered. |

```json
{"error": {"code": "SUPPLIER_BUSY", "message": "Valio rate limit: wait 27 s", "retry_after": 27}}
```

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
  or null. Valio (challenge Discord, 14 Nov): "Empty = not available". So an absent
  or null amount is not available, the same as zero. It is not unknown stock.
  `availableDate` may be absent or null. Its value is the earliest available date
  and can differ from the requested date.
- `availableAmount` is expressed in `salesUnit`. Zero means unavailable.
- An `availableAmount` of `999999` or more is a filler, not a measured quantity, for
  any product type, Terminal and Stock. Valio (challenge Discord, 14 Nov): "Availability
  ge 999999 means that we do not know the availability and our current logic allows
  ordering any quantity." Seen live on 2026-11-14 (2,000 products, one date): fillers
  `999999`, `666666666`, `9999999999`, `1999999999` and others, never below `999999`;
  the largest measured amount was `68293`. Empty was `scheduleLines: []` (335 of 2,000);
  an absent or null `availableAmount` was never seen.
- So, in Valio's words: a filler is unknown stock (a person may still approve it, see
  `POST /proposals/{id}/approve`); an empty answer (no schedule line, or an absent or
  null amount) is not available; zero is not available.

#### Gateway availability normalization

The raw Valio API above does not provide the following derived flags. The gateway
adapter normalizes each schedule line with a filler amount (`999999` or more) to
`availableAmount: null`, `unknown_stock: true`, and `orderable: false`. This rule
applies to both Terminal and Stock products even when their cutoff is in the
future. A missing or null amount becomes `availableAmount: 0`, `unknown_stock: false`,
`orderable: false`: not available, never unknown. Measured zero remains zero:
unavailable, but not unknown. A product with `scheduleLines: []` is left out of a quote
("Valio cannot deliver it on any date").

The adapter retains these products and schedule lines. UI and agent consumers
must keep them visible in proposals, labelled as unconfirmed stock, rather than
hide them because `orderable` is false. `orderable` describes confirmed upstream
fulfilment for the requested deadline; it is not permission to show a proposal
or consent to place an order. Human approval does not confirm stock, but since
2026-11-14 it is enough to place the order: the order names each supplier that must
still confirm (`supplier_must_confirm`, see `POST /proposals/{id}/approve`). Cutoff, delivery-date,
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
| `search_products` | POST `/tools/search_products` | `query: string`, `filters: object`, `limit: integer`, `need_id: string` (optional; see below), `mode: "text" \| "hybrid"` (optional, HTTP only; see below) | `products: object[]`, `search: "text" \| "hybrid" \| "meaning-fallback"` (the last only with `need_id`), `meaning_unavailable: true` (only when `mode: "hybrid"` fell back to words); with `need_id` also `requested_date`, `measure`, `note` |
| `get_offer` | POST `/tools/get_offer` | `product_ids: string[]`, `requested_date: YYYY-MM-DD`, `need_id: string` | `offer_id`, `valid_until`, `lines: object[]`, `signature`, `offer_hash` |
| `simulate_order` | POST `/tools/simulate_order` | `offer_id: string` | `offer_id`, `expected_total`, `currency`, `mandate: object`, `lines: object[]`, `signature`, `offer_hash` |
| `place_order` | POST `/tools/place_order` | `offer_id`, `expected_total: decimal string`, `idempotency_key: string` | `order_id`, `outcome`, `status` |
| `request_approval` | POST `/tools/request_approval` | `offer_id: string`, `idempotency_key: string` | `approval_id`, `status: PENDING` |
| `get_order_status` | GET `/tools/get_order_status` | `order_id: string` | `order_id`, `status`, `outcome` |
| `get_audit_log` | GET `/tools/get_audit_log` | `run_id: string` | `events: object[]` |
| `change_proposal` | POST `/tools/change_proposal` | `proposal_id: string`, `idempotency_key: string`, `lines`, `add` (as "Changing a proposal") | the proposal in the `GET /proposals/{id}` shape |

Five more tools exist only for a personal approval token (see "Personal approval tokens").
They call the kitchen routes of the token's kitchen (`GET /v1/me` gives it):

| MCP tool | Method and path | Request fields | Success response fields |
|---|---|---|---|
| `list_proposals` | GET `/v1/kitchens/{k}/proposals` | none | `proposals: object[]` |
| `get_proposal` | GET `/v1/kitchens/{k}/proposals/{id}` | `proposal_id: string` | the proposal |
| `list_orders` | GET `/v1/kitchens/{k}/orders` | none | `orders: object[]` |
| `approve_proposal` | POST `/v1/kitchens/{k}/proposals/{id}/approve` | `proposal_id`, `expected_total: decimal string`, `idempotency_key: string` | as the approve route |
| `reject_proposal` | POST `/v1/kitchens/{k}/proposals/{id}/reject` | `proposal_id`, `reason: string`, `idempotency_key: string` | `proposal_id`, `status: REJECTED` |

**Remote MCP (#280).** The same eight tools are also served over MCP streamable HTTP at
`POST /mcp` (stateless, JSON responses), same names, arguments and results as above.
Three bearer tokens are accepted (`Authorization: Bearer <token>`): the agent token, a
kitchen API token (`tkb_...`, see "Kitchen API tokens") that holds `kitchen:propose`, and
a personal approval token (`tka_...`, see "Personal approval tokens").
Any other caller, the human token and a session cookie included, gets
`401 UNAUTHENTICATED` with `WWW-Authenticate: Bearer`. Each call runs the route above
with the caller's own token: the agent principal, the kitchen token with its own kitchen
and scopes, or the person of the approval token. So every refusal and audit entry is the
same as over HTTP.

`tools/list` depends on the caller. The agent token and a kitchen token see the eight
tools above and nothing else: no approve, reject or cancel tool. A personal approval
token sees the read tools (`search_products`, `get_order_status`, `get_audit_log`) and
the five tools of the second table; it does not see the tools that propose
(`get_offer`, `simulate_order`, `request_approval`, `place_order`, `change_proposal`).
A hidden tool called by name with an agent or kitchen token runs its route and gets
the route's 403 `HUMAN_SESSION_REQUIRED`. There is no cancel tool for anyone.

The trusted application/engine creates `need_id` before invoking the buyer agent,
with `POST /v1/kitchens/{kitchen_id}/needs` (scope `kitchen:propose`). Body:
`quantity` (decimal string, above 0), `unit`, `requested_date` (`YYYY-MM-DD`), `text`
(optional) and `event` (boolean, optional, default `false`). Answer: `need_id`,
`quantity`, `unit`, `requested_date`, `text`. A missing field or a quantity of 0 or less
is 422 `INVALID_REQUEST`. `event: true` marks one-off demand: every offer line quoted for
that need gets `EVENT_LINE`. The trusted app sets `event` from the person's request; the
model never sets it (no tool takes it).

The gateway loads quantities from that stored need; neither `get_offer` nor
`simulate_order` accepts quantities invented by the model. Offer lines include
`product_id`, `quantity`, `unit`, `why`, `available_date`, `unknown_stock` and
`cutoff_passed`. A line also carries `unit_price` (decimal string, per `unit`, before
tax) and `closing_time` (the order cut-off for that line as a timestamp with an offset,
or null when the supplier gives none). Unknown stock is never represented as a measured
sentinel value.

A product that the kitchen's allergen rule refuses is left out of the offer, as in
`POST /proposals` (see `ALLERGEN_RULE` in "Reason codes").

**A need the allergen rule refuses as a whole (#974).** When the need has a `text`, the
gateway applies the rule under "A request the allergen rule removes" to its product
words when it stores the need. For a refused need, `search_products` with that `need_id`
answers `products: []` for every query, with the reason in `note`. `get_offer` quotes
the refused products the person named, not the `product_ids` of the call: the offer has
no line, `mandate.verdict` is `REFUSED`, and `mandate.reasons[0]` is the reason. The
answer of `POST /needs` does not change.

| Status | Code | When (`get_offer`) |
|---|---|---|
| 422 | `INVALID_NEED` | `need_id` is missing or names no need of this kitchen. |
| 422 | `INVALID_REQUEST` | `product_ids` is not 1 to 50 product codes, or `requested_date` is not the need's date. |
| 409 | `KITCHEN_POLICY_INVALID` | The kitchen's `excluded_allergens` names an allergen nobody knows (a typo). Fails closed: no offer is made until a person fixes the setting. |

A simulated offer line also carries three optional fields from the Valio datasets
(see "Static datasets"). They are for display and choice; they never change a quantity.

| Field | Type | Meaning |
|---|---|---|
| `reliability` | number or null | The supplier's delivery reliability for this product: delivered versus ordered, 0 to 1. Null means unknown. |
| `carbon_kg_co2e_per_kg` | number or null | kg CO2-eq per kg, the average of the product group, not this product's own figure. Null means unknown. |
| `labels` | string[] | Product labels, for example `EU_ORGANIC_FARMING`. May be empty. |

**Cut-off, lead time and delivery reliability to show (#1453).** A simulated offer line
(also in `blocks[].lines` and on order lines) carries six more fields, for display only.
They never change a quantity, a line, `cutoff_passed`, `closing_time` or `reliability`
(those keep their meaning above), so the engine and every basket are the same. Each
value says where it came from; real data always wins:

1. `valio`: Valio's own answer (`closingTime` from availability, the delivery
   reliability CSV).
2. `supplier_terms`: the supplier's user-set terms (`order_days`, `cutoff_time`,
   `lead_time_days`, see "Suppliers").
3. `demo`: demo values for a synthetic demo kitchen only (`python -m demo.delivery_terms`).
   They are invented for the demo, never Valio's or a supplier's numbers; the screen
   marks them "(demo)". A real kitchen has no demo values.

| Field | Type | Meaning |
|---|---|---|
| `cutoff_at` | timestamp with offset, or null | Order by this moment for the line's delivery. Valio's `closingTime` when Valio gives one. Otherwise the last order day at the cut-off time (kitchen time, Europe/Helsinki) that still delivers, with the lead time, by the delivery date: the later of `available_date` and the requested date. Null when no source knows it. |
| `cutoff_source` | `"valio"`, `"supplier_terms"`, `"demo"` or null | Where `cutoff_at` came from. `demo` when any part of it (order days, cut-off time or lead time) is a demo value. |
| `lead_time_days` | integer or null | Days from order to delivery: a per-product demo value, else the supplier's terms, else the supplier's demo value. |
| `lead_time_source` | `"supplier_terms"`, `"demo"` or null | Where `lead_time_days` came from. |
| `delivery_reliability` | number or null | Delivered versus ordered, 0 to 1: Valio's `reliability` when known, else the product's demo value, else the supplier's demo value. |
| `reliability_source` | `"valio"`, `"demo"` or null | Where `delivery_reliability` came from. |

A proposal stored before #1453 has none of these fields: read a missing field as null.

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
23:00). `mandate.reasons` is a list of human-readable strings; `mandate.reason_codes`
and `mandate.warnings` use the codes in "Reason codes" below.

A hard rule works per product, not on the whole mandate (#146):

- A product that a hard rule stops (a passed cut-off, a sales block, no delivery date in
  time, no stock, the wrong unit) is left out. It is not a line. It is in the
  simulation's `excluded` list as `{product_id, reason}`, and its reason is also in
  `mandate.reasons`. The other products stay lines.
- `mandate.verdict` is `REFUSED` only when no line is left. Otherwise it is
  `NEEDS_APPROVAL`, even when some products were left out.
- Each line carries its own `reason_codes`. `mandate.reason_codes` is the set of the
  line codes plus `CLOSING_PASSED` and `PARTIAL_STOCK` for the whole request.
- `mandate.warnings` holds only codes of the kind "warning" in "Reason codes" (today
  `OVER_BUDGET_WARNING` and `CERTAINTY_PREMIUM_HIGH`). A warning is shown on the approval card; it never blocks and
  never approves. A warning code is never in `reason_codes`.

For example, the milk case:

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
    "available_date": "2026-11-16", "unknown_stock": false, "cutoff_passed": false,
    "reason_codes": ["PARTIAL_STOCK"]
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
Each row also has `matched_by`: `"words"` (found by the text search only), `"meaning"`
(found by Atlas Vector Search only; it also has the reason `"similar meaning, no word match"`)
or `"both"`. A `"text"` search answers `"words"` on every row.

**With `need_id` (string, optional).** The search becomes a shortlist for that stored
need (#639):

- Only products of the kind the need's `text` names stay (`gateway/kind.py`), when the
  catalog shows that kind. The kind is a set of catalog categories, read from the
  product word of the text (its last product word: "milk" in "lactose-free milk"): the
  categories where at least half of the products (and at least 5) carry that word in
  the English or Finnish name, as a word or as the end of a compound, and where the
  word is not glued to one other word the text does not have ("ice cream", "condensed
  milk", "peanut butter"). The best matches of up to three of those categories are
  searched too, with the product words of the need's text (not the caller's query),
  because the word search returns 50 rows at most. Rows that hold only
  some of the query words are dropped when other rows hold all of them. Nothing is
  narrowed when the catalog shows no such kind, when no row is of the kind, when no
  row of the kind is sold in the need's measure, when `filters.category` is set, or
  when the search was `"hybrid"`. A need with no text uses the query. This step runs
  first; the two steps below run on what it keeps.
- When the need's unit is `L` or `KG` and at least one match is sold in that measure
  (`net_content.unit`), only those products stay. Otherwise nothing is filtered.
- Each product gets `can_arrive`: `true` when it can arrive by the need's date (stock
  scheduled, cut-off not passed, no sales block), `false` when it cannot, `null` when
  unknown (an own product, or no live answer). Rows with `true` come first, then `null`,
  then `false`.
- The response adds `requested_date` (the need's date), `measure` (`"L"`, `"KG"`, or
  `null` when nothing was filtered) and `note` (a short hint for the model).
- An unknown `need_id` (not this kitchen's) is 422 `INVALID_NEED`; a `need_id` that is
  not a string is 422 `INVALID_REQUEST`. The offer step still checks every product.
- A need that the kitchen's allergen rule refuses as a whole gives `products: []` and
  the reason in `note` (see "A need the allergen rule refuses as a whole").

**Which search ran (`search`).** `"text"` is the Atlas Search text index. `"hybrid"` is
the text search fused with Atlas Vector Search over product embeddings (`$rankFusion`),
so a product can match by meaning without sharing a word; such a row has the match
reason `"similar meaning, no word match"`. Hybrid runs only when the gateway has
`SEARCH_HYBRID=true`; it is off by default. The hard filters (allergens, labels, kitchen
scope) apply to both sides. When the vector side cannot answer in 2 seconds, or fails,
the gateway answers with the text search and says `"text"`: a search never fails because
of it.

**Search by meaning for one request (`mode`, #1382).** `mode: "hybrid"` runs the hybrid
search for this one request, whatever `SEARCH_HYBRID` says; `mode: "text"` runs the text
search only. Without `mode`, `SEARCH_HYBRID` decides, as before. Any other value is 422
`INVALID_REQUEST`. `mode` is for the web Catalog page: it is ignored with a `need_id` (the
Buyer's shortlist), and the MCP tool `search_products` never sends it, so the Buyer's
searches do not change. When `mode: "hybrid"` cannot make the query vector (no key, the
embedding service's limit of 3 new texts a minute, more than 2 seconds, the rest time after
a failure), the answer is the text search with `search: "text"` and `meaning_unavailable: true`.
A query asked before keeps its vector in the gateway's memory, so asking it again runs hybrid
without a new embedding call.

**Meaning search when the words find nothing (`"meaning-fallback"`, #1384).** With
`need_id`, when the word search finds no product, the gateway runs Atlas Vector Search
once for the same query and the same hard filters (allergens with the group rule,
`allergen_strictness`, labels, kitchen scope; with `strict`, a product with
`allergen_data_known: false` never comes back). It runs whatever `SEARCH_HYBRID` says,
and only on zero word hits: a request the words answer gets the same rows as before.
The kind and measure steps above then run on what it found. Such an answer says
`search: "meaning-fallback"`, and each of its rows has the match reason
`"similar meaning, no word match"` (`matched_by: "meaning"`). It never runs for a need the allergen rule refuses
(`products: []` as above), and not when the word search finds products only without the
allergen filter: the excluded products are not replaced by others. When the query vector
cannot be made (no key, the embedding rate limit, a slow answer, no vector index), the
answer stays `products: []` with `search: "text"` and a `note` that says the meaning
search could not run.

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

The web Catalog page and screens that hold product codes use these rows: `searchProducts`
posts `search_products` with `limit: 50` and only the filters the person set (`exclude_allergens`
with `allergen_strictness`, `require_labels`, `temperature`), and does not call it for an empty
query with no filter. With the switch "Search by meaning (Atlas Vector Search)" on, it also
sends `mode: "hybrid"`; with it off it sends no `mode`. Each row shows its `matched_by`, and
`meaning_unavailable: true` shows a line that the words were used. `getProducts` reads `GET /v1/kitchens/{kitchen_id}/catalog/products?ids=`
in groups of 200; while the gateway does not serve that route (a 404 with no `error` envelope,
before #1172), it answers from the sample products as it did before. A named 404 is an error. Both map a row with `mapCatalogProduct` (`web/src/api/http-catalog.ts`):
`allergen_data_known: false` is `allergens: null` (unknown), never an empty list.

### Stored rows: order, approval, audit entry

What the shared repository keeps, and what list and detail routes return. Money
and quantities are decimal strings on the wire.

- **Order:** `order_id`, `kitchen_id`, `offer_id`, `idempotency_key`, `expected_total`,
  `lines`, `payload_hash`, `offer_hash` ("Signed offers"), `approved_by` (a person, or
  `"auto-approve (rule set by <person>)"`), `status`, `outcome`, `created_at`,
  `updated_at`, and `receipt` ("Signed order receipt") once the order is placed. The row is
  written before any send, with `status` and `outcome` null; both are set when the attempt ends.
- **Approval:** `approval_id`, `kitchen_id`, `offer_id`, `idempotency_key`, `status`
  (`PENDING`, `APPROVED`, `REJECTED`), `reasons` (string[]), `requested_at`,
  `decided_by`, `decided_at`, and `reason` on a rejection. Decided once, by a human, or
  by the kitchen's earned auto-approve rule ("Earned auto-approve").
- **Audit entry:** `seq` (1, 2, 3 ...), `prev_hash`, `hash`, `stored_at`, `event` (what
  the client sent: `event_id`, `run_id`, `type`, `tool`, `arguments`, `result`, and
  `order_id` when the event belongs to an order) and `server` (what the gateway adds:
  `kitchen_id`, `principal`, its own timestamp). `hash` covers the whole entry and
  the previous entry's hash, so a changed or removed entry is detectable.

### Gateway health

Served (#1188, `gateway/app.py`). `GET /health` is public (no token) and never calls
Valio: monitors call it often. Answer:

```json
{"status": "ok", "valio_api": "live", "valio_reachable": true,
 "valio_checked_at": "2026-11-14T13:40:02+00:00"}
```

- `valio_api`: `live` when the gateway talks to Valio's challenge API, `mock` when it runs
  on a stand-in (tests, the web's mock gateway).
- `valio_reachable`: from the last call to Valio that the gateway made anyway: `true`
  when it answered, `false` when it failed (an HTTP error, a timeout, a 429), `null` when
  no call was made since the gateway started. `valio_checked_at` is the time of that call,
  or null.
- Nothing else: no host name, key, status code or upstream error text.

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
  `supplier:demand`, `supplier:offers` (a write: sending an offer to a kitchen, #110).
- **Only a person approves or rejects: through a signed-in session or a personal
  approval token.** No agent token and no kitchen API token can hold `kitchen:approve`.
  The Buyer proposes; it never approves. A call to approve or reject without a person
  returns 403 `HUMAN_SESSION_REQUIRED` (decision 2026-11-14, "Personal approval tokens").
- Every mutation (POST, PUT, DELETE) carries a nonempty `idempotency_key` string in
  the JSON body, scoped to the organisation and the route. The same rules as the
  gateway tools apply: a replay returns the stored result, reuse with a different
  payload returns 409 `IDEMPOTENCY_KEY_REUSED`, no header alternative.
- Every call is in the audit log: who (user, API key or agent), what, when, and the
  figure that was shown.

### Sign-in and roles (#270)

A person signs in with email and password. The gateway then sets a session cookie.
The gateway finds the caller in this order: the session cookie, then the server's
agent or human bearer token, then a kitchen API token.

| Method | Path | Body | Answer |
|---|---|---|---|
| POST | `/v1/auth/login` | `email`, `password` | `{email, name, role, kitchen_id}`. Sets the cookie `tkb_session`: httpOnly, SameSite=Strict, path `/`, 12 hours, Secure over HTTPS. |
| POST | `/v1/auth/logout` | none | `{"signed_out": true}`. Ends the session and clears the cookie. Also 200 without a session. |
| GET | `/v1/me` | | `{kind, name, role, kitchen_id, can_approve, scopes}`. `kind` is `human`, `agent`, `token` or `personal` (a personal approval token: `name` is the person's email, `role` the person's role now, `scopes` `["kitchen:read"]`, plus `via: "personal_token"`, `token_id` and `expires_at`). `role` is null when `kind` is `agent` or `token`. `scopes` is null for a person, a sorted list for a token. `kitchen_id` is null for the server tokens (any kitchen). |
| POST | `/v1/auth/change-password` | `current_password`, `new_password` | `{"changed": true}`. Needs the session cookie. Ends every other session of that person; this one stays. |

These four routes take no `idempotency_key`.

- Passwords: at least 10 characters. They are scrypt hashes; the gateway never stores
  or logs one in clear.
- An unknown email and a wrong password give the same answer. Five wrong passwords in
  a row lock the account for five minutes. A wrong current password on
  change-password counts too.
- A session belongs to one kitchen. A call for another kitchen is 403 `KITCHEN_SCOPE`.
- The first approver comes from the server `.env` (`DEMO_USER_EMAIL`,
  `DEMO_USER_PASSWORD`).
- `GATEWAY_REQUIRE_LOGIN=true` switches off the shared human token: then only a
  signed-in person is a human. The agent token is not changed.

| Role | Can |
|---|---|
| `approver` | Everything a chef can, plus approve, reject, resolve an unknown send, and manage API tokens and webhooks. |
| `chef` | Read, and ask for proposals (`kitchen:propose`). |
| `viewer` | Read only. |

A person without the role gets 403 `ROLE_REQUIRED`. The shared human token acts as an
`approver`.

| Status | Code | When |
|---|---|---|
| 401 | `INVALID_LOGIN` | Wrong email or password, or a wrong current password. |
| 401 | `UNAUTHENTICATED` | No valid session or token (change-password: no session). |
| 403 | `ROLE_REQUIRED` | The person's role cannot do this. |
| 422 | `WEAK_PASSWORD` | The new password is shorter than 10 characters, or the same as the current one. |
| 429 | `ACCOUNT_LOCKED` | Too many wrong passwords; try again in a few minutes. |

### Kitchen aliases and unknown items

`GET /v1/kitchens/{kitchen_id}/aliases` (`kitchen:read`) returns the kitchen's aliases
and unknown phrases. Aliases are sorted by phrase; unknown phrases are sorted by
ask count descending, at most 100:

```json
{
  "aliases": [
    {"phrase": "house milk", "product_id": "462775",
     "product_name": "Valio Eila lactose-free milk 1 L", "set_by": "aron", "uses": 2}
  ],
  "unknown_items": [
    {"phrase": "talon maito", "times": 2,
     "first_asked": "2026-11-14T02:10:00+00:00",
     "last_asked": "2026-11-14T02:31:00+00:00",
     "suggestions": [{"product_id": "462775", "product_name": null}],
     "suggested_by": "meaning"}
  ]
}
```

- An alias has `phrase`, `product_id`, `product_name`, `set_by` and `uses`;
  `product_name` and `set_by` can be null.
- An unknown item has `times` and nullable ISO `first_asked` and `last_asked`
  timestamps. `suggestions` is null until looked up, otherwise a list of at most
  three `{product_id, product_name}` objects; `product_name` is nullable.
- `suggested_by` is `meaning` for vector search, `words` for text search, or null
  when no lookup has completed.
- Each call looks up at most three phrases without stored suggestions. Successful
  lookups, including empty lists, are stored and reused without another search.
  A search failure leaves the item unlooked-up so a later call retries it.
- Suggestions never create an alias or link a product automatically, and never
  create or change an order; a person decides whether to link one.

### Kitchen API tokens (#271)

A person creates a token for one kitchen, for Claude over MCP, a script or another
agent. A token never approves.

| Method | Path | Body | Answer |
|---|---|---|---|
| POST | `/v1/kitchens/{kitchen_id}/tokens` | `name` (1 to 80 characters), `scopes` | The token row plus `token`. |
| GET | `/v1/kitchens/{kitchen_id}/tokens` | | `{"tokens": [...]}`, newest first, revoked ones included. Never the secret. |
| DELETE | `/v1/kitchens/{kitchen_id}/tokens/{token_id}` | | The token row, with `revoked_at` set. A second revoke returns the same row. |

Token row: `token_id`, `name`, `scopes`, `prefix` (the first 8 characters, for
display), `created_at`, `created_by`, `last_used_at` (or null), `revoked_at` (or null).

- `token` (`tkb_...`) is in the create answer only. It is shown once; the gateway
  keeps only its SHA-256.
- `scopes` holds one or more of `kitchen:read`, `kitchen:propose` and `kitchen:write`
  (stock counts, menus, recipes, own products, suppliers: a POS or inventory feed).
  `kitchen:approve` or another scope is 422 `INVALID_REQUEST`.
- A token acts only for its own kitchen, with only its own scopes. It also works on
  `/tools/*` and on `/mcp` (with `kitchen:propose`).
- Create and revoke are audit entries (`token_created`, `token_revoked`).
- These routes take no `idempotency_key`.

| Status | Code | When |
|---|---|---|
| 401 | `UNAUTHENTICATED` | A revoked or unknown token is used. |
| 403 | `HUMAN_SESSION_REQUIRED` | The caller is not a person (a token or the agent). |
| 403 | `ROLE_REQUIRED` | The person is not an `approver`. |
| 403 | `SCOPE_REQUIRED` | A token calls a route without the scope it needs. |
| 403 | `KITCHEN_SCOPE` | A token calls a route of another kitchen, or a signed-in person calls the token routes of a kitchen that is not theirs. |
| 404 | `TOKEN_NOT_FOUND` | No such token in this kitchen. |
| 422 | `INVALID_REQUEST` | A name or scope rule above is broken. |

The three token routes check the kitchen first (#591): a session belongs to one kitchen,
so a person cannot create, list or revoke the tokens of another kitchen (403
`KITCHEN_SCOPE`). The shared human token has no kitchen, so it is not bound.

### Personal approval tokens

A personal approval token stands for one person, so that person can approve or reject
from their own chat (for example Claude Desktop over `/mcp`). It is not a kitchen API
token: agent and kitchen tokens still never approve.

| Method | Path | Body | Answer |
|---|---|---|---|
| POST | `/v1/kitchens/{kitchen_id}/approval-tokens` | `name` (optional, 1 to 80 characters, default `"chat"`), `hours` (optional integer, 1 to 24, default 8) | The token row plus `token`. |
| GET | `/v1/kitchens/{kitchen_id}/approval-tokens` | | `{"tokens": [...]}`, newest first, revoked and expired ones included. Never the secret. |
| DELETE | `/v1/kitchens/{kitchen_id}/approval-tokens/{token_id}` | | The token row, with `revoked_at` set. A second revoke returns the same row. |

Token row: `token_id`, `kind: "personal_approval"`, `name`, `person` (email),
`kitchen_id`, `prefix` (the first 8 characters), `created_at`, `created_by` (the
person, or `operator-cli`), `expires_at`, `last_used_at` (or null), `revoked_at` (or null).

- Who creates one: only a person signed in with the session cookie, role `approver`,
  whose account is in the `users` collection, for their own kitchen. The token is that
  person's, bound to that kitchen. The open demo's shared human token (everyone acts as
  the demo approver) cannot create one: 403 `PERSONAL_TOKEN_NEEDS_SIGN_IN`. An agent, a
  kitchen token or a personal token: 403 `HUMAN_SESSION_REQUIRED`. A chef or a viewer:
  403 `ROLE_REQUIRED`. Any approver of the kitchen may list and revoke the kitchen's
  personal tokens (list and revoke also work with the shared human token, like the
  kitchen token routes), so a lost token can be stopped at once.
- Operator command for the stage, on the server: `python -m gateway.tokens add-approver
  --email <an existing approver's email> [--hours 8] [--kitchen <id>]` (`--kitchen` is
  needed only for an all-kitchens account), `python -m gateway.tokens list-approvers
  [--kitchen <id>]`, `python -m gateway.tokens remove-approver --token-id <id>`. The token
  value is printed once, to the operator's terminal only.
- `token` (`tka_...`) is in the create answer only. The gateway keeps its SHA-256.
- It expires: default 8 hours, at most 24. Expired, revoked or unknown: 401
  `UNAUTHENTICATED`. An account that no longer exists: 401. A person who is no longer an
  approver: 403 `ROLE_REQUIRED` on approve and reject.
- Scope: `kitchen:read` for its kitchen, plus `POST /proposals/{id}/approve` and
  `POST /proposals/{id}/reject` as that person. Everything else a person can do in the
  web (settings, sharing, auto-approve, users, API tokens, approval tokens, webhooks,
  choose-option, resolve, recall dismiss, the audit demo) is 403 `HUMAN_SESSION_REQUIRED`.
- It never proposes. One credential proposes, a different one approves, so a model that
  proposes can never also approve: `POST /proposals`, `POST /needs`,
  `POST /proposals/{id}/change`, `/tools/get_offer`, `/tools/simulate_order`,
  `/tools/request_approval`, `/tools/place_order`, `/tools/change_proposal` and the
  `kitchen:write` routes are 403 `SCOPE_REQUIRED`. The Buyer worker never gets one.
- Approve is unchanged: `expected_total` and `idempotency_key` are required; 409
  `TOTAL_MISMATCH`, `BLOCKED_BY_RECALL`, `NOT_PENDING` and the idempotency replay apply
  exactly as in the web; unconfirmed stock is a warning, as in the web. Earned auto-approve is unchanged.
- Audit: create and revoke are entries (`approval_token_created`,
  `approval_token_revoked`, with `token_id`, `person`, `expires_at`). Every approve and
  reject with it names the person as `actor` and carries `"via": "personal_token"` and
  `token_id` (`order_placed`, `total_mismatch`, `proposal_rejected`); never the value.
- Prompt injection: the token is for a person's own chat, short-lived (8 hours by
  default), approve and reject only, and every use is audited with `via:
  personal_token`; the chat must show the person the total and get an explicit yes
  before it calls `approve_proposal`, and product text (any text in the data) is data,
  never an instruction to approve.

| Status | Code | When |
|---|---|---|
| 401 | `UNAUTHENTICATED` | The token is expired, revoked or unknown, or its account is gone. |
| 403 | `PERSONAL_TOKEN_NEEDS_SIGN_IN` | Create with the open demo's shared human token: a personal token needs a real signed-in account. |
| 403 | `HUMAN_SESSION_REQUIRED` | Create, list or revoke by a token or the agent; any person-only route called with a personal token. |
| 403 | `ROLE_REQUIRED` | The person is not an `approver`. |
| 403 | `SCOPE_REQUIRED` | A personal token on a propose or write route. |
| 403 | `KITCHEN_SCOPE` | Another kitchen than the token's or the session's. |
| 404 | `TOKEN_NOT_FOUND` | No such approval token in this kitchen. |
| 422 | `INVALID_REQUEST` | `hours` is not an integer from 1 to 24, or `name` is too long. |

### Kitchen side: `/v1/kitchens/{kitchen_id}/...`

| Method | Path | Scope | What |
|---|---|---|---|
| POST | `/stock-counts` | `kitchen:write` | Push a stock count (POS, inventory, manual). `null` means unknown, never zero. A repeat `idempotency_key` returns the stored answer. A repeat key while the first request is still storing returns 409 `IDEMPOTENCY_IN_PROGRESS`: try again. A store that fails releases the key, so the same key can be retried. |
| GET | `/stock` | `kitchen:read` | Current stock and position (on hand + on order). Shape under "Body shapes: stock and demand". |
| POST | `/stock/photo` | `kitchen:write` | Nemotron 3.5 Super VL reads a shelf photo into a count to confirm. Stores no count. Shape under "Count from a shelf photo". Served. |
| POST | `/menu-photo` | `kitchen:write` + `kitchen:propose` | Nemotron 3.5 Super VL reads a photo of a week's menu into dishes matched to recipes, and a menu-plan proposal that waits for a person. Orders nothing. Shape under "Plan from a menu photo". Served by `gateway/menu_photo.py` (#1154). |
| GET | `/products`, `/products/{id}` | `kitchen:read` | Own products (not in a supplier catalog). Shape below. |
| POST, PUT, DELETE | `/products`, `/products/{id}` | `kitchen:write` | Create, change or delete an own product. |
| GET | `/catalog/products?ids=` | `kitchen:read` | Product rows by code, for screens that hold product codes (recipes, orders). `ids` is 1 to 200 codes, comma-separated. Returns `{"products": [...]}` in the order asked, each in the product row shape of `search_products` (no `score`, no `match_reasons`). Covers the supplier catalogs and this kitchen's own products, never another kitchen's. A code that is not found is left out; it is not an error. Fewer than 1 or more than 200 codes is 422 `INVALID_REQUEST`. |
| GET | `/recipes`, `/recipes/{id}` | `kitchen:read` | Recipe = products x quantity per portion, with yield; allergens rolled up. |
| POST, PUT, DELETE | `/recipes`, `/recipes/{id}` | `kitchen:write` | Create, change or delete a recipe. |
| GET | `/menu-plans/{week}` | `kitchen:read` | The week's menu plan (shape below). |
| PUT | `/menu-plans/{week}` | `kitchen:write` | Menus per day: recipe + expected covers. `week` is ISO `YYYY-Www`. |
| GET | `/demand?from=&to=` | `kitchen:read` | Future need per product and day, from the menu plan and history. At most 62 days. Shape under "Body shapes: stock and demand". |
| GET | `/forecast?from=&to=` | `kitchen:read` | The engine's forecast per product and day. Shape under "Forecasts". |
| GET | `/forecast-accuracy?from=&to=` | `kitchen:read` | Past forecasts against what the kitchen really needed, per week. Shape under "Forecasts". |
| GET | `/suppliers`, `/suppliers/{id}` | `kitchen:read` | Suppliers and their terms: free-delivery threshold, fee, order days, cut-off, lead time, discount tiers. User-set; demo values are placeholders. |
| POST, PUT, DELETE | `/suppliers`, `/suppliers/{id}` | `kitchen:write` | Create, change or delete a supplier and its terms. |
| POST | `/suppliers/{id}/price-list/photo` | `kitchen:write` | Read a photo of a manual supplier's price list into draft own products; writes nothing. Served (#1174). Shape under "Read a supplier's price list from a photo". |
| POST | `/needs` | `kitchen:propose` | Store a need (quantity, unit, date, optional `event`) before the Buyer runs. Answer: `need_id`. Shape under "Team gateway interfaces". |
| POST | `/proposals` | `kitchen:propose` | Ask the Buyer: product codes with a quantity and a date, or free text ("1,000 L milk by Monday"). Returns the proposal in the `GET /proposals/{id}` shape, `status: READY` (or `REJECTED` when no line is left). Body, the free-text path and errors under "Creating a proposal". A demand window `from`/`to` is not a body yet. |
| GET | `/proposals` | `kitchen:read` | `{"proposals": [...]}`, newest first, at most 100, each in the `GET /proposals/{id}` shape. |
| GET | `/proposals/{id}` | `kitchen:read` | Lines with `why`, one block per supplier, simulated totals (`expected_total`, `mov_gap`, `delivery_fee`), mandate reasons, warnings. |
| GET | `/proposals/{id}/addable` | `kitchen:read` | What the buyer can add to this proposal, most probable first, and the lines that reach free delivery. Shape under "Addable products". |
| POST | `/proposals/{id}/approve` | `kitchen:approve` (a person, role `approver`: a signed-in session or a personal approval token) | Body: `expected_total` (decimal string, the total the person saw) + `idempotency_key`. A total that moved returns 409 `TOTAL_MISMATCH` with the current total as `expected_total` in the `error` object; a line whose supplier stock is not confirmed does not block a person's approval (2026-11-14, any supplier, Valio too): the order is placed, its lines keep `unknown_stock: true` and its `supplier_must_confirm` names each supplier that must still confirm (earned auto-approve never places such a proposal); a proposal held by a recall returns 409 `BLOCKED_BY_RECALL`; a proposal that is not `READY` returns 409 `NOT_PENDING`. In each case nothing is sent. A missing `expected_total` is 422 `INVALID_REQUEST`. `blocks` is ignored (see below). |
| POST | `/proposals/{id}/reject` | `kitchen:approve` (a person, role `approver`: a signed-in session or a personal approval token) | Body: `reason` (string) + `idempotency_key`. The reason feeds the engine and `env/`. |
| POST | `/proposals/{id}/choose-option` | `kitchen:propose` (human) | Make one of the proposal's `substitute_options` the proposal's basket. Re-simulates it; approves and sends nothing. Shape under "Chef substitute choices". |
| POST | `/proposals/{id}/change` | `kitchen:propose` (a person or an agent) | Set a line's quantity (0 removes it) or add a product from the addable list. Re-quotes live; approves and sends nothing. Returns the proposal in the `GET /proposals/{id}` shape with a new `offer_id` and `expected_total`. Body and errors under "Changing a proposal". MCP tool `change_proposal`. |
| GET | `/orders`, `/orders/{id}` | `kitchen:read` | Order `status` and the gateway `outcome` (below). Each order also has `supplier_must_confirm`: the `supplier_id`s whose stock nobody confirmed yet (a person calls or e-mails them). `[]` for a normal order. `receipt` is the signed order receipt or null ("Signed order receipt"). |
| GET | `/orders/{id}/resolution` | `kitchen:approve` (human) | What our store knows about an order whose send result is unknown. Shape under "Resolving an unknown send". |
| POST | `/orders/{id}/resolve` | `kitchen:approve` (human) | A person records what really happened to an `UNCONFIRMED` or `SENT_READ_FAILED` order: `placed` or `not_sent`. Never resends. Shape under "Resolving an unknown send". |
| GET | `/sharing` | `kitchen:read` | The kitchen's consent records (shape below). |
| PUT | `/sharing` | human, role `approver` | Consent for one supplier: body `supplier_id`, `share_forecast` (boolean). Answer: the whole list, as `GET`. Every change is an audit entry. |
| GET | `/supplier-offers` | `kitchen:read` | Suggestions a supplier sent to this kitchen, open ones first. Shape under "Supplier offers". |
| POST | `/supplier-offers/{offer_id}/accept` | human, role `approver` | Turn an open offer into a normal proposal. It approves and orders nothing: the proposal waits in the inbox like any other. |
| POST | `/supplier-offers/{offer_id}/decline` | human, role `approver` | Say no to an open offer. Optional body: `reason`. |
| GET | `/settings` | `kitchen:read` | Kitchen settings: how the engine sizes orders and what the Buyer may propose. Shape below. |
| PUT | `/settings` | human, role `approver` | Change settings. Only the fields in the body change. Every change is an audit entry. |
| GET | `/auto-approve` | `kitchen:read` | Earned auto-approve: the setting and the learning progress. Shape under "Earned auto-approve". |
| PUT | `/auto-approve` | human, role `approver` | Switch auto-approve on (with a limit) or off. 409 `LEARNING_PERIOD` before the learning period is done. |
| GET | `/audit` | `kitchen:read` | Every step: who, what, when, the figure shown. |
| GET | `/drift` | `kitchen:read` | Standing-order drift for the last full week: products whose order per 100 guests (`portion_creep`) or spend per 100 guests (`cost_creep`) is 15% or more above the 4 weeks before. Shape below. Served (`gateway/drift_routes.py` over `store.drift.standing_order_drift`). |
| GET | `/audit/verify` | `kitchen:read` | Check the audit hash chain now. Shape below. Served, like the next four rows (`gateway/trust_routes.py` over `store.trust`). |
| GET | `/audit/chain?limit=` | `kitchen:read` | This kitchen's newest audit entries with their chain hashes, for the Trust screen. Shape below. |
| POST | `/audit/demo-tamper` | `kitchen:approve` (human, role `approver`) | Demo only: edit one audit row of the synthetic demo kitchen, so `/audit/verify` shows the break. 403 `DEMO_ONLY` for any other kitchen. |
| POST | `/audit/demo-restore` | `kitchen:approve` (human, role `approver`) | Demo only: put the tampered row back exactly as it was. |
| GET | `/events` | `kitchen:read` | Server-sent events: this kitchen's new and changed proposals, approvals and audit entries, as they happen. Shape below. |
| GET | `/recalls` | `kitchen:read` | This kitchen's recall alerts, the proposals they hold and the last check. Shape under "Recall alerts (Context.dev)". |
| POST | `/recalls/check` | `kitchen:write` | Run the recall monitor now: one Context.dev scrape of the Ruokavirasto list (the recording when Context.dev is slow, down or has no key), matched to the kitchen's stock, recipes and open proposals. Body: `idempotency_key`. Never orders. Same answer as `GET /recalls`. |
| POST | `/recalls/{event_id}/dismiss` | `kitchen:approve` (human) | A person dismisses one alert after checking the packs. Body: `reason`. Shape in [recall-contract.md](recall-contract.md). |
| GET | `/label-checks` | `kitchen:read` | Recorded Hyvää Suomesta producer checks for catalog products 462535, 462576 and 462775, plus one synthetic `negative_control`. Answer: `{"checks": [...], "negative_control": {...}}`. Shape in [product-evidence-contract.md](product-evidence-contract.md). |
| POST, GET, DELETE | `/tokens`, `/tokens/{id}` | human, role `approver` | Kitchen API tokens. Shape under "Kitchen API tokens". |
| POST, GET, DELETE | `/approval-tokens`, `/approval-tokens/{id}` | human, role `approver` (create: signed-in session only) | Personal approval tokens. Shape under "Personal approval tokens". |
| GET | `/model-usage` | `kitchen:read` | How much the Buyer agent used its model for this kitchen: runs, model calls, tokens, seconds. Shape under "Model usage". |
| GET | `/atlas` | `kitchen:read` | What MongoDB Atlas holds and runs for the product: vectors, index states, time-series collections, audit chain length. Counts only. Shape under "Atlas facts". Proposed (#1393); the store function exists, the route is not built. |
| GET | `/permissions` | `kitchen:read` | What the Buyer does alone, what a person signs off, what it can never do (`gateway/permissions.py`). Answer: `{alone, person, never, auto_approve_enabled}`; the first three are lists of `{action, audit_kind, rule}`, `auto_approve_enabled` is a boolean. When it is `true`, `alone` gets one more row (audit_kind `auto_approved`, `"Approve routine orders up to <limit> EUR"`; its `rule` names the approver who switched it on), and the first `person` row reads `"Every order that is not routine"`. When it is `false`, the rows are unchanged. |
| POST, GET | `/webhooks` | human, role `approver` | Register a webhook (body `url`, `events`) or list them. Shape under "Webhooks". |
| DELETE | `/webhooks/{id}` | human, role `approver` | Remove the webhook and its delivery log. |
| POST | `/webhooks/{id}/test` | human, role `approver` | Send one signed `ping` now, one attempt. Answer: the delivery row. |
| GET | `/webhooks/{id}/deliveries` | human, role `approver` | `{"deliveries": [...]}`: the last 50 deliveries, newest first. |

**Planning routes (#642).** `gateway/kitchen_routes.py` serves suppliers, recipes, own
products, menu plans, stock counts, stock, demand, settings and sharing.

- `kitchen:write` means a signed-in person who is not a `viewer` (403 `ROLE_REQUIRED`
  for a viewer), or a kitchen API token with `kitchen:write` (403 `SCOPE_REQUIRED`
  without it). The Buyer agent token cannot write.
- `PUT /settings` and `PUT /sharing` need an approver: 403 `HUMAN_SESSION_REQUIRED` for
  a token or the agent, 403 `ROLE_REQUIRED` for a chef or a viewer.
- Lists answer `{"suppliers": [...]}`, `{"recipes": [...]}` and `{"products": [...]}`.
  Create and change answer the row. Delete answers `{"deleted": true}`. An unknown id is
  404 `NOT_FOUND`. A store rule that is broken is 422 `INVALID_REQUEST` with the reason.
- `GET /menu-plans/{week}` of a week without a plan answers `days: []`.
- Every write is an audit entry: `suppliers_created`, `suppliers_changed`,
  `suppliers_deleted` (the same for `recipes_` and `products_`), `menu_plan_changed`,
  `stock_counted`, `settings_changed`, `share_granted`, `share_revoked`.
- `POST /stock/photo` writes no kitchen data. It leaves one audit entry per call:
  `stock_photo_read` or `stock_photo_failed` (see "Count from a shelf photo").
- `POST /orders/{order_id}/delivery-note/photo` leaves stock counts and the order
  unchanged. Each call records `delivery_note_read` or `delivery_note_failed`; see
  [Check a delivery from a photo of its note](#check-a-delivery-from-a-photo-of-its-note-362)
  for fields and the staged structured-result persistence change (#1304).
- `POST /menu-photo` leaves the stored menu plan unchanged. It writes a
  `menu_photo_read` or `menu_photo_failed` audit entry (see "Plan from a menu photo"),
  plus the pending proposal when matched dishes need ingredients.
- Gap: only `POST /stock-counts` replays a repeat `idempotency_key`. The supplier,
  recipe, product and menu-plan writes ignore the key, so a repeated create makes a
  second row.

Proposal `status`, as the gateway returns it (#529):

| Status | Approvable | Meaning |
|---|---|---|
| `READY` | yes | A new proposal with at least one line. It waits for a person. |
| `REJECTED` | no | A person rejected it, or it was created with no line left. |
| `APPROVED` | no | A person approved it; `order_id` names the order. |
| `BLOCKED_BY_RECALL` | no | A recall holds a line of it. Approve answers 409 `BLOCKED_BY_RECALL`. See [recall-contract.md](recall-contract.md). |
| `APPROVING` | no | An approve call claimed it and runs the live re-check; no attempt row yet. It goes on to `COMMITTING`, or back to `READY`. |
| `COMMITTING` | no | The attempt row is being written or the send result is unknown; the proposal is held. It ends as `APPROVED`, or goes back to `READY` (or `BLOCKED_BY_RECALL`). When its order is `UNCONFIRMED` or `SENT_READ_FAILED`, it stays `COMMITTING` until a person uses "Resolving an unknown send"; nothing else releases it. |
| `PENDING` | no | Kept for a proposal the Buyer worker is still building. The gateway does not set it yet. |
| `EXPIRED` | no | Kept for later. The gateway does not set it yet. |

A client treats an unknown status as not approvable. An approval row (`approval_id`)
has its own status, `PENDING` until a person decides; `request_approval` returns that
one.

The approve body has one top-level `expected_total`, because one supplier places orders
today (Valio). An approved proposal places one order. When a second supplier adapter
places orders, the body gets `blocks: [{supplier_id, expected_total}]` again, one block
per supplier, and each block is checked (#528).

More proposal fields, defined in their own files (all optional and additive):

- `recall_alerts`, `replacement_proposal_id`, `recall_replan_error`, and
  `recall_status` on a line: [recall-contract.md](recall-contract.md).
- `product_evidence`: dated product facts from the producer's page, for display only.
  Null when there are none. [product-evidence-contract.md](product-evidence-contract.md).
- `label_checks`: producer-register checks for the proposal's own lines.
  [product-evidence-contract.md](product-evidence-contract.md).

Order `status` is the supplier side of the order: `SENT`, `CONFIRMED`, `PARTIAL`,
`REJECTED`, `UNCONFIRMED`. The order `outcome` is the gateway result from "Team gateway
interfaces": `CONFIRMED`, `NOT_SENT`, `UNCONFIRMED`, `SENT_READ_FAILED`. An outcome of
`NOT_SENT` means no order exists at the supplier, so it has no order `status`.

### Resolving an unknown send

An order with outcome `UNCONFIRMED` or `SENT_READ_FAILED` is never sent again. A
person finds out what happened and records it. Both routes need a human session of an
approver: an API key or an agent token gets 403 `HUMAN_SESSION_REQUIRED`, a chef or
viewer gets 403 `ROLE_REQUIRED`.

The Valio mock API has no order endpoint: orders are ours. So "look up the real state"
means two things. The gateway returns what our own store knows. The person checks the
supplier by their own means (phone, e-mail, the supplier's portal) and types the result.
The gateway never asks the supplier and never guesses.

An attempt whose approval call failed after the attempt row was written is stored as
`UNCONFIRMED` (order `status` null); its proposal stays held, so no second approval can
place a duplicate.

`GET /v1/kitchens/{kitchen_id}/orders/{order_id}/resolution` returns what is known.
Each call writes an `order_lookup` audit entry.

```json
{
  "order_id": "9f1c...",
  "proposal_id": "5b2e...",
  "proposal_status": "COMMITTING",
  "idempotency_key": "approve-7",
  "payload_hash": "sha256 hex of {offer_id, expected_total, lines}",
  "offer_id": "c41d...",
  "supplier_id": "sup-valio",
  "approved_by": "aron",
  "outcome": "UNCONFIRMED",
  "status": null,
  "expected_total": "74.51",
  "lines": [],
  "created_at": "2026-11-14T02:10:00+00:00",
  "updated_at": "2026-11-14T02:10:01+00:00",
  "resolvable": true,
  "resolution": null
}
```

`status` is the supplier-side status when the store has one, else null. `resolvable`
is true only while `outcome` is `UNCONFIRMED` or `SENT_READ_FAILED`. `resolution` is
null until a person resolves the order; after that it is the object below.

`POST /v1/kitchens/{kitchen_id}/orders/{order_id}/resolve`

```json
{"resolution": "placed", "supplier_order_ref": "VAL-2026-00123", "idempotency_key": "r-1"}
```

```json
{"resolution": "not_sent", "note": "Valio sales desk: no such order", "idempotency_key": "r-2"}
```

- `resolution`: `placed` or `not_sent`. Required.
- `supplier_order_ref`: the supplier's own order reference, 1 to 200 characters.
  Required with `placed`; refused with `not_sent`.
- `note`: optional free text, at most 500 characters.
- `idempotency_key`: required, like every mutation.

What each resolution does:

| `resolution` | Order | Proposal | Approval |
|---|---|---|---|
| `placed` | `outcome: CONFIRMED`, `status: SENT`, the reference stored | `APPROVED`, linked to this order | stays `APPROVED` |
| `not_sent` | `outcome: NOT_SENT`, `status: null` | back to `READY` (or `BLOCKED_BY_RECALL` when a recall holds a line), so a person can decide again | a new `PENDING` approval replaces the used one |

Neither resolution sends anything, and neither writes a second attempt row: the stored
order row changes in place. After `not_sent`, a new decision is a new approve call with
a new `idempotency_key` (it passes every guard again and writes its own attempt row);
the old key only replays the closed attempt.

Response (200), also returned by a repeat:

```json
{
  "order_id": "9f1c...",
  "proposal_id": "5b2e...",
  "proposal_status": "APPROVED",
  "outcome": "CONFIRMED",
  "status": "SENT",
  "resolution": {
    "resolution": "placed",
    "supplier_order_ref": "VAL-2026-00123",
    "note": "",
    "resolved_by": "aron",
    "resolved_at": "2026-11-14T02:31:00+00:00",
    "from_outcome": "UNCONFIRMED"
  }
}
```

An order is resolved once. Repeating the same resolution (and the same reference)
returns the stored result and changes nothing, with any `idempotency_key`. Each
resolution writes one `order_resolved` audit entry: who, when, the resolution, the
reference, the outcome before.

| Error | Status | When |
|---|---|---|
| `HUMAN_SESSION_REQUIRED` | 403 | The caller is not a person through a signed-in session (agent token, API key, personal approval token) |
| `ROLE_REQUIRED` | 403 | The person is not an approver |
| `ORDER_NOT_FOUND` | 404 | No such order in this kitchen |
| `INVALID_REQUEST` | 422 | `resolution` is not `placed` or `not_sent`; `placed` without `supplier_order_ref`; `not_sent` with one; a field too long; no `idempotency_key` |
| `ORDER_NOT_RESOLVABLE` | 409 | The order's outcome is not `UNCONFIRMED` or `SENT_READ_FAILED` and no resolution is stored. The error carries `outcome` |
| `ALREADY_RESOLVED` | 409 | A different resolution, or another reference, is already stored. The error carries the stored `resolution` |

### Optional Nemotron proposal explanation (#1173)

`GET /v1/kitchens/{kitchen_id}/proposals/{proposal_id}` accepts optional
`explanation_language=en|fi` (422 for any other value). It keeps `kitchen:read`
and kitchen isolation. Without this parameter, it makes no model call. With it,
the normal proposal returns immediately, adding `explanation: null` until the
background job has a checked result. A later read with the same language returns:

```json
{"explanation": {"text": "?", "language": "en", "model": "nemotron-3.5-super-vl",
 "checked": true, "source_hash": "?", "duration_ms": 1540}}
```

This field is optional for older clients. The web loads the existing approval card
first and requests this detail separately for visible proposals, using the person's
current language. It may poll this detail, but never waits for it before rendering
the card. The full deterministic `decision_summary` stays available. Tymon owns
that card integration. Missing, invalid or unavailable explanations leave the card
unchanged. A proposal creation, option choice, approval or order never waits for
an explanation.

The worker receives only versioned facts derived from the stored request and offer
simulation, the same sources as `gateway/decision.py`. Each fact binds its kind
(`chosen`, `left_out`, `held`, `total`, `approval`), product, quantity, unit and
reason. Nemotron composes two or three sentences by choosing among supplied,
localized sentence forms for these facts; it cannot write an unsupported reason,
change a product/quantity pairing, or claim a pending order is placed. Each sentence
returns `{fact_id, kind, product_id, text, numbers}`. Gateway code validates the
whole result against those facts and sentence forms; one invalid sentence discards
the whole explanation. Amounts, dates, product names/codes and reasons are copied
from the facts, never calculated by the model. EN/FI number formatting is accepted
only when it denotes the same bound value; invented quantities and number words
outside the supplied sentence forms fail. Unreadable or absent facts stay unknown.

Results are cached separately by kitchen, proposal, source revision and language.
The source revision includes the current offer, decision inputs and proposal status;
choosing another option, refreshing an offer, approval or a recall invalidates the
old explanation. A job finishing after a change cannot publish its stale text.
Only the requested language is generated; a later view in the other language has
its own result. The server permits one explanation job per kitchen at a time and
at most one new model attempt per 30 seconds, with a five-minute cooldown for a
failed source/language. Polling, parallel viewers and refreshes share a durable
claim. Claims expire so an interrupted worker can be recovered. Expired proposals
and non-pending states do not start jobs.

One model call, thinking off, short reply budget, 15-second worker deadline; no
model or gateway retry and no automatic provider fallback. Usage is metered as
`proposal_explanation`. Audit actions `proposal_explanation_ready` and
`proposal_explanation_failed` contain the proposal/source, language, model,
latency, sentence count or safe error code. No explanation text, prompt or secret
is written to audit. The signed offer and receipt remain authoritative.

### Creating a proposal

`POST /v1/kitchens/{kitchen_id}/proposals` takes one of four bodies. All need a nonempty
`idempotency_key`.

**Structured body.** The caller names the products; the engine sizes every line.

| Field | Type | Rule |
|---|---|---|
| `product_ids` | string[] | Product codes to quote. Required. |
| `quantity` | decimal string | The need, in `unit`. Above 0, else 422 `INVALID_REQUEST`. |
| `unit` | string | The measure of `quantity`, for example `L` or `KG`. |
| `requested_date` | `YYYY-MM-DD` | The delivery day. |
| `text` | string, optional | The person's own words, kept on the proposal. |
| `event` | boolean, optional | Default `false`. `true` means one-off demand (a party): every line gets `EVENT_LINE`, and the demand is kept out of the base forecast. |

`event` is part of the idempotency payload only when it is `true`. A replay without
`event` and one with `event: false` are the same request.

**Free-text body.** `text` (for example "1,000 L lactose-free milk by Monday") and no
`product_ids`. The gateway tries two readers, in this order:

1. The Buyer worker. The gateway posts `{text, requested_date, idempotency_key,
   kitchen_id}` to `BUYER_WORKER_URL/run` with the agent token, plus `event: true` when
   the request was an event. The worker keeps `event` on the need it stores, so every
   line gets `EVENT_LINE`. Its answer is returned as it is.
   When the text names a delivery day ("by Monday", "maanantaiksi", "16.11.", an ISO
   date), the gateway sends that day as `requested_date`, whatever the body says: a day
   in the text wins over the date picked in a form, as it does for the parser below.
   The body's `requested_date` is sent only when the text names no day.
   That answer is the proposal in the `GET /proposals/{id}` shape, plus three fields
   that only this answer has (a later `GET /proposals/{id}` does not have them):
   - `buyer_run_id`: the Buyer run that made the proposal; its audit steps carry it.
   - `buyer_model`: the model the Buyer ran on, `"nemotron-3.5-super-vl"`.
   - `buyer_usage`: what the model used for this request, from the endpoint's own
     counts (`agent/usage.py`): `{"calls": 7, "failed": 0, "prompt_tokens": 41250,
     "completion_tokens": 1830, "reasoning_tokens": 0, "seconds": 38.412}`. Integers,
     but `seconds` is a number with at most 3 decimals. `reasoning_tokens` is a part
     of `completion_tokens`. A run that was started again counts both attempts. The
     field is missing when the model client has no meter.

   The answer also has `model_trace` (what the model did, see "What the model did"
   below). Unlike the three fields above, a later `GET /proposals/{id}` has it too.
   A replay with the same key returns the same answer, with the same three fields.
   The sum over a kitchen's runs is under "Model usage".
2. The deterministic parser (`gateway/parse.py`), only when the worker is not
   configured, or when its error carries `fallback_safe: true`. Any other worker error is
   returned as it is: the worker may already have made a proposal, so the gateway never
   makes a second one. The parser reads English and Finnish: a quantity with a unit, a
   delivery day and the product words. When the text names no day, it uses
   `requested_date` from the body (the date picked in a form); a day in the text wins. It
   searches the catalog with the product words (50 matches), keeps the products of the
   kind the words name (the rule of `search_products` with `need_id`), then up to 20 that
   fit the asked measure (`gateway/candidates.py`), and the engine sizes the lines. It
   never guesses.

| Status | Code | When |
|---|---|---|
| 422 | `INVALID_REQUEST` | A required field is missing, or `quantity` is 0 or less. |
| 422 | `CANNOT_READ_REQUEST` | The parser cannot read the text without guessing: no quantity with a unit, no delivery day, a day in the past, no product named, more than 500 characters. The message says what is missing. A text with several products is not refused for that any more (#1375): it is split, see "Free text with several products" below. Its own refusals (two delivery days, a split that fails the check, a part with no product words, more than 30 products) are this code too; no proposal is stored. |
| 422 | `NO_PRODUCTS_FOUND` | The parser read the text, but no catalog product matches the product words. |
| 409 | `KITCHEN_POLICY_INVALID` | The kitchen's `excluded_allergens` names an allergen nobody knows (a typo). Fails closed: no offer is made until a person fixes the setting. |
| 409 | `IDEMPOTENCY_KEY_REUSED` | The key was used with another request (for free text: another `text`). |

The proposal's `request` object echoes what was quoted: `product_ids`, `quantity`,
`unit`, `requested_date`, `text`, and:

- `made_by`: `parser` when the parser read the free text, `structured` for a body with
  `product_ids`.
- `query`: the product words the parser searched for. Only on `made_by: parser`.
- `search`: `"meaning-fallback"`, only when the Buyer quoted a product that its search
  found by meaning after the word search found nothing (#1384). The proposal's
  `decision_summary.searched` then ends with "Found by meaning (Atlas Vector Search)
  after the word search found nothing."
- `event`: `true`, only when the request was an event.
- `refusal`: only on a request the allergen rule removes (below): `code`
  (`ALLERGEN_RULE`), `allergens` (string[], the names a person reads, for example
  `["peanuts"]`) and `message` (one sentence).

**A request the allergen rule removes (#974).** A kitchen that excludes peanuts asks for
"15 kg peanut butter". Before the Buyer worker runs, and again on the parser path, the
gateway reads the product words and searches the catalog with no allergen filter:

1. The best matches are the hits whose names hold the most of the request's words.
2. One best match with known allergen data and no excluded allergen: the request goes on
   as above. The same when no best match declares an excluded allergen, or fewer than
   half of them do (missing allergen data alone never refuses a request).
3. Otherwise the request is refused. The answer is 200 with a proposal in the usual
   shape: `status: REJECTED`, no line, `mandate.verdict: REFUSED`, `ALLERGEN_RULE` in
   `mandate.reason_codes`, `request.made_by: parser`, `request.refusal` set,
   `request.product_ids` and `excluded` are the refused best matches (20 at most), and
   `mandate.reasons[0]` is `request.refusal.message`: `This kitchen excludes peanuts, so
   "peanut butter" cannot be ordered: ...`. No other kind of product is proposed, and
   the Buyer worker is not called.

The delivery day of such a request may come from `requested_date` in the body when the
text names none. A replay with the same key and text returns the same proposal.

**List body: several products in one request (#1375).** `needs` and no `product_ids`, no
`from`/`to`. One proposal for all the needs: one total, the supplier `blocks`, one approval,
signed. This is what a chat bot sends for "20 L oat drink, 5 kg butter and 40 rolls for
Monday", and what a free text with several products becomes (below).

| Field | Type | Rule |
|---|---|---|
| `needs` | object[] | 2 to 30 rows of `{text, quantity, unit}`. |
| `needs[].text` | string | The product words ("oat drink"), 1 to 120 characters, at least one word. |
| `needs[].quantity` | decimal string | Above 0, finite, at most 1000000. |
| `needs[].unit` | string | `L`, `KG`, `G` or `ST` (pieces), any case. `G` is read as kilos (`500 G` = `0.5 KG`). |
| `requested_date` | `YYYY-MM-DD` | The one delivery day of every need. Required; not in the past. |
| `idempotency_key` | string | Required. |
| `text` | string, optional | The person's whole sentence, kept on the proposal. At most 500 characters. |
| `event` | boolean, optional | As for the structured body: every line gets `EVENT_LINE`. |

Any other shape (1 row, 31 rows, a bad quantity or unit, two rows with the same product
words, `needs` together with `product_ids` or `from`/`to`): 422 `INVALID_REQUEST`, and
the message names the row.

Each need is read as a single free-text request is read by the parser, in this order and
with no model call: (1) the allergen rule of #974 on its product words, before anything
else; (2) the kitchen's own words for a product (alias memory); (3) the catalog search
narrowed to the kind and the measure the words name; (4) the quote: recall holds, the
per-product allergen rule, live offers, the engine sizes the lines. The Buyer worker is not
called for a list: one model run per need would be N slow runs in series.

A need that cannot be ordered does not stop the others. It stays on the proposal with
`result: "refused"` and a `problem`, the others are quoted:

| `problem.code` | When |
|---|---|
| `ALLERGEN_RULE` | The kitchen's allergen rule removes the products that best match the words (#974). `problem.allergens` names them. |
| `NO_PRODUCTS_FOUND` | No catalog product matches the words. The words are remembered for a person to link. |
| `NOT_AVAILABLE` | Products match, but none can be ordered for the day: a recall hold, the cut-off, no stock. Also a need whose products are all on the proposal for an earlier need ("same product as need 1": ask once, with the sum). |

The answer is a normal proposal with these additions:

- `request.made_by` is `list`; `request.quantity` is the number of needs and
  `request.unit` is `products`; `request.product_ids` are all products priced.
- `request.items`: one row per need, in the order asked: `{text, quantity, unit, query,
  product_ids, result, problem}`. `result` is `proposed` or `refused`; `problem` is
  `{code, message}` (plus `allergens` for `ALLERGEN_RULE`) or `null`. `quantity` and `unit`
  are the need as read (`G` already in `KG`).
- `request.problems`: one sentence per refused need, for a person
  (`5 kg peanut butter: This kitchen excludes peanuts, so "peanut butter" cannot be ordered: ...`).
  The same sentences are in `mandate.reasons`.
- `request.split_by`: only on a free text split into needs (below): `model` or `rules`.
- `NEED_REFUSED` is in `mandate.reason_codes` when any need was refused, and
  `ALLERGEN_RULE` when the allergen rule refused one. `shortfalls` and `PARTIAL_STOCK` as
  for the menu-plan body.
- At least one line: `status: READY`. Every need refused: `status: REJECTED`, no line,
  `mandate.verdict: REFUSED`.

A replay with the same key and the same body returns the same proposal; the check runs
before any search, so a changed catalog never makes a replay a conflict. The same key with
another body: 409 `IDEMPOTENCY_KEY_REUSED`. A kitchen allergen rule nobody knows fails the
whole request with 409 `KITCHEN_POLICY_INVALID`. Earned auto-approve never applies while a
need is refused (`NEED_REFUSED`): a person sees what was left out. Approve, reject, change,
the live re-check and signing work as for any proposal.

**Free text with several products (#1375).** A free-text body whose text asks for two
products or more: a second quantity after "and", "ja", "sekä", "och", "plus", "&", "+", ";"
or a comma. A quantity is a number with a unit ("5 kg") or a whole number before a word
("40 rolls" is 40 pieces). A pack size is not a product ("200 L milk in 1 l cartons",
"50 kg flour, 25 kg sacks"), and neither is a count of people or days ("for 40 guests",
"40 hengelle") or a date ("17 nov", "16.11."). Every other text goes the single-product way
above, unchanged.

1. A stored proposal with this key: the same text returns it, another text is 409
   `IDEMPOTENCY_KEY_REUSED`. No split, no model call on a replay.
2. The delivery day: the day the text names, else `requested_date` of the body. A text
   that names two days or more ("milk for Monday and bread for Tuesday") is 422
   `CANNOT_READ_REQUEST`, and the message starts with `one delivery day per request`.
3. Nemotron splits the text (one call to the Buyer worker's `/split`, at most 40 s). It
   never sets a quantity: plain code checks the split. It must have one need per quantity of
   the text, each need's quantity and unit must be one of the text's (each used once), and
   each need's words must be words of the text that follow that quantity. The quantities that
   go on are the ones read from the text. A split that fails the check is 422
   `CANNOT_READ_REQUEST` with the sentence of before: `one product per request: ...`.
4. When the model is not configured, does not answer in time, or answers outside its
   schema, plain code splits the text: before each quantity, the product words after it. A
   part with no product words, or product words before the first quantity, is 422
   `CANNOT_READ_REQUEST` (the message says which). A split timeout skips the model for the
   next 2 minutes (its own breaker; the Buyer's breaker is not touched). More than 30
   products is 422 `CANNOT_READ_REQUEST`.
5. The needs then go the list body's way, with `request.text` the person's sentence and
   `request.split_by` `model` or `rules`. The trace (`model_trace`) is the parser's rule
   trace: the model only split the words, the matching is plain code.

**Menu-plan window body (#74, #701).** `from` and `to` and no `product_ids` and no
`text`: one proposal for everything the menu plan needs in that window, net of counted
stock. This is the Planner's "Propose order for this week".

| Field | Type | Rule |
|---|---|---|
| `from`, `to` | `YYYY-MM-DD` | The window, both days included. `from` on or before `to`, at most 31 days apart, else 422 `INVALID_REQUEST`. |
| `requested_date` | `YYYY-MM-DD`, optional | The delivery day to quote. Default: `from`. |

The gateway reads the same rows as `GET /demand` for the window and sums the `net_need`
per product. A product whose stock was never counted has no net need, so its full
`gross_need` is used and the need says so; unknown stock is never read as zero stock, and
never silently as "nothing needed". Each product is then sized by the engine for its own
need and measure (`L`, `KG`, or pieces). The answer is a normal proposal (one total, the
supplier `blocks`, one approval, signed) with these additions:

- `request.made_by` is `menu_plan`; `request.window` is `{from, to}`; `request.problems`
  are the menu entries that could not be counted (unknown recipe, no covers).
- `request.needs`: one `{product_id, quantity, unit, stock_counted}` per product.
  `stock_counted: false` means the stock was never counted and the full need is proposed.
- `shortfalls`: one `{product_id, shortfall, unit}` per product the supplier cannot fully
  cover for the date. A shortfall adds `PARTIAL_STOCK` to `mandate.reason_codes`.
- `request.quantity` is the number of products and `request.unit` is `products`.

| Status | Code | When |
|---|---|---|
| 422 | `NOTHING_NEEDED` | Counted stock covers the plan in this window. `error.problems` lists menu entries that could not be counted. |
| 409 | `IDEMPOTENCY_KEY_REUSED` | The key was used with another window. |

Recall holds and the kitchen's `excluded_allergens` apply per product, as for any quote.
Approve, reject, the live re-check (`TOTAL_MISMATCH`) and signing work as for any proposal.
Earned auto-approve never applies while any line has unknown stock or a shortfall.

### What the model did: `model_trace` (#1197)

A proposal the Buyer made and an offer Valio's selling agent made carry `model_trace`:
what the model did, in counts and codes. The web shows it as a folded panel, "What
Nemotron did". It shows which work the model did (it chose the tools and the products)
and which work it did not do (the engine sets every quantity and price; a person
approves).

```json
{"model_trace": {
  "made_by": "model", "reader": "buyer", "model": "nemotron-3.5-super-vl", "thinking": false,
  "calls": 4, "failed": 0, "prompt_tokens": 23110, "completion_tokens": 910,
  "reasoning_tokens": 0, "seconds": 6.214, "attempts": 1, "truncated": false,
  "steps": [
    {"by": "model", "attempt": 1, "tool": "search_products", "query": "lactose free milk", "count": 12},
    {"by": "model", "attempt": 1, "tool": "get_offer", "products": 3, "count": 3},
    {"by": "model", "attempt": 1, "tool": "simulate_order", "count": 3, "code": "NEEDS_APPROVAL"},
    {"by": "model", "attempt": 1, "tool": "request_approval", "code": "PENDING"}]}}
```

| Field | Type | Meaning |
|---|---|---|
| `made_by` | `model` or `rule` | `model`: Nemotron chose the products and the tool calls. `rule`: code chose (the gateway's parser, or the selling agent run with `--no-model`). |
| `reader` | `buyer`, `parser` or `seller` | Who read the request: the Buyer worker, the gateway's parser (`gateway/parse.py`), or Valio's selling agent (`agent/seller.py`). |
| `model` | string or `null` | The model name, `"nemotron-3.5-super-vl"`. `null` when no model ran. |
| `thinking` | boolean or `null` | Thinking on or off for the model calls. `null` when no model ran. |
| `calls`, `failed` | integer | Model calls, and the calls of those that failed. |
| `prompt_tokens`, `completion_tokens`, `reasoning_tokens` | integer | As in `buyer_usage`; `reasoning_tokens` is a part of `completion_tokens`. |
| `seconds` | number | Time in model calls, at most 3 decimals. |
| `attempts` | integer | Buyer runs for this request: 1, or 2 when a run that wrote nothing was started again (#735). 1 for the seller, 0 for the parser. |
| `steps` | array | In order, at most 40 (`truncated: true` when more were cut). Empty when no model ran. |
| `truncated` | boolean | Steps were cut at 40. |

Every count is 0 and `seconds` is 0 when no model ran. All counts come from the
endpoint's own `usage` (`agent/usage.py`), both attempts together.

One step:

| Field | Type | Meaning |
|---|---|---|
| `by` | `model` or `code` | `model`: the model asked for this step. `code`: the runner or agent did it itself (the substitute reads after a short simulation, the seller's shortlist, a rule pick). |
| `attempt` | integer | 1 or 2. |
| `tool` | string | One of the seven Buyer tools (`search_products`, `get_offer`, `simulate_order`, `request_approval`, `place_order`, `get_order_status`, `get_audit_log`); `invalid` for a call the policy could not read; for the seller, `shortlist` (code) and `pick`. |
| `query` | string, optional | `search_products` only: the search words, only letters, digits, spaces and `-`, at most 60 characters. |
| `products` | integer, optional | `get_offer` only: how many products were asked for. |
| `count` | integer, optional | How many rows came back: products found (after the allergen rule), offer lines, simulated lines, shortlist entries. |
| `code` | string, optional | A code, never text: the mandate verdict (`NEEDS_APPROVAL`, `REFUSED`), the approval status (`PENDING`), the order outcome, a policy reason code (`SCHEMA_INVALID`, `UNKNOWN_ID`, `NEED_MISMATCH`, ...), `TOOL_FAILED`, `MEANING_FALLBACK` on a `search_products` step whose answer was `search: "meaning-fallback"` (#1384), or `PICKED` for the seller's pick. |

**Never in it:** a key or token, the system prompt, any text the model wrote (its
reply, its reasons, the seller's `reason`), prices, quantities, other kitchens' data
(the seller's shortlist facts such as the demand of all kitchens stay out). The search
words are the one exception to "no model text": cleaned as above, and shown only to the
kitchen that asked.

**Where it is.**

- `POST /proposals`, the Buyer's answer: `model_trace` with `reader: buyer`. It is
  stored with the run (`db.agent_runs`, `result.model_trace`, through
  `store/agent_runs.py`), so a replay answers the same trace.
- `GET /proposals` and `GET /proposals/{id}`: a proposal the Buyer made carries the
  trace of its run. A proposal the parser made (`request.made_by: parser`) carries
  `{"made_by": "rule", "reader": "parser", "model": null, "thinking": null, ...0,
  "attempts": 0, "steps": []}`: the panel says the parser answered and shows no model
  steps. Every other proposal (structured, menu plan, an accepted offer) has
  `model_trace: null`.
- Supplier offers: an optional `model_trace` in the `POST /offers` body, with
  `reader: seller`, is checked, stored on the offer and returned in the offer shape
  (`null` when none was sent). See "Supplier offers".
- A trace from before #1197 does not exist: such a proposal has `model_trace: null`.
  The web then shows no panel.

The web: one folded line ("4 model calls, 6.2 s, thinking off"), unfolded the steps as
a short list, and the last line "Quantities and prices: the engine. Approval: you."
Strings go through the web's i18n (English and Finnish).

### Addable products

`GET /v1/kitchens/{kitchen_id}/proposals/{proposal_id}/addable` lists what the buyer can
add to this proposal, most probable first. Candidates are the products in the kitchen's
latest stock count that are not on the proposal yet. Quantities come from the engine,
prices from the live supplier. It changes nothing.

```json
{
  "proposal_id": "p-1",
  "rows": [{
    "rank": 1, "product_id": "469549", "name": "Butter 500 g",
    "on_hand": "4", "on_order": "0", "suggested_qty": "12", "unit": "ST",
    "unit_price": "3.85", "addable": true, "timing": "TODAY", "days_of_stock": "1.5",
    "reason_codes": [], "why": "..."
  }],
  "skipped": [{"product_id": "470863", "reason": "pack size unknown: ..."}],
  "mov_padding": {
    "add": [{"product_id": "469549", "quantity": "12", "unit": "ST", "value": "46.20"}],
    "total_ex_vat": "312.40", "saves_fee": "25.00",
    "reason_codes": ["MOV_PADDED"], "why": "Added ... already wanted for the next order: ..."
  }
}
```

| Field | Type | Meaning |
|---|---|---|
| `rank` | integer | 1 is the most probable addition. |
| `on_hand`, `on_order` | decimal string or null | The last count and stock on order. Null means unknown. |
| `suggested_qty` | decimal string or null | The engine's quantity, in `unit`. |
| `unit_price` | decimal string or null | Null when the supplier gives no price. |
| `addable` | boolean | False when the row is shown but cannot be added (for example, no price). |
| `timing` | `TODAY`, `THIS_WEEK`, `THIS_MONTH`, `NO_ACTION` | When the product needs ordering. |
| `days_of_stock` | decimal string or null | Days the current stock lasts. |
| `reason_codes`, `why` | string[], string | Codes from "Reason codes", and the engine's own sentence. |
| `skipped` | `{product_id, reason}[]` | Counted products that cannot be ranked: not in the catalog, or the pack size is unknown. |

`mov_padding` is the engine's answer to "what closes the free-delivery gap" (S06). `add`
holds the smallest set of rows the engine wants anyway (`addable`, `suggested_qty` above
0) that brings the proposal to free delivery; `value` is the line value before tax.
`total_ex_vat` is the proposal total before tax after these lines are added, and
`saves_fee` is the delivery fee that is saved. When nothing sensible closes the gap,
free delivery is already reached, or the terms are unknown, `add` is `[]`,
`total_ex_vat` is the proposal's own total, `saves_fee` is `"0.00"`, `reason_codes` is
`[]`, and `why` says which case it is. A suggestion only: nothing is added until a
person changes the proposal.

| Status | Code | When |
|---|---|---|
| 404 | `PROPOSAL_NOT_FOUND` | No such proposal in this kitchen. |

### Changing a proposal

`POST /v1/kitchens/{kitchen_id}/proposals/{proposal_id}/change` (served, #303). Scope
`kitchen:propose`: a person (approver or chef) or an agent may change a proposal; only a
person approves it. Over MCP the tool `change_proposal` calls the same code
(`POST /tools/change_proposal`, the same body plus `proposal_id`, for the token's kitchen).

```json
{"idempotency_key": "change-1",
 "lines": [{"product_id": "462775", "quantity": "40"}, {"product_id": "463335", "quantity": "0"}],
 "add": [{"product_id": "462921", "quantity": "8"}]}
```

- `lines`: products on the proposal. `quantity` (decimal string or number, 0 or more) is the
  new quantity in the line's own sales unit (the line's `unit`). `0` removes the line. A
  line that is not named keeps its quantity.
- `add` (optional): products from the proposal's `GET .../addable` list with `addable: true`;
  `quantity` above 0, in the row's `unit`.
- At least one of the two is needed; a product is named once.
- The gateway quotes the new basket live on the proposal's own path: a stored, signed
  offer snapshot with `offer_hash`, the recall, allergen and mandate checks again. The
  engine rounds each quantity up to the product's lot size. A line whose quantity was set
  says so in its `why`: `"Quantity set by <actor>. ..."`; when rounded, `"Quantity set by
  <actor>: 2.5 ST asked, rounded up to 3 ST (sold in steps of 1). ..."`, with
  `LOT_SIZE_ROUNDED` in its `reason_codes`. A quantity above the confirmed stock is cut to
  it, as on any proposal (`PARTIAL_STOCK`).
- The answer is the proposal in the `GET /proposals/{id}` shape: the same `proposal_id`,
  still `READY`, with a new `offer_id` and `expected_total`. Nothing is approved or sent. The
  old total can no longer be approved: `/approve` with it is 409 `TOTAL_MISMATCH`.
- The proposal's `request` becomes the changed basket (one need per product, in its sales
  unit, `unit: "products"`, `changed_by`); the first request is kept as `original_request`.
- Audit entry `proposal_changed`: `actor`, `proposal_id`, `from_offer_id`, `offer_id`,
  `from_total`, `expected_total`, and `changes`: one
  `{product_id, unit, from_qty, asked_qty, to_qty}` per named product (`to_qty` after
  rounding; `0` for a removed line, `from_qty` `0` for an added one). A person's change is
  also learning data (`qty_changed`, `line_removed`, `line_added`); an agent's is not.
- A repeat with the same `idempotency_key` and body returns the proposal and quotes nothing.

The web's `ProposalChange` maps onto this body: `SET_QUANTITY` is one `lines` entry,
`REMOVE_LINE` is one `lines` entry with `quantity: 0`, `ADD_LINE` is one `add` entry.
The web client (`changeProposal` in `web/src/api/http.ts`) sends one change per call, with
quantities as decimal strings and one `web-change:<uuid>` key per change (kept for a retry
until it is answered). The approval card then reloads and approves the new `expected_total`.

| Status | Code | When |
|---|---|---|
| 404 | `PROPOSAL_NOT_FOUND` | No such proposal in this kitchen. |
| 404 | `LINE_NOT_FOUND` | A `lines` product is not on the proposal (add it with `add`). |
| 409 | `NOT_PENDING` | The proposal is not `READY` (approved, rejected, held by a recall), or it changed during this call. |
| 409 | `NOT_ADDABLE` | An `add` product is not on the addable list, or cannot be added (no price). |
| 409 | `CLOSING_PASSED` | The cut-off of a line has passed. |
| 409 | `LINE_UNAVAILABLE` | A product cannot be ordered now for another reason (a recall hold, an allergen rule, no stock date). |
| 409 | `IDEMPOTENCY_KEY_REUSED` | The key was used with another body. |
| 422 | `EMPTY_PROPOSAL` | Every line would be removed: reject the proposal instead. |
| 422 | `INVALID_REQUEST` | No `idempotency_key`, no line, a negative or non-numeric quantity, a product named twice, an `add` product already on the proposal. |
| 403 | `ROLE_REQUIRED` / `SCOPE_REQUIRED` | A viewer, or a token without `kitchen:propose`. |

After a refused change the proposal is unchanged: it keeps the basket it had.

### Forecasts

Both routes need `from` and `to` (`YYYY-MM-DD`, inclusive).

`GET /v1/kitchens/{kitchen_id}/forecast?from=&to=` returns the engine's forecast per
product and day, oldest first. A future day is the forecast made today.

```json
{"kitchen_id": "demo-kitchen", "band_from": "own forecast errors", "lines": [
  {"product_id": "469549", "date": "2026-11-16", "need": "42.5", "unit": "L",
   "made_on": "2026-11-14", "why": "...",
   "p10": 36.1, "p50": 42.3, "p90": 49.8, "band_from": "product forecast errors"}
]}
```

- `need` is a decimal string in `unit`. `made_on` is the day the forecast was made;
  `made_on` and `why` may be null.
- `p10`, `p50`, `p90` are the forecast band (#432): JSON numbers (not decimal strings),
  in the same unit as `need`, rounded to 3 decimals. For display only.
- The band comes from the actual/forecast ratios of the last 8 weeks
  (`engine/newsvendor.py`). A line's `band_from` says which: `product forecast errors`
  (this product has at least 20 ratios), else `own forecast errors` (the kitchen's
  pooled ratios, at least 20), else `default spread` (a normal with a 15% spread).
- The top-level `band_from` is the kitchen's fallback: `own forecast errors` or
  `default spread`.
- The window is at most 120 days.

`GET /v1/kitchens/{kitchen_id}/forecast-accuracy?from=&to=` compares past forecasts (as
made the Monday before) with what the kitchen really needed. It compares two methods:
the engine and a plain weekday average.

```json
{"kitchen_id": "demo-kitchen", "from": "2026-09-01", "to": "2026-11-09", "methods": {
  "engine": {
    "total": {"predicted": 1200.0, "actual": 1150.0, "wape": 0.113, "bias": 0.0435,
              "under": 40.0, "over": 90.0, "series": 48},
    "weeks": [{"week": "2026-W36", "predicted": 120.0, "actual": 115.0, "wape": 0.0957,
               "bias": 0.0435, "under": 3.0, "over": 8.0, "series": 5}]
  },
  "weekday-average": {"total": {"predicted": 1180.0, "actual": 1150.0, "wape": 0.1913,
                                "bias": 0.0261, "under": 95.0, "over": 125.0, "series": 48},
                      "weeks": []}
}}
```

- `methods` has the keys `engine` and `weekday-average`; each has the same shape.
- Errors are counted per product and ISO week. `predicted` and `actual` are the sums.
  `wape` is the sum of the absolute errors divided by `actual`. `bias` is
  (`predicted` - `actual`) / `actual`. `under` is the sum of actual above predicted,
  `over` the sum of predicted above actual. `series` counts the product-weeks.
- These are numbers for display, never figures to approve.
- `weeks` has one row per ISO week (`YYYY-Www`), oldest first.
- The window is at most 400 days.

| Status | Code | When (both routes) |
|---|---|---|
| 422 | `INVALID_REQUEST` | `from` or `to` is missing or not a date, `to` is before `from`, or the window is too long (120 days for `/forecast`, 400 for `/forecast-accuracy`). |

### Chef substitute choices

A proposal may include `substitute_options` (default `[]`), up to three distinct
engine-backed baskets considered after partial stock, unknown stock or a passed
cutoff. Supplier-linked alternatives are considered before catalog fallback.

| Field | Type | Meaning |
|---|---|---|
| `tier` | `good`, `better`, `best` | Presentation order; not a guarantee that an option is superior. Fewer choices are allowed. |
| `source` | `confirmed`, `original`, `supplier`, `catalog` | The confirmed part of a short order (below), requested basket, supplier link, or catalog fallback. |
| `offer_id` | string | This option's stored engine offer; refresh if expired. |
| `expected_total`, `currency` | decimal string, `EUR` | Exact simulated total for this basket. |
| `lines` | offer-line array | Engine-owned `product_id`, decimal-string `quantity`, `unit`, `why`, `unknown_stock`. |
| `why` | string | Short deterministic explanation, including unknown stock/allergen data. |
| `requires_chef_approval` | `true` | Choices never select, approve or place themselves. |
| `stock_confirmed` | boolean | False if any line has unconfirmed stock. A person may still approve; the order then waits for the supplier (`supplier_must_confirm`). Auto-approve never places it. |
| `allergen_data_known` | boolean | False if any retained original line has unknown allergen data; never label it safe. |
| `recommended` | boolean, optional | `true` on at most one option: the one the engine would take. Absent or `false` means not marked; the UI never infers it. |
| `held` | object, optional | Only on a `confirmed` option: `{quantity, unit}` of the need that this option does not order. It waits until the supplier confirms stock. Absent when confirmed stock covers the whole need. |

Options use the same trusted need/date. A partial-stock option can combine the
original and substitute products so the engine converts the gap by base unit,
not by assuming supplier packs are interchangeable. A candidate that the engine
excludes (cutoff, wrong unit, etc.) is not offered. Selecting a preference is not
an applied edit: re-simulate the selected basket and obtain human approval to its
exact total through the existing workflow before placement.

**The confirmed part as an option.** When a proposal has a line with unconfirmed stock and
the engine's `partial_fill` names a part the supplier confirms, the gateway offers that part
as the first option: `source: "confirmed"`, its own stored and signed quote, `stock_confirmed:
true`, `recommended: true`, and `held` for the rest. Its `why` says what is ordered now and
what waits. It is the option whose every line has confirmed stock; a person may also approve
the proposal's own basket, and the order then waits for the supplier (`supplier_must_confirm`).
When the proposal's own basket has no
confirmed stock at all, the gateway looks in the catalog shortlist for the request text and
offers confirmed stock from there; the `why` then says it was found in the catalog. A request
without text gets no such search. The gateway answers at most three options:
the confirmed one first, then the Buyer's, with tiers `good`, `better`, `best` in that order.

**Choosing an option.** `POST /v1/kitchens/{kitchen_id}/proposals/{proposal_id}/choose-option`
(served)

```json
{"offer_id": "offer-7f3a", "idempotency_key": "choose-1"}
```

- `offer_id` is the `offer_id` of one entry in the proposal's `substitute_options`; that
  is what identifies an option.
- The gateway simulates that basket again with fresh prices and stock and makes it the
  proposal's basket. The answer is the proposal in the `GET /proposals/{id}` shape, still
  `READY`: its lines and `expected_total` are the chosen basket's, and its `offer_id` is
  the fresh offer. The chosen entry in `substitute_options` carries the same refreshed
  `offer_id`, so a client finds the current choice by comparing the two.
- Nothing is approved and nothing is sent. The person then approves the new
  `expected_total` through `/approve`, as for any proposal.
- A line whose fresh stock is unknown (Valio's filler of 999999 or more, or a manual or
  csv price list) does not refuse the choice (#1313, the approve rule of 2026-11-14): the
  chosen basket keeps `unknown_stock: true` on that line, the mandate reasons say
  "<supplier> must confirm stock for: <products>.", and the approval places the order with
  `supplier_must_confirm` and `stock: unknown` on that receipt line, as for any proposal.
  A line that is not available (empty, null or zero) is still refused: 409 `OPTION_UNAVAILABLE`.
- Only a human session may choose: 403 `HUMAN_SESSION_REQUIRED` for an API key or the
  Buyer's token.

| Status | Code | When |
|---|---|---|
| 404 | `PROPOSAL_NOT_FOUND` | No such proposal in this kitchen. |
| 404 | `OPTION_NOT_FOUND` | `offer_id` is not one of this proposal's options. |
| 409 | `NOT_PENDING` | The proposal is no longer `READY` (approved, rejected, expired). |
| 409 | `STOCK_UNKNOWN` | Only an auto-approval of a line with unconfirmed stock. Neither a person's approve (since 2026-11-14) nor choosing an option (since #1313) returns it. |
| 409 | `CLOSING_PASSED` | The cut-off of a line has passed. |
| 409 | `OPTION_UNAVAILABLE` | A product of the option cannot be ordered now for another reason (no available stock, a recall hold, an allergen rule, no price). |
| 409 | `IDEMPOTENCY_KEY_REUSED` | The key was used with another body. |

After a 409 the proposal is unchanged: it keeps the basket it had.

A choice also replaces the proposal's `request` with the option's request, because the
approval quotes the stored request again; the first request is kept as `original_request`.
The audit entry `option_chosen` names the old and new `offer_id`, the new total and the
`held` quantity. A repeat with the same `idempotency_key` and `offer_id` returns the proposal
and quotes nothing.

The trusted worker reads `kitchen_settings.excluded_allergens` through `store`:
an explicit string array of supported allergen names/GS1 codes, including `[]`
when the kitchen explicitly has no exclusions. Missing/malformed policy disables
automatic substitute assessment. The model cannot supply or relax this policy.
Allergen groups (`store/allergen_groups.py`, #672) work in both directions, on every
path that reads `excluded_allergens` (the gateway and the Buyer):

- A group code or its name (`AN` or `nuts`, `AW` or `gluten`) excludes the group code
  and every member code.
- A member code (`SA` almond, `UW` wheat) also excludes its group code: a product that
  declares only "tree nuts" does not say which nut, and unknown is never safe. It does
  not exclude the other members.
- Oats (`GO`) stay outside the gluten group in both directions.
CONTAINS, MAY_CONTAIN and UNDECLARED matches are refused. Unknown allergen data
is excluded for substitutes and for restricted kitchens. An unrestricted
kitchen's specifically requested original may remain visible as unknown for
chef review. Own-product lookups remain scoped to that kitchen.

### Partial fill: confirmed stock now, a plan for the rest (#288)

A simulation (`get_offer`, `simulate_order`) and every proposal (create and detail)
carry `partial_fill`. It is `null` when confirmed stock covers the need, or when no
stock is confirmed for the requested date. Otherwise it is the engine's answer to
"what happens to the rest?":

```json
{
  "need": "1000", "measure": "L", "remaining": "949",
  "reason_codes": ["PARTIAL_STOCK", "PACK_SIZE_DERIVED"],
  "why": "Order 51 L now for 2026-11-16: 51 ST of Arla 1 L fat free, all the stock Valio confirms for that date, EUR 131.07 ex VAT. Hold the remaining 949 L until Valio confirms stock: no offer shows confirmed stock for a later delivery date.",
  "now": {
    "kind": "NOW", "quantity": "51", "measure": "L", "deliver_on": "2026-11-16",
    "total_ex_vat": "131.07",
    "why": "Order 51 L now for 2026-11-16: 51 ST of Arla 1 L fat free, all the stock Valio confirms for that date, EUR 131.07 ex VAT.",
    "lines": [{"product_id": "462775", "quantity": "51", "unit": "ST", "unit_price": "2.57",
               "total": "131.07", "why": "...", "unknown_stock": false, "reason_codes": ["PARTIAL_STOCK", "PACK_SIZE_DERIVED"]}]
  },
  "rest": [{
    "kind": "HOLD", "quantity": "949", "measure": "L", "deliver_on": null, "total_ex_vat": null,
    "why": "Hold the remaining 949 L until Valio confirms stock: no offer shows confirmed stock for a later delivery date.",
    "lines": []
  }]
}
```

| Field | Type | Meaning |
|---|---|---|
| `need`, `remaining` | decimal string | The request, and the request minus what `now` covers, in `measure`. |
| `why` | string | The sentence of `now`, then of each `rest` part, in order. Shown verbatim. |
| `reason_codes` | string[] | `PARTIAL_STOCK` always, plus the codes of the lines. |
| `now` | part | The stock the supplier confirms for the requested date, and nothing else. |
| `rest` | part[] | One or two parts, in order: `LATER` (if any), then `HOLD` (if any). Their quantities add up to `remaining`. |

A part:

| Field | Type | Meaning |
|---|---|---|
| `kind` | `NOW`, `LATER`, `HOLD` | `LATER`: the earliest later delivery date on which an offer shows confirmed stock and an open cut-off. `HOLD`: no confirmed stock covers it; it waits until the supplier confirms stock. |
| `quantity`, `measure` | decimal string, string | What this part covers (or holds), in the request's measure. |
| `deliver_on` | date or `null` | `null` for `HOLD`: no date is known. |
| `total_ex_vat` | decimal string or `null` | Ex VAT, without fees. `null` for `HOLD`: unknown, never zero. |
| `why` | string | One deterministic sentence with the part's numbers. |
| `lines` | array | `product_id`, `quantity`, `unit`, `unit_price`, `total`, `why`, `unknown_stock` (always `false`), `reason_codes`. Empty for `HOLD`. |

- Unknown stock (a filler, 999999 or more) is never counted, in `now` or in `LATER`.
- `partial_fill` is information: it has no `offer_id`, and it does not change the
  proposal's `lines` or `expected_total`. It cannot be approved or placed as it is.
  Its totals are ex VAT; a figure a person approves still comes from a simulation.
- The `LATER` part uses the first schedule line the supplier returns for each product.

### Earned auto-approve (#618)

Off by default. A kitchen can switch it on only after the gateway has learned from its
own human decisions. `gateway/autoapprove.py` holds every rule.

`GET /v1/kitchens/{kitchen_id}/auto-approve` (`kitchen:read`):

```json
{
  "enabled": false, "limit_eur": null, "set_by": null, "set_at": null,
  "learning": {"weeks": 2, "weeks_needed": 4, "decisions": 11, "decisions_needed": 20,
               "edit_rate": 0.05, "max_edit_rate": 0.1, "learning_done": false},
  "never": ["ALLERGEN_DATA_MISSING", "ALLERGEN_RULE", "BLOCKED_BY_RECALL", "..."],
  "max_limit_eur": "2000"
}
```

- `learning_done` is true when all three hold: at least 4 weeks since the first human
  decision, at least 20 human decisions (approve or reject), and at most 10% of the
  approved proposals edited before approval. Auto-approvals never count.
- `never`: the reason codes that always send a proposal to a person.

`PUT /v1/kitchens/{kitchen_id}/auto-approve` with `{"enabled": true, "limit_eur": "500"}`
or `{"enabled": false}`. Human session, role `approver`. No `idempotency_key`. The
answer is the `GET` shape. Switching off is at once and keeps the last limit.

| Status | Code | When |
|---|---|---|
| 403 | `HUMAN_SESSION_REQUIRED` | The caller is a token or the agent. |
| 403 | `ROLE_REQUIRED` | The person is not an `approver`. |
| 409 | `LEARNING_PERIOD` | `enabled: true` before `learning_done`. |
| 422 | `INVALID_REQUEST` | `enabled` is not a boolean; `limit_eur` is not a number, is 0 or less, or is above 2000. |

Each change writes an audit entry `auto_approve_changed` (`enabled`, `limit_eur`).

When it is on, `POST /proposals` approves a new proposal without waiting only when all
of these hold: the total is at or under the limit; no warning; no reason code from
`never`; nothing excluded; every line has confirmed stock; nothing short; not an event
and not a recall replacement; every product was already on at least 3 human-approved
orders of this kitchen whose lines were not edited. Any doubt or error: the proposal
waits for a person (`READY`).

- The approval runs the normal approve path, with the same live re-check (a moved price
  still refuses with `TOTAL_MISMATCH`; the proposal then stays `READY`).
- `order.approved_by` and the approval's `decided_by` are
  `"auto-approve (rule set by <person>)"`, the approver who switched it on.
- The audit entry `auto_approved` comes first, with `proposal_id`, `expected_total` and
  `evidence` (`limit_eur`, `rule_set_by` and the `learning` fields).
- Proposals the Buyer opens through `/tools/request_approval` are never auto-approved.

### Signed offers (#676)

Every offer and proposal carries `signature` and `offer_hash`: `get_offer`,
`simulate_order`, `GET /proposals`, `GET /proposals/{id}` and `POST /proposals`. Both are null
when signing failed; signing never fails a quote.

- `signature` is a compact JWS, algorithm `EdDSA` (Ed25519), header `kid`. Claims:
  `iss` (`trusted-kitchen-buyer`), `sub` (the `offer_id`), `kitchen_id`,
  `requested_date`, `iat` (as-of), `exp` (valid until), `source`, `currency` (`EUR`),
  `expected_total`, `lines` (`product_id`, `quantity`, `unit`, `unit_price`,
  `stock: "confirmed" | "unknown"`) and `offer_hash`.
- `offer_hash` is the SHA-256 hex of the delivery date, the total and each line
  (product, quantity, unit, unit price), with numbers in one spelling (`1.40` = `1.4`).
- `GET /.well-known/jwks.json` (no token) returns the public key:
  `{"keys": [{"kty": "OKP", "crv": "Ed25519", "x": "...", "kid": "...", "use": "sig", "alg": "EdDSA"}]}`.
  `python -m gateway.verify_offer --base-url <gateway> --offer offer.json` checks one
  offer; a changed line, price or total, another key or an expired offer fails.
- The key is `GATEWAY_SIGNING_KEY` (base64 of a 32-byte seed) from the server
  environment, and the deployed gateway requires it (#755): the deploy does not start
  without it, and the gateway never keeps a signing key in the database there. Only tests
  and local runs, without `GATEWAY_SIGNING_KEY_REQUIRED=true`, create one key and keep it
  in the database.
- An approved order stores the `offer_hash` of the offer the person approved.
  `place_order` for an offer whose `offer_hash` differs is 409 `APPROVAL_MISMATCH`.
  An order without a stored `offer_hash` (older, or signing failed) skips this check.

### Signed order receipt (#290)

Every order answer carries `receipt`: `GET /orders`, `GET /orders/{id}`, the answer of
`POST /proposals/{id}/approve` and of `/tools/place_order`. The gateway signs it once, when
it records the order a person approved, with the same key as the offers.

- `receipt` is a compact JWS, algorithm `EdDSA` (Ed25519), header `kid`. Claims:
  `iss` (`trusted-kitchen-buyer`), `type` (`order_receipt`), `sub` (the `order_id`),
  `kitchen_id`, `offer_id`, `offer_hash` (the signed offer the person approved),
  `currency` (`EUR`), `expected_total` (decimal string), `lines` (`product_id`,
  `quantity`, `unit`, `stock`: `"confirmed"` or `"unknown"`; an `"unknown"` line is one
  its supplier in `supplier_must_confirm` must still confirm), `approved_by` (the person, or
  `"auto-approve (rule set by <person>)"`), `iat` (when the gateway recorded the order),
  `supplier_outcome`, `supplier_note` and `supplier_must_confirm`.
- `supplier_outcome` is what the gateway knows about the supplier when it signs. Today
  it is always `NOT_SENT`: Valio's API has no order endpoint, so the gateway records the
  order and sends nothing. The receipt proves that a person approved this order and that
  the gateway recorded it. It never says that a supplier accepted it.
- A receipt has no `exp`: it does not expire. It is a statement about one moment (`iat`).
  A later change (a supplier confirmation, a person's resolution) is in the order's
  `status` and `outcome`, not in the receipt.
- `receipt` is null when signing failed (the order is still placed, and the gateway logs
  a warning), and for every order placed before this field existed. Old orders are not
  signed afterwards.
- To verify: take the public key from `GET /.well-known/jwks.json`, check the JWS, then
  compare `sub`, `expected_total` and `lines` with the order shown.
  `python -m gateway.verify_offer --base-url <gateway> --receipt order.json` does this
  (`order.json` is one order answer); a changed line, quantity or total, another key or
  an offer signature in place of the receipt fails.

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
| GET | `/demand?from=&to=&product=` | `supplier:demand` | Forecast demand across kitchens that consented, per product and day. Served (#662). |
| GET | `/demand/shortage-risk?from=&to=` | `supplier:demand` | Products where forecast demand is above the supplier's stated availability, or the availability is unknown. Served (#662). |
| GET | `/demand/buying-note?from=&to=&lang=` | `supplier:demand` | A short note for the supplier's planner, written by Nemotron from the shortage-risk rows; every number checked against its row. Served (#1176). Shape under "Buying note for the supplier's planner". |
| GET | `/demand/drift` | `supplier:demand` | The same drift warnings for each kitchen whose `/sharing` consent names this supplier, with `kitchen_id` and `kitchen_name`. Served. Only the server's unbound session passes: no token can hold `supplier:demand` yet, and a person signed in to a kitchen gets 403 `SCOPE_REQUIRED` (#599). |
| POST | `/offers` | `supplier:offers` | A substitute offered to one kitchen before a predicted shortage. It shows up as a suggestion, never as an order. Shape under "Supplier offers". |

A supplier only sees demand from kitchens whose `/sharing` consent names it, and only
sends offers to those kitchens.

### Body shapes: stock and demand

Served (#642, #662). Quantities are decimal strings in the stated `unit`.
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
| `on_order` | decimal string or null | Approved orders (outcome `CONFIRMED`, status `SENT`, `CONFIRMED` or `PARTIAL`) whose delivery day is today or later, in the kitchen's `unit`: quantity x `size_in_base_units` x `net_content`. An order without a known delivery day is not counted. Null when a line cannot be converted to the kitchen's unit. |
| `on_order_known` | boolean | `false` when `on_order` is null (a line could not be converted). Never read a missing `on_order` as zero. |
| `position` | decimal string or null | `on_hand` + `on_order`; null when `on_hand` or `on_order` is null. |
| `next_delivery_date` | date or null | The earliest delivery day among the counted open orders. |

`GET /v1/kitchens/{kitchen_id}/demand?from=&to=` returns `from`, `to` and `rows`, one
per product and day:

| Field | Type | Notes |
|---|---|---|
| `product_id`, `date`, `unit` | string | |
| `covers` | integer or null | Expected guests that day. |
| `gross_need` | decimal string | Covers x recipe quantity. |
| `net_need` | decimal string or null | `gross_need` minus the stock `position`; null when the stock is unknown. |
| `why` | string | How the need was computed, for example `"180 x 0.1 KG (Carrot soup, 85% yield)"`, or `"forecast from history"`. |
| `source` | `"menu_plan"` or `"history"` | Where the forecast comes from. A day without a menu plan uses the stored forecast. |

The answer also has `problems`: short strings for menu-plan entries that could not be
counted (a recipe that does not exist, an entry without covers). A window longer than
62 days, or `to` before `from`, is 422 `INVALID_REQUEST`.

`GET /v1/suppliers/{supplier_id}/demand?from=&to=&product=` returns `supplier_id`,
`from`, `to`, `kitchens_sharing` (how many kitchens have active consent for this
supplier) and `rows`, one per product and delivery day, across kitchens that consented.
The window is at most 14 days (422 `INVALID_REQUEST` otherwise):

| Field | Type | Notes |
|---|---|---|
| `product_id`, `date`, `unit` | string | |
| `product_name` | string or null | The English catalog name; null when the catalog has none. |
| `demand` | decimal string | Sum of the kitchens' stored forecast need. |
| `kitchens` | integer | How many consenting kitchens the sum covers. |
| `by_kitchen` | `{kitchen_id, kitchen_name, demand}[]` | One entry per consenting kitchen with demand that day; `demand` above is their sum. A kitchen without active consent appears nowhere: not in the sum, not in this list. |
| `available` | decimal string or null | The supplier's live availability, in kitchen units; null when unknown (a stock sentinel, a sales block, no live answer, or no unit conversion). |
| `shortage` | decimal string or null | `demand` minus `available` when positive; null when `available` is null. |
| `risk` | `"OK"`, `"SHORT"` or `"UNKNOWN"` | `UNKNOWN` when `available` is null. |
| `suggested_buy` | decimal string or null | `shortage` rounded up to a whole unit; null when `shortage` is null. |

`GET /v1/suppliers/{supplier_id}/demand/shortage-risk` returns the same answer, with
only the rows whose `risk` is not `OK` (so `SHORT` and `UNKNOWN`).

Both routes: a kitchen token and the Buyer agent token get 403 `SCOPE_REQUIRED` (no
token can hold `supplier:demand` yet). A person signed in to a kitchen also gets 403
`SCOPE_REQUIRED` (#599): consent names the supplier, not other kitchens, so one kitchen's
people never read another kitchen's demand. Until supplier accounts exist, only the
server's unbound session (the demo's Valio view) passes.

### Buying note for the supplier's planner (#1176)

Served by `gateway/buying_note.py` (#1176); the model call is made by the Buyer worker
(`agent/buying_note_service.py`, internal `POST /buying-note`), which holds the model key.
`GET /v1/suppliers/{supplier_id}/demand/buying-note?from=&to=&lang=` turns the
shortage-risk rows of the same window into a short note for the supplier's planner,
written by Nemotron 3.5 Super VL. Same scope, window rules and 403s as
`shortage-risk` above. `lang` is `en` (default) or `fi`; anything else is 422
`INVALID_REQUEST`.

The model only chooses the words. Plain code picks the rows first: `SHORT` rows by the
largest `shortage`, then `UNKNOWN` rows by the largest `demand`, at most 8. The model sees
for each row only `product_id`, `product_name`, `date`, `unit`, `demand`, `kitchens`,
`available`, `shortage`, `suggested_buy` and `risk`: never `by_kitchen`, a kitchen
name, a menu, a recipe, a price or a pack size. It is told to write no dates and no
product names (the answer shows both next to each line). A product name inside a line is not read for
numbers, so the "1 l" of "Valio Eila 1 l" is not a quantity.

The worker's model reply is validated against this strict internal shape:

```json
{
  "lines": [
    {
      "row": 0,
      "product_id": "462775",
      "text": "Forecast 2400 L from 6 kitchens against 1700 L available: buy 700 L more.",
      "numbers": ["2400", "6", "1700", "700"]
    }
  ]
}
```

All four line fields are required and additional properties are rejected. There are
at most eight lines; `text` is at most 240 characters and `numbers` at most six
strings. Every number is a **string**, exactly as written in `text`, per `SCHEMA`.

`row` is the zero-based index into the selected rows sent with this call, not a
catalog index. The public `note` omits `row` and `numbers`. The model contributes
only `product_id` and `text`: `product_id` must match the selected row, whose trusted
data supplies the returned `product_id`, `product_name`, `date` and `risk`; only the
validated `text` is copied from the model.

Every line the model writes is checked by plain code before anyone sees it:

- it names one input row (`row`), and its `product_id` is that row's;
- every number in its text is one of that row's values (`demand`, `available`,
  `shortage`, `suggested_buy`, `kitchens`), compared after reading the number in the
  note's language (`1 000`, `12,5` in Finnish; `1,000`, `12.5` in English), and the
  line's own `numbers` list holds exactly those numbers;
- a row with `risk: UNKNOWN` may state only its `kitchens` count: unknown availability
  is never written as a gap of the whole forecast;
- no number words for a quantity (`two`, `hundred`, `kaksi`, `sata`, `tuhat`, ...);
- no row is used twice.

If any line fails, the whole note is dropped: `note` is null and `dropped` names the
first failed rule. The page then shows the table as it does today.

Answer:

```json
{
  "supplier_id": "sup-valio", "from": "2026-11-16", "to": "2026-11-22", "lang": "en",
  "model": "nemotron-3.5-super-vl", "duration_ms": 2140, "cached": false,
  "rows_used": 2,
  "note": [
    {"product_id": "462775", "product_name": "Valio Eila lactose-free milk 1 L",
     "date": "2026-11-16", "risk": "SHORT",
     "text": "Forecast 2400 L from 6 kitchens against 1700 L available: buy 700 L more."},
    {"product_id": "463335", "product_name": "Washed potato 10 kg",
     "date": "2026-11-17", "risk": "UNKNOWN",
     "text": "Availability unknown for 3 kitchens: ask the grower."}
  ],
  "dropped": null
}
```

- No `SHORT` or `UNKNOWN` row in the window: `note` is `[]`, `rows_used` is 0, and no
  model call is made.
- `dropped` is null, or one of `ROW_UNKNOWN`, `PRODUCT_MISMATCH`, `ROW_REPEATED`,
  `NUMBER_NOT_IN_ROW`, `NUMBERS_LIST_MISMATCH`, `GAP_FOR_UNKNOWN`, `NUMBER_WORD`, or
  `REPLY_INVALID` (the model's reply did not match its schema at all).
- Passing notes are cached for 5 minutes by supplier, window, language and the input
  rows. Dropped notes (`note: null`) are cached for 30 seconds (#1211), so a refresh
  immediately after a bad reply does not spend another call, but a later view can
  recover. Cache hits have `cached: true`. One supplier's note is never served to another.
- One note per supplier at a time: a second request while one is written answers 429
  `BUYING_NOTE_BUSY`. One model call, up to 30 s, never retried by the gateway.
- 503 `BUYING_NOTE_UNAVAILABLE` (model or worker down, or no model key) and 504
  `BUYING_NOTE_TIMEOUT`: the page shows the table only.
- The note writes nothing: no audit entry in any kitchen's log, no offer, no order. Its
  model calls are counted by the usage meter under `buying_note`.

### Supplier offers (#374)

A supplier's selling agent sees a predicted shortage and offers one kitchen a substitute.
The kitchen sees a suggestion. A person turns it into a normal proposal, and that proposal
still needs the normal approval. An offer is never an order, and nothing in it is trusted
as a price or a quantity.

**Scope (decided for #110).** `POST /offers` needs `supplier:offers`, not
`supplier:read-orders`: a write does not sit under a read scope. No token can hold
`supplier:offers` yet. As for `supplier:demand`, only the server's unbound session passes;
a kitchen token, the Buyer agent token and a person signed in to a kitchen get 403
`SCOPE_REQUIRED`.

**Consent.** A kitchen that shares its forecast with a supplier accepts suggestions from
that supplier. No other kitchen can get one: without active `/sharing` consent for this
supplier the answer is 403 `SHARING_REQUIRED`, also for a kitchen that does not exist (the
answer does not tell a supplier which kitchens exist). Revoking the consent stops new
offers and stops accepting the open ones.

**`POST /v1/suppliers/{supplier_id}/offers`**

| Field | Type | Notes |
|---|---|---|
| `kitchen_id` | string | The kitchen the offer is for. |
| `product_id` | string | The offered product: a catalog product of this supplier. |
| `replaces_product_id` | string | The product that is predicted short. Not the same as `product_id`. |
| `requested_date` | `YYYY-MM-DD` | The day of the shortage. Not in the past. |
| `reason` | string | Plain text, at most 300 characters. Control characters are removed. |
| `made_by` | string | Who chose the product: a model name, `rule` or a person. At most 100 characters. |
| `idempotency_key` | string | Scoped to the supplier. |
| `model_trace` | object, optional | What the selling agent's model did (#1197), in the shape of "What the model did", with `reader: seller`. The gateway keeps only the fields that shape names; a wrong type, more than 40 steps, a `query` on a seller step, or a `made_by` that disagrees with the offer's `made_by` (`rule` against anything else) is 422 `INVALID_REQUEST`. It is not part of the idempotency payload. It is the supplier's account of its own agent: shown to a person as that, never read as a price, a quantity or a reason. |

There is no price and no quantity in the body. The gateway takes the quantity and the unit
from the kitchen's own forecast: its `demand` for `replaces_product_id` on that date, in
the `SHORT` row of the supplier's shortage view (`/demand/shortage-risk`). The price and the
stock are read live from the supplier when a person accepts.

The answer is the stored offer:

```json
{
  "offer_id": "5f0c...",
  "supplier_id": "sup-valio",
  "kitchen_id": "demo-kitchen",
  "product_id": "400123",
  "product_name": "Lactose free milk drink 1 L",
  "replaces_product_id": "400555",
  "replaces_product_name": "Lactose free semi-skimmed milk 1 L",
  "requested_date": "2026-11-17",
  "quantity": "42",
  "unit": "L",
  "reason": "Same fat level and pack size; in stock for Monday.",
  "made_by": "nemotron-3.5-super-vl",
  "status": "OPEN",
  "created_at": "2026-11-14T05:10:00+00:00",
  "proposal_id": null,
  "decided_by": null,
  "decided_at": null,
  "allergen_data_known": true,
  "model_trace": {"made_by": "model", "reader": "seller", "model": "nemotron-3.5-super-vl",
                  "thinking": false, "calls": 1, "failed": 0, "prompt_tokens": 812,
                  "completion_tokens": 48, "reasoning_tokens": 0, "seconds": 1.204,
                  "attempts": 1, "truncated": false,
                  "steps": [{"by": "code", "attempt": 1, "tool": "shortlist", "count": 5},
                            {"by": "model", "attempt": 1, "tool": "pick", "code": "PICKED"}]}
}
```

`model_trace` is `null` on an offer sent without one, and on offers from before #1197.

**Allergen data.** A product that declares an allergen the kitchen excludes is always
refused. A product without allergen data is refused too, with one exception: the product it
replaces has no allergen data either. The catalog declares no allergens for fresh
vegetables and potatoes, so without this a cucumber could never replace a cucumber. Such an
offer carries `allergen_data_known: false`, the kitchen's tile says "The catalog has no
allergen data for this product. Check the label before you approve.", and the proposal it
becomes carries `ALLERGEN_DATA_MISSING` like any other proposal for that product.

`status` is `OPEN`, `ACCEPTED`, `DECLINED` or `EXPIRED`. An open offer whose
`requested_date` is before today reads as `EXPIRED`; nothing runs in the background.

Refusals, in this order. A refused offer stores nothing and writes nothing in a kitchen's
audit log.

| Status | Code | When |
|---|---|---|
| 403 | `SCOPE_REQUIRED` | The caller does not hold `supplier:offers` (see "Scope"). |
| 422 | `INVALID_REQUEST` | A field is missing or has the wrong type, the date is not a date or is in the past, `reason` is longer than 300 characters, or `product_id` equals `replaces_product_id`. |
| 409 | `IDEMPOTENCY_KEY_REUSED` | The key was used with another body. The same key with the same body answers the stored offer. |
| 403 | `SHARING_REQUIRED` | The kitchen does not share its forecast with this supplier, or does not exist. |
| 404 | `PRODUCT_NOT_FOUND` | `product_id` is not a catalog product of the supplier. Only Valio (`sup-valio`) has a catalog today; a kitchen's own product is never offered. |
| 422 | `NO_SHORTAGE` | The supplier's shortage view has no `SHORT` row for `replaces_product_id` on that date with this kitchen in it. A supplier cannot push a product without a shortage behind it. |
| 422 | `ALLERGEN_RULE` | The kitchen's allergen rule refuses the product, or the product's allergen data is not known while the product it replaces has allergen data (see "Allergen data" below). The answer does not name the kitchen's allergens. A kitchen rule that names an unknown allergen is 409 `KITCHEN_POLICY_INVALID`: no offer until the kitchen fixes it. |
| 409 | `OFFER_LIMIT` | The kitchen already has 3 open offers from this supplier. |

One offer per supplier, kitchen, offered product and date: a later one (another key)
answers the stored offer, whatever its status, and stores nothing. A "no thanks" is final:
the supplier cannot ask again for the same product and day.

Rounds (demo reset): the rule above holds within one round of a kitchen. A kitchen starts in
round 0. `python -m demo.reset_offers --apply` (a server command, no route) starts the next
round: from then on the same supplier, product and day may be offered again, as a new offer
with a new `offer_id`; its accept makes a new proposal. Offers of earlier rounds, their
proposals and audit lines stay as they were. Each offer carries `round` (an integer) in the
stored row; ids of round 0 are the ids made before rounds existed. The reset writes one
audit entry, `demo_offers_reset`.

**`GET /v1/kitchens/{kitchen_id}/supplier-offers`** answers `{"offers": [...]}` in the shape
above: open offers first, then the newest, at most 50.

**`POST /v1/kitchens/{kitchen_id}/supplier-offers/{offer_id}/accept`** takes no body. Only
a person passes (403 `HUMAN_SESSION_REQUIRED` for a token or the Buyer agent, 403
`ROLE_REQUIRED` for a chef or a viewer). The gateway creates a normal proposal
(`POST /proposals` rules: live price and stock, the engine sizes the lines, the allergen
rule and recall holds apply) for `product_id`, the offer's `quantity` and `unit`, on
`requested_date`, with the idempotency key `offer:<offer_id>`. Then the offer becomes
`ACCEPTED` and keeps the `proposal_id`. Answer:

```json
{"offer": {"offer_id": "5f0c...", "status": "ACCEPTED", "proposal_id": "9a1b..."},
 "proposal_id": "9a1b...", "proposal_status": "READY"}
```

- `offer` is the whole offer, as above.
- A second accept (a double click) answers the same proposal; there is never a second one.
- The proposal is never auto-approved, also when the kitchen switched earned auto-approve
  on: a suggestion from a supplier always waits for a person in the inbox.
- `proposal_status: "REJECTED"`: the supplier cannot deliver the product for that date
  after all. The offer stays `OPEN`; nothing waits in the inbox.
- An accept after a `REJECTED` proposal asks the supplier again and builds a new proposal
  (the stock may be back). The rejected one stays as it is. At most 5 proposals are built
  for one offer; after that an accept answers the last one. A proposal that is not
  `REJECTED` is never built twice: the double-click rule above holds for every attempt.
- 404 `OFFER_NOT_FOUND`: no such offer in this kitchen. 409 `OFFER_NOT_OPEN`: the offer is
  `DECLINED` or `EXPIRED`. 403 `SHARING_REQUIRED`: the kitchen revoked its consent.
- The supplier's `reason` is shown to the person and stops there: it is not part of the
  proposal, and no Buyer prompt or tool reads it. The proposal's `text` is a fixed sentence
  the gateway writes from catalog names.

**`POST /v1/kitchens/{kitchen_id}/supplier-offers/{offer_id}/decline`** takes an optional
`reason` (string, at most 500 characters). Only a person passes, as for accept. Answer: the
offer, `status: "DECLINED"`. Declining a declined offer answers the same; an `ACCEPTED` or
`EXPIRED` offer is 409 `OFFER_NOT_OPEN`.

**Served** (`gateway/supplier_offers.py`, `store/supplier_offers.py`). Valio's selling agent
is `agent/seller.py`: code builds a shortlist of at most 5 substitutes from the whole
catalog category of the short product (same measure, a confirmed stock count that covers the
kitchen's need, can arrive, passes the allergen rule above, not short itself; products named
like the short one first; Valio's filler amounts such as 999999 or 666666666 are not a
count), Nemotron 3.5 Super VL picks one entry and
writes the reason, and a pick outside the shortlist means no offer. It runs on the server
inside the gateway image (`python -m agent.seller --dry-run`, then `--apply`), not over HTTP.

**Audit.** Each step is one entry in the kitchen's audit log, written once (a retry does
not add a line): `supplier_offer_received` (actor `supplier:<supplier_id>`, with `offer_id`,
`supplier_id`, `product_id`, `replaces_product_id`, `requested_date`, `quantity`, `unit`,
`made_by`), `supplier_offer_accepted` (the person, `offer_id`, `proposal_id`) and
`supplier_offer_declined` (the person, `offer_id`, `reason`). The supplier's `reason` text
is stored on the offer only, not in the audit entry.

### Count from a shelf photo (#373)

Served (`gateway/stock_photo.py`; the Buyer worker reads the photo at its internal
`POST /shelf`, `agent/shelf_service.py`, because the model key lives in that container).

`POST /v1/kitchens/{kitchen_id}/stock/photo` reads one photo of a shelf with Nemotron
3.5 Super VL and answers a count to confirm. It writes nothing to stock: the person
checks the numbers, and the web app then sends the usual `POST /stock-counts`. The only
thing stored is one audit entry (`stock_photo_read`: who, how many rows, how many of
them counted, how long; or `stock_photo_failed` with the error code). The audit entry
never holds the image or the text the model read.

- Scope `kitchen:write`: a signed-in person who is not a `viewer`, or a kitchen API
  token with `kitchen:write`. The Buyer agent token is refused (403 `SCOPE_REQUIRED`).
- One read per kitchen at a time (#839): a second photo while one is being read answers
  429 `STOCK_PHOTO_BUSY` and never reaches the model. Wait for the first answer, then send
  again. Each read is one model call of up to 75 s on shared credits.
- Body: JSON, like every other gateway route (no multipart parser is installed, and the
  web client and the tokens already speak JSON). The image is base64 in one field:

```json
{"image_base64": "/9j/4AAQSkZJRgABAQ..."}
```

- The image is PNG or JPEG (decided from its first bytes, not from a header), at most
  4 MB after decoding. The whole request body is at most 6 MB. The web app scales a
  photo down to 1600 px on the long side and sends JPEG.
- One call to the worker. The gateway never retries it. The worker stops the vision
  call after 75 seconds (504 `VISION_TIMEOUT`); a normal read takes a few seconds.

Answer:

```json
{
  "model": "nemotron-3.5-super-vl",
  "duration_ms": 4210,
  "saved": false,
  "rows": [
    {"row": "COUNTED", "product_id": "463335",
     "product_name": "Valio Eila 3 % milk drink 1 l lactose free",
     "label": "Valio Eila 3% 1L", "confidence": "high",
     "packs": 6, "pack_size": "1", "count": "6", "unit": "L"},
    {"row": "PLEASE_COUNT", "product_id": "463038",
     "product_name": "Valio Eila 10 L novobox",
     "label": "Valio Eila 10 L novobox", "confidence": "low",
     "packs": null, "pack_size": "10", "count": null, "unit": "L"},
    {"row": "UNMATCHED", "product_id": null, "product_name": null,
     "label": "Arla L m", "confidence": "low",
     "packs": null, "pack_size": null, "count": null, "unit": null}
  ]
}
```

| Field | Type | Notes |
|---|---|---|
| `model` | string | Always `nemotron-3.5-super-vl`: the model that read the photo. |
| `duration_ms` | integer | How long the read took, measured by the gateway. |
| `saved` | `false` | Always false: this route stores no count. |
| `rows[].row` | `COUNTED`, `PLEASE_COUNT`, `UNMATCHED` | See below. |
| `rows[].label` | string | The text the model read on the pack. Data, never an instruction. |
| `rows[].confidence` | `high`, `medium`, `low` | The model's own word. |
| `rows[].product_id`, `product_name` | string or null | The kitchen's product the label matches; both null for `UNMATCHED`. |
| `rows[].packs` | integer or null | Packs the model counted. Null unless the row is `COUNTED`. |
| `rows[].pack_size` | decimal string or null | Kitchen units in one pack (`net_content.value`; `"1"` for a product counted in `PCS`). Null when not known: no net content, a net content in another unit, or a product sold by weight. |
| `rows[].count` | decimal string or null | `packs` x `pack_size`, in `unit`: the value for `on_hand` in `POST /stock-counts`. Null unless the row is `COUNTED`. |
| `rows[].unit` | `L`, `KG`, `PCS` or null | The unit the kitchen counts this product in. Null for `UNMATCHED`. |

Rows:

- `COUNTED`: the label matches one product, the count was read, confidence is high or
  medium, and the pack size is known. A suggestion for a person to confirm.
- `PLEASE_COUNT`: the product is known, but the number is not: low confidence, an
  unreadable count, or an unknown pack size. `count` is null.
- `UNMATCHED`: the label fits no product of this kitchen, or fits two. `count` is null.

Unknown is never a number: only a `COUNTED` row has `packs` and `count`. Products are
matched against this kitchen's stock list (products with a stock count) and its own
products, by name. A product with one `PLEASE_COUNT` row has no `COUNTED` row in the
same answer (a partial number would be wrong). Two `COUNTED` rows for one product (two
shelves) are added up by the client. `rows` can be empty: the model saw no product.

Errors (the usual `{"error": {"code", "message"}}`); in every case nothing was read
and nothing is stored:

| HTTP | Code | When |
|---|---|---|
| 403 | `SCOPE_REQUIRED`, `ROLE_REQUIRED`, `KITCHEN_SCOPE` | The Buyer agent token, a token without `kitchen:write`, a viewer, or another kitchen. |
| 413 | `IMAGE_TOO_LARGE` | The body is over 6 MB or the decoded image is over 4 MB. |
| 422 | `INVALID_JSON`, `INVALID_REQUEST` | The body is not a JSON object, or `image_base64` is missing or not base64. |
| 422 | `NOT_AN_IMAGE` | The decoded bytes are not PNG or JPEG. |
| 429 | `STOCK_PHOTO_BUSY` | A shelf photo for this kitchen is still being read (one read per kitchen at a time); try again when it ends. |
| 502 | `VISION_REPLY_INVALID` | The model answered outside the strict schema. Nothing is repaired or guessed. |
| 503 | `VISION_NOT_CONFIGURED` | The server has no vision worker or no model key. |
| 503 | `VISION_UNAVAILABLE` | The worker or the model could not be reached, or answered with an error. |
| 504 | `VISION_TIMEOUT` | The model did not answer in time. |

A person can always type the count by hand; no error blocks `POST /stock-counts`.

### Check a delivery from a photo of its note (#362)

**Persistence transition (#1300/#1304):** the served response below remains
`saved:false` until #1304 lands. Its successor persists only structured delivery
observations (not stock) and returns `saved:true` after a durable save, as specified
in [Outcomes and delivery observations](#outcomes-and-delivery-observations).
Photos, note text and lot numbers remain transient in both versions.


Served (`gateway/delivery_note.py`; the Buyer worker reads the photo at its internal
`POST /delivery-note`, `agent/receiving_service.py`, like the shelf photo above).

`POST /v1/kitchens/{kitchen_id}/orders/{order_id}/delivery-note/photo` reads one photo
of the paper delivery note with Nemotron 3.5 Super VL. The note is then checked against
the stored order, line by line, in plain code (`agent/receiving.py` `match_delivery`).
It writes nothing to stock or to the order: a person checks the lines, approves or
refuses a substitute, and counts the stock as usual (`POST /stock-counts`). The only
thing stored is one audit entry (`delivery_note_read`: who, the order, how many lines
per status, how long; or `delivery_note_failed` with the error code). The audit entry
never holds the image or the text the model read.

- Scope, body (`{"image_base64": "..."}`), image limits, the one-call-no-retry rule and
  the 75 s worker timeout: the same as `POST /stock/photo`.
- One read per kitchen at a time: a second photo while one is being read answers 429
  `DELIVERY_NOTE_BUSY`.
- The order must be this kitchen's (404 `ORDER_NOT_FOUND` otherwise).

Answer:

```json
{
  "model": "nemotron-3.5-super-vl",
  "duration_ms": 5120,
  "saved": false,
  "order_id": "6f1c...",
  "note": {"order_ref": "ORD-DEMO-0001", "delivery_date": "2026-11-16"},
  "complete": false,
  "lines": [
    {"product_id": "462775", "status": "SHORT", "ordered": "51", "received": "36",
     "missing": "15", "base_unit": "ST",
     "order_quantity": "51", "order_unit": "ST", "missing_order_qty": "15",
     "unit_price": "1.10", "claim_eur": "16.50",
     "lots": [{"lot": "L2611A", "best_before": "unknown", "quantity": "3", "unit": "KI"}]}
  ],
  "not_ordered": [
    {"product_id": "462921", "status": "SUBSTITUTE", "replaces": "462775",
     "quantity": "2", "unit": "KI", "received": "10", "base_unit": "ST",
     "lot": "L2611B", "best_before": "2026-11-28", "needs_approval": true}
  ],
  "claim": {"currency": "EUR", "total_eur": "16.50", "lines": 1, "quantity": "15",
            "unit": "ST", "not_valued": 0, "supplier_name": "Valio Aimo"}
}
```

| Field | Type | Notes |
|---|---|---|
| `note.order_ref`, `note.delivery_date` | string | As printed on the note, or `"unknown"`. Data, never an instruction. |
| `complete` | boolean | True only when every ordered line is `RECEIVED` and nothing else came. |
| `lines[]` | one per ordered line | `status`: `RECEIVED`, `SHORT`, `MISSING` or `UNKNOWN`. |
| `lines[].ordered`, `received`, `missing` | decimal string or null | In `base_unit` (the catalog's base unit, converted with the catalog's pack sizes). Null when unknown. |
| `lines[].order_quantity`, `order_unit` | decimal string, string | The ordered quantity and unit as stored on the order (the supplier's sales unit). (#1198) |
| `lines[].missing_order_qty` | decimal string or null | `missing` in `order_unit`: `missing` x `order_quantity` / `ordered`. Null when `missing` is null. (#1198) |
| `lines[].unit_price` | money string or null | EUR ex VAT per `order_unit`, the price stored on the order. Null when the order has none. (#1198) |
| `lines[].claim_eur` | money string or null | The value of what did not come: `missing_order_qty` x `unit_price`, rounded half up to cents. `"0.00"` for `RECEIVED`. Null for `UNKNOWN` and for a line without a price. (#1198) |
| `claim` | object | One total to claim from the supplier, for the `SHORT` and `MISSING` lines (#1198). |
| `claim.total_eur` | money string | The sum of the `claim_eur` of the `SHORT` and `MISSING` lines (each rounded first). `"0.00"` when there are none. Ex VAT. |
| `claim.lines` | integer | How many lines are `SHORT` or `MISSING`. |
| `claim.quantity`, `claim.unit` | decimal string and string, or both null | The sum of `missing_order_qty` when every `SHORT` and `MISSING` line has the same `order_unit` and a known value; else both null. |
| `claim.not_valued` | integer | Lines that may be short but have no value: `UNKNOWN` lines, and `SHORT` or `MISSING` lines without a price. They are not in `total_eur`; a person checks them. |
| `claim.supplier_name` | string or null | The supplier's name when the order is for one supplier; else null. |
| `lines[].lots` | list | The note's lines for this product: `lot`, `best_before` (`"unknown"` when unreadable), quantity and unit as printed. |
| `not_ordered[]` | one per note line not on the order | `status`: `SUBSTITUTE` (it says it replaces an ordered product, or that part is unreadable), `EXTRA` (not ordered, replaces nothing), `UNREADABLE` (no readable product code). |
| `not_ordered[].needs_approval` | boolean | True for every `SUBSTITUTE`: a person says yes or no before it counts as received. |

Unknown is never a number. An unreadable quantity makes the line `UNKNOWN`, never
`MISSING` or zero. A line absent from the note is `MISSING` only when every product
code on the note was readable; otherwise it is `UNKNOWN`, because the unreadable line
may be that product.

The money is plain code in the gateway, from the stored order's own lines and prices; the
model gives no price and no value (#1198). A `SUBSTITUTE` is not taken off the claim: a
person decides if it counts. Nothing is sent to the supplier (Valio's API has no claim
route); the web app copies the claim as plain text for a person to send.

Errors: those of `POST /stock/photo` (with `DELIVERY_NOTE_BUSY` in place of
`STOCK_PHOTO_BUSY`), plus 404 `ORDER_NOT_FOUND`. In every case nothing was read and
nothing is stored. A person can always check the delivery by hand.

### Check a package's allergen label from a photo (#1175)

Served by `gateway/label_photo.py` (#1175); the photo is read by the Buyer worker
(`agent/label_service.py`), the words are mapped and compared by plain code
(`agent/label.py`). The prepared demo photo is `demo/label-photo.png`: the demo bakery's
cinnamon bun, whose "may contain" line names peanuts, which the demo kitchen excludes.
`POST /v1/kitchens/{kitchen_id}/orders/{order_id}/label/photo` reads one photo of
a delivered package's label with Nemotron 3.5 Super VL. Plain code compares the allergens
read with the kitchen's allergen rule and with the catalog row of the product. **The
answer is shown to a person and stored nowhere**: it never changes the catalog, the order
or the stock, and "unknown" in the catalog stays unknown.

Body: `{"image_base64": "...", "product_id": "462921"}`. Scope `kitchen:write`, the same
image limits as `POST /stock/photo`, and the order must be this kitchen's (404
`ORDER_NOT_FOUND`). `product_id` is a catalog product (404 `PRODUCT_NOT_FOUND`); it may be
a substitute that is not on the order (`in_order: false`). One read per kitchen at a time
(429 `LABEL_PHOTO_BUSY`).

The model copies, as printed:
- the product name and the EAN (barcode digits);
- the words emphasised as allergens in the ingredient list (bold or capitals);
- the allergen words of a "may contain" sentence (`voi sisältää`, `kan innehålla`, `may contain`);
- whether an allergen statement is printed at all.

Plain code maps each word to its GS1 code with a fixed table in Finnish, Swedish and English
(`maito` → `AM`, `vehnä` → `UW`, `manteli` → `SA`, `pähkinä` → `AN`, ...). The table matches
whole words and safe word starts only: `kookosmaito` is not `maito` and `munakoiso` is not
`muna`. The "may contain" phrase itself is removed first: `voi sisältää` starts with `voi`,
which alone means butter. **A word that is not in the table is "please check", never ignored.**

Answer:

```json
{
  "model": "nemotron-3.5-super-vl", "duration_ms": 3100,
  "order_id": "ord-...", "product_id": "462921", "in_order": true,
  "outcome": "EXCLUDED_ALLERGEN",
  "message": "The label declares peanuts, which this kitchen excludes. Do not use it; ask a person.",
  "product_check": "CONFIRMED_BY_EAN",
  "label": {"product_name": "...", "ean": "6408430000000",
            "contains": [{"word": "MAITO", "code": "AM"}],
            "may_contain": [{"word": "maapähkinää", "code": "AP"}],
            "unknown_words": []},
  "excluded_hits": [{"code": "AP", "level": "MAY_CONTAIN"}],
  "differences": [{"code": "AP", "kind": "LABEL_ADDS", "text": "The label lists peanuts (may contain); the catalog does not."}],
  "catalog_allergen_data": "KNOWN",
  "please_check": []
}
```

| Field | Rule |
|---|---|
| `outcome` | The first that applies: `EXCLUDED_ALLERGEN` (a code the kitchen excludes, as CONTAINS **or** MAY_CONTAIN, same as the search filter), `PLEASE_CHECK` (any reason below), `DIFFERS` (label and catalog differ), `CATALOG_UNKNOWN` (the catalog has no allergen data; the label is shown as read), `AGREES`. |
| `message` | One plain sentence for the page. `AGREES` says "The label we read agrees with the catalog. Read the label yourself before use." **There is no green or safe outcome**: a vision model can miss a word. |
| `product_check` | `CONFIRMED_BY_EAN` (the EAN read is one of the product's GTINs), `CONFIRMED_BY_NAME` (no EAN read, or the product has no GTIN, as an own product; at least 60% of the words of a catalog name of the product are on the label), `MISMATCH` (an EAN read that is not this product's), `NOT_CONFIRMED`. The last two are "please check: this may be another product". |
| `label.contains`, `label.may_contain` | The words as printed with their code; a word with no code is in `unknown_words` instead. |
| `excluded_hits` | Codes the label declares that the kitchen's rule excludes (groups expanded as in the order path, #741). |
| `differences` | Both directions, each with a sentence: `LABEL_ADDS` (on the label, not in the catalog) and `CATALOG_ADDS` ("The catalog lists milk; we did not read it on the label.", the more likely reader error). Empty when the catalog data is unknown. |
| `catalog_allergen_data` | `KNOWN` or `UNKNOWN` (from the catalog row; unknown is never "free from"). |
| `please_check` | Reasons: `NO_STATEMENT_READ` (no allergen statement found: never "no allergens"), `WORD_UNKNOWN`, `PRODUCT_MISMATCH`, `PRODUCT_NOT_CONFIRMED`. |

Errors: those of `POST /stock/photo`, plus 404 `ORDER_NOT_FOUND`, 404 `PRODUCT_NOT_FOUND`
and 429 `LABEL_PHOTO_BUSY`.

Audit: `label_photo_read` (actor the person, `order_id`, `product_id`, `outcome`,
`product_check`, the count of `excluded_hits`, `differences` and `please_check`,
`duration_ms`) or `label_photo_failed` (`code`, `duration_ms`). Never the photo or the
label's text.

### Plan from a menu photo (#1136)

Served by `gateway/menu_photo.py` (#1154, Maciek, #1136).
The web Planner page builds its "Plan from a menu photo" panel against this section with
the mock.

`POST /v1/kitchens/{kitchen_id}/menu-photo` reads one photo of a week's menu (a printed
sheet or a whiteboard) with Nemotron 3.5 Super VL. The model reads only
`[{day, dish, covers?}]`; it never gives a quantity. Plain code then matches each dish
to this kitchen's recipes (`GET /recipes`) by name. A dish that matches no recipe, or
two, is `NOT_KNOWN`: it is listed, never guessed. The matched dishes go to the menu-plan
window path ("Menu-plan window body" under "Creating a proposal"): the engine sizes
every line, and the answer holds a proposal that waits for a person in the inbox.
Nothing is approved or ordered. The route does not write the stored menu plan
(`PUT /menu-plans/{week}`): the read dishes stand in for the plan of those days only for
this one proposal.

- Scope `kitchen:write` and `kitchen:propose`: a signed-in `chef` or `approver`, or a
  kitchen API token with both scopes. The Buyer agent token is refused (403
  `SCOPE_REQUIRED`).
- One read per kitchen at a time: a second photo while one is being read answers 429
  `MENU_PHOTO_BUSY` and never reaches the model. Each read is one model call of up to
  75 s on shared credits. The gateway never retries it.
- Image limits: those of `POST /stock/photo` (PNG or JPEG, decided from the first bytes;
  at most 4 MB decoded; the whole body at most 6 MB). The web app scales a photo down to
  1600 px on the long side and sends JPEG.

Body (JSON):

```json
{"image_base64": "/9j/4AAQSkZJRgABAQ...", "from": "2026-11-16", "to": "2026-11-22",
 "requested_date": "2026-11-16", "idempotency_key": "web-menu-photo:6f1c..."}
```

| Field | Type | Rule |
|---|---|---|
| `image_base64` | string | The photo, base64. |
| `from`, `to` | `YYYY-MM-DD` | The week the menu is for, both days included. The rules of the menu-plan window body: `from` on or before `to`, at most 31 days apart, else 422 `INVALID_REQUEST`. A weekday the model reads ("Monday") is placed on its date in this window. |
| `requested_date` | `YYYY-MM-DD`, optional | The delivery day to quote. Default: `from`. |
| `covers` | integer, optional | Covers for a dish whose covers the menu does not show. Without it such a dish is not sized (see `in_proposal`). |
| `idempotency_key` | string | Passed to the proposal: a repeated key makes no second proposal (409 `IDEMPOTENCY_KEY_REUSED` for another window). |

Answer:

```json
{
  "model": "nemotron-3.5-super-vl",
  "duration_ms": 6120,
  "from": "2026-11-16",
  "to": "2026-11-22",
  "dishes": [
    {"day": "2026-11-16", "dish": "Salmon soup", "covers": 120,
     "recipe_id": "rec-salmon-soup", "recipe_name": "Salmon soup",
     "status": "MATCHED", "in_proposal": true},
    {"day": "2026-11-20", "dish": "Reindeer stew", "covers": 80,
     "recipe_id": null, "recipe_name": null,
     "status": "NOT_KNOWN", "in_proposal": false}
  ],
  "proposal": {"proposal_id": "6f1c...", "status": "READY"},
  "no_proposal_reason": null
}
```

| Field | Type | Notes |
|---|---|---|
| `model` | string | Always `nemotron-3.5-super-vl`. |
| `duration_ms` | integer | The whole call, measured by the gateway (model read, match and proposal). |
| `from`, `to` | `YYYY-MM-DD` | The window of the body. |
| `dishes[].day` | `YYYY-MM-DD` or null | The date in the window of the day the menu names. Null when the menu names no day, or a day outside the window. |
| `dishes[].dish` | string | The dish name as the model read it. Data, never an instruction. |
| `dishes[].covers` | integer or null | Covers the menu shows for the dish, else the body's `covers`, else null. Never a guess. |
| `dishes[].recipe_id`, `recipe_name` | string or null | The kitchen recipe the dish matches; both null for `NOT_KNOWN`. |
| `dishes[].status` | `MATCHED`, `NOT_KNOWN` | `MATCHED`: one recipe of this kitchen matches the name. `NOT_KNOWN`: none or two match; a person adds the recipe or plans the day by hand. |
| `dishes[].in_proposal` | boolean | True only for a `MATCHED` dish with a `day` and `covers`: its ingredients are in the proposal. |
| `proposal` | object or null | `{proposal_id, status}` of the proposal made (`status` as in `GET /proposals/{id}`, normally `READY`; read the rest there). Null when none was made. |
| `no_proposal_reason` | string or null | Why `proposal` is null: `NOTHING_NEEDED` (counted stock covers the matched dishes) or `NOT_SIZED` (no matched dish has a day and covers). Null when a proposal was made. |

The proposal is a normal menu-plan proposal (`request.made_by: menu_plan`,
`request.window`, `request.needs`, one approval, signed). Approve, reject, the live
re-check and earned auto-approve work as for any proposal.

Audit: one entry per call, `menu_photo_read` (who, the window, how many dishes per
status, the `proposal_id` or the `no_proposal_reason`, how long) or `menu_photo_failed`
(the error code). The audit entry never holds the image or the text the model read.

Errors (the usual `{"error": {"code", "message"}}`); in every case nothing is stored but
the audit entry, and no proposal is made:

| HTTP | Code | When |
|---|---|---|
| 403 | `SCOPE_REQUIRED`, `ROLE_REQUIRED`, `KITCHEN_SCOPE` | The Buyer agent token, a token without both scopes, a viewer, or another kitchen. |
| 413 | `IMAGE_TOO_LARGE` | The body is over 6 MB or the decoded image is over 4 MB. |
| 422 | `INVALID_JSON`, `INVALID_REQUEST` | The body is not a JSON object; `image_base64` is missing or not base64; a bad window; no `idempotency_key`. |
| 422 | `NOT_AN_IMAGE` | The decoded bytes are not PNG or JPEG. |
| 422 | `NOTHING_MATCHED` | The model read no dish, or no dish matches a recipe of this kitchen. `error.dishes` lists the dishes read (the `dishes[]` shape), so a person sees what was not known. |
| 429 | `MENU_PHOTO_BUSY` | A menu photo for this kitchen is still being read; try again when it ends. |
| 502 | `VISION_REPLY_INVALID` | The model answered outside the strict schema. Nothing is repaired or guessed. |
| 503 | `VISION_NOT_CONFIGURED` | The server has no vision worker or no model key. |
| 503 | `VISION_UNAVAILABLE` | The worker or the model could not be reached, or answered with an error. |
| 504 | `VISION_TIMEOUT` | The model did not answer in time. |

A person can always plan the week by hand on the Planner page; no error blocks
`PUT /menu-plans/{week}` or "Propose order for this week".

### Read a supplier's price list from a photo (#1174)

Served by `gateway/price_list_photo.py` (#1174); the photo is read by the Buyer worker
(`agent/price_list_service.py`), the texts by plain code (`agent/price_list.py`).
The prepared demo photo is `demo/price-list-photo.png` (Corner Bakery).
`POST /v1/kitchens/{kitchen_id}/suppliers/{supplier_id}/price-list/photo` reads
one photo of a supplier's price list (paper, or a screenshot of a PDF) with Nemotron 3.5
Super VL into **draft** own products. A person checks every row and saves it with the
own-product routes (`POST /products`, `PUT /products/{id}`). **This route writes nothing**:
no product, no price, no stock.

- Scope `kitchen:write`. The Buyer agent token is refused (403 `SCOPE_REQUIRED`).
- The supplier must be one of this kitchen's suppliers (404 `SUPPLIER_NOT_FOUND`) with
  adapter `manual` or `csv` (422 `SUPPLIER_HAS_API`): Valio's prices come from its API.
- One read per kitchen at a time (429 `PRICE_LIST_BUSY`). One model call of up to 75 s;
  the gateway never retries it.
- Image limits and body: those of `POST /stock/photo` (`{"image_base64": "..."}`).

The model copies only what is printed: per row the product name, the price, the unit the
price is for, the pack size, and per list the currency and the VAT note. Plain code reads
those texts. The model never converts, completes or guesses.

Answer:

```json
{
  "model": "nemotron-3.5-super-vl", "duration_ms": 5200,
  "supplier_id": "sup-bakery", "currency": "EUR", "vat": "INCLUDED",
  "truncated": false,
  "rows": [
    {"name": "Rye sourdough loaf 800 g", "price_text": "4,40 €", "price_unit_text": "kpl",
     "pack_text": "800 g", "status": "READ", "reasons": [],
     "draft": {"name": "Rye sourdough loaf 800 g", "supplier_id": "sup-bakery", "unit": "ST",
               "base_unit": "KG", "pack_size_in_base_units": "0.8", "unit_price_eur": "4.40",
               "price_source": "price_list_photo", "allergen_data": "UNKNOWN", "allergens": []},
     "match": {"product_id": "own-rye-loaf", "name": "Rye sourdough loaf 800 g",
               "unit_price_eur": "4.20", "kind": "PRICE_CHANGED"}},
    {"name": "Seed rolls", "price_text": "0,95", "price_unit_text": null, "pack_text": null,
     "status": "PLEASE_CHECK", "reasons": ["PRICE_UNIT_MISSING"],
     "draft": {"name": "Seed rolls", "supplier_id": "sup-bakery", "unit": null,
               "base_unit": null, "pack_size_in_base_units": null, "unit_price_eur": null,
               "price_source": "price_list_photo", "allergen_data": "UNKNOWN", "allergens": []},
     "match": null}
  ]
}
```

| Field | Rule |
|---|---|
| `currency` | `EUR` when the list or the row prints `€` or `EUR`; else null. |
| `vat` | `INCLUDED` (`sis. alv`, `incl. VAT`, `inkl. moms`), `EXCLUDED` (`alv 0 %`, `excl. VAT`, `+ alv`, `exkl. moms`) or null when the list does not say. Never assumed. |
| `truncated` | True when the photo had more than 40 rows; only the first 40 are in `rows`. |
| `rows[].name`, `price_text`, `price_unit_text`, `pack_text` | Copied as printed; null when not printed or unreadable. |
| `rows[].status` | `READ` or `PLEASE_CHECK`. |
| `rows[].reasons` | Why a row needs a person, below. Empty for `READ`. |
| `rows[].draft` | An own-product body for `POST /products`, never sent by this route. `unit_price_eur` is null when the price cannot be trusted. `allergen_data` is always `UNKNOWN`: a price list says nothing safe about allergens. |
| `rows[].match` | A suggestion only: an existing own product of this supplier with the same name (case and spaces ignored), its stored price, and `kind` `SAME` or `PRICE_CHANGED` (null when the read price is
empty, so there is nothing to compare). Null when none, or when two own products have that name. The person picks; nothing is overwritten (`PUT` is the person's own action). |

Reasons (`rows[].reasons`):

| Reason | When | Price in the draft |
|---|---|---|
| `NAME_UNREADABLE` | No name was read. | empty |
| `PRICE_UNREADABLE` | No price, or not a positive number (`2,50` is 2.50). | empty |
| `PRICE_UNIT_MISSING` | The unit the price is for is not printed next to it. | empty |
| `UNIT_UNKNOWN` | The printed unit is not one we know (`kpl`, `pcs`, `st` → `ST`; `kg` → `KG`; `l`, `ltr` → `L`; `ltk`, `laatikko`, `box` → `KI`; `pussi`, `bag` → `BAG`). | empty |
| `CURRENCY_UNKNOWN` | Neither the row nor the list prints `€` or `EUR`. | empty |
| `PACK_UNCLEAR` | A pack size is printed but cannot be read as g, kg, ml, cl, dl or l. | kept; pack fields empty |
| `VAT_UNKNOWN` | The list does not say whether prices include VAT. | kept |

Errors: those of `POST /stock/photo` (413, 422 `NOT_AN_IMAGE`, 502 `VISION_REPLY_INVALID`,
503, 504), plus 404 `SUPPLIER_NOT_FOUND`, 422 `SUPPLIER_HAS_API` and 429
`PRICE_LIST_BUSY`.

Audit: `price_list_photo_read` (actor the person, `supplier_id`, the count of `READ` and
`PLEASE_CHECK` rows, `truncated`, `duration_ms`) or `price_list_photo_failed` (`code`,
`duration_ms`). Never the photo, the names or the prices.

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
`idempotency_key` like every mutation (422 `INVALID_REQUEST` without it); the same key
answers the stored result again.

- Only a person with the role `approver` can call them: 403 `HUMAN_SESSION_REQUIRED` for
  a token or the agent, 403 `ROLE_REQUIRED` for another role.
- Each tamper, and each restore that put a row back, writes an audit entry after the
  edit: `kind` `audit_demo_tamper` or `audit_demo_restore`, `actor` (the person) and
  `tampered_seq`. So the tampered entry is not the newest one, and `length` after a
  restore is two more than before the demo.

- Only the synthetic demo kitchen (`demo-kitchen`) can be tampered. Any other kitchen
  gets 403 `DEMO_ONLY`. This is a demonstration that a change is detected; the audit
  log has no other way to change or delete an entry.
- A forgotten tamper heals itself: the next `/audit/verify` (from any kitchen) or
  `/audit/demo-tamper` restores a tampered row that is older than 10 minutes.
- One tampered row at a time: a second tamper before a restore is 409 `ALREADY_TAMPERED`.
  A demo kitchen without audit entries is 409 `NOTHING_TO_TAMPER`.

`GET /audit/chain?limit=5` answers this kitchen's newest `limit` entries (1 to 100,
default 20; else 422 `INVALID_REQUEST`), oldest first:

```json
{"entries": [{"seq": 412, "prev_hash": "9f2c...", "hash": "41ab...",
              "event": {"seq": 412, "event_id": "...", "kind": "order_placed", "actor": "aron", "at": "..."}}]}
```

- `event` is the entry exactly as `GET /audit` answers it. `hash` and `prev_hash` are
  the stored SHA-256 values (64 hex characters). `seq` counts the shared chain, so one
  kitchen's rows can skip numbers.
- A tampered entry shows its edited `event` with its old `hash`: this route shows what
  is stored, `/audit/verify` says whether it still fits.

`GET /events` is a `text/event-stream`. Each message:

```
event: proposal
data: {"operation": "insert", "document": {"proposal_id": "...", "status": "READY"}}
```

- `event` is `proposal`, `approval` or `audit`. `operation` is `insert`, `update` or
  `replace`. `document` is the whole row after the change, in the shape the matching
  read route returns (`GET /proposals/{id}`, the approval row, a `GET /audit` entry).
- Only this kitchen's rows are sent. The stream starts with the comment `: connected`.
  A comment line (`: ping`) arrives after 5 seconds without a message, so a dropped
  connection is noticed.
- A `proposal` whose offer cannot be read arrives as `{"proposal_id", "status"}` only;
  the client loads the rest with `GET /proposals/{id}`.
- The gateway ends a stream after 10 minutes. That is not an error: the client connects
  again, as after any drop.
- 503 `EVENTS_UNAVAILABLE` instead of a stream: the database has no change streams (a
  standalone MongoDB; Atlas has them), or 16 streams are open on the gateway already.
  The screens then work without live updates.
- The tamper demo shows on the stream: the tamper is an `audit` message with
  `operation: "update"`, the restore one with `operation: "replace"`.
- Nothing is replayed after a reconnect: the client loads the lists again, then listens.
- The browser's `EventSource` cannot send an `Authorization` header; the web client
  reads the stream with `fetch`.

**Conformance kit (#609).** `python -m gateway.conformance --base-url <gateway> --token
<token> [--kitchen demo-kitchen] [--markdown | --json]` checks a running gateway's trust
rules with an agent-level token. It places no order and opens no approval. Thirteen checks,
C01 to C13: `/health` answers; no token is 401; `GET /permissions` is served; the
gateway sizes the order from the stored need and ignores a model quantity;
`simulate_order` returns the offer's total with a verdict; `place_order` without a human
approval is 403 `NEEDS_APPROVAL`; the token cannot approve or reject (403) or create
tokens (403); no cancel or edit route exists for an order (404 or 405); a kitchen token
reading another kitchen is 403 `KITCHEN_SCOPE` (skipped for a server agent token); an
unknown offer is 404 `OFFER_NOT_FOUND`; the MCP tool list of this token has no approve,
reject or cancel tool; the hidden `approve_proposal` tool called by name is refused with
403 (C13). A check is PASS, FAIL or SKIP; any FAIL gives exit code 1.

### Model usage (#365)

`GET /v1/kitchens/{kitchen_id}/model-usage` (`kitchen:read`) sums the `buyer_usage` of
this kitchen's Buyer runs (`db.agent_runs`, one row per free-text `POST /proposals` that
reached the Buyer worker):

```json
{"model": "nemotron-3.5-super-vl", "since": "2026-11-14T18:02:11+00:00",
 "runs": 14, "finished_runs": 11, "runs_without_usage": 5,
 "model_calls": 63, "prompt_tokens": 371250, "completion_tokens": 16470,
 "reasoning_tokens": 0, "model_seconds": "345.7",
 "last_run_at": "2026-11-14T22:40:03+00:00"}
```

- `runs`: every Buyer run of the kitchen. `finished_runs`: the runs that ended with a
  proposal (state `READY`).
- `runs_without_usage`: the runs that carry no `buyer_usage`: a run from before the
  meter, a run that did not end with a proposal, a run that is not finished yet. The
  five sums below count only the other runs, so `runs - runs_without_usage` is the
  number of runs behind them.
- `model_calls`, `prompt_tokens`, `completion_tokens`, `reasoning_tokens`: integers.
  `reasoning_tokens` is a part of `completion_tokens`. A count that is missing or is not
  a whole number of 0 or more adds 0.
- `model_seconds`: a decimal string with one decimal, the time the model calls took.
- `since` and `last_run_at`: when the oldest counted run started and when the newest
  counted run finished, UTC. Both `null` when no run is counted.
- A kitchen with no runs gets the same shape: every count `0`, `model_seconds` `"0.0"`,
  both times `null`. Never a 404.
- `model` is the Buyer's model name, the same value as `buyer_model` on a proposal answer.
- Counts only: no request text, no reply text, no key.
- Where it shows: the About page.

### Atlas facts (proposed, #1393)

`GET /v1/kitchens/{kitchen_id}/atlas` (`kitchen:read`) answers what MongoDB Atlas holds
and runs for the product, read live. Proposed: the store function exists
(`store.atlas.atlas_facts`); the gateway route is not built yet (#1383).

```json
{"mongodb_version": "8.0.37", "data_mb": 215, "products": 17548,
 "vectors": [{"model": "voyage-4", "dimensions": 1024, "count": 17546}],
 "search_indexes": [
   {"name": "products_search", "type": "search", "status": "READY", "queryable": true},
   {"name": "products_vector", "type": "vectorSearch", "status": "READY", "queryable": true}],
 "time_series": [{"collection": "covers", "documents": 1780},
                 {"collection": "orders_history", "documents": 1050}],
 "audit_entries": 1487,
 "change_stream_collections": ["proposals", "approvals", "audit_log"]}
```

- The numbers are for the whole database, the same for every kitchen: counts and index
  states only. No address, no key, no document, no other kitchen's rows.
- **Unknown is `null`, never zero.** Each top-level value except
  `change_stream_collections` is `null` when it could not be read; the page then shows no
  number for it. An empty list was read and is empty.
- `data_mb`: data plus indexes, whole megabytes. `products`: rows the text search reads.
- `vectors`: one row per embedding model and size, largest first. Two rows mean the
  vectors are being replaced; the page shows both.
- `search_indexes`: `type` is `search` (Atlas Search) or `vectorSearch` (Atlas Vector
  Search); `status` is Atlas's own word (`READY`, `PENDING`, `BUILDING`, `FAILED`, ...).
- `time_series`: the time-series collections behind forecasts and the drift aggregation.
- `audit_entries`: the length of the hash-chained audit log, all kitchens.
- `change_stream_collections`: the collections the live event stream (`/events`) watches.
- The gateway keeps the answer for a minute. Never a 404 for a kitchen the session may read.
- Where it shows: the About page (#1383, #1292).

### Standing-order drift

`GET /v1/kitchens/{kitchen_id}/drift` answers `{"week": "2026-11-09", "warnings": [...]}`,
biggest change first. `week` is the Monday of the last full week. Each warning:

```json
{"product_id": "462775", "kind": "portion_creep", "change": 0.4, "unit": "ST",
 "qty_per_100": 14.0, "baseline_qty": 10.0, "spend_per_100": 35.98,
 "baseline_spend": 25.7, "baseline_weeks": 4,
 "why": "14.0 ST per 100 guests last week, 10.0 on average over the 4 weeks before (+40%). Check portions before this order renews."}
```

- `kind`: `portion_creep` (more ordered per guest) or `cost_creep` (the same amount per
  guest costs more). A drop is not a warning.
- Fewer than 3 weeks of history, or a week without guests, is never drift: it is left out.
- `week` is always there, also with `"warnings": []`. A warning has `product_name` when
  the catalog knows the product; on the supplier route also `kitchen_id` and
  `kitchen_name` (`null` when the kitchen has no name).
- When the database cannot run the aggregation: 503 `DRIFT_UNAVAILABLE`. The screens
  then hide the drift tile; they never show an empty list as "no drift".
- Rates are per 100 guests from the `covers` series; money values are numbers for display
  only, never a figure to approve (approval figures come from `simulate_order`).
- Where it shows: a warning on the next proposal for that product, and a list on the
  supplier demand view (consenting kitchens only).

### Webhooks

Served for the kitchen side (#277, `gateway/webhooks.py`). An approver registers an https
URL for one kitchen. Routes are in the kitchen table; all five need a human session of an
approver.

`POST /v1/kitchens/{kitchen_id}/webhooks`, body `{"url": "https://...", "events": [...]}`.
Answer: `webhook_id`, `url`, `events`, `created_at`, `created_by`, and `secret`
(`whsec_...`). The secret is in this answer only; the list never shows it. At most 10
webhooks per kitchen. Create and delete are audit entries (`webhook_created`,
`webhook_deleted`). `GET .../webhooks` answers `{"webhooks": [...], "events": [...]}`
(the events one can subscribe to). These routes take no `idempotency_key`.

Events: `proposal.ready`, `proposal.approved`, `proposal.rejected`, `order.placed`,
`total_mismatch`, `recall.alert`, `supplier.offer`, `agent.refused` and `delivery.checked`
(the last three since #1188: #1281, #1329). They come from the audit trail, so a webhook
says what the audit log says. `ping` is sent only by `POST .../webhooks/{id}/test`; it is not a subscription. A
webhook gets only the events it names; the web form ticks `proposal.ready` and
`recall.alert` for a new webhook and offers the others unticked.

Bodies (`data`) of the three newer events and of the second `recall.alert` case (#1362),
all served. Each holds only fields of its audit entry:

| Event | From the audit kind | `data` | Sent |
|---|---|---|---|
| `supplier.offer` | `supplier_offer_received`, `supplier_offer_accepted`, `supplier_offer_declined` (#374) | `step` (`RECEIVED`, `ACCEPTED`, `DECLINED`), `offer_id`, `supplier_id`, `product_id`, `replaces_product_id`, `requested_date`, `quantity`, `unit`; `proposal_id` when accepted. Never the supplier's reason text. | Once per offer and step, also when the offer is written by the selling agent's one-off command (`python -m agent.seller --apply`): that command waits for its deliveries before it exits. |
| `agent.refused` | `refused` (#548) | `actor`, `code` (for example `HUMAN_SESSION_REQUIRED`), `method`, `route`: the route **pattern**, such as `/v1/kitchens/{kitchen_id}/approvals/{approval_id}/approve`, never the path with ids. | At most one delivery per webhook, actor and code a minute; more refusals in that minute stay in the audit log only. |
| `delivery.checked` | `delivery_note_read` (#362) | `order_id`, `statuses` (count per line status), `complete`, `needs_approval` (substitute lines waiting for a person), `duration_ms`. Never the photo or the note's text. | Once per read. |
| `recall.alert`, case `FOUND` (#1187) | the recall alert of a check (`POST /recalls/check`) | `case: "FOUND"`, `recall_event_id`, `product_id`, `product_name`, `match` (`exact`, `possible`, `review`), `found`: `{stock: true/false, recipes: <count>, open_proposal: true/false}`, `notice_url`, `next_step`. | When a check finds a recalled product in this kitchen's stock or recipes, also when no open proposal holds it. **Once per webhook and recall alert**: an alert stored before the webhook existed is sent at the next check; every later check sends nothing for it. A check inside the 60 s cooldown sends nothing. |

The existing `recall.alert` for a blocked proposal (`recall_proposal_blocked`) keeps its
body and gains `case: "PROPOSAL_BLOCKED"`.

A delivery is one JSON POST:

```json
{"id": "<delivery_id>", "event": "order.placed", "kitchen_id": "demo-kitchen",
 "at": "2026-11-14T02:10:00+00:00", "data": {"...": "..."}}
```

- Headers: `X-TKB-Event` (the event), `X-TKB-Delivery` (= `id`) and
  `X-TKB-Signature: sha256=<hex>`.
- The signature is the HMAC-SHA256 of the raw body with the webhook secret. A receiver
  checks it (constant-time compare) before it trusts the body. A repeat `id` is a replay.
- Any 2xx is a success. Else the gateway tries again: at most 3 attempts, 3 seconds
  each, short backoff. Deliveries run in the background; a slow or broken receiver never
  delays or fails an order.
- Delivery row (`/test` and `/deliveries`): `delivery_id`, `event`, `at`, `attempts`,
  `status` (HTTP status or null), `ok`, `error` (an error class name or null). Never a
  body.
- The URL must be https. Private, loopback and link-local addresses and internal host
  names are refused, at registration and again at delivery; redirects are not followed.
  `GATEWAY_WEBHOOKS_DEV=true` allows `http://localhost` for a developer's own machine,
  never in production.

| Status | Code | When |
|---|---|---|
| 403 | `HUMAN_SESSION_REQUIRED` | The caller is not a person (a token or the agent). |
| 403 | `ROLE_REQUIRED` | The person is not an `approver`. |
| 404 | `WEBHOOK_NOT_FOUND` | No such webhook in this kitchen. |
| 422 | `INVALID_REQUEST` | A bad URL, no event or an unknown event, or already 10 webhooks. |
| 502 | `WEBHOOK_TEST_FAILED` | The test ping could not be sent. |

Delivery resolves the receiver's host once, refuses it when any address is private,
loopback or link-local, and connects to that checked address. The `Host` header and the
TLS name (SNI and the certificate check) stay the host name, so a second DNS answer
(DNS rebinding) can never redirect a delivery to an internal address (#562).

Supplier-side events (`price.changed`, `demand.changed`) are not served yet.

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
  "price_source": "entered",
  "allergens": [{"code": "AW", "level": "CONTAINS"}],
  "allergen_data": "ENTERED"
}
```

- `price_source` is `entered` (typed in by a person, the default) or `price_list_photo`
  (read from a photo of the supplier's price list and checked by a person, #1174). It
  says where `unit_price_eur` came from; it never changes how the price is used. A
  change of `unit_price_eur` without `price_source` sets it back to `entered`.
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

One record per kitchen and supplier. `GET /sharing` returns `{"sharing": [...]}`.
`PUT /sharing` with `{supplier_id, share_forecast}` grants or revokes one supplier and
returns the whole list. A missing `supplier_id` or a `share_forecast` that is not a
boolean is 422 `INVALID_REQUEST`.

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
  "certainty_premium_max": "3",
  "excluded_allergens": ["AP", "AN", "AS"],
  "standing_orders": {"469549": "200"}
}
```

| Field | Type | Rule |
|---|---|---|
| `service_level` | `{A, B, C}` of decimal strings | A fraction above 0 and below 1 per demand class (A = menu-critical). The UI shows percent: 97.5 % is `"0.975"`. A value of 0, 1 or more is a 422. |
| `max_cover_days` | object of integers | Never order more than this many days of cover. Keys are the engine's categories: `fresh_dairy`, `vegetables`, `meat`, `fish`, `frozen`, `dry`, `other`. Each at least 1. Another key is a 422, never ignored. |
| `stockout_cap` | decimal string | Demand seen during a stock-out is scaled up by at most this factor. From 1 to 3. |
| `budget_warning_order_eur`, `budget_warning_week_eur` | decimal string or null | Above it the approval shows `OVER_BUDGET_WARNING`. `null` means no warning. A warning only: a person approves every order anyway. |
| `certainty_premium_max` | decimal string or null | How much more the kitchen pays for stock the supplier confirms: the main plan uses a confirmed-stock offer only when its price per litre or kilo is at most this many times the cheapest orderable price. At least `1`; default `3`; `null` means no limit. A dearer confirmed offer is left out of the plan and listed in `excluded` with the two prices. When leaving it out would make the order short, it stays and the plan carries `CERTAINTY_PREMIUM_HIGH`. Engine default until `store/` saves it and the settings page shows it. |
| `excluded_allergens` | string[] or null | GS1 codes or the allergen names of `search_products`. A product that lists one as CONTAINS, MAY_CONTAIN or UNDECLARED is refused. `[]` means the kitchen has explicitly no exclusions. `null` means nobody has set the policy yet: unknown, not "none". |
| `standing_orders` | object of decimal strings | Per `product_id`: the kitchen's standing order per delivery, in that product's sales unit. `{}` means none. The engine only flags a standing order more than 10 % off the need (`STANDING_ORDER_DRIFT`, S08); a person changes it. |
| `approve_unconfirmed_manual` | boolean | Redundant since 2026-11-14 (Aron): still stored and returned, and another type is still a 422, but approval no longer reads it. A person may approve any proposal with unknown-stock lines, from any supplier, Valio too; the order then names those suppliers in `supplier_must_confirm` and waits for their confirmation. Earned auto-approve never applies to these lines: it refuses every unknown-stock line. Off by default (#631); absent from `GET` until a person sets it. |

`PUT /settings` takes any subset of these fields plus `idempotency_key`. A field that is
left out keeps its value, so a partial save can never drop the allergen policy.
`excluded_allergens` cannot be set back to `null`. A `standing_orders` in the body
replaces the whole map; it never merges with the stored one. Send `{}` to clear every
standing order; to drop one product, send the map without it. Each value must be a
positive decimal string; 0, a negative number or another type is a 422. The answer is
the full settings as `GET` returns them.

- Only a human user session of an approver may change settings; an API key or the
  Buyer's token gets 403 `HUMAN_SESSION_REQUIRED`, a chef or viewer 403 `ROLE_REQUIRED`.
  The settings decide what the Buyer may propose, so the Buyer cannot relax them.
- Each change writes one audit entry `settings_changed` with the user and, per changed
  field, the value before and after.
- The web client maps its own names to these: `serviceLevelPercent` (percent) to
  `service_level` (fraction), `maxDaysOfCover` to `max_cover_days`, `stockOutDemandCap`
  to `stockout_cap`, `budgetWarningPerOrderExVat` / `budgetWarningPerWeekExVat` to the
  two budget fields, `excludedAllergens` to `excluded_allergens`.

### Onboarding lookup (Context.dev)

`POST /v1/onboarding/lookup` (human user session). On sign-up the kitchen types its work
email or its website; the gateway looks the business up with Context.dev and returns the
profile fields to pre-fill. Served by the gateway (`gateway/onboarding.py`, #602). For
now `opening_hours` is always `null`: the optional `/v1/web/scrape` call is not made.
A caller that is not a person gets 403 `HUMAN_SESSION_REQUIRED`. The web client calls
this route through `lookupKitchenBrand` in `web/src/api/http-onboarding.ts`; a 429 (the
paid-lookup limit) shows on the page as `RATE_LIMITED`.

Request: exactly one of the two fields. A POST, so the email never sits in a URL or an
access log. It saves nothing, so it takes no `idempotency_key`.

```json
{"email": "chef@hotelkuusi.fi"}
{"website": "https://www.hotelkuusi.fi"}
```

Response: every field is `{value, source}`. `value` `null` means unknown: Context.dev did
not return it, and the gateway never guesses one. `source` is `null` exactly when `value`
is.

```json
{
  "domain": "hotelkuusi.fi",
  "found": true,
  "name": {"value": "Hotel Kuusi",
           "source": {"provider": "Context.dev", "endpoint": "POST /v1/brand/retrieve"}},
  "logo_url": {"value": "https://...", "source": {"...": "..."}},
  "colors": {"value": ["#1f4d3a", "#e9d8a6"], "source": {"...": "..."}},
  "address": {"value": {"street": "Satakunnankatu 41", "postal_code": "33210",
                        "city": "Tampere", "country": "Finland"}, "source": {"...": "..."}},
  "kitchen_type": {"value": "hotel", "source": {"...": "..."}},
  "opening_hours": {"value": null, "source": null}
}
```

| Field | From Context.dev | Rule |
|---|---|---|
| `domain` | | The domain the lookup used: from the email after `@`, or the website's host without `www.`. |
| `found` | | `false` when Context.dev knows nothing about the domain (its 400 `NOT_FOUND`): 200 with every field unknown, so the person fills in the form. |
| `name` | `brand.title` | |
| `logo_url` | `brand.logos[]` | An https URL. Prefer `type` `icon` or `logo` in light `mode`; `null` when there is none. |
| `colors` | `brand.colors[].hex` | `#rrggbb`, main colour first. `null` when there are none, never `[]`. |
| `address` | `brand.address` | `street`, `postal_code`, `city`, `country`; a part Context.dev leaves out is `null` on its own. |
| `kitchen_type` | `brand.industries.eic[]` | `hotel`, `school`, `hospital` or `restaurant` when the industry or subindustry clearly says so (hotels and accommodation, primary or secondary education, hospitals and health care, restaurants and food service). Anything else is `null`. A guess; the person confirms it. |
| `opening_hours` | not in `brand/retrieve` | Free text as the website writes it. Optional second call: `POST /v1/web/scrape` (the endpoint `monitor/recalls.py` uses) on the home or contact page, reading schema.org `openingHours`. Without it, `null`. `source.endpoint` names whichever endpoint gave the value. |

Which Context.dev endpoint, and why:

- `POST https://api.context.dev/v1/brand/retrieve` with `{"type": "by_email", "email": ...}`
  or `{"type": "by_domain", "domain": ...}`. One call returns name, logos, colours, address
  and industry (EIC), which is every field but the opening hours. `by_email` resolves the
  work email's domain for us; that is the sponsor's own example ("brand itself from a
  customer's email"). `/brand/styleguide` (fonts, spacing) and `/brand/search` (name
  autocomplete) are not needed for the form.
- Context.dev answers a free or disposable email with 422 `FREE_EMAIL_DETECTED` /
  `DISPOSABLE_EMAIL_DETECTED`. The gateway returns 422 `FREE_EMAIL` with "Type the
  kitchen's website instead."; the page then asks for the website.
- An address that is neither an email nor a domain: 422 `INVALID_QUERY`. Context.dev down,
  out of credits or slow (a cold domain can take more than 10 s; use a timeout of at least
  10,000 ms): 502 `LOOKUP_UNAVAILABLE`. The page shows a blank form in both cases.
- Too many lookups (#604): 429 `LOOKUP_RATE_LIMITED`, with a `Retry-After` header (whole
  seconds) and the same number in the body:
  `{"error": {"code": "LOOKUP_RATE_LIMITED", "message": "...", "retry_after_s": 42}}`.
  The limit is 10 Context.dev calls per 60 seconds per caller: a signed-in person by
  account, anyone else (the open demo's shared token) by client address
  (`ONBOARDING_RATE_LIMIT`, `ONBOARDING_RATE_WINDOW_S`). Only a lookup that would call
  Context.dev counts; a bad query (422) and an answer from the cache do not. A 429 is
  never an empty profile: the page shows a blank form and says the lookup is busy.

Rules:

- `CONTEXT_DEV_API_KEY` stays on the gateway (the same key as the recall monitor). The
  browser calls our route, never Context.dev.
- Nothing is saved by this route. The person checks every field, changes what is wrong
  and presses "Confirm and save"; only then is the profile stored. Until the kitchen
  profile has a save route, the web keeps the confirmed profile in the browser and shows
  the logo in the app shell.
- "Nothing is saved" means no database write. The gateway process keeps the answer for a
  domain in memory for a short time (#604), so the same domain asked again makes no second
  paid Context.dev call: 10 minutes for a found brand (`ONBOARDING_CACHE_TTL_S`), 1 minute
  for `found: false` (`ONBOARDING_CACHE_NOT_FOUND_TTL_S`). An email lookup and a website
  lookup of one domain are kept apart, and the email itself is not kept. An error (502,
  422) is never kept. The answer has the same shape either way; a restart of the gateway
  empties the memory.
- Every pre-filled field shows "From your website via Context.dev" and its
  `source.endpoint` until the person edits it.
- The web client maps `logo_url` to `logoUrl`, `kitchen_type` to `kitchenType`,
  `opening_hours` to `openingHours` and `postal_code` to `postalCode`.

### Product pictures: kind icons and brand logos (Context.dev)

The Valio catalog and its API have no product photo (`synkkaData.medias[]` holds ids
only, no URL). Photos from the web are not copied: that is a copyright risk. So a
product shows one of two pictures, and both are honest about what they are:

1. **A kind icon.** `ProductThumb`
   (`web/src/components/purchasing/product-thumb.tsx`) uses
   `web/src/lib/product-picture.ts` to read the product's English and Finnish names
   and choose a Lucide icon on a tile tinted for its kind. These are icons, not
   emoji, and represent only the kind, never an actual pack photo. A name matching
   no rule gets the plain `Package` icon. This needs no route.
2. **The brand logo, when it is known.** `brand` on the product row (from
   `synkkaData.brand`) is looked up with Context.dev and the answer is kept in
   MongoDB (`brand_logos`, through `store/`). The logo replaces the icon.

`GET /v1/brands/logos?name=Valio&name=Arla` (`kitchen:read`). One to 50 `name`
parameters (repeat the parameter; a brand can hold a comma). Each name is trimmed;
no name, an empty name, more than 50 names or a name longer than 100 characters is
422 `INVALID_REQUEST`. The answer has one row per distinct name, in the order asked:

```json
{"logos": [
  {"brand": "Valio", "status": "found", "logo_url": "https://media.brand.dev/....png",
   "background": "own", "domain": "valio.fi", "checked_at": "2026-11-14T20:00:00+00:00",
   "source": {"provider": "Context.dev", "endpoint": "POST /v1/brand/retrieve"}},
  {"brand": "HK", "status": "none", "logo_url": null, "background": null, "domain": null,
   "checked_at": "2026-11-14T20:00:00+00:00", "source": null},
  {"brand": "Arla", "status": "not_checked", "logo_url": null, "background": null,
   "domain": null, "checked_at": null, "source": null}
]}
```

| Field | Notes |
|---|---|
| `status` | `found`: a logo is known. `none`: Context.dev was asked (or the name cannot be asked) and there is no logo that matches the brand; this is kept and never asked again. `not_checked`: nobody has asked yet. |
| `logo_url` | An https URL from Context.dev's answer, or `null`. |
| `background` | What the logo needs behind it: `light`, `dark`, or `own` (the image has its own background). `null` without a logo. |
| `domain` | The brand's website as Context.dev found it, so a person can see which company the logo belongs to. `null` without a logo. |
| `checked_at` | When Context.dev was asked; `null` for `not_checked`. |

Rules:

- **This route never calls Context.dev.** It reads `brand_logos` only, so a page view or
  a search on the open demo spends no credits. A database error is 503
  `LOGOS_UNAVAILABLE`; the web then shows the kind icons.
- **Context.dev is asked only by an operator**, once per brand, with a capped command:
  `python -m gateway.brand_logos --limit 20` (default 10, at most 30 per run). It takes
  the catalog brands with the most products that have no row yet, or the brands named
  with `--brand`. It stops early when Context.dev says fewer than 300 credits remain
  (the recall monitor and the onboarding lookup use the same key), on a 401, 402 or
  429, and after three failed calls in a row. A failed call (network, timeout, 5xx)
  stores nothing, so the brand stays `not_checked`. Without `CONTEXT_DEV_API_KEY` it
  calls nothing.
- The lookup is `POST /v1/brand/retrieve` with `{"type": "by_name", "name": <brand>,
  "country_gl": "fi"}`: the catalog has brand names, not domains. A name shorter than
  3 or longer than 30 characters cannot be asked (Context.dev's limits): it is stored
  as `none` without a call.
- **A logo is kept only when the answer matches the brand**, because a name can be
  ambiguous: the brand name, lower case with everything but letters and digits removed,
  must equal Context.dev's `title` treated the same way, or the first label of its
  `domain` ("Santa Maria" matches the title "SantaMaria"; "Valio" matches `valio.fi`).
  Anything else, and Context.dev's 400 `NOT_FOUND`, is stored as `none`.
- The logo picked, from `brand.logos[]` with an https URL: an `icon` with its own
  background, then an `icon` and then a `logo` for a light background, then the same
  for a dark background, then a `logo` with its own background.
- The web client maps `logo_url` to `logoUrl` and `checked_at` to `checkedAt`. It shows a
  logo only for `status` `found` with an https URL, with `alt` "<brand> logo" and the
  `domain` as its title. A failed call or a broken image shows the kind icon. The
  browser loads the image from Context.dev's host; the gateway never fetches it.

### Recall alerts (Context.dev)

The recall monitor (`monitor/recalls.py`) reads the Ruokavirasto recall list with
Context.dev `POST /v1/web/scrape`. `monitor/proposals.py` matches the notices to what the
kitchen has: its newest stock count, its recipes and the lines of its open proposals
(`store/recalls.py` `context`). A recalled line puts an open proposal on hold and the Buyer
plans a separate replacement proposal. A recalled product that is only in stock or in a
recipe gives an alert with no proposal. These two routes show that state and let a person run a
check now. They are views: they keep no second recall store and no second matching logic.
The code is `gateway/recalls_view.py`.

**One source for the alert fields:** [recall-contract.md](recall-contract.md) ("Exact alert
fields"). The same document holds the hold, the replacement proposal, the reject and the
dismiss route. This section only adds what the two routes add.

`GET /v1/kitchens/{kitchen_id}/recalls` and `POST /v1/kitchens/{kitchen_id}/recalls/check`
both answer:

```json
{
  "last_check": {
    "checked_at": "2026-11-14T04:30:00+00:00",
    "checked_by": "chef@hotel.example",
    "source": "recording",
    "live_error": "NO_KEY",
    "fetched_at": "2026-11-13T22:17:51+00:00",
    "details_fetched_at": "2026-11-13T22:17:51+00:00",
    "via": "Context.dev /v1/web/scrape (json)",
    "notices_scanned": 38,
    "scanned_since": "2026-03-02",
    "notices_listed": null,
    "notices_unread": null
  },
  "alerts": [
    {
      "event_id": "recall-3f1c9a0b5e7d2c4a8b6e1f0d",
      "type": "recall.alert",
      "kitchen_id": "demo-kitchen",
      "product_id": "461332",
      "product_name": "Kulta Katriina Traditional fine ground filter coffee RAC 5x1kg",
      "match": "possible",
      "why": "same brand Kulta Katriina, shared word(s) kahvi, perinteinen",
      "where": ["on the open purchase proposal"],
      "recall": {
        "url": "https://www.ruokavirasto.fi/elintarvikkeet/ohjeita-kuluttajille/takaisinvedot-2023-/suodatinkahvissa-vierasesineriski/",
        "date": "2026-03-06", "title": "Suodatinkahvissa vierasesineriski",
        "reason": "...", "action": "...",
        "recalled_product": "Kulta Katriina Perinteinen suodatinkahvi", "brand": "Kulta Katriina",
        "gtin": null, "package_size": "500 g",
        "lot": "23.8.2027, 24.8.2027, 26.8.2027, 1.9.2027 ja 5.9.2027"
      },
      "next_step": "Do not use it until checked. Check your packs: ...",
      "replacement_proposal": [],
      "detected_at": "2026-11-14T04:30:00+00:00",
      "status": "active",
      "proposals": [
        {
          "proposal_id": "7c2e...",
          "status": "BLOCKED_BY_RECALL",
          "replacement_proposal_id": "9b41...",
          "recall_replan_error": null,
          "replacement": {
            "proposal_id": "9b41...",
            "status": "READY",
            "expected_total": "56.75",
            "currency": "EUR",
            "lines": [{"product_id": "475842", "product_name": "12 x Löfbergs Crescendo Ground Coffee 500g Rainforest Alliance",
                       "quantity": "1", "unit": "KI"}]
          }
        }
      ]
    }
  ]
}
```

What the view adds to an alert:

- `status` is always there: `active` or `dismissed` (the stored alert may omit it).
  Dismissed alerts stay in the list with `dismissed_by`, `dismissed_at`, `dismiss_reason`.
- `where`: plain English lines that say why the product matters to this kitchen, as they
  were at the first detection (an alert is stored once). The lines are
  `"in stock: 3.253 KG"` (the newest count, above zero),
  `"on the stock list: amount not counted"` (a count of `null`: unknown, never zero),
  `"in recipes: <recipe name>, <recipe name>"` and `"on the open purchase proposal"`.
  A count of zero gives no line. The screens show the lines as they are.
- `proposals`: every proposal of this kitchen that carries this alert, newest first; `[]`
  when none does. An alert with `proposals: []` is for a product in stock or in a recipe
  that no open proposal holds: its `status` is `active`, nothing is held, and a later
  request for that product leaves it out with `BLOCKED_BY_RECALL` (`exact` and `possible`
  alerts; a `review` alert blocks nothing). The screens then say that no open order holds
  it and that new orders leave it out. `status` is the proposal status. An `exact` or `possible` alert holds the
  proposal (`BLOCKED_BY_RECALL`) and its line of `product_id` has
  `recall_status: "BLOCKED_BY_RECALL"`; a `review` alert is a warning and holds nothing.
- `replacement_proposal_id` and `recall_replan_error` are the proposal's own fields
  (recall-contract.md). The replacement is a **separate proposal** with its own total and
  its own pending approval. There is no inline replacement line on the held proposal.
- `replacement`: a short copy of that replacement proposal, so the screen can show it
  without a second call: its `status`, `expected_total` and lines (`quantity` a decimal
  string in `unit`, sized by the engine). `null` when there is no replacement or it cannot
  be read. A person approves it through `/proposals/{id}/approve` as usual; the held
  proposal is closed with `/proposals/{id}/reject`.
- `replacement_proposal` (the monitor's field) stays a list of unapproved ideas; it is not
  the replacement proposal.

`last_check`:

- `null` when no check has run for this kitchen. Then the screens say "not checked yet",
  never "no recalls". An empty `alerts` list with a `last_check` means the check found
  nothing in this kitchen's stock, recipes and open proposals.
- `source`: `live` when Context.dev scraped the Ruokavirasto list during this check;
  `recording` when it did not, and the saved scrape (`monitor/fixtures/ruokavirasto.json`)
  was used. The screens show which one, so a recording is never shown as live.
- `live_error`: `null` for `live`; for `recording` the reason: `NO_KEY` (the gateway has no
  `CONTEXT_DEV_API_KEY`), `TIMEOUT`, `UPSTREAM_ERROR` or `BAD_ANSWER`.
- `fetched_at`: when the list was scraped (`live`: during this check; `recording`: when the
  recording was made). `details_fetched_at`: when the notice pages (product, brand, EAN,
  lot) were scraped; a check makes one scrape, the list, so the pages always come from the
  recording.
- `notices_scanned`: notices matched against the kitchen's stock, recipes and open proposals. `scanned_since`: the date
  of the oldest of them (`YYYY-MM-DD`); the recording starts there and older notices were
  left out when it was made.
- `notices_listed`: notices on the live list, of any age; `null` for `recording`.
  `notices_unread`: notices on the live list, dated `scanned_since` or later or with no
  date, whose page is not in the recording; `null` for `recording`. They were **not**
  matched: when it is above 0 the screens say "N new notices not read yet", never "no
  recalls".

`POST /recalls/check`:

- Body: `{"idempotency_key": "<1 to 200 characters>"}`. A missing or wrong key is 422
  `INVALID_REQUEST`.
- Scope `kitchen:write`. A signed-in person who is not a `viewer` has it (403
  `ROLE_REQUIRED` for a viewer). A kitchen API token has it only when it was created
  with `kitchen:write`; the agent token never has it (403 `SCOPE_REQUIRED`).
- A repeat `idempotency_key` scrapes nothing and applies nothing: it answers the stored
  `last_check` of that check with the alerts as they are now.
- Cooldown (#652): a new `idempotency_key` sent while this kitchen's newest check is
  younger than 60 seconds (`RECALL_CHECK_COOLDOWN_S`; 0 switches it off) scrapes nothing
  and applies nothing. The answer is that newest check's `last_check` (its own
  `checked_at` and `checked_by`) with the alerts as they are now, plus `"reused": true`
  at the top level, next to `last_check` and `alerts`. `reused` is only there when it is
  `true`. A cooldown answer only reads: no matching, no hold, no audit entry, and the new
  key is not recorded (sent again after the cooldown, it runs a check). The cooldown is
  per kitchen; another kitchen's check is not reused.
- One check at a time per kitchen (#652): a second check for the same kitchen waits for
  the running one and then gets the cooldown answer, so two clicks make one scrape. When
  the running check does not end in time: 429 `RECALL_CHECK_BUSY` with a `Retry-After`
  header (whole seconds, 10) and `error.retry_after_s`. "In time" is the scrape timeout
  plus 30 seconds, so 75 seconds by default (`RECALL_CHECK_LOCK_WAIT_S` sets it directly;
  0 answers 429 at once): a click never hangs longer than that. A 429 says nothing about recalls: the
  screens keep what they showed and never say "no recalls".
- One check makes at most one Context.dev call, with one attempt and a timeout (45 seconds;
  `RECALL_CHECK_TIMEOUT_S`, at most 120). It never retries and never loops. A live list
  scrape took 30 seconds on 2026-11-14, so the button shows "Checking recalls…" that long.
- It never orders, approves or cancels anything. It holds proposals and plans replacement
  proposals exactly as `monitor.proposals` does; an alert already known (same `event_id`)
  is not re-planned and a dismissed alert is not applied again.
- Audit: the monitor's entries as before (`recall.alert` per notice and product,
  `recall_proposal_blocked`, `recall_replacement_proposed`, ...) plus one `recall_check`
  entry per check with the `last_check` fields and the alert ids.
- When neither the scrape nor the recording can be read: 502 `RECALL_CHECK_UNAVAILABLE`.
  The screens then show recalls as unknown.
- `CONTEXT_DEV_API_KEY` stays on the gateway; the browser never calls Context.dev.

The web client maps snake_case to camelCase. One web `RecallAlert` per alert and
proposal: `proposals[].proposal_id` becomes `orderId`, `replacement_proposal` becomes
`replacementIdeas`, `quantity` becomes a number.

### Richer kitchen facts (proposed, #435)

Not served yet. These four facts are what the forecast and the recipes learn from; they
are written down now so store, web and gateway use one shape. Quantities are decimal
strings in kitchen units; `null` means unknown, never zero.

**Covers per service.** `POST /v1/kitchens/{kitchen_id}/covers` (`kitchen:write`):

```json
{"idempotency_key": "covers-2026-11-16", "date": "2026-11-16", "source": "pos",
 "services": [{"meal": "breakfast", "covers": 180}, {"meal": "lunch", "covers": 95},
              {"meal": "dinner", "covers": null}]}
```

`meal` is `breakfast`, `lunch`, `dinner` or `other`. A `null` is a service that was not
counted. The day's total is the sum of the counted services, with `complete: false` when
any service is null.

**Dish sales.** `POST /v1/kitchens/{kitchen_id}/dish-sales` (`kitchen:write`): what was
really cooked, from the POS.

```json
{"idempotency_key": "sales-2026-11-16-lunch", "date": "2026-11-16", "meal": "lunch", "source": "pos",
 "dishes": [{"recipe_id": "salmon-soup", "portions": 88}, {"recipe_id": "rice-pudding", "portions": 40}]}
```

Theoretical usage of a product on a day = the sum over dishes of `portions` x the
recipe's `qty_per_portion` / yield.

**Waste log.** `POST /v1/kitchens/{kitchen_id}/waste` (`kitchen:write`):

```json
{"idempotency_key": "waste-2026-11-16-1", "date": "2026-11-16",
 "entries": [{"product_id": "469549", "quantity": "4", "unit": "L", "reason": "EXPIRED"},
             {"recipe_id": "salmon-soup", "portions": 6, "reason": "OVERPRODUCTION"}]}
```

`reason` is `EXPIRED`, `OVERPRODUCTION`, `PLATE_WASTE`, `SPILL` or `OTHER`. An entry
names a product with a quantity, or a recipe with portions.

**Actual against theoretical usage.** `GET /v1/kitchens/{kitchen_id}/usage?from=&to=`
(`kitchen:read`), one row per product:

| Field | Type | Notes |
|---|---|---|
| `product_id`, `unit` | string | |
| `actual` | decimal string or null | Opening count + deliveries - closing count. Null when either count is missing. |
| `theoretical` | decimal string or null | From dish sales x recipes. Null when no dish sales were sent. |
| `logged_waste` | decimal string | From the waste log, 0 when nothing was logged. |
| `gap` | decimal string or null | `actual` - `theoretical` - `logged_waste`. Null when `actual` or `theoretical` is null. |
| `gap_share` | decimal string or null | `gap` / `theoretical`. A lasting positive share means unlogged waste or a recipe that uses more than it says. |

The engine may suggest a recipe correction (a new `qty_per_portion` or `yield_pct`) when
`gap_share` stays above 10% for three weeks; a person accepts or declines it, and the
decision is a feedback row. Nothing changes a recipe on its own.

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

Kind says where a code goes: `reason` in `reason_codes` (of a line, the mandate or an
engine row), `warning` only in `mandate.warnings`, `error` as an HTTP error code, and
`outcome` as a `place_order` outcome.

| Code | Kind | Meaning |
|---|---|---|
| `CLOSING_PASSED` | reason | `closingTime` is at or before now for this delivery. The product is left out; the code is on the mandate. |
| `STOCK_UNKNOWN` | reason | Valio's availability is a filler (999999 or more), or the supplier is a manual or csv price list. A missing, null or zero amount is not available, not unknown. A warning on approve: a person may still approve, the order then waits for the supplier (`supplier_must_confirm`). For each supplier with such lines the mandate reasons say "<supplier> must confirm stock for: <product names>." (`Valio` for Valio's lines). |
| `PARTIAL_STOCK` | reason | less is available than needed |
| `NEED_REFUSED` | reason | a request with several products (#1375): at least one need cannot be ordered (`request.items[].problem`); the others are proposed. On the mandate. Earned auto-approve never applies. |
| `SUBSTITUTE_NEEDS_OK` | reason | a substitute changes the product; a human agrees |
| `SUBSTITUTE_FAT_LEVEL` | reason | two lines of one plan have known fat levels more than 0.5 g per 100 g apart (fat-free and 3 % milk, S01). From the supplier record's `FAT` nutrient; unknown fat is never compared. On the mandate. |
| `ALLERGEN_RULE` | reason | a kitchen allergen rule refuses a product: its known allergens (CONTAINS, MAY_CONTAIN or UNDECLARED) include an excluded code. That product is left out, listed under `excluded` with reason `ALLERGEN_RULE: the kitchen excludes <codes>` (per product, not the whole mandate), on every path: `POST /proposals` and MCP `get_offer`. Unknown allergen data is not a hit: the line stays with `ALLERGEN_DATA_MISSING`. |
| `ALLERGEN_DATA_MISSING` | reason | no allergen data; treated as unknown |
| `OVER_BUDGET_WARNING` | warning | total is above the kitchen's budget warning. A warning only: a human approves every order anyway. Replaces `OVER_SPEND_LIMIT`. |
| `CERTAINTY_PREMIUM_HIGH` | warning | the plan uses confirmed stock that costs more than `certainty_premium_max` times the cheapest orderable price per litre or kilo, because the order would be short without it. Show it on the approval card with the line's price. |
| `LOT_SIZE_ROUNDED` | reason | quantity rounded up to `allowedLotSize` or pack |
| `EVENT_LINE` | reason | one-off demand, kept out of the base forecast |
| `MOV_PADDED` | reason | lines pulled forward to reach free delivery |
| `TOTAL_MISMATCH` | error | gateway total differs from the figure the human approved |
| `STANDING_ORDER_DRIFT` | reason | standing order no longer matches usage. The line's `numbers.propose_standing_order` is the suggested new one (demand x review days, in sales units); the why says it. A person changes the standing order, never the engine. |
| `STOCK_COUNT_MISSING` | reason | kitchen stock count is empty |
| `STOCKOUT_ADJUSTED` | reason | demand scaled up for days out of stock |
| `POSITION_OK` | reason | on hand + on order is enough; no order now |
| `COVER_CEILING` | reason | more would exceed the maximum days of cover |
| `PACK_SIZE_DERIVED` | reason | pack size derived because the pack data is missing or wrong |
| `UNCONFIRMED` | outcome | the send may have landed; a human checks |

## place_order outcomes

| `outcome` | Meaning | What the caller does |
|---|---|---|
| `CONFIRMED` | The order is known to be placed in our gateway | Show it; done |
| `NOT_SENT` | The request never left; nothing exists at the supplier | May retry explicitly, with the same `idempotency_key` |
| `UNCONFIRMED` | It may already have been applied | Stop; a human checks the order status. Never resend |
| `SENT_READ_FAILED` | It landed; only reading the answer failed | Re-read the order status. Never resend |

Refusals before any send are errors, not outcomes: `TOTAL_MISMATCH` (409: re-simulate
and ask the human again), `STOCK_UNKNOWN` (409 only for an auto-approval: a person's
approval of an unconfirmed line places the order with `supplier_must_confirm`), `BLOCKED_BY_RECALL`
(409: a recall holds the proposal; look at its replacement proposal), `NOT_PENDING`
(409: the proposal is not `READY`), `APPROVAL_MISMATCH` (409: `place_order` names an
offer other than the one the person approved), `HUMAN_SESSION_REQUIRED` (403),
`ROLE_REQUIRED` (403), `IDEMPOTENCY_KEY_REUSED` (409). No adapter retries a POST automatically.

The way out of `UNCONFIRMED` and `SENT_READ_FAILED` is "Resolving an unknown send": a
person records `placed` or `not_sent`. Its refusals are `ORDER_NOT_RESOLVABLE` (409) and
`ALREADY_RESOLVED` (409).


## Kitchen morning/evening brief (#1332)

`GET /v1/kitchens/{kitchen_id}/brief?when=morning|evening&lang=en|fi`
requires `kitchen:read` scoped to that kitchen. Both parameters are required;
missing, repeated, unknown parameters or unsupported values return 422
`INVALID_REQUEST`. Calendar dates and cut-offs use `Europe/Helsinki`.
This read creates no proposal, approval, order or delivery decision.

Plain code gathers current kitchen-scoped facts and ranks at most six rows:
1. READY waiting proposals with the earliest known offer closing time today
   (morning), or from now until tomorrow noon (evening).
2. Active recall alerts matching stock, recipes or waiting proposals.
3. OPEN supplier suggestions waiting for an answer.
4. Non-cancelled orders arriving today (morning); today's latest delivery-note
   check per order with SHORT, MISSING or SUBSTITUTE counts (evening).
5. Remaining READY drafts, grouped by supplier with count and known EUR total.
6. Non-cancelled orders with `supplier_must_confirm`.

Ties use time, then stable reference ID. A cut-off already represented is not
repeated in the draft summary. Missing stock, quantity or price stays unknown,
never zero; incomplete totals are not shown as complete totals. Existing delivery
checks expose audit counts, not product quantities: the brief reports only those
counts until a separate delivery-result contract provides more. No upstream
supplier call, photo, document text or other kitchen's data is used.

Each internal row has `kind` (`CUTOFF`, `RECALL`, `SUPPLIER_OFFER`, `DELIVERY`,
`DELIVERY_CHECK`, `WAITING_DRAFTS`, `UNCONFIRMED`), `ref_id`, code-set `urgent`, and
only its known product/supplier names, quantities with units, amounts and times.
The worker receives these compact rows with closed English/Finnish sentence
variants generated from their facts. It selects wording in strict JSON:
`{lines: [{text, kind, ref_id, numbers: ["..."]}]}`. Exactly one line per row,
in source order. The gateway accepts only that row's complete allowed sentence,
and additionally checks its declared/written numbers against the same row using
`claim_check` with Finnish formatting normalized. Numeric inclusion alone cannot
prove a product/date/advice claim. A bad or missing line is replaced individually
by its deterministic localized sentence. Extra rows never appear.

Response (no wrapper):
```json
{"when":"morning","lang":"en","made_by":"model",
 "lines":[{"text":"...","kind":"CUTOFF","ref_id":"...","urgent":true}],
 "nothing_urgent":false,"model":"nemotron-3.5-super-vl","duration_ms":123}
```
`made_by` is `model` when all returned lines passed, `mixed` when some passed,
or `rule` when none passed. `nothing_urgent` means no reportable rows: empty
`lines` and `true`; a nonempty brief has `false`, even with no urgent row.
Only cut-offs today and active recalls have `urgent:true`. Tomorrow-morning
cut-offs included in an evening brief have `urgent:false` until their local date.
An empty brief or missing worker configuration has `made_by:"rule"` and
`model:null`. `model` names Nemotron only when a model was attempted; rejected
model output can therefore have `made_by:"rule"` with a non-null model.
`duration_ms` is measured handler elapsed time (including fact reads, cache lookup
and any worker wait), even when no model call is made or a cache entry is used.

One model call, no retry, with a 30-second model deadline and a 35-second worker
request deadline. Missing configuration, timeout, invalid reply or a busy writer
returns the same facts in rule-based lines, never a model error in place of the
brief. Empty briefs make no model call. No model key reaches the gateway.
Cache per kitchen, period, language and current fact fingerprint: valid results
300 seconds, partial/rule fallback 30 seconds, bounded entries. Facts are rebuilt
before cache lookup so a changed approval/recall/offer does not reuse old text.
Simultaneous readers do not start duplicate model calls for the same key.
The usage meter records role `kitchen_brief`. Audit kind `kitchen_brief_read`
records only row/model-line/rule-line counts, duration, cache use and period/language;
no line text or model reply. Authentication/scope/storage failures are ordinary
route errors, never an invented empty brief.


## Learning from kitchen changes and deliveries (#1300)

**Future contract, implemented in stages.** This section does not make every route or field
available immediately. The existing change route keeps its behaviour until each stage lands.
Learning adds no model-controlled write endpoint and never changes a typed request quantity.

### Changes and human feedback

`POST /v1/kitchens/{kitchen_id}/proposals/{proposal_id}/change` retains its existing wrapper,
validation, idempotency and `kitchen:propose` scope. Each entry in `lines` or `add` may add:

```json
{
  "idempotency_key": "change-7",
  "lines": [
    {"product_id": "462775", "quantity": "20", "reason": "TOO_MUCH"},
    {"product_id": "463335", "quantity": "0", "reason": "OTHER", "note": "Event cancelled"}
  ],
  "add": [
    {"product_id": "462921", "quantity": "8", "reason": "TOO_LITTLE"}
  ]
}
```

- `reason`: `TOO_MUCH`, `TOO_LITTLE`, `IN_STOCK`, `MENU_CHANGED`, `BUDGET` or `OTHER`;
  absent or `null` preserves legacy behaviour.
- `note`: permitted only with `OTHER`; otherwise absent or `null`. It is a string of at most
  200 characters, including whitespace, and is never placed in learned-fact or audit output.
- Invalid combinations are `422 INVALID_REQUEST`; existing change errors remain unchanged.
- The proposal response remains the normal `GET /proposals/{id}` proposal object, not a
  learning-specific wrapper.

The change-level `idempotency_key` remains top-level, never per entry. Its
canonical hash includes normalized product/quantity/reason/note for every named
entry; absent and null optional fields are equivalent. Same key with a different
reason/note is `409 IDEMPOTENCY_KEY_REUSED`, just like a changed quantity.

Feedback is stored only for an authenticated human's change. Agents may change proposals,
but model, automatic and token-only actions never create human-labelled learning rows.
`approved` and `rejected` rows each represent one logical human decision for the proposal/offer,
including its total; approval/rejection idempotency must not duplicate that row. A
personal approval token counts as its verified human principal, never as the agent
that carries it; auto-approval remains a distinct system action. Rejection's
existing free-text `feedback.reason` is distinct from a change line's enum `reason`.

Change rows retain trusted server-read context: `forecast_need`, `stock_position` (nullable),
`covers`, `requested_date`, `made_by` and `offer_id`. `forecast_need` is the **unlearned base**
forecast in the same unit and quantity basis as `from_qty` and `to_qty`, so repeated computation
does not compound learning. The server derives context from the offer being changed, before re-quoting. A
missing unlearned base stays null and cannot train a correction; never substitute
an already-learned shown quantity. Client-supplied context is ignored, not trusted. Missing quantities
and dates are `null`; quantities on the wire are decimal strings.

A joined feedback row retains `ts`, `kitchen_id`, `product_id`, `proposal_id`,
`user`, existing `kind`, `from_qty`, `to_qty`, `unit`, plus nullable `reason`,
`note`, `context`, `outcome` and a stable `feedback_id` for outcome association.
For example (quantities all in `unit`):
```json
{"feedback_id":"fb-1","ts":"2026-11-14T10:00:00Z","kitchen_id":"k-1",
 "proposal_id":"p-1","product_id":"potato","user":"chef-1",
 "kind":"qty_changed","from_qty":"40","to_qty":"20","unit":"KG",
 "reason":"TOO_MUCH","note":null,
 "context":{"forecast_need":"40","stock_position":null,"covers":null,
            "requested_date":"2026-11-16","made_by":"menu_plan","offer_id":"o-1"},
 "outcome":{"next_count_at":null,"next_count":null,"ran_out":null}}
```
`context.made_by` is `menu_plan`, `request` or `supplier_offer`; an unknown
legacy origin is null. Context/outcomes are internal learning records, not new
client-write fields. Human changes are recorded only after the change commits;
failed edits and identical replays create no feedback rows. Their reason/note
are included in the canonical change idempotency payload.

### Outcomes and delivery observations

The append-only MongoDB `feedback` time series is never updated in place to add an outcome.
Readers join change rows to separately stored outcomes by kitchen, proposal and feedback identity.
Legacy rows without `feedback_id` have unknown outcomes; never join them by
proposal/product alone. Rows without a qualifying reason or trusted unlearned
`forecast_need` cannot train correction ratios.
`next_count_at`, `next_count` and `ran_out` are a tri-state observation:

```json
{"next_count_at": null, "next_count": null, "ran_out": null}
```

`ran_out` is `true`, `false` or `null`. An unknown or absent stock count means `null`, never zero
and never `false`. A stock count alone does not establish whether the kitchen ran out.

The existing delivery-note check saves only structured results after a successful
authorized read; its response adds `"saved": true` only after durable persistence.
The actor is `checked_by` (the authenticated person or token principal, as in
audit); a token is never relabelled as a human. A row contains
kitchen, order and supplier ids, `requested_date`, note-read `delivery_date`, derived `days_late`,
`ordered_at` (from the trusted order), `checked_by`, `checked_at`, `source`
(`photo` or `manual_complete`) and lines:

```json
{
  "supplier_id": "supplier-1",
  "product_id": "462775",
  "unit": "ST",
  "status": "SHORT",
  "ordered": "40",
  "delivered": "30"
}
```

Line status is `RECEIVED`, `SHORT`, `MISSING` or `UNKNOWN`. The separate `not_ordered` array uses statuses `SUBSTITUTE`, `EXTRA`,
and `UNREADABLE`; `not_ordered` is a field name, not a status. Each line also carries
its `unit`; comparing ordered/delivered values requires a trusted unit conversion.
A substitute never counts as receipt of the original product without a separate
human decision; unknown conversions stay null. These describe observed lines, not inferred stock. Unknown delivered
quantities and dates are `null`. Raw photos, OCR text, note text and lot numbers are never stored.

The stored/public observation (`result` on the one-tap response) has this shape:
```json
{"result_id":"dr-1","revision":1,"kitchen_id":"k-1","order_id":"order-1",
 "supplier_id":"supplier-1","requested_date":"2026-11-16",
 "ordered_at":"2026-11-14T10:00:00Z","delivery_date":"2026-11-17","days_late":1,
 "checked_by":"chef-1","checked_at":"2026-11-17T08:00:00Z","source":"photo",
 "lines":[{"supplier_id":"supplier-1","product_id":"462775","status":"SHORT",
           "ordered":"40","delivered":"30","unit":"ST"}],"not_ordered":[]}
```
Dates are ISO calendar dates; timestamps carry an offset. `days_late` is a signed
integer calendar-day difference (early may be negative), null if either date is
unknown. `result_id` identifies this order's logical result, `revision` its positive
integer version. The order, offer and supplier blocks supply trusted identity,
requested date, order timestamp and ordered quantities, not the model/client.
For mixed-supplier orders, top-level `supplier_id` is null and each line retains
its supplier id; statistics group lines by that supplier, counting an order once
per supplier. Unknown supplier/unit is null and ineligible for that statistic.
`lines` contains original-order products only; `not_ordered` contains the observed
exceptions with product/supplier id when known, status, delivered quantity and
unit (all unknown values null). It carries no lot/best-before text. `ordered_at`
is nullable for legacy orders, so unknown lead time cannot become zero.

The newest valid observation per kitchen and order is eligible for learning; superseded or invalid
readings are not counted. Rechecking replaces the logical observation for learning, with
`delivery_result_saved` audited per changed result. Implementations may append
versioned observations plus a current-version selector; time-series rows themselves
are immutable. A replay cannot add another delivery to the statistics. Readers return the
selected observations oldest first. This persistence stores delivery facts, not stock counts, and
does not replace manual stock confirmation.

The one-tap path is `POST /v1/kitchens/{kitchen_id}/orders/{order_id}/received`,
with `{"idempotency_key":"received-1","delivery_date":"2026-11-14","complete":true}`.
It requires `kitchen:write` and a human chef or approver; viewers, agent/kitchen API
and personal approval tokens cannot assert this human observation. `delivery_date`
is a valid local ISO date, at most today in `Europe/Helsinki`; `complete` must be
boolean `true`. Missing/extra fields or bad types return `422 INVALID_REQUEST`.
A missing or another kitchen's order is `404 ORDER_NOT_FOUND`; an unplaced,
failed or cancelled order is `409 NOT_PENDING`. It stores `source:manual_complete`,
ordered quantities as delivered with `status:RECEIVED` only where those order
quantities/units are known (else `status:UNKNOWN`, `delivered:null`), empty
`not_ordered`,
and answers `{"saved":true,"order_id":"...","result":<structured observation>}`.
It never updates the order's supplier status or stock. The same key and body replay
the same result, even after a later check; changed body with that key is
`409 IDEMPOTENCY_KEY_REUSED`. New observations advance the logical current version.

### Learned facts

`GET /v1/kitchens/{kitchen_id}/learned`, scope `kitchen:read`, returns only that kitchen's facts:

```json
{
  "facts": [
    {
      "id": "lf_01JYK8M4N3M4K7W8N0E4Q2F6C5",
      "kind": "CORRECTION_RATIO",
      "product_id": "462775",
      "supplier_id": null,
      "name": "Washed potato 10 kg",
      "value": 0.5,
      "evidence": {"rows": 4, "from": "2026-09-21", "to": "2026-11-09",
                   "last": "2026-11-09"},
      "since": "2026-11-14",
      "active": true
    }
  ]
}
```

`kind` and scoped entity identity are stable. `id` identifies a fact evidence
version: kitchen + kind + entity + algorithm version + contributing observation
identities/versions. Unchanged evidence recomputes to the same id; a new id requires
new qualifying evidence, not a page read or a clock tick. `since` is the first date
of that version. Disabled versions stay disabled; genuinely new evidence may form
a new active version as specified in #1305. GET returns the current version per
kind/entity, including `active:false` overrides, in kind/entity/id order. Product facts use
`product_id`; supplier facts use `supplier_id`. No fact contains currency. `value` is a bounded
JSON number, not a decimal string:

| Kind | Entity and value | Additional numeric fields |
|---|---|---|
| `CORRECTION_RATIO` | Product; `value` is the ratio, within `0.3..1.5`. | `raw_value` (finite ratio), `applicable` boolean; an out-of-band ratio is clamped for display and `applicable:false`, never applied. |
| `DECLINED_PRODUCT` | Product; `value` is numeric `1`, meaning declined. | None required. |
| `SUPPLIER_LATE` | Supplier; `value` is nonnegative `mean_days_late`. | `mean_days_late` equals `value`, `on_time_rate` in `0..1`, `deliveries` integer; `mean_lead_time` and `sigma_lead_time` in days, nonnegative when known (else null). |
| `SUPPLIER_SHORT` | Supplier; `value` is `fill_rate` in `0..1`. | None required. |

For `SUPPLIER_LATE`, `on_time_rate` counts eligible deliveries with
`days_late <= 0` as on time. `mean_days_late` is the arithmetic mean of positive
`days_late` values (late deliveries only), or 0 when known deliveries contain no
late case; early deliveries never subtract from lateness. Thus five deliveries,
three exactly one day late and two on time, give `on_time_rate:0.4` and
`mean_days_late:1`. `mean_lead_time` and `sigma_lead_time` use all eligible known
actual lead times (`delivery_date - ordered_at` in local calendar days), including
early arrivals; impossible negative actual lead times are excluded, not clamped.
Sigma is population standard deviation. `deliveries`/`evidence.rows` count distinct
eligible orders per supplier, not photo checks or line items.

`evidence.rows` is a nonnegative integer; `from`, `to`, `last` and `since` are ISO dates.
An unknown rate is omitted together with its fact, not emitted as zero. Code computes facts from
trusted feedback windows and outcomes. `CORRECTION_RATIO` requires at least three relevant
`TOO_MUCH`/`TOO_LITTLE` rows from approved proposals in the last eight weeks;
rows with `ran_out:true` after a cut are excluded. Ratios use `to_qty /
context.forecast_need` (removal is zero), never `to_qty / from_qty` after learning.
No fact is emitted for the no-change band `0.95..1.05`; `IN_STOCK`, `MENU_CHANGED`, `BUDGET` and `OTHER` do not qualify.
`DECLINED_PRODUCT` requires at least three removals with reason `TOO_MUCH`,
`OTHER` or no reason, excluding `IN_STOCK`, `MENU_CHANGED` and `BUDGET`; an
explicit human product addition resets its decline history. Recipe/menu-required
products with no covering alternative remain with a warning rather than silently
removing the ingredient. Excluded learned products expose their fact id and
evidence in the existing `excluded` list for undo. Supplier facts need at least five distinct eligible deliveries in the last eight
weeks. Unknown dates/quantities are excluded from their respective statistic, not
counted as on-time/full. Missing order timestamps leave mean/sigma lead time
null; they cannot turn into zero-day delivery. The engine keeps user-set terms
when learned timing is unknown. Fields are finite numeric values, never NaN/infinity.
`name` is the trusted product/supplier display name. API adapters must normalize
these facts to the compact `agent.memory` shape; that helper is not the wire API.

Plan proposals only expose a quantity adjustment as:

```json
"learned": {"fact_id": "lf_01JYK8M4N3M4K7W8N0E4Q2F6C5",
            "from_qty": "40", "to_qty": "20", "unit": "KG", "ratio": 0.5,
            "evidence": {"rows":4,"from":"2026-09-21","to":"2026-11-09",
                         "last":"2026-11-09"}}
```

`from_qty`/`to_qty` are decimal strings before/after the learned quantity adjustment; existing pack
and ordering rules still apply. The `why` text remains. Typed request quantities
and supplier-proposed quantities are never adjusted. Supplier timing learning never
changes Valio available dates/cut-offs. Any learned adjustment blocks earned
auto-approval in this round. Typed requests, supplier-offer proposals and
ordinary unchanged lines omit `learned` entirely. A model may select relevant facts or
propose short checked `learned_not_applicable` text, but cannot disable a fact or change a quantity.
Every model sentence references `fact_id` and is checked against that fact
alone, with Finnish number formatting normalized. An invalid sentence is omitted,
leaving the plain learned evidence. A not-applicable model suggestion is only text
for human review; it does not skip an engine adjustment or persist a switch. Prompt memory is
capped at 12 entries and approximately 600 tokens.

### Disable, privacy and audit

`PUT /v1/kitchens/{kitchen_id}/learned/{id}` accepts exactly `{"active": false}` and requires an
authenticated human approver (`who.human`) with `kitchen:write` scoped to
`kitchen_id`; personal tokens grant no additional actions. Only this
kitchen's persisted override is written. This does not silently re-quote an
existing basket, alter a signed offer or place/cancel an order; the UI regenerates
the plan through its existing proposal path and displays the fresh quote for
human review ("Use the forecast instead"). The response is `{"fact": <fact>}` with `active: false`.
Repeating the same disable is idempotent. `active: true`, extra fields and reopening are
`422 INVALID_REQUEST`. A fact outside the caller's kitchen is `404 LEARNED_FACT_NOT_FOUND`;
missing scope is `403 SCOPE_REQUIRED`, and missing approver authority is `403 ROLE_REQUIRED`.
Agents and models have no direct fact-write or cross-kitchen access.

Audit `learned_fact_switched_off` once only when state actually changes, not on an
idempotent repeat. The actor is server-authenticated. `learned_fact_applied` names
proposal/offer, product and fact ids with from/to quantities and unit;
`learned_fact_switched_off` names the fact; `delivery_result_saved` names
order/result/revision and line-status counts. No notes, photos or free text and
no new webhook event are implied. Facts are private to one kitchen: no pooling,
cross-kitchen reads or cross-kitchen overrides are part of this contract.
