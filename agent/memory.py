"""Kitchen memory for Nemotron's prompts (#1308): compact facts and checked claims.

The model may use these facts as written, but it may never turn one into a new number.
"""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import json

from gateway.claim_check import check_sentence, numbers_in

KIND_ORDER = ("CORRECTION_RATIO", "DECLINED_PRODUCT", "SUPPLIER_LATE", "SUPPLIER_SHORT")

_EXTRA_KEYS = {
    "CORRECTION_RATIO": ("from_qty", "to_qty"),
    "DECLINED_PRODUCT": (),
    "SUPPLIER_LATE": ("on_time_rate", "mean_days_late", "deliveries"),
    "SUPPLIER_SHORT": ("fill_rate",),
}
_BASE_KEYS = {"id", "kind", "active", "product_id", "supplier_id", "name", "value", "evidence"}

TITLE = "What this kitchen taught the tool (facts, computed by code):"
RULES = (
    "Use these facts only as given. Never compute a new number from them. If a fact does not "
    "fit this request, mark it not_applicable with a short reason. Each sentence names the "
    "fact id it uses."
)


def _decimal(number) -> Decimal | None:
    """A JSON number as Decimal, ignoring booleans and values that are not finite."""
    if isinstance(number, bool) or not isinstance(number, (int, float, Decimal)):
        return None
    try:
        value = Decimal(str(number)) if isinstance(number, float) else Decimal(number)
    except (InvalidOperation, ValueError):
        return None
    return value if value.is_finite() else None


def _extra_items(fact):
    """The numeric kind extras, in their named order and then any new ones."""
    keys = list(_EXTRA_KEYS.get(fact.get("kind"), ()))
    keys.extend(key for key in fact
                if key not in _BASE_KEYS and key not in keys and _decimal(fact[key]) is not None)
    return [(key, fact[key]) for key in keys if _decimal(fact.get(key)) is not None]


def _entry(fact):
    entry = {"id": fact.get("id"), "kind": fact.get("kind")}
    if fact.get("product_id") is not None:
        entry["product_id"] = fact["product_id"]
    if fact.get("supplier_id") is not None:
        entry["supplier_id"] = fact["supplier_id"]
    entry["name"] = fact.get("name")
    entry["value"] = fact.get("value")
    entry.update(_extra_items(fact))
    entry["rows"] = fact.get("evidence", {}).get("rows")
    entry["last"] = fact.get("evidence", {}).get("last")
    return entry


def kitchen_memory(facts, product_ids, supplier_ids, *, max_lines=12, max_chars=2400):
    """The active facts for this kitchen, ordered and capped as the prompt can carry them."""
    products, suppliers = set(product_ids), set(supplier_ids)
    relevant = [
        fact for fact in facts
        if fact.get("active")
        and fact.get("kind") in KIND_ORDER
        and ((fact.get("product_id") is not None and fact["product_id"] in products)
             or (fact.get("supplier_id") is not None and fact["supplier_id"] in suppliers))
    ]
    relevant.sort(key=lambda fact: (KIND_ORDER.index(fact["kind"]),
                                    -int(fact.get("evidence", {}).get("rows", 0)),
                                    str(fact.get("id", ""))))

    entries, limit = [], max(0, max_lines)
    for fact in relevant:
        if len(entries) >= limit:
            break
        candidate = entries + [_entry(fact)]
        if len(json.dumps(candidate, ensure_ascii=False)) > max_chars:
            break
        entries = candidate
    return entries


def prompt_block(entries):
    """An English memory section, or nothing at all when there is no memory."""
    if not entries:
        return ""
    return f"{TITLE}\n{RULES}\n{json.dumps(entries, ensure_ascii=False)}"


def _is_rate(fact, key):
    return key.endswith("_rate") or key == "correction_ratio" or (
        key == "value" and fact.get("kind") == "CORRECTION_RATIO")


def allowed_numbers(fact):
    """Every number the fact states, plus whole-percent spellings of its rates and ratios."""
    numbers = []
    value = _decimal(fact.get("value"))
    if value is not None:
        numbers.append((value, "value"))
    numbers.extend((_decimal(raw), key) for key, raw in _extra_items(fact))
    rows = _decimal(fact.get("evidence", {}).get("rows"))
    if rows is not None:
        numbers.append((rows, "rows"))

    allowed = set()
    for number, key in numbers:
        if number is None:
            continue
        allowed.add(number.normalize())
        if _is_rate(fact, key) and Decimal(0) <= number <= Decimal("1.5"):
            percent = (number * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP)
            allowed.add(percent.normalize())
    return allowed


def check_learned_sentences(sentences, facts, lang):
    """Keep the checked learned sentences, dropping a bad one without its neighbours."""
    by_id = {fact.get("id"): fact for fact in facts}
    kept, dropped = [], []
    for sentence in sentences:
        fact_id = sentence.get("fact_id")
        fact = by_id.get(fact_id)
        if fact is None or not fact.get("active"):
            dropped.append({"fact_id": fact_id, "reason": "FACT_UNKNOWN"})
            continue
        reason = check_sentence(sentence.get("text", ""), sentence.get("numbers", []),
                                allowed_numbers(fact), lang, strip=[fact.get("name")])
        if reason:
            dropped.append({"fact_id": fact_id, "reason": reason})
        else:
            kept.append(sentence)
    return kept, dropped


def check_not_applicable(marks, facts, lang):
    """Keep only short not-applicable reasons whose numbers belong to their own fact."""
    by_id = {fact.get("id"): fact for fact in facts}
    kept = []
    for mark in marks:
        fact_id, text = mark.get("fact_id"), mark.get("reason")
        fact = by_id.get(fact_id)
        if fact is None or not fact.get("active") or not isinstance(text, str) or len(text) > 200:
            continue
        declared = mark.get("numbers") or numbers_in(text, lang)
        if check_sentence(text, declared, allowed_numbers(fact), lang,
                          strip=[fact.get("name")]) is None:
            kept.append({"fact_id": fact_id, "reason": text})
    return kept
