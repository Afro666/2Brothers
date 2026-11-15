from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D

import mongomock
import pytest

from agent.single_pick import checked_reason, covers_need_alone, coverage_rows, minimal_indices
from engine.offers import Offer
from engine.packs import PackInfo
from engine.selection_facts import selection_facts
from store.buyer_context import pick_facts

NOW = datetime(2026, 11, 14, 12, tzinfo=timezone.utc)


def offer(pid='milk', *, size='1', price='1.4', stock='698'):
    return Offer(pid, 'Milk', PackInfo('KI', 'L', D(size), D(1), False), D(price),
                 None if stock is None else D(stock), False, date(2026, 11, 16))


def test_quote_facts_compare_cases_and_keep_unknown_stock_unknown():
    facts = selection_facts([offer(), offer('box', size='10', price='12', stock=None)], D(1000), 'L')
    assert facts['milk']['stock_quantity_base'] == '698'
    assert facts['milk']['stock_covers'] == '0.698'
    assert facts['box']['stock_state'] == 'unknown'
    assert facts['box']['stock_covers'] is None and facts['box']['stock_quantity_base'] is None
    assert facts['box']['price_per_base_unit'] == '1.2'
    assert facts['box']['packs_needed'] == '100'
    assert facts['milk']['packs_needed'] == '1000'
    assert selection_facts([offer(stock='0')], D(1000), 'L')['milk']['stock_state'] == 'none'
    with pytest.raises(ValueError):
        selection_facts([offer()], D(1000), 'KG')


def test_private_facts_are_bound_to_kitchen_offer_expiry_and_recent_real_orders():
    db = mongomock.MongoClient(tz_aware=True).db
    db.offers.insert_one({'_id': 'o', 'kitchen_id': 'a',
        'valid_until': (NOW + timedelta(minutes=5)).isoformat(),
        'selection_facts': selection_facts([offer()], D(1000), 'L')})
    db.products.insert_one({'_id': 'milk', 'kitchen_id': 'b', 'lactose_free': True})
    common = {'outcome': 'CONFIRMED', 'created_at': NOW - timedelta(days=1),
              'lines': [{'product_id': 'milk'}, {'product_id': 'milk'}]}
    for extra in ({'kitchen_id': 'a'}, {'kitchen_id': 'b'},
                  {'kitchen_id': 'a', 'placed_by': 'demo-seed'},
                  {'kitchen_id': 'a', 'created_at': NOW - timedelta(days=57)}):
        db.orders.insert_one({**common, **extra})
    result = pick_facts(db, 'a', 'o', ['milk'], NOW)['milk']
    assert result['ordered_before'] == 1
    assert result['diet_claims']['lactose_free'] is None
    assert pick_facts(db, 'b', 'o', ['milk'], NOW) == {}
    assert pick_facts(db, 'a', 'o', ['milk'], NOW + timedelta(minutes=5)) == {}


def test_numeric_reason_is_bound_to_its_own_product_evidence():
    row = {'name': 'Milk 1 L', 'selection': {'stock_quantity_base': '698', 'stock_covers': '0.698'}}
    checked_reason('Milk 1 L has 698 available.', row)
    with pytest.raises(ValueError):
        checked_reason('Has 999 available.', row)
    checked_reason('A 10 L pack can meet the requested 51 L.',
                   {'name': 'Milk', 'selection': {'base_per_sales_unit': '10'}}, {'quantity': '51'})


def test_single_preference_is_kept_only_with_proven_full_delivery_coverage():
    need = {'unit': 'L', 'needed_by': '2026-11-16'}
    fact = selection_facts([offer(stock='100')], D(51), 'L')['milk']
    rows = [{'selection': fact}, {'selection': None}]
    assert minimal_indices([0, 1], rows, need) == [0]
    for change in ({'stock_state': 'unknown'}, {'stock_quantity_base': '50'},
                   {'cutoff_passed': True}, {'first_arrival': '2026-11-17'}, {'base_unit': 'KG'}):
        assert minimal_indices([0, 1], [{'selection': {**fact, **change}}, rows[1]], need) == [0, 1]


@pytest.mark.parametrize('change', [
    {'stock_state': 'unknown'}, {'stock_state': 'none'}, {'stock_quantity_base': None},
    {'stock_quantity_base': 'Infinity'}, {'stock_quantity_base': 'NaN'},
    {'stock_quantity_base': True}, {'stock_quantity_base': '-1'},
    {'packs_needed': '0'}, {'packs_needed': '-1'}, {'packs_needed': 'Infinity'},
    {'base_per_sales_unit': '0'}, {'base_per_sales_unit': 'NaN'},
    {'cutoff_passed': True}, {'cutoff_passed': None}, {'cutoff_passed': 0}, {'cutoff_passed': 'false'},
    {'packs_needed': '1e999999999'}, {'first_arrival': None},
    {'first_arrival': 'not-a-date'}, {'first_arrival': '2026-11-17'}, {'base_unit': 'KG'},
])
def test_coverage_hint_never_proves_full_coverage_from_ineligible_or_malformed_evidence(change):
    need = {'unit': 'L', 'needed_by': '2026-11-16'}
    fact = selection_facts([offer(size='10', stock='6')], D(53), 'L')['milk']
    row = {'selection': {**fact, **change}, 'covers_need_alone': True}
    assert covers_need_alone(row, need) is False
    assert minimal_indices([0, 1], [row, {'selection': None}], need) == [0, 1]


def test_coverage_hint_uses_rounded_packs_without_mutating_evidence_or_overriding_rank():
    need = {'unit': 'L', 'needed_by': '2026-11-16'}
    fact = selection_facts([offer(size='10', stock='6')], D(53), 'L')['milk']
    rows = [{'selection': fact, 'alias': False, 'kitchen_declined': True}, {'selection': None, 'alias': True}]
    enriched = coverage_rows(rows, need)
    assert enriched[0]['covers_need_alone'] is True and enriched[1]['covers_need_alone'] is False
    assert 'covers_need_alone' not in rows[0] and enriched[0]['selection'] is fact
    # 53 L on the shelf is insufficient: buying six ten-litre packs needs 60 L.
    assert covers_need_alone({'selection': {**fact, 'stock_quantity_base': '53'}}, need) is False
    # The hint cannot make a later product override the model's higher-priority first preference.
    assert minimal_indices([1, 0], enriched, need) == [1, 0]
    # Pruning recomputes proof, ignoring a forged/precomputed root flag.
    enriched[0]['covers_need_alone'] = False
    assert minimal_indices([0, 1], enriched, need) == [0]


def test_fractional_weighted_sales_units_are_valid_and_missing_evidence_is_not():
    need = {'unit': 'KG', 'needed_by': '2026-11-16'}
    fact = {'stock_state': 'confirmed', 'cutoff_passed': False, 'first_arrival': '2026-11-16',
            'base_unit': 'KG', 'stock_quantity_base': '3.5', 'packs_needed': '3.5',
            'base_per_sales_unit': '1'}
    assert covers_need_alone({'selection': fact}, need) is True
    assert covers_need_alone({'selection': {**fact, 'stock_quantity_base': '3.49'}}, need) is False
    for malformed in (None, [], 'not-facts', 1):
        assert covers_need_alone({'selection': malformed}, need) is False
