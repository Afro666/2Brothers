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
| E. Openness and path to production (15%) | The same rules over MCP and OpenAPI. Public `llms.txt` and agent card. Scoped tokens, signed offers and signed order receipts (one public key), signed webhooks, one adapter per supplier. An outside MCP client reaches a waiting proposal and gets 403 on approve (`python -m demo.second_agent`). | `docs/byoa.md`, `gateway/discovery.py`, `gateway/signing.py`, `gateway/suppliers.py`, `demo/second_agent.py` |

**Optional features**

- Sustainability and delivery reliability: each proposal line carries `reliability` and
  `carbon_kg_co2e_per_kg` from Valio's datasets (`gateway/service.py`).
- Substitution and exceptions: up to three engine-priced substitute baskets, each needs the
  chef's approval (`agent/substitutes.py`, `agent/README.md`). Partial fill: order the
  confirmed stock now, plan the rest (`engine/partial.py`). On the live site the 1,000 L
  milk request shows this as option A, "Order the confirmed 698 L now. The other 302 L is
  held until the supplier confirms stock"; a person chooses it and approves its exact total
  (`gateway/options.py`, `docs/demo.md`).
- Proactive selling agent: Valio's own agent reads the predicted shortages of the kitchens
  that share their forecast, and offers a kitchen a substitute that can arrive. The offer is
  a suggestion: no price and no quantity come from the supplier, and a person turns it into
  a normal proposal (`agent/seller.py`, `gateway/supplier_offers.py`, `docs/contract.md`
  "Supplier offers"). Run once on the live site on 2026-11-14.
- Stock from a photo: Nemotron VL reads a shelf photo into counts that a person checks and
  saves (`gateway/stock_photo.py`).
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
endpoint (`agent/model.py:43`, `agent/model.py:54`). We did not train or fine-tune it.

**What it does.** It is the Buyer agent. It reads the chef's request and calls seven MCP
tools: search, offer, simulate, request approval, place order, order status and audit log
(`gateway/mcp_server.py:83`, `agent/runner.py`). It chooses the products and the next step.
It never sets a quantity, a price or a total, and it has no approve tool. The deployed
gateway sends free-text requests to it (`deploy/compose.yaml:41`, `agent/service.py`). The
vision side reads a delivery-note photo and a shelf photo into a strict JSON schema
(`agent/vision.py`, `agent/receiving.py`, `agent/shelf.py`). Plain code then compares the
note with the order.
The shelf reader is live on the Stock page ("Count from a photo", #373): on a prepared
test photo it filled five counts in about 2 s, and the half hidden pack got "please count"
and no number; a person saves (`gateway/stock_photo.py`, `agent/shelf_service.py`,
`docs/demo.md` "Photo beat").
It also has a second role, on the supplier's side (#374): Valio's selling agent
(`agent/seller.py`). Code reads the shortage view and builds a shortlist of at most five
substitutes; the model picks one and writes the reason; a pick outside the shortlist means
no offer. The gateway takes no price and no quantity from it (`gateway/supplier_offers.py`).
Live on 2026-11-14 it offered the demo kitchen Rosamunda washed potato in place of washed
potato that is predicted short on 16 Nov; a person made a proposal from the tile, and that
proposal waits for approval like any other (`docs/demo.md` "Selling-agent beat").

**How much we use it.** A token meter counts every model call per role from the
endpoint's `usage` field (`agent/usage.py`, `agent/README.md` "Token meter"). Measured on
2026-11-14 with the settings the product runs: one Buyer request is about 4 model calls,
44,700 prompt tokens and 290 completion tokens (before the settings change: 2,250
completion tokens, of which 1,720 reasoning). One photo read is one call of about 1,300 to
2,100 prompt tokens and 190 completion tokens. The benchmark used about 130,000 tokens per
kitchen week with thinking on, over 12 weeks (`env/README.md`, the "tokens/episode"
column). Measuring the live loop on 2026-11-14 took 184 Buyer requests: 832 model calls
and 9.57 million tokens (`agent/README.md` "Buyer loop settings"). The site shows the
kitchen's own count on the About page, from
`GET /v1/kitchens/{kitchen_id}/model-usage` (`gateway/model_usage.py`,
`store/agent_runs.py`).

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
(`agent/README.md:422`). Vision replies use a strict JSON schema with thinking off; a
reply outside the schema is refused whole (`agent/model.py:66`, `agent/vision.py`). A
scripted prompt-injection test shows the guards hold when the model obeys the attack
(`agent/conformance.py`, `agent/README.md:49`).

The live Buyer loop got its own measurement, because there the model picks products and
tools and sets no quantity (`agent/README.md` "Buyer loop settings", 24 requests per
variant on the live model). Before, it ran on the endpoint default (thinking on) with a
2,048 token reply budget: 5 of 346 model calls used the whole budget on reasoning and
returned no tool call, so the run stopped and started again. The product now runs with
thinking off, 2,048 tokens, and a prompt that asks for one offer with the three best
products that can arrive (`agent/model.py`, `agent/runner.py`):

| Live loop | Finished | On the first attempt | Completion tokens per request | Median seconds |
|---|---|---|---|---|
| Before: thinking on, old prompt | 24 of 24 | 20 | 2,251 | 14.1 |
| Now: thinking off, one-offer prompt | 24 of 24 | 24 | 289 | 8.8 |

The first offer now has three products every time (before: 1 to 5), and repeated runs of
one request give the same products much more often. So thinking is on where the model
decides numbers (the benchmark) and off where the engine does (the product).

**Not built:** fine-tuning. The gate decided no-go: no GPU budget and no validated
recipe, so we claim no adapter gain (`docs/fine-tuning-gate.md`). The gateway route that
stores a delivery-note result (`agent/README.md:98`). A test of the shelf reader on a real
phone photo: only synthetic photos were read. The benchmark has 3 seeds per kitchen type,
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

**Atlas Vector Search.** The index `products_vector` (1,024 dimensions, cosine) and the
hybrid search with `$rankFusion` are on `main` (`store/search.py`, `store/embeddings.py`,
`store/vector_index.json`). The vectors come from MongoDB's own embedding API (model
`voyage-4`); they are computed once and travel as a file (`python -m store.embeddings
--export-from ... --out ...`, then `--import-from`). The gateway uses hybrid search only
with `SEARCH_HYBRID=true` and falls back to the text search on any failure; the tool
answer says which one ran (`gateway/catalog_search.py`). It is off by default.

**Also served by the gateway:** the tamper check and the change stream. `GET
/v1/kitchens/{k}/audit/verify` walks the hash chain, and the Trust page runs a tamper test
on the live log: change one line, "Chain broken at line N", restore, "Chain OK"
(`gateway/trust_routes.py`, `store/trust.py`).

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

**In the web app.** The approvals inbox has a recall panel with "Check recalls now"; a
held proposal sits in its own group with the notice and a link to its replacement
(`web/src/components/purchasing/recall-panel.tsx`, the routes in `gateway/recalls_view.py`).
The onboarding page calls the brand lookup and fills the form
(`web/src/api/http-onboarding.ts`). Both are limited on the open demo site: 10 lookups a
minute and a 60 second recall cooldown (`gateway/limits.py`).

**Limits to know.** The server needs `CONTEXT_DEV_API_KEY`; without it the onboarding
lookup answers 502 and the recall check answers from the recording and says so. In a
gateway check the notice pages come from the recording; only the list is scraped live.

## OpenAI: Best Use of Codex

The evidence is in `docs/codex.md`: numbers from the GitHub API, six episodes with PR
links, and the limits. The numbers below are from `python docs/codex_metrics.py --until
2026-11-14T03:30:00Z`.

- One rule set for every agent. `AGENTS.md` points Codex at `CLAUDE.md`: one issue, one
  branch, one PR, and an automatic review on every PR.
- Maciek works with Codex and, next to it, a Claude Code session. 42 merged PRs came from
  his Codex session: 11% of the 368 merged PRs, with 6,478 added lines. 2,613 of those
  lines (40%) are in test files.
- 41 of the 42 Codex PRs passed the first automatic review. The review blocked one (#87)
  because its code was ahead of the contract.
- Codex built the Valio client (#45), the MCP tools (#54), the Nemotron Buyer loop (#63),
  the weather and season signals (#183, #207), the human approval flow (#436) and the
  recall holds with replacement baskets (#455). `agent/README.md:409` records the first three.
- Codex also worked as a second reviewer: on #120 it found six failing cases in code that
  the Claude Code session wrote, before the PR opened.
- Five decisions in `docs/decisions.md` are tagged Codex: the unknown-stock rule (#48),
  read-only policy recovery (#67), the closed reason-code list (#96), the fine-tuning
  no-go (#364) and the recall-hold rule (#459).
- The gateway serves the Buyer tools over MCP at `/mcp`, so Codex can also be the Buyer
  (`gateway/README.md`, "Remote MCP").

**Not Codex:** `env/` (Kitchen Week and the benchmark) and the first recall monitor came
from Maciek's Claude Code session. Aron and Tymon use Claude Code. The review bot and the
fix bot are Claude.

**Not built:** the screen recording, and Maciek's own prompts and time estimates (#360,
"For Maciek to fill in" in `docs/codex.md`). We have no measured number for how much Codex
sped the work up, so we state none here. No CI step runs Codex (#361).

## Open items before submission

- [ ] Paste each section into the Junction form (#369).
- [ ] Record the 3-minute demo. The fallback video: `python -m demo.record_demo --approve` (#295).
- [ ] Server keys: `CONTEXT_DEV_API_KEY` (onboarding lookup, live recall check),
      `MONGODB_AI_API_KEY` (hybrid search), `GATEWAY_SIGNING_KEY` (#755).
- [ ] Context.dev: on the server, run `python -m demo.recall_demo` before the recording, so
      a proposal with the recalled coffee exists (`deploy/README.md`).
- [ ] MongoDB: import the product vectors on the server and decide on `SEARCH_HYBRID`
      (#366). Until then the form says "vector search is built and off by default".
- [ ] Codex: Maciek's three prompts, time estimates and the 90-second recording (#360).
- [ ] Nemotron: the improvement round on the benchmark (#365). Store a delivery-note result
      through the gateway (#362).
- [ ] Valio: the selling agent needs one fresh offer before the demo
      (`python -m agent.seller --apply --limit 1 --kitchen demo-kitchen` on the server).
