# Junction 2026 – challenges

Sources: the Junction platform challenge list (hackjunction.app/participate/45, pasted
2026-11-13), Spread's public pages (spread.bahnexpress.com: /llms.txt, /how, /judging),
the Exa docs index (docs.exa.ai/llms.txt), the Context.dev docs index
(docs.context.dev/llms.txt), the Cala docs index (docs.cala.ai/llms.txt), and the MariaDB
vector docs (mariadb.com/docs/server/reference/sql-structure/vectors/vector-overview).
The "Tech Challenges" tab on the platform is not in here yet.

Team constraint: **no hardware.** The hardware track is listed at the end, short.

---

## 1. Overview (software only)

Fit = how well it suits us (3 devs, 4 coding agents, no hardware, 48 h). 5 = best.

| # | Challenge | Sponsor | Track | 1st prize | Judged by | Fit |
|---|---|---|---|---|---|---|
| A1 | Trusted Trade Agents | Valio Aimo | Agentic AI | **€4,000** (2nd €2k, 3rd €1k) | Jury | 5 |
| A2 | Spread (car transport sim) | Bahn Express | Agentic AI | €2,000 (€1k, €500) | **Leaderboard** → top 10 → jury | 5 |
| A3 | Break the Agent (RL environment) | AfterQuery | Agentic AI | **€3,000** + work trial (€1.5k, €500) | Rubric + judges rerun | 4 |
| A4 | Earned Trust in AI Code | Tieto | Agentic AI | €2,000 (€1k, €500) | Jury | 4 |
| A5 | Decode the Noise | Hostinger | Agentic AI | €2,000 (€1k) + hosting | Jury | 3 |
| A6 | The Internet Butler | Exa | Agentic AI | $2,500 + $5k credits (… ) | Jury, live queries | 3 |
| F1 | Make Unicorns Real | Cala | FinTech | ~€5,000 hackathon travel + €1k credits | Jury (4×25%) | 3 |
| F2 | Personal Economic Trainer | S-Pankki | FinTech | €2,000 Airbnb card (€1k, €500) | Jury | 4 |
| H1 | Equal Care Across Finland | AstraZeneca | Healthcare | €1,000 (€750, €250) | Jury | 2 |
| H2 | Beyond the Clinic | Aalto University | Healthcare | TBA | Jury | 2 |
| I1 | Make Blueprints Talk | Stoa | AI Infra (Verda) | €1,000 + work trial (€750, €250) | Jury | 2 |
| D1 | The Web Is Your Real-Time Database | Context.dev | Data | €2,000 (€500, swag) | Jury | 3 |
| D2 | Rethinking Recruitment | City of Espoo | Data | €1,500 (€1k, €500) | Jury | 2 |
| D3 | Wikipedia Through Time | MariaDB | Data | €1,000 + €1k UpCloud + certs (€500, €250) | Jury | 3 |

### Side prizes we can stack on top (MLH)

Any project can also enter these. They are cheap to add if planned from the start.

| Prize | What it needs | Easy to add to |
|---|---|---|
| Best Use of **Entire** (mini projector) | Use Entire Sessions, Graph, Brain, Trails in our workflow | Any project; strong with A4 |
| Best Use of **ElevenLabs** (earbuds) | Voice in the product | F2, A6, A1 (voice approval) |
| Best Use of **Gemini API** (swag) | Gemini as a model in the product | Any |
| Best Use of **MongoDB Atlas** (M5Stack kit) | Atlas as the database | Any |
| Best Use of **Tiger Data** (Stream Deck Mini) | Postgres/Timescale, time series | A2 (event log), F2 (transactions) |
| Best Use of **Vultr** (prizes) | Deploy on Vultr | A2 (final runs on a stable cloud box) |
| Best Use of **Solana** (hardware wallets) | Solana transactions | Hard to fit; skip |
| DEV Writing Challenge ($100) | Blog post on DEV after the event | Any |

---

## 2. Key dates (from Spread's /judging page; Junction's own schedule wins if they differ)

- Fri 13 Nov 18:00 – opening ceremony
- Fri 13 Nov 19:30 – hacking starts
- Fri 13 Nov 23:59 – **preliminary submission due** on the Junction platform
- Sat 14 Nov 12:00 – Junction platform submissions open
- Sun 15 Nov 10:00 – **final submissions close**
- Sun 15 Nov 10:30–14:00 – review / jury time
- Sun 15 Nov 14:00 – final ceremony; challenge winners at 15:10

---

## 3. Agentic AI track

### A1. Trusted Trade Agents – Valio Aimo

**Prizes:** 1st €4,000 · 2nd €2,000 · 3rd €1,000 (biggest software prize pool).

**Context.** Valio Aimo is a food-service wholesaler (part of Valio, €2.4B revenue). It serves
20,000+ professional kitchens, with 25,000 products from 700 suppliers and 350 staff. It plans a
B2B marketplace. For Junction, the challenge mocks **today's webshop and backend**, not the
marketplace.

**Question.** How can a wholesaler let *external* autonomous purchasing agents find products,
compare offers, place orders and get the right approval, without exposing real systems,
confidential data or the roadmap? Build on **open, verifiable standards**, not one platform's
black box.

**Core (must have):**
1. **Product, price & availability lookup:** a structured way for an external agent to search
   and retrieve what is available and at what price.
2. **Inquiry → order:** a defined interaction from requesting price & availability to placing an
   order. Fixed prices, no negotiated quote.
3. **Permission & human-approval management:** what the agent may decide alone, and what
   goes to a human for sign-off.

**Optional (not needed to win):**
- Delivery time & sustainability comparison (delivery reliability, certificates / labels in the
  webshop; category-level CO₂ ranges as a stretch).
- Substitution and exception handling when the exact request cannot be met (not scored as core:
  last year's Zero-Fail Logistics covered it).
- Traceability and explainability: a human-readable record of what the agent did and why.

**Example request:** a hotel chain's agent sends *"I need 1,000 litres of lactose-free milk by
Monday. Find an option that meets our requirements based on price and availability."* The
system returns products, prices and availability in structured form. The agent orders within
its authority, or sends it to a human for approval.

**Framing they stress:** this is *not* "replace the webshop with a chatbot". It is how a European
wholesaler becomes safely and openly readable by agents, before someone else's platform defines
that interface.

**Our notes.**
- Natural stack: an **MCP server** (open standard) + an OpenAPI spec over a mock catalog, a
  policy engine (spend limits, categories, new-supplier rules), an approval inbox, and an
  audit log. Possibly A2A / Agent Cards for discovery, signed order intents.
- Proven pattern: the agent drafts an order, simulates the total, and sends only after a human
  says "yes" to that exact total (the server rejects the send if the total moved).
- Stack prizes: ElevenLabs (voice approval call), MongoDB/Gemini.
- Questions for the booth: is there a mock dataset / catalog? Which standards do they like (MCP,
  A2A, UCP/ACP)? How do they score?

---

### A2. Spread – Bahn Express

**Prizes:** 1st €2,000 · 2nd €1,000 · 3rd €500.

**What it is.** Run a simulated car-transport company for one week in Finland. Freelance drivers
drive each car on its own wheels. Your system quotes dealers and posts drives as gigs in a
drivers' app. **Score = gross margin** (dealer payments − driver fees − refunds − costs).
**At least 90% of orders must arrive on time**, or you are not ranked.

**Start:** create the team at `spread.bahnexpress.com/join` with event code **`spread-kmu9z6`**.
Give the agent `spread.bahnexpress.com/llms.txt`. Docs: `/handbook`, `/rules` (wins on
conflicts), `/api`, `openapi.json`, `/kit/` (TypeScript: Bun or Node 22.18+, `bun starter.ts`;
Python 3.9+: wheel, `spread-starter`). Env: `SPREAD_URL=https://spread.bahnexpress.com`,
`SPREAD_KEY=<team key>`.

**The world (from /how):**
- One week Monday → next Monday, 30 Finnish towns, realistic drive times. ~**1,000 price
  requests** per week.
- A request = one car from pickup to delivery (a trade-in = two cars, one price). Up to 3 speeds:
  same day, next business day, within 3 business days; each has a deadline and a public list
  price by distance. Each request shows a *typical driver fee* (a hint, not a cost).
- You quote per option. The dealer picks yours or the competitor's. Quoting very high = decline.
  **Unanswered requests make that dealer less willing later.**
- **Competitor:** quotes on every request. Levels ≤6: near list price. Level 7: ~25% above,
  level 8: ~40% above. Varies by lane and day. If you win most of a dealer's work, it lowers its
  prices for that dealer. You never see its prices; infer from wins/losses.
- **Drivers:** freelance. You post a gig with an opening fee and a rise schedule. Driver cost =
  home → pickup distance + road time + public transport home; evening, weekend, private address
  and early morning cost more. **Drivers learn your pattern**: if fees always rise, they wait.
  Near pickup they wait less. Drivers can drop bookings; you can release a driver for a fee.
- **Deadlines** 20:00 on business days; Saturday short, Sunday closed. Drivers only book gigs
  they can finish in time, so raise fees early. Warning 3 h before last possible pickup with no
  driver.
- **Late refunds:** ≤2 h late 10%, 2–24 h 25%, ≤2 business days 50%, later 100%. Undelivered =
  penalty of 2× price.
- **Dealer notes** (pickup windows, early closing, plates) are enforced whether you read them or
  not. Failed visit ≥ €25 + repost. Premium cars need experienced drivers, manual cars the right
  licence, low-charge EVs a charging stop; violations = fines. Dealers can reroute/cancel after
  you win.
- **Combining cars:** one gig can carry several cars in a fixed stop order, up to 12 h driving.
  A driver already nearby on your car: extra car costs only added time and fares. **Direct
  offers:** send a gig to one driver for 10 min at your fee; max 3 offers per driver per day,
  none 23:00–07:00.
- **Levels 1–8**, each adds a rule: 1 posting (fixed fee, every quote wins) · 2 rising fees ·
  3 multi-car gigs + direct offers · 4 competitor · 5 notes, plan changes, weather · 6 surprise
  events (regional competitor outages, driver flu) · 7 shortage (⅓ drivers, dearer competitor:
  choose which cars to win) · 8 trust (severe shortage, one secret weekday where the competitor
  quotes far lower, late orders erode dealer trust).
- **Practice:** your system controls the clock (create week, advance, read events, act).
  Deterministic: same seed + actions = same result.
- **Final:** real time, live event stream. Limits **20 actions/s, 50 reads/s** (429 = free
  retry). If you disconnect, the week goes on without you.

**Schedule (Helsinki time):** ranking rounds Fri 19:30; Sat 00:00, 09:00, 12:00, 15:00, 18:00,
21:00; Sun 00:00, 03:00, 06:00. **Test finals Sat 14:00 and 20:00** (registration paused 13:45,
19:45). **Final Sun 08:00**, level 8, ~34 min, own copy of one secret week. Registration closes
**07:30**. Start before 08:00, kit starters run with `--final`. Restart at once if it crashes.
Use a stable machine; **a cloud machine near Stockholm** is recommended.

**How you win:** top 10 by margin present to the jury (5–10 slides or a short video). After top
10, margin no longer counts. Jury: **Elegant** (few parts, each with a reason), **Clear** (we can
follow how it decides), **Creative** (an unexpected view of dealers/drivers/week), **Robust**
(unseen weeks, many-week results, survives restarts, slow network, surprises). Bahn's own best
system plays every round: beat it.

**Submit:** preliminary Fri 23:59, final Sun 10:00 on Junction: submission hash (team page), code
link, presentation. For each major idea: what, why, effect (margin and on-time share with/without,
on the same weeks). Plus final result, best ranking round, what failed, what would break it.

**Our notes.**
- Objective score, deterministic simulator, an llms.txt for agents, kits in TS and Python. Very
  well suited to 4 coding agents running experiments in parallel.
- Natural split: pricing (quote model, competitor inference per dealer/lane), dispatch (fee
  schedule, direct offers, multi-car bundling), and an eval harness (many seeds, A/B per idea,
  dashboard). The deck almost writes itself from the A/B table.
- Downside: Sunday 07:30–08:35 must be awake and on a stable cloud box (Vultr side prize fits).
- Hint: ask the Bahn booth for hints; they offer them.

---

### A3. Break the Agent – AfterQuery

**Prizes:** 1st €3,000 + direct to final-stage work trial + merch · 2nd €1,500 + merch · 3rd €500.

**Task.** Build a **reinforcement-learning environment** that today's best agents struggle in.
Any setting: game, scientific sim, software task, real-world process. Needs: a clear goal, actions,
observations, and a **checkable reward**. Run a frontier agent in it and compare with a **stronger
reference run** that you can demonstrate and reproduce. Show where and why the agent fails. The
difficulty must come from decisions, with the info and tools needed available. They provide the
**agent harness and model credits**. Judges try to **reward-hack** it.

**Stretch / tiebreaker:** train a smaller model on experience from the env and show it improves.

**Rubric (100 p):**
- **The gap (30):** frontier agent consistently below your reference run; both reproducible.
- **Meaningful difficulty (30):** mistakes explained and tied to decisions; no withheld info,
  trick wording, impossible timing or broken tools.
- **Reward integrity (25):** survives exploit attempts; doing nothing or stopping early scores
  ~0; doing the task well is the best way to score.
- **Craft (15):** rules make sense; judges run the eval from the README with **one command**.

**Judging run:** 10-min demo. Judges rerun with the standard harness: your reference run, 3 agent
runs, a do-nothing baseline, a stop-early baseline. 15 min of exploit hunting.

**Our notes.** Pure software, clear rubric. The "reference run" can be a scripted solver /
expert policy. Good settings: long-horizon business processes with hidden state (e.g. a purchasing
or dispatch sim), debugging a broken repo, spreadsheet reconciliation. Ask the booth for the harness
format early.

---

### A4. Earned Trust in AI Code – Tieto

**Prizes:** 1st €2,000 · 2nd €1,000 · 3rd €500.

**Question.** How does AI code review keep pace with AI-written code while a **named human stays
accountable** for every change? Picture: an agent's 200-line PR opens with its own story – what,
why, what else it touches, how sure the AI is about each part. The reviewer checks a story instead
of hunting problems. (Context: agent tokens passed human tokens Feb 2026, 7.3 T by Aug, OpenRouter
/ a16z.)

**Task.** Design an AI code-review **concept**, then show it works: concept, principles, reference
implementation and technology considerations, across frontend, backend and security. Challenge
line-by-line review. Balance risk, hallucination, transparency, confidence and quality.

**Expected from each team:**
- Concept: what the "PR review factory" should follow; key principles and how they balance the
  five factors.
- Illustrate on **one sample agent-written change with its requirement ID**: what the AI found,
  **what it refused to decide, and why**.
- How the evidence lets a **named human accept without a full read**.
- Failure modes seen; a short decision log. Synthetic or cleared data only.

**Deliverables:** concept card (recommendation, principles, trade-offs, limits) · live walkthrough
of where trust comes from · lessons log · demo video / presentation.
**Out of scope:** a finished product, model training, vendor selection.

**Our notes.** We live this exact workflow (agents writing PRs, gates, merge only the gated head,
review agents). Strong fit with the **Entire** MLH prize (Trails = issue/PR + agent review).
Risk: "concept" challenges reward storytelling; less engineering depth needed.

---

### A5. Decode the Noise – Hostinger

**Prizes:** 1st €2,000 · 2nd €1,000. All three winners: 1 year hosting + domain, swag, social
spotlight.

**Task.** An AI tool that analyses text, social content or web-traffic patterns to detect
coordinated propaganda, bot amplification or bad-actor behaviour. Form: API, dashboard, classifier
with an explainable verdict, or a monitoring service for site owners. **Must be live on Hostinger
infrastructure with a public URL** by the end. They care about the **strength and honesty of the
detection logic, incl. false positives**, more than a polished front end.

**Our notes.** Hostinger offers VPS (Docker template + Compose manager) and managed Node.js
hosting from GitHub. Ask the booth whether they give free credits. Data is the hard part (need
labelled bot/propaganda data).

---

### A6. The Internet Butler / Your Personal Assistant – Exa

**Prizes:** 1st $2,500 + $5,000 Exa credits + hoodies + Exa TRMNL dashboard · 2nd $1,500 + $3,000
credits + hoodies + macropad · 3rd $500 + $1k credits + hoodies. Every team with a working Exa
project gets credits. (The challenge text still has template placeholders for amounts.)

**Task.** A personal agent that takes tedious tasks off people's hands: finds what matters across
the web, works out what needs to happen, gets it as close to done as possible, leaves final
approval to the user. **Demo on a real case.** Examples: rent increase legality, missed benefits,
special occasions, errands, business info, travel disruption.

**Judging:** use of Exa for info **not in training data** · usefulness to a **specific group of
real people** · **clear sources** · originality · demo works on **live queries, incl. the judges'
own**.

**Exa API (docs.exa.ai):** Search, Contents, Answer (cited), Highlights, Snapshot (page at a
datetime), Deep Search, Exa Agent (research/list-building, structured output), Websets (verified
enriched datasets, monitors), Monitors API (recurring search → webhook), Batch API, hosted MCP at
`mcp.exa.ai/mcp`.

**Our notes.** Many teams will pick this. Win by narrowing to one group (e.g. international
students in Finland: Kela benefits, rent rules, residence permits). Stacks with ElevenLabs.

---

## 4. FinTech track

### F1. Make Unicorns Real – Cala

**Prizes:** winner: each member becomes a "Cala Comet" (~€5,000 for a team of 4: one hackathon of
choice per month for 3 months, travel + stay covered) + €1,000 Cala credits + merch. Runner-up:
€500 credits + merch.

**Task.** A product on Cala's data that solves a real need for founders, investors or both. Focus
beats breadth. Slush starts right after: aim for something they could use the next day. Must lean
on Cala's **structured, sourced data on companies, funding rounds, investors and their
connections**.

**Judging (25% each):** real need · execution end-to-end · originality · Cala is core.

**Cala API (docs.cala.ai):** Query (typed JSON rows + entities), Search (markdown answer with
citations), Search Entities (fuzzy by name), Lookup Entity (by external id), Retrieve Entity (by
UUID), Entity Introspection (field schema). OpenAPI at `api.cala.ai/openapi.json`. MCP at
`api.cala.ai/mcp/` with an `X-API-KEY` header (from a third-party mirror; check). Integrations:
Claude Desktop, Agent Skill, n8n.

---

### F2. Personal Economic Trainer – S-Pankki (S-Bank)

**Prizes:** 1st €2,000 Airbnb gift card · 2nd €1,000 · 3rd €500.

**Context.** S-Bank: Finland's 4th largest bank, 3.5 M customers; S-mobiili used weekly by 1 in 3
Finnish adults. No Finnish bank yet lets customers chat with their own financial data.

**Task.** On a **large synthetic transaction dataset** modelled on real S-Bank data, build an AI
experience to chat with your own money: "How much did I spend on taxis last month?", "What kind of
spender am I?", "What is safe to spend this week?", "How much could I save by cutting dining out
20%?".

**What they value:**
- **Pedagogy: three baskets** – mandatory & regular (rent), mandatory & irregular (broken washing
  machine), everyday leakage (coffees). Help people see where money really goes.
- **MyData spirit:** users explore freely, not fixed charts picked by the bank.
- Open-data benchmarks (e.g. Statistics Finland).
- Output: **mobile app or a web app embeddable in a mobile app.**
- Financial literacy, especially young adults.

**Our notes.** Clear, well-scoped, data provided. Text-to-SQL over transactions + a basket
classifier + "safe to spend" forecast. Stacks: ElevenLabs (voice), Tiger Data (time series),
Gemini.

---

## 5. Healthcare track

### H1. Equal Care Across Finland – AstraZeneca

**Prizes:** €1,000 · €750 · €250. Key insights at the AstraZeneca stand **Fri 20:00**.

**Task.** An AI-powered, nationwide solution for equal and effective cancer care in Finland.
Must: **identify the gap** (access / outcome differences), **locate it in the pathway**
(detection, referral primary → specialist, diagnosis, treatment start), and – most important –
**recommend concrete, evidence-based actions** at national or account level.

**Possible formats:** AI analyst explaining indicator trends + actions · monitoring dashboard with
recommendations · early-warning system for delays · intervention-impact simulation.

**Minimum:** reliable public data and/or mentor insights, **sources for every claim** · cover at
least one indicator of **Goal 3 of the national cancer strategy** · actionable proposals · a
working demo (slides alone are not enough).

### H2. Beyond the Clinic – Aalto University

**Prizes:** TBA.

**Task.** A product that helps people **stay well at home after TMS depression treatment**
(maintenance treatment). Anything: natural stimuli, phone, music, games, light, AI. Ideally
**closed loop**: sense how someone is doing → respond with something that helps → learn what works
for that person.

---

## 6. AI Infrastructure track (Verda)

### I1. Make Blueprints Talk – Stoa

**Prizes:** €1,000 + work trial at Stoa · €750 · €250.

**Task.** A program that answers natural-language questions about **construction drawings and BIM
models**, accurately and **verifiably**: the answer shows where in the drawing it came from so a
human can check in seconds. Dataset: real technical drawings in many formats and languages +
example questions. They want approaches **next year's frontier models won't make obsolete**:
hybrids of frontier models, computer vision, 3D, geometry, small fine-tuned models.

**Our notes.** Hardest problem on the list, smaller prize. GPU via Verda.

---

## 7. Data track

### D1. The Web Is Your Real-Time Database – Context.dev

**Prizes:** €2,000 + swag · €500 + swag · swag.

**Task.** A product that **reacts to the live web**: turn live web data into decisions, actions
or experiences. Inspiration: GPU rental price comparison, "Yapper" leaderboard of founders on X,
cve.now (new CVEs), Ferndesk (onboarding personalised with company data and brand assets).

**Context.dev API (docs.context.dev):** Scrape (many formats), Map URLs, Crawl → Markdown, Search
the web, Answer (sourced, your JSON shape), Parse a file; Brand intelligence (logos, colours, company
details, socials, styleguide extraction); People search & enrich; Company search; News search (by
query, company, domain, ticker, ISIN); Batches (up to 100k URLs); **Monitors** (scheduled watches,
`change.detected` webhooks).

### D2. Rethinking Recruitment – City of Espoo

**Prizes:** €1,500 · €1,000 · €500.

**Question (only text given):** how can recruitment and matchmaking events organised by the City
of Espoo help companies and talent find and connect with each other in a relevant way, now that
AI-generated job-search materials and AI-assisted recruitment are common?

### D3. Wikipedia Through Time – MariaDB

**Prizes:** 1st €1,000 cash + €1,000 UpCloud credits + MariaDB certification voucher per member
(learn.mariadb.com, value $750) · 2nd €500 · 3rd €250. Winners credited on mariadb.org blog.

**Task.** A Wikipedia tool that does not exist yet (or is underused), **MariaDB at the core**.
- **RAG track** (most teams): MariaDB native vector search → grounded, source-cited answers (e.g.
  research assistant for the history of Finland).
- **SVT track** (advanced): system-versioned tables → what an article said on a date, edit wars,
  how an event's story was rewritten.
- **Both** (very advanced): "what did Wikipedia say about this in 2015, and what changed?"

**Judging:** creative use of MariaDB RAG and/or SVT · technical execution and scalability across
the provided datasets · usefulness to readers/editors · design and demo. SVT / both get extra
credit for ambition.

**MariaDB tech:** `VECTOR(N)` type, `VECTOR INDEX` (modified HNSW), up to 16,383 dims, Euclidean
and cosine; `VEC_DISTANCE` uses the index only with `ORDER BY … LIMIT` (a bare `WHERE` threshold
scans everything). Vector search since 11.7 GA.

---

## 8. Hardware track by Arduino (skipped: no hardware)

| Challenge | Sponsor | Prizes | One line |
|---|---|---|---|
| The Green European Renaissance | Arduino | Ventuno Q per member · UNO Q 4G + kits · kits | Edge AI on Arduino UNO Q for local green problems |
| AI Glasses for Everyone, Everyday | Meta | Ray-Ban Meta per member | First-person-view use case; web apps and Device Access Toolkit mobile apps also count |
| Stop Simulating, Start Moving | Ignite Next × Intel | €5,000 · €3,000 · €2,000 | SO-101 arm: VLA policy + Anomalib brick inspection, OpenVINO on Core Ultra |
| The Robot Teleoperation Challenge | Rokoko | Smartgloves II + SDK (€4,990) · Smartsuit Pro II · Smartgloves I | Mocap suits/gloves controlling robot hands/arms/humanoids |
| Aaltonomous Humanoid | Aalto University | €2,000 + lab visit; top ~5 run on real G1 | Unitree G1 sorts coloured blocks; **simulation first** (Isaac Sim), Docker policy server |

Note: **Aaltonomous Humanoid** and **Meta glasses** (web app) can be done mostly in software.
Aaltonomous is judged in simulation first, and the robot is theirs.

---

## 9. Shortlist (Claude's view, to discuss)

1. **A1 Valio Aimo** – biggest prize, clear core, pure software, a pattern we know well
   (agent drafts, human approves a stated total).
2. **A2 Spread** – objective leaderboard, built for agents, easy to split three ways, deck comes
   from A/B data. Cost: Sunday 07:30 wake-up.
3. **A3 AfterQuery** – big prize, strict rubric, harness provided.
4. **F2 S-Pankki** – well scoped, data provided, consumer demo, stacks voice.

Stack in every case: **Entire** (workflow), **Gemini** or **ElevenLabs** where natural.

## 10. Questions to ask at the booths (Fri evening)

- Valio Aimo: mock catalog/API provided? Preferred standards (MCP, A2A, agent payments)? Weighting of core vs optional?
- AfterQuery: harness format and model credits? Can the reference run be a scripted solver?
- S-Pankki: dataset size/schema, access time? Can we use any LLM?
- Bahn: hint on the competitor model; is a Vultr/Stockholm box OK for the final?
- Hostinger: free hosting credits for teams?
- All: is one project allowed in several challenges? (usually one main challenge + MLH side prizes)
