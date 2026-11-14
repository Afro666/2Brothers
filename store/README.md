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
| `suppliers`, `recipes`, `menu_plans` | `store.repository` | Kitchen data in the contract's data shapes; see below. Own products are rows in `products`. |
| `brand_logos` | `store.brand_logos` | One row per catalog brand: what Context.dev said about its logo (`found` or `none`), written once by `python -m gateway.brand_logos`. `_id` is the brand name. |

Money is `Decimal` in Python and `Decimal128` in Mongo; the wire format is a decimal
string. `store.orders` refuses binary floats and the unknown-stock sentinels
`999999` and `9999999999`: unknown stock is `None`.

```python
from decimal import Decimal
from store.db import get_db
from store import audit, orders
from store.products import get_product, get_products

db = get_db()
get_product(db, "462775")                      # flattened row; raw=True adds the full record
get_products(db, ["469549", "own-1"], kitchen_id="k1")   # several, in the order asked; catalog
                                               # rows plus that kitchen's own; unknown codes left out
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

## Kitchen data

`store.repository.Repository` keeps suppliers, recipes, menu plans and own products in
the shapes of `docs/contract.md` ("Data shapes"). Every method takes the kitchen first
and every query carries it, so one kitchen never reads or changes another kitchen's
rows. Money and quantities go in as decimal strings and come out as `Decimal`.

```python
from store.repository import Repository

repo = Repository(db)
repo.suppliers.create("k1", {"supplier_id": "sup-valio", "name": "Valio Aimo",
                             "adapter": "valio_api",
                             "terms": {"free_delivery_threshold_eur": "300.00"}})
repo.suppliers.update("k1", "sup-valio", {"terms": {"delivery_fee_eur": "25.00"}})  # other terms stay
repo.recipes.create("k1", {"name": "Carrot soup", "ingredients": [
    {"product_id": "460708", "qty_per_portion": "0.100", "unit": "KG", "yield_pct": "85"}]})
repo.menu_plans.put("k1", "2026-W47", [
    {"date": "2026-11-16", "meal": "lunch", "recipe_id": "rec-soup-1", "covers": 180}])
repo.own_products.create("k1", {"name": "Rye loaf 800 g", "unit": "ST", "supplier_id": "sup-bakery",
                                "base_unit": "KG", "pack_size_in_base_units": "0.8",
                                "unit_price_eur": "4.20"})   # allergen_data defaults to UNKNOWN
```

`repo.settings.get("k1")` returns what the kitchen has set; `repo.settings.put("k1", changes)`
changes only the fields given and returns `(settings, changed)`, where `changed` holds the
value before and after for the audit entry. The allergen policy is `None` until a person
sets it: unknown, not "none".

`suppliers`, `recipes` and `own_products` have `create`, `get`, `list`, `update`, `delete`;
`menu_plans` has `put` (replaces the week), `get`, `list`, `delete`. A supplier term that
was never set is `None`: unknown, never zero.

## Feedback and stock counts

```python
from datetime import datetime, timezone
from store import feedback, history

feedback.record_feedback(db, "k1", "prop-1", [
    {"kind": "qty_changed", "product_id": "469549", "from_qty": "40", "to_qty": "60", "unit": "L"},
    {"kind": "line_removed", "product_id": "460708"},
    {"kind": "approved"}], user="chef-1")          # one row per change
feedback.list_feedback(db, "k1", proposal_id="prop-1")
feedback.declined_products(db, "k1")                # removed 3 times or more: stop proposing

history.record_stock_count(db, "k1", datetime.now(timezone.utc), [
    {"product_id": "469549", "on_hand": "120", "unit": "L"},
    {"product_id": "470863", "on_hand": None, "unit": "L"}])   # None: not counted, never zero
history.current_stock(db, "k1")                     # the latest count per product
```

Feedback kinds are `qty_changed`, `line_removed`, `line_added`, `rejected` (with a
`reason`) and `approved`. The corrected quantity is the label the forecast learns from.
Time-series collections must exist before the first write: `python -m store.history`
creates them, or call `history.ensure_history_collections(db)` once per database.

## Trust screen and live inbox

```python
from store import trust

trust.verify(db, "demo-kitchen")    # {"ok": True, "length": 412, "broken_at": None,
                                    #  "broken_kitchen_id": None, "kitchen_entries": 57}
trust.tamper(db, "demo-kitchen")    # {"seq": 412, "tampered": True}; verify now reports broken_at: 412
trust.restore(db, "demo-kitchen")   # the exact row is back and the chain verifies again

events = trust.watch_kitchen(db, "demo-kitchen")   # the change stream is open from here
for event in events:                # None is a heartbeat, about once a second when quiet
    if event:                       # {"collection": "proposals", "operation": "insert", "document": {...}}
        ...
events.close()                      # when the client goes away
```

`tamper` is a demo: it runs only for `demo-kitchen` while its `kitchens` row says
`synthetic: true`, edits one audit row, and keeps the original in `audit_tamper_demo`
until `restore`. Every other kitchen gets `PermissionError`. The chain is one for all
kitchens, so every kitchen's `verify` shows the break while it lasts, with
`broken_kitchen_id: "demo-kitchen"`; a tamper left for 10 minutes restores itself on the
next `verify` or `tamper`. `store.audit` still has no
update and no delete. `watch_kitchen` covers `proposals`, `approvals` and `audit_log`
and carries only that kitchen's rows; on the free tier an insert arrived in
about 0.03 s (five tries).

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
python -m store.history --share-with valio_aimo   # demo: 16 of the 20 kitchens consent
```

| Collection | One row per | From |
|---|---|---|
| `kitchen_stock` (time series) | kitchen, product, day | `stock.jsonl`: `on_hand`, `received`, `used`, `short`, `wasted`, `unit` |
| `covers` (time series) | kitchen, day | `covers.jsonl` |
| `orders_history` (time series) | order | `orders.jsonl`; prices become `Decimal` |
| `deliveries` (time series) | order line | `deliveries.jsonl` |
| `forecasts` (time series) | kitchen, product, day | `save_forecasts(db, rows)`: `need`, `unit`, `why` |
| `feedback` (time series) | change a human made to a proposal | `store.feedback.record_feedback` |
| `kitchens` | kitchen | `kitchens.jsonl`, marked `synthetic: true` |
| `sharing` | kitchen and supplier | the contract's consent record |

Loading replaces the rows of the kitchens in `kitchens.jsonl` and leaves other kitchens
alone. Quantities are in kitchen units (`L`, `KG`, `PCS`).

```python
from store import history

history.kitchen_demand(db, "K01", "463171", "2026-11-02", "2026-11-08")
# [{"product_id": "463171", "date": "2026-11-02", "unit": "L", "demand": 117.1, "kitchens": 1}, ...]
history.set_sharing(db, "K01", "valio_aimo", True, user="user-42")   # a human grants; audited
history.supplier_demand(db, "valio_aimo", "463171", "2026-11-02", "2026-11-08")
# the same rows summed over the kitchens with active consent, plus
# "by_kitchen": [{"kitchen_id": "K01", "kitchen_name": "School 1 Tampere", "demand": 117.1}, ...]
```

Demand from history is what the kitchen used plus what it could not serve (`used` +
`short`). Pass `source="forecast"` to read the engine's `forecasts` instead. A supplier
sees nothing until a kitchen shares; then it sees that kitchen by name (`by_kitchen`),
as the consent text tells the kitchen. A kitchen without active consent appears nowhere. `--share-with` seeds demo consent for four in five
synthetic kitchens, recorded as granted by `synthetic-seed`; every fifth is held back so
the consent rule shows.

## Semantic search (hybrid)

Words miss what meaning finds: a search for "lactose-free milk" should also find a
product whose name says it another way. Every product has one embedding of 1024
dimensions, stored on the product row as float32 binary under `embedding` with the model
name and size. A second Atlas index, `products_vector` (`store/vector_index.json`),
serves `$vectorSearch`.

Two embedding services work; the first whose key is in `.env` is used:

| Key | Model | Note |
|---|---|---|
| `NVIDIA_API_KEY` | `nvidia/nemotron-3.5-embed-1b` | Not run yet: the team has no key. |
| `MONGODB_AI_API_KEY` (+ `MONGODB_AI_ENDPOINT`, default `ai.mongodb.com`) | `voyage-4` | MongoDB's embedding API. The whole catalog was embedded with it on 2026-11-14. |

A row embedded with one model is embedded again when the other model becomes the current
one: vectors of two models are never mixed in one index.

```bash
python -m store.embeddings     # embeds new and changed products; needs one of the two keys
```

A machine may hold the embedding key or the database address, not both. Then the vectors
travel as a file (about 73 MB for the whole catalog):

```bash
# where the key is (reads the catalog file, calls the embedding service, no database)
python -m store.embeddings --export-from vendor/valio/valio_aimo_junction26_product_data.json --out vectors.jsonl.gz
# where the database is (needs no key); also creates the vector index
python -m store.embeddings --import-from vectors.jsonl.gz
```

The import writes a vector only when the product row exists and its text is still the
text that was embedded. A search still needs the key on the machine that serves it,
because the query is embedded too.

`python -m store.loader` does the same after loading the catalog, and skips it with a
message when the key is missing. Reloading the catalog keeps the vectors.

```python
search_products(db, "lactose free milk", hybrid=True)                      # text + meaning
search_products(db, "oat drink", {"exclude_allergens": ["gluten"]}, hybrid=True)
```

- `hybrid=True` embeds the query, runs the text search and the vector search over the
  **same hard filters**, and lets Atlas fuse the two by rank (`$rankFusion`). A row found
  only by meaning carries the reason `similar meaning, no word match`.
- A similar meaning never overrides a filter: excluded allergens, required labels and
  the kitchen scope cut rows before ranking, and missing allergen data is still unknown.
- If the embedding service fails, the call raises `EmbeddingError`; ask again without
  `hybrid` for the plain text search.
- Storage: 17,546 vectors of 1024 float32 are 72 MB. As plain number arrays they would
  be about three times that.

## Tests

CI runs `python -m pytest`; install it next to the test extra:
`python -m pip install -e ".[test]" pytest`.

- Offline: `python -m pytest store`. Fixtures are synthetic; the live tests are skipped.
- Live on Atlas: `STORE_LIVE_TESTS=1 python -m pytest store`. The store, time-series and
  feedback tests use a throwaway database that is dropped afterwards. The search
  acceptance reads the loaded catalog, and writes and removes one own product.
