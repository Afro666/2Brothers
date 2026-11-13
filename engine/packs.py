"""How much of a measure (L, KG, ST) one sales unit holds, and rounding to what can ship.

Trap (S12): `units[]` is in base units, often ST, and says nothing about litres or kilos;
the 10 kg carrot sack is "1 ST, KI 1". The honest measure comes from
catalogPrice / comparisonPrice, cross-checked against units[] where both exist.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

COUNTABLE = {"ST", "KI", "PAK", "BAG", "RAS", "PRK", "BOT", "CS", "KRT", "KRS", "PAL"}


class PackDataError(ValueError):
    """Pack data is missing or contradicts itself: stop and ask, never guess."""


@dataclass(frozen=True)
class PackInfo:
    sales_unit: str
    measure: str                 # unit the size is in: L, KG or the base unit
    size: Decimal                # measure per sales unit
    lot_size: Decimal            # smallest order step, in sales units
    derived: bool                # True when the size came from the price ratio


def _units(product: dict) -> dict[str, Decimal]:
    return {u["unitId"]: Decimal(str(u["sizeInBaseUnits"])) for u in product.get("units", [])}


def pack_info(product: dict, *, price: Decimal | None = None,
              comparison_price: Decimal | None = None, comparison_unit: str | None = None,
              measure: str | None = None) -> PackInfo:
    """`product` is a catalog row; prices are per sales unit and per comparison unit.

    `measure` is the unit the request is in. When it is the base unit, units[] answers.
    Otherwise the price ratio does (a 5 x 1 L case at 10.97, 2.19 per L, holds 5 L).
    """
    sales, base = product["salesUnit"], product["baseUnit"]
    units = _units(product)
    lot = Decimal(str(product.get("allowedLotSize") or "0.01"))
    if sales in COUNTABLE and lot < 1:
        lot = Decimal(1)
    in_base = units.get(sales)
    want = measure or comparison_unit or base
    if want == base and in_base:
        return PackInfo(sales, base, in_base, lot, derived=False)
    if want == sales:
        return PackInfo(sales, sales, Decimal(1), lot, derived=False)
    if price is None or comparison_price is None or comparison_unit != want:
        raise PackDataError(f"no way to convert {want} to {sales} for product {product['id']}")
    if comparison_price <= 0 or price <= 0:
        raise PackDataError(f"non-positive price for product {product['id']}")
    ratio = price / comparison_price
    # The two prices are rounded to cents, so the ratio is a little off (11.18 / 1.12 = 9.98).
    size = ratio.quantize(Decimal("0.1"), ROUND_HALF_UP)
    if size >= 1:
        size = size.quantize(Decimal("1"), ROUND_HALF_UP) if abs(size - size.to_integral()) <= Decimal("0.2") else size
    if size <= 0:
        raise PackDataError(f"pack size rounds to zero for product {product['id']}")
    return PackInfo(sales, want, size, lot, derived=True)


def to_sales_units(need: Decimal, info: PackInfo) -> tuple[Decimal, bool]:
    """Round a need in `info.measure` up to whole lot steps. Returns (qty, rounded)."""
    if need <= 0:
        return Decimal(0), False
    raw = need / info.size
    steps = (raw / info.lot_size).to_integral_value(ROUND_CEILING)
    qty = (steps * info.lot_size).normalize()
    exact = raw.normalize()
    return qty, qty != exact
