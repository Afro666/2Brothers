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
| `backtest.py` | forecast backtest (recipe vs weekday-MA vs MA28 vs Croston/SBA), results in `BACKTEST.md` |
| `llm.py` | LLM buyer: a model plays Kitchen Week from the observation JSON (Verda) |
| `llm_report.py` | table of LLM runs vs the reference policy |

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
  still sent); over `hard_cap` it is never sent (penalty 50, plus 300 if approval was
  not asked, so skipping approval never pays); a product not on
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
| `over-order` (3x, never asks approval) | 3578 | 4182 | 2081 | 4351 |
| `stop-early` (stops after Tuesday) | 775 | 239 | 1781 | -1505 |
| `do-nothing` | 185 | -1571 | -5962 | -5784 |

## LLM buyer vs the engine (#120)

```
python -m env.run --policy llm-deepseek --seed 1            # prints the reference score next to it
python -m env.run --policy llm-kimi --seeds 3 --kitchen hotel
python -m env.llm_report --markdown                         # this table, from env/out/llm/
```

On every day with a delivery tomorrow the model gets the full observation JSON (stock with
lots, forecast with menu, recipes, prices, mandate rules, Valio notices) and must answer one
JSON action. No tools and no memory: everything is in the observation. Models on Verda:
`deepseek-4-1-flash-1017` and `kimi-k3-1-pro` (`VERDA_API_KEY`), `nemotron-3.5-super-vl` on
the shared endpoint (`VERDA_INFERENCE_KEY`), with thinking on and off. Temperature 0. Replies
are parsed defensively (bad quantities are dropped, never crash the run); transcripts with
the observation, reply and action go to `env/out/llm/` (git-ignored, the key is redacted).

Results, 2026-11-13 (same seeds as the reference; score = EUR per week; "orders during
stock-out" = products ordered for a day Valio had announced it cannot deliver):

| model | kitchen | episodes | score | reference | gap | lost covers | skipped approvals | orders during stock-out | bad replies | tokens/episode |
|---|---|---|---|---|---|---|---|---|---|---|
| deepseek | restaurant | 5 | 2316 | 4145 | -1829 | 64.6 | 7 | 6 | 0 | 10555 |
| deepseek | hotel | 5 | 345 | 6233 | -5889 | 347.8 | 5 | 4 | 0 | 12113 |
| deepseek | school | 5 | 2351 | 8586 | -6235 | 592.5 | 1 | 4 | 0 | 7470 |
| deepseek | hospital | 5 | 4246 | 9709 | -5463 | 320.2 | 8 | 12 | 0 | 19922 |
| deepseek | all | 20 | 2315 | 7168 | -4854 | 331.3 | 21 | 26 | 0 | 12515 |
| kimi | restaurant | 3 | 3969 | 4861 | -892 | 43.7 | 0 | 0 | 3 | 55068 |
| kimi | hotel | 3 | 3461 | 5952 | -2492 | 156.7 | 0 | 0 | 1 | 58621 |
| kimi | school | 3 | 3972 | 9098 | -5126 | 592.2 | 0 | 0 | 2 | 30897 |
| kimi | hospital | 3 | 6754 | 8935 | -2181 | 56.3 | 0 | 0 | 3 | 79812 |
| kimi | all | 12 | 4539 | 7212 | -2673 | 212.2 | 0 | 0 | 9 | 56100 |
| nemotron | restaurant | 3 | 3433 | 4861 | -1428 | 21.1 | 0 | 0 | 0 | 112514 |
| nemotron | hotel | 3 | 1917 | 5952 | -4035 | 239.2 | 0 | 0 | 1 | 131103 |
| nemotron | school | 3 | 5598 | 9098 | -3500 | 408.7 | 0 | 0 | 1 | 87206 |
| nemotron | hospital | 3 | 6630 | 8935 | -2305 | 105.5 | 0 | 1 | 0 | 190305 |
| nemotron | all | 12 | 4395 | 7212 | -2817 | 193.6 | 0 | 1 | 2 | 130282 |
| nemotron-nothink | restaurant | 3 | 128 | 4861 | -4733 | 374.3 | 1 | 2 | 0 | 12574 |
| nemotron-nothink | hotel | 3 | -1660 | 5952 | -7612 | 612.2 | 1 | 3 | 0 | 14511 |
| nemotron-nothink | school | 3 | 1192 | 9098 | -7906 | 788.4 | 0 | 1 | 0 | 9265 |
| nemotron-nothink | hospital | 3 | -2458 | 8935 | -11393 | 992.2 | 2 | 6 | 0 | 22687 |
| nemotron-nothink | all | 12 | -699 | 7212 | -7911 | 691.8 | 4 | 12 | 0 | 14759 |

What the numbers say:

1. **No model reaches the engine.** Every model is below the reference on every kitchen
   type; the best (Kimi, Nemotron with thinking) lose about EUR 2.7-2.8k a week.
2. **The cheap fast model breaks the rules.** DeepSeek Flash skipped approval 21 times in 20
   weeks and ordered into the announced stock-out 26 times; Kimi and Nemotron (thinking)
   almost never did. Controls matter most for the model you would pick on price.
3. **Thinking is worth ~EUR 5k a week for Nemotron**, at ~9x the tokens (130k vs 15k per
   week). With thinking off it is the worst model and loses money in the hotel and hospital.

Caveats: 3 seeds per kitchen (DeepSeek 5), and seed-to-seed sd is large (see the baselines
table), so read the "all" rows. 9 of Kimi's 49 decisions hit the 16k-token cap of that run
(empty reply = no order); its score is a lower bound. Reasoning models need a large
`max_tokens` (now 64k): at 4k Kimi, at 16k Nemotron answered nothing. `/no_think` and a
reasoning budget are ignored by the Nemotron endpoint; `chat_template_kwargs.enable_thinking`
works. The live Buyer loop is a different job (it picks products and tools, the engine sets
the quantities) and runs with thinking off and a 2,048 token budget; its own numbers are in
`agent/README.md`, "Buyer loop settings".
