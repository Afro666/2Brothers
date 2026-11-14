"""Which catalog hits the fallback parser hands to the engine (#276).

A text search for "lactose free milk" ranks chocolate, bread mix and cake bases above the
milk: they share the words. None of them can be measured in litres, so a request for
1,000 L could not be covered and the proposal came back empty. This module keeps the hits
that can answer the request. It only chooses which products to price; the engine still
sizes every line, and unknown data is never treated as a match.
"""

from __future__ import annotations

from collections import Counter

SEARCH_LIMIT = 60   # how many hits to look at
CANDIDATES = 20     # how many go on to price and availability
_FAMILY = {"L": "volume", "DL": "volume", "CL": "volume", "ML": "volume",
           "KG": "weight", "G": "weight"}


def _family(unit) -> str | None:
    return _FAMILY.get(str(unit or "").strip().upper())


def _content_family(row: dict) -> str | None:
    """The kind of measure of the product's net content, or None when it is not known."""
    content = row.get("net_content")
    return _family(content.get("unit")) if isinstance(content, dict) else None


def pick_candidates(rows: list[dict], unit: str, cap: int = CANDIDATES) -> list[str]:
    """Product ids to price, best first, at most `cap`.

    1. A request in litres or kilograms drops hits whose net content is known to be the
       other kind (a 150 g chocolate bar for a request in litres).
    2. Hits of the most common category among the best matching ones come first: the
       request names one kind of product.
    3. A hit with unknown net content is kept, after the known ones: unknown is not a
       match, and it is not a mismatch either. The engine decides when it has the price.

    A request in pieces or packs (no measure family) keeps the search order.
    """
    want = _family(unit)
    if want is None:
        return [row["product_id"] for row in rows][:cap]
    known = [row for row in rows if _content_family(row) == want]
    unknown = [row for row in rows if _content_family(row) is None]
    categories = Counter(row.get("category") for row in known[:20] if row.get("category"))
    if categories:
        top = categories.most_common(1)[0][0]
        known = ([row for row in known if row.get("category") == top]
                 + [row for row in known if row.get("category") != top])
    return [row["product_id"] for row in known + unknown][:cap]
