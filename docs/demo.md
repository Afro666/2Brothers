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
   terminal with the two commands of beat 5.
5. **Recall beat only:** it is one-shot per recorded notice and needs data (see beat 4).
6. **Have the fallback video open** in a player, paused at 0:00 (#295: not recorded yet).

## The script

| Time | Beat | What you do | What you say | Criterion |
|---|---|---|---|---|
| 0:00 | 1. The request | On `/requests` type: `1,000 L lactose-free milk by Monday`. Press "Ask the agent". | "This is the sentence from your challenge. No product codes." | A, B |
| 0:15 | 2. The honest answer | The card appears (about 12 s). Read the "Why this basket" list. | "It checked 20 products with live Valio prices and stock. 12 cannot make Monday: their cut-off passed. Valio confirms stock for 698 litres only. The rest is on the cheapest milk, and the card says its stock is not confirmed. A chatbot would have promised 1,000 litres." | B, D |
| 0:50 | 3. The human decides | Open `/approvals` on the phone. Show the total and the options. Approve or reject with one tap. Open `/audit`. | "The agent can propose. It has no approve tool. A person approves the exact total; if the price moves, the old yes is refused. Every step is in a hash-chained log." | C |
| 1:30 | 4. An exception | Show one: the recall hold (*not live in the web yet*, #655), or the tamper check on `/trust` (*mock data in gateway mode until the trust routes merge*). Until then: run `python -m gateway.scenarios` in the terminal. | "13 golden cases with the correct decision. All 13 pass. They include a moved price, an allergen with missing data, and a duplicate send." | D |
| 2:10 | 5. Any agent | In the terminal: `curl -s https://31-22-104-201.sslip.io/llms.txt \| head -20`, then the search call from `docs/byoa.md`. | "This is not our agent's private door. Any agent with a URL and a token can read the catalog, get an offer, simulate and propose. The agent card, the OpenAPI file and the MCP endpoint are public. Our conformance kit runs 12 trust checks against any gateway." | E |
| 2:40 | 6. Close | Show the Valio side: role "Valio planner", Home. | "The kitchen shares its forecast if it agrees. Valio sees demand before the orders arrive: 16 kitchens share, and 8 lines are short for Monday and Tuesday." (Numbers from 14 Nov; read them from the screen.) | bonus |

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

- [ ] Record the 90-second fallback video (#295).
- [ ] Measure the manual webshop time (#295).
- [ ] Buyer path through the web still fell back to the parser at 02:22 UTC on 14 Nov;
      confirm it says the Buyer model before rehearsal.
- [ ] Recall beat: web wiring #655; `CONTEXT_DEV_API_KEY` on the server; seed with
      `python -m demo.recall_demo` (see `deploy/README.md`). One-shot: do not press
      "Check recalls now" in rehearsal on the live kitchen.
- [ ] Tamper check beat: gateway trust routes and the web wiring.
- [ ] Claude Desktop as the second agent (`docs/byoa.md`): run it once before the demo.
