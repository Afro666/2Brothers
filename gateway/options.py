"""Options on a proposal: the "confirmed stock only" option, and choosing an option.

Why. Live on 2026-11-14 every milk proposal in the demo inbox had a line whose stock Valio
does not report. Such a line cannot be placed (a person's yes is not stock confirmation),
so no Approve button worked. The engine already knew the part Valio confirms
(`partial_fill.now`, #288), but only as text. Here it becomes an option with its own
stored, signed quote that a person can choose and then approve.

Rules.
- An option never selects, approves or places itself. Choosing needs a human session and
  only swaps the proposal's basket; the person then approves the new exact total.
- A basket with a line of unconfirmed stock cannot be chosen (409 `STOCK_UNKNOWN`): it
  would still not be placeable.
- After a refused choice the proposal keeps the basket it had.

Contract: docs/contract.md, "Chef substitute choices".
"""

from __future__ import annotations

import logging
from decimal import Decimal

from store import orders

TIERS = ("good", "better", "best")
CONFIRMED = "confirmed"

log = logging.getLogger(__name__)


def merged(doc: dict) -> list[dict]:
    """The proposal's options as the API answers them: the confirmed-stock option first,
    then the Buyer's own, at most three, with tiers in that order."""
    from gateway.service import _line_out     # here: service.py imports this module

    own = doc.get("confirmed_option")
    if own:   # stored offer lines keep the two dataset numbers as text; the API answers numbers
        own = {**own, "lines": [_line_out(line) for line in own.get("lines") or []]}
    options = ([own] if own else []) + list(doc.get("substitute_options") or [])
    return [{**option, "tier": TIERS[n]} for n, option in enumerate(options[:len(TIERS)])]


def attach_confirmed(gw, kitchen_id: str, proposal_id: str, request: dict, sim: dict) -> None:
    """Store the confirmed part of a short order as an option. Never fails a proposal."""
    try:
        option = _confirmed_option(gw, kitchen_id, request, sim)
        if option:
            gw.db.proposals.update_one({"_id": proposal_id, "kitchen_id": kitchen_id},
                                       {"$set": {"confirmed_option": option}})
    except Exception:
        log.warning("confirmed-stock option failed: kitchen_id=%s proposal_id=%s",
                    kitchen_id, proposal_id, exc_info=True)


def _catalog_quote(gw, kitchen_id: str, request: dict) -> dict | None:
    """The same need quoted over the request's products plus the catalog shortlist for
    its text. Used when the chosen basket has no confirmed stock: the Buyer model once
    picked a single product whose stock Valio does not report, while another lactose-free
    milk had confirmed stock. None when the request has no text to search by."""
    text = (request.get("text") or "").strip()
    if not text:
        return None
    from gateway.candidates import SEARCH_LIMIT, pick_candidates
    from gateway.parse import ParseError, parse_request
    try:
        query = parse_request(text, gw.now().date()).query
    except ParseError:
        return None
    from gateway import catalog_search
    rows, _ = catalog_search.search(gw.db, query, {}, SEARCH_LIMIT, kitchen_id, injected=gw._search)
    ids = list(dict.fromkeys([*request["product_ids"], *pick_candidates(rows, request["unit"])]))
    if set(ids) == set(request["product_ids"]):
        return None      # the catalog adds nothing to the basket already quoted
    offer = gw._quote(kitchen_id, {"product_ids": ids, "quantity": request["quantity"],
                                   "unit": request["unit"], "requested_date": request["requested_date"],
                                   "text": text, "made_by": "confirmed_search"})
    return offer


def _all_confirmed(quote: dict) -> bool:
    lines = quote.get("lines") or []
    return (bool(lines) and all(line.get("unknown_stock") is False for line in lines)
            and Decimal(str(quote.get("shortfall") or "0")) <= 0)


def _confirmed_option(gw, kitchen_id: str, request: dict, sim: dict) -> dict | None:
    if request.get("needs") or not sim.get("lines"):
        return None
    if all(line.get("unknown_stock") is False for line in sim["lines"]):
        return None      # the plan is placeable as it is
    part, found = sim.get("partial_fill"), ""
    if not (part and (part.get("now") or {}).get("lines")):
        wide = _catalog_quote(gw, kitchen_id, request)
        if wide is None:
            return None
        found = " This stock was found in the catalog, outside the basket above."
        if _all_confirmed(wide["simulation"]):      # the catalog covers the whole need
            return _option(gw, wide, request["unit"], None,
                           f"Order all {request['quantity']} {request['unit']} from stock the supplier "
                           "confirms for this date." + found)
        part = wide["simulation"].get("partial_fill")
        if not (part and (part.get("now") or {}).get("lines")):
            return None
    now = part["now"]
    ids = [line["product_id"] for line in now["lines"]]
    offer = gw._quote(kitchen_id, {"product_ids": ids, "quantity": now["quantity"], "unit": part["measure"],
                                   "requested_date": request["requested_date"],
                                   "text": request.get("text") or "", "made_by": "confirmed_only"})
    if not _all_confirmed(offer["simulation"]):
        return None
    measure, held = part["measure"], part["remaining"]
    return _option(gw, offer, measure, held,
                   f"Order the confirmed {now['quantity']} {measure} now. The other {held} {measure} "
                   "is held until the supplier confirms stock; nothing is ordered for it." + found)


def _option(gw, offer: dict, measure: str, held: str | None, why: str) -> dict:
    """An option entry for a stored, signed quote whose every line has confirmed stock."""
    quote = offer["simulation"]
    ids = [line["product_id"] for line in quote["lines"]]
    known = {d["_id"]: d.get("allergen_data_known") is True
             for d in gw.db.products.find({"_id": {"$in": ids}}, {"allergen_data_known": 1})}
    option = {
        "source": CONFIRMED, "offer_id": offer["offer_id"],
        "expected_total": quote["expected_total"], "currency": quote["currency"],
        "lines": quote["lines"], "why": why,
        "requires_chef_approval": True, "stock_confirmed": True,
        "allergen_data_known": all(known.get(pid, False) for pid in ids),
        "recommended": True,
    }
    if held is not None:
        option["held"] = {"quantity": held, "unit": measure}
    return option


def choose(gw, kitchen_id: str, proposal_id: str, body: dict, *, human: str | None) -> dict:
    """Make one option the proposal's basket, after a fresh quote. Nothing is approved."""
    from gateway.service import GatewayError

    if not human:
        raise GatewayError(403, "HUMAN_SESSION_REQUIRED", "only a person can choose an option")
    offer_id, key = body.get("offer_id"), body.get("idempotency_key")
    if not isinstance(offer_id, str) or not offer_id or not isinstance(key, str) or not key:
        raise GatewayError(422, "INVALID_REQUEST", "offer_id and idempotency_key are required")
    doc = gw.db.proposals.find_one({"_id": proposal_id, "kitchen_id": kitchen_id})
    if doc is None:
        raise GatewayError(404, "PROPOSAL_NOT_FOUND", "no such proposal")
    for seen in doc.get("choices") or []:
        if seen["key"] == key:
            if seen["offer_id"] != offer_id:
                raise GatewayError(409, "IDEMPOTENCY_KEY_REUSED", "key used with another option")
            return gw._proposal_out(doc)
    if doc["status"] != "READY":
        raise GatewayError(409, "NOT_PENDING", f"proposal is {doc['status']}")
    option = next((o for o in merged(doc) if o.get("offer_id") == offer_id), None)
    if option is None:
        raise GatewayError(404, "OPTION_NOT_FOUND", "this is not one of the proposal's options")
    try:
        stored = orders.get_offer(gw.db, offer_id)
    except Exception:
        stored = None
    if not stored or stored.get("kitchen_id") != kitchen_id:
        raise GatewayError(404, "OPTION_NOT_FOUND", "the option's quote is not stored")
    fresh = gw._quote(kitchen_id, stored["request"])
    lines = fresh["simulation"].get("lines") or []
    wanted = {line["product_id"] for line in option.get("lines") or []}
    missing = wanted - {line["product_id"] for line in lines}
    if missing:
        reasons = " ".join(e.get("reason") or "" for e in fresh["simulation"].get("excluded") or []
                           if e.get("product_id") in missing)
        if "cut-off" in reasons:
            raise GatewayError(409, "CLOSING_PASSED", "the order cut-off of a line has passed")
        raise GatewayError(409, "OPTION_UNAVAILABLE", "a product of this option cannot be ordered now")
    if any(line.get("unknown_stock") is not False for line in lines):
        raise GatewayError(409, "STOCK_UNKNOWN", "the fresh quote cannot confirm the stock of a line")

    def refreshed(entry: dict | None) -> dict | None:
        return {**entry, "offer_id": fresh["offer_id"]} if entry and entry.get("offer_id") == offer_id else entry

    changes = {"offer_id": fresh["offer_id"], "request": stored["request"],
               "chosen_option": {"source": option.get("source"), "from_offer_id": doc["offer_id"]},
               "confirmed_option": refreshed(doc.get("confirmed_option")),
               "substitute_options": [refreshed(o) for o in doc.get("substitute_options") or []]}
    if "original_request" not in doc:
        changes["original_request"] = doc["request"]
    claimed = gw.db.proposals.find_one_and_update(
        {"_id": proposal_id, "kitchen_id": kitchen_id, "status": "READY", "offer_id": doc["offer_id"]},
        {"$set": changes, "$push": {"choices": {"key": key, "offer_id": offer_id,
                                                "result_offer_id": fresh["offer_id"]}}})
    if claimed is None:      # approved, rejected, held or re-quoted in the meantime
        raise GatewayError(409, "NOT_PENDING", "the proposal changed; look at it again")
    gw._audit(kitchen_id, "option_chosen", human, proposal_id=proposal_id,
              source=option.get("source"), from_offer_id=doc["offer_id"], offer_id=fresh["offer_id"],
              expected_total=fresh["simulation"]["expected_total"], held=option.get("held"))
    return gw._proposal_out(gw.db.proposals.find_one({"_id": proposal_id}))
