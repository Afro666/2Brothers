"""Gateway core: request -> live offers -> engine -> proposal -> human approval -> order.

No HTTP here (gateway/app.py maps routes onto these methods). Every figure a human sees
comes from `simulate`, the engine's numbers on a stored offer snapshot. Approve re-reads
live prices and stock first: if the total moved, it refuses with TOTAL_MISMATCH and
nothing is placed. There is no upstream order endpoint at Valio, so a placed order is
"placed in our gateway" (outcome CONFIRMED, status SENT) until a supplier confirms it.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
import hashlib
from typing import Callable
from uuid import uuid4

from bson.decimal128 import Decimal128
from pymongo.errors import DuplicateKeyError

from engine import (AddableRow, Candidate, Item, KitchenParams, Offer, Wanted, allergen_codes, pack_info,
                    pad_to_free_delivery, plan_request, rank_addable)
from engine.offers import RequestPlan
from engine.packs import PackDataError
from gateway.decision import decision_summary
from store import audit, orders
from store.audit import canonical
from store.history import current_stock
from store.products import get_product

DEMAND_DAYS = 28                    # usage history behind the daily demand of addable rows
REVIEW_DAYS = 3.0                   # days to the delivery after next, until order days are wired
CENT = Decimal("0.01")
TOLERANCE = Decimal("0.005")
OFFER_TTL = timedelta(minutes=15)   # Aron, 2026-11-14 (#19 answer F)
VALIO = "sup-valio"


class GatewayError(Exception):
    """An error the routes return as {"error": {"code", "message"}}."""

    def __init__(self, status: int, code: str, message: str, **extra):
        super().__init__(message)
        self.status, self.code, self.message, self.extra = status, code, message, extra


def _money(x: Decimal) -> str:
    return f"{x.quantize(CENT, ROUND_HALF_UP):f}"


def _dec(value) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _hash(payload: dict) -> str:
    return hashlib.sha256(canonical(payload).encode()).hexdigest()


class Gateway:
    def __init__(self, db, valio, *, now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self.db, self.valio, self.now = db, valio, now
        db.proposals.create_index([("kitchen_id", 1), ("idempotency_key", 1)], unique=True)
        db.orders.create_index([("kitchen_id", 1), ("idempotency_key", 1)], unique=True)
        db.approvals.create_index([("kitchen_id", 1), ("idempotency_key", 1)], unique=True)

    # ---- helpers ------------------------------------------------------------------

    def _audit(self, kitchen_id: str, kind: str, actor: str, **data) -> None:
        event = {"event_id": uuid4().hex, "kind": kind, "actor": actor, **data}
        audit.append_event(self.db, event, {"kitchen_id": kitchen_id, "at": self.now().isoformat()})

    def _params(self, kitchen_id: str) -> KitchenParams:
        doc = self.db.kitchen_settings.find_one({"_id": kitchen_id}) or {}
        return KitchenParams.from_dict(doc.get("engine"))

    def _terms(self, kitchen_id: str) -> dict:
        doc = self.db.suppliers.find_one({"kitchen_id": kitchen_id, "adapter": "valio_api"}) or {}
        return doc.get("terms") or {}

    def _offers(self, product_ids: list[str], measure: str, requested: date) -> tuple[list[Offer], list[tuple[str, str]], dict]:
        """Live Valio offers for these products, converted for the engine."""
        prices = {p["productId"]: p for p in self.valio.price(product_ids, requested.isoformat())["products"]}
        avail = {p["productId"]: p for p in self.valio.availability(product_ids, requested.isoformat())["products"]}
        offers, skipped, tax = [], [], {}
        for pid in product_ids:
            doc = get_product(self.db, pid, raw=True)
            price, stock = prices.get(pid) or {}, avail.get(pid) or {}
            if doc is None or not doc.get("raw"):
                skipped.append((pid, "not in the catalog"))
                continue
            if price.get("error") or not (price.get("catalogPrice") or {}).get("value"):
                skipped.append((pid, "no price from Valio"))
                continue
            lines = stock.get("scheduleLines") or []
            if not lines:
                skipped.append((pid, "Valio cannot deliver it on any date"))
                continue
            unit_price = _dec(price["catalogPrice"]["value"])
            cmp = price.get("comparisonPrice") or {}
            try:
                pack = pack_info(doc["raw"], price=unit_price, comparison_price=_dec(cmp.get("value")),
                                 comparison_unit=price.get("comparisonUnit"), measure=measure)
            except PackDataError as exc:
                skipped.append((pid, f"pack size unknown: {exc}"))
                continue
            line = lines[0]
            available_date = line.get("availableDate")
            offers.append(Offer(
                pid, (doc.get("names") or {}).get("en") or doc.get("name") or pid, pack, unit_price,
                _dec(line.get("availableAmount")),   # the client already turned sentinels into None
                stock.get("cutoff_passed"),
                date.fromisoformat(available_date) if available_date else None,
                bool(stock.get("salesBlock") or line.get("salesBlock")),
                not allergen_codes(doc),          # unknown allergen data is never safe (S02, S04)
            ))
            tax[pid] = _dec((price.get("tax") or {}).get("taxRate")) or Decimal(0)
        return offers, skipped, tax

    def _simulate(self, kitchen_id: str, plan: RequestPlan, tax: dict, skipped: list) -> dict:
        terms = self._terms(kitchen_id)
        threshold = _dec(terms.get("free_delivery_threshold_eur"))
        fee_value = _dec(terms.get("delivery_fee_eur"))
        net = plan.total
        vat = sum((ln.total * tax.get(ln.product_id, Decimal(0)) / 100 for ln in plan.lines), Decimal(0))
        if threshold is None or fee_value is None:
            mov_gap = fee = None          # unknown terms: never shown as zero
        else:
            mov_gap = max(threshold - net, Decimal(0))
            fee = fee_value if mov_gap > 0 else Decimal(0)
        expected = net + vat + (fee or Decimal(0))
        excluded = [*plan.excluded, *skipped]
        reasons = [f"{pid}: {why}" for pid, why in excluded]
        if plan.shortfall > 0:
            reasons.append(f"{plan.shortfall.normalize():f} {plan.measure} of the request cannot be covered for this date.")
        if any(ln.unknown_stock for ln in plan.lines):
            reasons.append("Some lines have stock Valio does not report: not confirmed until Valio confirms.")
        verdict = "NEEDS_APPROVAL" if plan.lines else "REFUSED"
        return {
            "currency": "EUR",
            "total_ex_vat": _money(net), "vat": _money(vat),
            "delivery_fee": None if fee is None else _money(fee),
            "mov_gap": None if mov_gap is None else _money(mov_gap),
            "expected_total": _money(expected),
            "shortfall": f"{plan.shortfall.normalize():f}", "measure": plan.measure,
            "mandate": {"verdict": verdict, "reasons": reasons,
                        "reason_codes": list(plan.reason_codes), "warnings": list(plan.warnings)},
            "lines": [{"product_id": ln.product_id, "quantity": f"{ln.quantity.normalize():f}",
                       "unit": ln.unit, "unit_price": _money(ln.unit_price), "total": _money(ln.total),
                       "why": ln.why, "unknown_stock": ln.unknown_stock,
                       "reason_codes": list(ln.reason_codes)} for ln in plan.lines],
            "excluded": [{"product_id": pid, "reason": why} for pid, why in excluded],
            "alternative": None if plan.alternative is None else {
                "total_ex_vat": _money(plan.alternative.total),
                "lines": [{"product_id": ln.product_id, "quantity": f"{ln.quantity.normalize():f}",
                           "unit": ln.unit, "total": _money(ln.total), "why": ln.why}
                          for ln in plan.alternative.lines]},
        }

    def _quote(self, kitchen_id: str, request: dict) -> dict:
        requested = date.fromisoformat(request["requested_date"])
        measure = request["unit"]
        need = Decimal(str(request["quantity"]))
        if need <= 0:
            raise GatewayError(422, "INVALID_REQUEST", "quantity must be positive")
        offers, skipped, tax = self._offers(list(request["product_ids"]), measure, requested)
        plan = plan_request(need, measure, offers, requested, self._params(kitchen_id),
                            event=bool(request.get("event")))
        sim = self._simulate(kitchen_id, plan, tax, skipped)
        now = self.now()
        offer = orders.save_offer(self.db, {
            "offer_id": uuid4().hex, "kitchen_id": kitchen_id, "supplier_id": VALIO,
            "request": request, "valid_until": (now + OFFER_TTL).isoformat(),
            "simulation": sim, "fetched_at": now})
        return offer

    # ---- kitchen side ---------------------------------------------------------------

    def create_proposal(self, kitchen_id: str, body: dict, actor: str) -> dict:
        for field in ("product_ids", "quantity", "unit", "requested_date", "idempotency_key"):
            if not body.get(field):
                raise GatewayError(422, "INVALID_REQUEST", f"{field} is required")
        request = {k: body[k] for k in ("product_ids", "quantity", "unit", "requested_date")}
        request["text"] = body.get("text") or ""
        if body.get("event"):
            request["event"] = True       # one-off demand (S05): EVENT_LINE, kept out of the forecast
        key = body["idempotency_key"]
        stored = self.db.proposals.find_one({"kitchen_id": kitchen_id, "idempotency_key": key})
        if stored:
            if stored["payload_hash"] != _hash(request):
                raise GatewayError(409, "IDEMPOTENCY_KEY_REUSED", "key used with another request")
            return self._proposal_out(stored)
        offer = self._quote(kitchen_id, request)
        sim = offer["simulation"]
        doc = {"_id": uuid4().hex, "kitchen_id": kitchen_id, "idempotency_key": key,
               "payload_hash": _hash(request), "request": request, "offer_id": offer["offer_id"],
               "status": "READY" if sim["lines"] else "REJECTED", "created_by": actor,
               "created_at": self.now(), "approval_id": None, "order_id": None}
        try:
            self.db.proposals.insert_one(doc)
        except DuplicateKeyError:
            return self.create_proposal(kitchen_id, body, actor)
        if sim["lines"]:
            approval, _ = orders.request_approval(
                self.db, kitchen_id=kitchen_id, idempotency_key=f"proposal:{doc['_id']}",
                offer_id=offer["offer_id"], reasons=sim["mandate"]["reasons"])
            self.db.proposals.update_one({"_id": doc["_id"]}, {"$set": {"approval_id": approval["approval_id"]}})
            doc["approval_id"] = approval["approval_id"]
        self._audit(kitchen_id, "proposal_created", actor, proposal_id=doc["_id"],
                    offer_id=offer["offer_id"], expected_total=sim["expected_total"],
                    verdict=sim["mandate"]["verdict"])
        self._audit(kitchen_id, "decision_summary", actor, proposal_id=doc["_id"],
                    offer_id=offer["offer_id"], summary=self._summary(request, sim)["text"])
        return self._proposal_out(doc)

    def _proposal_out(self, doc: dict) -> dict:
        offer = orders.get_offer(self.db, doc["offer_id"])
        return {"proposal_id": doc["_id"], "status": doc["status"], "request": doc["request"],
                "substitute_options": doc.get('substitute_options', []),
                "offer_id": doc["offer_id"], "valid_until": offer["valid_until"],
                "approval_id": doc.get("approval_id"), "order_id": doc.get("order_id"),
                **offer["simulation"],
                "decision_summary": self._summary(doc["request"], offer["simulation"])}

    def _summary(self, request: dict, sim: dict) -> dict:
        ids = {ln["product_id"] for ln in sim.get("lines") or []} | {e["product_id"] for e in sim.get("excluded") or []}
        names = {d["_id"]: (d.get("names") or {}).get("en")
                 for d in self.db.products.find({"_id": {"$in": sorted(ids)}}, {"names": 1})}
        return decision_summary(request, sim, names)

    def get_proposal(self, kitchen_id: str, proposal_id: str) -> dict:
        doc = self.db.proposals.find_one({"_id": proposal_id, "kitchen_id": kitchen_id})
        if doc is None:
            raise GatewayError(404, "PROPOSAL_NOT_FOUND", "no such proposal")
        return self._proposal_out(doc)

    def list_proposals(self, kitchen_id: str) -> list[dict]:
        return [self._proposal_out(d) for d in
                self.db.proposals.find({"kitchen_id": kitchen_id}).sort("created_at", -1).limit(100)]

    def approve(self, kitchen_id: str, proposal_id: str, body: dict, *, human: str | None) -> dict:
        """A human says yes to the figure they saw. Re-check live; place only if unchanged."""
        if not human:
            raise GatewayError(403, "HUMAN_SESSION_REQUIRED", "only a person can approve an order")
        key, seen = body.get("idempotency_key"), body.get("expected_total")
        if not key or seen is None:
            raise GatewayError(422, "INVALID_REQUEST", "expected_total and idempotency_key are required")
        doc = self.db.proposals.find_one({"_id": proposal_id, "kitchen_id": kitchen_id})
        if doc is None:
            raise GatewayError(404, "PROPOSAL_NOT_FOUND", "no such proposal")
        if doc["status"] != "READY":
            return self._approved_or_conflict(kitchen_id, proposal_id, key)
        stored = orders.get_offer(self.db, doc["offer_id"])
        if Decimal(str(seen)) - Decimal(stored["simulation"]["expected_total"]) != 0:
            raise GatewayError(409, "TOTAL_MISMATCH", "this is not the total of the proposal",
                               expected_total=stored["simulation"]["expected_total"])
        # Claim the proposal atomically: one proposal places at most one order, even when
        # two approvals with different keys arrive together (double click, two tabs).
        claimed = self.db.proposals.find_one_and_update(
            {"_id": proposal_id, "kitchen_id": kitchen_id, "status": "READY", "offer_id": stored["offer_id"]},
            {"$set": {"status": "APPROVING", "approving_key": key}})
        if claimed is None:
            return self._approved_or_conflict(kitchen_id, proposal_id, key)
        try:
            return self._place(kitchen_id, proposal_id, doc, stored, seen, key, human)
        except BaseException:
            self.db.proposals.update_one({"_id": proposal_id, "status": "APPROVING", "approving_key": key},
                                         {"$set": {"status": "READY"}, "$unset": {"approving_key": ""}})
            raise

    def _approved_or_conflict(self, kitchen_id: str, proposal_id: str, key: str) -> dict:
        """Not READY: replay the order placed with this key, else 409 NOT_PENDING."""
        doc = self.db.proposals.find_one({"_id": proposal_id, "kitchen_id": kitchen_id}) or {}
        if doc.get("status") == "APPROVED" and doc.get("order_id"):
            order = orders.get_order(self.db, doc["order_id"])
            if order["idempotency_key"] == key:
                return {"proposal_id": proposal_id, **self._order_out(order)}
            raise GatewayError(409, "NOT_PENDING", "this proposal is already approved")
        raise GatewayError(409, "NOT_PENDING", f"proposal is {doc.get('status')}")

    def _place(self, kitchen_id: str, proposal_id: str, doc: dict, stored: dict, seen, key: str, human: str) -> dict:
        # Live re-check: price or stock may have moved since the human looked.
        fresh = self._quote(kitchen_id, doc["request"])
        new_total = Decimal(fresh["simulation"]["expected_total"])
        if abs(new_total - Decimal(str(seen))) > TOLERANCE or \
                fresh["simulation"]["lines"] != stored["simulation"]["lines"]:
            self.db.proposals.update_one({"_id": proposal_id}, {"$set": {"offer_id": fresh["offer_id"]}})
            self._audit(kitchen_id, "total_mismatch", human, proposal_id=proposal_id,
                        seen=str(seen), now=fresh["simulation"]["expected_total"])
            raise GatewayError(409, "TOTAL_MISMATCH", "the price or stock moved; look at the new total",
                               expected_total=fresh["simulation"]["expected_total"])
        sim = stored["simulation"]
        # A person's consent is not supplier stock confirmation. Keep unknown
        # lines visible in proposals, but never record a placed order for them.
        if any(line.get("unknown_stock") is not False for line in sim["lines"]):
            raise GatewayError(409, "STOCK_UNKNOWN", "supplier stock must be confirmed before placement")
        payload = {"offer_id": stored["offer_id"], "expected_total": sim["expected_total"], "lines": sim["lines"]}
        order, created = orders.record_attempt(
            self.db, kitchen_id=kitchen_id, idempotency_key=key, offer_id=stored["offer_id"],
            expected_total=Decimal128(sim["expected_total"]),   # exact decimal in any Mongo
            lines=[{k: v for k, v in ln.items() if k != "why"} for ln in sim["lines"]],
            payload_hash=_hash(payload), proposal_id=proposal_id, supplier_id=VALIO, approved_by=human)
        if created:
            if doc.get("approval_id"):
                orders.decide_approval(self.db, doc["approval_id"], status="APPROVED", decided_by=human)
            # No upstream order endpoint: the order is placed in our gateway, waiting for the supplier.
            order = orders.set_outcome(self.db, order["order_id"], outcome="CONFIRMED", status="SENT")
            self.db.proposals.update_one({"_id": proposal_id},
                                         {"$set": {"status": "APPROVED", "order_id": order["order_id"]}})
            self._audit(kitchen_id, "order_placed", human, proposal_id=proposal_id,
                        order_id=order["order_id"], expected_total=sim["expected_total"])
        else:   # the key already placed an order: nothing new placed here, release the claim
            self.db.proposals.update_one({"_id": proposal_id, "status": "APPROVING", "approving_key": key},
                                         {"$set": {"status": "READY"}, "$unset": {"approving_key": ""}})
        return {"proposal_id": proposal_id, **self._order_out(order)}

    def reject(self, kitchen_id: str, proposal_id: str, body: dict, *, human: str | None) -> dict:
        if not human:
            raise GatewayError(403, "HUMAN_SESSION_REQUIRED", "only a person can reject an order")
        doc = self.db.proposals.find_one({"_id": proposal_id, "kitchen_id": kitchen_id})
        if doc is None:
            raise GatewayError(404, "PROPOSAL_NOT_FOUND", "no such proposal")
        if doc["status"] == "REJECTED":
            return {"proposal_id": proposal_id, "status": "REJECTED"}
        if doc["status"] != "READY":
            raise GatewayError(409, "NOT_PENDING", f"proposal is {doc['status']}")
        reason = (body.get("reason") or "").strip()
        if doc.get("approval_id"):
            orders.decide_approval(self.db, doc["approval_id"], status="REJECTED", decided_by=human, reason=reason)
        self.db.proposals.update_one({"_id": proposal_id}, {"$set": {"status": "REJECTED", "reject_reason": reason}})
        self._audit(kitchen_id, "proposal_rejected", human, proposal_id=proposal_id, reason=reason)
        return {"proposal_id": proposal_id, "status": "REJECTED"}

    @staticmethod
    def _order_out(order: dict) -> dict:
        return {"order_id": order["order_id"], "outcome": order["outcome"], "status": order["status"],
                "expected_total": _money(Decimal(str(order["expected_total"]))),
                "lines": order["lines"], "created_at": order["created_at"].isoformat()
                if hasattr(order["created_at"], "isoformat") else order["created_at"]}

    def list_orders(self, kitchen_id: str) -> list[dict]:
        return [self._order_out(o) for o in orders.list_orders(self.db, kitchen_id)]

    def get_order(self, kitchen_id: str, order_id: str) -> dict:
        order = orders.get_order(self.db, order_id)
        if order is None or order["kitchen_id"] != kitchen_id:
            raise GatewayError(404, "ORDER_NOT_FOUND", "no such order")
        return self._order_out(order)

    # ---- Buyer agent tools (docs/contract.md "Team gateway interfaces") ---------------

    def create_need(self, kitchen_id: str, body: dict, actor: str) -> dict:
        """The trusted app stores the need; the model only picks products for it."""
        for field in ("quantity", "unit", "requested_date"):
            if not body.get(field):
                raise GatewayError(422, "INVALID_REQUEST", f"{field} is required")
        date.fromisoformat(body["requested_date"])
        if Decimal(str(body["quantity"])) <= 0:
            raise GatewayError(422, "INVALID_REQUEST", "quantity must be positive")
        need = {"_id": uuid4().hex, "kitchen_id": kitchen_id, "quantity": str(body["quantity"]),
                "unit": body["unit"], "requested_date": body["requested_date"],
                "text": body.get("text") or "", "created_by": actor, "created_at": self.now()}
        self.db.needs.insert_one(need)
        return {"need_id": need["_id"], **{k: need[k] for k in ("quantity", "unit", "requested_date", "text")}}

    def tool_get_offer(self, kitchen_id: str, body: dict) -> dict:
        need = self.db.needs.find_one({"_id": body.get("need_id"), "kitchen_id": kitchen_id})
        if need is None:
            raise GatewayError(422, "INVALID_NEED", "unknown need_id")
        ids = body.get("product_ids") or []
        if not ids or not all(isinstance(p, str) and p for p in ids) or len(ids) > 50:
            raise GatewayError(422, "INVALID_REQUEST", "product_ids: 1 to 50 product codes")
        if body.get("requested_date") and body["requested_date"] != need["requested_date"]:
            raise GatewayError(422, "INVALID_REQUEST", "requested_date must match the need")
        request = {"product_ids": ids, "quantity": need["quantity"], "unit": need["unit"],
                   "requested_date": need["requested_date"], "text": need["text"], "need_id": need["_id"]}
        return offer_out(self._quote(kitchen_id, request))

    def _kitchen_offer(self, kitchen_id: str, offer_id: str | None) -> dict:
        offer = orders.get_offer(self.db, offer_id) if offer_id else None
        if offer is None or offer.get("kitchen_id") != kitchen_id:
            raise GatewayError(404, "OFFER_NOT_FOUND", "no such offer")
        return offer

    def tool_simulate(self, kitchen_id: str, body: dict) -> dict:
        offer = self._kitchen_offer(kitchen_id, body.get("offer_id"))
        if datetime.fromisoformat(offer["valid_until"]) <= self.now():
            raise GatewayError(409, "OFFER_EXPIRED", "refresh the offer with get_offer")
        return offer_out(offer)

    def tool_request_approval(self, kitchen_id: str, body: dict, actor: str) -> dict:
        key = body.get("idempotency_key")
        if not isinstance(key, str) or not key.strip():
            raise GatewayError(422, "MISSING_IDEMPOTENCY_KEY", "idempotency_key is required")
        offer = self._kitchen_offer(kitchen_id, body.get("offer_id"))
        existing = self.db.proposals.find_one({"kitchen_id": kitchen_id, "offer_id": offer["offer_id"]})
        if existing:
            if existing["idempotency_key"] != key:
                raise GatewayError(409, "IDEMPOTENCY_KEY_REUSED", "this offer already has an approval request")
            return {"approval_id": existing["approval_id"], "proposal_id": existing["_id"], "status": "PENDING"}
        sim = offer["simulation"]
        if not sim["lines"]:
            raise GatewayError(422, "NOTHING_TO_APPROVE", "the offer has no lines")
        doc = {"_id": uuid4().hex, "kitchen_id": kitchen_id, "idempotency_key": key,
               "payload_hash": _hash(offer["request"]), "request": offer["request"],
               "offer_id": offer["offer_id"], "status": "READY", "created_by": actor,
               "created_at": self.now(), "approval_id": None, "order_id": None}
        try:
            self.db.proposals.insert_one(doc)
        except DuplicateKeyError:
            raise GatewayError(409, "IDEMPOTENCY_KEY_REUSED", "key used for another offer") from None
        approval, _ = orders.request_approval(
            self.db, kitchen_id=kitchen_id, idempotency_key=f"proposal:{doc['_id']}",
            offer_id=offer["offer_id"], reasons=sim["mandate"]["reasons"])
        self.db.proposals.update_one({"_id": doc["_id"]}, {"$set": {"approval_id": approval["approval_id"]}})
        self._audit(kitchen_id, "approval_requested", actor, proposal_id=doc["_id"],
                    offer_id=offer["offer_id"], expected_total=sim["expected_total"])
        self._audit(kitchen_id, "decision_summary", actor, proposal_id=doc["_id"],
                    offer_id=offer["offer_id"], summary=self._summary(offer["request"], sim)["text"])
        return {"approval_id": approval["approval_id"], "proposal_id": doc["_id"], "status": "PENDING"}

    def tool_place_order(self, kitchen_id: str, body: dict) -> dict:
        """The agent can never place an order itself: only a human approval places one."""
        key = body.get("idempotency_key")
        if not isinstance(key, str) or not key.strip():
            raise GatewayError(422, "MISSING_IDEMPOTENCY_KEY", "idempotency_key is required")
        offer = self._kitchen_offer(kitchen_id, body.get("offer_id"))
        doc = self.db.proposals.find_one({"kitchen_id": kitchen_id, "offer_id": offer["offer_id"]})
        if doc is None or doc["status"] != "APPROVED" or not doc.get("order_id"):
            raise GatewayError(403, "NEEDS_APPROVAL", "a person must approve this order in the approval inbox")
        order = orders.get_order(self.db, doc["order_id"])
        if abs(Decimal(str(body.get("expected_total") or "0")) - Decimal(str(order["expected_total"]))) > TOLERANCE:
            raise GatewayError(409, "TOTAL_MISMATCH", "this is not the approved total",
                               expected_total=_money(Decimal(str(order["expected_total"]))))
        return self._order_out(order)

    # ---- addable products (#129) ------------------------------------------------------

    def _daily_demand(self, kitchen_id: str, product_id: str, days: int = DEMAND_DAYS) -> float:
        """Average of used + short per recorded day. No usage recorded: 0, so no order."""
        since = self.now() - timedelta(days=days)
        totals: dict = {}
        for row in self.db.kitchen_stock.find({"meta.kitchen_id": kitchen_id, "meta.product_id": product_id,
                                               "ts": {"$gte": since}}):
            if row.get("used") is None:
                continue
            day = row["ts"].date()
            totals[day] = totals.get(day, Decimal(0)) + _dec(row["used"]) + (_dec(row.get("short")) or Decimal(0))
        return float(sum(totals.values()) / len(totals)) if totals else 0.0

    def addable(self, kitchen_id: str, proposal_id: str) -> dict:
        """What the buyer can add to this proposal, most probable first (engine.rank_addable).

        Candidates are the products in the kitchen's latest stock count. Quantities come
        from the engine, prices from live Valio. A product without a price is shown but
        cannot be added; a product whose pack size is unknown is listed under `skipped`.
        """
        doc = self.db.proposals.find_one({"_id": proposal_id, "kitchen_id": kitchen_id})
        if doc is None:
            raise GatewayError(404, "PROPOSAL_NOT_FOUND", "no such proposal")
        offer = orders.get_offer(self.db, doc["offer_id"])
        on_proposal = {ln["product_id"] for ln in offer["simulation"]["lines"]}
        counts = [c for c in current_stock(self.db, kitchen_id) if c["product_id"] not in on_proposal]
        requested = doc["request"]["requested_date"]
        prices = {}
        if counts:
            prices = {p["productId"]: p for p in
                      self.valio.price([c["product_id"] for c in counts], requested)["products"]}
        terms = self._terms(kitchen_id)
        lead = float(terms.get("lead_time_days") or 1)
        candidates, skipped = [], []
        for count in counts:
            pid = count["product_id"]
            product = get_product(self.db, pid, raw=True)
            if product is None or not product.get("raw"):
                skipped.append({"product_id": pid, "reason": "not in the catalog"})
                continue
            price = prices.get(pid) or {}
            value = None if price.get("error") else (price.get("catalogPrice") or {}).get("value")
            unit_price = _dec(value) if value else None
            cmp = price.get("comparisonPrice") or {}
            measure = product["raw"]["baseUnit"] if count["unit"] == "PCS" else count["unit"]
            try:
                pack = pack_info(product["raw"], price=unit_price, comparison_price=_dec(cmp.get("value")),
                                 comparison_unit=price.get("comparisonUnit"), measure=measure)
            except PackDataError as exc:
                skipped.append({"product_id": pid, "reason": f"pack size unknown: {exc}"})
                continue
            on_hand = count.get("on_hand")
            item = Item(pid, pack, daily_demand=self._daily_demand(kitchen_id, pid), lead_time_days=lead,
                        review_days=REVIEW_DAYS, on_hand=None if on_hand is None else float(on_hand),
                        abc=product.get("abc"), category=product.get("category"))
            names = product.get("names") or {}
            candidates.append(Candidate(item, name=names.get("en") or names.get("fi") or pid,
                                        unit_price=unit_price))
        rows = rank_addable(candidates, self._params(kitchen_id))
        # S06: if the proposal is under free delivery, suggest the smallest wanted lines that close it.
        wanted = [Wanted(r.product_id, r.name, r.suggested_qty, r.unit, r.unit_price) for r in rows
                  if r.addable and r.suggested_qty > 0]
        pad = pad_to_free_delivery(Decimal(offer["simulation"]["total_ex_vat"]),
                                   threshold=_dec(terms.get("free_delivery_threshold_eur")),
                                   fee=_dec(terms.get("delivery_fee_eur")), wanted=wanted)
        return {"proposal_id": proposal_id, "rows": [_addable_out(r) for r in rows], "skipped": skipped,
                "mov_padding": {"add": [{"product_id": w.product_id, "quantity": _qty(w.quantity), "unit": w.unit,
                                         "value": _money(w.value)} for w in pad.add],
                                "total_ex_vat": _money(pad.total), "saves_fee": _money(pad.saves_fee),
                                "reason_codes": list(pad.reason_codes), "why": pad.why}}

    # ---- forecasts: prove the prediction (#275) ---------------------------------------

    def forecast_accuracy(self, kitchen_id: str, start: str, end: str) -> dict:
        """Past forecasts (as made the Monday before) against what the kitchen really needed."""
        from engine.forecast import accuracy, accuracy_by_week
        from store.history import forecast_vs_actual
        d0, d1 = date.fromisoformat(start), date.fromisoformat(end)
        if d1 < d0 or (d1 - d0).days > 400:
            raise GatewayError(422, "INVALID_REQUEST", "from must be before to, at most 400 days")
        out = {"kitchen_id": kitchen_id, "from": start, "to": end, "methods": {}}
        for method, collection in (("engine", "forecasts"), ("weekday-average", "forecast_baseline")):
            pairs = forecast_vs_actual(self.db, kitchen_id, d0, d1, collection)
            out["methods"][method] = {"total": accuracy(pairs), "weeks": accuracy_by_week(pairs)}
        return out

    def forecast(self, kitchen_id: str, start: str, end: str) -> dict:
        """The engine's forecast per product and day (future days: made today)."""
        d0, d1 = date.fromisoformat(start), date.fromisoformat(end)
        if d1 < d0 or (d1 - d0).days > 120:
            raise GatewayError(422, "INVALID_REQUEST", "from must be before to, at most 120 days")
        lo = datetime.combine(d0, datetime.min.time(), tzinfo=timezone.utc)
        hi = datetime.combine(d1, datetime.max.time(), tzinfo=timezone.utc)
        rows = self.db.forecasts.find({"meta.kitchen_id": kitchen_id, "ts": {"$gte": lo, "$lte": hi}}).sort("ts", 1)
        return {"kitchen_id": kitchen_id, "lines": [
            {"product_id": r["meta"]["product_id"], "date": r["ts"].date().isoformat(),
             "need": f"{Decimal(str(r['need'])).normalize():f}", "unit": r["unit"],
             "made_on": r.get("made_on"), "why": r.get("why")} for r in rows]}

    def audit_log(self, kitchen_id: str) -> list[dict]:
        return [{"seq": e["seq"], **e["event"], "at": e["server"].get("at")}
                for e in audit.list_events(self.db, kitchen_id=kitchen_id)]


def _qty(x) -> str | None:
    return None if x is None else f"{Decimal(str(x)).normalize():f}"


def _addable_out(r: AddableRow) -> dict:
    return {"rank": r.rank, "product_id": r.product_id, "name": r.name,
            "on_hand": _qty(r.on_hand), "on_order": _qty(r.on_order),
            "suggested_qty": _qty(r.suggested_qty), "unit": r.unit,
            "unit_price": None if r.unit_price is None else _money(r.unit_price),
            "addable": r.addable, "timing": r.timing.name, "days_of_stock": _qty(r.days_of_stock),
            "reason_codes": list(r.reason_codes), "why": r.why}


def offer_out(offer: dict) -> dict:
    return {"offer_id": offer["offer_id"], "valid_until": offer["valid_until"], **offer["simulation"]}


__all__ = ["Gateway", "GatewayError", "offer_out", "asdict"]
