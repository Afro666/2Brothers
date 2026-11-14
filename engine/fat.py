"""Fat level of a product, and when a plan mixes fat levels (S01, SUBSTITUTE_FAT_LEVEL).

Pure: the caller passes the supplier's product record. A missing value is unknown, never 0.
"""

from __future__ import annotations

from decimal import Decimal

FAT_TOLERANCE = Decimal("0.5")      # g per 100 g: a fat-free milk (0) and a 3 % milk differ


def fat_per_100g(raw: dict | None) -> Decimal | None:
    """Total fat in g per 100 g from the record's nutritional content (`FAT`), or None."""
    rows = ((raw or {}).get("synkkaData") or {}).get("nutritionalContent") or []
    for row in rows:
        if (isinstance(row, dict) and row.get("id") == "FAT" and row.get("unit") == "GRM"
                and row.get("basisQuantity") == 100.0 and row.get("value") is not None):
            return Decimal(str(row["value"]))
    return None


def fat_levels_differ(levels: list[Decimal | None]) -> bool:
    """True when two known fat levels in one plan are more than FAT_TOLERANCE apart.
    Unknown levels are not compared: they say nothing either way."""
    known = [v for v in levels if v is not None]
    return len(known) > 1 and max(known) - min(known) > FAT_TOLERANCE
