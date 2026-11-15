# Demo script: three minutes

Status: **two running orders exist, and Aron's choice between them is open.** Story A (nine
beats, the offer tile first) was chosen by Aron on 2026-11-14 at 09:55 Helsinki and stays
the default until he says otherwise. The "Short version: milk first, six beats" below is
the order three mock jury rounds asked for; it is ready, and it replaces nothing.
The sponsor's own example, `1,000 L lactose-free milk by Monday`, is beat 2 to 4 of story A
and beat 1 to 3 of the short version. The milk card is described as on `main` on 15 Nov
(after #1905, #1971, #1972, #1976, #1977 and #1981); look at the live card first, because
a change shows only after its deploy. Each beat ran on the live site on 14 Nov, but
neither order was rehearsed as one run yet.
Owner: Aron (presents). Site: `https://31-22-104-201.sslip.io`.

Why this story: it shows the parts nobody else has (Valio's own agent, a refusal, an
outside agent), and it runs the sponsor's own request from the sentence to the signed
receipt. **One beat uses the Nemotron model live: the milk request (one model call).** When
the model does not answer, the gateway's parser makes the proposal and the card says so;
the story still works. The seller makes the offer before the demo and has a `--no-model`
fallback. On 14 Nov at 09:45 Helsinki the model endpoint did not answer for a while.

## Before you go on stage

1. **An open offer on Home.** The tile "Offer from Valio Aimo" needs an open offer. An
   accepted or declined offer is final within a round, and a rehearsal or a recording uses
   the open one up. So before each run, on the server, start a new round and make a fresh
   offer (#1182):

   ```
   cd /opt/2brothers
   docker compose --env-file .env -f deploy/compose.yaml run --rm -T --no-deps gateway python -m demo.reset_offers --kitchen demo-kitchen --apply
   docker compose --env-file .env -f deploy/compose.yaml run --rm -T --no-deps gateway python -m agent.seller --dry-run --limit 1 --kitchen demo-kitchen --days 14
   docker compose --env-file .env -f deploy/compose.yaml run --rm -T --no-deps gateway python -m agent.seller --apply --limit 1 --kitchen demo-kitchen --days 14
   ```

   Skip the first line when an offer is still open (the tile shows). Read the dry-run line
   first: a sensible substitute (same kind of food), `made_by` `nemotron-3.5-super-vl`. The
   model can take over a minute per answer (on 14 Nov: 67 s and 75 s). If it does not
   answer, add `--no-model` (a rule picks, `made_by: rule`); then do not say "Nemotron
   picked it" on stage. The open offer changes with every round: read the product, the
   date and the amount from the open offer on the Home tile, never from this file.
2. **Clear the inbox.** On the server: `python -m demo.clear_inbox` lists the waiting
   proposals, `python -m demo.clear_inbox --apply` removes them (not a reject, so it is
   not a person's decision). Then the offer's card and the milk card are the only ones.
3. **No deploys while you present.** There is no deploy hold (Aron's choice). A merge
   restarts the site for some seconds: before you start, look at GitHub Actions; if a
   deploy runs, wait for it.
4. **Open the tabs:** `/` (Home) on the phone, `/requests`, `/approvals`, `/orders`,
   `/trust`, `/demand`, `/about`, and a terminal in the repo for beat 8.
5. **The recall alert is stored.** Aron pressed "Check recalls now" on 14 Nov at 09:31: a
   live scrape (102 notices), the recalled coffee 461332 in stock (3.253 kg) and in three
   recipes. The panel shows it already. Do not press the button on stage: beat 6 only
   points at the stored alert.
6. **Make the outside agent's token before you start** if sign-in is on (it is off for
   judging): Settings, API & MCP tokens. With sign-in off, `--make-token` makes one.
7. **Fallback video** open in a player, paused at 0:00 (see "If something fails").
   Record it with `python -m demo.record_demo --story offer --approve`. The recorder types
   the same milk sentence, so step 8 counts for a recording too.
8. **The pick cache: ten minutes.** The same request within ten minutes reuses the stored
   pick (`store/buyer_picks.py:10-14` and `:40`: the key holds the kitchen, the typed text,
   the day, the amount and the shortlist; a pick lives 600 seconds). The pick is then a
   "Code:" step in the "What Nemotron did" panel, with the words "Reused Nemotron’s pick
   for the same request from a few minutes ago", and no model call is counted for it
   (`agent/service.py:134-137`, `web/src/components/purchasing/model-trace-panel.tsx:60`).
   The line on the folded card then does not say "1 call". The panel counts only the
   explanation call ("1 model call, ..."), or says "0 model calls (pick reused)" when
   the card has no explanation (`:88-89`). The script names the pick as a model call, so
   do one of these two:
   - wait ten minutes between the last rehearsal (or recording) and the real run; or
   - in rehearsal type `1000 litres of lactose-free milk for Monday`, and on stage type
     `1,000 L lactose-free milk by Monday`. Both read as 1000 L of "lactose free milk" for
     next Monday (`gateway/parse.py` `parse_request` and `agent/service.py` `parse_need`,
     run on both sentences for this text). The typed text is part of the key, so the
     second wording is a new pick. Keep the same day in the "Needed by" field.
9. **A fresh milk request after the last deploy.** A stored card keeps the options it was
   made with. A milk card from before #1894 can still hold a low-lactose milk as an
   option; a new request never does (`gateway/diet.py`, `gateway/service.py:399`). So
   after the last deploy: clear the inbox (step 2), then make the milk request again. Do
   not present an old milk card. Then look at the live card once: if its main button
   says "Approve option A: ..." and the card has the line "... of ... · ... not covered",
   the texts of this file hold. If the button says "Approve ... incl VAT", the new card is
   not deployed yet: use the older taps in "The taps on the milk card" below.

## The script (story A: Valio sees it first)

| Time | Beat | What you do | What you say | Criterion |
|---|---|---|---|---|
| 0:00 | 1. Valio sees it first | Home on the phone. Point at the open offer on the Home tile "Offer from Valio Aimo": the offered product, "in place of ..., which is predicted short on ...", the amount "from your own forecast", the sentence "written by Valio's selling agent (Nemotron 3.5 Super VL)". Read the product and the day from the tile. Press "Make a proposal": the card waits in the inbox. Do not approve it. | "This kitchen shares its forecast with Valio. Valio's own agent, Nemotron, saw that this product will run short, and offers a substitute before anyone orders. The supplier sends no price and no quantity: the amount is the kitchen's own forecast, and the price comes live from Valio when we ask. It is a normal proposal now, and it waits for a person." | B, E, bonus |
| 0:25 | 2. The sponsor's request | `/requests`: type `1,000 L lactose-free milk by Monday`, press "Ask the agent". The card opens in `/approvals`, folded. Point at the label beside the heading "To approve": "Live" and "MongoDB Atlas change stream". On the card, point at: the line "Picked by Nemotron 3.5 Super VL · 1 call · ... s"; the short explanation, signed "Written by Nemotron 3.5 Super VL from the checked decision record" (point at it now: it is gone after the approval); the total with "Option A, recommended by the Buyer" and the coverage line "... of ... · ... not covered" under it; the chip "Over budget" and the line under the chips, "Option A: ... ex VAT is ... above your kitchen's budget warning of ... per order. A warning only." | "This is Valio's own example. A chef writes one sentence, not product codes. New proposals reach this inbox without a refresh, over a MongoDB Atlas change stream. Valio does not have 1,000 litres confirmed in stock, so the card does not pretend: it leads with option A, the confirmed litres, and this line says how much is not covered. Nemotron wrote this short explanation from the checked record. 'Over budget': the line names option A's total, how far it is above this kitchen's own warning limit for one order, and the limit. It is a warning, not a block: the money is the kitchen's, so a person decides, not the agent." | A, B |
| 0:45 | 3. What Nemotron did | The panel is inside the folded part. On the milk card, press "Inspect (... options)" (or the link "Open the full decision record" under the explanation): the card unfolds. Scroll to the end of the open part and press "What Nemotron did": the panel opens. Folded it says "2 model calls, ... s, thinking off" ("1 model call, ..." when the card has no explanation). Unfolded, each step says "Model:" or "Code:"; the pick is "Model: Picked one product from the shortlist", the last step is "Model: Wrote the explanation on this card from the checked decision record: ... s", and the last line says "Quantities and prices: the engine. Approval: you." | "Two model calls, and neither sets a number. In the first, Nemotron picked the products from a shortlist. In the second, it wrote the short explanation on the card, from the checked record. Code did every other step: the search, the offer, the check against the guards, the request for approval. The model sets no quantity and no price, and it has no approve tool." If the panel says "1 model call", say "One model call: Nemotron picked the products from a shortlist", and leave the second call out. | A, C |
| 1:05 | 4. A person decides | Two taps. 1: the main button "Approve option A: ..." at the foot of the card (Inspect can stay open or closed). The card chooses option A and loads the new total; wait, do not press twice. 2: the dialog "Approve this order?" opens by itself: press "Yes, approve ...". Read the letter and the total from the screen. The card then says "Approved and recorded: ... Nothing is sent to the supplier." The explanation is not on the card after this: do not go back to point at it. | "A suggestion never becomes an order by itself. I approve the exact total I see: if the price or the stock moves before the order is placed, this yes is refused." | A, C |
| 1:25 | 5. Proof | `/orders`: open the milk order you just approved. Point at the block "Signed receipt": "Approved by", "Signed at", "Signed total", and under "Supplier" the words "Nothing sent to the supplier yet". Then `/trust` (the page "Tamper check"): point at the badge "Audit log stored in MongoDB Atlas", press "Verify audit chain", and point at the result line "Audit log intact: each of the ... entries carries the hash of the one before it". If a judge asks more about MongoDB: `/about`, the card "The data lives in MongoDB Atlas". | "An order that a person approves gets a signed receipt. Anyone can check it with our public key; change one number and the check fails. It also says plainly that Valio's test API has no order endpoint, so nothing was sent. And every step is in this log, in MongoDB Atlas, each line hashed with the one before." | C, E |
| 1:50 | 6. A recall | `/approvals`, the recall panel. Point at the stored alert. Do not press "Check recalls now". | "The Finnish Food Authority recalled batches of this coffee. It is on our shelf and in three of our recipes. New orders leave it out, and a person checks the packs." | D |
| 2:00 | 7. A rule the agent cannot break | `/requests`: type `15 kg peanut butter`, press "Ask the agent". | "This kitchen excludes peanuts. The request is refused in under a second, before any model runs, and nothing else is swapped in. An agent that 'helps' with plain butter would be worse than no agent." | C, D |
| 2:20 | 8. Any agent | Terminal: `python -m demo.second_agent --make-token`. It prints ten lines. Point at line 9: "the agent tries to approve its own proposal: HTTP 403 HUMAN_SESSION_REQUIRED". | "This is not our agent's door. An outside client reads our public agent card, connects over MCP, searches, gets an offer and asks for approval. Then it tries to approve its own proposal: 403. Only a person approves." | E |
| 2:45 | 9. Close | `/demand`: the Valio planner view. | "Valio sees the demand of every kitchen that agreed to share, and which lines will be short. That is how its agent knew about the shortage on the tile. Open interface, a person signs, and every step is in a hash-chained log." | bonus |

## Short version: milk first, six beats (the mock jury's order; Aron chooses which to present)

Three mock jury rounds (four judges in the last two) said the same: open with the sponsor's
sentence, six beats, no terminal on stage. Aron has not chosen yet, so story A above stays;
this is the ready alternative. About 2:30 in all. The spoken lines are story A's, shortened.
The numbers come from the screen. "Before you go on stage" counts for this order too, and
one thing more: record the clip of beat 6 before the stage.

| Time | Beat | What you do | What you say | Criterion |
|---|---|---|---|---|
| 0:00 | 1. The sponsor's request | `/requests`: type `1,000 L lactose-free milk by Monday`, press "Ask the agent". The card opens in `/approvals`, folded. Point at: the line "Picked by Nemotron 3.5 Super VL · 1 call · ... s"; the total with "Option A, recommended by the Buyer"; the coverage line "... of ... · ... not covered"; the chip "Over budget" and its line "Option A: ... ex VAT is ... above your kitchen's budget warning of ... per order. A warning only." | "This is Valio's own example. A chef writes one sentence, not product codes. Valio does not have 1,000 litres confirmed in stock, so the card does not pretend: it leads with the confirmed litres, and says how much is not covered. 'Over budget' is this kitchen's own warning limit for one order: a warning, not a block. The money is the kitchen's, so a person decides." | A, B |
| 0:30 | 2. What Nemotron did | Point at the short explanation on the card, signed "Written by Nemotron 3.5 Super VL from the checked decision record" (now: it is gone after the approval). Press "Inspect (... options)", scroll to the end of the open part, press "What Nemotron did". It says "2 model calls, ... s, thinking off"; the last line says "Quantities and prices: the engine. Approval: you." | "Two model calls, and neither sets a number. First Nemotron picked the products from a shortlist. Then it wrote this explanation from the checked record. Code did the search, the offer, the check and the request for approval. The model has no approve tool." If the panel says "1 model call", say only the pick. | A, C |
| 0:55 | 3. A person decides | The main button "Approve option A: ..."; wait; in the dialog "Approve this order?" press "Yes, approve ...". The card then says "Approved and recorded: ... Nothing is sent to the supplier." | "A suggestion never becomes an order by itself. I approve the exact total I see: if the price or the stock moves, this yes is refused." | A, C |
| 1:10 | 4. Proof | `/orders`: open the milk order. Point at the block "Signed receipt" and, under "Supplier", the words "Nothing sent to the supplier yet". Then `/trust`: the badge "Audit log stored in MongoDB Atlas", press "Verify audit chain", point at "Audit log intact: each of the ... entries carries the hash of the one before it". | "A person's yes gets a signed receipt. Anyone can check it with our public key; change one number and the check fails. It says plainly that Valio's test API has no order endpoint, so nothing was sent. And every step is in this log, in MongoDB Atlas, each line hashed with the one before." | C, E |
| 1:40 | 5. Two guards | `/requests`: type `15 kg peanut butter`, press "Ask the agent": refused. Then `/approvals`: point at the folded recall row, "1 recall: ... is in your stock (...)." Do not unfold it and do not press "Check recalls now". | "This kitchen excludes peanuts: refused in under a second, before any model runs, and nothing is swapped in. And a recall: the Finnish Food Authority recalled this coffee, it is on our shelf, and new orders leave it out." | C, D |
| 2:00 | 6. Valio's side | Home: the tile "Offer from Valio Aimo"; point at "written by Valio's selling agent (Nemotron 3.5 Super VL)". Do not press "Make a proposal". Then play the 10-second clip: an outside agent's run that ends with "the agent tries to approve its own proposal: HTTP 403 HUMAN_SESSION_REQUIRED". No terminal on stage. | "Valio's own agent saw the shortage first: this kitchen shares its forecast, and Valio offers a substitute before anyone orders, with no price and no quantity from the supplier. And the door is open to any agent: this outside client connected over MCP, asked for approval, then tried to approve its own proposal. 403. Only a person approves." | B, E, bonus |

**The clip of beat 6.** Record it before the stage, in a terminal in the repo:
`python -m demo.second_agent --make-token`. Record the screen while it runs, and cut to about
10 seconds that end on line 9 ("9. the agent tries to approve its own proposal: HTTP 403
HUMAN_SESSION_REQUIRED") and the line that starts with "RESULT:". The run leaves one
waiting proposal in the inbox: clear the inbox after it (step 2). Say "recorded before the
stage" if a judge asks; the command runs live on request.

**If a judge asks:** `/demand`, the Valio planner view ("Valio sees the demand of every
kitchen that agreed to share, and which lines will be short"); `/about`, the card "The
data lives in MongoDB Atlas". Neither is a beat here.

**The recall row** is one folded line since #1629
(`web/src/components/purchasing/recall-panel.tsx:83-97`). Its words depend on the stored
alert; read them in rehearsal.

## Notes for both orders

The beat numbers in these notes are story A's. In the short version the milk card is beat
1 to 3, the proof is beat 4, the two guards are beat 5.

**The numbers of the milk beat come from the screen, not from this file.** Valio's stock
moves, so the confirmed litres and the total of option A change:

- An earlier run on 14 Nov had 698 L confirmed and 302 L held, and option A was
  EUR 2,099.41 (this file before this change; the request was measured through the web,
  see "What was measured").
- A later live quote on 14 Nov had 51 L confirmed (`docs/submission.md`, "Buyer read
  context").
- Today's values were not read for this text: reading them needs a live request, which
  writes a need and a proposal. Read them off the card in rehearsal and say those.

**The taps on the milk card** (beat 3 and 4). This is the card on `main` on 15 Nov; a
change shows live only after its deploy, so look at the live card first (step 9).

- Every card starts folded (`web/src/components/purchasing/approval-card.tsx:251`). The
  folded card shows the line "Picked by Nemotron 3.5 Super VL · 1 call · ... s" (`:671`,
  `model-trace-panel.tsx:112-128`) and the short explanation. No tap is needed to read
  who picked.
- The "What Nemotron did" panel is still inside the part that "Inspect (... options)"
  opens (`approval-card.tsx:979`, the button `:993`), and the panel itself is folded. So
  beat 3 needs two taps: Inspect, then "What Nemotron did". The number in the Inspect
  label is the count of options on the card. The panel counts the pick and the explanation:
  "2 model calls" (`model-trace-panel.tsx:183`).
- The card leads with the recommended option while nobody changed the basket: the total is
  that option's, with "Option A, recommended by the Buyer" under it, and the main button
  says "Approve option A: ..." (`approval-card.tsx:351`, `:1025`). One press chooses
  option A, the gateway works the order out again, and the dialog "Approve this order?"
  opens by itself (`:482`).
- The words stay the same after the choice: the card still says "Option A, recommended by
  the Buyer" and the button still says "Approve option A: ..." (`:722`, `:1039`). So if
  the dialog was closed with "Cancel", press the same button again.
- Under the total, the coverage line says what was asked and what option A covers: "... of
  ... · ... not covered" (`:383-405`, #1970). It took the place of "... waits for stock
  confirmation" on the folded card; that sentence is now only inside Inspect, under the
  option.
- Before the choice, the line "Option ..., the basket proposed now: ..." under the total is
  the Buyer's own basket, another option than the one the card leads with. Do not read
  that amount as the total you approve.
- A basket a person edited is no option: its button says "Approve ..." with no letter
  (`:1040`). Change no line on the milk card before the approval. A button "Approve ...
  incl VAT" means the site still runs the older card: then open "Inspect (... options)",
  and under "Your options" press the button that starts with "Choose option A: approve";
  the dialog opens after a moment.
- In beat 3, press nothing under "Your options": a press there makes the total and the
  main button follow that pick (`approval-card.tsx:472`, `:953`). The option button on
  `main` reads "Choose option A: approve ..." (`option-compare.tsx:371`).
- The options view inside Inspect, on `main` today: the badges "Recommended by the Buyer",
  "Part now, the rest later", "Proposed now" and "The supplier must confirm stock"; the
  facts "Total" ("... in all"), "Stock" ("confirmed") and "Order cut-off" ("order by ..."
  or "met (order by ...)"); and "... waits for stock confirmation"
  (`option-compare.tsx:252-259`, `:285-305`, `:352`). PR #1988 (open on 15 Nov) changes this
  view: the supplier's name in the badge, how much is confirmed and how much waits, and
  the delivery day. Do not quote a label of the options view on stage before you saw it
  on the live card.

**The chip "Over budget" and its line** (beat 2). The chip shows when the total of the
option on the card is above the kitchen's budget warning for one order
(`gateway/service.py` `OVER_BUDGET_WARNING`, `engine/offers.py:220-221`;
`approval-card.tsx:368-381`). Under the chips, one line says it in numbers and names its
option: "Option A: ... ex VAT is ... above your kitchen's budget warning of ... per order. A
warning only." (`:423-431`, `:807`). The numbers are for the option whose total the card
shows, so while the card leads with option A they are option A's (#1970). When the
kitchen's limit is not known to the page it says "The total is above your kitchen's
budget warning per order. A warning only." The limit is the kitchen's own setting
(Settings, "Per order (ex VAT, €)"); the engine default is EUR 1,500
(`engine/params.py:24`). If option A is under the limit, the chip and the line are not on
the card: skip the sentence.

**The explanation on the card** (beat 2). Nemotron writes it from the checked decision
record, in its own model call; the line under it says "Written by Nemotron 3.5 Super VL
from the checked decision record · 1 call · ... s"
(`web/src/components/purchasing/proposal-explanation.tsx`). Two rules for the stage:

- **Point at it before the approve tap.** The card asks for the explanation only while
  the proposal waits (`approval-card.tsx:259-261`), so after the approval it is not on
  the card, and the panel then counts one call less.
- **Do not promise a sentence about a cheaper option.** The model gets that fact only when
  the decision record holds a cheaper alternative (`gateway/explanation_facts.py:11-39`).
  The proposal with confirmed stock only has none, so its explanation does not name one.
  Say what the text on the card says, not more.

The explanation is asked after the card is drawn, so it can come a moment later, or not at
all when the model is slow; the panel then says "1 model call".

**Where MongoDB Atlas shows on screen.** Three places, all in beats that exist:

- Beat 2, `/approvals`: beside the heading "To approve", the label "Live" and "MongoDB
  Atlas change stream" (`web/src/lib/live-events.tsx:86-101`, `web/src/pages/approvals.tsx:235-236`).
  It shows only while the live connection is up; if it is missing, skip its sentence.
- Beat 5, `/trust`: the badge "Audit log stored in MongoDB Atlas" under the heading "Tamper
  check", and the button "Verify audit chain" with its result line
  (`web/src/pages/trust.tsx:124-136`, `:158`).
- For questions and for the video, `/about`: the card "The data lives in MongoDB Atlas"
  (`id="about-atlas"`, `web/src/components/purchasing/atlas-card.tsx:115`), with "Other
  Atlas features in use" and the line "Change streams: ...".

**Which path answers** (beat 2 and 3). The deployed Buyer makes one model call per request:
Nemotron picks the products, and code makes every tool step (`deploy/compose.yaml:86`,
`agent/service.py:65`, `agent/single_pick.py`; #1257). The explanation on the card is one
more model call, made after the proposal exists; the panel counts both. A pick that
repeats within ten minutes comes from a cache: the panel then shows the pick as the step
"Code: Reused Nemotron’s pick for the same request from a few minutes ago" and counts no
model call for it (`agent/service.py:134-137`). So type the request
once in rehearsal and once on stage, at least ten minutes apart, or use the second wording
of "Before you go on stage", step 8. If the panel still shows it, say "the pick was
cached".
If the model does not answer, the card says "The Buyer model was not answering, so the
gateway's request parser made this proposal": say that, and skip the sentence about the
pick call.

**The receipt beat opens an order a person approved**: the milk order of beat 4, or an
older approved order if beat 4 failed. Never open the seeded delivery order (reference
`DEMO-1198`, EUR 178.09, eggs, cherry tomato and milk drink) for this beat: the demo seed
placed it, no person approved it, and it has no signed receipt by design (#1560, #1620).
Only the "Delivery beat" below opens that order, and there the script says the seed placed
it.

**Do not type** butter, eggs or salmon as a free request: those three still give the wrong
kind of product (clarified butter, scrambled egg mix, salmon cubes). Cheese, cream, oat
drink, chicken breast and lactose-free milk give the right kind. The one request in this
file with one of those words is `15 kg peanut butter` in beat 7. Type it exactly so: the
peanut rule refuses it before any product is picked, so no wrong product shows. No other
beat types butter, eggs or salmon.

## Shot list for the video

For Tymon. Seven shots, in this order. The milk request, from the typed sentence to the
approved order (shots 1 to 4), is inside the first 60 seconds. Each shot stays until its
text can be read. The numbers come from the screen.

1. `/requests`: the typed sentence `1,000 L lactose-free milk by Monday` in the box, and the button "Ask the agent".
2. `/approvals`, the milk card, folded: the line "Picked by Nemotron 3.5 Super VL · 1 call · ... s", the short explanation, the total with "Option A, recommended by the Buyer", and the coverage line "... of ... · ... not covered" (the litres confirmed and the litres that wait).
3. The same card after "Inspect (... options)": the "What Nemotron did" panel open, with "2 model calls, ... s, thinking off", the "Model:" and "Code:" steps and the line "Quantities and prices: the engine. Approval: you."
4. The same card: the main button "Approve option A: ...", the dialog "Approve this order?" with "Yes, approve ...", then the card with "Approved and recorded: ... Nothing is sent to the supplier."
5. `/orders`, the milk order: the block "Signed receipt" with "Approved by", "Signed total", and under "Supplier" the words "Nothing sent to the supplier yet" and the note "Recorded by the gateway. Nothing was sent to the supplier: its API has no order endpoint. The supplier has not accepted this order."
6. `/trust`: the badge "Audit log stored in MongoDB Atlas", the button "Verify audit chain", and the result line "Audit log intact: each of the ... entries carries the hash of the one before it".
7. Terminal, `python -m demo.second_agent --make-token`: line 9, "the agent tries to approve its own proposal: HTTP 403 HUMAN_SESSION_REQUIRED", and the last line that starts with "RESULT:".

The receipt's own claim is `supplier_outcome: NOT_SENT` (`gateway/signing.py:132`); the page
shows it as "Nothing sent to the supplier yet" (`web/src/pages/order-detail.tsx:88-89`).
Before the recording, mind the pick cache ("Before you go on stage", step 8): shot 3 must
show a "Model:" pick step. Make the milk request fresh after the last deploy (step 9), and
check the live card first: these labels show only after their deploy. The explanation is
on the card only before the approval, so shot 2 comes before shot 4.

## NVIDIA demo: five Nemotron jobs in 90 seconds (#1196)

**The sentence first:** "One model, five jobs, one buying loop, and it never sets a number."

Status: recorded on the live site on 2026-11-14 at 14:36 UTC, all nine steps ok, with the
model answering (`demo/out/3e9ea6c0044924f593e525a5b29b6f7a.webm` on Aron's laptop; `demo/out/`
is not in git). The Verda endpoint was slow that day (the menu read took about 70 s, the shelf
count about 100 s), so check `agent.ping` before the stage. Story A stays the main demo; this
one is for the NVIDIA judges, who must see Nemotron do core work live. Rubric points (the
sponsor's ask, answered in writing in `docs/submission.md`, "NVIDIA: Best Use of Nemotron"):
**Core** (Nemotron does core work, visibly in the demo), **Model** (which model and what it
does), **Why** (why it matters) and **Improved** (how we improved its outputs).

### Before the stage

1. **Does the model answer?** On the server, one bounded call (16 tokens, no retry):

   ```
   cd /opt/2brothers
   docker compose --env-file .env -f deploy/compose.yaml exec -T buyer python -m agent.ping --timeout 30
   ```

   `"status": "OK"` and a `latency_ms` under a few seconds: go. `"status": "ERROR"` (for
   example `TimeoutError` or `http_status` 503): every model beat below falls back. Say so
   on stage, beat by beat, or play the video (see "Fallback video" below).
2. **An open offer on Home** for beat 3: story A step 1 (`agent.seller --dry-run`, then
   `--apply`). Read the dry-run line: `made_by` must be `nemotron-3.5-super-vl`. With
   `--no-model` it is `rule`, and beat 3 then says "a rule picked it".
3. **Clear the inbox** (story A step 2), so the new proposals are easy to find.
4. **Photos on the laptop:** `demo/menu-photo.png` (beat 1), `agent/fixtures/shelf/demo-shelf.png`
   (beat 4), the prepared delivery note `agent/fixtures/receiving/demo-note.png` (beat 5).
5. **Tabs:** `/planner` (next week), `/requests`, `/` (Home), `/stock`, the demo delivery
   order in `/orders` (reference `DEMO-1198`, see "Delivery beat"), `/about`, and `docs/submission.md` at "How we improved its outputs".

### The script

| Time | Beat | What you tap | What you say | If the model does not answer | Rubric |
|---|---|---|---|---|---|
| 0:00 | Open | Home. | "One model, five jobs, one buying loop, and it never sets a number. Nemotron 3.5 Super VL on Verda." | - | Model |
| 0:05 | 1. Plan (#1136, #1140) | `/planner`, next week. "Plan from a menu photo", "Choose a file", `menu-photo.png`. Wait for "Nemotron 3.5 Super VL read ... dishes in ... s". | "The chef photographs next week's menu. Nemotron reads the dishes and the covers, and code matches each dish to a recipe. The engine sizes the ingredients. The proposal waits in the inbox." | The page says "The model is not answering right now. Plan the week by hand". Say: "The model is busy, so the chef plans by hand. Nothing is guessed." Press nothing more. | Core, Why |
| 0:20 | 2. Buy | `/requests`: type `1,000 L lactose-free milk by Monday`, "Ask the agent". Open the "What Nemotron did" panel. | "A chef writes a sentence, not product codes. One model call: Nemotron picks the products from a shortlist. Code does the search, the offer, the check and the request for approval, through the same audited MCP tools. The model has no approve tool, and the engine sets every quantity and price." | The card says "The Buyer model was not answering, so the gateway's request parser made this proposal". Say: "The model did not answer, so our parser made this one. Same engine, same numbers, no Nemotron." | Core, Model |
| 0:40 | 3. Sell | Home: the tile "Offer from Valio Aimo". Point at "written by Valio's selling agent (Nemotron 3.5 Super VL)". Do **not** press "Make a proposal". | "Nemotron in a second role, on Valio's side. Code builds a shortlist of substitutes; the model picks one and writes why. No price and no quantity come from the supplier." | The tile says "picked by rule, not by a model". Say: "Today a rule picked this one: the model was busy when the offer was made." | Model |
| 0:52 | 4. Count | `/stock`, "Count from a photo", "Choose a file", `demo-shelf.png`. Point at the five filled counts and the Edam "please count". | "Nemotron reads pack counts from the shelf. Code turns packs into litres and kilos. The Edam label did not match our stock list, so a person must identify it and count it. Unknown is never zero. Review duplicate rows before saving." Press "Save count" only if you decided to (see "Photo beat"). | The panel says "The photo was not read: ... You can still type the counts by hand." Say: "The model is busy; the counts are typed by hand." | Core, Why |
| 1:05 | 5. Receive | The demo delivery order in `/orders` (reference `DEMO-1198`; its page says "Placed by the demo seed", and it has no signed receipt by design), "Choose a delivery note photo", the prepared note. Point at the short and missing lines and the EUR to claim. | "Nemotron reads the delivery note. Plain code compares it with the order: this line is short, this one is missing. A person checks before stock changes." | The panel says "The note could not be read: ... Check the delivery by hand." Say: "The model is busy; the driver's note is checked by hand." | Core, Why |
| 1:15 | Numbers | `/about`, the card "The Buyer agent runs on Nemotron 3.5 Super VL" (runs, model calls, prompt and completion tokens, model seconds). Then the table "How we improved its outputs" in `docs/submission.md`. | "Measured, not claimed. These are this kitchen's Buyer runs, counted from the endpoint's own usage field. And we measured before we tuned: thinking on is worth about 5,000 euro a week where the model decides numbers. In the product the engine decides them, so thinking is off. On the old tool loop that cut 2,251 completion tokens to 289, and every request finished on the first try. Today the Buyer is one model call per request." | The card counts only runs that happened. If it says "No runs counted yet", show the measured table only. | Model, Improved |

Two honest limits to say if asked: the About card counts the Buyer's runs only (the photo
reads are counted in the container log, `python -m agent.usage`); and all photos are prepared
test photos, not real phone photos.

### Fallback video

```
python -m demo.record_demo --story nvidia
python -m demo.record_demo --story nvidia --note-photo PATH-TO-THE-PREPARED-NOTE
```

The prepared note is `agent/fixtures/receiving/demo-note.png` (#1198); without `--note-photo`
the receive beat is skipped. Record it as soon as `agent.ping` answers OK. The video goes to `demo/out/`.
The recorder types `1,000 L lactose-free milk by Monday`. A run of the same sentence in the
ten minutes before it gives a cached pick, and the "What Nemotron did" panel in the video
then shows no model call. Wait ten minutes after the last milk request, then record; and
wait ten minutes after a recording before the stage run (story A, "Before you go on
stage", step 8).
The recorder **never approves**: it refuses `--approve`, never accepts the offer and never
presses "Save count". A beat whose model did not answer says so in its caption (the parser
or a rule answered), or the step prints `SKIP` with the page's own words; record again when
the model answers.

**What it leaves in demo-kitchen:** up to two WAITING proposals, the menu-photo plan proposal
(only when a matched dish needs an order) and the Buyer's proposal for
`1,000 L lactose-free milk by Monday`. The photo reads store nothing but one audit entry
each. Clear the proposals afterwards, on the server (the first line lists, the second removes):

```
cd /opt/2brothers
docker compose --env-file .env -f deploy/compose.yaml run --rm -T --no-deps gateway python -m demo.clear_inbox
docker compose --env-file .env -f deploy/compose.yaml run --rm -T --no-deps gateway python -m demo.clear_inbox --apply
```

### Still open for this demo

- [x] Run every beat once on the live site with the model answering (2026-11-14, 14:36 UTC).
- [x] Record `python -m demo.record_demo --story nvidia` into `demo/out/` (same run).
- [x] Beat 2: the "What Nemotron did" panel (#1197, merged in #1279).
- [x] Beat 5: the prepared delivery-note photo and the EUR to claim (#1198, merged in #1314).
- [x] Beat 1: the menu photo read live in the recording (#1136).
- [ ] Rehearse once by hand on the stage laptop, and clear the inbox afterwards.

## Recall beat: the recalled coffee is on our shelf (#358)

In the three-minute script this is beat 6, about 10 seconds: point at the stored alert and
say one sentence. It shows robustness (criterion D). The steps below are the long form,
for a judge who asks. The recall list is read through Context.dev; that prize track was
dropped (#1388), so the script does not sell it.

One-shot on the live kitchen: the first check records the alert, and it stays. Do not
press the button in rehearsal there.

| Step | What you do | What the judge sees | What you say |
|---|---|---|---|
| 1 | Open `/stock`. Point at Kulta Katriina coffee. | The coffee 461332 with 3.253 kg on hand. | "This kitchen has this coffee on the shelf." |
| 2 | Open `/approvals`. Press "Check recalls now". Wait (the live scrape took 30 s on 14 Nov; a slow answer falls back to the recording and the panel says so). | The recall panel: "Kulta Katriina ... is recalled", the Food Authority notice "Suodatinkahvissa vierasesineriski" of 6 March 2026 with its link, "In stock: 3.253 KG", and "No open order holds it. New orders leave it out." | "The Finnish Food Authority recalled batches of this coffee. It is on our shelf; the kitchen knows before anyone orders it again." |
| 3 | Optional: on `/requests` ask for `5 kg Kulta Katriina filter coffee`. | The coffee is left out with the reason `BLOCKED_BY_RECALL`. | "And the agent cannot order it. A person checks the packs first." |

The alert needs no open proposal: the check matches the notices to the kitchen's stock and
recipes too (`store/recalls.py` `context`). The hold of an open proposal and its replacement
basket (`python -m demo.recall_demo`) need a product whose ordering is open at Valio; for the
coffee it closed on 12 Nov, so that part is not shown this weekend.

**Dry run before pressing again (#1076).** `python -m demo.recall_dry_run` builds the
kitchen as the check does and matches the recorded notices; it writes nothing (no alert,
no hold, no audit entry). It exits 0 when only 461332 would alert. On the server, through
the container:
`cd /opt/2brothers && docker compose --env-file .env -f deploy/compose.yaml run --rm -T --no-deps gateway python -m demo.recall_dry_run`.
Result 2026-11-14, local seed (`demo.seed`, today 14 Nov, the full Valio catalog): 23
products (19 in stock, 23 in recipes), 38 notices, one alert: `possible` 461332 (same brand,
"kahvi, perinteinen"), in stock 3.253 KG and in three recipes. Nothing else matches. The
live kitchen has not been dry-run yet: run the command above and paste its last two lines
here. A product added to the live stock by hand (for example an Elovena oat drink, a
Barebells bar or a Göran's kebab) would give a `possible` alert of its own.

## Photo beat: Nemotron VL counts a shelf (#373)

Live since 2026-11-14. This is the beat that shows the vision half of Nemotron 3.5 Super VL
on the screen. It takes about 20 seconds. Put it after beat 5, or use it in place of beat 6.

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

## Delivery beat: the note is short, and the app says what to claim (#1198)

**Not yet run on the live site.** The Verda model endpoint was overloaded on 14 Nov (#1135).
Run it once in rehearsal before you put it on stage. Put it after beat 5 (the order and its
receipt): order, delivery, check. About 20 seconds.

**Which order.** A fixed demo order, reference `DEMO-1198`, made by `demo/delivery_order.py`
(the seed places it too). It never changes, unlike the order beat 4 places. Three Valio lines
at the catalog prices of 13 Nov, EUR 178.09 ex VAT. Its order page shows "Placed by the demo
seed" where a signed receipt would be: no person approved it, so it has no receipt (#1560,
#1620). Say so when you open it: "the demo seed placed this order, so it has no receipt;
an order a person approves has one". This is the only beat that opens this order. Never
use it for the receipt beat (beat 5).

| Product | Ordered | On the note | Status | To claim |
|---|---|---|---|---|
| 463982 Kieku barn eggs L, 180 pcs | 3 KI at EUR 31.01 | 1 KI | SHORT 2 KI | EUR 62.02 |
| 460838 Cherry tomato 4 kg Finland | 1 KI at EUR 29.06 | not on the note | MISSING 1 KI | EUR 29.06 |
| 463335 Valio Eila 3 % milk drink 1 L | 40 ST at EUR 1.40 | 40 ST | RECEIVED | EUR 0.00 |

The screen shows: "3 cases short: €91.08 to claim from Valio Aimo".

**Find the order on demo morning.** On the server (`/opt/2brothers`):

    docker compose --env-file .env -f deploy/compose.yaml run --rm -T --no-deps gateway python -m demo.delivery_order

It prints `order <id>  reference DEMO-1198  open /orders/<id>` and writes nothing. If it
says "no demo delivery order yet", run it once with `--apply` (one order, one audit entry
`demo_delivery_order_placed`; a second run finds the same order). In the web app: Orders,
the order of EUR 178.09 with eggs, cherry tomato and milk drink. Open `/orders/<id>` in a tab.

The order has no proposal, so it has no delivery day: the stock screens never count it as
on order. It is marked `approved_by: demo-seed`.

**Cut-off, lead time and delivery reliability (#1453).** The approvals screen shows a
cut-off and a reliability per line. Where Valio and the supplier terms give none, demo
values fill in, marked "(demo)": invented, never Valio's numbers. The seed writes them; to
write only them (safe to run again):

    docker compose --env-file .env -f deploy/compose.yaml run --rm -T --no-deps gateway python -m demo.delivery_terms --apply

Without `--apply` it prints the counts and writes nothing. Only proposals made after it
show the values.

**Which photo.** `agent/fixtures/receiving/demo-note.png` (drawn by
`agent/fixtures/receiving/make_demo_note.py`; it says "SYNTHETIC TEST NOTE" on it). Copy it
to the phone or laptop before the demo. `demo-note.reply.json` is the answer a correct reader
gives; it is written by hand, not recorded from the live model.

**What you do.**

1. Open the demo order (`/orders/<id>`). Scroll to "Photo of the delivery note".
2. Press "Choose a delivery note photo" and pick `demo-note.png`.
3. Point at the lines: eggs "Short delivery", ordered 3, received 1; cherry tomato "Missing";
   milk drink "Received". Each short line says "To claim: €...".
4. Point at the total: "3 cases short: €91.08 to claim from Valio Aimo".
5. Press "Copy the claim". The toast says nothing was sent. Paste it in a note app if you
   want to show the text: the order id, each line with the price and the amount, the total.

**What you say.** "The delivery came. The chef takes a photo of the paper note. Nemotron
reads it, and plain code checks it against the order: two egg cases are missing, and the
tomatoes did not come at all. The money is not the model's: the app takes the price from the
order the chef approved. Three cases, 91 euros to claim from Valio. One tap copies the claim.
Valio's API has no claim route, so a person sends it. Nothing changes stock until a person
counts."

**If it fails.** The panel says why ("the vision model did not answer in time; nothing was
read, check the delivery by hand"); nothing is stored but one audit entry. Say: "the model is
busy; the check is plain code and works the same by hand", and go on. Without the model the
beat cannot be shown live; do not fake it. The tests run the same photo through the gateway,
the worker and the matcher with the hand-written reply
(`demo/tests/test_delivery_order.py`): 3 KI short, EUR 91.08.

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

- Milk request through the web, an earlier run on 14 Nov: answer in 12 s. Status READY, two
  lines: 698 ST of 463380 (stock confirmed) and 302 ST of 464237 (cheapest per litre, stock
  not confirmed). EUR 2,242.30 ex VAT, EUR 2,545.01 total. These are that run's numbers,
  not today's: Valio's confirmed stock moved later that day (51 L, `docs/submission.md`
  "Buyer read context").
- The portion cups (463203, 7.55 EUR per litre) are left out with a reason: "confirmed in
  stock, but ... 5.8 times the cheapest". That is the certainty premium limit (#700).
- `/llms.txt`, `/.well-known/agent-card.json`, `/gateway/openapi.json`: all answer 200.
- Conformance kit, run against the server: 11 checks passed, 0 failed, 1 skipped
  (12 results in that run, #609). The kit has 13 checks now (C01 to C13,
  `gateway/conformance.py`); they were not run against the server again for this text.
- Golden scenarios, a different count: `python -m gateway.scenarios` runs 13 scenarios
  (S01 to S13) on frozen test data, 13 PASS. They do not run against the live site.

Time to order: the agent path was about 12 to 15 s plus two taps (our own runs on the old
tool loop). With one model call, three 200 L requests on the live site took 2.5 to 3.8 s
(`agent/README.md` "Live measurements, 14 November 2026"); the 1,000 L request was not
timed again. The manual
webshop time is **an estimate, not a measurement** (Aron, 14 Nov): nobody timed it. Say it
like this, also on the last slide: "By hand in a webshop this order is a search, a
comparison of several products, a stock check and a basket: we estimate 5 to 10 minutes,
and it depends on the restaurant and the person. With the agent it is one sentence, about
15 seconds, and two taps." Never say "measured" for the manual time.

## If something fails

- **The page does not load:** a deploy is running. Wait 20 s and reload (see step 3).
- **No tile on Home:** the offer was used in rehearsal. Make a new one (step 1). If the
  seller prints only `NO_SUBSTITUTE` or `ALREADY_OFFERED`, there is no new shortage to offer
  for: skip beat 1 and start at beat 2, the sponsor's milk request.
- **"Make a proposal" gives a REJECTED proposal:** nothing can be delivered for that date
  any more. The offer stays open. Say: "Valio's stock moved since the offer; the gateway
  checks again and does not pretend", and go on with beat 2.
- **The milk card says the parser made it:** the model did not answer. Say so, and go on:
  the engine and the numbers are the same.
- **Option A cannot be approved** (the total moved, or nothing is confirmed): say "the
  gateway refuses a yes for an old total", and show beat 5 on an older order that a person
  approved. Never on the seeded order `DEMO-1198`.
- **The recall panel is empty:** the script does not press "Check recalls now". If you
  must press it, the read takes about 30 s and waits up to 45 s, then answers from the
  recording and says so.
- **Nothing works:** play the fallback video and talk over it. Milk story:
  `demo/out/fallback-2026-11-14-final-with-approval.webm`. A story-A video comes from
  `python -m demo.record_demo --story offer --approve` (it uses up the open offer). The
  NVIDIA video comes from `python -m demo.record_demo --story nvidia` (approves nothing; see
  "NVIDIA demo", "Fallback video").

## Not in the demo

Voice approval, the recipe builder, the menu planner and the settings pages. They exist or
are planned, and none of them scores in three minutes.

## Open items for this script

- [x] Fallback video: `python -m demo.record_demo --approve` records it with the approval
      (run 14 Nov 04:20 UTC, all nine steps ok). Record the final one after the last change.
- [x] Manual webshop time: stated as an estimate of 5 to 10 minutes, not measured (#295).
- [ ] Buyer path through the web still fell back to the parser at 02:22 UTC on 14 Nov;
      confirm it says the Buyer model before rehearsal.
- [ ] Recall beat: `CONTEXT_DEV_API_KEY` on the server; the coffee 461332 in the demo
      kitchen's stock (no seed needed, #358). One-shot: do not press
      "Check recalls now" in rehearsal on the live kitchen.
- [x] Tamper check beat: live on `/trust` (#747, #818).
- [x] Choose button on the option card (#403, #843): the big request can be approved.
- [ ] Delivery beat (#1198): place the demo order on the server
      (`python -m demo.delivery_order --apply`) and run the beat once on the live site
      when the Verda endpoint answers (#1135). Target: under 10 s.
- [ ] Claude Desktop as the second agent (`docs/byoa.md`): run it once before the demo.
