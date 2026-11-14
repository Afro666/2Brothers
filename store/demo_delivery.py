"""Demo delivery figures for a synthetic demo kitchen (#1453). Never a supplier's numbers.

Per supplier: lead time, order days, cut-off time and delivery reliability. Per product: a
lead time override (some products only) and a delivery reliability. The demo seed writes
them (demo/delivery_terms.py); the gateway shows one only where real data is missing, and
marks it `demo` (gateway/suppliers.py, `delivery_facts`). Every row carries `demo: true`.

Only a kitchen marked `synthetic` gets rows, so a real kitchen never sees a demo value.
"""

from __future__ import annotations

COLLECTION = "demo_delivery"


def ensure_indexes(db) -> None:
    db[COLLECTION].create_index([("kitchen_id", 1), ("supplier_id", 1), ("product_id", 1)])


def replace(db, kitchen_id: str, suppliers: list[dict], products: list[dict]) -> int:
    """Replace all demo rows of a synthetic kitchen. Safe to run again: same rows, same ids."""
    kitchen = db.kitchens.find_one({"_id": kitchen_id}, {"synthetic": 1})
    if not kitchen or kitchen.get("synthetic") is not True:
        raise ValueError(f"demo delivery figures need a synthetic kitchen, not {kitchen_id}")
    rows = [{**row, "_id": "|".join((kitchen_id, row["supplier_id"], row.get("product_id") or "")),
             "kitchen_id": kitchen_id, "product_id": row.get("product_id"), "demo": True}
            for row in [*suppliers, *products]]
    ensure_indexes(db)
    db[COLLECTION].delete_many({"kitchen_id": kitchen_id})
    for start in range(0, len(rows), 1000):
        db[COLLECTION].insert_many(rows[start:start + 1000], ordered=False)
    return len(rows)


def lookup(db, kitchen_id: str, supplier_id: str, product_ids: list[str]) -> dict:
    """`{"supplier": row or None, "products": {product_id: row}}` for one supplier's lines."""
    rows = db[COLLECTION].find({"kitchen_id": kitchen_id, "supplier_id": supplier_id,
                                "product_id": {"$in": [None, *product_ids]}, "demo": True})
    out: dict = {"supplier": None, "products": {}}
    for row in rows:
        if row.get("product_id") is None:
            out["supplier"] = row
        else:
            out["products"][row["product_id"]] = row
    return out


def catalog_profiles(db) -> list[dict]:
    """Code, names and storage temperature of every Valio catalog product, for the seed."""
    return list(db.products.find({"source": "valio"}, {"names": 1, "temperature": 1}))
