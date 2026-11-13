# env: kitchen simulation

Shared world for the synthetic history (#32) and the Kitchen Week RL env (#23).
Python 3.10+, standard library only.

| File | What |
|---|---|
| `catalog.py` | 23 real Valio products: code, pack, price (live `/api/price`, 2026-11-13), shelf life (our assumption) |
| `kitchens.py` | kitchen types (school, hospital, hotel, restaurant), recipes per cover, seeded kitchens |
| `sim.py` | stock in lots with shelf life (FIFO), deliveries with shortages, guests eating |
| `policies.py` | ordering policies: `reference` (engine stand-in), `do-nothing` |
| `history.py` | 20 kitchens x 12 weeks of history as JSON Lines |
| `week.py` | Kitchen Week RL env: one kitchen, one week, mandate, reward |
| `run.py` | runs a policy through Kitchen Week and prints the score |

## Synthetic history

```
python -m env.history --seed 1                  # writes env/out/history/*.jsonl (git-ignored)
python -m env.history --seed 2 --weeks 4 --kitchens 8 --out /tmp/h
python -m unittest discover -s env/tests -t . -v
```

Same seed, same files. Default period: Mon 2026-08-17 to Sun 2026-11-08; school autumn
holiday in ISO week 42. One day: delivery 06:00 → service → expired lots thrown away →
stock count 22:00 → order 14:00 for the next delivery day (lead time 1 day).
Per delivery line Valio delivers half (4%) or nothing (1.5%), so stock-outs happen.

Quantities: `stock` rows are in the product's kitchen unit (`L`, `KG`, `PCS`); `orders`
and `deliveries` are in Valio sales units (`pack` kitchen units each).

Dates are MongoDB Extended JSON (`{"$date": "...Z"}`). Time-series collections use
`timeField: "ts"`, `metaField: "meta"`. Load (through the repository module, or by hand):
`mongoimport --uri "$MONGODB_URI" --db kitchenweek --collection stock --file stock.jsonl`.

| File | One row per | Fields |
|---|---|---|
| `covers.jsonl` | kitchen, day | `ts`, `meta{kitchen_id,type}`, `covers` (guest meals served), `forecast_covers` (kitchen's own forecast), `open`, `menu` (recipes served) |
| `stock.jsonl` | kitchen, product, day | `ts` (22:00 count), `meta{kitchen_id,product_id}`, `unit`, `on_hand` (end of day), `received`, `used`, `short` (demand not served: stock-out), `wasted` (expired) |
| `orders.jsonl` | order | `ts` (placed), `meta{kitchen_id}`, `order_id`, `delivery_date`, `lines[{product_id,qty,sales_unit,unit_price,line_total}]`, `total_eur` (before tax) |
| `deliveries.jsonl` | order line | `ts` (06:00), `meta{kitchen_id,product_id}`, `order_id`, `ordered_qty`, `delivered_qty`, `status` (`full`/`partial`/`missing`) |
| `kitchens.jsonl` | kitchen | `kitchen_id`, `name`, `type`, `city`, `base_covers`, `delivery_weekdays` (0 = Mon), `products` |
| `products.jsonl` | product | `product_id`, `name`, `unit`, `pack`, `sales_unit`, `price_eur`, `shelf_life_days`, `abc` |
| `recipes.jsonl` | recipe | `recipe`, `per_cover{product_id: qty}` |

Seed 1 summary: weekday averages M 198 / T 225 / W 230 / T 242 / F 260 / S 164 / S 114
covers per kitchen; 2.8% of demand short (mostly in week 1 while opening stock settles),
0.5% waste overall, most of it mince and salmon (4-day shelf life).

## Kitchen Week (RL env)

```
python -m env.run --policy reference --seed 1                # score + breakdown + events
python -m env.run --policy all --seeds 20 --kitchen hotel    # baselines, mean and sd
python -m env.run --policy reference --seed 1 --json
```

One kitchen (`--kitchen restaurant|hotel|school|hospital`, picked by seed), Mon 2026-11-16
to Sun 2026-11-22. `KitchenWeek.reset()` returns the Sunday 14:00 observation; each
`step(action)` places the order for tomorrow, then simulates tomorrow. 7 steps.

- **Action:** `{"order": {product_id: sales_units}, "request_approval": bool, "stop": bool}`.
  Orders only count when tomorrow is a delivery day (`obs["order_for"]`).
- **Observation:** stock with lots and last-use days, open orders, products with pack and
  price, 7-day cover forecast with menu, recipes, mandate rules, Valio notices, yesterday.
- **Mid-week stock-out:** Valio cannot deliver one of the two most-used A products
  Wednesday to Friday, announced in `obs["valio_notices"]`.
- **Mandate:** order total over `auto_limit` needs `request_approval` (else penalty 300,
  still sent); over `hard_cap` a human refuses (penalty 50, not sent); a product not on
  the kitchen's list is refused (penalty 50). Under `mov` (EUR 200) costs a 45 fee.

**Reward** = revenue − food cost − waste − excess stock − delivery fees − stock-out
penalty − mandate penalty. Revenue per cover is the menu-price share of these
ingredients (ingredients ≈ 35%). A cover is lost when an A ingredient of its dish is
missing (B/C missing: a quarter); a lost cover also costs 50% goodwill. Excess stock =
stock value left above the opening stock, in full for shelf life ≤ 7 days, else 25%.
Under-order (`stockout_days`, `lost_covers`) and over-order (`wasted_qty`, `waste`) are
reported separately.

Baselines (20 seeds, mean score EUR; sd is about 30–40% of the mean, so compare means
over many seeds):

| policy | restaurant | hotel | school | hospital |
|---|---|---|---|---|
| `reference` (engine, reads notices) | 4314 | 5871 | 10001 | 9434 |
| `ignore-notices` (engine, blind to the stock-out) | 3193 | 3840 | 6950 | 5737 |
| `over-order` (3x, never asks approval) | 3578 | 4544 | 6783 | 6121 |
| `stop-early` (stops after Tuesday) | 775 | 239 | 1781 | -1505 |
| `do-nothing` | 185 | -1571 | -5962 | -5784 |
