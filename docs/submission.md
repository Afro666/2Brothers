# Submission notes (#369)

Text for the Junction 2026 form, one section per track. Every claim names its source: a
path in this repo or a live URL. Checked against `main` on 2026-11-14. A line marked
**Not built** is not in the product today.

## Form text, ready to paste (#1775)

Copy each block as it is. Every sentence was checked on 2026-11-14 at about 21:50 UTC
against the code on `main` and against GET calls on the live site, and the changed
sentences again on 2026-11-15 at 00:59 UTC (#1969). The Nemotron evidence was updated on 15 November after the fresh selection holdout (#2000); the sources are under the blocks. Do not add these claims by hand, because they are not true:

- "Context.dev reads supplier price pages." It does not. Context.dev reads the food recall
  list, one manufacturer page, a producer register and brand data. The price list of
  another supplier is read by Nemotron from a photo (`agent/price_list.py`).
- "It compares your suppliers" as a claim about real suppliers. Valio Aimo is the one real
  supplier. The five other suppliers of the demo kitchen are demo suppliers, and their
  names say "(demo)" (`GET /api/v1/kitchens/demo-kitchen/suppliers`).
- "The order goes to Valio." No order reaches Valio (see the description).

**Name.** The project is **Kitchen Buyer** (the name on the site, `web/index.html:26`). The
team is **2BROTHERS**. Use these two names in every field; do not write "Trusted Kitchen
Buyer".

**Punchline** (one line)

```
Kitchen Buyer makes Valio Aimo readable for any purchasing agent: an agent looks up product, price and availability and gets a signed offer, and a person approves every order.
```

**Description** (three short paragraphs, about 90 words)

```
Kitchen Buyer, by team 2BROTHERS, is for professional kitchens that buy from a wholesaler such as Valio Aimo: any agent can look up product, price and availability and get a signed offer, and a person approves every order. A chef types one sentence and gets one order proposal.

Code sets every quantity and total. When the supplier has not confirmed some stock, the card says how much waits.

No order reaches Valio: its mock API has no order route. The gateway keeps the approved order with a signed receipt that says NOT_SENT.
```

**Try it in one minute** (paste after the description, or in the demo field)

```
Open https://kitchenbuyer.pl (no sign-in). Open "Request an order", type "1,000 litres of lactose-free milk by Monday" and press "Ask the agent". Open "To approve" and the new card, then "What Nemotron did" on that card. Then open "Tamper check" in the menu and press "Verify audit chain". If no card comes, open "Order history" and the newest 698 L lactose-free milk order (EUR 2,099.41) to see its "Signed receipt".
```

The line starts with the request, so it does not need a card that already waits (on 15 Nov
at 00:59 UTC no milk card waited). The fallback order exists: `GET .../orders` lists three
698 L lactose-free milk orders of EUR 2,099.41 with a receipt, the newest of 14 Nov 22:18
UTC. The two oldest (14 Nov 03:48 and 03:50 UTC) have no receipt, so the line says "newest".

**Also in the product** (add these where the form has room; each is one true sentence)

```
Any outside agent with a kitchen token can do the same over REST or MCP, and anyone can check a signed offer or receipt with one public key.
Our Buyer agent (NVIDIA Nemotron 3.5 Super VL) picks the products; it sets no quantity, no price and no total, and an agent token cannot approve.
The agent decides no order alone on the demo: auto-approve exists and is off, a kitchen must earn it (4 weeks and 20 human decisions, at most 10% of approved proposals edited), an approver sets its limit (at most EUR 2,000), and it never approves a line with unconfirmed stock.
A Telegram bot takes a typed or spoken order, sends a brief of what waits, and shows the order as one message per supplier; approval stays on the site.
A recall check flags a product on the shelf that may match an official food recall, and new proposals leave it out.
The home page shows an offer written by Valio's selling agent; the kitchen's own forecast sets the quantity, and a person approves it like any order.
Every step is in a hash-chained audit log in MongoDB Atlas, and the "Tamper check" page verifies the chain.
Valio Aimo is the only real supplier; the other suppliers in the demo kitchen are demo suppliers.
```

**Best Use of Nemotron** (the short explanation the form asks for)

```
Model: NVIDIA Nemotron 3.5 Super VL (nemotron-3.5-super-vl) on Verda's shared inference endpoint. We did not train or fine-tune it.

What it does: it is the Buyer. For each request, code searches the catalog and gets a live offer. Then one Nemotron call picks up to three products from that shortlist. Our small recorded runs measured that model call at about 0.3 seconds; this excludes gateway, catalog and database time. Code does every tool step after that: a fresh offer for the picked products, the check against the guards, and the request for a person's approval. The same model also reads photos (a menu, a shelf, a delivery note, a supplier's price list) and picks the substitute in the offer from Valio's selling agent.

Why this model: one hosted vision-language model serves semantic product selection, menu reading, shelf counting, delivery-note reading and the supplier-side substitute choice. It adds text/image interpretation to the deterministic purchasing engine; the plain parser remains an available fallback. We have not established superiority over the full parser in an end-to-end comparison.

Why it matters: a chef writes a sentence, not product codes. A wrong model answer cannot become a wrong order, because the model sets no quantity, no price and no total, it has no approve tool, and a person approves every order. Each proposal the Buyer agent made has a panel "What Nemotron did" that shows the model call and the code steps. The card can also show a short explanation that Nemotron writes from the decision record; code checks it against the facts, and an explanation that fails the check is not shown.

How we improved its outputs: we measured, then changed. On our development benchmark (30 synthetic requests, three repeats each, 90 replies) the pick was exactly the expected products in 27 of 90 replies at the start. With the live quote facts and the ranked prompt it was 54 of 90. With a code guard that keeps the model's first choice alone when confirmed stock covers the need, it is 69 of 90. This is a development set, not held-out evidence. A separate fresh 20-case synthetic shortlist holdout, frozen before its one-pass run on 15 November with no prompt tuning from the replies, scored 19/20 raw exact product sets and 20/20 using the existing guard on those same replies. Each case has three synthetic candidates in known policy families; this is not live-catalog, whole-Buyer or real-photo accuracy. Median model round trip was 0.25 s, not end-to-end latency. Real phone-photo evaluation remains pending. The model replies in a strict JSON schema, and a reply outside the schema is refused. Thinking is off for the pick, with one call and no retry. The prompt ranks the rules in a fixed order (product kind/alias, diet, arrival/confirmed coverage, saved removal preference, comparable price, prior orders). Code checks the reply after the model: a pick outside the shortlist is refused, and so is a reason with a number that is not in the data. If the model does not answer in time, a plain parser makes the proposal and the card says so.
```

**Best Use of MongoDB Atlas** (one sentence)

```
Every order, proposal, approval and audit entry is in MongoDB Atlas. Search, vectors, time series and the change stream sit in one place, so the Buyer, the live inbox and the log share one store: Atlas Search and Atlas Vector Search over Valio's catalog (17,546 product vectors), time-series collections for stock, deliveries and forecasts, change streams for the live inbox, and an insert-only, hash-chained audit log that the Trust page checks.
```

**Still to do by hand in the form**

- [ ] Demo link: `https://kitchenbuyer.pl`
- [ ] Video link: `https://youtu.be/7Wu0xuCiUHI` (if the video is uploaded again, paste the new link instead; open it once signed out to check it plays).
- [ ] Table number: read it from the table at the venue.
- [ ] Side challenges: tick two only, **Best Use of Nemotron** and **Best Use of MongoDB
      Atlas** (#1388). Leave Context.dev, Codex and the others unticked.
- [ ] Main challenge: Valio Aimo, Trusted Trade Agents.

**Sources for the blocks**

| Claim | Source |
|---|---|
| Any agent, REST or MCP, with a kitchen token | `/llms.txt` on the live site ("Token", "The flow: 5 steps") |
| An agent token cannot approve | `/llms.txt`: 403 `HUMAN_SESSION_REQUIRED` on approve and reject |
| Signed offer and receipt, one public key | `gateway/signing.py`, `/api/.well-known/jwks.json` (answers 200) |
| The receipt says `NOT_SENT` | The receipt of the EUR 2,099.41 order of 14 Nov 07:14 UTC in `GET /api/v1/kitchens/demo-kitchen/orders` |
| Partial stock gives options | A waiting 1,000 L milk proposal in `GET .../proposals`: 698 L confirmed, 302 L not confirmed, three options |
| One Nemotron call per Buyer request, tool steps by code | `agent/service.py:65` (default `single_pick`), `deploy/compose.yaml:86`, `agent/single_pick.py`; the `model_trace` of a live proposal: 1 model call, thinking off, every tool step `by: code` |
| A tool loop exists as an option, not as the live default | `NEMOTRON_BUYER_STRATEGY=loop` (`agent/service.py:66`) |
| A repeated request reuses the pick for ten minutes (the panel then shows no model call) | `agent/README.md` "One model pick per request" |
| Strict JSON schema, the ranked prompt, the checks after the model | `agent/single_pick.py:20-58`, `:121-147`, `:261` |
| Parser fallback, and the card says so | `agent/README.md` "One model pick per request", `web/src/components/purchasing/model-trace-panel.tsx:105` |
| Photo readers and the selling agent | `agent/menu_photo.py`, `agent/shelf_service.py`, `agent/receiving.py`, `agent/price_list.py`, `agent/seller.py`; a live offer with `made_by: nemotron-3.5-super-vl` in `GET .../supplier-offers` |
| Atlas features and the 17,546 vectors | `GET /api/v1/kitchens/demo-kitchen/atlas`; `GET .../audit/verify` answers `ok: true` |
| What Context.dev reads | `monitor/recalls.py`, `monitor/enrichment.py`, `monitor/labels.py`, `gateway/onboarding.py`, `gateway/brand_logos.py` |
| The name "Kitchen Buyer" | `web/index.html:26` (the page title) |
| The try-it line: "Request an order", "Ask the agent", "To approve", "What Nemotron did", "Tamper check", "Verify audit chain", "Order history", "Signed receipt" | `web/src/components/purchasing/app-shell.tsx:62-64`, `:72`, `web/src/components/purchasing/chef-request-box.tsx:169`, `web/src/components/purchasing/model-trace-panel.tsx:189`, `web/src/pages/trust.tsx:136`, `web/src/pages/order-detail.tsx:63`; "litres" is a unit the request reader knows (`gateway/parse.py:17`, `agent/service.py:37`); checked on 2026-11-15 at 00:59 UTC: a milk proposal in `GET .../proposals` has `model_trace.made_by: model` with 1 call, `GET .../audit/verify` answers `ok: true`, and `GET .../orders` has the 698 L order of 14 Nov 22:18 UTC with a receipt |
| The pick takes about 0.3 seconds | `model_trace` of the live milk proposal `17dfba54…` in `GET .../proposals` (15 Nov 00:59 UTC): `calls: 1`, `seconds: 0.314`, `thinking: false`; the benchmark's median model round trip is 0.281 s ("Buyer read context" below). This is the model call, not the whole request |
| 27, 54 and 69 of 90 | The table under "Buyer read context (#1605, 14 Nov)" in this file; `agent/benchmarks/pick-context-v1-report.json` |
| The pick's reason is not shown; the card's explanation is a separate, checked Nemotron text | `agent/single_pick.py:263` ("The reason is never stored or shown"); `agent/explanation_service.py:1`, `agent/explanation.py` (`checked_reply`), `web/src/components/purchasing/approval-card.tsx:232-233`; the live audit log has `proposal_explanation_ready` and `proposal_explanation_failed` entries (`GET .../audit`, 15 Nov) |
| Auto-approve: off, earned, limit | `gateway/autoapprove.py:23-27` (4 weeks, 20 decisions, 10% edit rate, EUR 2,000), `:93-94` (a higher limit is refused), `:28` (`STOCK_UNKNOWN`, `PARTIAL_STOCK` never); `GET .../auto-approve` on 15 Nov 00:59 UTC: `enabled: false`, `learning_done: false` |
| "What Nemotron did" only on a proposal the Buyer agent made | A rule-made proposal has `model_trace.made_by: rule` and `calls: 0` (a waiting proposal in `GET .../proposals`); its card says "No model ran" (`model-trace-panel.tsx:105-106`) |
| The card says how much waits for stock confirmation, beside the total | `web/src/components/purchasing/approval-card.tsx:632-638`: under the total of an option that holds such stock, "{quantity} {unit} waits for stock confirmation" (for the 1,000 L milk request with 698 L confirmed: "302 L waits for stock confirmation"); the line itself says "{supplier} must confirm" (`web/src/components/purchasing/proposal-lines.tsx:73`) |
| The Telegram bot: typed or spoken order, brief, one message per supplier, no approve | `bot/README.md` ("Message rules", "What a person can do"), `bot/app.py:169-170` (voice), `deploy/compose.yaml` (services `bot` and `stt`; removed on 2026-11-16, after the event, when the project closed) |
| The recall check | `web/src/components/purchasing/recall-panel.tsx`, `gateway/service.py` (`BLOCKED_BY_RECALL`), rubric row D |
| The offer from Valio's selling agent | `web/src/pages/home/offer.tsx:86`, `:110-111`, `gateway/supplier_offers.py:9-10`, rubric row E |

## What it is

- Kitchen Buyer: a purchasing agent that Valio Aimo can give to its kitchen customers.
- A chef asks in plain words. The Buyer agent (Nemotron 3.5 Super VL) finds the products.
- The gateway reads Valio's live price and availability API. A deterministic engine sets
  every quantity.
- A person approves every order: in the web, or from their own chat with a personal
  approval token. Agent tokens never approve.
- Every step is in a hash-chained audit log. Each offer and each order receipt is signed when
  the signing key is available; a signing failure never blocks an order.
- Any other agent can use the same gateway over MCP or REST with a kitchen token.

Team 2Brothers: Aron (gateway, engine), Tymon (web, store), Maciek (agent, env, signals).

Live site: <https://kitchenbuyer.pl>. Sign-in is off for judging: open it and use it.
For agents:
[`/llms.txt`](https://kitchenbuyer.pl/llms.txt),
[`/.well-known/agent-card.json`](https://kitchenbuyer.pl/.well-known/agent-card.json),
[`/api/.well-known/jwks.json`](https://kitchenbuyer.pl/api/.well-known/jwks.json),
[`/gateway/openapi.json`](https://kitchenbuyer.pl/gateway/openapi.json),
[`/api/docs`](https://kitchenbuyer.pl/api/docs).

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
may still approve those lines. The gateway records the order and sends nothing
(`supplier_outcome: NOT_SENT`); the supplier must still confirm that stock: the order lists the
supplier in `supplier_must_confirm` (`gateway/service.py:1262-1290`), and the card says
"Valio must confirm stock for: <products>" (`web/src/pages/live-approvals.tsx:116-118`,
`web/src/components/purchasing/approval-card.tsx:226`, `:551`). Auto-approve never places
unknown stock (#1221).

**Rubric** (our own criteria and weights; Valio published none). Each row says what a judge
can see on the live site in under 2 minutes.

| Criterion | What a judge sees, and where | Source |
|---|---|---|
| A. Working end-to-end demo (30%) | `/requests`: type `1,000 L lactose-free milk by Monday`, press "Ask the agent". The card opens in `/approvals` with live prices, each line's `why`, product names, and the total. Nemotron picks the products (the card's "What Nemotron did" shows one model call); the engine sizes the lines. When Valio confirms only part of the stock, the card has options: A, the confirmed litres now (the rest waits for Valio to confirm stock); B, the Buyer's full 1,000 L basket, part of it waiting for confirmation; C, a catalog alternative sized by the engine. Read each option's total off the card: stock and prices are live from Valio, so the options and their totals move. The one figure that came back each time on 14 Nov is option A at 698 L confirmed, EUR 2,099.41 incl VAT (five orders in `/orders`). "Approve", then "Yes, approve EUR ...". `/orders`: an approved order's page shows the "Signed receipt", for example the EUR 601.55 order of 14 Nov 13:32 UTC (the rehearsed 200 L milk request, not the 1,000 L one). No order reaches Valio: its challenge API has no order route, so the order and its receipt stay in our gateway. `/audit`: every step. | `docs/demo.md` (milk, "What was measured"), `gateway/README.md:100`, `web/src/pages/order-detail.tsx:58` |
| B. Matches what the buyer asked (20%) | `/approvals`: each line shows its English and Finnish name, the brand when the catalog has one, a picture and a `why` sentence. The engine sizes each line; the model picks products only. Change a quantity, "Remove" a line or "Add products": the total is quoted again live. A request for several products is one proposal: on `/requests`, try `20 kg washed potatoes and 8 kg carrots for Tuesday lunch`. On 14 Nov a request with these two vegetables and a fish line became two purchase orders, the fish from Baltic Catch Fish Wholesale (a demo supplier, stock unknown, so it must confirm) and the vegetables from Valio, with VAT per line (EUR 347.74 incl VAT on 14 Nov, for the three lines). Each product name opens the product's page: allergens, VAT and every supplier's price. By hand in a webshop this order is a search, a comparison of several products, a stock check and a basket: we estimate 5 to 10 minutes, and it depends on the restaurant and the person. With the agent it is one sentence, about 15 seconds, and two taps. | `gateway/product_names.py:1-6`, `engine/README.md`, `gateway/change.py`, `web/src/components/purchasing/approval-card.tsx:377`, `:462`, `:480`, #1435, #1343, #1474 |
| C. Autonomy and controls (20%) | `/approvals`: the confirm dialog says "You approve exactly EUR ... If the price or stock moves before it is placed, the gateway refuses it". A card with unknown stock says Valio must confirm it. `/settings/approve-chat`: in the open demo any visitor can make a short-lived approve/reject-only token for the demo kitchen (8 hours by default, at most 24). It belongs to the shared demo approver, not to one person; it never proposes, and every use is audited with via: personal_token. A token of your own needs a signed-in approver account. Auto-approve is off by default and must be earned (4 weeks, 20 human decisions, at most 10% edited, a limit up to EUR 2,000). | `approval-card.tsx:551`, `:643`, `web/src/pages/settings/approve-chat.tsx:156-162`, `gateway/app.py:629-643`, `gateway/permissions.py:38-44`, `gateway/approval_tokens.py:1`, `gateway/mcp_http.py:9`, `gateway/autoapprove.py:21-25`, `gateway/service.py:1262-1290` |
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

The scenarios run on frozen test data, not the live site. S01's EUR 1,459.67 is option B ex VAT on that data; the live 1,000 L request gives the figures in row A.

13 PASS

**Not built:**

- An order sent to Valio. Their challenge API has no order endpoint, so every order stays
  in our gateway and its receipt says `NOT_SENT` (`gateway/README.md:108`,
  `gateway/signing.py:33`).
- A mandate as a verifiable credential (named in `docs/plan.md:33`, not in the code).
- An approval token of your own in the open demo. A visitor can make a token there, but it
  belongs to the shared demo approver and every visitor can revoke it; a token that stands
  for one person needs a signed-in approver account (`gateway/app.py:629-643`,
  `web/src/pages/settings/approve-chat.tsx:156-162`).
- Known limit: a free request for butter, eggs or salmon still gives the wrong kind of
  product (clarified butter, scrambled egg mix, salmon cubes) (`docs/demo.md:193-194`).
- The last recorded conformance run on the server is 11 passed, 0 failed, 1 skipped
  (`docs/demo.md:338`). The code now has 13 checks (`gateway/conformance.py:193-205`); they
  were not re-run on the server for this text.

## NVIDIA: Best Use of Nemotron

**Model.** Nemotron 3.5 Super VL (`nemotron-3.5-super-vl`) on Verda's shared inference
endpoint (`agent/model.py:24`, `agent/model.py:25`). Nemotron is reached only through
Verda's endpoint: every call needs `VERDA_INFERENCE_KEY`, and the code has no second
provider and no fallback model (`agent/model.py:28-33`). We did not train or fine-tune it.

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
2. **Buy: the Buyer agent.** The deployed gateway sends free-text requests to the Buyer
   worker (`deploy/compose.yaml:48`, `agent/service.py`). Today one live request makes
   **one model call** (the default `NEMOTRON_BUYER_STRATEGY=single_pick`,
   `deploy/compose.yaml:86`, `agent/service.py:65`; #1208, merged in #1257).
   - **What the model decides:** which products. Code searches the catalog and gets an
     engine offer. Nemotron then picks up to three products from that numbered shortlist
     and gives a short reason for each (`agent/single_pick.py:20`). It gets no tool
     definitions. Code checks the reason and drops it: it is never stored or shown
     (`agent/single_pick.py:263`). The `why` a person reads on each line is the engine's
     (`gateway/service.py:290`).
   - **What code does:** every tool step. It searches, gets the offer, gets a fresh offer
     for the picked products, simulates it and requests approval
     (`agent/single_pick.py:201-291`). These steps go through the same audited MCP tools
     and the same guards as before: `search_products`, `get_offer`, `simulate_order` and
     `request_approval` (`agent/runner.py:18`, `gateway/mcp_server.py:126-162`).
   - **The same pick again** within ten minutes comes from a cache and makes no model
     call; the prices, the stock and the offer are read again every time
     (`store/buyer_picks.py:40`, `agent/README.md` "One model pick per request").
   - **The older tool loop** is still in the code (`NEMOTRON_BUYER_STRATEGY=loop`, and the
     CLI agent). There the model itself called the tools, from a list of seven: search,
     offer, simulate, request approval, place order, order status and audit log
     (`agent/runner.py:18`). It was about 4 model calls per request. It is not what the
     live site runs today.
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
   from a photo"): on the stored prepared test-photo run it filled five counts in 2.2 s, and the
   half hidden pack got "please count" and no number; a person saves
   (`gateway/stock_photo.py`, `agent/shelf_service.py`, `docs/demo.md` "Photo beat").
5. **Receive: a delivery-note photo** (#1198; #1231, #1314). Nemotron reads the note into
   a strict JSON schema (`agent/vision.py`, `agent/receiving.py`). Plain code compares it
   with the order and computes the claim: the EUR value of each short or missing line at
   the stored order's own price, and one total (`gateway/delivery_note.py:245`). The model
   gives no price. On the prepared note for the fixed demo order `DEMO-1198` (EUR 178.09)
   the claim is 3 cases, EUR 91.08 (`demo/tests/test_delivery_order.py:47`,
   `demo/tests/test_delivery_order.py:84`). An order that a person approves gets a signed
   receipt (`gateway/service.py:1511`; a signing failure is logged and never blocks the
   order). `DEMO-1198` is different: the demo seed placed it and no person approved it. Its
   page says "Placed by the demo seed" and it has no signed receipt (`gateway/seeded.py:1`,
   `web/src/pages/order-detail.tsx:100`; #1560, fixed in #1620).

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
endpoint's `usage` field (`agent/usage.py`, `agent/README.md` "Token meter"). Each number
below names the Buyer path it was measured on.

- **Today, one pick per request.** One Buyer request is one model call, or none when the
  pick comes from the cache. Measured on the live site on 2026-11-14, after #1316: three
  new requests made one call each, 2,224 prompt tokens and 355 completion tokens in total,
  0.345 to 0.441 model seconds per call; two cached requests made no call
  (`agent/README.md` "Live measurements, 14 November 2026"). That is a small sample on a
  healthy endpoint, not a promise for a busy one.
- **Before, the old tool loop** (the default until #1257). One Buyer request was about 4
  model calls, 44,700 prompt tokens and 290 completion tokens; before the loop's settings
  change it was 2,250 completion tokens, of which 1,720 reasoning. Measuring that loop on
  2026-11-14 took 184 Buyer requests: 832 model calls and 9.57 million tokens
  (`agent/README.md` "Legacy Buyer loop settings").

One photo read is one call of about 1,300 to 2,100 prompt tokens and 190 completion
tokens. The benchmark used about 130,000 tokens per kitchen week with thinking on, over 12
weeks (`env/README.md`, the "tokens/episode" column). The site shows the
kitchen's own count on the About page, from
`GET /v1/kitchens/{kitchen_id}/model-usage` (`gateway/model_usage.py`,
`store/agent_runs.py`).

**Why it matters.** A chef writes a sentence, not product codes. The model turns it into
catalog products, and the engine gives each line a reason a person can read. A wrong model answer cannot become a
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

The old Buyer tool loop got its own measurement, because there the model picked products
and tools and set no quantity (`agent/README.md` "Legacy Buyer loop settings", 24 requests
per variant, the worker on a laptop against the live model). The table below is
that old loop, not what the live site runs today. At first the loop ran on the endpoint
default (thinking on) with a 2,048 token reply budget: 5 of 346 model calls used the whole
budget on reasoning and returned no tool call, so the run stopped and started again. We
then set thinking off, 2,048 tokens, and a prompt that asks for one offer with the three
best products that can arrive (`agent/model.py:21-22`, `agent/runner.py`):

| Live loop | Finished | On the first attempt | Completion tokens per request | Median seconds |
|---|---|---|---|---|
| Old loop, first: thinking on, old prompt | 24 of 24 | 20 | 2,251 | 14.1 |
| Old loop, tuned: thinking off, one-offer prompt | 24 of 24 | 24 | 289 | 8.8 |

In the tuned loop the first offer had three products every time (before: 1 to 5), and
repeated runs of one request gave the same products much more often. So thinking is on
where the model decides numbers (the benchmark) and off where the engine does (the
product).

The next step took the tools away from the model (#1208, #1257). The live site now asks
Nemotron for one pick: one JSON call, thinking off, 512 output tokens, a 20-second limit
and no model retry (`agent/service.py:186-187`, `agent/single_pick.py:168`). In three live
requests of one size on 2026-11-14 the loop took 4 model calls and about 43,500 prompt
tokens per request; the single pick took 1 call and 741 to 742 prompt tokens
(`agent/README.md` "Live measurements, 14 November 2026", 3 requests per row). The
"Buyer read context" part below measures that pick.

These are two different experiments and token metrics. The video's almost-eight-times reduction is **completion tokens in the older loop**, 2,251 to 289 (about 7.8x). The deck's **prompt tokens per request** compare the loop with single pick, about 43,500 to 741-742 (about 58.6x), three live requests per row. Neither ratio is a universal cost or end-to-end latency improvement. The current slide 5 says 0.3 s for the **Buyer model call**, not the shelf read; the stored prepared shelf run took 2.2 s.

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

**Buyer read context (#1605, 14 Nov).** A new synthetic shortlist benchmark has 30
distinct requests in five families (stock, diet, price, prior orders and product fit),
three repeats per condition, interleaved on the same Nemotron endpoint. It is not the
old #1025 live request set and is an exploratory development set, not held-out evidence.
The fixture and all three iterations are in `agent/fixtures/pick-context-v1.json` and
`agent/benchmarks/pick-context-v1-report.json`.

| Read context / pipeline | Exact expected product sets | Same product set on all 3 repeats | Valid replies | Mean prompt tokens | Median model round trip |
|---|---|---|---|---|---|
| Previous compact rows | 27/90 | 26/30 cases | 89/90 | 346 | 0.242 s |
| Quote facts + ranked prompt, model output alone | 54/90 | 20/30 cases | 90/90 | 964 | 0.281 s |
| Same replies + exact-quote full-coverage guard | 69/90 | 30/30 cases | 90/90 | 964 | 0.281 s |

The guard keeps the model's first choice alone only when the quote proves confirmed
stock covers its rounded packs and it can arrive in time; partial-stock baskets keep
their complements. Its improvement is code, not a claim of better raw model stability.
The richer prompt costs more tokens and was slightly slower; these are model-call
timings, not end-to-end gateway timings or a guarantee during provider congestion.
In those development runs the history-family expected sets failed, so those results
provided no demonstrated benefit from the prior-order counts. The new two history
cases passing below is not a retrospective change to that result or a memory ablation. An initial draft rejected 32/90 enriched replies because
its claim validator omitted trusted pack/need numbers; the report retains that failure.
On a separate live-quote milk snapshot, both prompts retained the confirmed-stock
product in all three repeats; that snapshot had 51 L confirmed, not the older 698 L.
The frozen stock cases also cover the saved 698 L scenario. No order was placed.

### Fresh selection holdout (#2000, 15 November)

The fixture and runner were committed before calls; production prompts and guards
were unchanged. Twenty new synthetic requests each have three candidates in six
known policy families. One attempt each, no failures/retries. Exact product sets:
**19/20 raw**, **20/20 after the existing guard on the same replies**. All first
preferences, schemas and production numeric-claim reason checks passed (20/20).
The one raw miss added an unnecessary unknown-stock complement to confirmed-full
orange juice; code removed it. Median model round trip was **0.250 s**, with 25,869
prompt and 1,149 completion tokens across 20 calls. Nothing was proposed or ordered.

The engine-offer-only comparator scored 8/20 here and 6/30 on the unchanged earlier
development fixture, offline. It omits the full parser's semantic/diet/alias filters,
so these numbers establish no model-versus-parser superiority. The two datasets,
prompt versions and repeat counts differ: do not call 19/20 an improvement over
27/90. See `agent/benchmarks/pick-holdout-20-v1.md`, the per-case JSON report, and the
frozen `agent/fixtures/pick-holdout-20-v1.json` for hashes, settings and limitations.

**Real-photo evidence is still missing.** Prepared images are not genuine phone
photos. The stored shelf fixture has five COUNTED rows and an UNMATCHED Edam label.
The jury reported duplicate butter in the video run; that different run is not the
stored reply or an accuracy result. UNMATCHED means the label did not match the
kitchen's list, not proof that occlusion alone caused the failure. The current
pitch notes already say no match on the stock list. A person must review every
suggested count. #2000 stays open until five to ten real photos with independently
checked expected counts/text are evaluated once and the per-item errors reported.

## MongoDB Atlas

The database is MongoDB Atlas. `store/` is the only package that talks to it
(`store/README.md`, `docs/decisions.md`).

**See it live: the About page, "The data lives in MongoDB Atlas"** (#1383; #1398, #1401,
#1447). The card shows the live numbers from `GET /v1/kitchens/{kitchen_id}/atlas`
(`store/atlas.py:49`, `gateway/atlas_routes.py:3`, kept for 60 s,
`gateway/atlas_routes.py:20`; `web/src/components/purchasing/atlas-card.tsx`). A part that
cannot be read shows "unknown", never zero. The numbers below were read from that route
(`GET https://31-22-104-201.sslip.io/api/v1/kitchens/demo-kitchen/atlas`) on 14 Nov at
21:46 UTC. They grow while people use the site, so the card can show more than this
table: at about 15:45 UTC the same route gave 17,548 products, 1,491 audit entries and
216 MB.

| On the card | Live value, read on 14 Nov at 21:46 UTC |
|---|---|
| MongoDB version | 8.0.37 |
| Data and indexes | 221 MB |
| Products (documents in the `products` collection, `store/atlas.py:54`) | 17,563 |
| Product vectors | 17,546, model `voyage-4`, 1,024 dimensions (17 fewer than the product count) |
| Search indexes | `products_search` READY, `products_vector` READY |
| Time-series collections | forecasts 43,078, kitchen_stock 32,218, deliveries 13,221, covers 1,780, orders_history 1,050 |
| Audit entries (the hash chain) | 1,570 |
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
| Hash-chained audit log | Insert-only. Each row stores the hash of the row before. `verify_chain` finds a changed or missing row, and since #1882 a cut or rewritten end, against a head record kept beside the log. The head is in the same database and is not signed yet (#1886), so it catches an accident or a careless edit, not someone who can write to the database. | `store/audit.py:91`, `store/audit.py:129` |

Why it matters: an order must not be sent twice, money must not round, and a person must
be able to check the log for changes (within the limit named in the table above). The whole database, data and indexes, is
221 MB (the same route, read on 14 Nov at 21:46 UTC).

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
