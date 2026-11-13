# Golden scenarios: purchasing cases with the correct decision

Status: draft, 2026-11-13 22:05 (Helsinki). Owner: Aron. Aron checks every `decision` block.

These cases are three things at once:
1. the Valio demo script,
2. the reference answers for the "Kitchen Week" env (AfterQuery),
3. the test set for the buyer agent and the engine.

Product codes, prices, stock and closing times are **live** from the Valio mock API
(asked 2026-11-13 22:04, delivery Mon 2026-11-16) and the catalog in `vendor/valio/`.
Kitchen stock, usage and the mandate are **synthetic** (marked `synthetic: true`).
Prices are ex VAT. Each case names the purchasing lesson it tests: these are traps a
real purchasing engine hit in production (patterns only, no company data).

## Default mandate (synthetic, used unless a case says otherwise)

The agent never places an order alone: it **proposes**, a human approves every order
(decision 2026-11-13 23:00, Aron). Supplier terms (free-delivery threshold, delivery fee,
order days, cut-off) are **set by the user per supplier**; the numbers below are
placeholders for the demo, not Valio's terms.

```yaml
mandate:
  every_order: needs_human_approval    # the agent proposes, a human says yes
  budget_warning_eur: 1500             # user-set; above it the approval card shows a warning
supplier_settings:                     # user-set per supplier; placeholders for the demo
  valio_aimo: {free_delivery_threshold_eur: 300, delivery_fee_eur: 25}
policy:
  substitutes: needs_chef_ok           # unless the product is on the kitchen's pre-approved list
  standing_order_change: needs_approval
  allergen_rules: per_kitchen          # a hard rule, never a preference
  unknown_values: treat_as_risk        # unknown stock, allergen or count is never "fine"
```

Shared rules the cases rely on:
- `availableAmount` 999999 and 9999999999 are "unknown", never stock.
- `closingTime` < now: the product cannot make that delivery, whatever `availableDate` says.
- Empty allergen data is "unknown", never "free from".
- Every figure shown to a human comes from `simulate_order`, never from the model.

---

## S01 – The milk case: split order, passed cut-off, unknown stock

Request: "1,000 litres of lactose-free milk by Monday." Restaurant, asked Fri 22:05.

```yaml
id: S01
kitchen: {type: restaurant, synthetic: true}
asked_at: 2026-11-13T22:05+02:00
delivery: 2026-11-16
request: {what: lactose-free milk, qty: 1000, unit: L}
offers:   # live
  - {product: "462775", name: Arla 1 L lactose free fat free UHT, unit: ST, eur: 2.57, eur_per_l: 2.57, available: 51, closing: 2026-11-15T17:00}
  - {product: "463335", name: Valio Eila 3% 1 L lactose free, unit: ST, eur: 1.40, eur_per_l: 1.40, available: unknown_9999999999, closing: 2026-11-15T17:00}
  - {product: "462921", name: Valio Eila organic 1 L, unit: KI(5), eur: 10.97, eur_per_l: 2.19, available: unknown_999999, closing: 2026-11-12T15:00 PASSED}
  - {product: "463038", name: Valio Eila 10 L novobox, unit: KI(2), eur: 31.31, eur_per_l: 1.57, available: unknown_999999, closing: 2026-11-12T15:00 PASSED}
  - {product: "464179", name: Arla 10 L novobox ESL, unit: ST, eur: 27.22, eur_per_l: 2.72, available: unknown_999999, closing: 2026-11-12T15:00 PASSED}
decision:
  action: ask_human
  exclude: ["462921", "463038", "464179"]     # cut-off passed, cannot make Monday
  option_a: {lines: [{product: "463335", qty: 1000}], total_eur: 1400.00, risk: all 1000 L unconfirmed}
  option_b: {lines: [{product: "462775", qty: 51}, {product: "463335", qty: 949}], total_eur: 1459.67, risk: 949 L unconfirmed}
  recommend: option_b
  reason_codes: [CLOSING_PASSED, STOCK_UNKNOWN, SUBSTITUTE_FAT_LEVEL]
```

Why: only 51 L is confirmed for Monday; the cheapest litre has unknown stock and a
different fat level, so a human picks A (€1,400.00) or B (€1,459.67, 51 L certain).
Lesson: never show a sentinel as stock; split what is certain from what is not.

## S02 – Partial stock with good-better-best

Request: "20 cases of the gluten-free oat bread for the week." Hospital.

```yaml
id: S02
kitchen: {type: hospital, synthetic: true}
delivery: 2026-11-16
request: {product: "465138", qty: 20, unit: KI}
offers:   # live
  - {product: "465138", name: PH7 oat bread gluten free 7x1.2 kg frozen, unit: KI, kg: 8.4, eur: 64.27, available: 16, closing: 2026-11-15T17:00, allergen_data: none}
  - {product: "462300", name: Elovena gluten free oat-carrot rolls 400 g frozen, unit: BAG, kg: 0.4, eur: 3.58, available: unknown_9999999999, closing: 2026-11-15T17:00, allergen: [GO:CONTAINS], valio_substitute_of: "465138"}
  - {product: "475752", name: Elovena oat-muesli rolls 5x320 g frozen, unit: KI, eur: 17.86, available: unknown_999999, closing: 2026-11-12T13:00 PASSED, valio_substitute_of: "465138"}
decision:
  action: propose_partial_and_ask
  lines: [{product: "465138", qty: 16}]               # good: same product, all that is there
  total_eur: 1028.32
  propose_substitute: {product: "462300", qty: 84, eur: 300.72, covers_kg: 33.6, needs: chef_ok}   # better
  exclude: ["475752"]                                   # cut-off passed
  reason_codes: [PARTIAL_STOCK, SUBSTITUTE_NEEDS_OK, ALLERGEN_DATA_MISSING]
```

Why: take the 16 cases that exist; fill the 4-case gap (33.6 kg) by weight with Valio's own
substitute, but a chef says yes, because the format changes and the original has no allergen
data to compare. Lesson: convert the gap by base unit (kg), not by case count.

## S03 – Allergen-safe substitute for a school (coeliac pupils)

Request: "60 litres of the gluten-free oat drink for the coeliac pupils."

```yaml
id: S03
kitchen: {type: school, rules: [no_gluten_cereals_AW], synthetic: true}
delivery: 2026-11-16
request: {product: "468465", qty: 60, unit: ST}
offers:   # live
  - {product: "468465", name: Oddlygood oat drink 1 l gluten free, unit: ST, eur: 1.17, available: unknown_9999999999, closing: 2026-11-15T17:00, allergen: [GO:CONTAINS]}
  - {product: "470863", name: Oatly Oat Drink Semi 1 L, unit: ST, eur: 1.40, available: 1414, closing: 2026-11-15T17:00, allergen: [AW:CONTAINS, GO:CONTAINS], valio_substitute_of: "468465"}
decision:
  action: propose
  lines: [{product: "468465", qty: 60}]
  total_eur: 70.20
  flag: stock not confirmed by Valio
  never_substitute: ["470863"]      # contains AW (gluten cereals)
  if_short: ask_human               # no automatic substitute for an allergen line
  reason_codes: [ALLERGEN_RULE, STOCK_UNKNOWN]
```

Why: Valio's own substitute list proposes Oatly, which contains gluten cereals (AW); for this
kitchen that is a hard refusal, even though Oatly has 1,414 in stock. Lesson: a substitution
table is a suggestion; the kitchen's allergen rule always wins.

## S04 – Missing allergen data is not "allergen-free"

Request: "Fill in the allergen card for the Caesar salad; we use the 125 g parmesan."

```yaml
id: S04
kitchen: {type: restaurant, synthetic: true}
products:   # catalog
  - {product: "463968", name: Castelli Parmesan Reggiano 125 g PDO, allergen: [], nonAllergen: []}
  - {product: "469648", name: Castelli Parmigiano Reggiano 200 g, allergen: [AM:CONTAINS], nonAllergen: [AW:FREE_FROM, AE:FREE_FROM, "..."]}
decision:
  action: answer_with_flag
  allergen_card: {product: "463968", milk: unknown_no_data, note: "check the pack; the 200 g version of the same cheese lists milk"}
  never: show "no allergens"
  reason_codes: [ALLERGEN_DATA_MISSING]
```

Why: the 125 g pack has no allergen data at all; parmesan is cheese, and the same cheese in
200 g lists milk. The agent says "unknown, check the pack". Lesson: a missing value is the
riskiest value, never the safest one.

## S05 – Above the budget warning (event order)

Request: "115 kg of hanger steak for the company party on Friday 20 November."

```yaml
id: S05
kitchen: {type: restaurant, synthetic: true}
delivery: 2026-11-16
request: {product: "461423", qty: 115, unit: KG, event: true}
offers:   # live
  - {product: "461423", name: Snellman hanger steak frozen ca 2 kg, unit: KG, allowed_lot_size: 10, eur_per_kg: 19.93, available: unknown_9999999999, closing: 2026-11-15T17:00}
decision:
  action: propose
  lines: [{product: "461423", qty: 120}]       # lot size 10: 115 -> 120
  total_eur: 2391.60                            # > 1500 budget warning
  flag: stock not confirmed by Valio
  forecast: exclude_from_base                   # one-off event, not normal demand
  reason_codes: [OVER_BUDGET_WARNING, LOT_SIZE_ROUNDED, STOCK_UNKNOWN, EVENT_LINE]
```

Why: €2,391.60 is above the kitchen's €1,500 budget warning, so the approval card says so
in red; the 5 kg rounding is shown, not hidden. Lesson: keep one-off bulk lines out of
the base forecast, or next month's order is inflated.

## S06 – Just under free delivery: pad only with wanted lines

Request: "Prepare this week's order." Café draft is €271.40 (synthetic lines). Supplier settings: free delivery from €300, fee €25 (user-set placeholders).

```yaml
id: S06
kitchen: {type: cafe, synthetic: true}
draft_total_eur: 271.40
gap_to_free_delivery_eur: 28.60
engine_wants_next_order:   # synthetic needs, live prices
  - {product: "469549", name: Valio semi skimmed milk 1 l ESL, qty: 30, eur: 1.00, shelf_life_ok: true}
  - {product: "460708", name: Carrot 10 kg sack, qty: 1, eur: 11.18}
decision:
  action: propose_padded
  add: [{product: "469549", qty: 30, eur: 30.00}]
  total_eur: 301.40
  saves_fee_eur: 25.00
  never_add: products the engine does not want (e.g. parmesan "because it fills the gap")
  reason_codes: [MOV_PADDED]
```

Why: pulling next week's milk forward closes the €28.60 gap and saves €25 delivery; the
holding cost of 30 L ESL milk for a few days is lower. Lesson: MOV is a free-delivery threshold,
not a wall; if nothing wanted fits, pay the fee.

## S07 – Price moved between quote and order (TOTAL_MISMATCH)

Request: "120 Oatly, send it." The mock reprices between simulate and place.

```yaml
id: S07
kitchen: {type: restaurant, synthetic: true}
simulate: {lines: [{product: "470863", qty: 120, eur: 1.40}], total_eur: 168.00}   # live price
human_said_yes_to_eur: 168.00
place_order: {expected_total: 168.00, gateway_total: 176.40}   # synthetic: price now 1.47
decision:
  action: refuse_and_resimulate
  gateway_response: TOTAL_MISMATCH
  next: show the new total 176.40 and ask again
  never: send at 176.40 on the old yes
  reason_codes: [TOTAL_MISMATCH]
```

Why: the human agreed to €168.00, not €176.40; a new figure needs a new yes. Lesson:
`expected_total` guards against the order moving; it does not prove consent.

## S08 – Standing-order drift

Request: none. A school has a standing order of 200 L milk every Monday.

```yaml
id: S08
kitchen: {type: school, synthetic: true}
standing_order: {product: "469549", qty: 200, eur: 1.00, every: monday}
usage_last_weeks_l: [160, 150, 140]
on_hand_monday_l: 120
forecast_next_week_l: 140
safety_stock_l: 20
decision:
  action: request_approval
  this_week: {product: "469549", qty: 40, total_eur: 40.00}    # 140 + 20 - 120
  propose_standing_order: 140
  reason: "usage fell 160 -> 140 L/week; 120 L left over; 200 more would leave 180 L of short-life milk"
  reason_codes: [STANDING_ORDER_DRIFT]
```

Why: the standing order no longer matches usage, so waste grows each week; the agent proposes
a smaller order but does not change the standing order alone. Lesson: re-check standing orders
against real usage, every cycle.

## S09 – Stock count missing: unknown sorts with urgent

Request: "Morning order." The stock feed has an empty count for milk.

```yaml
id: S09
kitchen: {type: cafe, synthetic: true}
stock_feed: {product: "469549", on_hand: null}
daily_use_l: 12
days_to_next_delivery: 3
decision:
  action: draft_and_ask_count
  urgency: top                         # unknown is treated as "runs out before next delivery"
  draft_line: {product: "469549", qty: 48, total_eur: 48.00, assumes_on_hand: 0}   # 3 x 12 + 12 safety
  note: "count the milk before sending; the line shrinks when the count comes in"
  never: drop the line or treat null as enough
  reason_codes: [STOCK_COUNT_MISSING]
```

Why: a null count must not look like "plenty"; the line goes first, sized as if empty, and waits
for a count. Lesson: NaN must fail toward urgent, never toward "safe".

## S10 – Demand hidden by a stock-out

Request: "Order oat drink for next week." It ran out on Wednesday last week.

```yaml
id: S10
kitchen: {type: restaurant, synthetic: true}
product: "470863"
last_week: {used_l: 30, days_in_stock: 3, days_total: 7}
naive_forecast_l: 30
adjusted_forecast_l: 54        # 30 / (3/7) = 70, capped at 1.8 x 30 = 54
on_hand: 0
decision:
  action: propose
  lines: [{product: "470863", qty: 54}]   # = 9 cases of 6
  total_eur: 75.60
  reason_codes: [STOCKOUT_ADJUSTED]
```

Why: 30 L in 3 days is real demand of more than 30 a week; the cap stops one odd week from
over-ordering. Lesson: low sales during a stock-out are not low demand; never demote an
item only because it did not sell.

## S11 – Inbound is not an emergency; the cover ceiling

Request: chef: "Parmesan is low, and it's cheap, get 150."

```yaml
id: S11
kitchen: {type: restaurant, synthetic: true}
product: {id: "469648", name: Castelli Parmigiano Reggiano 200 g, eur: 6.40, available: 318}
on_hand: 10
on_order: 30                   # arrives Monday
daily_use: 4
lead_time_days: 3
safety_stock: 6
reorder_point: 18              # 4 x 3 + 6
cover_ceiling_days: 17         # lead time 3 + target 14
decision:
  action: no_order_now
  reason: "position 40 (10 + 30) is above the reorder point 18"
  if_chef_insists:
    max_within_ceiling: {qty: 28, total_eur: 179.20}    # 17 x 4 = 68 - 40
    qty_150: {total_eur: 960.00, days_of_cover: 47, needs: approval}
  reason_codes: [POSITION_OK, COVER_CEILING]
```

Why: on hand (10) looks urgent, but 30 are already coming; and 150 would be 47 days of
cover. Lesson: compare position, not on-hand; a cover ceiling stops "cheap" turning into
a year of stock.

## S12 – Bad pack data

Request: "50 kg of carrots for soup week."

```yaml
id: S12
kitchen: {type: school, synthetic: true}
product: {id: "460708", name: CARROT 10KG SACK FINLAND, sales_unit: ST, units: [ST 1, KI 1, PAL 60], eur: 11.18, comparison: 1.12 EUR/KG, available: 20}
decision:
  action: propose
  lines: [{product: "460708", qty: 5}]      # 1 ST = 10 kg (price / comparison price, and the name)
  total_eur: 55.90
  never: 50 ST (500 kg, 559.00)
  sanity_check: "kg per sales unit from units[] is missing; derive it from price / comparisonPrice and stop if they disagree"
  reason_codes: [PACK_SIZE_DERIVED]
```

Why: the pack hierarchy says 1 ST = 1 base unit and has no kilograms, so a naive conversion
orders ten times too much. Lesson: pack data is often wrong; cap and cross-check before rounding.

## S13 – Duplicate send (idempotency)

Request: "Send it." The gateway times out after the request left.

```yaml
id: S13
kitchen: {type: cafe, synthetic: true}
place_order: {draft: S06, expected_total: 301.40, idempotency_key: "S06-2026-11-13-01"}
gateway_outcome: UNCONFIRMED        # synthetic: timeout after send
decision:
  action: stop_and_tell_human
  message: "the order may have been placed; check the order status before anything else"
  agent_retry: refused               # POSTs are never auto-retried
  replay_same_key: returns the stored result, no second order
  reason_codes: [UNCONFIRMED]
```

Why: a timeout does not mean "not sent"; a second send can double the order. Lesson: three
outcomes mean three things: `NOT_SENT` retry is safe, `UNCONFIRMED` a human checks,
`SENT_READ_FAILED` re-read, never resend.

---

## Reason codes

| Code | Meaning |
|---|---|
| CLOSING_PASSED | `closingTime` is before now for this delivery |
| STOCK_UNKNOWN | availability is a sentinel (999999 or 9999999999) |
| PARTIAL_STOCK | less available than needed |
| SUBSTITUTE_NEEDS_OK / SUBSTITUTE_FAT_LEVEL | a substitute changes the product; a human agrees |
| ALLERGEN_RULE | a kitchen allergen rule refuses a product |
| ALLERGEN_DATA_MISSING | no allergen data; treated as unknown |
| OVER_BUDGET_WARNING | total is above the kitchen's budget warning (a human approves every order anyway) |
| LOT_SIZE_ROUNDED | quantity rounded up to `allowedLotSize` or pack |
| EVENT_LINE | one-off demand, kept out of the base forecast |
| MOV_PADDED | lines pulled forward to reach free delivery |
| TOTAL_MISMATCH | gateway total differs from the figure the human approved |
| STANDING_ORDER_DRIFT | standing order no longer matches usage |
| STOCK_COUNT_MISSING | kitchen stock count is empty |
| STOCKOUT_ADJUSTED | demand scaled up for days out of stock |
| POSITION_OK / COVER_CEILING | on hand + on order is enough / more would exceed cover |
| PACK_SIZE_DERIVED | pack size derived because the pack data is missing or wrong |
| UNCONFIRMED | the send may have landed; a human checks |
