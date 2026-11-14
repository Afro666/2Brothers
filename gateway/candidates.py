"""Which catalog hits the fallback parser hands to the engine (#276).

A text search for "lactose free milk" ranks chocolate, bread mix and cake bases above the
milk: they share the words. None of them can be measured in litres, so a request for
1,000 L could not be covered and the proposal came back empty. This module keeps the hits
that can answer the request. It only chooses which products to price; the engine still
sizes every line, and unknown data is never treated as a match.
"""

from __future__ import annotations

from collections import Counter

SEARCH_LIMIT = 50   # how many hits to look at: the most store.search allows (MAX_LIMIT)
CANDIDATES = 20     # how many go on to price and availability
_FAMILY = {"L": "volume", "DL": "volume", "CL": "volume", "ML": "volume",
           "KG": "weight", "G": "weight"}


def _family(unit) -> str | None:
    return _FAMILY.get(str(unit or "").strip().upper())


def _content_family(row: dict) -> str | None:
    """The kind of measure of the product's net content, or None when it is not known."""
    content = row.get("net_content")
    return _family(content.get("unit")) if isinstance(content, dict) else None


def of_kind(rows: list[dict], categories, unit: str = "") -> list[dict]:
    """The search hits that are the kind of product the request names (gateway/kind.py).

    `categories`: the catalog categories of that kind; empty means the catalog shows none,
    and the rows come back as they are.

    1. When some hits hold every search word in one name (the search marks them with a
       score of `ALL_WORDS_BOOST` or more), the hits that hold only some of the words are
       dropped: "coconut milk" must not be answered with plain milk.
    2. Hits of the kind's categories are kept, best score first, and the others are
       dropped: a cheese sauce is not cheese, condensed milk is not milk, a cleaner is
       not cream.
    3. Unless no hit is of the kind, or none of them is sold in the asked measure (`unit`
       L or KG): then step 2 drops nothing, the request may mean something the rule
       does not see.
    """
    wanted = {str(c) for c in categories}
    if not wanted:
        return rows
    from store.search import ALL_WORDS_BOOST
    scored = all(isinstance(r.get("score"), (int, float)) for r in rows)
    if scored and any(r["score"] >= ALL_WORDS_BOOST for r in rows):
        rows = [r for r in rows if r["score"] >= ALL_WORDS_BOOST]
    kind = [r for r in rows if str(r.get("category")) in wanted]
    family = _family(unit)
    if not kind or (family and not any(_content_family(r) == family for r in kind)):
        return rows
    if scored:
        kind.sort(key=lambda r: -r["score"])       # stable: equal scores keep the search order
    return kind


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
