"""Exact producer registration checks; never assert SKU certification."""
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
import json
from pathlib import Path
import unicodedata

from monitor.recalls import ContextDev

LABEL = 'GOODS_FROM_FINLAND_BLUE_SWAN'
SOURCE = 'https://ruokatieto.fi/yhdistys/jasenyys/'
FIXTURE = Path(__file__).parent / 'fixtures/hyvaa-suomesta-producers.json'
SCHEMA = {'type': 'object', 'required': ['complete', 'register_date', 'producers'], 'properties': {
    'complete': {'type': 'boolean', 'description': 'True only if the entire alphabetic producer list through its end is visible; false for partial or paginated results'},
    'register_date': {'type': ['string', 'null'], 'description': 'Explicit date of register in YYYY-MM-DD'},
    'producers': {'type': 'array', 'items': {'type': 'string'},
                  'description': 'Exact legal names of food producers, excluding association-only non-producer members'}}}


def normalized(name):
    return ' '.join(unicodedata.normalize('NFKC', name).casefold().split())


@lru_cache(maxsize=1)
def recording():
    return json.loads(FIXTURE.read_text(encoding='utf-8'))


def verify(product, label, *, register=None, now=None):
    now = now or datetime.now(timezone.utc)
    producer = product.get('producer') or product.get('vendor')
    row = {'product_id': product.get('product_id') or product.get('_id'), 'label': label,
           'producer': producer, 'label_verified': 'unknown', 'scope': 'producer',
           'source_url': SOURCE if label == LABEL else None, 'checked_at': None,
           'via': 'Context.dev web/scrape structured JSON', 'reason': 'Unsupported label register'}
    if label != LABEL:
        return row
    if not isinstance(producer, str) or not producer.strip():
        return {**row, 'reason': 'Legal producer is missing; brand names are not legal-entity matches'}
    try:
        register = recording() if register is None else register
        checked = datetime.fromisoformat(register['checked_at'].replace('Z', '+00:00'))
        issued = date.fromisoformat(register['register_date'])
        names = register['producers']
        if (register.get('source_url') != SOURCE or register.get('scope') != 'producer' or
            register.get('complete') is not True or not isinstance(names, list) or len(names) < 250 or
            any(not isinstance(name, str) or not name.strip() for name in names)):
            raise ValueError('Partial or invalid register')
        if (checked.tzinfo is None or checked > now or now - checked > timedelta(days=30) or
            issued > checked.date() or (now.date() - issued).days > 30):
            raise ValueError('Stale or invalid register dates')
        row['checked_at'] = register['checked_at']
        found = normalized(producer) in {normalized(name) for name in names}
        row.update(label_verified=True if found else 'not_found',
            reason='Exact producer name in recorded register; SKU certification is unverified' if found else
                   'Exact producer name not found in the complete recorded register; no claim about SKU certification')
    except (KeyError, TypeError, ValueError, OSError):
        row['reason'] = 'Register incomplete, unavailable or stale'
    return row


def checks(products, *, now=None):
    return [verify(product, label, now=now) for product in products for label in product.get('labels', [])]


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', help='Refresh the register using Context credits')
    parser.add_argument('--output', type=Path, default=FIXTURE)
    args = parser.parse_args()
    if args.live:
        data = ContextDev().scrape_json(SOURCE, SCHEMA)
        row = {**data, 'source_url': SOURCE, 'scope': 'producer',
               'checked_at': datetime.now(timezone.utc).isoformat(), 'via': 'Context.dev web/scrape structured JSON'}
        # Refuse to overwrite a usable recording with partial/invalid evidence.
        if verify({'product_id': 'probe', 'vendor': 'Arla Oy'}, LABEL, register=row)['label_verified'] == 'unknown':
            raise SystemExit('Register extraction incomplete; existing recording preserved')
        args.output.write_text(json.dumps(row, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print('Register recording refreshed')
    else:
        demo = [{'product_id': '462535', 'vendor': 'ARLA OY'},
                {'product_id': '462576', 'vendor': 'ARLA OY'},
                {'product_id': '462775', 'vendor': 'ARLA OY'},
                {'product_id': 'synthetic-negative-control', 'vendor': 'Synthetic Unregistered Demo Producer Oy'}]
        print(json.dumps([verify(p, LABEL) for p in demo], ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
