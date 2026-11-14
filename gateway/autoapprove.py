"""Earned auto-approve (#299). Off by default; a kitchen can switch it on only after the
tool has learned from its decisions (Aron, 2026-11-14).

Rules, all checked here in one place:
- Learning period: at least 4 weeks since the first human decision, at least 20 human
  decisions, and at most 10% of the approved proposals were edited before approval.
- Only an approver switches it on, with a limit in EUR that they choose.
- A proposal is approved automatically only when ALL of these hold: total at or under the
  limit; no warning; every line has confirmed stock; nothing was excluded for a cut-off,
  allergen, recall or sales block; nothing is short; no substitute; and every product on it
  was already on at least 3 human-approved orders of this kitchen without being edited.
- The approval is recorded as "auto-approve (rule set by <person>)", with the evidence, and
  goes through the same live re-check as a human approval (TOTAL_MISMATCH still refuses).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

WEEKS_NEEDED = 4
DECISIONS_NEEDED = 20
MAX_EDIT_RATE = 0.10
PRODUCT_ORDERS_NEEDED = 3
MAX_LIMIT_EUR = Decimal("2000")
NEVER_CODES = {"STOCK_UNKNOWN", "PARTIAL_STOCK", "CLOSING_PASSED", "ALLERGEN_RULE", "ALLERGEN_DATA_MISSING",
               "SUBSTITUTE_NEEDS_OK", "SUBSTITUTE_FAT_LEVEL", "EVENT_LINE", "STANDING_ORDER_DRIFT",
               "STOCK_COUNT_MISSING", "BLOCKED_BY_RECALL"}


class AutoApproveError(ValueError):
    def __init__(self, code: str, message: str, status: int = 409):
        super().__init__(message)
        self.code, self.status = code, status


def _aware(value):
    return value.replace(tzinfo=timezone.utc) if isinstance(value, datetime) and value.tzinfo is None else value


def _human(decided_by: str | None) -> bool:
    return bool(decided_by) and not str(decided_by).startswith("auto-approve")


def learning(db, kitchen_id: str, now: datetime) -> dict:
    """How far the kitchen is through the learning period, from its own decisions."""
    decided = [a for a in db.approvals.find({"kitchen_id": kitchen_id, "status": {"$in": ["APPROVED", "REJECTED"]}})
               if _human(a.get("decided_by"))]
    first = min((_aware(a["decided_at"]) for a in decided if a.get("decided_at")), default=None)
    weeks = int((now - first) / timedelta(weeks=1)) if first else 0
    approved = [a for a in decided if a["status"] == "APPROVED"]
    edited_proposals = {f["proposal_id"] for f in db.feedback.find(
        {"meta.kitchen_id": kitchen_id, "kind": {"$in": ["qty_changed", "line_removed", "line_added"]}},
        {"proposal_id": 1})}
    proposals = {p["approval_id"]: p["_id"] for p in db.proposals.find(
        {"kitchen_id": kitchen_id, "approval_id": {"$ne": None}}, {"approval_id": 1})}
    edited = sum(1 for a in approved if proposals.get(a["_id"]) in edited_proposals)
    edit_rate = edited / len(approved) if approved else 0.0
    done = weeks >= WEEKS_NEEDED and len(decided) >= DECISIONS_NEEDED and edit_rate <= MAX_EDIT_RATE
    return {"weeks": weeks, "weeks_needed": WEEKS_NEEDED, "decisions": len(decided),
            "decisions_needed": DECISIONS_NEEDED, "edit_rate": round(edit_rate, 3),
            "max_edit_rate": MAX_EDIT_RATE, "learning_done": done}


def settings(db, kitchen_id: str) -> dict:
    doc = db.kitchen_settings.find_one({"_id": kitchen_id}, {"auto_approve": 1}) or {}
    auto = doc.get("auto_approve") or {}
    return {"enabled": bool(auto.get("enabled")), "limit_eur": auto.get("limit_eur"),
            "set_by": auto.get("set_by"), "set_at": auto.get("set_at")}


def status(db, kitchen_id: str, now: datetime) -> dict:
    return {**settings(db, kitchen_id), "learning": learning(db, kitchen_id, now),
            "never": sorted(NEVER_CODES), "max_limit_eur": f"{MAX_LIMIT_EUR:f}"}


def configure(db, kitchen_id: str, *, enabled: bool, limit_eur, person: str, now: datetime) -> dict:
    if not isinstance(enabled, bool):
        raise AutoApproveError("INVALID_REQUEST", "enabled must be true or false", 422)
    change: dict = {"enabled": enabled, "set_by": person, "set_at": now.isoformat()}
    if enabled:
        if not learning(db, kitchen_id, now)["learning_done"]:
            raise AutoApproveError("LEARNING_PERIOD", "the Buyer is still learning from this kitchen's decisions")
        try:
            limit = Decimal(str(limit_eur))
        except Exception:
            raise AutoApproveError("INVALID_REQUEST", "limit_eur must be a number", 422) from None
        if not limit.is_finite() or limit <= 0 or limit > MAX_LIMIT_EUR:
            raise AutoApproveError("INVALID_REQUEST", f"limit_eur must be above 0 and at most {MAX_LIMIT_EUR}", 422)
        change["limit_eur"] = f"{limit:f}"
    else:
        change["limit_eur"] = settings(db, kitchen_id).get("limit_eur")
    db.kitchen_settings.update_one({"_id": kitchen_id}, {"$set": {"auto_approve": change}}, upsert=True)
    return settings(db, kitchen_id)


def _trusted_products(db, kitchen_id: str) -> set[str]:
    """Products on at least 3 human-approved orders whose proposals were never edited."""
    edited = {(f["proposal_id"], f["meta"].get("product_id")) for f in db.feedback.find(
        {"meta.kitchen_id": kitchen_id, "kind": {"$in": ["qty_changed", "line_removed"]}})}
    counts: dict[str, int] = {}
    bad: set[str] = set()
    for order in db.orders.find({"kitchen_id": kitchen_id, "outcome": "CONFIRMED"}):
        if not _human(order.get("approved_by")):
            continue
        for line in order.get("lines", []):
            pid = line.get("product_id")
            if (order.get("proposal_id"), pid) in edited:
                bad.add(pid)
            counts[pid] = counts.get(pid, 0) + 1
    return {pid for pid, n in counts.items() if n >= PRODUCT_ORDERS_NEEDED and pid not in bad}


def decide(db, kitchen_id: str, simulation: dict, request: dict, now: datetime) -> tuple[bool, list[str], dict]:
    """(auto?, reasons it is not, evidence). Never raises: any doubt means a person decides."""
    conf = settings(db, kitchen_id)
    if not conf["enabled"]:
        return False, ["auto-approve is off"], {}
    progress = learning(db, kitchen_id, now)
    why: list[str] = []
    if not progress["learning_done"]:
        why.append("the learning period is not complete")
    mandate = simulation.get("mandate") or {}
    lines = simulation.get("lines") or []
    codes = set(mandate.get("reason_codes") or []) | {c for ln in lines for c in ln.get("reason_codes", [])}
    if not lines or mandate.get("verdict") != "NEEDS_APPROVAL":
        why.append("nothing to approve")
    if mandate.get("warnings"):
        why.append("a warning: " + ", ".join(mandate["warnings"]))
    if codes & NEVER_CODES:
        why.append("needs a person: " + ", ".join(sorted(codes & NEVER_CODES)))
    if simulation.get("excluded"):
        why.append("a product was excluded")
    if any(ln.get("unknown_stock") is not False for ln in lines):
        why.append("stock is not confirmed")
    if Decimal(str(simulation.get("shortfall") or "0")) > 0:
        why.append("the request is not fully covered")
    if request.get("event") or request.get("made_by") == "recall-buyer":
        why.append("not a routine order")
    try:
        over = Decimal(str(simulation.get("expected_total"))) > Decimal(str(conf["limit_eur"]))
    except Exception:
        over = True
    if over:
        why.append("above the kitchen's auto-approve limit")
    trusted = _trusted_products(db, kitchen_id)
    new = sorted({ln.get("product_id") for ln in lines} - trusted)
    if new:
        why.append("products without 3 unedited approved orders: " + ", ".join(map(str, new)))
    evidence = {"limit_eur": conf["limit_eur"], "rule_set_by": conf["set_by"], **progress}
    return not why, why, evidence
