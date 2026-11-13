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
- A product-level or schedule-level `salesBlock: true` means it cannot be ordered.
- `scheduleLines` is empty when the product cannot currently be delivered on any
  date; otherwise the challenge returns exactly one line.
- A line requires `salesBlock`, `availableAmount`, and `salesUnit`.
  `availableDate` may be absent or null. Its value is the earliest available date
  and can differ from the requested date.
- `availableAmount` is expressed in `salesUnit`. Zero means unavailable.
- Stock quantities are known. Terminal products use `999999` as an unknown-quantity
  sentinel; this must not be presented as measured stock.

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

Pending agreement with the gateway and UI owners. The upstream facts above do
not establish our MCP tool names, approval messages, simulation output, or order
state transitions. Add those interfaces here in a separate contract PR before
building integrations against them.
