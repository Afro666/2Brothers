"""Recorded coffee notice changes a real engine proposal, using synthetic prices."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path

import mongomock
import pytest
from gateway.service import Gateway, GatewayError
from monitor.proposals import apply_notices
from monitor.recalls import audit, scan
from store.audit import list_events, verify_chain

NOW = datetime(2026, 11, 14, tzinfo=timezone.utc)
NOTICES = json.loads((Path(__file__).parents[1] / 'fixtures/ruokavirasto.json').read_text(encoding='utf-8'))['notices']


class Prices:
    def price(self, ids, day):
        return {'products': [{'productId': pid, 'catalogPrice': {'value': '10'},
            'comparisonPrice': {'value': '10'}, 'comparisonUnit': 'KG', 'tax': {'taxRate': '13.5'}} for pid in ids]}

    def availability(self, ids, day):
        return {'products': [{'productId': pid, 'cutoff_passed': False,
            'scheduleLines': [{'availableAmount': '50', 'availableDate': day}]} for pid in ids]}


def setup():
    db = mongomock.MongoClient(tz_aware=True).db
    for pid, brand, name in [('461332', 'Kulta Katriina', 'Kulta Katriina Perinteinen kahvi'),
                             ('475842', 'Löfbergs', 'Löfbergs coffee')]:
        db.products.insert_one({'_id': pid, 'brand': brand, 'names': {'en': name, 'fi': name},
            'substitutions': ['475842'] if pid == '461332' else [],
            'allergen_data_known': True, 'allergens': {'contains': [], 'may_contain': [], 'undeclared': []},
            'raw': {'id': pid, 'salesUnit': 'ST', 'baseUnit': 'ST', 'allowedLotSize': 1,
                    'units': [{'unitId': 'ST', 'sizeInBaseUnits': 1}]}})
    db.kitchen_settings.insert_one({'_id': 'hotel', 'excluded_allergens': []})
    gw = Gateway(db, Prices(), now=lambda: NOW)
    p = gw.create_proposal('hotel', {'product_ids': ['461332'], 'quantity': '5', 'unit': 'KG',
        'requested_date': '2026-11-16', 'text': 'hotel coffee', 'idempotency_key': 'coffee'}, 'test')
    return db, gw, p


def test_coffee_hold_replans_different_brand_without_ordering():
    db, gw, p = setup()
    apply_notices(gw, 'hotel', NOTICES)
    original = gw.get_proposal('hotel', p['proposal_id'])
    assert original['status'] == 'BLOCKED_BY_RECALL'
    assert original['lines'][0]['recall_status'] == 'BLOCKED_BY_RECALL'
    assert original['recall_alerts'][0]['recall']['url'].startswith('https://www.ruokavirasto.fi/')
    assert original['recall_alerts'][0]['recall']['lot']
    replacement = gw.get_proposal('hotel', original['replacement_proposal_id'])
    assert replacement['status'] == 'READY'
    assert [(l['product_id'], l['quantity']) for l in replacement['lines']] == [('475842', '5')]
    assert db.orders.count_documents({}) == 0
    with pytest.raises(GatewayError, match='recall'):
        gw.approve('hotel', p['proposal_id'], {'expected_total': p['expected_total'], 'idempotency_key': 'approve'}, human='chef')
    apply_notices(gw, 'hotel', NOTICES)
    assert db.proposals.count_documents({}) == 2
    kinds = [e['event'].get('kind') for e in list_events(db, kitchen_id='hotel')]
    assert 'recall_proposal_blocked' in kinds and 'recall_replacement_proposed' in kinds
    assert verify_chain(db)['ok']


def test_unknown_policy_or_unsafe_substitute_keeps_hold():
    db, gw, p = setup()
    db.kitchen_settings.delete_many({})
    apply_notices(gw, 'hotel', NOTICES)
    held = gw.get_proposal('hotel', p['proposal_id'])
    assert held['status'] == 'BLOCKED_BY_RECALL'
    assert held['recall_replan_error'] == 'KITCHEN_POLICY_UNKNOWN'
    assert not held['replacement_proposal_id']
    assert db.orders.count_documents({}) == 0


def test_recall_during_price_recheck_prevents_commit():
    db, gw, p = setup()
    quote = gw._quote
    fired = False
    def racing(kitchen, request):
        nonlocal fired
        fresh = quote(kitchen, request)
        if not fired:
            fired = True
            apply_notices(gw, 'hotel', NOTICES)
        return fresh
    gw._quote = racing
    with pytest.raises(GatewayError) as error:
        gw.approve('hotel', p['proposal_id'], {'expected_total': p['expected_total'], 'idempotency_key': 'approve'}, human='chef')
    assert error.value.code == 'BLOCKED_BY_RECALL'
    assert db.orders.count_documents({}) == 0


def test_audit_replay_ignores_changed_stock_and_replacement_ideas():
    db, _, _ = setup()
    kitchen = {'kitchen_id': 'hotel', 'products': [{'product_id': '461332', 'brand': 'Kulta Katriina',
        'names': {'fi': 'Kulta Katriina Perinteinen kahvi'}}], 'proposal': ['461332']}
    alerts = scan(NOTICES, kitchen, NOW)
    audit(db, alerts, NOW)
    changed = deepcopy(alerts)
    changed[0]['where'] = ['in stock: 1 KG']
    changed[0]['replacement_proposal'] = [{'product_id': 'new'}]
    audit(db, changed, NOW)
    assert len(list_events(db, kitchen_id='hotel')) == 3  # proposal + summary + one notice
