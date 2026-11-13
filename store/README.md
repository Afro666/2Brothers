# Store: MongoDB repository

`store` is the only package that talks to MongoDB (Atlas). Gateway and agent import
it; nothing else opens a connection. Install from the repository root with
`python -m pip install -e ".[test]"` and put `MONGODB_URI` in `.env`.
The database is the one named in the URI, else `two_brothers`.

## Load the Valio catalog

1. Download the three datasets into the git-ignored `vendor/valio/`. The endpoints
   redirect to the file, so `curl` needs `-L`; Cloudflare needs a `User-Agent`.
   The data is for this challenge only: never commit it.

   ```bash
   mkdir -p vendor/valio
   KEY=$(grep '^VALIO_API_KEY=' .env | cut -d= -f2-)
   for pair in products:product_data.json delivery-reliability:delivery_reliability.csv \
               carbon-footprint:carbon_footprint.csv; do
     curl -fsSL -A 2brothers/0.1 -H "X-API-Key: $KEY" \
       "https://junction26.valioaimo.fi/api/${pair%%:*}/download" \
       -o "vendor/valio/valio_aimo_junction26_${pair##*:}"
   done
   ```

2. Load it: `python -m store.loader` (about two minutes on the free tier).
   It flattens every product, upserts in batches of 500 and creates all indexes.
   Running it again is safe. Expected output: `upserted 17546 products` and about
   121 MB of data and indexes, out of the free tier's 512 MB.

## Collections

| Collection | Module | Notes |
|---|---|---|
| `products` | `store.products` | `_id` is the product code (a string). One collection and one search index for every source: `source` is `valio` (the catalog) or `own` (a kitchen's own product, with its `kitchen_id`). |
| `offers` | `store.orders` | Price and availability snapshots with `fetched_at`. Never updated, never expired. |
| `orders` | `store.orders` | The attempt row is written before any send. Unique `(kitchen_id, idempotency_key)`. |
| `approvals` | `store.orders` | `PENDING` until a human decides, once. There is no auto-approve. |
| `audit_log` | `store.audit` | Insert-only and hash-chained. `_id` is the sequence number. |
| `kitchen_stock`, `covers`, `orders_history`, `deliveries`, `forecasts`, `kitchens`, `sharing` | `store.history` | Time series and consent; see below. |
| `suppliers`, `recipes`, `menu_plans` | `store.repository` | Kitchen data (#81). `Repository.own_products` reads and writes own products in `products`, in the contract's own-product shape. |

Money is `Decimal` in Python and `Decimal128` in Mongo; the wire format is a decimal
string. `store.orders` refuses binary floats and the unknown-stock sentinels
`999999` and `9999999999`: unknown stock is `None`.

```python
from decimal import Decimal
from store.db import get_db
from store import audit, orders
from store.products import get_product

db = get_db()
get_product(db, "462775")                      # flattened row; raw=True adds the full record
order, created = orders.record_attempt(         # before any send; replays return the stored row
    db, kitchen_id="k1", idempotency_key="key-1", offer_id="offer-1",
    expected_total=Decimal("149.02"), lines=[], payload_hash="sha256...")
orders.set_outcome(db, order["order_id"], outcome="CONFIRMED", status="SENT")
audit.append_event(db, {"event_id": "e1", "run_id": "r1", "type": "tool_call_started"},
                   server={"kitchen_id": "k1", "principal": "agent"})
audit.verify_chain(db)                          # {"ok": True, "length": 1, "broken_at": None}
```

## The product row

Field paths were read from the real catalog, not guessed. What `flatten()` stores:

| Field | From | Notes |
|---|---|---|
| `names.en / fi / sv` | `synkkaData.names[]` | `fi` is always there; `sv` is missing on about 8%. |
| `brand` | `synkkaData.brand` | Trimmed; `None` on about 18%. |
| `category`, `vendor`, `country` | `category`, `vendorName`, `countryOfOrigin` | Category is a 5-character code; the data has no category names. |
| `base_unit`, `sales_unit`, `units[]`, `lot_size` | `baseUnit`, `salesUnit`, `units[]`, `allowedLotSize` | `units[]` is the pack hierarchy in base units. `lot_size` is `None` when the catalog says 0.01. |
| `net_content {value, unit}` | see below | Per base unit, in `L` or `KG` (the contract's kitchen units). |
| `allergens.contains / may_contain / undeclared` | `classifications[name=allergen].values[] {id, unit}` | GS1 codes. `UNDECLARED` is its own list and never counts as free-from. `X99` ("no declarable allergens") is not an allergen: it sets `no_declarable_allergens`. |
| `allergen_data_known` | allergen or free-from values exist | False on 46% of the catalog. False means unknown, never allergen-free. |
| `free_from` | `classifications[name=nonAllergen]` | A code that is also under contains / may contain is dropped: the riskier statement wins. |
| `claims`, `lactose_free` | `classifications[name=nutritionalClaim]` | `lactose_free`: claim `FREE_FROM_LACTOSE` or free-from `ML`, and no lactose under contains / may contain. Lactose-free milk still contains milk (`AM`). |
| `labels` | `classifications[name=packagingMarkedLabel]` | Without the three storage tags. |
| `temperature` | `temperatureCondition`, else a single storage tag | `chilled` (1–4), `frozen` (7), `ambient` (8). Codes 5, 6, 9 have no known meaning and stay `None`. |
| `reliability`, `carbon_kg_co2e_per_kg` | the two CSV files | `None` when the product is not in the file. |
| `substitutions` | `substitutions[].substituteProduct` | Valio's own suggestions; a kitchen's allergen rule still wins. |
| `raw` | the whole record | Left out by `get_product` unless `raw=True`. |

`net_content_source` says how far to trust the size:

| Source | Products | Meaning |
|---|---|---|
| `synkka` | 7,418 | The piece is measured in the product data. |
| `synkka_case` | 1,913 | The case is measured; divided by the case size from `units[]`. |
| `base_unit` | 1,106 | Sold by weight: one base unit is one kilogram. |
| `name` | 5,280 | Read from the product name ("1 l", "7X1,2KG"). A guess: check before relying on it. |
| `None` | 1,829 | Unknown. |

## Search

`store.search.search_products(db, query, filters, limit)` implements `search_products`
from `docs/contract.md` on one Atlas Search index, `products_search`. Its definition is
`store/search_index.json` (1 KB; the free tier allows 3 indexes of 3 KB each).
`python -m store.loader` creates it; Atlas then builds it in under a minute.

```python
from store.search import search_products

search_products(db, "lactose free milk 1 l")            # the 1 l lactose-free milks first
search_products(db, "oat drink", {"exclude_allergens": ["gluten"]})
search_products(db, "", {"require_labels": ["EU_ORGANIC_FARMING"], "temperature": "frozen"})
```

- Text runs over the English, Finnish and Swedish names (each with its own analyzer)
  and the brand, and tolerates one typo.
- Ranking: products with every query word in one name come first, then products of the
  size written in the query ("1 l", "500 g"), then plain relevance.
- `exclude_allergens` takes names or GS1 codes and removes CONTAINS and MAY_CONTAIN.
  Products without allergen data stay, with the reason `allergen data missing`;
  `allergen_strictness: "strict"` removes them too. A misspelt allergen is an error.
- Every row has `score` and `match_reasons`, and never the `raw` record.
- Pass the authenticated kitchen as `kitchen_id=` to include that kitchen's own products.
  A search never returns another kitchen's own products; without `kitchen_id` it
  returns the catalog only.
- Known limit: Finnish and Swedish compound words are not split, so `maito` does not
  find `kevytmaitojuoma`. English queries find those products through the English name.

## History, forecasts and consent

`store.history` keeps the time series behind the demand views. Load Maciek's synthetic
history (20 kitchens, 12 weeks) with:

```bash
python -m env.history --seed 1     # writes env/out/history/*.jsonl (git-ignored)
python -m store.history            # about one minute; safe to run again
```

| Collection | One row per | From |
|---|---|---|
| `kitchen_stock` (time series) | kitchen, product, day | `stock.jsonl`: `on_hand`, `received`, `used`, `short`, `wasted`, `unit` |
| `covers` (time series) | kitchen, day | `covers.jsonl` |
| `orders_history` (time series) | order | `orders.jsonl`; prices become `Decimal` |
| `deliveries` (time series) | order line | `deliveries.jsonl` |
| `forecasts` (time series) | kitchen, product, day | `save_forecasts(db, rows)`: `need`, `unit`, `why` |
| `kitchens` | kitchen | `kitchens.jsonl`, marked `synthetic: true` |
| `sharing` | kitchen and supplier | the contract's consent record |

Loading replaces the rows of the kitchens in `kitchens.jsonl` and leaves other kitchens
alone. Quantities are in kitchen units (`L`, `KG`, `PCS`).

```python
from store import history

history.kitchen_demand(db, "K01", "463171", "2026-11-02", "2026-11-08")
# [{"product_id": "463171", "date": "2026-11-02", "unit": "L", "demand": 117.1, "kitchens": 1}, ...]
history.set_sharing(db, "K01", "valio_aimo", True, granted_by="user-42")   # a human grants
history.supplier_demand(db, "valio_aimo", "463171", "2026-11-02", "2026-11-08")
# the same rows, summed over the kitchens with active consent; never which kitchens
```

Demand from history is what the kitchen used plus what it could not serve (`used` +
`short`). Pass `source="forecast"` to read the engine's `forecasts` instead. A supplier
sees nothing until a kitchen shares: no consent is seeded.

## Tests

- Offline: `python -m unittest discover -s store/tests -t . -v`. Fixtures are synthetic.
- Against the real cluster, in a throwaway database that is dropped afterwards:
  `STORE_LIVE_TESTS=1 python -m unittest store.tests.test_live -v`.
- Time series, also in a throwaway database:
  `STORE_LIVE_TESTS=1 python -m unittest store.tests.test_history -v`.
- Search acceptance, read-only on the loaded catalog:
  `STORE_LIVE_TESTS=1 python -m unittest store.tests.test_search_live -v`.
