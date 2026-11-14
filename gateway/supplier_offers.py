"""Supplier offers (#374, docs/contract.md "Supplier offers"): a supplier's selling agent
offers one kitchen a substitute before a predicted shortage.

- POST /v1/suppliers/{supplier_id}/offers                              (supplier:offers)
- GET  /v1/kitchens/{kitchen_id}/supplier-offers                       (kitchen:read)
- POST /v1/kitchens/{kitchen_id}/supplier-offers/{offer_id}/accept     (a person)
- POST /v1/kitchens/{kitchen_id}/supplier-offers/{offer_id}/decline    (a person)

What the supplier sends is not trusted. There is no price in the body and no quantity: the
quantity is the kitchen's own forecast demand in the SHORT row of the shortage view, so an
offer without a shortage behind it is refused. The `reason` text is shown to a person and
stops there: it never goes into a proposal, a Buyer prompt or a tool. Accept makes a normal
proposal through `Gateway.create_proposal` (live price and stock, the engine's sizes, the
allergen rule, recall holds) and approves nothing.
"""

from __future__ import annotations

from datetime import date
import unicodedata

from fastapi import Depends, Request

from gateway.service import GatewayError, _hash
from gateway.suppliers import VALIO
from gateway.supplier_routes import supplier_demand
from store import audit
from store import supplier_offers as offers
from store.history import consenting_kitchens
from store.products import get_products

REASON_MAX = 300
MADE_BY_MAX = 100
DECLINE_REASON_MAX = 500
OPEN_LIMIT = 3            # open offers per kitchen per supplier
_FIELDS = ("kitchen_id", "product_id", "replaces_product_id", "requested_date", "reason", "made_by",
           "idempotency_key")


def clean_text(value: str) -> str:
    """Plain text: no control or format characters (also no bidi marks), spaces collapsed."""
    kept = "".join(" " if ch.isspace() else ch for ch in value
                   if ch.isspace() or not unicodedata.category(ch).startswith("C"))
    return " ".join(kept.split())


def _status(doc: dict, today: date) -> str:
    if doc["status"] == offers.OPEN and doc["requested_date"] < today.isoformat():
        return offers.EXPIRED
    return doc["status"]


def _out(doc: dict, today: date) -> dict:
    return {"offer_id": doc["_id"], "status": _status(doc, today),
            **{key: doc.get(key) for key in (
                "supplier_id", "supplier_name", "kitchen_id", "product_id", "product_name",
                "replaces_product_id", "replaces_product_name", "requested_date", "quantity", "unit",
                "reason", "made_by", "created_at", "proposal_id", "decided_by", "decided_at")},
            # false: the catalog declares no allergens for the offered product (see `_allergens_ok`)
            "allergen_data_known": doc.get("allergen_data_known") is True}


def _name(row: dict | None, fallback: str) -> str:
    names = (row or {}).get("names") or {}
    return names.get("en") or names.get("fi") or fallback


def _audit_once(gw, kitchen_id: str, kind: str, offer_id: str, actor: str, at: str, **data) -> None:
    """One audit line per offer and step: the event id is fixed, so a retry adds nothing."""
    audit.append_event(gw.db, {"event_id": f"{kind}:{offer_id}", "kind": kind, "actor": actor,
                               "offer_id": offer_id, **data}, {"kitchen_id": kitchen_id, "at": at})


def _audit_received(gw, doc: dict) -> None:
    _audit_once(gw, doc["kitchen_id"], "supplier_offer_received", doc["_id"],
                f"supplier:{doc['supplier_id']}", doc["created_at"],
                **{key: doc[key] for key in ("supplier_id", "product_id", "replaces_product_id",
                                             "requested_date", "quantity", "unit", "made_by")})


def _validated(body: dict, today: date) -> dict:
    for field in _FIELDS:
        if not isinstance(body.get(field), str) or not body[field].strip():
            raise GatewayError(422, "INVALID_REQUEST", f"{field} is required (a string)")
    try:
        day = date.fromisoformat(body["requested_date"])
    except ValueError:
        raise GatewayError(422, "INVALID_REQUEST", "requested_date must be YYYY-MM-DD") from None
    if day < today:
        raise GatewayError(422, "INVALID_REQUEST", "requested_date is in the past")
    reason, made_by = clean_text(body["reason"]), clean_text(body["made_by"])
    if not reason or len(reason) > REASON_MAX:
        raise GatewayError(422, "INVALID_REQUEST", f"reason: plain text, 1 to {REASON_MAX} characters")
    if not made_by or len(made_by) > MADE_BY_MAX:
        raise GatewayError(422, "INVALID_REQUEST", f"made_by: 1 to {MADE_BY_MAX} characters")
    if body["product_id"] == body["replaces_product_id"]:
        raise GatewayError(422, "INVALID_REQUEST", "product_id is the product it replaces")
    return {"kitchen_id": body["kitchen_id"], "product_id": body["product_id"],
            "replaces_product_id": body["replaces_product_id"], "requested_date": day.isoformat(),
            "reason": reason, "made_by": made_by}


def _kitchen_demand(gw, supplier_id: str, kitchen_id: str, product_id: str, day: date) -> tuple[str, str] | None:
    """(quantity, unit): this kitchen's forecast demand in the SHORT row, or None."""
    answer = supplier_demand(gw.db, gw.valio, supplier_id, day, day, product_id)
    for row in answer["rows"]:
        if row["product_id"] != product_id or row["date"] != day.isoformat() or row["risk"] != "SHORT":
            continue
        for part in row["by_kitchen"]:
            if part["kitchen_id"] == kitchen_id:
                return part["demand"], row["unit"]
    return None


def _allergens_ok(gw, kitchen_id: str, product: dict, replaced: dict | None) -> bool:
    """The kitchen's allergen rule always wins: a declared hit is refused. A product without
    allergen data is refused too, with one exception: the product it replaces has no allergen
    data either (fresh vegetables, potatoes). Then the offer is no worse than what the kitchen
    already buys; the offer says `allergen_data_known: false` and the proposal it becomes
    carries ALLERGEN_DATA_MISSING, so a person checks the label."""
    if gw._allergen_refusals(kitchen_id, [product["product_id"]]):
        return False
    if product.get("allergen_data_known") is True:
        return True
    return replaced is not None and replaced.get("allergen_data_known") is not True


def create(gw, supplier_id: str, body: dict, sender: str) -> dict:
    """Store one offer for one kitchen. Refusals in the contract's order; a refusal stores
    nothing and writes nothing in a kitchen's audit log."""
    today = gw.now().date()
    fields = _validated(body, today)
    key, payload_hash = body["idempotency_key"], _hash(fields)
    stored = offers.by_key(gw.db, supplier_id, key)
    if stored is not None:
        if stored["payload_hash"] != payload_hash:
            raise GatewayError(409, "IDEMPOTENCY_KEY_REUSED", "key used with another offer")
        _audit_received(gw, stored)             # a retry after a lost audit write heals it
        return _out(stored, today)
    kitchen_id, product_id = fields["kitchen_id"], fields["product_id"]
    # An unknown kitchen answers the same: a supplier does not learn which kitchens exist.
    if kitchen_id not in consenting_kitchens(gw.db, supplier_id):
        raise GatewayError(403, "SHARING_REQUIRED", "this kitchen does not share its forecast with this supplier")
    rows = {row["product_id"]: row for row in
            get_products(gw.db, [product_id, fields["replaces_product_id"]])}
    product = rows.get(product_id)
    # The catalog is Valio's: no other supplier has a catalog product to offer yet.
    if supplier_id != VALIO or product is None or product.get("source", "valio") == "own":
        raise GatewayError(404, "PRODUCT_NOT_FOUND", "product_id is not a catalog product of this supplier")
    new_id = offers.offer_id(supplier_id, kitchen_id, product_id, fields["requested_date"])
    same = offers.by_id(gw.db, new_id)
    if same is not None:                        # one offer per supplier, kitchen, product and date
        return _out(same, today)
    day = date.fromisoformat(fields["requested_date"])
    demand = _kitchen_demand(gw, supplier_id, kitchen_id, fields["replaces_product_id"], day)
    if demand is None:
        raise GatewayError(422, "NO_SHORTAGE", "no predicted shortage of replaces_product_id for this "
                                               "kitchen on this date")
    if not _allergens_ok(gw, kitchen_id, product, rows.get(fields["replaces_product_id"])):
        raise GatewayError(422, "ALLERGEN_RULE", "the kitchen's allergen rule refuses this product, "
                                                 "or its allergen data is not known")
    if offers.count_open(gw.db, supplier_id, kitchen_id, today.isoformat()) >= OPEN_LIMIT:
        raise GatewayError(409, "OFFER_LIMIT", f"this kitchen already has {OPEN_LIMIT} open offers from this supplier")
    supplier = gw._supplier(kitchen_id, supplier_id) or {}
    doc, _ = offers.insert(gw.db, {
        "_id": new_id, "supplier_id": supplier_id, "supplier_name": supplier.get("name") or supplier_id,
        **fields, "product_name": _name(product, product_id),
        "replaces_product_name": _name(rows.get(fields["replaces_product_id"]), fields["replaces_product_id"]),
        "quantity": demand[0], "unit": demand[1], "status": offers.OPEN,
        "allergen_data_known": product.get("allergen_data_known") is True,
        "idempotency_key": key, "payload_hash": payload_hash, "sent_by": sender,
        "created_at": gw.now().isoformat(), "proposal_id": None, "decided_by": None, "decided_at": None})
    _audit_received(gw, doc)
    return _out(doc, today)


def list_offers(gw, kitchen_id: str) -> list[dict]:
    today = gw.now().date()
    rows = [_out(doc, today) for doc in offers.list_for_kitchen(gw.db, kitchen_id)]
    return sorted(rows, key=lambda row: row["status"] != offers.OPEN)      # stable: newest first inside


def _open_or_refuse(gw, kitchen_id: str, offer_id: str, human: str | None, done: str) -> tuple[dict, bool]:
    """(offer, already decided this way). 403 without a person, 404, 409 when not open."""
    if not human:
        raise GatewayError(403, "HUMAN_SESSION_REQUIRED", "only a person can answer a supplier's offer")
    doc = offers.get(gw.db, kitchen_id, offer_id)
    if doc is None:
        raise GatewayError(404, "OFFER_NOT_FOUND", "no such offer")
    if doc["status"] == done:
        return doc, True
    status = _status(doc, gw.now().date())
    if status != offers.OPEN:
        raise GatewayError(409, "OFFER_NOT_OPEN", f"this offer is {status}")
    return doc, False


def accept(gw, kitchen_id: str, offer_id: str, *, human: str | None) -> dict:
    """A person turns the offer into a normal proposal. The proposal first, with a fixed key,
    then the offer: a double click or a retry meets the same proposal."""
    doc, replay = _open_or_refuse(gw, kitchen_id, offer_id, human, offers.ACCEPTED)
    today = gw.now().date()
    if replay:
        proposal = gw.db.proposals.find_one({"_id": doc["proposal_id"], "kitchen_id": kitchen_id}) or {}
        return {"offer": _out(doc, today), "proposal_id": doc["proposal_id"],
                "proposal_status": proposal.get("status")}
    if kitchen_id not in consenting_kitchens(gw.db, doc["supplier_id"]):
        raise GatewayError(403, "SHARING_REQUIRED", "this kitchen no longer shares its forecast with this supplier")
    # The text is ours, built from catalog names. The supplier's reason is never part of it.
    proposal = gw.create_proposal(kitchen_id, {
        "product_ids": [doc["product_id"]], "quantity": doc["quantity"], "unit": doc["unit"],
        "requested_date": doc["requested_date"], "idempotency_key": f"offer:{offer_id}",
        "text": f"Offer from {doc['supplier_name']}: {doc['product_name']} in place of "
                f"{doc['replaces_product_name']}"}, human, auto_approve=False)
    if proposal["status"] == "REJECTED":        # nothing can be delivered: the offer stays open
        return {"offer": _out(doc, today), "proposal_id": proposal["proposal_id"],
                "proposal_status": "REJECTED"}
    now = gw.now().isoformat()
    updated = offers.decide(gw.db, kitchen_id, offer_id, offers.ACCEPTED,
                            proposal_id=proposal["proposal_id"], decided_by=human, decided_at=now)
    if updated is None:                         # another click decided it in the meantime
        updated = offers.get(gw.db, kitchen_id, offer_id) or doc
        if updated["status"] != offers.ACCEPTED:
            raise GatewayError(409, "OFFER_NOT_OPEN", f"this offer is {updated['status']}",
                               proposal_id=proposal["proposal_id"])
    _audit_once(gw, kitchen_id, "supplier_offer_accepted", offer_id, updated["decided_by"],
                updated["decided_at"], proposal_id=updated["proposal_id"])
    return {"offer": _out(updated, today), "proposal_id": updated["proposal_id"],
            "proposal_status": proposal["status"]}


def decline(gw, kitchen_id: str, offer_id: str, body: dict, *, human: str | None) -> dict:
    reason = body.get("reason", "")
    if not isinstance(reason, str) or len(clean_text(reason)) > DECLINE_REASON_MAX:
        raise GatewayError(422, "INVALID_REQUEST", f"reason: a string of at most {DECLINE_REASON_MAX} characters")
    doc, replay = _open_or_refuse(gw, kitchen_id, offer_id, human, offers.DECLINED)
    if not replay:
        updated = offers.decide(gw.db, kitchen_id, offer_id, offers.DECLINED, decided_by=human,
                                decided_at=gw.now().isoformat(), decline_reason=clean_text(reason))
        doc = updated or offers.get(gw.db, kitchen_id, offer_id) or doc
        if doc["status"] != offers.DECLINED:
            raise GatewayError(409, "OFFER_NOT_OPEN", f"this offer is {doc['status']}")
    _audit_once(gw, kitchen_id, "supplier_offer_declined", offer_id, doc["decided_by"],
                doc["decided_at"], reason=doc.get("decline_reason", ""))
    return _out(doc, gw.now().date())


def mount_supplier_offers(app, gw, principal, body) -> None:
    @app.post("/v1/suppliers/{supplier_id}/offers")
    async def send_offer(supplier_id: str, request: Request, who=Depends(principal)):
        who.need_supplier("supplier:offers")
        return create(gw(), supplier_id, await body(request), who.name)

    k = "/v1/kitchens/{kitchen_id}/supplier-offers"

    @app.get(k)
    def kitchen_offers(kitchen_id: str, who=Depends(principal)):
        who.need("kitchen:read", kitchen_id)
        return {"offers": list_offers(gw(), kitchen_id)}

    @app.post(k + "/{offer_id}/accept")
    def accept_offer(kitchen_id: str, offer_id: str, who=Depends(principal)):
        who.need("kitchen:read", kitchen_id)
        return accept(gw(), kitchen_id, offer_id, human=who.human)

    @app.post(k + "/{offer_id}/decline")
    async def decline_offer(kitchen_id: str, offer_id: str, request: Request, who=Depends(principal)):
        who.need("kitchen:read", kitchen_id)
        raw = await request.body()
        data = await body(request) if raw.strip() else {}
        return decline(gw(), kitchen_id, offer_id, data, human=who.human)
