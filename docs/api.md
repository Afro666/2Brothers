# Product API (design draft): restaurants and suppliers

Status: draft, 2026-11-13 23:30. Owner: Aron. When the team agrees, the routes move into
`docs/contract.md` (its own PR). One REST API (OpenAPI) plus an MCP server for agents;
both call the same gateway code.

## Who calls what

```
Kitchen systems (POS, inventory)  --push stock, covers-->  Trusted Kitchen Buyer API
Kitchen users (web app, phone)    --menus, approve----->         |
Buyer agent (Nemotron, MCP)       --propose only------->         |
                                                                 |--- supplier adapters --> Valio Aimo API
Suppliers (Valio, others)         <--orders, demand-----         |                      --> CSV / e-mail supplier
                                  --confirm, offers---->
```

## Auth and the trust rule

- Every organisation (kitchen or supplier) gets API keys with scopes.
- Scopes: `kitchen:read` (every GET on the kitchen side, including products, recipes
  and suppliers), `kitchen:write` (POST, PUT, DELETE on stock, menus, products, recipes,
  suppliers), `kitchen:propose`, `kitchen:approve`, `supplier:read-orders`, `supplier:confirm`,
  `supplier:demand`.
- **`kitchen:approve` is only on a human user session**, never on an API key or the
  agent's MCP token. The Buyer can propose; it cannot approve. That is the product's trust
  rule in one line.
- Every mutation takes an `Idempotency-Key` header; every call is in the audit log with who
  (user, key or agent) and what.

## Kitchen side (`/v1/kitchens/{kitchen_id}/...`)

| Method | Path | What |
|---|---|---|
| POST | `/stock-counts` | Push a stock count (POS/inventory/manual); null = unknown, never zero |
| GET | `/stock` | Current stock and position (on hand + on order) |
| CRUD | `/products` | Own products (not in a supplier catalog) |
| CRUD | `/recipes` | Recipe = products x qty per portion; allergens rolled up |
| PUT | `/menu-plans/{week}` | Menus per day: recipe + expected covers |
| GET | `/demand?from=&to=` | Future need per product and day (from menu plan and history) |
| CRUD | `/suppliers` | Suppliers and their terms (free delivery, fee, order days, cut-off, lead time) |
| POST | `/proposals` | Ask the Buyer: free text ("1,000 L milk by Monday") or a demand window |
| GET | `/proposals/{id}` | Lines with "why", one block per supplier, simulated totals, warnings |
| POST | `/proposals/{id}/approve` | Human only. Body: `expected_total` per supplier block |
| POST | `/proposals/{id}/reject` | Human, with a reason (feeds the env and the engine) |
| GET | `/orders`, `/orders/{id}` | Status: `SENT`, `CONFIRMED`, `PARTIAL`, `UNCONFIRMED`, `NOT_SENT` |
| PUT | `/sharing` | Consent: which supplier may see this kitchen's forecast |
| GET | `/audit` | Every step: who, what, when, the figure shown |

## Supplier side

**We call them (adapter contract).** Each supplier is one adapter with the same five calls:
`catalog`, `price(products, date)`, `availability(products, date)`, `place_order`,
`order_status`. Valio Aimo is the live adapter; `manual` and `csv` adapters use the price
list the kitchen entered (stock unknown, order goes out by e-mail or PDF).

**They call us** (`/v1/suppliers/{supplier_id}/...`):

| Method | Path | What |
|---|---|---|
| GET | `/orders` | Orders kitchens approved for this supplier |
| POST | `/orders/{id}/confirm` | Confirm full, partial (with lines) or reject |
| GET | `/demand?from=&to=&product=` | Consented forecast demand across kitchens, per product and day |
| GET | `/demand/shortage-risk` | Products where forecast demand is above the supplier's stated availability |
| POST | `/offers` | Proactive offer to a kitchen (substitute, promotion); it shows up as a suggestion, never an order |

## Webhooks (both sides)

`proposal.ready`, `proposal.approved`, `order.sent`, `order.unconfirmed`, `order.confirmed`,
`price.changed`, `recall.alert` (Context.dev), `demand.changed` (supplier).
