# Valio data and API: what we found

Checked 2026-11-13 21:00 by Aron's session. Source files are in `vendor/valio/`
(git-ignored: challenge data, not for use outside the challenge). API contract:
`docs/contract.md`.

## API traps (tested live)

- **Send a `User-Agent` header.** Without one, Cloudflare returns `403 error code: 1010`
  (Python `urllib` default UA is blocked). Any value works, e.g. `2brothers/0.1`.
- Auth: header `X-API-Key` (from `.env` `VALIO_API_KEY`). `/api/ping` returns `{"status":"ok"}`.
- **Unknown-stock sentinels:** `999999` (Terminal products) **and** `9999999999` (seen on a
  Stock product). Treat both as "unknown, not measured", never as real stock.
- **`closingTime` can already be in the past** for the requested date (Terminal products:
  closing 2026-11-12 15:00 for a 2026-11-16 delivery, asked on 11-13). Then the item cannot
  make that delivery even though `availableDate` says 11-16. Check `closingTime > now`.
- Unknown product code: HTTP 200 with `scheduleLines: []` (no error flag in availability).
- Price: `comparisonPrice` per `comparisonUnit` (L or KG) is the fair way to compare pack
  sizes. Prices are before tax in `value`; dairy tax rate 13.5%.
- `listPrice` > `catalogPrice` (catalog already has a discount); `netPriceFound: false` for
  customer `123`.
- No order endpoint upstream: order, approval and audit are ours.

## Product catalog (`valio_aimo_junction26_product_data.json`, 87 MB)

- **17,546 products**, 349 categories, 648 vendors, none deleted.
- Top-level: `id`, `salesUnit`, `baseUnit`, `category`, `allowedLotSize`, `vendorName`,
  `countryOfOrigin`, `temperatureCondition` (1–8), `units[]`, `deposits[]`,
  `substitutions[]` (only 196 products), `synkkaData{}`.
- Sales units: KI 8,005 (case), ST 5,607 (piece), KG 1,068, PAK, BAG, RAS, PRK, BOT …
- `units[]` = pack hierarchy: `{unitId, sizeInBaseUnits}` e.g. PAL 160 / KI 5 / ST 1.
  Use it to convert "1,000 litres" into sales units and round to pack.
- `substitutions[]` = Valio's own `{product, substituteProduct}` pairs: the first rung of
  good-better-best.
- `synkkaData` (GS1 Synkka product data):
  - `names[]` in en / fi / sv; `brand`; `marketingTexts`; `keyIngredients`; `ingredients[]`
    with percentages and origin.
  - `classifications[]` (on 17,535 products):
    - **`allergen`**: ENUM values with GS1 codes and `unit: CONTAINS` / may-contain
      (e.g. `AE` egg, `BM` mustard, `AM` milk, `AW` gluten cereals …).
    - **`nonAllergen`**: free-from claims.
    - **`packagingMarkedLabel`**: certificates/labels, e.g. `GOODS_FROM_FINLAND_BLUE_SWAN`,
      `EU_ORGANIC_FARMING`, `FINNISH_HEART_SYMBOL`, `RAINFOREST_ALLIANCE`, and temperature
      tags `coolTemperature` / `warmTemperature`.
    - `nutritionalClaim`, `nutritionFact`, `gda`, `vitamin`, `mineral`, `packaging`.
  - `nutritionalContent[]` per 100 g/ml; `storageInstructions`; `unitConversions` (weights,
    sizes).
  - Missing allergen data is **unknown**, never "allergen-free".

## Other datasets

- `delivery_reliability.csv`: 4,425 products, `productId,deliveryReliability` (0–1,
  delivered vs ordered). Missing = unknown.
- `carbon_footprint.csv`: 11,033 products, `AVG kg CO2-eq/kg` of the product group.

## The milk example, live (requested 2026-11-16, asked 2026-11-13)

"1,000 L of lactose-free milk by Monday" already hits three exceptions:

| Product | Pack | €/L (ex VAT) | Stock | Closing | Problem |
|---|---|---|---|---|---|
| 462775 Arla 1 L lactose free fat free UHT | ST, KI 12 | 2.57 | 51 ST | 11-15 17:00 | only 51 L in stock |
| 462921 Valio Eila organic 1 L | KI 5 | 2.19 | unknown (999999) | **11-12 15:00 (passed)** | cannot make Monday |
| 463038 Valio Eila 10 L novobox | KI 2 | – | unknown | 11-12 (passed) | cannot make Monday |
| 463335 Valio Eila 3 % 1 L | ST, KI 5 | – | 9999999999 (unknown) | 11-15 17:00 | stock unknown |
| 464179 Arla 10 L novobox ESL | ST | – | unknown | 11-12 (passed) | cannot make Monday |

So the honest answer is a **split order + a human decision**: what can arrive Monday,
what arrives later, and which substitutes (fat %, pack size, organic) are acceptable.
That is the demo.
