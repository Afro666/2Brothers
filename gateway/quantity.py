"""One guard for quantities that arrive in a request.

`Decimal(str(value))` accepts an exponent such as `1e-50000000`. Stored as a Decimal
that is harmless, but `f"{x.normalize():f}"` would try to write out tens of millions of
digits. The guard also runs where quantities are computed (menu plans, supplier-offer
demand, recall replacements), which can carry more than three decimals, so the bound is
generous: nine places keeps every real quantity and limits the digits the formatting
helpers ever see.
"""

from __future__ import annotations

from decimal import Decimal

MAX_DECIMAL_PLACES = 9


def too_many_places(number: Decimal) -> bool:
    """True when a finite Decimal has more than `MAX_DECIMAL_PLACES` decimal places."""
    return number.is_finite() and number.as_tuple().exponent < -MAX_DECIMAL_PLACES
