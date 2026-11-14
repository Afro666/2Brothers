"""Plain-words decision record for a proposal (issue #282).

Built from the stored request and simulation only. Every number is copied from those
fields as the gateway stored it, never recomputed or rounded, so the summary cannot
disagree with the figures a person approves. No model writes it.
"""

from __future__ import annotations

from gateway.suppliers import VALIO

# #1384: a product the Buyer's search found by meaning only, because the words found nothing.
FOUND_BY_MEANING = "found by meaning (Atlas Vector Search) after the word search found nothing"


def _supplier_of(sim: dict) -> dict:
    """product_id -> supplier name, from the proposal's supplier blocks (#73).
    Valio keeps its short name; a line outside any block (stored before #73) is Valio's."""
    out = {}
    for b in sim.get("blocks") or []:
        name = "Valio" if b.get("supplier_id") == VALIO else (b.get("name") or b.get("supplier_id"))
        for ln in b.get("lines") or []:
            out[ln["product_id"]] = name
    return out


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

    supplier_of = _supplier_of(sim)
    suppliers = list(dict.fromkeys(supplier_of.values())) or ["Valio"]
    source = f"{suppliers[0]} prices and stock" if len(suppliers) == 1 else "supplier prices and stock"
    ids = list(request.get("product_ids") or [])
    searched = (f"Checked {len(ids)} product(s) with {source} for "
                f"{request.get('requested_date')}: {', '.join(ids)}.")
    if request.get("search") == "meaning-fallback":
        searched += f" {FOUND_BY_MEANING[0].upper()}{FOUND_BY_MEANING[1:]}."

    chosen = [f"{ln['quantity']} {ln['unit']} of {_name(ln['product_id'], names)}, "
              f"EUR {ln['total']} ex VAT: {ln['why']}" for ln in sim.get("lines") or []]
    left_out = [f"{_name(e['product_id'], names)} left out: {e['reason']}" for e in sim.get("excluded") or []]
    if sim.get("shortfall") not in (None, "0", "0.0"):
        left_out.append(f"{sim['shortfall']} {sim.get('measure')} of the request cannot be covered for this date.")
    refused_needs = list(request.get("problems") or []) if request.get("made_by") == "list" else []
    left_out = [f"Not proposed: {p}" for p in refused_needs] + left_out     # several products (#1375)

    fee = sim.get("delivery_fee")
    if not sim.get("lines"):
        totals = "Nothing is ordered, so there is no total."
    else:
        vat = (f"VAT EUR {sim['vat']}" if sim.get("vat") is not None else
               "VAT unknown for " + ", ".join(_name(pid, names) for pid in sim.get("vat_unknown") or [])
               + ", so no total incl VAT")
        totals = (f"Total EUR {sim['expected_total']} (EUR {sim['total_ex_vat']} ex VAT + {vat}"
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
        # A request the kitchen's allergen rule refuses as a whole says so in its own words (#974).
        refusal = (request.get("refusal") or {}).get("message")
        if refused_needs and not refusal:
            refusal = " ".join(refused_needs)      # every need of a list was refused (#1375)
        decide.append(f"Nothing can be ordered. {refusal}" if refusal
                      else "Nothing can be ordered: no line passed the checks.")
    unknown = [ln for ln in sim.get("lines") or [] if ln.get("unknown_stock") is not False]
    by_supplier: dict[str, list] = {}
    for ln in unknown:
        by_supplier.setdefault(supplier_of.get(ln["product_id"], "Valio"), []).append(ln)
    for supplier, lines in by_supplier.items():
        decide.append(f"{supplier} has not confirmed stock for " + ", ".join(
            f"{_name(ln['product_id'], names)} ({ln['quantity']} {ln['unit']})" for ln in lines)
            # Nothing is sent to a supplier (#1863): the order is RECORDED, supplier_outcome NOT_SENT.
            + f": you can still approve; the order is recorded, nothing is sent to {supplier}, "
              f"and {supplier} must still confirm that stock.")

    parts = [asked, searched]
    parts += ["Chosen: " + c for c in chosen] or ["Chosen: nothing."]
    parts += left_out
    parts += [totals] + ["To decide: " + d for d in decide]
    return {"asked": asked, "searched": searched, "chosen": chosen, "left_out": left_out,
            "totals": totals, "decide": decide, "text": "\n".join(parts)}
