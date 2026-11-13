# Plan: purchasing agent for restaurants

Status: draft, 2026-11-13 (before the opening). Owner: Aron.

## The idea in one line

A restaurant's purchasing agent orders from Valio Aimo through a **trusted agent gateway**:
the numbers come from a proven purchasing engine, the model chooses and explains, a human
approves every order, and every step is in an audit log.

## Challenges we enter

| Challenge | Role | Why it fits |
|---|---|---|
| **Valio Aimo – Trusted Trade Agents** (€4k) | **Main** | The whole product. |
| Verda Compute Track ($10k credits) | Tech | Host Nemotron and the app (Docker, deployed by GitHub Actions). |
| NVIDIA Nemotron (RTX 5080) | Tech | Nemotron 3.5 Super VL is the buyer agent; VL reads delivery notes / menus. |
| Context.dev – Fully Structured Web (€750) | Tech | Live food-recall and price monitors trigger re-plans. |
| MongoDB Atlas (kit) | Tech | Suppliers, menus, history, audit log, order store. Decided 2026-11-13 (see `docs/decisions.md`); Aiven dropped. |
| OpenAI – Best Use of Codex ($10k credits) | Tech | Maciek builds with Codex; log how. |
| Entire (projector) | Tech | Our agent workflow. |

Skip: AfterQuery (dropped 2026-11-13 23:45: we stay with Valio), Cala, Aiven, CRACI, Gemini/Gemma, Solana.

## Valio Aimo scoring → what we build

| Criterion | Weight | Our answer |
|---|---|---|
| Working end-to-end demo | 30% | request → lookup → simulate → order or approval, on their mock API |
| Matches what the buyer asked | 20% | engine computes quantity from recipes × covers − stock; model never invents numbers |
| Autonomy and controls | 20% | signed mandate, approval inbox, audit trail |
| Robustness to exceptions | 15% | partial availability, good-better-best substitution, allergen rules, delivery cut-off |
| Openness, path to production | 15% | MCP + OpenAPI, mandate as a verifiable credential (JWT/VC), documented assumptions |

## Architecture

```
Restaurant side                         Valio Aimo side (we mock the gateway, they mock the backend)
-------------------                     ------------------------------------------------------------
Chef / buyer UI (Tymon)                 Agent Gateway (Aron)  = MCP server + OpenAPI
  menu, covers, approvals, audit          search_products      -> structured catalog rows
        |                                 get_offer            -> price, availability, lead time, labels,
Buyer agent (Maciek)                                              offer_id valid until T
  Nemotron 3.5 Super VL on Verda          simulate_order       -> total, delivery date, MOV gap,
  + purchasing engine (Python)                                    policy verdict (propose / refused) + warnings
        |                                 place_order(offer_id, expected_total, idempotency_key)
        +----------- MCP --------------->  request_approval / approval status
                                          order_status, audit_log
Context.dev monitors (recalls, prices) --> webhook --> re-plan
```

## What we reuse from Aron's production purchasing engine

Patterns only, no data. Source: the engine's code and docs (read 2026-11-13).

**Quantities (deterministic, never from the LLM)**
- Need = forecast covers × recipe quantity − stock on hand − stock on order.
- Safety stock = Z·√(LT·σ²_d + d²·σ²_LT); service level by class (A 97.5%, B 95%, C 90%).
  For a kitchen: A = menu-critical (milk, main protein), C = garnish.
- Reorder point = daily demand × lead time + safety stock. Compare **position** (on hand + on
  order), not on-hand, or inbound stock looks like an emergency.
- Cover ceiling: never more than lead time + target days of cover (perishables: shelf life).
- Rounding order: MOQ floor → pack multiple → sanity cap on bad pack data.
- Demand seen during a stock-out is undercounted: divide by the in-stock share (cap 1.8×).
- Remove one-off bulk lines (an event) from the base forecast; plan events separately.

**Every line carries a "why"**
- A short deterministic sentence from a small decision tree ("2 × 10 L: Monday covers 180 ×
  0.05 L, stock 3 L, lead time 1 day"). The model may rephrase it, never change the number.

**Minimum order value / delivery fee**
- Treat MOV as a free-delivery threshold, not a wall.
- Pad only with lines the engine already wants, smallest item that closes the gap first.
- Pad only if delivery fee saved > holding cost (perishables: spoilage risk).

**Urgency**
- Tiers: guests affected today → runs out before the next delivery → due now → can wait.
- A missing value is never "safe": unknown sorts with urgent.

**Sending an order safely (this is the Valio "controls" score)**
- Simulate before quoting any figure. The agent shows the human the exact total.
- `place_order` takes `expected_total`; the gateway refuses with `TOTAL_MISMATCH` if price
  or stock moved since the simulate (tolerance €0.005).
- Idempotency: an attempt row is written *before* the backend call, plus a payload hash and
  an `Idempotency-Key`. A replay returns the stored result.
- Three failure outcomes, each with a different meaning:
  `NOT_SENT` (safe to retry), `UNCONFIRMED` (a human checks; blocks the order),
  `SENT_READ_FAILED` (it landed; re-read, never resend). POSTs are never auto-retried.
- The agent may not approve, cancel, or release a stuck order. It may only add products the
  engine scored for this need.
- "expected_total guards against the order moving, it does not prove consent." Consent is a
  human "yes" in the approval inbox, recorded in the audit log.

## Kitchen planning and own suppliers (Aron, 2026-11-13 23:00)

- **No auto-approve.** The agent proposes every order; a human approves it. The mandate
  only limits what the agent may *propose* (allergen rules, approved substitutes, budget
  warning).
- **Suppliers are the user's.** Valio Aimo is one supplier, not the only one. The user adds
  suppliers and sets each one's terms: free-delivery threshold, delivery fee, order days,
  cut-off time, lead time. Valio comes with a live API adapter; other suppliers start as
  manual entry or a CSV price list.
- **Own products.** The user adds products that are not in a supplier catalog (name, unit,
  pack size, price, supplier, allergens).
- **Meals and menus.** The user builds recipes from products (quantity per portion), plans
  menus per day and week, and enters expected covers.
- **Future demand.** Menu plan x covers x recipe quantity - stock - on order gives the need
  per product and day, weeks ahead. The same numbers feed the Valio demand view.

## Two-sided: what Valio told us at their stand (2026-11-13 evening)

Valio wants to **give this tool to their customers**, so kitchens order faster and know what
they will need. Two additions follow from that:

1. **Kitchen stock integration (customer side).** The kitchen's current stock feeds the
   engine: manual count, CSV, or a mock POS/inventory feed. Need = forecast − stock − on order.
2. **Valio demand view (wholesaler side).** With the kitchen's consent, its forecast need is
   shared with Valio. Valio sees, per product and delivery day, the **predicted demand across
   all customers** vs. its own availability: shortage risk before orders arrive, what Valio
   itself should buy from its suppliers, and which customers to offer a substitute early.
   This is the same purchasing engine one level up (warehouse reorder point, safety stock,
   lead time from supplier). It also covers Valio's "proactive selling agent" scenario.

Trust and data ownership: the kitchen decides what it shares (forecast only, never menus or
prices it got elsewhere); every share is in the audit log. That is Valio's "trust protocol"
question, answered from both sides.

Data we must generate: synthetic order and stock history for ~20 kitchens (hotel, school,
hospital, restaurant) over ~12 weeks, using real catalog products. The Kitchen Week sim
(`env/`, below) produces it, so one generator serves the demo and the forecasts.
Store history in MongoDB time-series collections.

## Synthetic kitchen history (`env/`)

AfterQuery is dropped (2026-11-13 23:45). The `env/` simulator stays as the generator of
synthetic kitchen history (orders, stock, covers) for the forecast and the Valio demand view.

## Team split

| Who | Area (folder) | First task |
|---|---|---|
| Aron | `gateway/` + `engine/` (Python, FastAPI, MCP) | wrap the Valio mock API; simulate + place_order with guards |
| Tymon | `web/` (approval inbox, audit log, chef view; mobile-friendly) | screens on mock JSON from `docs/contract.md` |
| Maciek (Codex) | `agent/` + `env/` (Nemotron Buyer on Verda, history generator) | Nemotron tool-calling loop against the gateway |

## Timeline

- Fri 18:00–21:00: opening, Valio + Verda booths, get resources, **preliminary
  submission by 23:59**.
- Fri night: contract in `docs/contract.md`, skeletons, first end-to-end call to Valio mock.
- Sat 12:00: **happy path works end to end** (milk example).
- Sat 20:00: exceptions (partial stock, substitution, allergens), audit log UI, menu planner.
- Sun 04:00: feature freeze. Then demo script, video, submission texts.
- Sun 10:00: final submission.

## Open questions (ask at the booths)

1. Valio: API docs and base URL (portal), rate limits, are recipes/allergens in the catalog?
2. Verda: which Nemotron endpoint/model name, and GPU access for fine-tuning.
