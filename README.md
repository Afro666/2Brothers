# Trusted Kitchen Buyer

Junction 2026, team 2Brothers (Aron, Tymon, Maciek). Challenge: **Valio Aimo, Trusted Trade Agents**.

A purchasing agent that a wholesaler gives to its kitchen customers. The kitchen says what it
needs, or plans its menus. The agent (the **Buyer**) finds products, checks live prices, stock
and order deadlines, and proposes an order. A person approves it. Every step is in an audit log.
With the kitchen's consent, the wholesaler sees the forecast demand of all its customers before
the orders come in.

- **Live demo:** https://31-22-104-201.sslip.io (no password; anyone with the link is the demo person)
- **For an outside agent:** [`docs/byoa.md`](docs/byoa.md) (curl and MCP), `/llms.txt`, `/gateway/docs`
- **Why it is built this way:** [`docs/choices.md`](docs/choices.md)
- **Three-minute demo script:** [`docs/demo.md`](docs/demo.md)

## The flow

| Step | What happens | Where |
|---|---|---|
| 1. Request | "1,000 L lactose-free milk by Monday", or "propose an order for this week's menu plan" | web, REST, MCP |
| 2. Lookup | Catalog search, then live Valio price and stock for the shortlist only | `gateway/`, `store/` |
| 3. Order at a fixed price | The engine sizes every line; the offer is a signed snapshot, valid 15 minutes | `engine/`, `gateway/signing.py` |
| 4. Approval | A person approves the total they saw; the gateway re-checks live and refuses if anything moved | `gateway/service.py` |

## What we can show, not only say

Each of these is a command or a page, not a slide.

| Claim | How to check it |
|---|---|
| The model never invents a quantity | The Buyer's tools take product codes only; the gateway sizes lines from the stored need. `python -m gateway.conformance --base-url https://31-22-104-201.sslip.io/gateway --token <token>` asks for 99,999 and gets the need's quantity (check C04). |
| An agent cannot approve, cancel or act for another kitchen | The same kit, checks C06 to C10; the table is at Settings > Permissions and every "never" row has a test (`gateway/tests/test_permissions.py`). |
| Price and stock claims are verifiable | Every offer is signed (EdDSA). Public key: `/gateway/.well-known/jwks.json`. `python -m gateway.verify_offer --base-url ... --offer offer.json` fails on a changed line or price. |
| An order has a signed receipt | Every placed order carries `receipt`, signed with the same key: the order, the offer hash the person approved, the exact total, the lines, who approved, and that nothing was sent to the supplier. `python -m gateway.verify_offer --base-url ... --receipt order.json` fails on any change. |
| A "yes" covers exactly one order | The approved order stores the offer hash; placing another offer is `APPROVAL_MISMATCH`; a moved price is `TOTAL_MISMATCH`; a repeated send returns the first order. |
| Unknown is never zero | Valio's "stock unknown" value, an empty stock count and missing allergen data are shown as unknown and never as stock, zero or "free from" (`docs/scenarios.md`, S01, S04, S09). |
| The forecast is true | Reports > Forecast vs actual: 10 weeks of predictions made the Monday before, against what happened. Our engine misses 4.5% a week, a weekday average 6.7% (all 20 demo kitchens: 4.7% against 11.4%). |
| The golden scenarios pass | `python -m gateway.scenarios` runs S01 to S13 from [`docs/scenarios.md`](docs/scenarios.md) and prints the pass table. |
| The live site is healthy | `python -m demo.rehearsal` checks the public site in one table (add `--buyer` for one real Buyer request). |

## Two sides

- **The kitchen** has suppliers with its own terms, own products, recipes with yield, menu plans,
  stock counts, and settings for how the engine sizes orders. Valio is one supplier; a second
  supplier with a manual price list works too. It decides which supplier may see its forecast,
  and every change of that consent is in the audit log.
- **The wholesaler** sees, per product and day, the forecast demand of the kitchens that agreed,
  against its own availability: what will run short, and what to buy.

## What is real and what is not

- **Real:** Valio's challenge APIs for price and availability, and Valio's catalog (17,546
  products) in MongoDB Atlas; the Buyer is NVIDIA Nemotron 3.5 Super VL on Verda, with a
  deterministic parser as the stated fallback; food recalls come from Context.dev.
- **Ours, because Valio's challenge has no order endpoint:** placing the order, approval and
  audit. An approved order is "placed in our gateway"; a supplier confirmation is the next step.
- **Synthetic:** the kitchens' history (20 kitchens, August to November, built from real Valio
  products and prices) and the demo kitchen's supplier terms. The pages say "Sample data" where
  a screen is not on live data yet.
- **Earned auto-approve** exists and is off: a kitchen can switch it on only after four weeks of
  its own approvals, for routine orders under its limit. Everything else always waits for a person.

## Repository

| Folder | What |
|---|---|
| `engine/` | Pure purchasing logic: packs and lot sizes, confirmed stock first, partial fill, safety levels (newsvendor), demand from menu plans, forecast accuracy |
| `gateway/` | FastAPI gateway and MCP server: proposals, approval, signing, tokens, sign-in, webhooks, kitchen and supplier routes, conformance kit |
| `agent/` | The Nemotron Buyer and its worker |
| `store/` | MongoDB Atlas: catalog, search, orders, hash-chained audit log, history, forecasts |
| `signals/`, `monitor/` | Weather, holidays, seasons; recall monitor (Context.dev) |
| `env/`, `demo/` | Kitchen simulation, forecast and ordering backtests, demo data, rehearsal check |
| `web/` | The app: requests, approvals, planner, stock, suppliers, forecast, trust, settings |
| `docs/` | Contract between areas, scenarios, decisions, choices, demo script |

## Run it

```
python -m pip install -e ".[test,signals]"
python -m pytest gateway engine demo agent env store signals -q
python -m gateway.scenarios
cd web && npm ci && npm test
```

The gateway needs `VALIO_API_KEY` and `MONGODB_URI` (see `.env.example`; keys never go in git).
Deploy is Docker Compose on a Verda instance through GitHub Actions (`deploy/`).

## How we worked

Three people and their coding agents. One task is one issue, one branch, one PR. Every PR is
reviewed by an automatic Opus review; what it finds becomes an issue for a person or for the
fix agent. Rules for people and agents: [`CLAUDE.md`](CLAUDE.md). Decisions with their reasons:
[`docs/decisions.md`](docs/decisions.md). All Junction challenges we looked at: [`challenges.md`](challenges.md).
