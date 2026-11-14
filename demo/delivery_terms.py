"""Demo lead time, cut-off and delivery reliability for demo-kitchen (#1453). Invented values.

    python -m demo.delivery_terms            # counts and examples, writes nothing
    python -m demo.delivery_terms --apply    # replace demo-kitchen's demo rows (safe to run again)

The demo seed (`python -m demo.seed`) writes them too. Every value is demo data, never
Valio's or a supplier's number: the gateway shows one only where real data is missing and
marks it `demo` (docs/contract.md, "Cut-off, lead time and delivery reliability to show").

- Per supplier: lead time, order days, cut-off time, delivery reliability (on-time share).
- Per product: a delivery reliability for every Valio catalog product and the demo bakery's
  own products, and a lead time override for some: fresh fish and fresh bakery 1 day,
  dry (ambient) goods 2 days. Other products take the supplier's lead time.

Deterministic: the same seed gives the same values (a hash of seed and product code).
"""

from __future__ import annotations

import argparse
import hashlib
import re

DEMO_ID = "demo-kitchen"
VALIO, BAKERY = "sup-valio", "sup-bakery"

SUPPLIERS = [
    {"supplier_id": VALIO, "lead_time_days": 2, "order_days": ["MON", "TUE", "WED", "THU", "FRI"],
     "cutoff_time": "16:00", "reliability": 0.96},
    {"supplier_id": BAKERY, "lead_time_days": 1, "order_days": ["TUE", "FRI"],
     "cutoff_time": "14:00", "reliability": 0.92},
]
# (low, high) of a product's delivery reliability, per kind.
RANGES = {"fish": (0.86, 0.95), "bakery": (0.90, 0.98), "dry": (0.94, 0.995), "other": (0.90, 0.99)}
LEAD = {"fish": 1, "bakery": 1, "dry": 2}

_FISH = re.compile(r"\b(fish|salmon|cod|herring|trout|pike|perch|vendace|whitefish|zander|hake|saithe)\b"
                   r"|(kala|lohi|silakka|muikku|siika|kuha|ahven|turska|taimen)\b", re.I)
_BAKERY = re.compile(r"\b(bread|loaf|bun|baguette|croissant|sourdough|rye bread)\b"
                     r"|(leipä|pulla|sämpylä|patonki|limppu)\b", re.I)


def kind(names: dict | None, temperature: str | None) -> str:
    """`fish` (chilled fish), `bakery` (bread not frozen), `dry` (ambient) or `other`."""
    text = " ".join((names or {}).values())
    if temperature == "chilled" and _FISH.search(text):
        return "fish"
    if temperature != "frozen" and _BAKERY.search(text):
        return "bakery"
    return "dry" if temperature == "ambient" else "other"


def _share(seed: int, product_id: str, low: float, high: float) -> float:
    digest = hashlib.sha256(f"{seed}:{product_id}".encode()).digest()
    return round(low + (high - low) * int.from_bytes(digest[:8], "big") / 2 ** 64, 3)


def product_row(seed: int, supplier_id: str, product_id: str, kind_: str) -> dict:
    row = {"supplier_id": supplier_id, "product_id": product_id,
           "reliability": _share(seed, product_id, *RANGES[kind_]), "kind": kind_}
    if kind_ in LEAD:
        row["lead_time_days"] = LEAD[kind_]
    return row


def build(seed: int, catalog: list[dict], own_products: list[dict]) -> tuple[list[dict], list[dict]]:
    """Pure: supplier rows and product rows from catalog profiles and the demo's own products."""
    products = [product_row(seed, VALIO, str(p["_id"]), kind(p.get("names"), p.get("temperature")))
                for p in catalog]
    products += [product_row(seed, p["supplier_id"], p["product_id"], "bakery") for p in own_products]
    return [dict(s) for s in SUPPLIERS], products


def load(db, seed: int = 1) -> int:
    """Write demo-kitchen's demo rows through the store. Returns the number of rows."""
    from demo.seed import DEMO_OWN_PRODUCTS
    from store import demo_delivery

    suppliers, products = build(seed, demo_delivery.catalog_profiles(db), DEMO_OWN_PRODUCTS)
    return demo_delivery.replace(db, DEMO_ID, suppliers, products)


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--apply", action="store_true", help="write the rows (default: print only)")
    a = p.parse_args(argv)
    from store.db import get_db
    from store import demo_delivery
    from demo.seed import DEMO_OWN_PRODUCTS

    db = get_db()
    if a.apply:
        print(f"demo delivery rows for {DEMO_ID}: {load(db, a.seed)}")
        return
    suppliers, products = build(a.seed, demo_delivery.catalog_profiles(db), DEMO_OWN_PRODUCTS)
    counts: dict[str, int] = {}
    for row in products:
        counts[row["kind"]] = counts.get(row["kind"], 0) + 1
    print(f"would write {len(suppliers)} supplier rows and {len(products)} product rows: {counts}")
    for row in suppliers + products[:3]:
        print(row)
    print("nothing written; add --apply")


if __name__ == "__main__":
    main()
