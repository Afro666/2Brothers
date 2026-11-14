"""Pinned manufacturer-page evidence; never a substitute for catalog safety data."""
from datetime import datetime, timezone
import json
from pathlib import Path

from monitor.recalls import ContextDev

SOURCE = 'https://www.lofbergs.fi/kahvimme/suodatinkahvit/crescendo'
FIXTURE = Path(__file__).parent / 'fixtures/crescendo.json'
SCHEMA = {'type': 'object', 'required': ['name', 'brand', 'pack', 'origin', 'allergens'],
    'properties': {key: {'type': ['string', 'null']} for key in ('name', 'brand', 'pack', 'origin', 'allergens')}}


def validate(row):
    if not isinstance(row, dict) or row.get('source_url') != SOURCE or row.get('product_id') != '475842':
        raise ValueError('Unsupported manufacturer evidence')
    if row.get('name', '').casefold() != 'crescendo' or row.get('brand', '').casefold() != 'löfbergs':
        raise ValueError('Manufacturer product identity did not match')
    for key in ('pack', 'origin', 'allergens'):
        if row.get(key) is not None and (not isinstance(row[key], str) or len(row[key]) > 500):
            raise ValueError('Invalid product evidence')
    if not isinstance(row.get('checked_at'), str):
        raise ValueError('Undated product evidence')
    return row


def evidence(*, live=False, client=None):
    if not live:
        return validate(json.loads(FIXTURE.read_text(encoding='utf-8')))
    facts = (client or ContextDev()).scrape_json(SOURCE, SCHEMA)
    # The pinned official page and exact identity prevent accidental joins.
    return validate({**facts, 'product_id': '475842', 'source_url': SOURCE,
        'checked_at': datetime.now(timezone.utc).isoformat(), 'via': 'Context.dev web/scrape structured JSON'})


def attach(gateway, kitchen_id, proposal, *, live=False, client=None):
    from store.evidence import save_product_evidence
    ids = {line['product_id'] for line in proposal['lines']}
    if '475842' not in ids:
        return []
    row = evidence(live=live, client=client)
    if save_product_evidence(gateway.db, kitchen_id, proposal['proposal_id'], [row]):
        gateway._audit(kitchen_id, 'replacement_enriched', 'recall-monitor',
            proposal_id=proposal['proposal_id'], source_url=row['source_url'], checked_at=row['checked_at'],
            product_id=row['product_id'], via=row['via'])
    return [row]
