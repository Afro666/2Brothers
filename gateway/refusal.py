"""When the kitchen's allergen rule removes what the person asked for (#974).

A kitchen that excludes peanuts asks for "15 kg peanut butter". The allergen rule takes
every peanut butter out, the search still finds plain butter (it shares a word), and the
proposal was plain butter: another kind of product, with no word about it.

This module looks at the catalog hits for the person's own product words BEFORE the
allergen rule is applied, and answers one question: are the best matches all refused by
the rule? If so the request is refused and the answer names the allergen. It only reads;
the engine and `Gateway._allergen_refusals` still decide every line.

The rule:
1. The best matches are the hits whose names hold the most of the request's words
   ("peanut butter": both words; plain butter holds one and is not a best match).
2. A best match with known allergen data and no excluded allergen: the request goes on,
   as before. So does a request with no declared hit at all (missing data alone never
   refuses a request), and one where the declared hits are less than half of the best
   matches.
3. Otherwise every best match is refused by the rule or has no allergen data (unknown
   is never safe): the request is refused.
"""

from __future__ import annotations

import re

from engine import allergen_rule_hits
from store.search import ALLERGENS

MAX_IDS = 20      # refused products listed on the proposal
_LABEL = {"nuts": "tree nuts"}
# GS1 code -> the name a person reads; the first name in the table wins (UW: gluten).
_NAME = {code: _LABEL.get(name, name) for name, codes in reversed(list(ALLERGENS.items())) for code in codes}
_WORD = re.compile(r"[^\W\d_]+")


def _tokens(row: dict) -> set[str]:
    names = row.get("names") if isinstance(row.get("names"), dict) else {}
    text = " ".join(str(value) for value in [*names.values(), row.get("brand") or ""])
    return set(_WORD.findall(text.lower()))


def _holds(tokens: set[str], word: str) -> bool:
    """The word, or a longer form of it ("peanut" in "peanuts", "maapähkinävoi" in "-voita")."""
    return word in tokens or (len(word) >= 4 and any(
        len(token) >= 4 and (token.startswith(word) or word.startswith(token)) for token in tokens))


def _list(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def excluded_request(query: str, rows: list[dict], rule) -> dict | None:
    """`{"code", "allergens", "product_ids", "message"}` when the kitchen's rule removes
    the products that best match `query`, else None.

    `rows`: catalog search hits for `query` with no allergen filter, best first.
    `rule`: the kitchen's excluded GS1 codes, groups expanded (store/allergen_groups.py).
    """
    words = list(dict.fromkeys(w for w in _WORD.findall((query or "").lower()) if len(w) > 1))
    if not words or not rule or not rows:
        return None
    rule = tuple(rule)
    scored = [(sum(_holds(tokens, word) for word in words), row)
              for row, tokens in ((row, _tokens(row)) for row in rows)]
    most = max(score for score, _ in scored)
    if most == 0:
        return None
    best = [row for score, row in scored if score == most]
    hits = [(row, allergen_rule_hits(row, rule)) for row in best]
    declared = [(row, found) for row, found in hits if found]
    if any(not found and row.get("allergen_data_known") is True for row, found in hits):
        return None                      # a best match the kitchen can have: go on as before
    if not declared or 2 * len(declared) < len(best):
        return None                      # missing data alone is not this rule's refusal
    common = set(declared[0][1]).intersection(*(found for _, found in declared[1:]))
    codes = common or {code for _, found in declared for code in found}
    allergens = sorted({_NAME.get(code, code) for code in codes})
    unknown = len(best) - len(declared)
    message = (f'This kitchen excludes {_list(allergens)}, so "{" ".join(words)}" cannot be ordered: '
               f"the products that match it contain or may contain {_list(allergens)}"
               + (", or have no allergen data" if unknown else "")
               + ". No other kind of product is proposed in its place.")
    return {"code": "ALLERGEN_RULE", "allergens": allergens,
            "product_ids": [row["product_id"] for row, _ in declared][:MAX_IDS], "message": message}
