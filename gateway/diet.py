"""A diet word in a request is a hard rule on every product proposed for it (#1869).

Why. Live on 2026-11-15 the request "1,000 L lactose-free milk by Monday" had an option
with 132 L of "Arla Whole milk 1 L Suomesta low lactose Uht". "lactose free" was only a
pair of search words: the shortlist was narrowed by category, and a quote left out
recalled products, the kitchen's allergens and a wrong plant drink, never a product that
does not meet the diet the person asked. Low lactose is not lactose-free.

The rule.
- `asked(text)`: the diets a request text names, in English, Finnish and Swedish.
- `meets(row, diet)`: a product meets a diet only with proof. The proof is the catalog's
  own claim (`lactose_free`, `FREE_FROM_GLUTEN`, a free-from code) or the product name
  saying it ("laktoositon"). A declared allergen that contradicts it always wins.
- No proof is not a match: unknown data never passes, and no row never passes.

Used for the shortlist (`Gateway._of_kind`) and for every quote (`Gateway._plan_one`), so
it holds for the basket, the confirmed-stock option and the Buyer's substitute options,
on the Buyer path and on the plain-code path. It only ever removes a product.
"""

from __future__ import annotations

import re
from typing import NamedTuple


class Diet(NamedTuple):
    key: str
    label: str                     # as a person reads it: "lactose-free"
    words: re.Pattern              # the diet in a request text or a product name
    claim: str                     # the catalog's nutritional claim
    free_codes: frozenset[str]     # a free-from statement with one of these codes proves it
    codes: frozenset[str]          # a declared allergen with one of these codes refutes it


# The gluten cereals; oats (GO) are outside the group (store/allergen_groups.py).
_GLUTEN = frozenset({"AW", "UW", "NR", "GB", "GS", "GK"})

DIETS = (
    Diet("lactose_free", "lactose-free",
         re.compile(r"\blactose[\s-]*free\b|\bfree\s+(?:from|of)\s+lactose\b"
                    r"|\blaktoosit(?:on|to)\w*|\blaktosfri\w*"),
         "FREE_FROM_LACTOSE", frozenset({"ML"}), frozenset({"ML"})),
    Diet("gluten_free", "gluten-free",
         re.compile(r"\bgluten[\s-]*free\b|\bfree\s+(?:from|of)\s+gluten\b"
                    r"|\bgluteenit(?:on|to)\w*|\bglutenfri\w*"),
         "FREE_FROM_GLUTEN", frozenset({"AW"}), _GLUTEN),
)

# Who picked the product codes of a quote for the person's text: the plain-code reader,
# one need of a list, and the confirmed-stock options. A Buyer's offer is known by its
# `need_id`. A body with its own codes (a client, a person's change) is left as asked.
PICKED_FOR_TEXT = ("parser", "list_item", "confirmed_search", "confirmed_only")


def asked(text: str | None) -> tuple[Diet, ...]:
    """The diets the text names; empty when it names none ("low lactose" is none)."""
    low = (text or "")[:500].lower()
    return tuple(diet for diet in DIETS if diet.words.search(low))


def _codes(value) -> set[str]:
    return {v for v in value if isinstance(v, str)} if isinstance(value, (list, tuple, set)) else set()


def meets(row: dict | None, diet: Diet) -> bool:
    """True only when the product is proven to meet the diet."""
    if not isinstance(row, dict):
        return False
    allergens = row.get("allergens") if isinstance(row.get("allergens"), dict) else {}
    declared = _codes(allergens.get("contains")) | _codes(allergens.get("may_contain"))
    if declared & diet.codes:
        return False                                  # the riskier statement wins
    if row.get(diet.key) is True or diet.claim in _codes(row.get("claims")):
        return True
    if _codes(row.get("free_from")) & diet.free_codes:
        return True
    names = row.get("names") if isinstance(row.get("names"), dict) else {}
    return any(diet.words.search(str(name or "").lower()) for name in [*names.values(), row.get("name")])


def unmet(row: dict | None, diets) -> Diet | None:
    """The first of `diets` the product does not meet, or None when it meets them all."""
    return next((diet for diet in diets if not meets(row, diet)), None)


def keep(rows: list[dict], text: str | None) -> list[dict]:
    """The rows that meet every diet the text names; all of them when it names none."""
    diets = asked(text)
    return [row for row in rows if unmet(row, diets) is None] if diets else rows


def not_met(diet: Diet) -> str:
    """The reason a product is left out of a quote."""
    return f"not {diet.label} as asked: no other product is proposed in its place"


def none_found(diets) -> str:
    label = " and ".join(diet.label for diet in diets)
    return (f"The catalog has no {label} product that matches. A product that is not "
            f"{label} is not proposed in its place.")
