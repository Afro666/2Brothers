"""Who placed an order when no person did (#1560, Aron 2026-11-14).

A seed script writes its order straight into the store (`demo/delivery_order.py`, the
delivery demo order DEMO-1198). Such an order never passes the approve path: no person
approved it, it has no signed receipt, and it earns nothing for auto-approve. The order
says so with `placed_by: "demo-seed"`. This is the one place that reads the marker.
"""

from __future__ import annotations

SEED = "demo-seed"


def is_seed(name: str | None) -> bool:
    return name == SEED


def placed_by(order: dict) -> str | None:
    """`"demo-seed"` for an order a seed placed; None for every other order.

    The live order of 14 Nov was stored before the marker, with the seed as a fake
    approver (`approved_by: "demo-seed"`): it is read the same, so no database edit.
    """
    if is_seed(order.get("placed_by")) or is_seed(order.get("approved_by")):
        return SEED
    return None
