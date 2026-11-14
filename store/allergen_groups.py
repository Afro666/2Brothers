"""A kitchen's excluded allergens -> the GS1 codes that refuse a product (#672).

One rule for every reader of `kitchen_settings.excluded_allergens` (the gateway and
the Buyer agent), built on the code tables in store/search.py:

- A group code (`AN` tree nuts, `AW` gluten cereals) or its name means the whole
  group: the group code and every member code.
- A member code (`SA` almond) also excludes its group code: a product that declares
  only "tree nuts" does not say which nut, and unknown is never safe. It does not
  exclude the other members.
- Oats (`GO`) are outside the gluten group in both directions (docs/decisions.md,
  2026-11-13 23:32: gluten-free oats exist).
- A misspelt allergen is an error (`ValueError`), never ignored.
"""

from __future__ import annotations

from store.search import ALLERGENS, allergen_codes

# Group code -> its member codes: every allergen in the table with more than one code.
GROUPS = {codes[0]: tuple(codes[1:]) for codes in ALLERGENS.values() if len(codes) > 1}
_GROUP_OF = {member: group for group, members in GROUPS.items() for member in members}


def excluded_allergen_codes(values) -> list[str]:
    """Names or GS1 codes a kitchen excludes -> every GS1 code that refuses a product."""
    asked = allergen_codes(values)
    codes = set(asked)
    for code in asked:  # one pass over what was asked: a member never pulls in its siblings
        codes.update(GROUPS.get(code, ()))
        if code in _GROUP_OF:
            codes.add(_GROUP_OF[code])
    return sorted(codes)
