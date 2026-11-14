"""Brand logos found with Context.dev (docs/contract.md, "Product pictures").

One row per catalog brand in `brand_logos`; `_id` is the brand name as the product row
has it. A row is written once, when Context.dev was asked (or the name cannot be asked),
and read by the logos route. Mongo access stays in store.
"""
from __future__ import annotations

from datetime import datetime

STATUSES = ('found', 'none')
BACKGROUNDS = ('light', 'dark', 'own')


def get_many(db, names) -> dict[str, dict]:
    """The stored rows for these brand names, by name. A name without a row is left out."""
    names = list(dict.fromkeys(names))
    if not names:
        return {}
    return {row['_id']: row for row in db.brand_logos.find({'_id': {'$in': names}})}


def put(db, brand: str, *, status: str, checked_at: datetime, logo_url: str | None = None,
        background: str | None = None, domain: str | None = None) -> None:
    """Keep what Context.dev said about one brand. A row that is already there is kept:
    each brand is asked once."""
    if status not in STATUSES:
        raise ValueError(f'status must be one of {STATUSES}')
    if status == 'found' and not (isinstance(logo_url, str) and logo_url.startswith('https://')
                                  and background in BACKGROUNDS):
        raise ValueError('a found logo needs an https URL and a background')
    row = {'status': status, 'checked_at': checked_at,
           'logo_url': logo_url if status == 'found' else None,
           'background': background if status == 'found' else None,
           'domain': domain if status == 'found' else None}
    db.brand_logos.update_one({'_id': brand}, {'$setOnInsert': row}, upsert=True)


def unchecked_brands(db, limit: int) -> list[str]:
    """Catalog brands that have no row yet, the brands with the most products first
    (a tie by name), at most `limit`."""
    if limit <= 0:
        return []
    done = {row['_id'] for row in db.brand_logos.find({}, {'_id': 1})}
    counts = db.products.aggregate([
        {'$match': {'source': 'valio', 'brand': {'$type': 'string', '$ne': ''}}},
        {'$group': {'_id': '$brand', 'n': {'$sum': 1}}},
    ])
    ranked = sorted(((row['n'], row['_id']) for row in counts if row['_id'] not in done),
                    key=lambda pair: (-pair[0], pair[1]))
    return [name for _, name in ranked[:limit]]
