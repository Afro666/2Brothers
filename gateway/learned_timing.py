"""Learned delivery timing applied to a plan proposal (#1306).

A late supplier's lead-time spread adds the engine's safety stock to that supplier's plan
lines. The numbers come from `engine/delivery_timing.py`; this module only reads the
kitchen's own rows and writes what the line shows (docs/contract.md, "Learned safety stock").
"""

from __future__ import annotations

from decimal import Decimal

from engine.delivery_timing import delivery_timing, learned_safety_stock
from gateway.suppliers import VALIO
from store.delivery_results import delivery_history
from store.products import get_products

_KIND = "SUPPLIER_LATE"


def _number(value) -> Decimal | None:
    try:
        number = Decimal(str(value))
    except (ArithmeticError, TypeError, ValueError):
        return None
    return number if number.is_finite() else None


def _text(value: Decimal) -> str:
    return f"{value.normalize():f}"


def add_safety_stock(gw, kitchen_id: str, facts: list[dict], needs: list[dict],
                     gross: dict[tuple[str, str], Decimal], days: int, today) -> None:
    """Raise the needs of a late supplier's products by the learned safety stock, in place.

    Only for an active SUPPLIER_LATE fact; without one nothing is read and nothing changes.
    A need that a correction ratio already adjusted is left alone: the person's own
    correction is the last word, and a line names one fact. The statistics are the
    product's own deliveries when there are enough, else the supplier's.
    """
    late = {str(fact["supplier_id"]): fact for fact in facts
            if fact.get("kind") == _KIND and fact.get("active") is True and fact.get("supplier_id")}
    if not late or days <= 0:
        return
    products = {str(row["product_id"]): row for row in get_products(
        gw.db, [need["product_id"] for need in needs], kitchen_id)}
    observations = delivery_history(gw.db, kitchen_id)
    params = gw._params(kitchen_id)
    for need in needs:
        if need.get("learned"):
            continue
        product_id = str(need["product_id"])
        product = products.get(product_id) or {}
        # As in the quote: a catalog product is Valio's, an own product its supplier's.
        supplier_id = str(product["supplier_id"]) if (
            product.get("source") == "own" and product.get("supplier_id")) else VALIO
        fact = late.get(supplier_id)
        demand = gross.get((need["product_id"], need["unit"]))
        if fact is None or demand is None:
            continue
        timing = (delivery_timing(kitchen_id, supplier_id, observations, today, product_id=product_id)
                  or delivery_timing(kitchen_id, supplier_id, observations, today))
        terms = (gw._supplier(kitchen_id, supplier_id) or {}).get("terms") or {}
        original = need["quantity"]
        adjusted, info = learned_safety_stock(
            original, demand / Decimal(days), timing, fact, z=params.z(product.get("abc")),
            lead_time_days=terms.get("lead_time_days"), unit=need["unit"])
        if info is None:
            continue
        if supplier_id == VALIO and info.get("name") in (None, VALIO):
            info["name"] = "Valio Aimo"
        need["quantity"] = _text(adjusted)
        # The offer store refuses binary floats; the API turns this back into a number.
        need["learned"] = {**info, "sigma_lead_time": _text(Decimal(str(info["sigma_lead_time"])))}
        need["unlearned_quantity"] = original


def safety_stock_sentence(info) -> str | None:
    """What a person reads first on the line: how much was added, from which deliveries,
    and how to get the plain number back. None for anything but a learned safety stock."""
    if not isinstance(info, dict) or info.get("kind") != _KIND:
        return None
    evidence = info.get("evidence") or {}
    extra, plain, sigma = (_number(info.get(key)) for key in ("safety_stock", "from_qty", "sigma_lead_time"))
    late, rows = evidence.get("late"), evidence.get("rows")
    if None in (extra, plain, sigma) or not isinstance(late, int) or not isinstance(rows, int):
        return None
    unit = info.get("unit") or ""
    what = " of this product" if evidence.get("scope") == "product" else ""
    cap = ", capped" if info.get("capped") else ""
    return (f"Includes {_text(extra)} {unit} learned safety stock on top of {_text(plain)} {unit}: "
            f"{info.get('name') or 'the supplier'} was late in {late} of its last {rows} deliveries{what} "
            f"(lead time varies by {_text(sigma)} days{cap}). "
            f"Switch this learned fact off to order {_text(plain)} {unit}.")


def unlearned_line_quantity(quantity, info) -> str | None:
    """The line's quantity without the learned safety stock, in the line's own unit: the
    basis a later correction is measured against (gateway/change.py), so learning never
    compounds. None when the two quantities are not usable."""
    line, plain, learned = (_number(value) for value in (
        quantity, (info or {}).get("from_qty"), (info or {}).get("to_qty")))
    if line is None or plain is None or learned is None or learned <= 0:
        return None
    return _text((line * plain / learned).quantize(Decimal("0.001")))
