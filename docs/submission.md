# Submission notes (#369)

Text for the Junction 2026 form, one section per track. Every claim names its source: a
path in this repo or a live URL. Checked against `main` on 2026-11-14. A line marked
**Not built** is not in the product today.

## What it is

- Trusted Kitchen Buyer: a purchasing agent that Valio Aimo can give to its kitchen customers.
- A chef asks in plain words. The Buyer agent (Nemotron 3.5 Super VL) finds the products.
- The gateway reads Valio's live price and availability API. A deterministic engine sets
  every quantity.
- A person approves every order: in the web, or from their own chat with a personal
  approval token. Agent tokens never approve.
- Every step is in a hash-chained audit log. Each offer and each order receipt is signed when
  the signing key is available; a signing failure never blocks an order.
- Any other agent can use the same gateway over MCP or REST with a kitchen token.

Team 2Brothers: Aron (gateway, engine), Tymon (web, store), Maciek (agent, env, signals).

Live site: <https://31-22-104-201.sslip.io>. Sign-in is off for judging: open it and use it.
For agents:
[`/llms.txt`](https://31-22-104-201.sslip.io/llms.txt),
[`/.well-known/agent-card.json`](https://31-22-104-201.sslip.io/.well-known/agent-card.json),
[`/api/.well-known/jwks.json`](https://31-22-104-201.sslip.io/api/.well-known/jwks.json),
[`/gateway/openapi.json`](https://31-22-104-201.sslip.io/gateway/openapi.json),
[`/api/docs`](https://31-22-104-201.sslip.io/api/docs).

## Main track: Valio Aimo, Trusted Trade Agents

**Core requirements**

1. **Product, price and availability lookup.** Search runs over Valio's 17,546 catalog
   products in MongoDB Atlas. Price and stock come live from Valio's challenge API: each
   signed offer names its source, "Valio Aimo price and availability API, read at iat"
   (`gateway/signing.py:106`). The Catalog page searches the live gateway; a failed call
   is an error, never sample rows (#1216, #1172, #1535, `web/src/api/http-catalog.ts:184-210`).
   Each product shows a picture: a kind icon from its name, or the brand logo when
   Context.dev knows the brand. No product photo is copied from the web (#1246, #1247,
   #1252, #1395).
2. **Inquiry to order on fixed prices.** A request becomes a proposal with a 15-minute
   signed offer snapshot. One request may name several products; it becomes one proposal
   (#1474). A person can change the proposal before approving: set a quantity, remove a
   line, add a product. Each change gets a fresh live quote and a new total (#1200, #1343).
   A person approves the exact total. The order is then stored in our gateway, with a signed
   receipt when signing works (`gateway/service.py:1359-1372`). Valio's challenge API has no
   order endpoint, so no order reaches Valio.
3. **Permissions and human approval.** Agent and kitchen tokens never approve. Over MCP
   they do not even see the approve, reject or cancel tools. A person approves in the web
   or from their own chat with a personal approval token: approve and reject only, never
   propose, 8 hours by default, at most 24; every approve and reject made with it is
   audited, with the token id (`gateway/approval_tokens.py:3-6`, `:21`, #1243, #1275, #1336).
   Approval needs the exact total the person saw. A moved price refuses the old yes.

**Unconfirmed stock.** Valio's API answers 999999 or more when stock is unknown. A person
may still approve those lines. The order is sent and waits for the supplier: it lists the
supplier in `supplier_must_confirm` (`gateway/service.py:1262-1290`), and the card says
"Valio must confirm stock for: <products>" (`web/src/pages/live-approvals.tsx:116-118`,
`web/src/components/purchasing/approval-card.tsx:226`, `:551`). Auto-approve never places
unknown stock (#1221).

**Rubric** (our own criteria and weights; Valio published none). Each row says what a judge
can see on the live site in under 2 minutes.

| Criterion | What a judge sees, and where | Source |
|---|---|---|
| A. Working end-to-end demo (30%) | `/requests`: type `1,000 L lactose-free milk by Monday`, press "Ask the agent". The card opens in `/approvals` with live prices, each line's `why`, product names, and the total. Option A orders the confirmed stock now. "Approve", then "Yes, approve EUR ...". `/orders`: open the EUR 601.55 milk order of 14 Nov 13:32 UTC; its page shows the "Signed receipt". `/audit`: every step. | `docs/demo.md` (milk, "What was measured"), `gateway/README.md:100`, `web/src/pages/order-detail.tsx:58` |
| B. Matches what the buyer asked (20%) | `/approvals`: each line shows its English and Finnish name, the brand when the catalog has one, a picture and a `why` sentence. The engine sizes each line; the model picks products only. Change a quantity, "Remove" a line or "Add products": the total is quoted again live. A request for several products is one proposal. By hand in a webshop this order is a search, a comparison of several products, a stock check and a basket: we estimate 5 to 10 minutes, and it depends on the restaurant and the person. With the agent it is one sentence, about 15 seconds, and two taps. | `gateway/product_names.py:1-6`, `engine/README.md`, `gateway/change.py`, `web/src/components/purchasing/approval-card.tsx:377`, `:462`, `:480`, #1435, #1343, #1474 |
| C. Autonomy and controls (20%) | `/approvals`: the confirm dialog says "You approve exactly EUR ... If the price or stock moves before it is placed, the gateway refuses it". A card with unknown stock says Valio must confirm it. `/settings/approve-chat`: in the open demo any tester can make a short-lived approve/reject-only token for the demo kitchen; it never proposes, and every use is audited with via: personal_token. Auto-approve is off by default and must be earned (4 weeks, 20 human decisions, at most 10% edited, a limit up to EUR 2,000). | `approval-card.tsx:551`, `:643`, `web/src/pages/settings/approve-chat.tsx:145-151`, `gateway/approval_tokens.py:1`, `gateway/mcp_http.py:9`, `gateway/autoapprove.py:21-25`, `gateway/service.py:1262-1290` |
| D. Robustness to exceptions (15%) | `/approvals`: the recall panel flags the coffee on the shelf (3.253 kg) as a possible match to a Finnish Food Authority recall (only some batch dates); new proposals leave it out. `/requests`: `15 kg peanut butter` is refused in gateway code before the Buyer agent runs (#974). 13 golden scenarios, all PASS (table below). | `gateway/service.py:355`, `:428` (`BLOCKED_BY_RECALL`), `docs/demo.md` "Recall beat", `docs/decisions.md` (#974), `gateway/scenarios.py` |
| E. Openness and path to production (15%) | `/llms.txt`, `/.well-known/agent-card.json`, `/api/.well-known/jwks.json`, `/gateway/openapi.json` all answer. Home (`/`): the tile "Offer from Valio Aimo", written by Valio's selling agent; the supplier sets no price: the quantity is the kitchen's own forecast demand, and the gateway prices it. `/trust`: "Verify audit chain". An outside agent is refused: `/llms.txt` says agent tokens get 403 `HUMAN_SESSION_REQUIRED` on approve, and `python -m demo.second_agent` shows it (needs a local run; it creates one waiting proposal). | `gateway/discovery.py`, `gateway/signing.py:99`, `:118`, `gateway/supplier_offers.py:9-10`, `web/src/pages/home/offer.tsx:85`, `web/src/pages/trust.tsx:126`, `demo/second_agent.py`, `gateway/conformance.py:204-205` |

**Optional features**

- Sustainability and delivery reliability: each proposal line carries
  `carbon_kg_co2e_per_kg`, and `reliability` where Valio's data has it
  (`gateway/service.py:261`).
- Substitution and exceptions: up to three engine-priced substitute baskets, each needs the
  chef's approval (`agent/substitutes.py:122-135`). Partial fill: order the confirmed stock
  now, hold the rest (`engine/partial.py`, `gateway/options.py`). On the live site the
  1,000 L milk request shows option A, "Order the confirmed ... L now"; a person chooses it
  and approves its exact total (`docs/demo.md`).
- Proactive selling agent: Valio's own agent reads the predicted shortages of the kitchens
  that share their forecast. It offers a substitute that can arrive. Live on Home now: Rosamunda
  washed potato in place of washed potato, predicted short on 16 Nov, made by
  `nemotron-3.5-super-vl` (`GET /api/v1/kitchens/demo-kitchen/supplier-offers`, 14 Nov). A
  person turns the offer into a normal proposal (`agent/seller.py`,
  `gateway/supplier_offers.py`).
- Recall check: "Check recalls now" on `/approvals` reads the Finnish Food Authority list
  through Context.dev (102 notices listed, last live check 14 Nov 12:35 UTC). A match blocks
  the product on every proposal (`web/src/components/purchasing/recall-panel.tsx:207`,
  `gateway/service.py:355`, `GET /api/v1/kitchens/demo-kitchen/recalls`).
- Trust protocol: each offer and each order receipt is a JWS (EdDSA) when the signing key is
  available, checkable with the one public key at `/api/.well-known/jwks.json`. The receipt
  names the offer hash, the exact total, the lines, the approver, and which lines Valio must
  still confirm. It always says `supplier_outcome: NOT_SENT` (`gateway/signing.py:33`,
  `:118`, `:132`).
- Traceability: insert-only audit log, each line hashed with the one before
  (`store/audit.py:96`). `/trust` checks the chain.

**Golden scenarios.** Output of `python -m gateway.scenarios --markdown` on commit 6aa6756,
2026-11-14 16:11 UTC:

| Case | What | Layer | Result | Detail |
|---|---|---|---|---|
| S01 | Milk: split order, passed cut-off, unknown stock | gateway HTTP | **PASS** | lines = [('462775', '51'), ('463335', '949')]; total ex VAT (option B) = 1459.67 |
| S02 | Partial stock, good-better-best | engine | **PASS** | lines = [('465138', '16')]; total = 1028.32 |
| S03 | Allergen-safe substitute for a school | gateway HTTP | **PASS** | lines = [('468465', '60')]; total ex VAT = 70.20 |
| S04 | Missing allergen data is not allergen-free | catalog (store.products) | **PASS** | 125 g allergen data known = False; 125 g says no allergens = False |
| S05 | Above the budget warning (event order) | engine | **PASS** | lines = [('461423', '120')]; total = 2391.60 |
| S06 | Just under free delivery: pad with wanted lines | engine | **PASS** | add = [('469549', '30')]; total = 301.40 |
| S07 | Price moved between quote and approval | gateway HTTP | **PASS** | old yes is refused = (409, 'TOTAL_MISMATCH'); orders placed on the old yes = 0 |
| S08 | Standing-order drift | engine | **PASS** | this week qty = 40; proposed standing order = 140 |
| S09 | Stock count missing: unknown sorts with urgent | engine | **PASS** | draft qty (sized as if empty) = 48; urgency top = True |
| S10 | Demand hidden by a stock-out | engine | **PASS** | adjusted forecast L/week = 54.0; qty = 54 |
| S11 | Inbound is not an emergency; the cover ceiling | engine | **PASS** | order now = 0; max within ceiling = 34 |
| S12 | Bad pack data (10 kg carrot sack) | engine | **PASS** | lines = [('460708', '5')]; total = 55.90 |
| S13 | Duplicate send (idempotency) | gateway HTTP | **PASS** | replay with the same key returns the stored order = True; orders stored = 1 |

13 PASS

**Not built:**

- An order sent to Valio. Their challenge API has no order endpoint, so every order stays
  in our gateway and its receipt says `NOT_SENT` (`gateway/README.md:108`,
  `gateway/signing.py:33`).
- A mandate as a verifiable credential (named in `docs/plan.md:33`, not in the code).
- A personal approval token from the open demo: it needs a signed-in approver account
  (`web/src/pages/settings/approve-chat.tsx:145-151`).
- The last recorded conformance run on the server is 11 passed, 0 failed, 1 skipped
  (`docs/demo.md:338`). The code now has 13 checks (`gateway/conformance.py:193-205`); they
  were not re-run on the server for this text.

## NVIDIA: Best Use of Nemotron

**Model.** Nemotron 3.5 Super VL (`nemotron-3.5-super-vl`) on Verda's shared inference
endpoint (`agent/model.py:43`, `agent/model.py:54`). We did not train or fine-tune it.

**What it does: five jobs in one buying loop.** One model plans, buys, sells, counts and
receives. In every job it reads or chooses, and plain code sets every number. It never
sets a quantity, a price or a total, and it has no approve tool.

1. **Plan: a menu photo** (#1136; #1140, #1154, #1160, #1217). The chef uploads next
   week's menu on the Planner page. Nemotron reads the dishes and the printed covers; code
   matches each dish to a kitchen recipe and the engine sizes the ingredients. The result
   is a normal proposal that waits for approval (`gateway/menu_photo.py:81`,
   `agent/menu_photo.py`). Live on 2026-11-14 it read `demo/menu-photo.png` in 1,893 ms
   end to end: five dishes matched, with their covers 120, 100, 110, 90 and 100 (comment
   on #1136).
2. **Buy: the Buyer agent.** It reads the chef's request and calls seven MCP tools:
   search, offer, simulate, request approval, place order, order status and audit log
   (`gateway/mcp_server.py:83`, `agent/runner.py`). It chooses the products and the next
   step. The deployed gateway sends free-text requests to it (`deploy/compose.yaml:41`,
   `agent/service.py`).
   - **Several products in one sentence** (#1375; #1437, #1474). "20 L oat drink, 5 kg
     butter and 40 rolls for Monday" becomes one proposal. Nemotron splits the text into
     needs (`agent/split.py`). Plain code then checks the split: one need per quantity in
     the text, each quantity read from the person's words, none added or changed
     (`gateway/split.py:149`). A split that fails the check is refused with 422
     `CANNOT_READ_REQUEST`; with no model answer, plain code cuts the text before each
     quantity (`gateway/app.py:380`, `gateway/split.py:125`). A need that cannot be ordered is
     listed with its reason, and the others are proposed (`gateway/service.py:609`).
   - **Meaning search when words find nothing** (#1384; #1407, #1443). When the Buyer's
     search words find no product (a typo, a Finnish phrase), the search tool runs Atlas
     Vector Search once, with the same allergen filters. The answer says
     `search: "meaning-fallback"`, and the proposal says "found by meaning (Atlas Vector
     Search) after the word search found nothing" (`gateway/service.py:1386`,
     `agent/runner.py:134`). It never runs for a refused need.
3. **Sell: Valio's selling agent** (#374). A second role, on the supplier's side
   (`agent/seller.py`). Code reads the shortage view and builds a shortlist of at most five
   substitutes (`agent/seller.py:14`); the model picks one and writes the reason; a pick
   outside the shortlist means no offer. The gateway takes no price and no quantity from it
   (`gateway/supplier_offers.py`). Live on 2026-11-14 it offered the demo kitchen
   Rosamunda washed potato in place of washed potato that is predicted short on 16 Nov; a
   person made a proposal from the tile, and that proposal waits for approval like any
   other (`docs/demo.md` "Selling-agent beat").
4. **Count: a shelf photo** (#373). The shelf reader is live on the Stock page ("Count
   from a photo"): on a prepared test photo it filled five counts in about 2 s, and the
   half hidden pack got "please count" and no number; a person saves
   (`gateway/stock_photo.py`, `agent/shelf_service.py`, `docs/demo.md` "Photo beat").
5. **Receive: a delivery-note photo** (#1198; #1231, #1314). Nemotron reads the note into
   a strict JSON schema (`agent/vision.py`, `agent/receiving.py`). Plain code compares it
   with the order and computes the claim: the EUR value of each short or missing line at
   the stored order's own price, and one total (`gateway/delivery_note.py:245`). The model
   gives no price. On the prepared note for the fixed demo order `DEMO-1198` (EUR 178.09)
   the claim is 3 cases, EUR 91.08 (`demo/tests/test_delivery_order.py:47`,
   `demo/tests/test_delivery_order.py:84`).

**See what it did: the "What Nemotron did" panel** (#1197; #1228, #1279). Each Buyer
proposal and each supplier offer has a folded panel. Folded, it shows one line: model
calls, seconds and thinking on or off. Unfolded, it lists the steps, each marked Model or
Code, and ends with "Quantities and prices: the engine. Approval: you."
(`web/src/components/purchasing/model-trace-panel.tsx`). The trace holds counts and codes
only: never a key, the system prompt, model text, a price or a quantity
(`gateway/model_trace.py:1`). A parser answer says the parser answered, and a rule pick
says "Picked by rule. No model ran."

**The 90-second NVIDIA demo** (#1249). `docs/demo.md` "NVIDIA demo" runs the five jobs
above in 90 seconds, with an honest fallback for each beat when the model does not answer.
`python -m demo.record_demo --story nvidia` records it as a fallback video; it never
approves, never accepts the offer and never saves a count (`demo/record_demo.py:6`).

**Embeddings are not Nemotron.** We tried to make the product vectors with Nemotron
(#1199). Verda serves no embedding model: the Nemotron container answers 404 on
`/embeddings` and lists one chat model, and Verda's docs say embeddings return 404 (comment
on #1199). So the vectors for Atlas Vector Search are MongoDB's `voyage-4`.

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

**It learns from the kitchen, without fine-tuning.** We have only API access to Nemotron,
so nothing is trained. The tool learns from the reasons people give when they change a
plan proposal: *too much*, *too little*, *still in stock*, *menu changed*.

- **Plain code computes the facts:**
  - a correction ratio per product, measured against the engine's unlearned forecast
  - products the kitchen keeps removing
  - suppliers that deliver late or short

  See `engine/learning.py` and `GET /v1/kitchens/{k}/learned`.
- **Nemotron gets them as a kitchen memory in its prompt** (`agent/memory.py`):
  - in the proposal explanation, a learned line becomes one fixed sentence it must copy
  - in the Buyer's pick, the facts help it choose between products, never a quantity

  Every number it repeats is checked against its fact.
- **Visible and reversible:** a learned quantity shows on the plan line with its evidence,
  is audited, is never auto-approved, and an approver switches it off with one call.

Measured in Kitchen Week (`env/README.md`, "Learning from the kitchen's changes"; held-out
seeds 4–5, all four kitchen types, a synthetic chef with hidden habits). The table shows
weeks 3–4 of 4.

| Nemotron Buyer | Chef corrections a week | With a reason | Score | Habit stock-out days |
|---|---:|---:|---:|---:|
| without the kitchen memory | 9.94 | 7.37 | 2,812 | 0.62 |
| **with the kitchen memory** | **5.88 (−41%)** | **3.25 (−56%)** | 2,843 | 0.69 |

So with what the kitchen taught the tool, Nemotron's orders need about half as many human
corrections, with score level and no rise in stock-outs beyond noise. The memory costs
about 7% more tokens (1.22M tokens for the whole run). An earlier round (#365) showed the
opposite for rules Nemotron wrote about itself, which made it worse. So the design gives
it computed facts, not its own rules. The chef is synthetic and each cell is 8
kitchen-weeks; the README states both.

**Not built:** fine-tuning. The gate decided no-go: no GPU budget and no validated
recipe, so we claim no adapter gain (`docs/fine-tuning-gate.md`). Nemotron embeddings:
Verda serves no embedding model (#1199). A test of the photo readers on real phone photos:
the shelf, menu and delivery-note photos are prepared test photos (`docs/demo.md` "NVIDIA
demo"). The benchmark has 3 seeds per kitchen type, so read the "all" rows only.

## MongoDB Atlas

The database is MongoDB Atlas. `store/` is the only package that talks to it
(`store/README.md`, `docs/decisions.md`).

**See it live: the About page, "The data lives in MongoDB Atlas"** (#1383; #1398, #1401,
#1447). The card shows the live numbers from `GET /v1/kitchens/{kitchen_id}/atlas`
(`store/atlas.py:49`, `gateway/atlas_routes.py:3`, kept for 60 s,
`gateway/atlas_routes.py:20`; `web/src/components/purchasing/atlas-card.tsx`). A part that
cannot be read shows "unknown", never zero. Read from that route on 2026-11-14 at about
15:45 UTC:

| On the card | Live value |
|---|---|
| MongoDB version | 8.0.37 |
| Data and indexes | 216 MB |
| Products | 17,548 |
| Product vectors | 17,546, model `voyage-4`, 1,024 dimensions |
| Search indexes | `products_search` READY, `products_vector` READY |
| Time-series collections | forecasts 43,078, kitchen_stock 32,218, deliveries 13,221, covers 1,780, orders_history 1,050 |
| Audit entries (the hash chain) | 1,491 |
| Change streams | proposals, approvals, audit_log |

Under the numbers is the measured comparison of words against hybrid search
(`$rankFusion` of Atlas Search and Atlas Vector Search) on 10 queries, top 8 each: better
on 6, equal on 2, slightly worse on 2. These are written-down results, not computed at
page load; the file's `source` field says they were measured on the server on 2026-11-14
at about 07:18 UTC (`web/src/data/atlas-search-comparison.json`, #1080).

**Search by meaning on the Catalog page** (#1382; #1406, #1448). A switch "Search by
meaning (Atlas Vector Search)" runs the hybrid search for that one request
(`web/src/pages/catalog.tsx:235`, `gateway/catalog_search.py:71`). Each row says how it
was found: `matched_by` is `words`, `meaning` or `both` (`store/search.py:295`), and the
page marks the row "By meaning" or "By words and meaning"
(`web/src/pages/catalog.tsx:114`). When the meaning search cannot run, the page says so
and shows the word matches (`web/src/pages/catalog.tsx:316`).

**Hybrid stays off for the Buyer on stage** (#1127). `SEARCH_HYBRID` is not on, so the
rehearsed baskets stay as they are (`docs/decisions.md`, 2026-11-14 11:55). The Buyer
searches by words, and by meaning only when the words find nothing (#1384, below). The
Catalog switch and the Buyer's shortlist are separate: the shortlist ignores `mode`
(`docs/decisions.md`, 2026-11-14 ~15:00, #1382).

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
be able to check that nobody changed the log. The whole database, data and indexes, is
216 MB (the About card, read at about 15:45 UTC on 2026-11-14).

**Atlas Vector Search.** The index `products_vector` (1,024 dimensions, cosine) and the
hybrid search with `$rankFusion` are on `main` (`store/search.py`, `store/embeddings.py`,
`store/vector_index.json`). The vectors come from MongoDB's own embedding API (model
`voyage-4`); they are computed once and travel as a file (`python -m store.embeddings
--export-from ... --out ...`, then `--import-from`). The gateway uses hybrid search only
with `SEARCH_HYBRID=true` and falls back to the text search on any failure; the tool
answer says which one ran (`gateway/catalog_search.py`). It is off by default.
The Buyer's search uses Atlas Vector Search on its own when the words find nothing, with
the same hard filters, and says `search: "meaning-fallback"` (`gateway/catalog_search.py:101`
`meaning`, `gateway/service.py:1386`, #1384).
The `$vectorSearch` pre-filter applies the same allergen group rule as the text search: an
excluded allergen also excludes the allergens of its group, before any ranking
(`store/search.py:192`, `store/search.py:61`; #1481, PR #1485). A similar meaning never
overrides an allergen filter.
The vectors are `voyage-4` and not Nemotron, because Verda serves no embedding model
(comment on #1199).

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

**How the data drives the core flow.** The monitor matches a recall notice to what the
kitchen has: its counted stock, its recipes and the lines of its open proposals
(`store/recalls.py` `context`). A recalled product on the shelf gives an alert that says
"in stock: 3.253 KG", also when no order holds it, and every later request leaves that
product out with `BLOCKED_BY_RECALL`. An exact or possible match on an open proposal holds
the proposal. The gateway then refuses
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
- [ ] Context.dev: the demo kitchen has the recalled coffee 461332 in stock, so "Check
      recalls now" gives the alert with no seed (`docs/demo.md`, "Recall beat").
      `python -m demo.recall_demo` adds a held proposal only while Valio takes orders for it.
- [ ] MongoDB: import the product vectors on the server and decide on `SEARCH_HYBRID`
      (#366). Until then the form says "vector search is built and off by default".
- [ ] Codex: Maciek's three prompts, time estimates and the 90-second recording (#360).
- [ ] Nemotron: the improvement round on the benchmark (#365). Store a delivery-note result
      through the gateway (#362).
- [ ] Valio: the selling agent needs one fresh offer before the demo
      (`python -m agent.seller --apply --limit 1 --kitchen demo-kitchen` on the server).
