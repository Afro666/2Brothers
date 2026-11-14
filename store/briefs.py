from __future__ import annotations

from store import recalls
from store.products import get_products
from store.repository import Repository, _from_store


def _product_names(db, kitchen, ids, context):
    rows = list((context or {}).get("products") or [])
    known = {str(row.get("product_id") or row.get("_id")) for row in rows}
    missing = sorted(ids - known)
    if missing:
        rows.extend(get_products(db, missing, kitchen))
    result = {}
    for row in rows:
        product_id = row.get("product_id") or row.get("_id")
        if product_id is None:
            continue
        names = row.get("names") or {}
        en = names.get("en") or names.get("fi")
        fi = names.get("fi") or names.get("en")
        result[str(product_id)] = {"en": en, "fi": fi}
    return result


def snapshot(db, kitchen):
    proposals = list(db.proposals.find({"kitchen_id": kitchen, "status": "READY"})
                     .sort([("created_at", 1), ("_id", 1)]).limit(100))
    joined = []
    for proposal in proposals:
        offer = db.offers.find_one({"_id": proposal.get("offer_id")})
        joined.append({"proposal": proposal, "offer": offer if offer and offer.get("kitchen_id") == kitchen else {}})

    orders = list(db.orders.find({"kitchen_id": kitchen})
                  .sort([("created_at", -1), ("_id", -1)]).limit(100))
    for order in orders:
        offer = db.offers.find_one({"_id": order.get("offer_id"), "kitchen_id": kitchen}) or {}
        order["requested_date"] = order.get("requested_date") or offer.get("requested_date")
    supplier_rows = Repository(db).suppliers.list(kitchen)
    suppliers = {}
    for row in supplier_rows:
        supplier_id = row.get("supplier_id") or row.get("_id") or row.get("id")
        name = row.get("name") or row.get("supplier_name")
        if supplier_id is not None and isinstance(name, str) and name.strip():
            suppliers[str(supplier_id)] = name.strip()

    supplier_offers = list(db.supplier_offers.find({"kitchen_id": kitchen, "status": "OPEN"})
                           .sort([("requested_date", 1), ("_id", 1)]).limit(50))
    alerts = list(db.recall_alerts.find({"kitchen_id": kitchen, "status": {"$nin": ["dismissed", "resolved", "closed"]}})
                  .sort([("detected_at", -1), ("_id", -1)]).limit(200))
    context = recalls.context(db, kitchen)[0] if alerts else None
    audit = list(db.audit_log.find({"server.kitchen_id": kitchen})
                 .sort([("server.at", -1), ("_id", -1)]).limit(1000))

    ids = {str(alert["product_id"]) for alert in alerts if alert.get("product_id") is not None}
    ids.update(str(row["product_id"]) for row in supplier_offers if row.get("product_id") is not None)
    for item in joined:
        simulation = item["offer"].get("simulation") or {}
        ids.update(str(line["product_id"]) for line in simulation.get("lines") or []
                   if isinstance(line, dict) and line.get("product_id") is not None)
    if context:
        ids.update(map(str, context.get("proposal") or []))
        ids.update(map(str, (context.get("stock") or {}).keys()))
        ids.update(map(str, (context.get("recipes") or {}).keys()))

    return _from_store({"proposals": joined, "orders": orders, "suppliers": suppliers,
            "supplier_offers": supplier_offers, "alerts": alerts,
            "recall_context": context, "audit": audit,
            "products": _product_names(db, kitchen, ids, context)})
