# engine/

Deterministic purchasing engine (#18). Pure functions, no I/O: the gateway feeds it
catalog rows, Valio offers and kitchen stock; the Buyer agent only reads its output.

- `packs.py`: measure per sales unit. `units[]` is in base units (often ST), so litres and
  kilos come from `catalogPrice / comparisonPrice`; such a size is flagged
  `PACK_SIZE_DERIVED`. No way to convert raises `PackDataError` (stop and ask).
- `offers.py`: `plan_request(need, measure, offers, date, params)` for a request like
  "1,000 L by Monday". Excludes passed cut-offs, sales blocks and late dates; confirmed
  stock first, then the cheapest unknown-stock offer (flagged); a shortfall is reported.
  Gives a cheaper all-unknown alternative when there is one.
- `quantity.py`: `replenish(item, params)`: periodic order-up-to (lead time + review days +
  safety stock) against position (on hand + on order). An empty stock count is sized as if
  empty and marked urgent. `cover_limit` checks extra quantity against the cover ceiling.
- `demand.py`: stock-out adjusted demand (cap set by the user, default 1.8x), safety stock.
- `urgency.py`: tiers; unknown sorts with urgent.
- `params.py`: per-kitchen settings, all user-editable (`KitchenParams.from_dict`).

Every line has `reason_codes` from `docs/contract.md` and a deterministic `why` sentence.

Tests: `python -m pytest engine -q` (golden scenarios S01, S02, S05, S08-S12).
