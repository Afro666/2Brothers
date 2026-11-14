"""Free-delivery threshold (MOV): pad only with lines the engine wants (S06, docs/plan.md).

Rules from Aron's production purchasing engine (patterns only, no company data):
- The threshold is a free-delivery threshold, not a wall: paying the fee is fine.
- Pad only with lines the engine already wants for a coming order, never with a product
  "because it fills the gap".
- The smallest single line that closes the gap first; else the smallest lines together.
- A line that would spoil before it is used is never pulled forward.
- Pad only when the fee saved is more than the cost of holding the goods earlier.
- Unknown terms (no threshold or no fee): never pad.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")


@dataclass(frozen=True)
class Wanted:
    """A line the engine wants for a coming order (e.g. an addable row with a quantity)."""

    product_id: str
    name: str
    quantity: Decimal               # in sales units, as the engine sized it
    unit: str
    unit_price: Decimal             # ex VAT
    keeps_until_used: bool = True   # False: shelf life too short to pull it forward
    holding_cost: Decimal = Decimal(0)   # cost of holding it from now until it is used

    @property
    def value(self) -> Decimal:
        return (self.quantity * self.unit_price).quantize(CENT, ROUND_HALF_UP)


@dataclass(frozen=True)
class Padding:
    add: tuple[Wanted, ...]
    total: Decimal                  # draft total after padding, ex VAT
    saves_fee: Decimal
    reason_codes: tuple[str, ...]
    why: str


def _eur(x: Decimal) -> str:
    return f"{x.quantize(CENT, ROUND_HALF_UP):f} EUR"


def pad_to_free_delivery(draft_total: Decimal, *, threshold: Decimal | None, fee: Decimal | None,
                         wanted: list[Wanted]) -> Padding:
    def none(why: str) -> Padding:
        return Padding((), draft_total, Decimal(0), (), why)

    if threshold is None or fee is None:
        return none("Delivery terms unknown: no padding.")
    gap = threshold - draft_total
    if gap <= 0 or fee <= 0:
        return none("Free delivery already reached.")
    usable = sorted((w for w in wanted if w.keeps_until_used and w.quantity > 0),
                    key=lambda w: (w.value, w.product_id))
    pick = next(([w] for w in usable if w.value >= gap), None)
    if pick is None:
        pick, got = [], Decimal(0)
        for w in usable:
            pick.append(w)
            got += w.value
            if got >= gap:
                break
        if got < gap:
            return none(f"Nothing the engine wants closes the {_eur(gap)} gap: pay the {_eur(fee)} delivery fee.")
    holding = sum((w.holding_cost for w in pick), Decimal(0))
    if holding >= fee:
        return none(f"Closing the {_eur(gap)} gap costs {_eur(holding)} in holding, more than the "
                    f"{_eur(fee)} fee: pay the fee.")
    added = sum((w.value for w in pick), Decimal(0))
    names = ", ".join(f"{w.quantity.normalize():f} {w.unit} {w.name}" for w in pick)
    why = (f"Added {names} ({_eur(added)}), already wanted for the next order: closes the "
           f"{_eur(gap)} gap and saves the {_eur(fee)} delivery fee.")
    return Padding(tuple(pick), draft_total + added, fee, ("MOV_PADDED",), why)
