"""The way out of an unknown send (#291, docs/contract.md "Resolving an unknown send").

An order with outcome UNCONFIRMED or SENT_READ_FAILED is never sent again. A person
looks at what our store knows (`lookup`), checks the supplier by their own means, and
records `placed` or `not_sent` (`resolve`). Valio's mock has no order endpoint, so the
gateway cannot ask the supplier: it only stores what the person found.

The order row is claimed first, atomically, so one order gets one resolution. The steps
after it (proposal, approval, audit entry) can each run twice without harm: a repeat of
the same resolution finishes a resolution that stopped halfway.
"""

from __future__ import annotations

from decimal import Decimal

from gateway.service import Gateway, GatewayError, _line_out, _money
from store import audit, orders, recalls
from store.order_resolution import RESOLVABLE, resolve_order

REF_MAX, NOTE_MAX = 200, 500
_PUBLIC = ("resolution", "supplier_order_ref", "note", "resolved_by", "resolved_at", "from_outcome")


def _iso(value) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else value


def _order(gw: Gateway, kitchen_id: str, order_id: str) -> dict:
    order = orders.get_order(gw.db, order_id)
    if order is None or order["kitchen_id"] != kitchen_id:
        raise GatewayError(404, "ORDER_NOT_FOUND", "no such order")
    return order


def _proposal(gw: Gateway, kitchen_id: str, order: dict) -> dict:
    return gw.db.proposals.find_one({"_id": order.get("proposal_id"), "kitchen_id": kitchen_id}) or {}


def _public(resolution: dict | None) -> dict | None:
    return None if resolution is None else {key: resolution.get(key) for key in _PUBLIC}


def lookup(gw: Gateway, kitchen_id: str, order_id: str, *, human: str | None) -> dict:
    """What our own store knows about the order. Changes nothing but the audit log."""
    if not human:
        raise GatewayError(403, "HUMAN_SESSION_REQUIRED", "only a person can look into an unknown send")
    order = _order(gw, kitchen_id, order_id)
    gw._audit(kitchen_id, "order_lookup", human, order_id=order_id, outcome=order["outcome"])
    return {"order_id": order_id, "proposal_id": order.get("proposal_id"),
            "proposal_status": _proposal(gw, kitchen_id, order).get("status"),
            "idempotency_key": order["idempotency_key"], "payload_hash": order["payload_hash"],
            "offer_id": order["offer_id"], "supplier_id": order.get("supplier_id"),
            "approved_by": order.get("approved_by"),
            "outcome": order["outcome"], "status": order["status"],
            "expected_total": _money(Decimal(str(order["expected_total"]))),
            "lines": [_line_out(ln) for ln in order["lines"]],
            "created_at": _iso(order["created_at"]), "updated_at": _iso(order["updated_at"]),
            "resolvable": order["outcome"] in RESOLVABLE,
            "resolution": _public(order.get("resolution"))}


def _text(body: dict, field: str, limit: int) -> str:
    value = body.get(field)
    if value is None:
        return ""
    if not isinstance(value, str) or len(value.strip()) > limit:
        raise GatewayError(422, "INVALID_REQUEST", f"{field}: text, at most {limit} characters")
    return value.strip()


def _wanted(body: dict) -> tuple[str, str | None, str]:
    """Validate the body: (resolution, supplier_order_ref, note)."""
    kind = body.get("resolution")
    if kind not in ("placed", "not_sent"):
        raise GatewayError(422, "INVALID_REQUEST", "resolution must be placed or not_sent")
    key = body.get("idempotency_key")
    if not isinstance(key, str) or not key.strip():
        raise GatewayError(422, "INVALID_REQUEST", "idempotency_key is required")
    ref = _text(body, "supplier_order_ref", REF_MAX)
    if kind == "placed" and not ref:
        raise GatewayError(422, "INVALID_REQUEST", "placed needs supplier_order_ref: the supplier's order reference")
    if kind == "not_sent" and body.get("supplier_order_ref") is not None:
        raise GatewayError(422, "INVALID_REQUEST", "not_sent takes no supplier_order_ref: nothing was sent")
    return kind, ref or None, _text(body, "note", NOTE_MAX)


def resolve(gw: Gateway, kitchen_id: str, order_id: str, body: dict, *, human: str | None) -> dict:
    """Record what a person found: `placed` or `not_sent`. Never sends anything."""
    if not human:
        raise GatewayError(403, "HUMAN_SESSION_REQUIRED", "only a person can resolve an unknown send")
    kind, ref, note = _wanted(body)
    order = _order(gw, kitchen_id, order_id)
    if order.get("resolution") is None:
        if order["outcome"] not in RESOLVABLE:
            raise GatewayError(409, "ORDER_NOT_RESOLVABLE",
                               "only an UNCONFIRMED or SENT_READ_FAILED order can be resolved",
                               outcome=order["outcome"])
        resolution = {"resolution": kind, "supplier_order_ref": ref, "note": note,
                      "resolved_by": human, "resolved_at": gw.now().isoformat(),
                      "from_outcome": order["outcome"], "idempotency_key": body["idempotency_key"].strip()}
        placed = kind == "placed"
        claimed = resolve_order(gw.db, kitchen_id, order_id, outcome="CONFIRMED" if placed else "NOT_SENT",
                                status="SENT" if placed else None, resolution=resolution)
        order = claimed or _order(gw, kitchen_id, order_id)   # lost the race: read who won
    stored = order.get("resolution")
    if stored is None:   # the outcome changed under us, and not through a resolution
        raise GatewayError(409, "ORDER_NOT_RESOLVABLE",
                           "only an UNCONFIRMED or SENT_READ_FAILED order can be resolved",
                           outcome=order["outcome"])
    if (stored["resolution"], stored["supplier_order_ref"]) != (kind, ref):
        raise GatewayError(409, "ALREADY_RESOLVED", "this order already has another resolution",
                           resolution=_public(stored))
    _finish(gw, kitchen_id, order)
    return {"order_id": order_id, "proposal_id": order.get("proposal_id"),
            "proposal_status": _proposal(gw, kitchen_id, order).get("status"),
            "outcome": order["outcome"], "status": order["status"], "resolution": _public(stored)}


def _finish(gw: Gateway, kitchen_id: str, order: dict) -> None:
    """Proposal, approval and audit entry for a stored resolution. Safe to run again."""
    stored, order_id = order["resolution"], order["order_id"]
    proposal = _proposal(gw, kitchen_id, order)
    # Only a proposal that still belongs to this order: never one that moved on, and
    # never a commit that another approval (another key) holds right now.
    held = {"status": "COMMITTING", "approving_key": order["idempotency_key"]}
    mine = {"_id": proposal.get("_id"), "kitchen_id": kitchen_id, "order_id": {"$in": [None, order_id]}}
    if proposal and stored["resolution"] == "placed":
        gw.db.proposals.update_one(
            {**mine, "$or": [held, {"status": {"$in": ["APPROVED", "READY", "BLOCKED_BY_RECALL"]}}]},
            {"$set": {"status": "APPROVED", "order_id": order_id}, "$unset": {"approving_key": ""}})
        if proposal.get("approval_id"):
            try:
                orders.decide_approval(gw.db, proposal["approval_id"], status="APPROVED",
                                       decided_by=order.get("approved_by") or stored["resolved_by"])
            except orders.NotPending:
                pass   # the approval call decided it before it failed
    elif proposal and (all(proposal.get(key) == value for key, value in held.items()) or
                       (proposal["status"] == "APPROVED" and proposal.get("order_id") == order_id)):
        _reopen(gw, kitchen_id, proposal, order_id)
    audit.append_event(
        gw.db,
        {"event_id": f"order_resolved:{order_id}", "kind": "order_resolved", "actor": stored["resolved_by"],
         "order_id": order_id, "proposal_id": order.get("proposal_id"),
         **{key: stored[key] for key in ("resolution", "supplier_order_ref", "note", "resolved_at", "from_outcome")}},
        {"kitchen_id": kitchen_id, "at": gw.now().isoformat()})


def _reopen(gw: Gateway, kitchen_id: str, proposal: dict, order_id: str) -> None:
    """Nothing was sent: a person can decide again. The release rule of #508: a recall
    that holds a line keeps the proposal blocked."""
    offer = orders.get_offer(gw.db, proposal["offer_id"])
    sim = offer["simulation"]
    blocked = recalls.blocked_ids(gw.db, kitchen_id)
    state = "BLOCKED_BY_RECALL" if any(ln["product_id"] in blocked for ln in sim["lines"]) else "READY"
    approval_id = proposal.get("approval_id")
    used = orders.get_approval(gw.db, approval_id) if approval_id else None
    if used is not None and used["status"] != "PENDING":
        # The used approval stays in the record; the new decision gets its own row.
        fresh, _ = orders.request_approval(
            gw.db, kitchen_id=kitchen_id, idempotency_key=f"proposal:{proposal['_id']}:after:{order_id}",
            offer_id=proposal["offer_id"], reasons=sim["mandate"]["reasons"])
        approval_id = fresh["approval_id"]
    gw.db.proposals.update_one(
        {"_id": proposal["_id"], "kitchen_id": kitchen_id, "status": proposal["status"],
         "approving_key": proposal.get("approving_key"), "order_id": {"$in": [None, order_id]}},
        {"$set": {"status": state, "approval_id": approval_id, "order_id": None},
         "$unset": {"approving_key": ""}})
