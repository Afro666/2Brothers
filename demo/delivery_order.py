"""The demo order for the delivery-note beat (#1198), placed once in demo-kitchen.

    python -m demo.delivery_order             # prints the order id if it is there; writes nothing
    python -m demo.delivery_order --apply     # places it if it is missing (safe to run again)

The beat needs a placed order whose lines match a prepared delivery-note photo
(`agent/fixtures/receiving/demo-note.png`, made by `make_demo_note.py`). An order placed
in a rehearsal changes every time, so this places one fixed order: three Valio lines at
the prices in `env/catalog.py` (Valio catalog prices read on 2026-11-13), reference
DEMO-1198. The idempotency key makes it one order per database: a second run finds it.

The order has no proposal and so no delivery day: the stock screens never count it as
on order. It is marked `placed_by: demo-seed` and has no `approved_by`: no person approved
it, so it has no signed receipt and it earns nothing for auto-approve (#1560; an order
stored earlier with `approved_by: demo-seed` is read the same, `gateway/seeded.py`). It has
one audit entry, `demo_delivery_order_placed`. Nothing is sent to Valio.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from uuid import uuid4

from bson.decimal128 import Decimal128

from env.catalog import PRODUCTS
from gateway.seeded import SEED

KITCHEN = "demo-kitchen"
KEY = "demo-delivery-beat-1198"
REFERENCE = "DEMO-1198"
SUPPLIER = {"supplier_id": "sup-valio", "name": "Valio Aimo"}
CENT = Decimal("0.01")
# product, quantity in its Valio sales unit. The photo shows 1 of 3 egg cases, no tomatoes,
# and all 40 milk drinks: SHORT 2 KI, MISSING 1 KI, RECEIVED.
LINES = (("463982", "3"), ("460838", "1"), ("463335", "40"))


def lines() -> list[dict]:
    out = []
    for pid, qty in LINES:
        product = PRODUCTS[pid]
        price = Decimal(str(product.price)).quantize(CENT)     # catalog prices are whole cents
        out.append({"product_id": pid, "name": product.name, "quantity": qty, "unit": product.sales_unit,
                    "unit_price": f"{price:f}", "total": f"{(price * Decimal(qty)).quantize(CENT, ROUND_HALF_UP):f}",
                    "unknown_stock": False, "reason_codes": []})
    return out


def find(db) -> dict | None:
    from store import orders
    return orders.attempt_for_key(db, KITCHEN, KEY)


def place(db) -> dict:
    """The demo order; placed when it is missing. Returns the stored order."""
    from store import audit, orders
    found = find(db)        # the unique key index is the gateway's; do not rely on it here
    if found is not None:
        return found
    rows = lines()
    total = sum((Decimal(ln["total"]) for ln in rows), Decimal(0))
    order, created = orders.record_attempt(
        db, kitchen_id=KITCHEN, idempotency_key=KEY, offer_id=KEY, expected_total=Decimal128(f"{total:f}"),
        lines=rows, placed_by=SEED, reference=REFERENCE, supplier_id=SUPPLIER["supplier_id"],
        blocks=[{**SUPPLIER, "product_ids": [ln["product_id"] for ln in rows]}], supplier_must_confirm=[])
    if not created:
        return order
    order = orders.set_outcome(db, order["order_id"], outcome="CONFIRMED", status="SENT")
    audit.append_event(db, {"event_id": uuid4().hex, "kind": "demo_delivery_order_placed", "actor": SEED,
                            "order_id": order["order_id"], "reference": REFERENCE, "expected_total": f"{total:f}"},
                       {"kitchen_id": KITCHEN, "at": datetime.now(timezone.utc).isoformat()})
    return order


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="place the order if it is missing")
    args = parser.parse_args(argv)
    from store.db import get_db
    db = get_db()
    order = place(db) if args.apply else find(db)
    if order is None:
        print("no demo delivery order yet; run with --apply")
        return
    print(f"order {order['order_id']}  reference {REFERENCE}  open /orders/{order['order_id']}")


if __name__ == "__main__":
    main()
