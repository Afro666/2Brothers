# Why it is built this way

The choices behind the Trusted Kitchen Buyer gateway, in plain words. Field-level rules are
in [`contract.md`](contract.md); who decided what, and when, is in
[`decisions.md`](decisions.md). The live API is at `/api/docs` on the demo site.

## One gateway, two doors: MCP and OpenAPI

- An agent talks to the gateway over **MCP** (`/mcp`): `search_products`, `get_offer`,
  `simulate_order`, `request_approval`, `place_order`, `order_status`. Any MCP client works:
  our Nemotron Buyer, Claude Desktop, or a script.
- A person's app, or any developer, uses the same gateway over **REST** with an
  **OpenAPI** spec (`/api/openapi.json`, browsable at `/api/docs`).
- Both doors call the same code. The guards below cannot be skipped by picking the other
  door.

## The gateway owns the numbers, not the model

- The model chooses products and explains. It never sets a quantity, a price or a total.
- The purchasing engine (`engine/`) sizes every line: demand times cover days, plus safety
  stock, minus stock on hand and on order, rounded up to whole sales units. Money is
  `Decimal`, never a float.
- Every line carries a `why` sentence and reason codes from the engine, so a person can
  check the number without reading code.

## A person approves every order

- The Buyer agent can propose. Only a signed-in person can approve, and only with a
  human session: an API key or the agent's token gets `HUMAN_SESSION_REQUIRED`.
- The approval names the exact total the person saw (`expected_total`). If the price or
  stock moved since then, the gateway refuses with `TOTAL_MISMATCH` and sends nothing.
  The person sees the new figure and decides again.
- Stock that the supplier does not confirm blocks the approval (`STOCK_UNKNOWN`), and a
  recalled product blocks it (`BLOCKED_BY_RECALL`).
- There is no auto-approve. A budget limit is a warning on the approval, never a reason to
  skip it.

## Every write can be repeated safely

- Every write takes an `idempotency_key`. The same key with the same body returns the
  stored result; the same key with another body is `IDEMPOTENCY_KEY_REUSED`.
- No adapter retries a supplier `POST` on its own. When a send result is unknown, the
  order is `UNCONFIRMED` or `SENT_READ_FAILED` and a person resolves it: an order is never
  placed twice by a retry.

## Unknown is never zero, and never safe

- A price, a stock level, a delivery fee or allergen data that nobody gave us is `null`,
  never `0` or "none".
- Missing allergen data is not "allergen-free": the line gets `ALLERGEN_DATA_MISSING`.
- Stock that the supplier reports as a sentinel (999999) is unknown stock, not plenty.
- Unknown supplier terms mean the engine does not pad an order to free delivery.

## Everything is in the audit log

- Each step (request, offer, approval, send, result) is one audit event with who, what,
  when and the figure shown. The log is a hash chain: the Trust screen checks it and
  shows if any row was changed after the fact (`store/audit.py`, `verify_chain`).

## What is live and what is mocked

| Part | State |
|---|---|
| Valio Aimo product, price and availability API | Live: Valio's own mock API for the challenge |
| Valio order placement | Valio's mock API; no real order reaches Valio |
| Catalog, prices and stock in the demo | From that API and the challenge datasets |
| Kitchen history (covers, stock counts, orders) | Synthetic, from `env/` |
| Buyer agent | Nemotron 3.5 Super VL on Verda |
| Database | MongoDB Atlas |
| Recall monitor | Context.dev monitors |
| Other suppliers | `manual` and `csv` adapters: the kitchen's own price list, stock unknown |

## The path to production

- A supplier joins by implementing one **adapter** with five calls: `catalog`,
  `price(products, date)`, `availability(products, date)`, `place_order`, `order_status`.
  Valio Aimo is the first live adapter.
- Suppliers that have no API start as `manual` or `csv` adapters. The guards and the
  approval flow are the same.
- A kitchen's own agent can use the gateway with a kitchen API token, scoped to what it
  may do (`kitchen:propose`, not `kitchen:approve`).
