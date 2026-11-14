"""A supplier's price list from a photo (#1174): the model copies text, code reads it, and
anything uncertain is PLEASE_CHECK with an empty price. Never guessed, never saved."""
import asyncio
import base64
import json
from pathlib import Path

import httpx
import pytest
from jsonschema import ValidationError

from agent.price_list import MAX_ROWS, pack, price, read_rows, unit_of, vat
from agent.price_list_service import PriceListReader
from agent.receiving import RecordedModel
from agent.service import WorkerError, create_app

ROOT = Path(__file__).resolve().parents[2]
REPLY = json.loads((ROOT / 'agent' / 'fixtures' / 'price_list' / 'demo.reply.json').read_text(encoding='utf-8'))
PHOTO = (ROOT / 'demo' / 'price-list-photo.png').read_bytes()
EXISTING = [{'product_id': 'own-rye-loaf', 'name': 'Rye sourdough loaf 800 g', 'unit_price_eur': '4.20'},
            {'product_id': 'own-cinnamon-bun', 'name': 'Cinnamon bun', 'unit_price_eur': '2.10'}]


def row(**kw):
    return {'name': 'Seed rolls', 'price': '0,95 €', 'price_unit': 'kpl', 'pack': 'unknown', **kw}


def one(r, currency='EUR', vat_text='sis. alv 14 %', existing=()):
    return read_rows({'currency': currency, 'vat': vat_text, 'rows': [r]}, 'sup-bakery', existing)['rows'][0]


def test_the_recorded_demo_photo_reads_into_checked_drafts():
    out = read_rows({k: v for k, v in REPLY.items() if k != 'model'}, 'sup-bakery', EXISTING)
    assert out['currency'] == 'EUR' and out['vat'] == 'INCLUDED' and out['truncated'] is False
    by = {r['name']: r for r in out['rows']}
    rye = by['Rye sourdough loaf 800 g']
    assert rye['status'] == 'READ' and rye['draft']['unit'] == 'ST' and rye['draft']['unit_price_eur'] == '4.40'
    assert (rye['draft']['base_unit'], rye['draft']['pack_size_in_base_units']) == ('KG', '0.8')
    assert rye['match'] == {'product_id': 'own-rye-loaf', 'name': 'Rye sourdough loaf 800 g',
                            'unit_price_eur': '4.20', 'kind': 'PRICE_CHANGED'}
    assert by['Cinnamon bun']['match']['kind'] == 'SAME'
    assert by['Rye flour bulk']['draft']['unit'] == 'KG' and by['Rye flour bulk']['draft']['unit_price_eur'] == '2.80'
    rolls = by['Seed rolls']
    assert rolls['status'] == 'PLEASE_CHECK' and rolls['reasons'] == ['PRICE_UNIT_MISSING']
    assert rolls['draft']['unit_price_eur'] is None
    assert all(r['draft']['allergen_data'] == 'UNKNOWN' and r['draft']['price_source'] == 'price_list_photo'
               for r in out['rows'])


def test_a_price_without_a_printed_unit_is_please_check_with_an_empty_price():
    """Aron's added case (review point 1)."""
    r = one(row(price_unit='unknown'))
    assert r['status'] == 'PLEASE_CHECK' and 'PRICE_UNIT_MISSING' in r['reasons']
    assert r['draft']['unit_price_eur'] is None and r['draft']['unit'] is None


def test_the_unit_may_follow_a_slash_in_the_price():
    r = one(row(price='2,80 €/kg', price_unit='unknown'))
    assert r['status'] == 'READ' and r['draft']['unit'] == 'KG' and r['draft']['unit_price_eur'] == '2.80'


@pytest.mark.parametrize('text,expected', [('4,40 €', '4.40'), ('€4.40', '4.40'), ('2,5', '2.50'), ('12', '12.00'),
                                            ('0', None), ('4,40 / 3,90', '4.40'), ('3,90 4,40', None),
                                            ('4,405', None), ('ask', None), (None, None)])
def test_price_reading(text, expected):
    value = price(text)
    assert (None if value is None else f'{value:.2f}') == expected


@pytest.mark.parametrize('printed,code', [('kpl', 'ST'), ('€/kpl', 'ST'), ('/ kg', 'KG'), ('per kg', 'KG'),
                                          ('ltk', 'KI'), ('pussi', 'BAG'), ('L', 'L'), ('tray', None)])
def test_unit_mapping(printed, code):
    assert unit_of(printed, None)[1] == code


def test_an_unknown_unit_is_please_check():
    r = one(row(price_unit='tray'))
    assert r['reasons'] == ['UNIT_UNKNOWN'] and r['draft']['unit_price_eur'] is None


@pytest.mark.parametrize('text,expected', [('800 g', ('KG', '0.8')), ('1,5 kg', ('KG', '1.5')), ('33 cl', ('L', '0.33')),
                                            ('5 dl', ('L', '0.5')), ('500 ml', ('L', '0.5')), ('6 x 80 g', None)])
def test_pack_reading(text, expected):
    value = pack(text)
    assert (None if value is None else (value[0], f'{value[1]:f}')) == expected


def test_an_unclear_pack_keeps_the_price_but_not_the_pack():
    r = one(row(pack='6 x 80 g'))
    assert r['reasons'] == ['PACK_UNCLEAR'] and r['draft']['unit_price_eur'] == '0.95'
    assert r['draft']['base_unit'] is None and r['draft']['pack_size_in_base_units'] is None


def test_currency_is_eur_only_when_printed():
    """Review point 2: no currency sign anywhere is PLEASE_CHECK and an empty price."""
    r = one(row(price='0,95'), currency='unknown')
    assert 'CURRENCY_UNKNOWN' in r['reasons'] and r['draft']['unit_price_eur'] is None
    assert one(row(price='0,95'), currency='Hinnat EUR')['status'] == 'READ'
    assert one(row(price='0,95 €'), currency='unknown')['status'] == 'READ'


@pytest.mark.parametrize('text,expected', [('sis. alv 14 %', 'INCLUDED'), ('incl. VAT', 'INCLUDED'),
                                            ('inkl. moms', 'INCLUDED'), ('alv 0 %', 'EXCLUDED'), ('+ alv', 'EXCLUDED'),
                                            ('excl. VAT', 'EXCLUDED'), ('veroton', 'EXCLUDED'), ('unknown', None),
                                            ('Hinnat EUR', None)])
def test_vat_is_never_assumed(text, expected):
    assert vat(text) == expected


def test_vat_not_stated_marks_the_row_but_keeps_the_price():
    """Review point 3."""
    r = one(row(), vat_text='unknown')
    assert r['reasons'] == ['VAT_UNKNOWN'] and r['draft']['unit_price_eur'] == '0.95'


def test_a_match_is_a_suggestion_with_both_prices_and_no_kind_when_the_new_price_is_empty():
    """Review point 4: the name match never overwrites; it shows the old price next to the new."""
    existing = [{'product_id': 'own-1', 'name': 'Seed Rolls', 'unit_price_eur': '0.90'}]
    r = one(row(), existing=existing)
    assert r['match'] == {'product_id': 'own-1', 'name': 'Seed Rolls', 'unit_price_eur': '0.90', 'kind': 'PRICE_CHANGED'}
    assert one(row(price_unit='unknown'), existing=existing)['match']['kind'] is None
    two = existing + [{'product_id': 'own-2', 'name': 'seed rolls', 'unit_price_eur': '1.00'}]
    assert one(row(), existing=two)['match'] is None          # two names alike: no guess


def test_more_than_40_rows_is_truncated():
    """Review point 6."""
    out = read_rows({'currency': 'EUR', 'vat': 'sis. alv', 'rows': [row(name=f'Bun {i}') for i in range(55)]}, 'sup-bakery')
    assert out['truncated'] is True and len(out['rows']) == MAX_ROWS


def test_an_unreadable_name_and_a_reply_outside_the_schema():
    assert one(row(name='unknown'))['reasons'] == ['NAME_UNREADABLE']
    with pytest.raises(ValidationError):
        read_rows({'currency': 'EUR', 'rows': []}, 'sup-bakery')


def test_reader_makes_one_schema_constrained_photo_call():
    model = RecordedModel({'content': json.dumps({k: v for k, v in REPLY.items() if k != 'model'})})
    model.close = lambda: asyncio.sleep(0)
    result = asyncio.run(PriceListReader(WorkerError, model_factory=lambda: model).read(PHOTO))
    assert len(result['rows']) == 8 and len(model.requests) == 1 and model.requests[0]['name'] == 'price_list'
    assert model.requests[0]['messages'][1]['content'][1]['image_url']['url'].startswith('data:image/png;base64,')


def test_worker_auth_and_kitchen_scope(monkeypatch):
    monkeypatch.setenv('GATEWAY_AGENT_TOKEN', 'test-agent')
    monkeypatch.setenv('GATEWAY_KITCHEN_ID', 'k1')
    class Reader:
        async def read(self, image):
            return {'currency': 'EUR', 'vat': 'unknown', 'rows': []}
    async def run():
        app = create_app(price_list=Reader())
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://worker') as client:
            body = {'kitchen_id': 'k1', 'image_base64': base64.b64encode(PHOTO).decode()}
            auth = {'Authorization': 'Bearer test-agent'}
            assert (await client.post('/price-list', json=body)).status_code == 401
            assert (await client.post('/price-list', headers=auth, json={**body, 'kitchen_id': 'k2'})).status_code == 403
            assert (await client.post('/price-list', headers=auth, json=body)).status_code == 200
    asyncio.run(run())
