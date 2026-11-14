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
from gateway import options, product_names
from gateway.decision import FOUND_BY_MEANING, decision_summary
from gateway.partial_fill import partial_out
from gateway.suppliers import (UNKNOWN_FACTS, VALIO, ManualAdapter, ValioAdapter, apply_discount_tiers,
                               delivery_facts)
from store import audit, demo_delivery, orders, recalls, supplier_offers
from store.audit import canonical
from store.history import current_stock

DEMAND_DAYS = 28                    # usage history behind the daily demand of addable rows
REVIEW_DAYS = 3.0                   # days to the delivery after next, until order days are wired
CENT = Decimal("0.01")
TOLERANCE = Decimal("0.005")
COMMIT_STALE = timedelta(seconds=60)   # older COMMITTING with no attempt row is stuck (#715)
log = logging.getLogger(__name__)
OFFER_TTL = timedelta(minutes=15)   # Aron, 2026-11-14 (#19 answer F)
KIND_SEARCHES = 3                   # extra catalog searches for a request's kind, one per category
KINDS_TTL = timedelta(hours=1)      # the kinds snapshot is rebuilt after this: a reloaded catalog counts (#1026)
KINDS_RETRY = timedelta(seconds=60) # after a failed catalog read, wait this long before reading again (#1026)
MAX_NEED_QUANTITY = Decimal("1000000")   # one need of a list body (#1375), as change.py caps a line


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


_LINE_NUMBERS = ("reliability", "carbon_kg_co2e_per_kg", "delivery_reliability")


def _line_out(line: dict) -> dict:
    """A stored offer or order line as the API answers it: the two dataset values are numbers
    (docs/contract.md), kept as text in Mongo because the store refuses a binary float (#570)."""
    out = {**line, **{key: float(line[key]) for key in _LINE_NUMBERS if line.get(key) is not None}}
    out.pop("unlearned_quantity", None)     # internal basis for a later correction
    return out


def _learned_out(info: dict | None) -> dict | None:
    """A stored learned entry as the API answers it: ratio is a JSON number."""
    if not isinstance(info, dict):
        return info
    out = dict(info)
    try:
        out["ratio"] = float(Decimal(str(out["ratio"])))
    except (ArithmeticError, KeyError, TypeError, ValueError):
        pass
    return out


def _matched_by(rows: list[dict]) -> list[dict]:
    """Every search row says how it was found (#1382); a text search finds by words."""
    for row in rows:
        row.setdefault("matched_by", "words")
    return rows


def _hash(payload: dict) -> str:
    return hashlib.sha256(canonical(payload).encode()).hexdigest()


class Gateway:
    def __init__(self, db, valio, *, now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
                 search: Callable | None = None, meaning: Callable | None = None):
        self.db, self.valio, self.now = db, valio, now
        self._search = search          # catalog search; default: store.search (Atlas Search)
        # The Buyer's meaning search when the words find nothing (#1384); default: Atlas Vector
        # Search, but only with the default word search: an injected word search and no
        # injected meaning search (tests, offline runs) means no fallback.
        self._meaning = meaning
        self._kinds = None             # gateway/kind.py, read from the catalog on first use
        self._kinds_at = None          # when the snapshot was read (rebuilt after KINDS_TTL)
        self._kinds_failed_at = None   # when the last read failed (no new read for KINDS_RETRY)
        db.proposals.create_index([("kitchen_id", 1), ("idempotency_key", 1)], unique=True)
        db.orders.create_index([("kitchen_id", 1), ("idempotency_key", 1)], unique=True)
        db.approvals.create_index([("kitchen_id", 1), ("idempotency_key", 1)], unique=True)
        supplier_offers.ensure_indexes(db)      # a supplier's suggestions to a kitchen (#374)

    # ---- helpers ------------------------------------------------------------------

    def _audit(self, kitchen_id: str, kind: str, actor: str, **data) -> None:
        event = {"event_id": uuid4().hex, "kind": kind, "actor": actor, **data}
        audit.append_event(self.db, event, {"kitchen_id": kitchen_id, "at": self.now().isoformat()})
        try:    # webhooks (#277): after the event is stored; a receiver can never break an order
            from gateway import webhooks
            webhooks.dispatch(self.db, kitchen_id, kind, data, actor=actor)
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
            # Display-only cut-off, lead time and reliability, with their source (#1453).
            when.update(delivery_facts(adapter.when, found, supplier.get("terms") or {},
                                       demo_delivery.lookup(self.db, kitchen_id, supplier_id, ids), requested))
            offers.extend(found)
            skipped.extend(left_out)
            tax.update(rates)
            supplier_of.update({pid: supplier_id for pid in ids})
        return offers, skipped, tax, supplier_of, when

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
        unknown = {"available_date": None, "cutoff_passed": None, "closing_time": None, **UNKNOWN_FACTS}
        by_supplier: dict[str, list] = {}
        for ln in plan.lines:
            by_supplier.setdefault(supplier_of.get(ln.product_id, VALIO), []).append(ln)
        blocks = [self._block(self._supplier(kitchen_id, sid), lines, tax)
                  for sid, lines in by_supplier.items()]
        # The top-level gap and fee are those of the only supplier; with several, read `blocks`.
        # No line at all: nothing is ordered, so no delivery and no total (#995).
        if len(blocks) > 1:
            mov_gap = fee = None
        elif blocks:
            mov_gap, fee = blocks[0]["mov_gap"], blocks[0]["fee"]
        else:
            mov_gap = fee = Decimal(0)
        net = plan.total
        vat = sum((b["vat"] or Decimal(0) for b in blocks), Decimal(0))
        expected = sum((b["expected"] for b in blocks), Decimal(0))
        excluded = [*plan.excluded, *skipped]
        reasons = [f"{pid}: {why}" for pid, why in excluded]
        if plan.shortfall > 0:
            reasons.append(f"{plan.shortfall.normalize():f} {plan.measure} of the request cannot be covered for this date.")
        if any(ln.unknown_stock and supplier_of.get(ln.product_id, VALIO) == VALIO for ln in plan.lines):
            reasons.append("Some lines have stock Valio does not report: not confirmed until Valio confirms."
                           " You may approve it; the order then waits for Valio's confirmation.")
        for b in blocks:
            if b["supplier_id"] != VALIO:
                reasons.append(f"{b['name']} is a price list the kitchen entered: its stock is not known "
                               "until the supplier confirms. You may approve it; the order then waits "
                               "for the supplier's confirmation (call or e-mail them).")
            if b["vat"] is None:
                reasons.append(f"VAT for {b['name']} is not known: its total is ex VAT.")
        # Per supplier, in plain words: which products it must still confirm (Valio, 14 Nov).
        waiting = {b["supplier_id"]: [ln.product_id for ln in b["lines"] if ln.unknown_stock] for b in blocks}
        ids = sorted({pid for pids in waiting.values() for pid in pids})
        names = {d["_id"]: (d.get("names") or {}).get("en") for d in
                 self.db.products.find({"_id": {"$in": ids}}, {"names": 1})} if ids else {}
        for b in blocks:
            if waiting[b["supplier_id"]]:
                who = "Valio" if b["supplier_id"] == VALIO else b["name"]
                reasons.append(f"{who} must confirm stock for: "
                               + ", ".join(names.get(pid) or pid for pid in waiting[b["supplier_id"]]) + ".")
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
        rule = self._allergen_rule(kitchen_id)
        if not rule:
            return {}
        from store.products import get_products
        refused = {}
        for row in get_products(self.db, product_ids, kitchen_id=kitchen_id):
            hits = allergen_rule_hits(row, rule)
            if hits:
                refused[row["product_id"]] = hits
        return refused

    def _allergen_rule(self, kitchen_id: str) -> tuple[str, ...]:
        """The GS1 codes the kitchen excludes, groups expanded; empty when it has no rule."""
        from store.buyer_context import excluded_allergens
        from store.allergen_groups import excluded_allergen_codes
        values = excluded_allergens(self.db, kitchen_id)
        if not values:
            return ()
        try:
            # A group code (AW, AN) means its whole group: the same helper as the Buyer agent.
            return tuple(excluded_allergen_codes(values))
        except ValueError:
            raise GatewayError(409, "KITCHEN_POLICY_INVALID",
                               "the kitchen's allergen rule names an unknown allergen; fix it in settings") from None

    def _excluded_request(self, kitchen_id: str, query: str) -> dict | None:
        """#974: the refusal when the kitchen's allergen rule removes the products that best
        match the person's own product words (gateway/refusal.py), else None. One catalog
        search with no allergen filter, and only for a kitchen that has a rule."""
        rule = self._allergen_rule(kitchen_id)
        if not rule or not query:
            return None
        from gateway import catalog_search
        from gateway.candidates import SEARCH_LIMIT
        from gateway.refusal import excluded_request
        rows, _ = catalog_search.search(self.db, query, {}, SEARCH_LIMIT, kitchen_id, injected=self._search)
        return excluded_request(query, rows, rule)

    def _mixed_fat(self, plan: RequestPlan) -> bool:
        """S01: the lines of one plan have different fat levels (fat-free and 3 % milk)."""
        from engine.fat import fat_levels_differ, fat_per_100g
        ids = [ln.product_id for ln in plan.lines]
        if len(ids) < 2:
            return False
        docs = self.db.products.find({"_id": {"$in": ids}}, {"raw.synkkaData.nutritionalContent": 1})
        return fat_levels_differ([fat_per_100g(d.get("raw")) for d in docs])

    def _plan_one(self, kitchen_id: str, request: dict) -> tuple:
        """One need over its products: recall holds, the kitchen's allergen rule, live offers,
        the engine's sizes and the gap fill. (plan, skipped, tax, supplier_of, when, refused);
        no discount tier yet, nothing saved. The single request and each need of a list."""
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
        plan, skipped = self._fill_gap(kitchen_id, plan, skipped, requested, tax, supplier_of, when)
        return plan, skipped, tax, supplier_of, when, refused

    def _quote(self, kitchen_id: str, request: dict) -> dict:
        if request.get("needs"):
            sim = self._basket(kitchen_id, request)
            return self._save_offer(kitchen_id, request, sim)
        if request.get("made_by") == "list":
            return self._save_offer(kitchen_id, request, self._list_basket(kitchen_id, request))
        plan, skipped, tax, supplier_of, when, refused = self._plan_one(kitchen_id, request)
        tiers = {sid: (self._supplier(kitchen_id, sid).get("terms") or {}).get("discount_tiers") or []
                 for sid in set(supplier_of.values())}
        plan = apply_discount_tiers(plan, lambda pid: tiers.get(supplier_of.get(pid), []))
        sim = self._simulate(kitchen_id, plan, tax, skipped, supplier_of, when)
        if refused and "ALLERGEN_RULE" not in sim["mandate"]["reason_codes"]:
            sim["mandate"]["reason_codes"].append("ALLERGEN_RULE")
        if request.get("refusal"):       # the whole request is refused (#974): say it first
            sim["mandate"]["reasons"].insert(0, request["refusal"]["message"])
            # A rule refused it, not the stock (#995).
            sim["mandate"]["reason_codes"] = [c for c in sim["mandate"]["reason_codes"] if c != "PARTIAL_STOCK"]
        if self._mixed_fat(plan) and "SUBSTITUTE_FAT_LEVEL" not in sim["mandate"]["reason_codes"]:
            sim["mandate"]["reason_codes"].append("SUBSTITUTE_FAT_LEVEL")   # S01: a person picks
        return self._save_offer(kitchen_id, request, sim)

    def _fill_gap(self, kitchen_id: str, plan: RequestPlan, skipped: list, requested: date,
                  tax: dict, supplier_of: dict, when: dict) -> tuple[RequestPlan, list]:
        """S02 (#731): the original covers only part of the need, and a basket product was left
        out because it is sold in another measure (bread in cases, rolls in bags). Size that
        substitute for the gap by weight or volume (engine/gap.py); its lines say
        SUBSTITUTE_NEEDS_OK, so a person agrees. Updates tax, supplier_of and when in place."""
        from dataclasses import replace
        from engine.gap import fill_gap
        left = [pid for pid, why in [*plan.excluded, *skipped]
                if why.startswith(("pack size unknown", "sold in "))]
        if plan.shortfall <= 0 or not plan.lines or not left:
            return plan, skipped
        original = plan.lines[0].product_id
        for common in ("KG", "L"):
            orig, *_ = self._offers(kitchen_id, [original], common, requested)
            if orig and orig[0].pack.measure == common:
                break
        else:
            return plan, skipped
        subs, _, t, s, w = self._offers(kitchen_id, left, common, requested)
        sub = fill_gap(plan, orig[0].pack, subs, requested, self._params(kitchen_id))
        if sub is None:
            return plan, skipped
        tax.update(t), supplier_of.update(s), when.update(w)
        used = {ln.product_id for ln in sub.lines}
        rest = (sub.shortfall / orig[0].pack.size) if sub.shortfall > 0 else Decimal(0)
        codes = [*plan.reason_codes, *sub.reason_codes]   # PARTIAL_STOCK stays: the original is short
        plan = replace(plan, lines=(*plan.lines, *sub.lines), total=plan.total + sub.total, shortfall=rest,
                       excluded=tuple(e for e in plan.excluded if e[0] not in used),
                       reason_codes=tuple(dict.fromkeys(codes)))
        return plan, [e for e in skipped if e[0] not in used]

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
            # A changed proposal (#303) names each quantity in the product's own sales unit.
            measure = n["unit"] if n.get("sales_unit") or n["unit"] in ("L", "KG") else "ST"
            by_measure.setdefault(measure, []).append(n)
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
                plan = plan_request(Decimal(str(n["quantity"])), measure, mine, requested, None,
                                    event=bool(request.get("event")))
                lines += [_set_by(ln, n, mine[0].pack.lot_size) for ln in plan.lines]
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
        if request.get("made_by") == "menu_plan":
            # The change helper measures a later correction against the unlearned engine
            # number, never against the already learned line (#1305).
            ratios = {}
            for need in needs:
                ratio = (need.get("learned") or {}).get("ratio")
                if ratio is not None:
                    ratios[need["product_id"]] = Decimal(str(ratio))
            for line in sim["lines"]:
                ratio = ratios.get(line["product_id"])
                if ratio is not None and ratio > 0:
                    line["unlearned_quantity"] = f"{(Decimal(str(line['quantity'])) / ratio).normalize():f}"
        sim["shortfalls"] = [{"product_id": p, "shortfall": f"{q.normalize():f}", "unit": u} for p, q, u in short]
        for p, q, u in short:
            sim["mandate"]["reasons"].append(f"{p}: {q.normalize():f} {u} of the plan's need cannot be covered for this date.")
        for code in (["PARTIAL_STOCK"] if short else []) + (["ALLERGEN_RULE"] if refused else []):
            if code not in sim["mandate"]["reason_codes"]:
                sim["mandate"]["reason_codes"].append(code)
        return sim

    def _list_basket(self, kitchen_id: str, request: dict) -> dict:
        """One simulation for a request with several products (#1375): each need is planned
        over its own products as a single request is (`_plan_one`), then one total, one set of
        supplier blocks, one approval. A need with no line is refused here (NOT_AVAILABLE) and
        the others go on; `request["items"]` and `request["problems"]` are updated in place
        before the request is stored, so the proposal says what was left out and why."""
        requested = request["requested_date"]
        params = self._params(kitchen_id)
        lines, excluded, codes, warnings, skipped, short = [], [], [], [], [], []
        tax, supplier_of, when = {}, {}, {}
        used: dict[str, int] = {}       # product_id -> the need (1-based) that has it
        mixed = allergen = False
        for number, item in enumerate(request["items"], 1):
            if item.get("result") != "proposed":
                allergen = allergen or (item.get("problem") or {}).get("code") == "ALLERGEN_RULE"
                continue
            free = [p for p in item["product_ids"] if p not in used]
            if not free:
                first = min(used[p] for p in item["product_ids"])
                item.update(result="refused", problem={
                    "code": "NOT_AVAILABLE",
                    "message": f"same product as need {first}: ask for it once, with the sum"})
                continue
            plan, skip, t, s, w, refused = self._plan_one(kitchen_id, {
                "product_ids": free, "quantity": item["quantity"], "unit": item["unit"],
                "requested_date": requested, "event": request.get("event")})
            tax.update(t), supplier_of.update(s), when.update(w)
            skipped += skip
            allergen = allergen or bool(refused)
            if not plan.lines:
                why = "; ".join(f"{pid}: {r}" for pid, r in [*plan.excluded, *skip][:3])
                item.update(result="refused", problem={
                    "code": "NOT_AVAILABLE",
                    "message": "no product can be ordered for this day" + (f" ({why})" if why else "")})
                continue
            used.update({ln.product_id: number for ln in plan.lines})
            lines += plan.lines
            excluded += list(plan.excluded)
            codes += [c for c in plan.reason_codes if c not in codes]
            warnings += [w_ for w_ in plan.warnings if w_ != "OVER_BUDGET_WARNING" and w_ not in warnings]
            mixed = mixed or self._mixed_fat(plan)        # within one need, never milk next to cream
            if plan.shortfall > 0:
                short.append((plan.lines[0].product_id, plan.shortfall, plan.measure, item["text"]))
        total = sum((ln.total for ln in lines), Decimal("0.00"))
        if params.budget_warning_order_eur is not None and total > params.budget_warning_order_eur:
            warnings.append("OVER_BUDGET_WARNING")
        plan = RequestPlan(Decimal(len(request["items"])), "products", tuple(lines), total, Decimal(0),
                           tuple(excluded), tuple(codes), tuple(warnings))
        tiers = {sid: (self._supplier(kitchen_id, sid).get("terms") or {}).get("discount_tiers") or []
                 for sid in set(supplier_of.values())}
        plan = apply_discount_tiers(plan, lambda pid: tiers.get(supplier_of.get(pid), []))
        sim = self._simulate(kitchen_id, plan, tax, skipped, supplier_of, when)
        problems = [f"{item['quantity']} {item['unit']} {item['text']}: {item['problem']['message']}"
                    for item in request["items"] if item.get("result") == "refused"]
        request["problems"] = problems
        sim["mandate"]["reasons"][:0] = problems
        sim["shortfalls"] = [{"product_id": p, "shortfall": f"{q.normalize():f}", "unit": u, "text": t}
                             for p, q, u, t in short]
        for p, q, u, t in short:
            sim["mandate"]["reasons"].append(f"{t}: {q.normalize():f} {u} cannot be covered for this date.")
        reason_codes = sim["mandate"]["reason_codes"]
        if not sim["lines"]:            # every need was refused: a rule or the stock, not a shortfall
            reason_codes[:] = [c for c in reason_codes if c != "PARTIAL_STOCK"]
        for code, on in (("PARTIAL_STOCK", bool(short)), ("ALLERGEN_RULE", allergen),
                         ("SUBSTITUTE_FAT_LEVEL", mixed), ("NEED_REFUSED", bool(problems))):
            if on and code not in reason_codes:
                reason_codes.append(code)
        return sim

    def _list_inputs(self, kitchen_id: str, body: dict) -> tuple[list[dict], str, str, bool]:
        """The list body checked (#1375): (items, requested_date, text, event), or 422
        INVALID_REQUEST naming the row. No search, no model: this is what a replay compares."""
        from gateway.parse import UNITS, product_words
        from gateway.split import MAX_NEED_TEXT, MAX_NEEDS, MIN_NEEDS
        if body.get("product_ids") or body.get("from") or body.get("to"):
            raise GatewayError(422, "INVALID_REQUEST", "needs cannot be sent with product_ids or from/to")
        needs = body.get("needs")
        if not isinstance(needs, list) or not MIN_NEEDS <= len(needs) <= MAX_NEEDS:
            raise GatewayError(422, "INVALID_REQUEST", f"needs must be a list of {MIN_NEEDS} to {MAX_NEEDS} rows")
        try:
            day = date.fromisoformat(str(body.get("requested_date")))
        except ValueError:
            raise GatewayError(422, "INVALID_REQUEST", "requested_date must be YYYY-MM-DD") from None
        if day < self.now().date():
            raise GatewayError(422, "INVALID_REQUEST", "requested_date is in the past")
        text = body.get("text") or ""
        if not isinstance(text, str) or len(text) > 500:
            raise GatewayError(422, "INVALID_REQUEST", "text: at most 500 characters")
        event = body.get("event", False)
        if not isinstance(event, bool):
            raise GatewayError(422, "INVALID_REQUEST", "event must be true or false")
        items, seen = [], {}
        for number, need in enumerate(needs, 1):
            words = need.get("text") if isinstance(need, dict) else None
            raw, unit = (need.get("quantity"), need.get("unit")) if isinstance(need, dict) else (None, None)
            if not isinstance(words, str) or not 0 < len(words.strip()) <= MAX_NEED_TEXT:
                raise GatewayError(422, "INVALID_REQUEST", f"need {number}: text must be 1 to {MAX_NEED_TEXT} characters")
            unit = UNITS.get(unit.strip().lower()) if isinstance(unit, str) else None
            if unit not in ("L", "KG", "G", "ST"):
                raise GatewayError(422, "INVALID_REQUEST", f"need {number}: unit must be L, KG, G or ST")
            try:
                if isinstance(raw, bool) or not isinstance(raw, (str, int)):
                    raise InvalidOperation
                quantity = Decimal(str(raw).strip())
            except InvalidOperation:
                raise GatewayError(422, "INVALID_REQUEST", f"need {number}: quantity must be a number") from None
            if not quantity.is_finite() or quantity <= 0 or quantity > MAX_NEED_QUANTITY:
                raise GatewayError(422, "INVALID_REQUEST",
                                   f"need {number}: quantity must be above 0 and at most {MAX_NEED_QUANTITY}")
            if unit == "G":
                quantity, unit = quantity / 1000, "KG"
            query = product_words(words)
            if not query:
                raise GatewayError(422, "INVALID_REQUEST", f"need {number}: no product words in {words!r}")
            if query in seen:
                raise GatewayError(422, "INVALID_REQUEST",
                                   f"need {number}: the same product as need {seen[query]}; put it in one row")
            seen[query] = number
            items.append({"text": " ".join(words.split()), "quantity": f"{quantity.normalize():f}",
                          "unit": unit, "query": query})
        return items, day.isoformat(), text, event

    def _read_need(self, kitchen_id: str, item: dict, rule: tuple[str, ...]) -> None:
        """Which products may answer one need, read as the parser reads a single request, with
        no model. The allergen rule of #974 runs first, before the kitchen's own words: a
        product linked by alias is not a way around it. Sets result, product_ids, problem."""
        from gateway import catalog_search, memory
        from gateway.candidates import SEARCH_LIMIT, pick_candidates
        from gateway.refusal import excluded_request
        from store.products import get_product
        query, unit = item["query"], item["unit"]
        rows = None
        if rule:
            rows, _ = catalog_search.search(self.db, query, {}, SEARCH_LIMIT, kitchen_id, injected=self._search)
            refusal = excluded_request(query, rows, rule)
            if refusal:
                item.update(result="refused", product_ids=refusal["product_ids"], problem={
                    "code": "ALLERGEN_RULE", "message": refusal["message"], "allergens": refusal["allergens"]})
                return
        known = memory.lookup(self.db, kitchen_id, query, count_use=True)
        if known and get_product(self.db, known) is not None:
            item.update(result="proposed", product_ids=[known], problem=None)
            return
        if rows is None:
            rows, _ = catalog_search.search(self.db, query, {}, SEARCH_LIMIT, kitchen_id, injected=self._search)
        ids = pick_candidates(self._of_kind(rows, query, {}, query, unit, kitchen_id), unit)
        if not ids:
            memory.note_unknown(self.db, kitchen_id, query)     # remembered for a person to link or add
            item.update(result="refused", product_ids=[], problem={
                "code": "NO_PRODUCTS_FOUND", "message": f"no catalog product matches {query!r}"})
            return
        item.update(result="proposed", product_ids=ids, problem=None)

    def _create_list(self, kitchen_id: str, body: dict, actor: str, *, auto_approve: bool = True,
                     split_by: str | None = None) -> dict:
        """The list body (#1375): one proposal for several needs. The replay check compares the
        checked inputs before any search, so a changed catalog never turns a replay into a
        conflict."""
        key = body.get("idempotency_key")
        if not isinstance(key, str) or not key.strip():
            raise GatewayError(422, "INVALID_REQUEST", "idempotency_key is required")
        items, day, text, event = self._list_inputs(kitchen_id, body)
        payload_hash = _hash({"needs": [{k: i[k] for k in ("text", "quantity", "unit")} for i in items],
                              "requested_date": day, "text": text, "event": event})
        stored = self.db.proposals.find_one({"kitchen_id": kitchen_id, "idempotency_key": key})
        if stored:
            # A split free text is the same request when the text is the same: two racing
            # requests may have split it differently (the model, or plain code).
            same = (stored["request"].get("text") == text) if split_by else stored.get("payload_hash") == payload_hash
            if not same:
                raise GatewayError(409, "IDEMPOTENCY_KEY_REUSED", "key used with another request")
            return self._proposal_out(stored)
        rule = self._allergen_rule(kitchen_id)        # a misspelt rule fails the whole request (409)
        for item in items:
            self._read_need(kitchen_id, item, rule)
        ids = list(dict.fromkeys(p for item in items for p in item["product_ids"]))
        request = {"product_ids": ids, "quantity": str(len(items)), "unit": "products",
                   "requested_date": day, "text": text, "made_by": "list", "items": items, "problems": []}
        if split_by:
            request["split_by"] = split_by
        if event:
            request["event"] = True
        return self._store_proposal(
            kitchen_id, request, key, payload_hash, actor, auto_approve=auto_approve,
            retry=lambda: self._create_list(kitchen_id, body, actor, auto_approve=auto_approve, split_by=split_by))

    def prepare_several(self, kitchen_id: str, body: dict) -> dict | None:
        """A free text that asks for several products (#1375), before any model call. None:
        the text names one product, and the single-product path answers as before.
        `{"replay": proposal}`: the key was used with this text. `{"day": "YYYY-MM-DD"}`: split
        it and send the needs as a list body for that one delivery day."""
        from gateway.parse import ParseError
        from gateway import split
        text = body.get("text")
        if not isinstance(text, str) or not split.several(text):
            return None
        key = body.get("idempotency_key")
        if not isinstance(key, str) or not key.strip():
            raise GatewayError(422, "INVALID_REQUEST", "idempotency_key is required")
        stored = self.db.proposals.find_one({"kitchen_id": kitchen_id, "idempotency_key": key})
        if stored is not None:
            if stored["request"].get("text") != text:
                raise GatewayError(409, "IDEMPOTENCY_KEY_REUSED", "key used with another request")
            return {"replay": self._proposal_out(stored)}
        if len(text) > 500:
            raise GatewayError(422, "CANNOT_READ_REQUEST", "the request is too long (500 characters at most)")
        today = self.now().date()
        try:
            named = split.days(text, today)
        except ParseError as exc:
            raise GatewayError(422, "CANNOT_READ_REQUEST", str(exc)) from None
        if len(named) > 1:
            raise GatewayError(422, "CANNOT_READ_REQUEST", split.ONE_DAY)
        day = next(iter(named), None) or _form_day(body)
        if day is None:
            raise GatewayError(422, "CANNOT_READ_REQUEST",
                               "no delivery day (for example 'by Monday', 'maanantaiksi' or '16.11.')")
        if day < today:
            raise GatewayError(422, "CANNOT_READ_REQUEST", "the delivery day is in the past")
        return {"day": day.isoformat()}

    def _save_offer(self, kitchen_id: str, request: dict, sim: dict) -> dict:
        now = self.now()
        offer_id = uuid4().hex
        from gateway import signing
        # offer_hash needs no key: always set it, so place_order always runs APPROVAL_MISMATCH (#753)
        signed = {"signature": None, "offer_hash": signing.offer_hash(sim, request["requested_date"])}
        try:    # signed offers (#290): never a reason to fail a quote
            token, digest = signing.sign_offer(
                self.db, offer_id=offer_id, kitchen_id=kitchen_id, simulation=sim,
                requested_date=request["requested_date"], as_of=now, valid_until=now + OFFER_TTL)
            signed = {"signature": token, "offer_hash": digest}
        except Exception as exc:  # log the type only: never the key or the seed
            log.warning("offer signing failed: %s", type(exc).__name__)
        offer = orders.save_offer(self.db, {
            "offer_id": offer_id, "kitchen_id": kitchen_id, "supplier_id": VALIO,
            "request": request, "valid_until": (now + OFFER_TTL).isoformat(),
            "simulation": sim, "fetched_at": now, **signed})
        return offer

    def _of_kind(self, rows: list[dict], query: str, filters: dict | None, text: str, unit: str,
                 kitchen_id: str | None = None) -> list[dict]:
        """The search hits narrowed to the kind of product `text` names (gateway/kind.py,
        gateway/candidates.py `of_kind`). The word search returns 50 hits and "cheese" is in
        439 names, so the best hits of each category of that kind (three at most) are
        searched too, with the person's own product words: a model's query can be a word
        no name has ("voita" for butter found white icing). It only narrows what a search
        found, and it never fails a search: when the kind cannot be read, the rows come
        back as they are."""
        from gateway import catalog_search
        from gateway.candidates import SEARCH_LIMIT, of_kind
        from gateway.kind import Kinds, product_phrase
        filters = dict(filters or {})
        now = self.now()
        stale = self._kinds is None or self._kinds_at is None or now - self._kinds_at >= KINDS_TTL
        backing_off = self._kinds_failed_at is not None and now - self._kinds_failed_at < KINDS_RETRY
        if stale and not backing_off:
            try:
                self._kinds, self._kinds_at, self._kinds_failed_at = Kinds.from_db(self.db), now, None
            except Exception:
                self._kinds_failed_at = now
                log.warning("kinds could not be read from the catalog", exc_info=True)
        if self._kinds is None:
            return rows
        try:
            categories = self._kinds.categories(text)
        except Exception:
            log.warning("kind of a request could not be read", exc_info=True)
            return rows
        if not categories or filters.get("category") is not None:
            return rows
        merged, seen = list(rows), {r["product_id"] for r in rows}
        words = product_phrase(text) or query
        for category in categories[:KIND_SEARCHES]:
            try:
                more, _ = catalog_search.search(self.db, words, {**filters, "category": category},
                                                SEARCH_LIMIT, kitchen_id, injected=self._search,
                                                hybrid_ok=False)     # inside one category: words are enough
            except Exception:
                log.warning("kind search failed: category=%s", category, exc_info=True)
                continue
            for row in more:
                # An injected search may not know the filter: take only what was asked.
                if row["product_id"] not in seen and str(row.get("category")) == category:
                    seen.add(row["product_id"])
                    merged.append(row)
        return of_kind(merged, categories, unit)

    # ---- kitchen side ---------------------------------------------------------------

    def _from_text(self, kitchen_id: str, body: dict, default_day: date | None = None) -> dict:
        """Free text and no product list: the deterministic parser (#276), the fallback
        when the Nemotron Buyer is not running. It reads, searches and stops; the engine
        still sizes every line and a person still approves.

        When the kitchen's allergen rule removes the products that best match the request,
        the answer carries `refusal` and only those refused products: the proposal is then
        REJECTED with that reason, never another kind of product (#974)."""
        from gateway.parse import ParseError, parse_request
        try:
            parsed = parse_request(body["text"], self.now().date(), default_day)
        except ParseError as exc:
            raise GatewayError(422, "CANNOT_READ_REQUEST", str(exc)) from None
        from gateway import catalog_search, memory
        from gateway.candidates import SEARCH_LIMIT, pick_candidates
        from store.products import get_product
        known = memory.lookup(self.db, kitchen_id, parsed.query, count_use=True)
        if known and get_product(self.db, known) is not None:
            # The kitchen linked these words to one product: no search, no guess. The allergen
            # rule, the cut-off and the stock checks apply to it in the quote like to any product.
            read = {**body, "product_ids": [known], **{k: v for k, v in parsed.as_need().items() if k != "query"},
                    "made_by": "parser", "query": parsed.query}
            read.pop("refusal", None)
            return read
        rows, _ = catalog_search.search(self.db, parsed.query, {}, SEARCH_LIMIT, kitchen_id,
                                        injected=self._search)
        # Keep the hits that can answer the request: the text search alone ranks chocolate
        # and bread mix above the milk for "lactose free milk", and a cheese sauce above cheese.
        unit = parsed.as_need().get("unit") or ""
        ids = pick_candidates(self._of_kind(rows, parsed.query, {}, parsed.query, unit, kitchen_id), unit)
        from gateway.refusal import excluded_request
        refusal = excluded_request(parsed.query, rows, self._allergen_rule(kitchen_id))
        if not ids and not refusal:
            memory.note_unknown(self.db, kitchen_id, parsed.query)     # remembered for a person to link or add
            raise GatewayError(422, "NO_PRODUCTS_FOUND", f"no catalog product matches {parsed.query!r}",
                               remembered=True)
        read = {**body, "product_ids": ids, **{k: v for k, v in parsed.as_need().items() if k != "query"},
                "made_by": "parser", "query": parsed.query}
        read.pop("refusal", None)       # set here only, never by the client
        if refusal:
            read["product_ids"] = refusal.pop("product_ids")
            read["refusal"] = refusal
        return read

    def refuse_excluded(self, kitchen_id: str, body: dict, actor: str) -> dict | None:
        """Before the Buyer runs (#974): a free-text request whose best matches the kitchen's
        allergen rule removes ends here, as a REJECTED proposal that names the allergen. The
        Buyer would only see what is left (plain butter for "peanut butter") and propose it.
        None: the request goes on to the Buyer as before. The delivery day may come from
        the body (`requested_date`), as it does for the Buyer.

        A text that asks for two products ("100 L cream and 50 kg cheese") also ends here,
        with 422 `CANNOT_READ_REQUEST`: one request names one product."""
        text, key = body.get("text"), body.get("idempotency_key")
        if not isinstance(text, str) or not isinstance(key, str) or not key.strip():
            return None
        stored = self.db.proposals.find_one({"kitchen_id": kitchen_id, "idempotency_key": key})
        if stored is not None:
            if not stored["request"].get("refusal"):
                return None             # a Buyer or parser proposal: its own replay rules apply
            if stored["request"].get("text") != text:
                raise GatewayError(409, "IDEMPOTENCY_KEY_REUSED", "key used with another request")
            return self._proposal_out(stored)
        from gateway.parse import ONE_PRODUCT, asks_for_two
        if asks_for_two(text):
            # Before any model call: the Buyer would take one of the two, or neither.
            raise GatewayError(422, "CANNOT_READ_REQUEST", ONE_PRODUCT)
        if not self._allergen_rule(kitchen_id):
            return None
        try:
            day = date.fromisoformat(body["requested_date"]) if body.get("requested_date") else None
            read = self._from_text(kitchen_id, body, day)
        except (TypeError, ValueError):
            return None                 # not a date: the Buyer path says so
        except GatewayError as exc:
            if exc.code in ("CANNOT_READ_REQUEST", "NO_PRODUCTS_FOUND"):
                return None             # the parser cannot read it; the Buyer may
            raise
        if not read.get("refusal"):
            return None
        return self.create_proposal(kitchen_id, body, actor, read=read)

    def _from_plan(self, kitchen_id: str, body: dict, *, entries=None) -> dict:
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
        rows, problems = demand_rows(self.db, kitchen_id, start, end, self.now().date(), self.now().tzinfo,
                                     entries_override=entries)
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
        # Learned facts are computed once for this plan. Only a plan proposal adjusts a
        # quantity; the stored need keeps the unlearned number as the correction basis.
        from engine.learning import apply_ratio
        from gateway import learned as learned_facts
        facts = learned_facts.compute_facts(self, kitchen_id, self.now().date())
        ratios = {fact["product_id"]: fact for fact in facts
                  if fact.get("kind") == "CORRECTION_RATIO" and fact.get("active") is True
                  and fact.get("applicable") is True}
        for need in needs:
            fact = ratios.get(need["product_id"])
            if fact is None:
                continue
            original = need["quantity"]
            adjusted, info = apply_ratio(original, fact)
            if info is None:
                continue
            need["quantity"] = f"{adjusted.normalize():f}"
            # The offer store refuses binary floats; the API turns this back into a number.
            need["learned"] = {**info, "ratio": f"{Decimal(str(info['ratio'])).normalize():f}",
                               "unit": need["unit"]}
            need["unlearned_quantity"] = original
        problems = [*problems, *learned_facts.plan_problems(
            self, kitchen_id, facts, [need["product_id"] for need in needs])]
        return {"product_ids": [n["product_id"] for n in needs], "quantity": str(len(needs)), "unit": "products",
                "requested_date": str(body.get("requested_date") or body["from"]), "needs": needs,
                "text": body.get("text") or f"Order for the menu plan {start.isoformat()} to {end.isoformat()}",
                "window": {"from": start.isoformat(), "to": end.isoformat()}, "problems": problems,
                "idempotency_key": body.get("idempotency_key")}

    def create_proposal(self, kitchen_id: str, body: dict, actor: str, *, auto_approve: bool = True,
                        read: dict | None = None, plan_entries=None, menu_photo=None,
                        needs: list[dict] | None = None) -> dict:
        """`auto_approve=False`: this proposal always waits for a person, whatever the kitchen's
        auto-approve rule says (a proposal made from a supplier's offer, #374).
        `read`: what `_from_text` already made of this free text (`refuse_excluded`).
        `needs`: internal callers only (the recall replan, #1482): each line's own
        `{product_id, quantity, unit}`, so a structured body is not sized as "N products"."""
        if body.get("needs") is not None:
            return self._create_list(kitchen_id, body, actor, auto_approve=auto_approve)    # #1375
        original_body = body
        planned = False
        if body.get("from") and body.get("to") and not body.get("product_ids") and not body.get("text"):
            if not body.get("idempotency_key"):
                raise GatewayError(422, "INVALID_REQUEST", "idempotency_key is required")
            stored = self.db.proposals.find_one({"kitchen_id": kitchen_id, "idempotency_key": body["idempotency_key"]})
            if stored:
                if menu_photo is not None and (stored.get('menu_photo') or {}).get('fingerprint') != menu_photo['fingerprint']:
                    raise GatewayError(409, 'IDEMPOTENCY_KEY_REUSED', 'key used with another request')
                if (stored["request"].get("window") or {}) != {"from": str(body["from"]), "to": str(body["to"])}:
                    raise GatewayError(409, "IDEMPOTENCY_KEY_REUSED", "key used with another request")
                return self._proposal_out(stored)
            body = self._from_plan(kitchen_id, body, entries=plan_entries)
            if menu_photo is not None:
                unsized = sum(not dish['in_proposal'] for dish in menu_photo['response']['dishes'])
                if unsized:
                    body['problems'].append(f'Menu photo: {unsized} dishes were not sized; check the photo results')
            planned = True
        if body.get("text") and not body.get("product_ids"):
            if not body.get("idempotency_key"):
                raise GatewayError(422, "INVALID_REQUEST", "idempotency_key is required")
            stored = self.db.proposals.find_one({"kitchen_id": kitchen_id, "idempotency_key": body["idempotency_key"]})
            if stored:
                if stored["request"].get("text") != body["text"]:
                    raise GatewayError(409, "IDEMPOTENCY_KEY_REUSED", "key used with another request")
                return self._proposal_out(stored)
            body = read or self._from_text(kitchen_id, body, _form_day(body))
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
        elif needs:
            request["needs"] = needs
        if parsed and body.get("query"):
            request["query"] = body["query"]
        if parsed and body.get("refusal"):
            request["refusal"] = body["refusal"]      # from _from_text only (#974)
        if parsed and body.get("buyer_down") is True:
            request["buyer_down"] = True              # the app route only: the model timed out
        if body.get("event"):
            request["event"] = True       # one-off demand (S05): EVENT_LINE, kept out of the forecast
        key = body["idempotency_key"]
        stored = self.db.proposals.find_one({"kitchen_id": kitchen_id, "idempotency_key": key})
        if stored:
            if stored["payload_hash"] != _hash(request):
                raise GatewayError(409, "IDEMPOTENCY_KEY_REUSED", "key used with another request")
            return self._proposal_out(stored)
        return self._store_proposal(
            kitchen_id, request, key, _hash(request), actor, auto_approve=auto_approve, menu_photo=menu_photo,
            retry=lambda: self.create_proposal(kitchen_id, original_body, actor, auto_approve=auto_approve,
                                               read=read, plan_entries=plan_entries, menu_photo=menu_photo,
                                               needs=needs))

    def _store_proposal(self, kitchen_id: str, request: dict, key: str, payload_hash: str, actor: str, *,
                        auto_approve: bool, retry: Callable[[], dict], menu_photo=None) -> dict:
        """Quote, store, ask for approval, audit: every body ends here. `retry` runs when
        another request stored the same key first (it then answers the replay)."""
        offer = self._quote(kitchen_id, request)
        sim = offer["simulation"]
        doc = {"_id": uuid4().hex, "kitchen_id": kitchen_id, "idempotency_key": key,
               "payload_hash": payload_hash, "request": request, "offer_id": offer["offer_id"],
               "status": "READY" if sim["lines"] else "REJECTED", "created_by": actor,
               "created_at": self.now(), "approval_id": None, "order_id": None}
        if menu_photo is not None:
            doc['menu_photo'] = menu_photo    # replay result only; never image bytes
        try:
            self.db.proposals.insert_one(doc)
        except DuplicateKeyError:
            return retry()
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
        applied = [{"product_id": need["product_id"], "fact_id": need["learned"].get("fact_id"),
                    "from_qty": need["learned"].get("from_qty"), "to_qty": need["learned"].get("to_qty"),
                    "unit": need["learned"].get("unit")}
                   for need in request.get("needs") or [] if need.get("learned")]
        if applied:
            self._audit(kitchen_id, "learned_fact_applied", actor, proposal_id=doc["_id"],
                        offer_id=offer["offer_id"], applied=applied)
        self._audit(kitchen_id, "decision_summary", actor, proposal_id=doc["_id"],
                    offer_id=offer["offer_id"], summary=self._summary(request, sim)["text"])
        if auto_approve:
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

    def _trace(self, doc: dict, traces: dict | None = None) -> dict | None:
        """What the model did (#1197): the Buyer run's trace, the parser's rule trace, or None."""
        from gateway import model_trace
        from store import agent_runs
        if (doc.get("request") or {}).get("made_by") in ("parser", "list"):   # a list is matched by rules (#1375)
            return model_trace.parser_trace()
        if traces is None:
            traces = agent_runs.traces(self.db, doc["kitchen_id"], [doc["_id"]])
        return model_trace.stored(traces.get(doc["_id"]))

    def _proposal_out(self, doc: dict, traces: dict | None = None) -> dict:
        offer = orders.get_offer(self.db, doc["offer_id"])
        substitutes = options.merged(doc)
        found = product_names.labels(self.db, product_names.proposal_ids(
            {**offer["simulation"], "substitute_options": substitutes}), doc["kitchen_id"])
        request_out = dict(doc["request"])
        if request_out.get("needs"):
            request_out["needs"] = [{**need, "learned": _learned_out(need["learned"])}
                                    if need.get("learned") else need
                                    for need in request_out["needs"]]
        result = {"proposal_id": doc["_id"], "status": doc["status"], "request": request_out,
                "substitute_options": substitutes,
                "offer_id": doc["offer_id"], "valid_until": offer["valid_until"],
                "approval_id": doc.get("approval_id"), "order_id": doc.get("order_id"),
                **offer["simulation"],
                "decision_summary": self._summary(doc["request"], offer["simulation"], found),
                "signature": offer.get("signature"), "offer_hash": offer.get("offer_hash")}
        result.update({key: doc.get(key) for key in ('recall_alerts', 'replacement_proposal_id', 'recall_replan_error', 'product_evidence')})
        result['recall_alerts'] = recalls.visible_alerts(self.db, doc['kitchen_id'], doc.get('recall_alerts', []))
        blocked = {a['product_id'] for a in doc.get('recall_alerts', []) if a['match'] in ('exact', 'possible')}
        learned = {need['product_id']: _learned_out(need['learned']) for need in doc['request'].get('needs') or []
                   if need.get('learned')}
        result['lines'] = [{**_line_out(line), **({'recall_status': 'BLOCKED_BY_RECALL'} if line['product_id'] in blocked else {}),
                            **({'learned': learned[line['product_id']]} if line['product_id'] in learned else {})}
                           for line in result['lines']]
        result['blocks'] = _blocks_out(result, result['lines'])
        from monitor.labels import checks
        from store.products import get_products
        result['label_checks'] = checks(get_products(self.db,
            [line['product_id'] for line in result['lines']], doc['kitchen_id']), now=self.now())
        result['model_trace'] = self._trace(doc, traces)
        # #1130: names on every line kind, read in one query for the whole proposal.
        return product_names.name_proposal(result, found)

    def _summary(self, request: dict, sim: dict, found: dict | None = None) -> dict:
        """`found`: product_names.labels already read for this proposal (no second query)."""
        if found is None:
            ids = {ln["product_id"] for ln in sim.get("lines") or []} | {e["product_id"] for e in sim.get("excluded") or []}
            found = product_names.labels(self.db, ids)
        return decision_summary(request, sim, {pid: f["product_name"] for pid, f in found.items()})

    def get_proposal(self, kitchen_id: str, proposal_id: str) -> dict:
        doc = self.db.proposals.find_one({"_id": proposal_id, "kitchen_id": kitchen_id})
        if doc is None:
            raise GatewayError(404, "PROPOSAL_NOT_FOUND", "no such proposal")
        return self._proposal_out(doc)

    def list_proposals(self, kitchen_id: str) -> list[dict]:
        from store import agent_runs
        docs = list(self.db.proposals.find({"kitchen_id": kitchen_id}).sort("created_at", -1).limit(100))
        traces = agent_runs.traces(self.db, kitchen_id, [d["_id"] for d in docs])     # one read for all
        return [self._proposal_out(d, traces) for d in docs]

    def approve(self, kitchen_id: str, proposal_id: str, body: dict, *, human: str | None,
                via: dict | None = None) -> dict:
        """A human says yes to the figure they saw. Re-check live; place only if unchanged.
        `via`: audit fields of a personal approval token ({"via": "personal_token", "token_id"})."""
        if not human:
            raise GatewayError(403, "HUMAN_SESSION_REQUIRED", "only a person can approve an order")
        key, seen = body.get("idempotency_key"), body.get("expected_total")
        if not key or seen is None:
            raise GatewayError(422, "INVALID_REQUEST", "expected_total and idempotency_key are required")
        doc = self.db.proposals.find_one({"_id": proposal_id, "kitchen_id": kitchen_id})
        if doc is None:
            raise GatewayError(404, "PROPOSAL_NOT_FOUND", "no such proposal")
        if doc["status"] == "COMMITTING" and self._release_stuck_commit(kitchen_id, doc, human):
            doc = self.db.proposals.find_one({"_id": proposal_id, "kitchen_id": kitchen_id}) or doc
        if doc["status"] != "READY":
            result = self._approved_or_conflict(kitchen_id, proposal_id, key)
            self._decision_feedback(kitchen_id, proposal_id, "approved", human,
                                    total=result.get("expected_total"))
            return result
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
            result = self._approved_or_conflict(kitchen_id, proposal_id, key)
            self._decision_feedback(kitchen_id, proposal_id, "approved", human,
                                    total=result.get("expected_total"))
            return result
        try:
            placed = self._place(kitchen_id, proposal_id, doc, stored, seen, key, human, via)
        except BaseException:
            # A write may have succeeded before its response failed. Only a
            # confirmed absence permits releasing the post-quote commit claim.
            try:
                self.db.proposals.update_one({"_id": proposal_id, "status": "APPROVING", "approving_key": key},
                                             {"$set": {"status": "READY"}, "$unset": {"approving_key": ""}})
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
            except Exception as exc:
                # Cannot prove absence while the database is unavailable. A later approve
                # releases a stale COMMITTING claim that has no attempt row (#715).
                try:
                    self._audit(kitchen_id, "approve_rollback_failed", human, proposal_id=proposal_id,
                                reason=type(exc).__name__)
                except Exception:
                    pass
            raise
        self._decision_feedback(kitchen_id, proposal_id, "approved", human,
                                total=placed.get("expected_total"))
        return placed

    def _decision_feedback(self, kitchen_id: str, proposal_id: str, kind: str, human: str,
                           *, total=None, reason=None) -> None:
        """One learning row per human decision, never for auto-approval. A replay finds
        its row and writes none. Feedback is never a reason to fail the decision."""
        if not human or human.startswith("auto-approve"):
            return
        try:
            from store.feedback import record_feedback
            existing = self.db.feedback.find_one(
                {"meta.kitchen_id": kitchen_id, "proposal_id": proposal_id, "kind": kind},
                {"_id": 1})
            if existing is not None:
                return
            record_feedback(self.db, kitchen_id, proposal_id, [{
                "feedback_id": f"{proposal_id}:{kind}", "kind": kind,
                "reason": reason, "total": total}], human)
        except Exception:
            log.warning("decision feedback failed: kitchen_id=%s proposal_id=%s kind=%s",
                        kitchen_id, proposal_id, kind, exc_info=True)

    def _release_stuck_commit(self, kitchen_id: str, doc: dict, human: str) -> bool:
        """A COMMITTING claim whose rollback failed (#715): with no order attempt for its key
        and older than COMMIT_STALE (so never an approval still in flight), release it."""
        since = doc.get("committing_at")
        if since is not None:
            if since.tzinfo is None:
                since = since.replace(tzinfo=timezone.utc)
            if self.now() - since < COMMIT_STALE:
                return False
        claim = doc.get("approving_key")
        if claim and orders.attempt_for_key(self.db, kitchen_id, claim) is not None:
            return False   # an attempt exists: resolve the order instead (gateway/resolve.py)
        stored = orders.get_offer(self.db, doc["offer_id"])
        blocked = recalls.blocked_ids(self.db, kitchen_id)
        state = 'BLOCKED_BY_RECALL' if any(l['product_id'] in blocked for l in stored['simulation']['lines']) else 'READY'
        released = self.db.proposals.update_one(
            {"_id": doc["_id"], "kitchen_id": kitchen_id, "status": "COMMITTING", "approving_key": claim},
            {"$set": {"status": state}, "$unset": {"approving_key": "", "committing_at": ""}})
        if not released.modified_count:
            return False
        self._audit(kitchen_id, "stuck_commit_released", human, proposal_id=doc["_id"], status=state)
        return True

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

    def _place(self, kitchen_id: str, proposal_id: str, doc: dict, stored: dict, seen, key: str, human: str,
               via: dict | None = None) -> dict:
        via = via or {}
        # Live re-check: price or stock may have moved since the human looked.
        fresh = self._quote(kitchen_id, doc["request"])
        new_total = Decimal(fresh["simulation"]["expected_total"])
        if abs(new_total - Decimal(str(seen))) > TOLERANCE or \
                fresh["simulation"]["lines"] != stored["simulation"]["lines"]:
            self.db.proposals.update_one({"_id": proposal_id}, {"$set": {"offer_id": fresh["offer_id"]}})
            self._audit(kitchen_id, "total_mismatch", human, proposal_id=proposal_id,
                        seen=str(seen), now=fresh["simulation"]["expected_total"], **via)
            raise GatewayError(409, "TOTAL_MISMATCH", "the price or stock moved; look at the new total",
                               expected_total=fresh["simulation"]["expected_total"])
        # Unchanged basket on an expired offer: place it on the fresh live quote, so the
        # order and audit point at a valid offer, not a stale snapshot (#534).
        if datetime.fromisoformat(stored["valid_until"]) <= self.now():
            stored = fresh
        sim = stored["simulation"]
        # A person's consent is not supplier stock confirmation, but it is enough to send
        # the order (Aron, 2026-11-14): a kitchen cannot wait for the supplier. The lines keep
        # unknown_stock and the order names each supplier that must still confirm. Every
        # supplier, Valio too; `approve_unconfirmed_manual` (#631) is no longer needed.
        # Earned auto-approve never places unknown stock: its rules refuse it, and so does this.
        blocks = sim.get("blocks") or [{"supplier_id": VALIO}]   # an offer stored before #73
        supplier = {ln["product_id"]: b["supplier_id"] for b in blocks for ln in b.get("lines", [])}
        unknown = [ln for ln in sim["lines"] if ln.get("unknown_stock") is not False]
        if unknown and human.startswith("auto-approve"):
            raise GatewayError(409, "STOCK_UNKNOWN", "auto-approve never places unconfirmed stock")
        must_confirm = sorted({supplier.get(ln["product_id"], VALIO) for ln in unknown})
        # Atomic commit point shared with the recall monitor. A notice arriving
        # during the live quote can still claim APPROVING and prevent this order.
        committed = self.db.proposals.update_one({'_id': proposal_id, 'kitchen_id': kitchen_id,
            'status': 'APPROVING', 'approving_key': key},
            {'$set': {'status': 'COMMITTING', 'offer_id': stored['offer_id'], 'committing_at': self.now()}})
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
            order = orders.set_outcome(self.db, order["order_id"], outcome="CONFIRMED", status="SENT",
                                       **self._receipt(kitchen_id, order))
            self.db.proposals.update_one({"_id": proposal_id},
                                         {"$set": {"status": "APPROVED", "order_id": order["order_id"]}})
            self._audit(kitchen_id, "order_placed", human, proposal_id=proposal_id,
                        order_id=order["order_id"], expected_total=sim["expected_total"],
                        supplier_must_confirm=must_confirm, **via)
        else:   # the key already placed an order: nothing new placed here, release the claim
            self.db.proposals.update_one({"_id": proposal_id, "status": "COMMITTING", "approving_key": key},
                                         {"$set": {"status": "READY"}, "$unset": {"approving_key": ""}})
        return {"proposal_id": proposal_id, **self._order_out(order)}

    def reject(self, kitchen_id: str, proposal_id: str, body: dict, *, human: str | None,
               via: dict | None = None) -> dict:
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
            'proposal_id': proposal_id, 'reason': doc.get('reject_reason', ''), **(via or {})},
            {'kitchen_id': kitchen_id, 'at': doc.get('rejected_at', self.now().isoformat())})
        if first_time:   # this path writes its audit event itself, so it also tells the webhooks (#277)
            try:
                from gateway import webhooks
                webhooks.dispatch(self.db, kitchen_id, 'proposal_rejected',
                                  {'proposal_id': proposal_id, 'reason': doc.get('reject_reason', '')},
                                  actor=doc.get('rejected_by', human))
            except Exception:
                pass
        try:
            total = orders.get_offer(self.db, doc["offer_id"])["simulation"]["expected_total"]
        except Exception:
            total = None
        self._decision_feedback(kitchen_id, proposal_id, "rejected", human, total=total,
                                reason=doc.get("reject_reason") or reason.strip())
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

    def _receipt(self, kitchen_id: str, order: dict) -> dict:
        """The signed receipt of a placed order (#290), as a field to store; {} when signing
        fails. Signing is never a reason to fail an order a person approved."""
        from gateway import signing
        try:
            return {"receipt": signing.sign_receipt(
                self.db, order_id=order["order_id"], kitchen_id=kitchen_id, offer_id=order["offer_id"],
                offer_hash=order.get("offer_hash"),
                expected_total=_money(Decimal(str(order["expected_total"]))), lines=order["lines"],
                approved_by=order["approved_by"],
                supplier_must_confirm=order.get("supplier_must_confirm") or [], at=self.now())}
        except Exception as exc:  # log the type only: never the key or the seed
            log.warning("receipt signing failed: %s", type(exc).__name__)
            return {}

    def _order_out(self, order: dict, found: dict | None = None) -> dict:
        """`found`: product_names.labels for these lines; read here when not given (#1130:
        names are computed at read time, so an order stored before them has them too)."""
        if found is None:
            found = product_names.labels(self.db, [ln.get("product_id") for ln in order["lines"]],
                                         order.get("kitchen_id"))
        return {"order_id": order["order_id"], "outcome": order["outcome"], "status": order["status"],
                "receipt": order.get("receipt"),     # signed order receipt (#290); null when not signed
                # #631: suppliers whose stock nobody confirmed yet; a person calls them
                "supplier_must_confirm": list(order.get("supplier_must_confirm") or []),
                "expected_total": _money(Decimal(str(order["expected_total"]))),
                "lines": [product_names.named(_line_out(ln), found) for ln in order["lines"]], "created_at": order["created_at"].isoformat()
                if hasattr(order["created_at"], "isoformat") else order["created_at"]}

    def list_orders(self, kitchen_id: str) -> list[dict]:
        rows = list(orders.list_orders(self.db, kitchen_id))
        found = product_names.labels(self.db, [ln.get("product_id") for o in rows for ln in o["lines"]], kitchen_id)
        return [self._order_out(o, found) for o in rows]

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
        from gateway.parse import product_words
        # The person's own words, not a model's query: when the kitchen's allergen rule removes
        # what they name, this need can never be searched or quoted into another product (#974).
        refusal = self._excluded_request(kitchen_id, product_words(need["text"]))
        if refusal:
            need["refusal"] = refusal
        self.db.needs.insert_one(need)
        return {"need_id": need["_id"], **{k: need[k] for k in ("quantity", "unit", "requested_date", "text")}}

    def tool_search(self, kitchen_id: str, query: str, filters: dict, limit: int,
                    need_id: str | None = None, mode: str | None = None) -> dict:
        """Catalog search for the Buyer. With the stored need it becomes a shortlist the
        Buyer can order from: only products sold in the need's measure (a request in litres
        never gets chocolate), and products that can still arrive on the requested date
        first. One availability call for the shortlist only, never for the whole catalog.

        `mode` ("text" or "hybrid") is the Catalog page's "Search by meaning" switch (#1382):
        it decides for this one request without a need. With a need (the Buyer) it is
        ignored, so the Buyer's basket never changes with it."""
        from gateway import catalog_search
        need = self.db.needs.find_one({"_id": need_id, "kitchen_id": kitchen_id}) if need_id else None
        if need_id and need is None:
            raise GatewayError(422, "INVALID_NEED", "unknown need_id")
        if need is None:
            hybrid = {"hybrid": True, "text": False}.get(mode)
            rows, kind = catalog_search.search(self.db, query, filters, limit, injected=self._search,
                                               hybrid=hybrid)
            out = {"products": _matched_by(rows), "search": kind}
            if hybrid and kind == "text" and (query or "").strip():
                out["meaning_unavailable"] = True     # no query vector: the words answered
            return out
        if need.get("refusal"):
            # Nothing to pick from, whatever the query: "butter" must not answer "peanut butter".
            return {"products": [], "requested_date": need["requested_date"], "measure": None,
                    "search": "text", "note": need["refusal"]["message"]}
        # Text search, or text plus meaning when SEARCH_HYBRID is on (gateway/catalog_search.py).
        rows, kind = catalog_search.search(self.db, query, filters, 50, injected=self._search)
        found_by_meaning: set[str] = set()
        fallback_note = None
        if not rows:
            # #1384: no word hit, so Atlas Vector Search once, with the same query and filters.
            rows, fallback_note = self._meaning_fallback(kitchen_id, query, filters)
            found_by_meaning = {r["product_id"] for r in rows}
        measure = need["unit"]
        # The kind of product the person named, from their own words, not the model's
        # query: "50 kg cheese" gets cheese, never a cheese sauce (gateway/kind.py). After
        # a hybrid search too: its first hit for "cheese" was a cheddar cheese sauce.
        # A need stored with no text (an outside client): the query is all there is.
        rows = self._of_kind(rows, query, filters, need["text"] or query, measure)
        same = [r for r in rows if (r.get("net_content") or {}).get("unit") == measure]
        filtered = bool(same) and measure in ("L", "KG")
        if filtered:
            rows = same
        rows = self._alias_first(kitchen_id, need["text"] or query, rows, measure if filtered else None)
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
        rows = rows[:limit]
        note = ("can_arrive false: the order cut-off for this date has passed or it cannot be delivered; "
                "prefer products with can_arrive true")
        shown = {r["product_id"] for r in rows} & found_by_meaning
        if shown:
            kind = "meaning-fallback"
            note = (f"{FOUND_BY_MEANING}; check that each product is what was asked. " + note)
            # Kept with the need, so the offer and the proposal can say it (tool_get_offer).
            self.db.needs.update_one({"_id": need["_id"]}, {"$addToSet": {"meaning_ids": {"$each": sorted(shown)}}})
        elif fallback_note and not rows:
            note = fallback_note
        return {"products": _matched_by(rows), "requested_date": need["requested_date"],
                "measure": measure if filtered else None, "search": kind, "note": note}

    def _meaning_fallback(self, kitchen_id: str, query: str, filters: dict) -> tuple[list[dict], str | None]:
        """#1384: the rows Atlas Vector Search finds for a query the words do not answer, and a
        note when there are none. It never runs in place of products the allergen filter
        removed, and it drops what the allergen rule refuses even when the vector side's
        pre-filter does not (the group rule: almonds excluded also excludes "tree nuts")."""
        from gateway import catalog_search
        if self._search is not None and self._meaning is None:
            return [], None                    # offline: an injected word search, no meaning search
        allergen_keys = ("exclude_allergens", "allergen_strictness")
        if any(filters.get(key) for key in allergen_keys):
            unfiltered = {k: v for k, v in filters.items() if k not in allergen_keys}
            try:
                hits, _ = catalog_search.search(self.db, query, unfiltered, 1, injected=self._search,
                                                hybrid_ok=False)
            except Exception:
                hits = [{}]                    # cannot tell: never risk a replacement
            if hits:
                return [], ("the allergen filter removes every product these words find; "
                            "nothing else is proposed in their place")
        try:
            rows = catalog_search.meaning(self.db, query, filters, 50, injected=self._meaning)
        except catalog_search.MeaningUnavailable:
            log.warning("meaning fallback could not run")
            return [], ("no product matches these words, and the meaning search could not run now "
                        "(Atlas Vector Search needs a new query vector); try other words")
        for r in rows:
            r.setdefault("matched_by", "meaning")     # no word hit: every row is by meaning (#1382)
        return self._allergen_safe(kitchen_id, filters, rows), None

    def _allergen_safe(self, kitchen_id: str, filters: dict, rows: list[dict]) -> list[dict]:
        """The rows no excluded allergen refuses: the caller's filter and the kitchen's rule, each
        with the group rule (store/allergen_groups.py). Strict, or a kitchen rule: undeclared
        counts too, and unknown allergen data is never safe."""
        from store.allergen_groups import excluded_allergen_codes
        rule = set(self._allergen_rule(kitchen_id))
        codes = set(excluded_allergen_codes(filters.get("exclude_allergens"))) | rule
        if not codes:
            return rows
        strict = filters.get("allergen_strictness") == "strict" or bool(rule)
        levels = ("contains", "may_contain") + (("undeclared",) if strict else ())
        safe = []
        for r in rows:
            allergens = r.get("allergens") or {}
            if any(codes & set(allergens.get(level) or ()) for level in levels):
                continue
            if strict and r.get("allergen_data_known") is False:
                continue
            safe.append(r)
        return safe

    def _alias_first(self, kitchen_id: str, words: str, rows: list[dict],
                     measure: str | None = None) -> list[dict]:
        """What this kitchen calls things (gateway/memory.py): when the request holds a phrase a
        person linked to a product, that product leads the shortlist, marked `alias: true`.
        The allergen rule, the cut-off and the stock checks still apply to it like to any other.
        With `measure` (the shortlist kept to L or KG), an aliased product sold in another
        measure is left out: a litre need never gets a kilo product at the top."""
        from gateway import memory
        from store.products import get_product
        try:
            pid = memory.lookup(self.db, kitchen_id, words, count_use=True)
        except Exception:
            return rows
        if not pid:
            return rows
        row = next((r for r in rows if r.get("product_id") == pid), None)
        if row is None:
            row = get_product(self.db, pid)
            if row is None:
                return rows
        if measure and (row.get("net_content") or {}).get("unit") != measure:
            return rows
        return [{**row, "alias": True}] + [r for r in rows if r.get("product_id") != pid]

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
        if not need.get("refusal") and set(ids) & set(need.get("meaning_ids") or ()):
            request["search"] = "meaning-fallback"     # the proposal says it (#1384)
        if need.get("refusal"):
            # Quote the refused products the person named, not the ones the caller picked.
            request["product_ids"] = need["refusal"]["product_ids"]
            request["refusal"] = {k: v for k, v in need["refusal"].items() if k != "product_ids"}
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
        compared = {}
        for method, collection in (("engine", "forecasts"), ("weekday-average", "forecast_baseline")):
            compared[method] = forecast_vs_actual(self.db, kitchen_id, d0, d1, collection)
        # Compare identical product/day observations, so missing baseline history
        # cannot inflate its error or give either method a different evaluation set.
        common = set.intersection(*({(pid, day) for pid, day, _, _ in pairs}
                                    for pairs in compared.values()))
        for method, candidates in compared.items():
            # Without one method there is no comparison to make, but the other
            # method's own measured accuracy remains useful. Empty series are
            # already mapped to unknown by the web, never a perfect 0% baseline.
            pairs = ([row for row in candidates if (row[0], row[1]) in common]
                     if all(compared.values()) else candidates)
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


def _set_by(line, need: dict, lot: Decimal):
    """A line whose quantity a person or an agent set (#303) says so in its `why`, and to
    what the engine rounded it. Built from the stored request only, so a re-quote at
    approve gives the same line."""
    if not need.get("set_by"):
        return line
    from dataclasses import replace
    asked = Decimal(str(need["quantity"]))
    note = f"Quantity set by {need['set_by']}"
    if "LOT_SIZE_ROUNDED" in line.reason_codes and line.quantity != asked:
        note += (f": {asked.normalize():f} {line.unit} asked, rounded up to {line.quantity.normalize():f} "
                 f"{line.unit} (sold in steps of {lot.normalize():f})")
    return replace(line, why=f"{note}. {line.why}")


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


def _form_day(body: dict) -> date | None:
    """The delivery day sent next to a free text (the date picked in a form), or None when
    it is missing or not a date. The parser uses it only when the text names no day."""
    try:
        return date.fromisoformat(body["requested_date"]) if body.get("requested_date") else None
    except (TypeError, ValueError):
        return None


def offer_out(offer: dict) -> dict:
    sim = offer["simulation"]
    lines = [_line_out(ln) for ln in sim["lines"]]
    return {"offer_id": offer["offer_id"], "valid_until": offer["valid_until"], **sim,
            "lines": lines, "blocks": _blocks_out(sim, lines),
            "signature": offer.get("signature"), "offer_hash": offer.get("offer_hash")}


__all__ = ["Gateway", "GatewayError", "offer_out", "asdict"]
