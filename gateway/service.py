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
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
import hashlib
import logging
from typing import Callable
from uuid import uuid4

from bson.decimal128 import Decimal128
from pymongo.errors import DuplicateKeyError

from engine import (AddableRow, Candidate, Item, KitchenParams, Offer, Wanted, allergen_rule_hits, pack_info,
                    pad_to_free_delivery, plan_request, rank_addable)
from engine.offers import RequestPlan
from engine.packs import PackDataError
from gateway import options
from gateway.decision import decision_summary
from gateway.partial_fill import partial_out
from gateway.suppliers import VALIO, ManualAdapter, ValioAdapter, apply_discount_tiers
from store import audit, orders, recalls
from store.audit import canonical
from store.history import current_stock

DEMAND_DAYS = 28                    # usage history behind the daily demand of addable rows
REVIEW_DAYS = 3.0                   # days to the delivery after next, until order days are wired
CENT = Decimal("0.01")
TOLERANCE = Decimal("0.005")
log = logging.getLogger(__name__)
OFFER_TTL = timedelta(minutes=15)   # Aron, 2026-11-14 (#19 answer F)


class GatewayError(Exception):
    """An error the routes return as {"error": {"code", "message"}}."""

    def __init__(self, status: int, code: str, message: str, **extra):
        super().__init__(message)
        self.status, self.code, self.message, self.extra = status, code, message, extra


def _money(x: Decimal) -> str:
    return f"{x.quantize(CENT, ROUND_HALF_UP):f}"


def _dec(value) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _text(value) -> str | None:
    return None if value is None else str(value)


_LINE_NUMBERS = ("reliability", "carbon_kg_co2e_per_kg")


def _line_out(line: dict) -> dict:
    """A stored offer or order line as the API answers it: the two dataset values are numbers
    (docs/contract.md), kept as text in Mongo because the store refuses a binary float (#570)."""
    return {**line, **{key: float(line[key]) for key in _LINE_NUMBERS if line.get(key) is not None}}


def _hash(payload: dict) -> str:
    return hashlib.sha256(canonical(payload).encode()).hexdigest()


class Gateway:
    def __init__(self, db, valio, *, now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
                 search: Callable | None = None):
        self.db, self.valio, self.now = db, valio, now
        self._search = search          # catalog search; default: store.search (Atlas Search)
        db.proposals.create_index([("kitchen_id", 1), ("idempotency_key", 1)], unique=True)
        db.orders.create_index([("kitchen_id", 1), ("idempotency_key", 1)], unique=True)
        db.approvals.create_index([("kitchen_id", 1), ("idempotency_key", 1)], unique=True)

    # ---- helpers ------------------------------------------------------------------

    def _audit(self, kitchen_id: str, kind: str, actor: str, **data) -> None:
        event = {"event_id": uuid4().hex, "kind": kind, "actor": actor, **data}
        audit.append_event(self.db, event, {"kitchen_id": kitchen_id, "at": self.now().isoformat()})
        try:    # webhooks (#277): after the event is stored; a receiver can never break an order
            from gateway import webhooks
            webhooks.dispatch(self.db, kitchen_id, kind, data)
        except Exception:
            pass

    def _params(self, kitchen_id: str) -> KitchenParams:
        doc = self.db.kitchen_settings.find_one({"_id": kitchen_id}) or {}
        return KitchenParams.from_dict(doc.get("engine"))

    def _standing_orders(self, kitchen_id: str) -> dict[str, Decimal]:
        """Per product: the standing order per delivery, in sales units (#380, S08)."""
        doc = self.db.kitchen_settings.find_one(
            {"_id": kitchen_id}, {"standing_orders": 1, "engine.standing_orders": 1}) or {}
        # PUT /settings stores it under `engine` (store/repository.py); older rows at the top.
        stored = (doc.get("engine") or {}).get("standing_orders") or doc.get("standing_orders") or {}
        out = {}
        for pid, qty in stored.items():
            try:
                value = _dec(qty)
            except (InvalidOperation, ValueError, TypeError):
                continue                   # nothing validates the map on write yet: skip bad values
            if value is not None and value.is_finite() and value > 0:
                out[pid] = value
        return out

    def _terms(self, kitchen_id: str) -> dict:
        doc = self.db.suppliers.find_one({"kitchen_id": kitchen_id, "adapter": "valio_api"}) or {}
        return doc.get("terms") or {}

    def _supplier(self, kitchen_id: str, supplier_id: str) -> dict | None:
        """The kitchen's supplier row; Valio is the row with the `valio_api` adapter."""
        if supplier_id == VALIO:
            doc = self.db.suppliers.find_one({"kitchen_id": kitchen_id, "adapter": "valio_api"}) or {}
            return {"name": "Valio Aimo", "adapter": "valio_api", **doc, "supplier_id": VALIO}
        return self.db.suppliers.find_one({"kitchen_id": kitchen_id, "supplier_id": supplier_id})

    def _offers(self, kitchen_id: str, product_ids: list[str], measure: str,
                requested: date) -> tuple[list[Offer], list[tuple[str, str]], dict, dict[str, str], dict]:
        """Live offers per supplier (gateway/suppliers.py), the supplier of each product, and per
        product the delivery facts each line shows: available_date, cutoff_passed, closing_time (#531).
        A catalog product is Valio's; an own product belongs to its `supplier_id`."""
        groups: dict[str, list[str]] = {}
        for pid in product_ids:
            row = self.db.products.find_one({"_id": pid, "source": "own", "kitchen_id": kitchen_id},
                                            {"supplier_id": 1})
            groups.setdefault(row["supplier_id"] if row else VALIO, []).append(pid)
        offers, skipped, tax, supplier_of, when = [], [], {}, {}, {}
        for supplier_id, ids in groups.items():
            supplier = self._supplier(kitchen_id, supplier_id)
            if supplier is None:
                skipped.extend((pid, f"supplier {supplier_id} is not set up") for pid in ids)
                continue
            adapter = (ValioAdapter(self.db, self.valio) if supplier_id == VALIO
                       else ManualAdapter(self.db, kitchen_id, supplier, self.now))
            found, left_out, rates = adapter.offers(ids, measure, requested)
            when.update(adapter.when)
            offers.extend(found)
            skipped.extend(left_out)
            tax.update(rates)
            supplier_of.update({pid: supplier_id for pid in ids})
        return offers, skipped, tax, supplier_of, when

    def _approve_unconfirmed_manual(self, kitchen_id: str) -> bool:
        """#631: the kitchen's switch, stored with the engine settings. Off unless set to true."""
        doc = self.db.kitchen_settings.find_one({"_id": kitchen_id}, {"engine.approve_unconfirmed_manual": 1}) or {}
        return (doc.get("engine") or {}).get("approve_unconfirmed_manual") is True

    def _block(self, supplier: dict, lines: list, tax: dict) -> dict:
        """One supplier's part of a basket: its lines and its own user-set terms."""
        terms = supplier.get("terms") or {}
        threshold = _dec(terms.get("free_delivery_threshold_eur"))
        fee_value = _dec(terms.get("delivery_fee_eur"))
        net = sum((ln.total for ln in lines), Decimal(0))
        rates = [tax.get(ln.product_id, Decimal(0)) for ln in lines]
        vat = None if any(rate is None for rate in rates) else sum(
            (ln.total * rate / 100 for ln, rate in zip(lines, rates)), Decimal(0))
        if threshold is None or fee_value is None:
            mov_gap = fee = None          # unknown terms: never shown as zero
        else:
            mov_gap = max(threshold - net, Decimal(0))
            fee = fee_value if mov_gap > 0 else Decimal(0)
        return {"supplier_id": supplier["supplier_id"], "name": supplier.get("name"),
                "net": net, "vat": vat, "mov_gap": mov_gap, "fee": fee,
                "expected": net + (vat or Decimal(0)) + (fee or Decimal(0)), "lines": lines}

    def _simulate(self, kitchen_id: str, plan: RequestPlan, tax: dict, skipped: list,
                  supplier_of: dict[str, str] | None = None, when: dict | None = None) -> dict:
        supplier_of, when = supplier_of or {}, when or {}
        unknown = {"available_date": None, "cutoff_passed": None, "closing_time": None}
        manual_ok = self._approve_unconfirmed_manual(kitchen_id)
        by_supplier: dict[str, list] = {}
        for ln in plan.lines:
            by_supplier.setdefault(supplier_of.get(ln.product_id, VALIO), []).append(ln)
        blocks = [self._block(self._supplier(kitchen_id, sid), lines, tax)
                  for sid, lines in by_supplier.items()]
        # The top-level gap and fee are those of the only supplier; with several, read `blocks`.
        # No line at all: Valio's terms on an empty basket, as before #73.
        if len(blocks) > 1:
            mov_gap = fee = None
        else:
            only = blocks[0] if blocks else self._block(self._supplier(kitchen_id, VALIO), [], tax)
            mov_gap, fee = only["mov_gap"], only["fee"]
        net = plan.total
        vat = sum((b["vat"] or Decimal(0) for b in blocks), Decimal(0))
        expected = sum((b["expected"] for b in blocks), Decimal(0)) if blocks else only["expected"]
        excluded = [*plan.excluded, *skipped]
        reasons = [f"{pid}: {why}" for pid, why in excluded]
        if plan.shortfall > 0:
            reasons.append(f"{plan.shortfall.normalize():f} {plan.measure} of the request cannot be covered for this date.")
        if any(ln.unknown_stock and supplier_of.get(ln.product_id, VALIO) == VALIO for ln in plan.lines):
            reasons.append("Some lines have stock Valio does not report: not confirmed until Valio confirms.")
        for b in blocks:
            if b["supplier_id"] != VALIO:
                reasons.append(f"{b['name']} is a price list the kitchen entered: its stock is not known "
                               "until the supplier confirms." + (
                                   " You may approve it; the order then waits for the supplier's "
                                   "confirmation (call or e-mail them)." if manual_ok else ""))
            if b["vat"] is None:
                reasons.append(f"VAT for {b['name']} is not known: its total is ex VAT.")
        verdict = "NEEDS_APPROVAL" if plan.lines else "REFUSED"

        def line_out(ln) -> dict:
            return {"product_id": ln.product_id, "quantity": f"{ln.quantity.normalize():f}",
                    "unit": ln.unit, "unit_price": _money(ln.unit_price), "total": _money(ln.total),
                    "why": ln.why, "unknown_stock": ln.unknown_stock,
                    "reason_codes": list(ln.reason_codes),
                    # Stored as text: the store refuses a binary float in an offer (#570).
                    # _line_out turns both back into numbers for every answer.
                    "reliability": _text(ln.reliability), "carbon_kg_co2e_per_kg": _text(ln.carbon),
                    "labels": list(ln.labels), **when.get(ln.product_id, unknown)}

        def money(x: Decimal | None) -> str | None:
            return None if x is None else _money(x)

        return {
            "currency": "EUR",
            "total_ex_vat": _money(net), "vat": _money(vat),
            "delivery_fee": money(fee), "mov_gap": money(mov_gap),
            "expected_total": _money(expected),
            "shortfall": f"{plan.shortfall.normalize():f}", "measure": plan.measure,
            "mandate": {"verdict": verdict, "reasons": reasons,
                        "reason_codes": list(plan.reason_codes), "warnings": list(plan.warnings)},
            "lines": [line_out(ln) for ln in plan.lines],
            "blocks": [{"supplier_id": b["supplier_id"], "name": b["name"],
                        "lines": [line_out(ln) for ln in b["lines"]],
                        "total_ex_vat": _money(b["net"]), "vat": money(b["vat"]),
                        "mov_gap": money(b["mov_gap"]), "delivery_fee": money(b["fee"]),
                        "expected_total": _money(b["expected"])} for b in blocks],
            "excluded": [{"product_id": pid, "reason": why} for pid, why in excluded],
            "alternative": None if plan.alternative is None else {
                "total_ex_vat": _money(plan.alternative.total),
                "lines": [{"product_id": ln.product_id, "quantity": f"{ln.quantity.normalize():f}",
                           "unit": ln.unit, "total": _money(ln.total), "why": ln.why}
                          for ln in plan.alternative.lines]},
            "partial_fill": partial_out(plan.partial),   # confirmed stock now, a plan for the rest (#288)
        }

    def _allergen_refusals(self, kitchen_id: str, product_ids: list[str]) -> dict[str, tuple[str, ...]]:
        """S03: the kitchen's allergen rule always wins, on every path (REST, MCP, any agent).
        A product whose known allergens include an excluded code is left out. A misspelt
        rule fails closed: no offer at all, never a silently wider one."""
        from store.buyer_context import excluded_allergens
        from store.allergen_groups import excluded_allergen_codes
        values = excluded_allergens(self.db, kitchen_id)
        if not values:
            return {}
        try:
            # A group code (AW, AN) means its whole group: the same helper as the Buyer agent.
            rule = tuple(excluded_allergen_codes(values))
        except ValueError:
            raise GatewayError(409, "KITCHEN_POLICY_INVALID",
                               "the kitchen's allergen rule names an unknown allergen; fix it in settings") from None
        from store.products import get_products
        refused = {}
        for row in get_products(self.db, product_ids, kitchen_id=kitchen_id):
            hits = allergen_rule_hits(row, rule)
            if hits:
                refused[row["product_id"]] = hits
        return refused

    def _mixed_fat(self, plan: RequestPlan) -> bool:
        """S01: the lines of one plan have different fat levels (fat-free and 3 % milk)."""
        from engine.fat import fat_levels_differ, fat_per_100g
        ids = [ln.product_id for ln in plan.lines]
        if len(ids) < 2:
            return False
        docs = self.db.products.find({"_id": {"$in": ids}}, {"raw.synkkaData.nutritionalContent": 1})
        return fat_levels_differ([fat_per_100g(d.get("raw")) for d in docs])

    def _quote(self, kitchen_id: str, request: dict) -> dict:
        if request.get("needs"):
            sim = self._basket(kitchen_id, request)
            return self._save_offer(kitchen_id, request, sim)
        requested = date.fromisoformat(request["requested_date"])
        measure = request["unit"]
        need = Decimal(str(request["quantity"]))
        if need <= 0:
            raise GatewayError(422, "INVALID_REQUEST", "quantity must be positive")
        blocked = recalls.blocked_ids(self.db, kitchen_id)
        refused = self._allergen_refusals(kitchen_id, request["product_ids"])
        offers, skipped, tax, supplier_of, when = self._offers(
            kitchen_id, [p for p in request["product_ids"] if p not in blocked and p not in refused],
            measure, requested)
        skipped.extend((p, 'BLOCKED_BY_RECALL') for p in request['product_ids'] if p in blocked)
        skipped.extend((p, f"ALLERGEN_RULE: the kitchen excludes {', '.join(hits)}")
                       for p, hits in refused.items())
        plan = plan_request(need, measure, offers, requested, self._params(kitchen_id),
                            event=bool(request.get("event")))
        tiers = {sid: (self._supplier(kitchen_id, sid).get("terms") or {}).get("discount_tiers") or []
                 for sid in set(supplier_of.values())}
        plan = apply_discount_tiers(plan, lambda pid: tiers.get(supplier_of.get(pid), []))
        sim = self._simulate(kitchen_id, plan, tax, skipped, supplier_of, when)
        if refused and "ALLERGEN_RULE" not in sim["mandate"]["reason_codes"]:
            sim["mandate"]["reason_codes"].append("ALLERGEN_RULE")
        if self._mixed_fat(plan) and "SUBSTITUTE_FAT_LEVEL" not in sim["mandate"]["reason_codes"]:
            sim["mandate"]["reason_codes"].append("SUBSTITUTE_FAT_LEVEL")   # S01: a person picks
        return self._save_offer(kitchen_id, request, sim)

    def _basket(self, kitchen_id: str, request: dict) -> dict:
        """One simulation for several needs (an order for a menu plan, #74): each product is
        sized by the engine for its own need, in its own measure; then one total, one set of
        supplier blocks, one approval."""
        from engine.offers import RequestPlan
        requested = date.fromisoformat(request["requested_date"])
        needs = request["needs"]
        ids = [n["product_id"] for n in needs]
        blocked = recalls.blocked_ids(self.db, kitchen_id)
        refused = self._allergen_refusals(kitchen_id, ids)
        params = self._params(kitchen_id)
        lines, excluded, codes, short = [], [], [], []
        skipped = [(p, "BLOCKED_BY_RECALL") for p in ids if p in blocked]
        skipped += [(p, f"ALLERGEN_RULE: the kitchen excludes {', '.join(hits)}") for p, hits in refused.items()]
        tax, supplier_of, when = {}, {}, {}
        by_measure: dict[str, list[dict]] = {}
        for n in needs:
            if n["product_id"] in blocked or n["product_id"] in refused:
                continue
            by_measure.setdefault(n["unit"] if n["unit"] in ("L", "KG") else "ST", []).append(n)
        for measure, group in by_measure.items():
            offers, skip, t, s, w = self._offers(kitchen_id, [n["product_id"] for n in group], measure, requested)
            skipped += skip
            tax.update(t)
            supplier_of.update(s)
            when.update(w)
            for n in group:
                mine = [o for o in offers if o.product_id == n["product_id"]]
                if not mine:
                    continue
                plan = plan_request(Decimal(str(n["quantity"])), measure, mine, requested, None)
                lines += list(plan.lines)
                excluded += list(plan.excluded)
                codes += [c for c in plan.reason_codes if c not in codes]
                if plan.shortfall > 0:
                    short.append((n["product_id"], plan.shortfall, n["unit"]))
        total = sum((ln.total for ln in lines), Decimal("0.00"))
        warnings = ()
        if params.budget_warning_order_eur is not None and total > params.budget_warning_order_eur:
            warnings = ("OVER_BUDGET_WARNING",)
        plan = RequestPlan(Decimal(len(needs)), "products", tuple(lines), total, Decimal(0),
                           tuple(excluded), tuple(codes), warnings)
        tiers = {sid: (self._supplier(kitchen_id, sid).get("terms") or {}).get("discount_tiers") or []
                 for sid in set(supplier_of.values())}
        plan = apply_discount_tiers(plan, lambda pid: tiers.get(supplier_of.get(pid), []))
        sim = self._simulate(kitchen_id, plan, tax, skipped, supplier_of, when)
        sim["shortfalls"] = [{"product_id": p, "shortfall": f"{q.normalize():f}", "unit": u} for p, q, u in short]
        for p, q, u in short:
            sim["mandate"]["reasons"].append(f"{p}: {q.normalize():f} {u} of the plan's need cannot be covered for this date.")
        for code in (["PARTIAL_STOCK"] if short else []) + (["ALLERGEN_RULE"] if refused else []):
            if code not in sim["mandate"]["reason_codes"]:
                sim["mandate"]["reason_codes"].append(code)
        return sim

    def _save_offer(self, kitchen_id: str, request: dict, sim: dict) -> dict:
        now = self.now()
        offer_id = uuid4().hex
        signed = {}
        try:    # signed offers (#290): never a reason to fail a quote
            from gateway import signing
            token, digest = signing.sign_offer(
                self.db, offer_id=offer_id, kitchen_id=kitchen_id, simulation=sim,
                requested_date=request["requested_date"], as_of=now, valid_until=now + OFFER_TTL)
            signed = {"signature": token, "offer_hash": digest}
        except Exception as exc:  # log the type only: never the key or the seed
            log.warning("offer signing failed: %s", type(exc).__name__)
            signed = {}
        offer = orders.save_offer(self.db, {
            "offer_id": offer_id, "kitchen_id": kitchen_id, "supplier_id": VALIO,
            "request": request, "valid_until": (now + OFFER_TTL).isoformat(),
            "simulation": sim, "fetched_at": now, **signed})
        return offer

    # ---- kitchen side ---------------------------------------------------------------

    def _from_text(self, kitchen_id: str, body: dict) -> dict:
        """Free text and no product list: the deterministic parser (#276), the fallback
        when the Nemotron Buyer is not running. It reads, searches and stops; the engine
        still sizes every line and a person still approves."""
        from gateway.parse import ParseError, parse_request
        try:
            parsed = parse_request(body["text"], self.now().date())
        except ParseError as exc:
            raise GatewayError(422, "CANNOT_READ_REQUEST", str(exc)) from None
        from gateway import catalog_search
        from gateway.candidates import SEARCH_LIMIT, pick_candidates
        rows, _ = catalog_search.search(self.db, parsed.query, {}, SEARCH_LIMIT, kitchen_id,
                                        injected=self._search)
        # Keep the hits that can answer the request: the text search alone ranks chocolate
        # and bread mix above the milk for "lactose free milk".
        ids = pick_candidates(rows, parsed.as_need().get("unit") or "")
        if not ids:
            raise GatewayError(422, "NO_PRODUCTS_FOUND", f"no catalog product matches {parsed.query!r}")
        return {**body, "product_ids": ids, **{k: v for k, v in parsed.as_need().items() if k != "query"},
                "made_by": "parser", "query": parsed.query}

    def _from_plan(self, kitchen_id: str, body: dict) -> dict:
        """`from` and `to` and no products: an order for what the menu plan needs in that
        window (net of stock). Unknown stock is not treated as zero stock silently: the full
        need is proposed and the line says the count is missing."""
        from gateway.kitchen_routes import demand_rows
        try:
            start, end = date.fromisoformat(str(body["from"])), date.fromisoformat(str(body["to"]))
        except ValueError:
            raise GatewayError(422, "INVALID_REQUEST", "from and to must be YYYY-MM-DD") from None
        if end < start or (end - start).days > 31:
            raise GatewayError(422, "INVALID_REQUEST", "from must be on or before to, at most 31 days apart")
        rows, problems = demand_rows(self.db, kitchen_id, start, end, self.now().date())
        total: dict[tuple[str, str], Decimal] = {}
        uncounted: set[str] = set()
        for row in rows:
            need = row["net_need"]
            if need is None:
                need = row["gross_need"]
                uncounted.add(row["product_id"])
            key = (row["product_id"], row["unit"])
            total[key] = total.get(key, Decimal(0)) + need
        needs = [{"product_id": pid, "quantity": f"{q.normalize():f}", "unit": unit,
                  "stock_counted": pid not in uncounted}
                 for (pid, unit), q in sorted(total.items()) if q > 0]
        if not needs:
            raise GatewayError(422, "NOTHING_NEEDED", "the plan needs nothing beyond the stock in this window",
                               problems=problems)
        return {"product_ids": [n["product_id"] for n in needs], "quantity": str(len(needs)), "unit": "products",
                "requested_date": str(body.get("requested_date") or body["from"]), "needs": needs,
                "text": body.get("text") or f"Order for the menu plan {start.isoformat()} to {end.isoformat()}",
                "window": {"from": start.isoformat(), "to": end.isoformat()}, "problems": problems,
                "idempotency_key": body.get("idempotency_key")}

    def create_proposal(self, kitchen_id: str, body: dict, actor: str) -> dict:
        planned = False
        if body.get("from") and body.get("to") and not body.get("product_ids") and not body.get("text"):
            if not body.get("idempotency_key"):
                raise GatewayError(422, "INVALID_REQUEST", "idempotency_key is required")
            stored = self.db.proposals.find_one({"kitchen_id": kitchen_id, "idempotency_key": body["idempotency_key"]})
            if stored:
                if (stored["request"].get("window") or {}) != {"from": str(body["from"]), "to": str(body["to"])}:
                    raise GatewayError(409, "IDEMPOTENCY_KEY_REUSED", "key used with another request")
                return self._proposal_out(stored)
            body = self._from_plan(kitchen_id, body)
            planned = True
        if body.get("text") and not body.get("product_ids"):
            if not body.get("idempotency_key"):
                raise GatewayError(422, "INVALID_REQUEST", "idempotency_key is required")
            stored = self.db.proposals.find_one({"kitchen_id": kitchen_id, "idempotency_key": body["idempotency_key"]})
            if stored:
                if stored["request"].get("text") != body["text"]:
                    raise GatewayError(409, "IDEMPOTENCY_KEY_REUSED", "key used with another request")
                return self._proposal_out(stored)
            body = self._from_text(kitchen_id, body)
            parsed = True
        else:
            parsed = False
        for field in ("product_ids", "quantity", "unit", "requested_date", "idempotency_key"):
            if not body.get(field):
                raise GatewayError(422, "INVALID_REQUEST", f"{field} is required")
        request = {k: body[k] for k in ("product_ids", "quantity", "unit", "requested_date")}
        request["text"] = body.get("text") or ""
        # Set by the gateway, never by the client: a structured body cannot claim the parser.
        request["made_by"] = "menu_plan" if planned else ("parser" if parsed else "structured")
        if planned:
            request.update({key: body[key] for key in ("needs", "window", "problems")})
        if parsed and body.get("query"):
            request["query"] = body["query"]
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
            options.attach_confirmed(self, kitchen_id, doc["_id"], request, sim)   # never raises
        self._audit(kitchen_id, "proposal_created", actor, proposal_id=doc["_id"],
                    offer_id=offer["offer_id"], expected_total=sim["expected_total"],
                    verdict=sim["mandate"]["verdict"])
        self._audit(kitchen_id, "decision_summary", actor, proposal_id=doc["_id"],
                    offer_id=offer["offer_id"], summary=self._summary(request, sim)["text"])
        self._maybe_auto_approve(kitchen_id, doc, sim, request)
        return self._proposal_out(self.db.proposals.find_one({"_id": doc["_id"]}) or doc)

    def _maybe_auto_approve(self, kitchen_id: str, doc: dict, sim: dict, request: dict) -> None:
        """Earned auto-approve (#299): off unless an approver switched it on after the learning
        period. Any doubt, any error: the proposal simply waits for a person."""
        try:
            from gateway import autoapprove
            ok, _, evidence = autoapprove.decide(self.db, kitchen_id, sim, request, self.now())
            if not ok:
                return
            by = f"auto-approve (rule set by {evidence['rule_set_by']})"
        except Exception:
            return
        # Approve first: the audit log must never show an auto-approval that placed no order.
        try:
            placed = self.approve(kitchen_id, doc["_id"], {"expected_total": sim["expected_total"],
                                                           "idempotency_key": "auto:" + doc["_id"]}, human=by)
        except Exception as exc:
            try:
                self._audit(kitchen_id, "auto_approve_skipped", by, proposal_id=doc["_id"],
                            reason=getattr(exc, "code", None) or type(exc).__name__)
            except Exception:
                pass
            return
        try:
            self._audit(kitchen_id, "auto_approved", by, proposal_id=doc["_id"],
                        order_id=placed.get("order_id"), expected_total=sim["expected_total"],
                        evidence=evidence)
        except Exception:
            pass

    def _proposal_out(self, doc: dict) -> dict:
        offer = orders.get_offer(self.db, doc["offer_id"])
        result = {"proposal_id": doc["_id"], "status": doc["status"], "request": doc["request"],
                "substitute_options": options.merged(doc),
                "offer_id": doc["offer_id"], "valid_until": offer["valid_until"],
                "approval_id": doc.get("approval_id"), "order_id": doc.get("order_id"),
                **offer["simulation"],
                "decision_summary": self._summary(doc["request"], offer["simulation"]),
                "signature": offer.get("signature"), "offer_hash": offer.get("offer_hash")}
        result.update({key: doc.get(key) for key in ('recall_alerts', 'replacement_proposal_id', 'recall_replan_error', 'product_evidence')})
        result['recall_alerts'] = recalls.visible_alerts(self.db, doc['kitchen_id'], doc.get('recall_alerts', []))
        blocked = {a['product_id'] for a in doc.get('recall_alerts', []) if a['match'] in ('exact', 'possible')}
        result['lines'] = [{**_line_out(line), **({'recall_status': 'BLOCKED_BY_RECALL'} if line['product_id'] in blocked else {})}
                           for line in result['lines']]
        result['blocks'] = _blocks_out(result, result['lines'])
        from monitor.labels import checks
        from store.products import get_products
        result['label_checks'] = checks(get_products(self.db,
            [line['product_id'] for line in result['lines']], doc['kitchen_id']), now=self.now())
        return result

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
            # A write may have succeeded before its response failed. Only a
            # confirmed absence permits releasing the post-quote commit claim.
            try:
                attempt = orders.attempt_for_key(self.db, kitchen_id, key)
                if attempt is None:
                    blocked = recalls.blocked_ids(self.db, kitchen_id)
                    state = 'BLOCKED_BY_RECALL' if any(l['product_id'] in blocked for l in stored['simulation']['lines']) else 'READY'
                    self.db.proposals.update_one({'_id': proposal_id, 'kitchen_id': kitchen_id,
                        'status': 'COMMITTING', 'approving_key': key},
                        {'$set': {'status': state}, '$unset': {'approving_key': ''}})
                elif attempt.get('proposal_id') == proposal_id and attempt['outcome'] is None:
                    # The attempt never ended: the send result is unknown. The proposal stays
                    # held; a person resolves the order (gateway/resolve.py, #291).
                    orders.set_outcome(self.db, attempt['order_id'], outcome='UNCONFIRMED', status=None)
            except Exception:
                pass  # Cannot prove absence while the database is unavailable.
            raise

    def _approved_or_conflict(self, kitchen_id: str, proposal_id: str, key: str) -> dict:
        """Not READY: replay the order placed with this key, else 409 NOT_PENDING."""
        doc = self.db.proposals.find_one({"_id": proposal_id, "kitchen_id": kitchen_id}) or {}
        if doc.get('status') == 'BLOCKED_BY_RECALL':
            raise GatewayError(409, 'BLOCKED_BY_RECALL', 'a recall holds this basket; review its replacement proposal')
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
        # Unchanged basket on an expired offer: place it on the fresh live quote, so the
        # order and audit point at a valid offer, not a stale snapshot (#534).
        if datetime.fromisoformat(stored["valid_until"]) <= self.now():
            stored = fresh
        sim = stored["simulation"]
        # A person's consent is not supplier stock confirmation. Keep unknown
        # lines visible in proposals, but never record a placed order for them.
        # One exception, off by default (#631): a manual/csv supplier's block, when the
        # kitchen switched `approve_unconfirmed_manual` on; that order waits for the supplier.
        blocks = sim.get("blocks") or [{"supplier_id": VALIO}]   # an offer stored before #73
        manual = {ln["product_id"]: b["supplier_id"] for b in blocks if b["supplier_id"] != VALIO
                  for ln in b.get("lines", [])}
        unknown = [ln for ln in sim["lines"] if ln.get("unknown_stock") is not False]
        if unknown and not (self._approve_unconfirmed_manual(kitchen_id)
                            and all(ln["product_id"] in manual for ln in unknown)):
            raise GatewayError(409, "STOCK_UNKNOWN", "supplier stock must be confirmed before placement")
        must_confirm = sorted({manual[ln["product_id"]] for ln in unknown})
        # Atomic commit point shared with the recall monitor. A notice arriving
        # during the live quote can still claim APPROVING and prevent this order.
        committed = self.db.proposals.update_one({'_id': proposal_id, 'kitchen_id': kitchen_id,
            'status': 'APPROVING', 'approving_key': key},
            {'$set': {'status': 'COMMITTING', 'offer_id': stored['offer_id']}})
        if not committed.modified_count:
            return self._approved_or_conflict(kitchen_id, proposal_id, key)
        order, created = orders.record_attempt(
            self.db, kitchen_id=kitchen_id, idempotency_key=key, offer_id=stored["offer_id"],
            expected_total=Decimal128(sim["expected_total"]),   # exact decimal in any Mongo
            lines=[{k: v for k, v in ln.items() if k != "why"} for ln in sim["lines"]],
            proposal_id=proposal_id, approved_by=human,
            offer_hash=stored.get("offer_hash"),     # the exact offer this yes covers (#290)
            # One order for the proposal (#73); the supplier split is stored on it.
            supplier_id=blocks[0]["supplier_id"] if len(blocks) == 1 else None,
            blocks=[{k: v for k, v in b.items() if k != "lines"}
                    | {"product_ids": [ln["product_id"] for ln in b.get("lines", [])]} for b in blocks],
            supplier_must_confirm=must_confirm)
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
            self.db.proposals.update_one({"_id": proposal_id, "status": "COMMITTING", "approving_key": key},
                                         {"$set": {"status": "READY"}, "$unset": {"approving_key": ""}})
        return {"proposal_id": proposal_id, **self._order_out(order)}

    def reject(self, kitchen_id: str, proposal_id: str, body: dict, *, human: str | None) -> dict:
        if not human:
            raise GatewayError(403, "HUMAN_SESSION_REQUIRED", "only a person can reject an order")
        reason = body.get('reason', '')
        if not isinstance(reason, str) or len(reason.strip()) > 500:
            raise GatewayError(422, 'INVALID_REQUEST', 'reason must be a string of at most 500 characters')
        doc = recalls.reject_basket(self.db, kitchen_id, proposal_id, human=human,
                                    reason=reason.strip(), at=self.now().isoformat())
        if doc is None:
            raise GatewayError(404, "PROPOSAL_NOT_FOUND", "no such proposal")
        if doc["status"] != "REJECTED":
            raise GatewayError(409, "NOT_PENDING", f"proposal is {doc['status']}")
        event_id = 'proposal-rejected:' + _hash([kitchen_id, proposal_id])
        first_time = self.db.audit_log.find_one({'event.event_id': event_id}, {'_id': 1}) is None
        audit.append_event(self.db, {'event_id': event_id,
            'kind': 'proposal_rejected', 'actor': doc.get('rejected_by', human),
            'proposal_id': proposal_id, 'reason': doc.get('reject_reason', '')},
            {'kitchen_id': kitchen_id, 'at': doc.get('rejected_at', self.now().isoformat())})
        if first_time:   # this path writes its audit event itself, so it also tells the webhooks (#277)
            try:
                from gateway import webhooks
                webhooks.dispatch(self.db, kitchen_id, 'proposal_rejected',
                                  {'proposal_id': proposal_id, 'reason': doc.get('reject_reason', '')})
            except Exception:
                pass
        return {"proposal_id": proposal_id, "status": "REJECTED"}

    def dismiss_recall(self, kitchen_id: str, event_id: str, body: dict, *, human: str | None) -> dict:
        if not human:
            raise GatewayError(403, 'HUMAN_SESSION_REQUIRED', 'only a person can dismiss a recall after checking packs')
        reason = body.get('reason')
        if not isinstance(reason, str) or not 10 <= len(reason.strip()) <= 500:
            raise GatewayError(422, 'INVALID_REQUEST', 'a pack-check reason of 10 to 500 characters is required')
        row = recalls.dismiss(self.db, kitchen_id, event_id, human=human, reason=reason.strip(), at=self.now().isoformat())
        if row is None:
            raise GatewayError(404, 'RECALL_NOT_FOUND', 'no such recall in this kitchen')
        result = {'event_id': row['_id'], **{key: row[key] for key in
                  ('status', 'dismissed_by', 'dismissed_at', 'dismiss_reason')}}
        audit.append_event(self.db, {'event_id': 'recall-dismissed:' + _hash([kitchen_id, event_id]),
            'kind': 'recall_dismissed', 'actor': row['dismissed_by'], 'recall_event_id': event_id,
            **{key: value for key, value in result.items() if key != 'event_id'}},
            {'kitchen_id': kitchen_id, 'at': row['dismissed_at']})
        return result

    @staticmethod
    def _order_out(order: dict) -> dict:
        return {"order_id": order["order_id"], "outcome": order["outcome"], "status": order["status"],
                # #631: suppliers whose stock nobody confirmed yet; a person calls them
                "supplier_must_confirm": list(order.get("supplier_must_confirm") or []),
                "expected_total": _money(Decimal(str(order["expected_total"]))),
                "lines": [_line_out(ln) for ln in order["lines"]], "created_at": order["created_at"].isoformat()
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
        if body.get("event") is True:
            need["event"] = True      # set by the trusted app, never by the model (#530)
        self.db.needs.insert_one(need)
        return {"need_id": need["_id"], **{k: need[k] for k in ("quantity", "unit", "requested_date", "text")}}

    def tool_search(self, kitchen_id: str, query: str, filters: dict, limit: int,
                    need_id: str | None = None) -> dict:
        """Catalog search for the Buyer. With the stored need it becomes a shortlist the
        Buyer can order from: only products sold in the need's measure (a request in litres
        never gets chocolate), and products that can still arrive on the requested date
        first. One availability call for the shortlist only, never for the whole catalog."""
        from gateway import catalog_search
        need = self.db.needs.find_one({"_id": need_id, "kitchen_id": kitchen_id}) if need_id else None
        if need_id and need is None:
            raise GatewayError(422, "INVALID_NEED", "unknown need_id")
        if need is None:
            rows, kind = catalog_search.search(self.db, query, filters, limit, injected=self._search)
            return {"products": rows, "search": kind}
        # Text search, or text plus meaning when SEARCH_HYBRID is on (gateway/catalog_search.py).
        rows, kind = catalog_search.search(self.db, query, filters, 50, injected=self._search)
        measure = need["unit"]
        same = [r for r in rows if (r.get("net_content") or {}).get("unit") == measure]
        filtered = bool(same) and measure in ("L", "KG")
        if filtered:
            rows = same
        rows = rows[:max(limit, 20)]
        arrival: dict[str, bool | None] = {}   # None: unknown (no answer or no cut-off time)
        try:
            # Catalog rows (source "valio") can be asked live; a kitchen's own products cannot.
            ids = [r["product_id"] for r in rows if r.get("source", "valio") != "own"]
            if ids:
                requested = date.fromisoformat(need["requested_date"])
                for product in self.valio.availability(ids, need["requested_date"])["products"]:
                    lines = product.get("scheduleLines") or []
                    day = lines[0].get("availableDate") if lines else None
                    cutoff = product.get("cutoff_passed")
                    ok = (bool(lines) and cutoff is not True and not product.get("salesBlock")
                          and day is not None and date.fromisoformat(day) <= requested)
                    # no closingTime from Valio: the cut-off is unknown, not passed
                    arrival[product["productId"]] = None if ok and cutoff is None else ok
        except Exception:
            arrival = {}     # no live answer: the offer step still checks every product
        for r in rows:
            r["can_arrive"] = arrival.get(r["product_id"])
        rows.sort(key=lambda r: 0 if r["can_arrive"] else (1 if r["can_arrive"] is None else 2))
        return {"products": rows[:limit], "requested_date": need["requested_date"],
                "measure": measure if filtered else None, "search": kind,
                "note": "can_arrive false: the order cut-off for this date has passed or it cannot be delivered; "
                        "prefer products with can_arrive true"}

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
        if need.get("event"):
            request["event"] = True
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
        options.attach_confirmed(self, kitchen_id, doc["_id"], offer["request"], sim)   # never raises
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
        if order.get("offer_hash") and offer.get("offer_hash") != order["offer_hash"]:
            raise GatewayError(409, "APPROVAL_MISMATCH", "the approval covers another offer than this one")
        if abs(Decimal(str(body.get("expected_total") or "0")) - Decimal(str(order["expected_total"]))) > TOLERANCE:
            raise GatewayError(409, "TOTAL_MISMATCH", "this is not the approved total",
                               expected_total=_money(Decimal(str(order["expected_total"]))))
        return self._order_out(order)

    # ---- addable products (#129) ------------------------------------------------------

    def _daily_demands(self, kitchen_id: str, product_ids: list, days: int = DEMAND_DAYS) -> dict:
        """Average of used + short per recorded day, per product, in one query.
        No usage recorded: 0, so no order."""
        if not product_ids:
            return {}
        since = self.now() - timedelta(days=days)
        totals: dict = {}
        for row in self.db.kitchen_stock.find({"meta.kitchen_id": kitchen_id,
                                               "meta.product_id": {"$in": list(product_ids)},
                                               "ts": {"$gte": since}}):
            if row.get("used") is None:
                continue
            per_day = totals.setdefault(row["meta"]["product_id"], {})
            day = row["ts"].date()
            per_day[day] = per_day.get(day, Decimal(0)) + _dec(row["used"]) + (_dec(row.get("short")) or Decimal(0))
        return {pid: float(sum(d.values()) / len(d)) if d else 0.0 for pid, d in totals.items()}

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
        standing = self._standing_orders(kitchen_id)
        pids = list(dict.fromkeys(str(c["product_id"]) for c in counts))
        products = {d["_id"]: d for d in self.db.products.find({"_id": {"$in": pids}})} if pids else {}
        demands = self._daily_demands(kitchen_id, pids)
        candidates, skipped = [], []
        for count in counts:
            pid = count["product_id"]
            product = products.get(str(pid))
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
            item = Item(pid, pack, daily_demand=demands.get(pid, 0.0), lead_time_days=lead,
                        review_days=REVIEW_DAYS, on_hand=None if on_hand is None else float(on_hand),
                        abc=product.get("abc"), category=product.get("category"),
                        standing_order=standing.get(pid))
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
        # The band (p10-p90) comes from forecast errors of the last 8 weeks (engine.newsvendor,
        # #432): the product's own when it has enough, else the kitchen's pooled ones, else a
        # normal with 15% spread.
        from engine.newsvendor import MIN_RESIDUALS, interval
        from store.history import forecast_vs_actual
        today = self.now().date()
        past = forecast_vs_actual(self.db, kitchen_id, today - timedelta(days=56), today - timedelta(days=1))
        pooled: list[float] = []
        by_product: dict[str, list[float]] = {}
        for pid, _, predicted, actual in past:
            if predicted > 0:
                pooled.append(actual / predicted)
                by_product.setdefault(pid, []).append(actual / predicted)
        kitchen_band = "own forecast errors" if len(pooled) >= MIN_RESIDUALS else "default spread"
        lines = []
        for r in rows:
            pid = r["meta"]["product_id"]
            need = float(str(r["need"]))
            own = by_product.get(pid, [])
            if len(own) >= MIN_RESIDUALS:
                ratios, band = own, "product forecast errors"
            else:
                ratios, band = pooled, kitchen_band
            lines.append({"product_id": pid, "date": r["ts"].date().isoformat(),
                          "need": f"{Decimal(str(r['need'])).normalize():f}", "unit": r["unit"],
                          "made_on": r.get("made_on"), "why": r.get("why"),
                          **interval(need, ratios=ratios), "band_from": band})
        return {"kitchen_id": kitchen_id, "band_from": kitchen_band, "lines": lines}

    def audit_log(self, kitchen_id: str) -> list[dict]:
        def at(entry: dict) -> str | None:
            # Older agent events were stored without a server time: use when they were stored.
            stored = entry.get("stored_at")
            return entry["server"].get("at") or (stored.isoformat() if hasattr(stored, "isoformat") else stored)
        return [{"seq": e["seq"], **e["event"], "at": at(e)}
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


def _blocks_out(sim: dict, lines: list[dict]) -> list[dict]:
    """The supplier blocks (#73) with the lines as the API answers them: each block takes
    its lines from `lines`, so a block line and a top-level line never differ."""
    def ids(block: dict) -> set:
        return {ln["product_id"] for ln in block["lines"]}
    return [{**block, "lines": [ln for ln in lines if ln["product_id"] in ids(block)]}
            for block in sim.get("blocks") or []]


def offer_out(offer: dict) -> dict:
    sim = offer["simulation"]
    lines = [_line_out(ln) for ln in sim["lines"]]
    return {"offer_id": offer["offer_id"], "valid_until": offer["valid_until"], **sim,
            "lines": lines, "blocks": _blocks_out(sim, lines),
            "signature": offer.get("signature"), "offer_hash": offer.get("offer_hash")}


__all__ = ["Gateway", "GatewayError", "offer_out", "asdict"]
