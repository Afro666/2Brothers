"""How much more a kitchen pays for stock the supplier confirms.

The main plan takes confirmed stock first, because a delivery that is certain is worth
more than a cheaper one that may arrive short. Without a limit it took any confirmed
stock: live on 2026-11-14 a request for 1,000 L of lactose-free milk was filled with 2 cl
portion cups at 7.55 EUR per litre while the cheapest milk cost 1.30. This module sets the
limit: a confirmed offer is used only when its price per measure is at most
`certainty_premium_max` times the cheapest orderable price per measure.

An offer over the limit is left out with a reason a person can read. It comes back when
leaving it out would make the order short: dear stock is better than no stock, and the
plan then carries the warning `CERTAINTY_PREMIUM_HIGH`.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:   # offers.py imports this module
    from engine.offers import Offer

DEFAULT_MAX = Decimal("3")
CENT = Decimal("0.01")


def over_premium(usable: list["Offer"], measure: str,
                 max_ratio: Decimal | None = DEFAULT_MAX) -> dict[str, str]:
    """`{product_id: reason}` for the confirmed offers that cost too much per measure.

    `usable` are the offers that can be ordered for the date. The cheapest of them, with
    or without confirmed stock, is the reference. `max_ratio` None switches the limit off.
    An offer with no confirmed stock is never in the answer: it is not paid for certainty.
    """
    if max_ratio is None or not usable:
        return {}
    cheapest = min(o.price_per_measure for o in usable)
    if cheapest <= 0:
        return {}
    out: dict[str, str] = {}
    for o in usable:
        if o.available is None:
            continue
        ratio = o.price_per_measure / cheapest
        if ratio > max_ratio:
            out[o.product_id] = (
                f"confirmed in stock, but {o.price_per_measure.quantize(CENT)} EUR per {measure} is "
                f"{ratio.quantize(Decimal('0.1'))} times the cheapest ({cheapest.quantize(CENT)} EUR per "
                f"{measure}); the limit is {max_ratio.normalize():f} times")
    return out
