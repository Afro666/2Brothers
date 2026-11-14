"""The engine's partial-fill option (#288) as the `partial_fill` object of a simulation.

Read-only: it shows what the engine planned (confirmed stock now, a plan for the rest).
It has no offer_id and cannot be approved or placed as it is; every number and sentence
is the engine's own, formatted as a decimal string.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from engine.partial import FillPart, PartialFill

CENT = Decimal("0.01")


def _money(x: Decimal) -> str:
    return f"{x.quantize(CENT, ROUND_HALF_UP):f}"


def _qty(x: Decimal) -> str:
    return f"{x.normalize():f}"


def _part(part: FillPart, vat: dict) -> dict:
    return {
        "kind": part.kind, "quantity": _qty(part.quantity), "measure": part.measure,
        "deliver_on": None if part.deliver_on is None else part.deliver_on.isoformat(),
        "total_ex_vat": None if part.total is None else _money(part.total),   # HOLD: unknown, never zero
        "why": part.why,
        "lines": [{"product_id": ln.product_id, "quantity": _qty(ln.quantity), "unit": ln.unit,
                   "unit_price": _money(ln.unit_price), "total": _money(ln.total), "why": ln.why,
                   "unknown_stock": ln.unknown_stock, "reason_codes": list(ln.reason_codes),
                   **vat.get(ln.product_id, {"vat_rate": None, "vat_source": None})}
                  for ln in part.lines],
    }


def partial_out(partial: PartialFill | None, vat: dict | None = None) -> dict | None:
    """`vat`: {product_id: {"vat_rate", "vat_source"}}; a product not in it has unknown VAT."""
    vat = vat or {}
    if partial is None:
        return None
    return {
        "need": _qty(partial.need), "measure": partial.measure, "remaining": _qty(partial.remaining),
        "reason_codes": list(partial.reason_codes), "why": partial.why,
        "now": _part(partial.now, vat), "rest": [_part(p, vat) for p in partial.rest],
    }
