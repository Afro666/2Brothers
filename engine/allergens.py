"""Allergen reason codes from a product row (S02, S04). A missing value is never safe."""

from __future__ import annotations


def allergen_codes(row: dict) -> tuple[str, ...]:
    """`ALLERGEN_DATA_MISSING` unless the row has allergen data or declares none present.

    A row without the field at all is unknown too: unknown is never "allergen-free".
    """
    if row.get("allergen_data_known") or row.get("no_declarable_allergens"):
        return ()
    return ("ALLERGEN_DATA_MISSING",)
