"""Learned facts for one kitchen (#1305-#1307): compute, list and switch off.

Facts are derived on read from the kitchen's own feedback and delivery observations.
Only a person's disable is stored, and it names the fact evidence version.
"""

from __future__ import annotations

from decimal import Decimal

from fastapi import Depends, Request

from engine.learning import correction_ratio_fact, declined_product_fact, supplier_facts
from gateway.service import GatewayError
from store import learned as learned_store
from store.delivery_results import delivery_history
from store.feedback import changes_for
from store.products import get_products
from store.repository import Repository

_APPROVED = ("APPROVED", "PLACED")


def _approved_proposals(gw, kitchen_id: str, rows: list[dict]) -> dict[str, bool]:
    """Which proposals count as approved: a human row, or the stored proposal state."""
    by_row = {row.get("proposal_id") for row in rows
              if row.get("kind") == "approved" and row.get("proposal_id")}
    ids = [row["proposal_id"] for row in rows if row.get("proposal_id")]
    stored = {doc["_id"]: doc.get("status") for doc in gw.db.proposals.find(
        {"_id": {"$in": ids}}, {"status": 1})} if ids else {}
    return {str(pid): pid in by_row or stored.get(pid) in _APPROVED for pid in ids}


def _entity(fact: dict) -> str:
    return str(fact.get("product_id") or fact.get("supplier_id") or "")


def compute_facts(gw, kitchen_id: str, today) -> list[dict]:
    """Every current fact of one kitchen, with disabled evidence versions marked inactive."""
    rows = changes_for(gw.db, kitchen_id)
    approved = _approved_proposals(gw, kitchen_id, rows)
    for row in rows:
        row["approved"] = approved.get(str(row.get("proposal_id"))) is True

    product_ids = sorted({str(row["product_id"]) for row in rows if row.get("product_id")})
    names = {row["product_id"]: ((row.get("names") or {}).get("en")
                                 or (row.get("names") or {}).get("fi")
                                 or row["product_id"])
             for row in get_products(gw.db, product_ids, kitchen_id)}
    facts = []
    for product_id in product_ids:
        name = names.get(product_id, product_id)
        fact = correction_ratio_fact(kitchen_id, product_id, name, rows, today)
        if fact is not None:
            facts.append(fact)
        fact = declined_product_fact(kitchen_id, product_id, name, rows, today)
        if fact is not None:
            facts.append(fact)

    observations = delivery_history(gw.db, kitchen_id)
    supplier_ids = set()
    for observation in observations:
        if observation.get("supplier_id"):
            supplier_ids.add(str(observation["supplier_id"]))
        for line in observation.get("lines") or []:
            if isinstance(line, dict) and line.get("supplier_id"):
                supplier_ids.add(str(line["supplier_id"]))
    supplier_names = {row["supplier_id"]: row.get("name") or row["supplier_id"]
                      for row in Repository(gw.db).suppliers.list(kitchen_id)}
    for supplier_id in sorted(supplier_ids):
        facts.extend(supplier_facts(kitchen_id, supplier_id,
                                    supplier_names.get(supplier_id, supplier_id),
                                    observations, today))

    disabled = learned_store.disabled_ids(gw.db, kitchen_id)
    unique, seen = [], set()
    for fact in facts:
        if fact["id"] in seen:
            continue
        seen.add(fact["id"])
        unique.append({**fact, "active": fact.get("active") is True and fact["id"] not in disabled})
    unique.sort(key=lambda fact: (str(fact.get("kind")), _entity(fact), str(fact.get("id"))))
    return unique


def plan_problems(gw, kitchen_id: str, facts: list[dict], product_ids: list[str]) -> list[str]:
    """Warning-only sentences for declined products and late suppliers of this plan."""
    product_ids = {str(pid) for pid in product_ids}
    problems = []
    declined = {fact["product_id"]: fact for fact in facts
                if fact.get("kind") == "DECLINED_PRODUCT" and fact.get("active") is True}
    for product_id in sorted(product_ids):
        fact = declined.get(product_id)
        if fact is None:
            continue
        count = (fact.get("evidence") or {}).get("rows")
        if count:
            problems.append(f"You removed {fact.get('name') or product_id} from {count} proposals; "
                            "it is still needed by the menu plan. Remove it again, or switch the fact off.")

    suppliers_of: dict[str, set[str]] = {}
    for row in get_products(gw.db, sorted(product_ids), kitchen_id):
        if row.get("supplier_id"):
            suppliers_of.setdefault(str(row["product_id"]), set()).add(str(row["supplier_id"]))
    for observation in delivery_history(gw.db, kitchen_id):
        top = observation.get("supplier_id")
        for line in observation.get("lines") or []:
            if not isinstance(line, dict) or str(line.get("product_id")) not in product_ids:
                continue
            supplier = line.get("supplier_id") or top
            if supplier:
                suppliers_of.setdefault(str(line["product_id"]), set()).add(str(supplier))
    plan_suppliers = {supplier for values in suppliers_of.values() for supplier in values}
    for fact in facts:
        if fact.get("kind") != "SUPPLIER_LATE" or fact.get("active") is not True:
            continue
        if str(fact.get("supplier_id")) not in plan_suppliers:
            continue
        rate, deliveries = fact.get("on_time_rate"), fact.get("deliveries")
        try:
            rate = Decimal(str(rate))
            deliveries = int(deliveries)
        except (ArithmeticError, TypeError, ValueError):
            continue
        if rate >= Decimal("0.7") or deliveries <= 0:
            continue
        late = deliveries - round(rate * deliveries)
        problems.append(f"{fact.get('name') or fact.get('supplier_id')} was late in {late} of the last "
                        f"{deliveries} deliveries: order a day earlier.")
    return problems


def mount_learned(app, gw, principal, body) -> None:
    """GET the current facts and PUT exactly {"active": false} to switch one off."""
    prefix = "/v1/kitchens/{kitchen_id}"

    @app.get(prefix + "/learned")
    def learned_facts(kitchen_id: str, who=Depends(principal)):
        who.need("kitchen:read", kitchen_id)
        return {"facts": compute_facts(gw(), kitchen_id, gw().now().date())}

    @app.put(prefix + "/learned/{fact_id}")
    async def learned_switch(kitchen_id: str, fact_id: str, request: Request, who=Depends(principal)):
        who.need("kitchen:write", kitchen_id)
        person = who.human
        if not person:
            raise GatewayError(403, "ROLE_REQUIRED", "only an approver can switch a learned fact off")
        data = await body(request)
        if set(data) != {"active"} or data["active"] is not False:
            raise GatewayError(422, "INVALID_REQUEST", 'body must be exactly {"active": false}')
        facts = compute_facts(gw(), kitchen_id, gw().now().date())
        fact = next((row for row in facts if row.get("id") == fact_id), None)
        if fact is None:
            raise GatewayError(404, "LEARNED_FACT_NOT_FOUND", "no such learned fact")
        changed = learned_store.disable(gw().db, kitchen_id, fact_id, person,
                                        gw().now().isoformat())
        if changed:
            gw()._audit(kitchen_id, "learned_fact_switched_off", person, fact_id=fact_id)
        return {"fact": {**fact, "active": False}}
