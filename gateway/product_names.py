"""Product names on the lines a person reads (#1130): proposals and orders.

Every line carries `product_name` (English), `product_name_fi` (Finnish) and `brand`, each a
string or null. Read from the product row, never invented: a product the catalog or the
kitchen's own products do not know keeps null in all three. One query per proposal or
order list, never one per line.
"""

from __future__ import annotations

import re

FIELDS = ("product_name", "product_name_fi", "brand")
UNKNOWN = dict.fromkeys(FIELDS)


def _text(value) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def labels(db, ids, kitchen_id: str | None = None) -> dict[str, dict]:
    """{product_id: {"product_name", "product_name_fi", "brand"}} for the known ids, in one
    query. With `kitchen_id`: catalog rows plus that kitchen's own products, never another
    kitchen's (the scope of store.products.get_products). Without it: any row by id."""
    ids = sorted({str(pid) for pid in ids if pid})
    if not ids:
        return {}
    query: dict = {"_id": {"$in": ids}}
    if kitchen_id is not None:
        query["$or"] = [{"kitchen_id": {"$exists": False}}, {"kitchen_id": kitchen_id}]
    out = {}
    for doc in db.products.find(query, {"names": 1, "brand": 1}):
        names = doc.get("names") if isinstance(doc.get("names"), dict) else {}
        out[doc["_id"]] = {"product_name": _text(names.get("en")), "product_name_fi": _text(names.get("fi")),
                           "brand": _text(doc.get("brand"))}
    return out


def named(line: dict, found: dict[str, dict]) -> dict:
    """The line with the three name fields (null when the product is not known)."""
    return {**line, **found.get(line.get("product_id"), UNKNOWN)}


def named_lines(lines, found: dict[str, dict]) -> list[dict]:
    return [named(line, found) for line in lines or []]


def proposal_ids(answer: dict) -> set[str]:
    """Every product id a proposal answer shows on a line or an excluded entry."""
    ids = {e.get("product_id") for e in answer.get("excluded") or []}
    groups = [answer.get("lines"), *[b.get("lines") for b in answer.get("blocks") or []],
              *[o.get("lines") for o in answer.get("substitute_options") or []],
              (answer.get("alternative") or {}).get("lines")]
    part = answer.get("partial_fill") or {}
    groups += [(part.get("now") or {}).get("lines"), *[p.get("lines") for p in part.get("rest") or []]]
    ids |= {ln.get("product_id") for group in groups for ln in group or []}
    return {pid for pid in ids if pid}


def name_proposal(answer: dict, found: dict[str, dict]) -> dict:
    """Add the name fields to every line kind and each excluded entry, and start the
    mandate reasons that open with a bare product code with the name (code in brackets)."""
    out = {**answer, "lines": named_lines(answer.get("lines"), found),
           "excluded": named_lines(answer.get("excluded"), found)}
    out["blocks"] = [{**b, "lines": named_lines(b.get("lines"), found)} for b in answer.get("blocks") or []]
    out["substitute_options"] = [{**o, "lines": named_lines(o.get("lines"), found)}
                                 for o in answer.get("substitute_options") or []]
    if answer.get("alternative"):
        out["alternative"] = {**answer["alternative"], "lines": named_lines(answer["alternative"].get("lines"), found)}
    part = answer.get("partial_fill")
    if part:
        def side(p):
            return {**p, "lines": named_lines(p.get("lines"), found)}
        out["partial_fill"] = {**part, **({"now": side(part["now"])} if part.get("now") else {}),
                               "rest": [side(p) for p in part.get("rest") or []]}
    mandate = answer.get("mandate")
    if mandate and mandate.get("reasons"):
        out["mandate"] = {**mandate, "reasons": [named_reason(r, found) for r in mandate["reasons"]]}
    return out


_LEAD = re.compile(r"^([^\s:]+): ")


def named_reason(reason, found: dict[str, dict]):
    """"463203: confirmed in stock, but ..." becomes "Arla milk 1 L (463203): confirmed in
    stock, but ..." when the product's name is known; any other sentence stays as it is."""
    if not isinstance(reason, str):
        return reason
    match = _LEAD.match(reason)
    name = match and (found.get(match.group(1)) or {}).get("product_name")
    if not name:
        return reason
    return f"{name} ({match.group(1)}): {reason[match.end():]}"
