# Demo script: three minutes

Status: story A, chosen by Aron on 2026-11-14 at 09:55 Helsinki. It replaces the milk
request as the main demo. Every beat below ran on the live site on 14 Nov.
Owner: Aron (presents). Site: `https://31-22-104-201.sslip.io`.

Why this story: it shows the parts nobody else has (Valio's own agent, a live recall read,
a refusal, an outside agent), and **no beat needs the Nemotron model at demo time**. The
model makes the offer before the demo, and the seller has a `--no-model` fallback. On
14 Nov at 09:45 Helsinki the model endpoint did not answer for a while; this story still works.

## Before you go on stage

1. **An open offer on Home.** The tile "Offer from Valio Aimo" needs an open offer. An
   accepted or declined offer is final, so after a rehearsal make a new one. On the server:

   ```
   cd /opt/2brothers
   docker compose --env-file .env -f deploy/compose.yaml run --rm -T --no-deps gateway python -m agent.seller --dry-run --limit 1 --kitchen demo-kitchen --days 14
   docker compose --env-file .env -f deploy/compose.yaml run --rm -T --no-deps gateway python -m agent.seller --apply --limit 1 --kitchen demo-kitchen --days 14
   ```

   Read the dry-run line first: a sensible substitute (same kind of food), `made_by`
   `nemotron-3.5-super-vl`. If the model does not answer, add `--no-model` (a rule picks,
   `made_by: rule`); then do not say "Nemotron picked it" on stage. The open offer on
   14 Nov: flounder fillet in place of salmon fillet, for Fri 20 Nov, 12.226 kg.
2. **Clear the inbox.** On the server: `python -m demo.clear_inbox` lists the waiting
   proposals, `python -m demo.clear_inbox --apply` removes them (not a reject, so it is
   not a person's decision). Then the card made from the offer is the only one.
3. **No deploys while you present.** There is no deploy hold (Aron's choice). A merge
   restarts the site for some seconds: before you start, look at GitHub Actions; if a
   deploy runs, wait for it.
4. **Open the tabs:** `/` (Home) on the phone, `/approvals`, `/requests`, `/demand`, and a
   terminal in the repo for beat 5.
5. **The recall alert is stored.** Aron pressed "Check recalls now" on 14 Nov at 09:31: a
   live scrape (102 notices), the recalled coffee 461332 in stock (3.253 kg) and in three
   recipes. The panel shows it already; pressing again reads the list again (about 30 s).
6. **Make the outside agent's token before you start** if sign-in is on (it is off for
   judging): Settings, API & MCP tokens. With sign-in off, `--make-token` makes one.
7. **Fallback video** open in a player, paused at 0:00 (see "If something fails").

## The script (story A: Valio sees it first)

| Time | Beat | What you do | What you say | Criterion |
|---|---|---|---|---|
| 0:00 | 1. Valio sees it first | Home on the phone. Point at the tile "Offer from Valio Aimo": the offered product, "in place of ..., which is predicted short on ...", the amount "from your own forecast", the sentence "written by Valio's selling agent (Nemotron 3.5 Super VL)". | "This kitchen shares its forecast with Valio. Valio's own agent, Nemotron, saw that salmon fillet will run short on Friday, and offers flounder fillet before anyone orders. The supplier sends no price and no quantity: the amount is the kitchen's own forecast, and the price comes live from Valio when we ask." | B, E, bonus |
| 0:30 | 2. A person decides | Press "Make a proposal". The inbox opens with the new card: products, the "why" of each line, the total, what to check. Press "Approve", then "Yes, approve EUR ...". | "A suggestion never becomes an order by itself. It is a normal proposal now, sized by our engine, and it waits for a person. The agent has no approve tool. I approve the exact total I see: if the price moves, this yes is refused." | A, C |
| 1:00 | 3. Proof | Order history, the new order: the block "Signed receipt" (approver, time, total). | "The gateway signs every offer and every order with one key. Anyone can check this receipt with the public key; change one number and the check fails. It also says plainly that Valio's test API has no order endpoint, so nothing was sent." | C, E |
| 1:20 | 4. A recall, live | `/approvals`, the recall panel. Press "Check recalls now" (about 30 s; talk while it runs). | "Context.dev just read the Finnish Food Authority recall list, 102 notices. One matches: this coffee is recalled, and it is on our shelf, 3.2 kilos, and in three of our recipes. No order holds it, and new orders leave it out. The kitchen knows before anyone orders it again." | D, Context.dev |
| 2:00 | 5. A rule the agent cannot break | `/requests`: type `15 kg peanut butter`, press "Ask the agent". | "This kitchen excludes peanuts. The request is refused in under a second, before any model runs, and nothing else is swapped in. An agent that 'helps' with plain butter would be worse than no agent." | C, D |
| 2:20 | 6. Any agent | Terminal: `python -m demo.second_agent --make-token`. It prints ten lines. | "This is not our agent's door. An outside client reads our public agent card, connects over MCP, searches, gets an offer and asks for approval. Then it tries to approve its own proposal: 403. Only a person approves." | E |
| 2:45 | 7. Close | `/demand`: the Valio planner view. | "Valio sees the demand of every kitchen that agreed to share, and which lines will be short. That is how its agent knew about the salmon. Open interface, a person signs, and every step is in a hash-chained log." | bonus |

**Do not type** butter, eggs or salmon as a free request: those three still give the wrong
kind of product (clarified butter, scrambled egg mix, salmon cubes). Cheese, cream, oat
drink, chicken breast and lactose-free milk give the right kind.

**The sponsor's own example** (`1,000 L lactose-free milk by Monday`) still works end to
end and is the answer if a judge asks for it: Option A "order the confirmed 698 L now, 302 L
held", "Choose option A", approve EUR 2,099.41. It needs the Nemotron Buyer (or the parser
fallback, which gives the same honest split).

## Recall beat: the recalled coffee is on our shelf (#358)

One-shot on the live kitchen: the first check records the alert, and it stays. Do not
press the button in rehearsal there.

| Step | What you do | What the judge sees | What you say |
|---|---|---|---|
| 1 | Open `/stock`. Point at Kulta Katriina coffee. | The coffee 461332 with 3.253 kg on hand. | "This kitchen has this coffee on the shelf." |
| 2 | Open `/approvals`. Press "Check recalls now". Wait (the live scrape took 30 s on 14 Nov; a slow answer falls back to the recording and the panel says so). | The recall panel: "Kulta Katriina ... is recalled", the Food Authority notice "Suodatinkahvissa vierasesineriski" of 6 March 2026 with its link, "In stock: 3.253 KG", and "No open order holds it. New orders leave it out." | "Context.dev just read the Finnish Food Authority recall list. The recalled coffee is on our shelf; the kitchen knows before anyone orders it again." |
| 3 | Optional: on `/requests` ask for `5 kg Kulta Katriina filter coffee`. | The coffee is left out with the reason `BLOCKED_BY_RECALL`. | "And the agent cannot order it. A person checks the packs first." |

The alert needs no open proposal: the check matches the notices to the kitchen's stock and
recipes too (`store/recalls.py` `context`). The hold of an open proposal and its replacement
basket (`python -m demo.recall_demo`) need a product whose ordering is open at Valio; for the
coffee it closed on 12 Nov, so that part is not shown this weekend.

## Photo beat: Nemotron VL counts a shelf (#373)

Live since 2026-11-14. This is the beat that shows the vision half of Nemotron 3.5 Super VL
on the screen. It takes about 20 seconds. Put it after beat 3, or use it in place of beat 4.

**Which photo.** Use `agent/fixtures/shelf/demo-shelf.png`. It is a synthetic photo
(`agent/fixtures/shelf/make_demo_shelf.py`): six products of the demo kitchen's stock list,
with their catalog names printed on the packs. Copy it to the laptop or the phone before
the demo. Do not use `agent/fixtures/shelf/shelf.png` on the live site: it shows milk the
demo kitchen does not stock, so all five rows come back "please count" (measured, see below).
A real phone photo of real packs was **not tested**. The label match is plain word overlap
with the English catalog name (`agent/shelf.py`), so a Finnish label will mostly be
"please count". That is safe, but it is not the demo. Say "a prepared test photo".

**What you do.**

1. Open `/stock` (menu: Kitchen, tab "Stock count").
2. In "Count from a photo" press "Choose a file" and pick `demo-shelf.png`. On a phone,
   "Count from a photo" opens the camera; "Choose a file" picks a stored photo.
3. After about 3 seconds the panel says what Nemotron read, and five Count fields are
   filled. Each one says "read from the photo by Nemotron 3.5 Super VL, check and save".
4. Point at the last row: "Valio Edam 17 %", "please count", no number. The pack is half
   hidden.
5. Press "Save count" only if you want the demo kitchen's stock to change (see the warning).

**What you say.** "Counting stock is the slowest job in a kitchen. Here Nemotron reads the
shelf. It counted six cartons, five, four, three tubs and four packs. Code turns packs into
litres and kilos: three tubs of 2 kg are 6 kg. The pack it could not see well has no
number: unknown is never zero and never a guess. Nothing is saved until a person presses
Save. After that, the next order proposal for the menu plan uses this stock."

**Measured on the live site (2026-11-14, `demo-shelf.png` through `/api`).** HTTP 200 in
2.7 s; the model part was 0.8 s (`duration_ms: 789`).

| Product | On the photo | Nemotron | In the Count field |
|---|---|---|---|
| 463335 Valio Eila 3 % milk drink 1 l | 6 | 6, high | 6 L |
| 464194 Valio whipping cream 1 l | 5 | 5, high | 5 L |
| 464187 Keiju Rapeseed oil 1 l | 4 | 4, high | 4 L |
| 462718 Valio Turkish cooking yoghurt 2 kg | 3 | 3, high | 6 KG |
| 463437 Valio Eila butter 500 g | 4 | 4, high | 2 KG |
| 462616 Valio Edam 1 kg (half hidden) | 1 | "Valio Edam 17 %", medium, no product match | please count |

`shelf.png` through the same route: HTTP 200 in 2.8 s (model 1.2 s), five rows, all
`UNMATCHED`. Both calls wrote nothing to stock (checked with `GET /stock` after them).

The same photo through the page itself (headless Chrome, 390 px wide, "Choose a file"):
1.9 s from the file to the filled fields; the page sent one 147 KB JPEG and nothing else.
The model read "Valio Elia" for "Valio Eila" on two packs that time, and the match held.

**Warning.** "Save count" changes the demo kitchen's real stock, and the plan proposal
reads it. The save step was not run on the live site that night. Run the whole beat once
in rehearsal and decide then if you press Save on stage.

**If it fails.** The panel says why, and the counts can still be typed by hand. "no vision
model is configured" means `VERDA_INFERENCE_KEY` is missing in the `buyer` container.

## Selling-agent beat: Valio's agent offers a substitute (#374)

**What it shows.** Nemotron in a second role, on the supplier's side. Code reads Valio's
shortage view and builds a shortlist; the model picks one product and writes the reason;
the gateway sets the quantity from the kitchen's own forecast. The kitchen sees a
suggestion. A person makes a proposal from it, and the proposal waits in the inbox like
any other.

**Before the demo.** The tile shows only while an offer is open, and an accepted or
declined offer is final. Make a new one on the server (`/opt/2brothers`); the dry run
first, it sends nothing:

    docker compose --env-file .env -f deploy/compose.yaml run --rm -T --no-deps gateway python -m agent.seller --dry-run --limit 1 --kitchen demo-kitchen
    docker compose --env-file .env -f deploy/compose.yaml run --rm -T --no-deps gateway python -m agent.seller --apply --limit 1 --kitchen demo-kitchen

The demo kitchen must share its forecast with Valio Aimo (`/suppliers`); without it the
run prints `SHARING_REQUIRED` and sends nothing. A date whose order cut-off passed gives
`NO_SUBSTITUTE` (on 14 Nov nothing could still arrive for Sunday 15 Nov).

**Seen on the live site (2026-11-14, 04:40 UTC).** The run sent one offer: Rosamunda
washed potato (460643) in place of washed potato 1 kg (460478), predicted short on Monday
16 Nov, 10.48 kg from the demo kitchen's forecast, picked by `nemotron-3.5-super-vl`. On a
390 px screen the tile showed the product, what it replaces, the quantity, the model's
sentence with its author, and "The catalog has no allergen data for this product. Check
the label before you approve." "Make a proposal" opened the inbox with a new card, "Offer
from Valio Aimo: POTATO ROSAMUNDA WASHED in place of POTATO WASHED 1KG", EUR 37.13 incl
VAT, waiting; nothing was approved. The audit log has `supplier_offer_received` (actor
`supplier:sup-valio`), `proposal_created` and `supplier_offer_accepted`.

**What went wrong first, so you know.** The first server run gave no offer: the catalog
has no allergen data for vegetables and potatoes, and the shortlist refused them all
(fixed in #952). And the model's first sentence said "the same 1kg pack size" about a
potato that is sold by weight; the model now gets how a product is sold, and a reason
with a pack or a number it was not given is dropped (#963).

## What was measured on the live site (2026-11-14)

- Milk request through the web: answer in 12 s. Status READY, two lines: 698 ST of 463380
  (stock confirmed) and 302 ST of 464237 (cheapest per litre, stock not confirmed).
  EUR 2,242.30 ex VAT, EUR 2,545.01 total.
- The portion cups (463203, 7.55 EUR per litre) are left out with a reason: "confirmed in
  stock, but ... 5.8 times the cheapest". That is the certainty premium limit (#700).
- `/llms.txt`, `/.well-known/agent-card.json`, `/gateway/openapi.json`: all answer 200.
- Conformance kit on the server: 11 passed, 0 failed, 1 skipped (#609).
- `python -m gateway.scenarios`: 13 PASS.

Time to order: the agent path is about 12 s plus one tap. The manual webshop time is
**not measured yet**: do one order by hand in the Valio webshop with a stopwatch and put
the number on the last slide. Do not quote a number nobody measured.

## If something fails

- **The page does not load:** a deploy is running. Wait 20 s and reload (see step 3).
- **No tile on Home:** the offer was used in rehearsal. Make a new one (step 1). If the
  seller prints only `NO_SUBSTITUTE` or `ALREADY_OFFERED`, there is no new shortage to offer
  for: skip beat 1 and open on the sponsor's milk example instead.
- **"Make a proposal" gives a REJECTED proposal:** nothing can be delivered for that date
  any more. The offer stays open. Say: "Valio's stock moved since the offer; the gateway
  checks again and does not pretend", and go on with beat 3 on an older order.
- **The recall check takes long:** it waits up to 45 s for Context.dev, then answers from
  the recording and says so. Keep talking; the alert is already stored.
- **Nothing works:** play the fallback video and talk over it. Milk story:
  `demo/out/fallback-2026-11-14-final-with-approval.webm`. A story-A video comes from
  `python -m demo.record_demo --story offer --approve` (it uses up the open offer).

## Not in the demo

Voice approval, the recipe builder, the menu planner and the settings pages. They exist or
are planned, and none of them scores in three minutes.

## Open items for this script

- [x] Fallback video: `python -m demo.record_demo --approve` records it with the approval
      (run 14 Nov 04:20 UTC, all nine steps ok). Record the final one after the last change.
- [ ] Measure the manual webshop time (#295).
- [ ] Buyer path through the web still fell back to the parser at 02:22 UTC on 14 Nov;
      confirm it says the Buyer model before rehearsal.
- [ ] Recall beat: `CONTEXT_DEV_API_KEY` on the server; the coffee 461332 in the demo
      kitchen's stock (no seed needed, #358). One-shot: do not press
      "Check recalls now" in rehearsal on the live kitchen.
- [x] Tamper check beat: live on `/trust` (#747, #818).
- [x] Choose button on the option card (#403, #843): the big request can be approved.
- [ ] Claude Desktop as the second agent (`docs/byoa.md`): run it once before the demo.
