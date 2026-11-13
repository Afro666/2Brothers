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

Seed 1 summary: weekday averages M 198 / T 225 / W 230 / T 242 / F 260 / S 165 / S 115
covers per kitchen; 2.4% of demand short (mostly in week 1 while opening stock settles),
0.3% waste overall, 3.7–5.6% for mince and salmon (4-day shelf life).
