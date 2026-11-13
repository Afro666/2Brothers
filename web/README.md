# web: purchasing UI component kit

The UI building blocks for the restaurant purchasing agent, filled with mock
data from the milk case in `docs/valio-data.md`. The real screens are built
on top of these.

Stack: Vite, React 19, TypeScript (strict), Tailwind CSS 4, radix-ui,
class-variance-authority, lucide-react, TanStack Router, vitest +
Testing Library. Node 22 or newer.

## Run it

```
cd web
npm install
npm run dev
```

Open http://localhost:5173/kit.

Other scripts: `npm run build`, `npm run typecheck`, `npm test`.

## Components

All in `src/components/purchasing/`. Generic primitives (button, card,
dialog, table …) are in `src/components/ui/`.

| Component | What it shows | Where it is used in the app |
|---|---|---|
| `AppShell` | Sidebar nav (Requests, Approvals, Orders, Audit log, Catalog); a top bar with a drawer on a phone | Every screen |
| `StatusBadge` | Order state (NEEDS_APPROVAL, REFUSED, PLACED, NOT_SENT, UNCONFIRMED, SENT_READ_FAILED) with a tooltip that says what it means | Orders, Approvals, Audit log |
| `UrgencyBadge` | Guests affected today / runs out before next delivery / due now / can wait / unknown (unknown is styled and sorted as urgent) | Requests, Orders |
| `OrderLinesTable` | Product, pack, quantity, unit price ex VAT, € per L/KG, stock ("unknown" for the 999999 and 9999999999 sentinels), available date, order cut-off (red when passed), and the line's "why" | Order detail, approval detail |
| `MovProgress` | Order value against the free-delivery threshold, with the gap in € | Order detail, Approvals |
| `OfferCompare` | Good / better / best substitutes: price per L, fat %, pack, organic, delivery, trade-offs | Requests (when the first choice cannot cover the ask) |
| `ProductCard` | Names, allergen chips (CONTAINS vs MAY CONTAIN; missing data shown as unknown), labels, temperature, CO2 per kg, delivery reliability | Catalog, product drawer |
| `ApprovalCard` | Request summary, totals ex/incl VAT, the mandate reasons, approve/reject; approve names the exact total | Approvals inbox |
| `AuditTimeline` | Every step in time order (request, search, offer, simulate, mandate check, approval, order) with its reason | Audit log, order history |
| `ChefRequestBox` | Free-text ask plus covers and date fields | Requests |
| `MandateSummary` | Spend limits, excluded allergens, accepted labels, substitution rules | Approvals, settings |

## Data

- Types: `src/types.ts`. Shaped after the Valio fields in `docs/contract.md`
  plus our own order, approval and audit concepts, so gateway JSON can
  replace the mocks later.
- Mocks: `src/mocks/milk-case.ts`. The product codes, the €/L of 462775
  and 462921, the 51 ST stock, the sentinels and the closing times are from
  the live API. Other prices, the MOV threshold, the mandate and the audit
  times are placeholders, marked in the file.
- Every component that compares a time takes `now` as a prop. The kit uses
  `MOCK_NOW` (Fri 13 Nov 2026 21:00 Helsinki), so the passed cut-offs stay
  passed in tests and demos.
- Times are always shown in Helsinki time (`src/lib/format.ts`).

## Screens and data access

- Routes are in `src/router.tsx`, one page per route in `src/pages/`. The nav
  follows the viewer's side: Kitchen (Chef, Buyer) or Valio (Valio planner).
  The role picker in the sidebar switches it; there is no login
  (`src/lib/role.tsx`).
- Screens get data only through `useApi()` (`src/api/`). `Api` in
  `src/api/types.ts` lists every call. `createMockApi()` serves the milk case
  from memory. `createHttpApi()` is the real gateway: its methods answer
  `NOT_SERVED` until the gateway serves the route.
- The app uses the mock unless `VITE_GATEWAY_URL` is set and
  `VITE_USE_MOCKS=false`.
- The contract is snake_case with money as decimal strings; `src/types.ts` is
  camelCase with numbers. Convert only in `src/api/` (`mapMoney` in `map.ts`).
- `useAsync` (`src/lib/use-async.ts`) with `LoadingState`, `ErrorState` and
  `EmptyState` covers the three states every screen has.

## Rules the components keep

- A missing value is unknown, never zero, "none" or "allergen-free".
- Stock sentinels never show as a number.
- Colours come from the tokens in `src/index.css` (light and dark).
- Works at 390 px: tables become stacked rows on a phone.
