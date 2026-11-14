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
5. **Recall beat only:** it is one-shot per recorded notice and needs data (see beat 4).
6. **Have the fallback video open** in a player, paused at 0:00. Record it with
   `python -m demo.record_demo --approve` (about one minute, captions, no sound; the file
   lands in `demo/out/`). Record again after any change to the demo path.
7. **Clear the inbox.** Test requests pile up: on 14 Nov the menu badge showed 24 waiting
   proposals. On the server, through the gateway container:
   `python -m demo.clear_inbox` lists them, `python -m demo.clear_inbox --apply` removes
   them. It is not a reject, so it does not count as a person's decision.
8. **Warm up.** Send one request before the live one. The Buyer model does not finish about
   one run in three; the gateway then retries once (#735), and after that the parser answers.

## Two requests, not one

A proposal with a line whose stock Valio does not report cannot be placed: a person's yes is
not stock confirmation. On 14 Nov every 1,000 L milk proposal had such a line, so its
Approve button was disabled. Until the option card has a Choose button (#403), show the
approval on a request that confirmed stock covers:

- **Small request, for the one-tap approval:** `200 L lactose-free milk by Monday`. Measured
  live: the Buyer (Nemotron 3.5 Super VL) answered in 8.5 s with 200 ST of 463380, stock
  confirmed, EUR 601.55. It can be approved.
- **Big request, for the honest answer:** `1,000 L lactose-free milk by Monday`. It shows
  the split, the cut-offs and the first option: "Order the confirmed 698 L now. The other
  302 L is held until the supplier confirms stock" (EUR 2,099.41, served by the gateway
  since #775). With the Choose button a person takes that option and approves it.

## The script

| Time | Beat | What you do | What you say | Criterion |
|---|---|---|---|---|
| 0:00 | 1. The request | On `/requests` type: `1,000 L lactose-free milk by Monday`. Press "Ask the agent". | "This is the sentence from your challenge. No product codes." | A, B |
| 0:15 | 2. The honest answer | The card appears (about 12 s). Read the "Why this basket" list. | "It checked 20 products with live Valio prices and stock. 12 cannot make Monday: their cut-off passed. Valio confirms stock for 698 litres only. The rest is on the cheapest milk, and the card says its stock is not confirmed. A chatbot would have promised 1,000 litres." | B, D |
| 0:50 | 3. The human decides | Open `/approvals` on the phone. Show the total and the options. Approve or reject with one tap. Open `/audit`. | "The agent can propose. It has no approve tool. A person approves the exact total; if the price moves, the old yes is refused. Every step is in a hash-chained log." | C |
| 1:30 | 4. An exception | Show one: the recall hold (*not live in the web yet*, #655), or the tamper check on `/trust` (*mock data in gateway mode until the trust routes merge*). Until then: run `python -m gateway.scenarios` in the terminal. | "13 golden cases with the correct decision. All 13 pass. They include a moved price, an allergen with missing data, and a duplicate send." | D |
| 2:10 | 5. Any agent | In the terminal: `curl -s https://31-22-104-201.sslip.io/llms.txt \| head -20`, then the search call from `docs/byoa.md`. | "This is not our agent's private door. Any agent with a URL and a token can read the catalog, get an offer, simulate and propose. The agent card, the OpenAPI file and the MCP endpoint are public. Our conformance kit runs 12 trust checks against any gateway." | E |
| 2:40 | 6. Close | Show the Valio side: role "Valio planner", Home. | "The kitchen shares its forecast if it agrees. Valio sees demand before the orders arrive: 16 kitchens share, and 8 lines are short for Monday and Tuesday." (Numbers from 14 Nov; read them from the screen.) | bonus |

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
"Too many requests": the route allows 10 photos a minute per address.

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

- [x] Fallback video: `python -m demo.record_demo` records it (first run 14 Nov, 57 s). Record the
      final one with `--approve` after the last change.
- [ ] Measure the manual webshop time (#295).
- [ ] Buyer path through the web still fell back to the parser at 02:22 UTC on 14 Nov;
      confirm it says the Buyer model before rehearsal.
- [ ] Recall beat: web wiring #655; `CONTEXT_DEV_API_KEY` on the server; seed with
      `python -m demo.recall_demo` (see `deploy/README.md`). One-shot: do not press
      "Check recalls now" in rehearsal on the live kitchen.
- [ ] Tamper check beat: the gateway routes are live (#747, `/audit/verify` answers the real
      chain); the web Trust page still shows sample data until #789.
- [ ] Choose button on the option card (#403), so the big request can be approved in the demo.
- [ ] Claude Desktop as the second agent (`docs/byoa.md`): run it once before the demo.
