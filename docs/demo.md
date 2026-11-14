# Demo script: three minutes

Status: draft, written 2026-11-14 04:50 (Helsinki) from tests on the live site that night.
Owner: Aron (presents). Site: `https://31-22-104-201.sslip.io`.

Each beat says what the site does **today**. A beat marked *not live yet* names the issue
that makes it live. Do not show a beat that is not live: an honest three steps beat five
shaky ones.

## Before you go on stage

1. **Stop deploys.** Every merge to main redeploys and restarts the containers. On
   2026-11-14 there were 46 deploys in one hour; pages refused connections for some
   seconds and one Buyer request got a 502 (#660). One hour before the demo, on the server:

   ```
   touch /opt/2brothers.hold
   ```

   Remove the file after judging. Tell the team: no merges to main during the hold.
2. **Pick the delivery date.** Many Valio products close their order cut-off days ahead
   (on Saturday 14 Nov, 12 of 20 lactose-free milks had already closed for Monday 16 Nov).
   Use a date for which the cut-offs are open, and run the request once in rehearsal with
   that exact date. "By Monday" on Sunday morning will have fewer open products.
3. **Check the Buyer path.** After the request, the card must not say "Proposed by the
   gateway's request parser". If it does, the Nemotron Buyer fell back (see "If something
   fails"). Check once in rehearsal.
4. **Open the tabs:** `/requests`, `/approvals` on a phone, `/audit`, `/llms.txt`, a
   terminal with the two commands of beat 5. For the photo beat: `/stock`, and
   `agent/fixtures/shelf/demo-shelf.png` on the device that shows it.
5. **Recall beat only:** it is one-shot per recorded notice (see "Recall beat"). It needs
   the coffee 461332 in the demo kitchen's stock (`/stock`; 3.253 kg on 14 Nov), no seed.
6. **Have the fallback video open** in a player, paused at 0:00. Record it with
   `python -m demo.record_demo --approve` (about 75 seconds, captions, no sound; it sends the
   1,000 L request, takes option A and approves it; the file
   lands in `demo/out/`). Record again after any change to the demo path.
   Story A ("Valio sees it first"): `python -m demo.record_demo --story offer --approve`.
7. **Clear the inbox.** Test requests pile up: on 14 Nov the menu badge showed 24 waiting
   proposals. On the server, through the gateway container:
   `python -m demo.clear_inbox` lists them, `python -m demo.clear_inbox --apply` removes
   them. It is not a reject, so it does not count as a person's decision.
8. **Warm up.** Send one request before the live one. The Buyer model does not finish about
   one run in three; the gateway then retries once (#735), and after that the parser answers.

## One request, and a person can approve it

A proposal with a line whose stock Valio does not report cannot be placed as it is: a
person's yes is not stock confirmation. The 1,000 L milk proposal has such a line. Its card
therefore shows options, and the first one is the part that Valio's stock confirms:
"Order the confirmed 698 L now. The other 302 L is held until the supplier confirms stock;
nothing is ordered for it." The button "Choose option A: approve EUR 2,099.41 incl VAT"
takes that option and opens the approval dialog with the exact total (#775, #844, #843).

Checked on the live site on 14 Nov at 04:10 UTC, on a 390 px wide screen: request, card in
14 s from the Buyer (Nemotron 3.5 Super VL), Choose, "Yes, approve EUR 2,099.41", status
APPROVED with one line of 698 ST of 463380 and an order id.

- **Backup request:** `200 L lactose-free milk by Monday`. Confirmed stock covers all of it
  (200 ST of 463380, EUR 601.55, 8.5 s), so its card has a plain Approve button.

## The script

| Time | Beat | What you do | What you say | Criterion |
|---|---|---|---|---|
| 0:00 | 1. The request | On `/requests` type: `1,000 L lactose-free milk by Monday`. Press "Ask the agent". | "This is the sentence from your challenge. No product codes." | A, B |
| 0:15 | 2. The honest answer | The card appears (about 12 s). Read the "Why this basket" list. | "It checked 20 products with live Valio prices and stock. 12 cannot make Monday: their cut-off passed. Valio confirms stock for 698 litres only. The rest is on the cheapest milk, and the card says its stock is not confirmed. A chatbot would have promised 1,000 litres." | B, D |
| 0:50 | 3. The human decides | Open `/approvals` on the phone. Show the total and the options. Press "Choose option A", then "Yes, approve". Open `/audit`. | "The agent can propose. It has no approve tool. I take the part Valio confirms: 698 litres now, 302 held, nothing ordered for it. I approve the exact total; if the price moves, the old yes is refused. Every step is in a hash-chained log." | C |
| 1:30 | 4. An exception | The tamper check on `/trust`: "Verify audit chain" says Chain OK; "Run the tamper test" changes one line and the page says "Chain broken at line N"; restore, and it is OK again (live, checked 14 Nov). Or run `python -m gateway.scenarios` in the terminal. Or the recall beat below. | "Nobody can edit the log quietly, not even us. And 13 golden cases with the correct decision all pass: a moved price, an allergen with missing data, a duplicate send." | D |
| 2:10 | 5. Any agent | In the terminal: `curl -s https://31-22-104-201.sslip.io/llms.txt \| head -20`, then the search call from `docs/byoa.md`. | "This is not our agent's private door. Any agent with a URL and a token can read the catalog, get an offer, simulate and propose. (To show it in 10 seconds: `python -m demo.second_agent --make-token`, an outside MCP client that reaches a waiting proposal and gets 403 when it tries to approve.) The agent card, the OpenAPI file and the MCP endpoint are public. Our conformance kit runs 12 trust checks against any gateway." | E |
| 2:40 | 6. Close | Show the Valio side: role "Valio planner", Home. Then the kitchen's Home: the tile "Offer from Valio Aimo" (needs an open offer, see "Selling-agent beat"). | "The kitchen shares its forecast if it agrees. Valio sees demand before the orders arrive: 16 kitchens share, and 8 lines are short for Monday and Tuesday." (Numbers from 14 Nov; read them from the screen.) "Valio's own agent, also Nemotron, saw the washed potatoes run short and offered this kitchen another washed potato. It is a suggestion: I make a proposal from it, and that proposal still waits for my approval." | bonus |

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

- **The page does not load:** a deploy is running. Wait 20 s and reload. This is why step 1
  exists.
- **"Proposed by the gateway's request parser":** the Buyer model did not finish; the
  deterministic parser answered. The numbers are still the engine's and still correct. Say:
  "the model is a convenience; the guards and the numbers do not depend on it". Then move on.
- **The proposal is REJECTED with no lines:** every candidate missed its cut-off for that
  date. Use the date you rehearsed with.
- **Nothing works:** play the fallback video and talk over it.

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
