"""Partial fill (#288): order the confirmed stock now, and say what happens to the rest.

"51 L certain" alone reads as a failed order. This option answers "does the kitchen get
its milk?" in two parts, each with its own sentence and the engine's own numbers:

- NOW: the stock the supplier confirms for the requested date, and nothing else.
- The rest, in this order:
  (a) LATER: the earliest later delivery date on which an offer shows confirmed stock
      and an open cut-off;
  (b) HOLD: what no confirmed stock covers waits until the supplier confirms stock.

Unknown stock (None, the sentinels) is never counted as covered, now or later. There is
no partial option when confirmed stock covers the need, or when nothing is confirmed for
the requested date (then there is nothing certain to order now).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal

from engine.offers import Offer, PlanLine, _exclude_reason, _fill, _n

ZERO = Decimal(0)
CODE_ORDER = ("PARTIAL_STOCK", "LOT_SIZE_ROUNDED", "PACK_SIZE_DERIVED", "ALLERGEN_DATA_MISSING", "EVENT_LINE")


@dataclass(frozen=True)
class FillPart:
    kind: str                           # NOW, LATER or HOLD
    quantity: Decimal                   # in measure: what this part covers or holds
    measure: str
    deliver_on: date | None             # None for HOLD: no date is known
    lines: tuple[PlanLine, ...]         # empty for HOLD
    total: Decimal | None               # ex VAT; None for HOLD: no price until stock is confirmed
    why: str


@dataclass(frozen=True)
class PartialFill:
    need: Decimal
    measure: str
    now: FillPart
    rest: tuple[FillPart, ...]          # LATER and/or HOLD; together they cover `remaining`
    remaining: Decimal                  # need minus what NOW covers, in measure
    reason_codes: tuple[str, ...]
    why: str                            # the sentence of NOW, then of each rest part


def _covered(lines: list[PlanLine], by_id: dict[str, Offer]) -> Decimal:
    return sum((ln.quantity * by_id[ln.product_id].pack.size for ln in lines), ZERO)


def _items(lines: list[PlanLine], by_id: dict[str, Offer]) -> str:
    return ", ".join(f"{_n(ln.quantity)} {ln.unit} of {by_id[ln.product_id].name}" for ln in lines)


def _total(lines: list[PlanLine]) -> Decimal:
    return sum((ln.total for ln in lines), Decimal("0.00"))


def _can_come_later(o: Offer, measure: str, requested: date) -> bool:
    """Confirmed stock on a later date, and its own cut-off is still open."""
    return (o.pack.measure == measure and not o.sales_block and o.cutoff_passed is False
            and o.available_date is not None and o.available_date > requested
            and o.available is not None and o.available > 0)


def partial_fill(need: Decimal, measure: str, offers: list[Offer], requested: date,
                 *, event: bool = False) -> PartialFill | None:
    """The partial option for a request, or None when confirmed stock covers the need or
    nothing is confirmed for `requested`. `event` marks every line EVENT_LINE (S05)."""
    if need <= 0:
        raise ValueError("need must be positive")
    by_id = {o.product_id: o for o in offers}

    def mark(lines: list[PlanLine]) -> list[PlanLine]:
        return [replace(ln, reason_codes=(*ln.reason_codes, "EVENT_LINE")) for ln in lines] if event else lines

    confirmed = [o for o in offers if o.pack.measure == measure and o.available is not None
                 and _exclude_reason(o, requested) is None]
    now_lines, remaining, _ = _fill(need, measure, confirmed, confirmed_first=True)
    if not now_lines or remaining <= 0:
        return None
    now_lines = mark(now_lines)
    covered = need - remaining
    now = FillPart("NOW", covered, measure, requested, tuple(now_lines), _total(now_lines),
                   f"Order {_n(covered)} {measure} now for {requested.isoformat()}: {_items(now_lines, by_id)}, "
                   f"all the stock Valio confirms for that date, EUR {_total(now_lines)} ex VAT.")

    rest: list[FillPart] = []
    left = remaining
    later = [o for o in offers if _can_come_later(o, measure, requested)]
    if later:
        day = min(o.available_date for o in later)
        lines, short, _ = _fill(left, measure, [o for o in later if o.available_date == day], confirmed_first=True)
        if lines:
            lines = mark(lines)
            got = min(left, _covered(lines, by_id))     # a lot rounded up still covers only what is left
            lead = (f"The remaining {_n(left)} {measure}" if short <= 0
                    else f"{_n(got)} {measure} of the remaining {_n(left)} {measure}")
            rest.append(FillPart("LATER", got, measure, day, tuple(lines), _total(lines),
                                 f"{lead} can come on {day.isoformat()}: {_items(lines, by_id)}, "
                                 f"confirmed in stock for that date, EUR {_total(lines)} ex VAT."))
            left = short
    if left > 0:
        rest.append(FillPart("HOLD", left, measure, None, (), None,
                             f"Hold the {'last' if rest else 'remaining'} {_n(left)} {measure} until Valio "
                             f"confirms stock: no offer shows {'more ' if rest else ''}confirmed stock "
                             "for a later delivery date."))

    codes = {"PARTIAL_STOCK"} | {c for part in (now, *rest) for ln in part.lines for c in ln.reason_codes}
    return PartialFill(need, measure, now, tuple(rest), remaining,
                       tuple(c for c in CODE_ORDER if c in codes),
                       " ".join(part.why for part in (now, *rest)))
