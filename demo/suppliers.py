"""Four invented suppliers for demo-kitchen, so one request gets a real choice (#1604).

    python -m demo.suppliers            # lists what it would write; writes nothing
    python -m demo.suppliers --apply    # writes the four suppliers and their products (safe to run again)
    python -m demo.suppliers --remove   # deletes exactly these suppliers and products

Every name is invented and ends in "(demo)"; no real company is meant. Each one is a manual
supplier (no API): it has a price list of own products, its stock is unknown, and a person
may still approve it (docs/decisions.md, 2026-11-14). Each product names the Valio catalog
product it is the same as (`catalog_product_id`), so the product page lists the choice, and
has that product's category, so the Buyer's kind filter keeps it next to Valio's.

Prices, packs, minimum order, order days and lead times are made-up demo values, cheaper on
some products and dearer on others than Valio's. Kept out on purpose, so the rehearsed stage
stories do not change (docs/demo.md): no milk, cream, cheese, butter or oat drink (the 1,000 L
and 200 L milk stories, the cream and cheese requests), nothing with peanuts (the refusal),
no coffee (the recall beat), no chicken. The demo seed (`python -m demo.seed`) writes them too.
"""

from __future__ import annotations

import argparse

DEMO_ID = "demo-kitchen"


FISH, VEG, DRY, DAIRY = "sup-demo-fish", "sup-demo-veg", "sup-demo-dry", "sup-demo-dairy"


def _terms(threshold: str, fee: str, days: list[str], cutoff: str, lead: int) -> dict:
    return {"free_delivery_threshold_eur": threshold, "delivery_fee_eur": fee, "order_days": days,
            "cutoff_time": cutoff, "lead_time_days": lead, "discount_tiers": []}


SUPPLIERS = [
    {"supplier_id": FISH, "name": "Baltic Catch Fish Wholesale (demo)", "adapter": "manual",
     "terms": _terms("150.00", "18.00", ["MON", "WED", "FRI"], "11:00", 1)},
    {"supplier_id": VEG, "name": "Green Acre Growers (demo)", "adapter": "manual",
     "terms": _terms("60.00", "9.90", ["TUE", "THU"], "12:00", 1)},
    {"supplier_id": DRY, "name": "Northern Pantry Wholesale (demo)", "adapter": "manual",
     "terms": _terms("250.00", "29.00", ["MON", "THU"], "15:00", 2)},
    {"supplier_id": DAIRY, "name": "Hillside Farm Dairy (demo)", "adapter": "manual",
     "terms": _terms("120.00", "15.00", ["MON", "WED", "FRI"], "10:00", 2)},
]


def _product(pid, name, supplier, unit, kilos, price, catalog_id, category, allergens=()):
    """One own product: `unit` is how it is sold, `kilos` the kilograms in one."""
    return {"product_id": pid, "name": name, "supplier_id": supplier, "unit": unit, "base_unit": "KG",
            "pack_size_in_base_units": kilos, "unit_price_eur": price,
            "allergens": [{"code": code, "level": "CONTAINS"} for code in allergens],
            "allergen_data": "ENTERED", "vat_rate": "13.5",      # food: the reduced rate (2026)
            "category": category, "catalog_product_id": catalog_id}


# (Valio's own catalog price for comparison, read 2026-11-13 in env/catalog.py, where known.)
PRODUCTS = [
    # Fish: fresh, three days a week, small minimum order.
    _product("own-demo-salmon-fillet", "Salmon fillet, fresh, trimmed 1 kg", FISH, "KG", "1", "22.90",
             "461903", "18701", ["AF"]),                                         # Valio 24.85 / kg
    _product("own-demo-trout-fillet", "Rainbow trout fillet, fresh 1 kg", FISH, "KG", "1", "19.40",
             "461921", "18701", ["AF"]),
    _product("own-demo-cod-fillet", "Cod fillet, skinless, MSC 1 kg", FISH, "KG", "1", "21.50",
             "461879", "18701", ["AF"]),
    # Vegetables: bigger packs, twice a week.
    _product("own-demo-potato-sack", "Potato, washed, 10 kg sack", VEG, "ST", "10", "11.50",
             "460478", "17421"),                                                 # Valio 1.66 / kg
    _product("own-demo-carrot-box", "Carrot, Finland, 5 kg box", VEG, "ST", "5", "5.40",
             "460811", "17431"),                                                 # Valio 1.26 / kg
    _product("own-demo-onion-net", "Yellow onion, 5 kg net", VEG, "ST", "5", "4.90",
             "460351", "17405"),                                                 # Valio 0.86 / kg: dearer here
    _product("own-demo-cherry-tomato", "Cherry tomato, Finland, 3 kg box", VEG, "ST", "3", "23.70",
             "460838", "17401"),                                                 # Valio 7.27 / kg: dearer here
    _product("own-demo-cucumber", "Cucumber, Finland, 1 kg", VEG, "KG", "1", "3.10",
             "460137", "17402"),                                                 # Valio 3.46 / kg
    # Dry goods: large sacks, two days lead time, high minimum order.
    _product("own-demo-rice-sack", "Wholegrain rice 10 kg", DRY, "ST", "10", "19.90",
             "462279", "21340"),                                                 # Valio 2.24 / kg
    _product("own-demo-fusilli", "Fusilli pasta 5 kg", DRY, "ST", "5", "16.40",
             "460008", "21380", ["AW"]),                                         # Valio 3.63 / kg
    _product("own-demo-wheat-flour", "Wheat flour 10 kg", DRY, "ST", "10", "11.90",
             "460791", "21300", ["AW"]),                                         # Valio 1.37 / kg
    _product("own-demo-oat-flakes", "Wholegrain oat flakes 5 kg", DRY, "ST", "5", "12.40",
             "460200", "21370", ["GO"]),                                         # Valio 2.76 / kg
    # Dairy: yoghurt and quark only (no milk, cream, cheese or butter: see the module text).
    _product("own-demo-natural-yoghurt", "Natural yoghurt 5 kg, lactose free", DAIRY, "ST", "5", "13.90",
             "464278", "10412", ["AM"]),
    _product("own-demo-turkish-yoghurt", "Turkish yoghurt 10 % 2 kg", DAIRY, "ST", "2", "6.90",
             "462718", "10412", ["AM"]),                                         # Valio 3.19 / kg: dearer here
    _product("own-demo-quark", "Plain quark 1 kg", DAIRY, "ST", "1", "4.20",
             "463196", "10430", ["AM"]),
]

SUPPLIER_IDS = tuple(s["supplier_id"] for s in SUPPLIERS)
PRODUCT_IDS = tuple(p["product_id"] for p in PRODUCTS)


def remove(db) -> dict:
    """Delete exactly these suppliers and products of demo-kitchen. Nothing else."""
    from store.repository import Repository
    repo = Repository(db)
    products = sum(repo.own_products.delete(DEMO_ID, pid) for pid in PRODUCT_IDS)
    suppliers = sum(repo.suppliers.delete(DEMO_ID, sid) for sid in SUPPLIER_IDS)
    return {"suppliers": suppliers, "products": products}


def load(db) -> dict:
    """Write them through the store, replacing earlier copies. Safe to run again."""
    from store.repository import Repository
    remove(db)
    repo = Repository(db)
    for supplier in SUPPLIERS:
        repo.suppliers.create(DEMO_ID, supplier)
    for product in PRODUCTS:
        repo.own_products.create(DEMO_ID, product)
    return {"suppliers": len(SUPPLIERS), "products": len(PRODUCTS)}


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--apply", action="store_true", help="write the demo suppliers and products")
    group.add_argument("--remove", action="store_true", help="delete them")
    args = parser.parse_args(argv)
    if not (args.apply or args.remove):
        for supplier in SUPPLIERS:
            names = [p["name"] for p in PRODUCTS if p["supplier_id"] == supplier["supplier_id"]]
            print(f"{supplier['supplier_id']}  {supplier['name']}: {len(names)} products ({', '.join(names)})")
        print("nothing written; add --apply (or --remove)")
        return
    from store.db import get_db
    db = get_db()
    print(f"{DEMO_ID}: " + str(load(db) if args.apply else remove(db)))


if __name__ == "__main__":
    main()
