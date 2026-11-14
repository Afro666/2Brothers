# Submission notes (#369)

Text for the Junction 2026 form, one section per track. Every claim names its source: a
path in this repo or a live URL. Checked against `main` on 2026-11-14. A line marked
**Not built** is not in the product today.

## What it is

- Trusted Kitchen Buyer: a purchasing agent that Valio Aimo can give to its kitchen customers.
- A chef asks in plain words. The Buyer agent (Nemotron 3.5 Super VL) finds the products.
- The gateway reads live Valio prices and stock. A deterministic engine sets every quantity.
- A person approves every order. Every step is in a hash-chained audit log.
- Any other agent can use the same gateway over MCP or REST with a kitchen token.

Team 2Brothers: Aron (gateway, engine), Tymon (web, store), Maciek (agent, env, signals).

Live site: <https://31-22-104-201.sslip.io>. For agents:
[`/llms.txt`](https://31-22-104-201.sslip.io/llms.txt),
[`/.well-known/agent-card.json`](https://31-22-104-201.sslip.io/.well-known/agent-card.json),
[`/gateway/openapi.json`](https://31-22-104-201.sslip.io/gateway/openapi.json),
[`/api/docs`](https://31-22-104-201.sslip.io/api/docs).

## Main track: Valio Aimo, Trusted Trade Agents

**Core requirements**

1. Product, price and availability lookup. Search is one Atlas Search index over 17,546
   catalog products. Price and stock come live from Valio's challenge API.
2. Inquiry to order on fixed prices. A request becomes a proposal with a 15-minute offer
   snapshot. A person approves it. The order is then stored in our gateway. Valio's
   challenge API has no order endpoint, so no order reaches Valio.
3. Permissions and human approval. A kitchen token has scopes and can never approve.
   Approval needs a person's session and the exact total the person saw.

**Rubric**

| Criterion | What we show | Source |
|---|---|---|
| A. Working end-to-end demo (30%) | Ask, live lookup, sized proposal, human approval, stored order, audit trail, on the live site | `gateway/README.md` ("HTTP gateway"), `deploy/compose.yaml` |
| B. Matches what the buyer asked (20%) | The engine sizes each line from the stored need. The model picks products only. Each line has a `why` sentence. | `engine/README.md`, `docs/choices.md` |
| C. Autonomy and controls (20%) | Approve is human-only. A moved price refuses the old yes (`TOTAL_MISMATCH`). Auto-approve exists, is off by default, and must be earned (4 weeks, 20 human decisions). Twelve live conformance checks. | `gateway/README.md` ("Earned auto-approve", "Conformance kit"), `gateway/conformance.py` |
| D. Robustness to exceptions (15%) | 13 golden scenarios in one command: all 13 PASS (table below). Unknown stock is never treated as stock. A recall blocks a proposal. | `gateway/scenarios.py`, `docs/scenarios.md`, `docs/recall-contract.md` |
| E. Openness and path to production (15%) | The same rules over MCP and OpenAPI. Public `llms.txt` and agent card. Scoped tokens, signed webhooks, one adapter per supplier. | `docs/byoa.md`, `gateway/discovery.py`, `gateway/suppliers.py` |

**Optional features**

- Sustainability and delivery reliability: each proposal line carries `reliability` and
  `carbon_kg_co2e_per_kg` from Valio's datasets (`gateway/service.py`).
- Substitution and exceptions: up to three engine-priced substitute baskets, each needs the
  chef's approval (`agent/substitutes.py`, `agent/README.md`). Partial fill: order the
  confirmed stock now, plan the rest (`engine/partial.py`).
- Traceability: insert-only audit log with a hash chain (`store/audit.py:129`). Recall
  notices are matched by EAN, brand and lot (`monitor/README.md`).

**Golden scenarios.** Output of `python -m gateway.scenarios --markdown` on `main`, 2026-11-14:

| Case | What | Layer | Result | Detail |
|---|---|---|---|---|
| S01 | Milk: split order, passed cut-off, unknown stock | gateway HTTP | **PASS** | lines = [('462775', '51'), ('463335', '949')]; total ex VAT (option B) = 1459.67 |
| S02 | Partial stock, good-better-best | engine | **PASS** | lines = [('465138', '16')]; total = 1028.32 |
| S03 | Allergen-safe substitute for a school | gateway HTTP | **PASS** | lines = [('468465', '60')]; total ex VAT = 70.20 |
| S04 | Missing allergen data is not allergen-free | catalog (store.products) | **PASS** | 125 g allergen data known = False; 125 g says no allergens = False |
| S05 | Above the budget warning (event order) | engine | **PASS** | lines = [('461423', '120')]; total = 2391.60 |
| S06 | Just under free delivery: pad with wanted lines | engine | **PASS** | add = [('469549', '30')]; total = 301.40 |
| S07 | Price moved between quote and approval | gateway HTTP | **PASS** | old yes is refused = (409, 'TOTAL_MISMATCH'); orders placed on the old yes = 0 |
| S08 | Standing-order drift | engine | **PASS** | this week qty = 40; proposing the standing order 200 -> 140: not built |
| S09 | Stock count missing: unknown sorts with urgent | engine | **PASS** | draft qty (sized as if empty) = 48; urgency top = True |
| S10 | Demand hidden by a stock-out | engine | **PASS** | adjusted forecast L/week = 54.0; qty = 54 |
| S11 | Inbound is not an emergency; the cover ceiling | engine | **PASS** | order now = 0; max within ceiling = 34 |
| S12 | Bad pack data (10 kg carrot sack) | engine | **PASS** | lines = [('460708', '5')]; total = 55.90 |
| S13 | Duplicate send (idempotency) | gateway HTTP | **PASS** | replay with the same key returns the stored order = True; orders stored = 1 |

13 PASS

**Not built:** an order sent to Valio (their API has no order endpoint,
`gateway/README.md:104`). A mandate as a
verifiable credential (planned in `docs/plan.md`, not in the code).

## NVIDIA: Best Use of Nemotron

**Model.** Nemotron 3.5 Super VL (`nemotron-3.5-super-vl`) on Verda's shared inference
endpoint (`agent/model.py:18`, `agent/model.py:27`). We did not train or fine-tune it.

**What it does.** It is the Buyer agent. It reads the chef's request and calls seven MCP
tools: search, offer, simulate, request approval, place order, order status and audit log
(`gateway/mcp_server.py:83`, `agent/runner.py`). It chooses the products and the next step.
It never sets a quantity, a price or a total, and it has no approve tool. The deployed
gateway sends free-text requests to it (`deploy/compose.yaml:41`, `agent/service.py`). The
vision side reads a delivery-note photo and a shelf photo into a strict JSON schema
(`agent/vision.py`, `agent/receiving.py`, `agent/shelf.py`). Plain code then compares the
note with the order.

**Why it matters.** A chef writes a sentence, not product codes. The model turns it into
catalog products and a reason a person can read. A wrong model answer cannot become a
wrong order, because the engine sizes the lines and a person approves.

**How we improved its outputs.** We measured first. On our Kitchen Week benchmark (12
weeks per model, `env/README.md:130`, `env/README.md:135`):

| Setting | Score EUR/week | Gap to engine | Skipped approvals | Orders into a stock-out |
|---|---|---|---|---|
| Nemotron, thinking off | -699 | -7911 | 4 | 12 |
| Nemotron, thinking on | 4395 | -2817 | 0 | 1 |
| Kimi K3.1 Pro | 4539 | -2673 | 0 | 0 |
| DeepSeek V4.1 Flash (20 weeks) | 2315 | -4854 | 21 | 26 |

Thinking on is worth about EUR 5,000 a week at about 9 times the tokens. No model reaches
the engine, so the engine keeps the numbers. Other changes: the reply budget went to 64k
tokens, because Nemotron answered nothing at 16k (`env/README.md:150`). A rejected read
call returns a fixed reason code, and live Nemotron then corrected its call
(`agent/README.md:284`). Vision replies use a strict JSON schema with thinking off; a
reply outside the schema is refused whole (`agent/model.py:37`, `agent/vision.py`). A
scripted prompt-injection test shows the guards hold when the model obeys the attack
(`agent/conformance.py`, `agent/README.md:49`).

**Not built:** fine-tuning. The gate decided no-go: no GPU budget and no validated
recipe, so we claim no adapter gain (`docs/fine-tuning-gate.md`). The gateway route that
stores a delivery-note result and the photo button on the stock page
(`agent/README.md:98`, `agent/README.md:135`). The benchmark has 3 seeds per kitchen type,
so read the "all" rows only.

## MongoDB Atlas

The database is MongoDB Atlas. `store/` is the only package that talks to it
(`store/README.md`, `docs/decisions.md`).

| Atlas feature | What we use it for | Source |
|---|---|---|
| Atlas Search | One index, `products_search`, over English, Finnish and Swedish names. One typo allowed, allergen exclusion, size boost. The gateway's product search calls it. | `store/search.py:153`, `store/search_index.json`, `gateway/service.py` |
| Time-series collections | Stock counts, covers, orders, deliveries, forecasts and feedback per kitchen and day | `store/history.py:35` |
| `$setWindowFields` with `$lookup` | Standing-order drift: this week against the mean of earlier weeks, in one aggregation | `store/drift.py:62`, `gateway/drift_routes.py` |
| Change streams | `watch_kitchen` follows proposals, approvals and the audit log of one kitchen | `store/trust.py:112` |
| `Decimal128` | Money is `Decimal` in Python and `Decimal128` in Mongo. A binary float is refused. | `store/db.py:21`, `store/orders.py` |
| Unique indexes | `(kitchen_id, idempotency_key)`: a repeated send returns the stored order | `store/db.py:63` |
| Hash-chained audit log | Insert-only. Each row stores the hash of the row before. `verify_chain` finds a changed row. | `store/audit.py:91`, `store/audit.py:129` |

Why it matters: an order must not be sent twice, money must not round, and a person must
be able to check that nobody changed the log. The catalog and its indexes take about
121 MB of the free tier's 512 MB (`store/README.md`).

**In progress, not on `main`:** Atlas Vector Search with hybrid search (draft PR #405,
issue #366).
**Not built:** a gateway route for the change stream and for the tamper check. Both are
in `store/trust.py` with tests; no gateway module calls them yet.

## Context.dev: Fully Structured Web

We call two Context.dev endpoints.

| Endpoint | Where | Why |
|---|---|---|
| `POST /v1/web/scrape` (JSON format with a schema) | `monitor/recalls.py:35`, `monitor/recalls.py:69` | Reads the Finnish Food Authority recall list and each notice page into products with name, brand, EAN, pack size and lot |
| `POST /v1/web/scrape`, same client | `monitor/enrichment.py`, `monitor/labels.py` | Reads one manufacturer page for a replacement product, and the Hyvää Suomesta producer register for a label check |
| `POST /v1/brand/retrieve` | `gateway/onboarding.py:27` | A kitchen's email or website becomes its name, logo, colours and address for onboarding |

**How the data drives the core flow.** The monitor matches a recall notice to the lines of
an open proposal. An exact or possible match holds the proposal. The gateway then refuses
the approval with 409 `BLOCKED_BY_RECALL` (`gateway/service.py`). A hold never expires
by itself: a person checks the packs first (`docs/recall-contract.md`). The monitor also
writes a separate replacement proposal with a live Valio quote; it never orders
(`monitor/proposals.py`, `monitor/README.md`). `POST /v1/kitchens/{k}/recalls/check` makes
one live scrape of the list and says whether the answer is `live` or the `recording`
(`gateway/recalls_view.py`, `deploy/README.md`).

The recorded run (2026-11-13, 38 notices) matches a coffee recall to product 461332 in
three demo kitchens (`monitor/README.md`).

**Not built:** the deployed web inbox does not show the recall yet. The components exist
(`web/src/components/purchasing/recall-panel.tsx`), but the web app does not call the
gateway's recall routes in gateway mode (#655). Today the hold is visible in the API
answers only. The onboarding page does not call the lookup route yet (#452). In a gateway
check the notice pages come from the recording; only the list is scraped live. On
2026-11-14 the live site had run no check and had no alerts
(<https://31-22-104-201.sslip.io/api/v1/kitchens/demo-kitchen/recalls>).

## OpenAI: Best Use of Codex

What the repo proves today:

- One rule set for every agent. `AGENTS.md` points Codex at `CLAUDE.md`: one issue, one
  branch, one PR, and an automatic review on every PR.
- `CLAUDE.md` names Codex as Maciek's agent. His areas are `agent/`, `env/` and `signals/`.
- `agent/README.md:271` records that Codex implemented the Valio adapter (#20), the MCP
  integration (#21) and the Buyer loop (#22), each on its own issue branch with a reviewed
  PR. The MCP tools are `gateway/mcp_server.py` (PR #54); the loop is `agent/runner.py`
  (PR #63).
- Five decisions in `docs/decisions.md` are tagged Codex: the unknown-stock rule (#48),
  read-only policy recovery (#67), the closed reason-code list (#96), the fine-tuning
  no-go (#364) and the recall-hold rule (#459).
- The gateway serves the Buyer tools over MCP at `/mcp`, so Codex can also be the Buyer
  (`gateway/README.md`, "Remote MCP").
- The team set up Codex CLI profiles for Kimi and DeepSeek on Verda as optional workers
  (`docs/decisions.md`, 2026-11-13 20:40).

**Not built:** `docs/codex.md` with metrics and a recording (#360). We have no measured
number for how much Codex sped the work up, so we state none here.

## Open items before submission

- [ ] Paste each section into the Junction form (#369).
- [ ] Record the 3-minute demo and the fallback video (#295).
- [ ] Codex: write `docs/codex.md` with metrics and the 90-second recording (#360). The
      Codex section has no speed-up number without it.
- [ ] Context.dev: on the server, run `python -m demo.recall_demo` and one recall check
      before the recording, so a held proposal exists (`deploy/README.md`).
- [ ] Context.dev: wire the recall routes into the web inbox (#655, #557). Without it the
      Context.dev data does not show in the web demo, and the sponsor asks for that.
- [ ] Context.dev: wire the onboarding lookup (#452). Limit credit spend on the open demo
      (#604, #652).
- [ ] Nemotron: improvement round on the benchmark with a token meter (#365). Store a
      delivery-note result through the gateway (#362) and add the shelf photo button (#373).
- [ ] MongoDB: merge Atlas Vector Search (draft PR #405, #366), or keep it out of the form.
- [ ] Valio: emit the two missing reason codes so S01 and S02 pass (`docs/scenarios.md`).
- [ ] Run `python -m gateway.conformance` against the live gateway and add its table here
      (C12 can crash on an SSE answer: #653).
