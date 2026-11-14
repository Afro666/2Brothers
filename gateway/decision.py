"""Plain-words decision record for a proposal (issue #282).

Built from the stored request and simulation only. Every number is copied from those
fields as the gateway stored it, never recomputed or rounded, so the summary cannot
disagree with the figures a person approves. No model writes it.
"""

from __future__ import annotations


def _name(pid: str, names: dict) -> str:
    name = names.get(pid)
    return f"{pid} {name}" if name else pid


def decision_summary(request: dict, sim: dict, names: dict | None = None) -> dict:
    """{"asked", "searched", "chosen", "left_out", "totals", "decide", "text"}.
    `names` maps product_id to a display name (optional)."""
    names = names or {}
    asked_text = (request.get("text") or "").strip()
    need = f"{request.get('quantity')} {request.get('unit')} for {request.get('requested_date')}"
    asked = f"Asked: \"{asked_text}\" ({need})." if asked_text else f"Asked: {need}."

    ids = list(request.get("product_ids") or [])
    searched = (f"Checked {len(ids)} product(s) with Valio prices and stock for "
                f"{request.get('requested_date')}: {', '.join(ids)}.")

    chosen = [f"{ln['quantity']} {ln['unit']} of {_name(ln['product_id'], names)}, "
              f"EUR {ln['total']} ex VAT: {ln['why']}" for ln in sim.get("lines") or []]
    left_out = [f"{_name(e['product_id'], names)} left out: {e['reason']}" for e in sim.get("excluded") or []]
    if sim.get("shortfall") not in (None, "0", "0.0"):
        left_out.append(f"{sim['shortfall']} {sim.get('measure')} of the request cannot be covered for this date.")

    fee = sim.get("delivery_fee")
    totals = (f"Total EUR {sim['expected_total']} (EUR {sim['total_ex_vat']} ex VAT + VAT EUR {sim['vat']}"
              + (f" + delivery EUR {fee}" if fee is not None else "; delivery fee unknown: supplier terms not set")
              + ").")
    alt = sim.get("alternative")
    if alt:
        totals += f" A cheaper option was also found: EUR {alt['total_ex_vat']} ex VAT."

    verdict = (sim.get("mandate") or {}).get("verdict")
    decide = []
    if verdict == "NEEDS_APPROVAL":
        decide.append(f"Nothing is ordered until a person approves the total of EUR {sim['expected_total']}.")
    elif verdict == "REFUSED":
        decide.append("Nothing can be ordered: no line passed the checks.")
    unknown = [ln for ln in sim.get("lines") or [] if ln.get("unknown_stock") is not False]
    if unknown:
        decide.append("Valio has not confirmed stock for " + ", ".join(
            f"{_name(ln['product_id'], names)} ({ln['quantity']} {ln['unit']})" for ln in unknown)
            + ": the order cannot be placed until Valio confirms that stock.")

    parts = [asked, searched]
    parts += ["Chosen: " + c for c in chosen] or ["Chosen: nothing."]
    parts += left_out
    parts += [totals] + ["To decide: " + d for d in decide]
    return {"asked": asked, "searched": searched, "chosen": chosen, "left_out": left_out,
            "totals": totals, "decide": decide, "text": "\n".join(parts)}
