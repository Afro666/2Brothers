"""Changing a proposal's lines (#303): set a quantity, remove a line, add an addable product.

Why. Live on 2026-11-14 a person could not change the pieces on a proposal; the only
way out was to reject it and ask again. Every action also has to work from chat (MCP).

Rules.
- A person or an agent may change a proposal; only a person approves it. A change
  approves and places nothing.
- Only a READY proposal changes. A recall-held, approved or rejected one is 409 NOT_PENDING.
- Quantities are in each line's sales unit; 0 removes the line. An added product must be
  on the proposal's addable list (`Gateway.addable`).
- The new basket is quoted live on the same path as the proposal (`Gateway._quote`, an
  offer snapshot with `offer_hash`): the engine rounds to the lot size and the mandate,
  recall and allergen guards run again. The proposal keeps its id and gets a new
  `offer_id` and `expected_total`, so approve refuses the old total (TOTAL_MISMATCH).
- After a refused change the proposal keeps the basket it had.

Contract: docs/contract.md, "Changing a proposal".
"""

from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation

from store import orders

MAX_LINES = 200
MAX_QUANTITY = Decimal("1000000")

log = logging.getLogger(__name__)


def _n(x: Decimal) -> str:
    return f"{x.normalize():f}"


def _entries(body: dict, field: str) -> list[tuple[str, Decimal]]:
    from gateway.service import GatewayError
    raw = body.get(field)
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > MAX_LINES:
        raise GatewayError(422, "INVALID_REQUEST", f"{field} must be a list of at most {MAX_LINES} lines")
    out = []
    for entry in raw:
        pid = entry.get("product_id") if isinstance(entry, dict) else None
        value = entry.get("quantity") if isinstance(entry, dict) else None
        if not isinstance(pid, str) or not pid or len(pid) > 200 or isinstance(value, bool) \
                or not isinstance(value, (str, int, float)):
            raise GatewayError(422, "INVALID_REQUEST", f"each {field} entry needs product_id and quantity")
        try:
            quantity = Decimal(str(value))
        except InvalidOperation:
            raise GatewayError(422, "INVALID_REQUEST", f"{pid}: quantity must be a number") from None
        if not quantity.is_finite() or quantity < 0 or quantity > MAX_QUANTITY:
            raise GatewayError(422, "INVALID_REQUEST", f"{pid}: quantity must be 0 or more")
        if field == "add" and quantity == 0:
            raise GatewayError(422, "INVALID_REQUEST", f"{pid}: an added product needs a quantity above 0")
        out.append((pid, quantity))
    return out


def change(gw, kitchen_id: str, proposal_id: str, body: dict, *, actor: str, person: str | None) -> dict:
    """Apply `lines` and `add` to a READY proposal after a fresh quote. `person` is the
    signed-in person (None for an agent or a token): only a person's change is feedback."""
    from gateway.service import GatewayError, _hash

    key = body.get("idempotency_key")
    if not isinstance(key, str) or not key.strip():
        raise GatewayError(422, "INVALID_REQUEST", "idempotency_key is required")
    lines, add = _entries(body, "lines"), _entries(body, "add")
    if not lines and not add:
        raise GatewayError(422, "INVALID_REQUEST", "lines or add must name at least one product")
    ids = [pid for pid, _ in lines + add]
    if len(ids) != len(set(ids)):
        raise GatewayError(422, "INVALID_REQUEST", "a product is named twice")
    payload = _hash({"lines": [[p, _n(q)] for p, q in lines], "add": [[p, _n(q)] for p, q in add]})

    doc = gw.db.proposals.find_one({"_id": proposal_id, "kitchen_id": kitchen_id})
    if doc is None:
        raise GatewayError(404, "PROPOSAL_NOT_FOUND", "no such proposal")
    for seen in doc.get("changes") or []:
        if seen["key"] == key:
            if seen["payload_hash"] != payload:
                raise GatewayError(409, "IDEMPOTENCY_KEY_REUSED", "key used with another change")
            return gw._proposal_out(doc)
    if doc["status"] != "READY":
        held = ": a recall holds it" if doc["status"] == "BLOCKED_BY_RECALL" else ""
        raise GatewayError(409, "NOT_PENDING", f"proposal is {doc['status']}{held}")
    if any(a.get("match") in ("exact", "possible") for a in doc.get("recall_alerts") or []):
        raise GatewayError(409, "NOT_PENDING", "a recall holds this basket; review its replacement proposal")

    stored = orders.get_offer(gw.db, doc["offer_id"])
    before_total = stored["simulation"]["expected_total"]
    current: dict[str, tuple[Decimal, str]] = {}
    for line in stored["simulation"]["lines"]:
        had, unit = current.get(line["product_id"], (Decimal(0), line["unit"]))
        current[line["product_id"]] = (had + Decimal(str(line["quantity"])), unit)
    for pid, _ in lines:
        if pid not in current:
            raise GatewayError(404, "LINE_NOT_FOUND", f"{pid} is not on this proposal; add it with add")
    units = {}
    if add:
        for pid, _ in add:
            if pid in current:
                raise GatewayError(422, "INVALID_REQUEST", f"{pid} is on the proposal already; set it with lines")
        rows = {r["product_id"]: r for r in gw.addable(kitchen_id, proposal_id)["rows"]}
        for pid, _ in add:
            row = rows.get(pid)
            if row is None or not row.get("addable"):
                raise GatewayError(409, "NOT_ADDABLE", f"{pid} is not on this proposal's addable list")
            units[pid] = row["unit"]

    asked = dict(lines)
    needs = []
    for pid, (had, unit) in current.items():
        quantity = asked.get(pid, had)
        if quantity > 0:
            need = {"product_id": pid, "quantity": _n(quantity), "unit": unit, "sales_unit": True}
            if pid in asked:
                need["set_by"] = actor
            needs.append(need)
    needs += [{"product_id": pid, "quantity": _n(q), "unit": units[pid], "sales_unit": True, "set_by": actor}
              for pid, q in add]
    if not needs:
        raise GatewayError(422, "EMPTY_PROPOSAL", "a proposal needs at least one line; reject it instead")

    old = doc["request"]
    request = {key_: old[key_] for key_ in ("text", "made_by", "event", "window", "problems", "query",
                                            "items", "split_by")    # a list of needs (#1375)
               if key_ in old}
    request.update({"product_ids": [n["product_id"] for n in needs], "quantity": str(len(needs)),
                    "unit": "products", "requested_date": old["requested_date"], "needs": needs,
                    "changed_by": actor})
    request.setdefault("text", "")
    fresh = gw._quote(kitchen_id, request)
    sim = fresh["simulation"]
    got: dict[str, Decimal] = {}
    for line in sim["lines"]:
        got[line["product_id"]] = got.get(line["product_id"], Decimal(0)) + Decimal(str(line["quantity"]))
    missing = [n["product_id"] for n in needs if n["product_id"] not in got]
    if missing:
        reasons = "; ".join(f"{e['product_id']}: {e['reason']}" for e in sim.get("excluded") or []
                            if e.get("product_id") in missing)
        code = "CLOSING_PASSED" if "cut-off" in reasons else "LINE_UNAVAILABLE"
        raise GatewayError(409, code, "a product of this change cannot be ordered now"
                           + (f" ({reasons})" if reasons else ""))

    changes = {"offer_id": fresh["offer_id"], "request": request}
    if "original_request" not in doc:
        changes["original_request"] = old
    claimed = gw.db.proposals.find_one_and_update(
        {"_id": proposal_id, "kitchen_id": kitchen_id, "status": "READY", "offer_id": doc["offer_id"]},
        {"$set": changes, "$push": {"changes": {"key": key, "payload_hash": payload, "by": actor,
                                                "from_offer_id": doc["offer_id"],
                                                "result_offer_id": fresh["offer_id"]}}})
    if claimed is None:      # approved, rejected, held or changed in the meantime
        raise GatewayError(409, "NOT_PENDING", "the proposal changed; look at it again")

    diff = []
    for pid, quantity in lines + add:
        had, unit = current.get(pid, (Decimal(0), units.get(pid)))
        diff.append({"product_id": pid, "unit": unit, "from_qty": _n(had), "asked_qty": _n(quantity),
                     "to_qty": _n(got.get(pid, Decimal(0)))})
    gw._audit(kitchen_id, "proposal_changed", actor, proposal_id=proposal_id,
              from_offer_id=doc["offer_id"], offer_id=fresh["offer_id"],
              from_total=before_total, expected_total=sim["expected_total"], changes=diff)
    if person:
        _feedback(gw, kitchen_id, proposal_id, diff, person)
    return gw._proposal_out(gw.db.proposals.find_one({"_id": proposal_id}))


def _feedback(gw, kitchen_id: str, proposal_id: str, diff: list[dict], person: str) -> None:
    """A person's change is learning data (store/feedback.py). Never fails the change."""
    rows = []
    for d in diff:
        before, after = Decimal(d["from_qty"]), Decimal(d["to_qty"])
        if before == after:
            continue
        kind = "line_added" if before == 0 else "line_removed" if after == 0 else "qty_changed"
        rows.append({"kind": kind, "product_id": d["product_id"], "unit": d["unit"],
                     "from_qty": None if kind == "line_added" else d["from_qty"],
                     "to_qty": None if kind == "line_removed" else d["to_qty"]})
    try:
        from store.feedback import record_feedback
        record_feedback(gw.db, kitchen_id, proposal_id, rows, person)
    except Exception:
        log.warning("change feedback failed: kitchen_id=%s proposal_id=%s", kitchen_id, proposal_id,
                    exc_info=True)
