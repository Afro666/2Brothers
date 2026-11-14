"""Allergen reason codes from a product row (S02, S04). A missing value is never safe."""

from __future__ import annotations


def allergen_codes(row: dict) -> tuple[str, ...]:
    """`ALLERGEN_DATA_MISSING` unless the row has allergen data or declares none present.

    A row without the field at all is unknown too: unknown is never "allergen-free".
    """
    if row.get("allergen_data_known") or row.get("no_declarable_allergens"):
        return ()
    return ("ALLERGEN_DATA_MISSING",)


def allergen_rule_hits(row: dict, excluded: tuple[str, ...]) -> tuple[str, ...]:
    """The kitchen's excluded GS1 codes this product lists as CONTAINS, MAY_CONTAIN or
    UNDECLARED (S03). Unknown allergen data gives no hit here: it stays on the line as
    ALLERGEN_DATA_MISSING, so a person checks the pack (S04)."""
    allergens = row.get("allergens") if isinstance(row, dict) else None
    if not isinstance(allergens, dict) or not excluded:
        return ()
    found = {code for level in ("contains", "may_contain", "undeclared")
             for code in (allergens.get(level) or []) if isinstance(code, str)}
    return tuple(sorted(found & set(excluded)))
