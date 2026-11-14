import asyncio
from datetime import date
from decimal import Decimal
import json

import httpx
import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from agent.runner import Buyer
from agent.substitutes import AllergenPolicy, SubstitutePlanner
from agent.tests.test_runner import Scripted, tool
from engine import plan_request
from gateway.scenarios import _offer, _row
from gateway.mcp_server import GatewayClient, build_server


def product(pid, *, known=True, contains=(), may=(), substitutes=()):
    return {'product_id': pid, 'names': {'en': 'gluten-free bread'}, 'category': 'bread',
            'allergen_data_known': known, 'allergens': {'contains': list(contains),
            'may_contain': list(may), 'undeclared': []}, 'substitutions': list(substitutes)}


class Scenario:
    def __init__(self, catalog, offers, source, quantity, measure, fallback=()):
        self.catalog, self.offers, self.source = catalog, offers, source
        self.quantity, self.measure, self.fallback = Decimal(quantity), measure, fallback
        self.quotes, self.events, self.baskets = {}, {}, []

    def __call__(self, request):
        body = json.loads(request.content) if request.content else {}
        path = request.url.path
        if path == '/audit/events':
            self.events[body['event_id']] = body
            data = {'event_id': body['event_id'], 'stored': True}
        elif path == '/tools/search_products':
            ids = [self.source] if body['query'] == 'original' else list(self.fallback)
            data = {'products': [self.catalog[pid] for pid in ids]}
        elif path == '/tools/get_offer':
            self.baskets.append(body['product_ids'])
            plan = plan_request(self.quantity, self.measure, [self.offers[pid] for pid in body['product_ids']], date(2026,11,16))
            oid = f'offer-{len(self.quotes)+1}'
            data = {'offer_id': oid, 'valid_until': '2099-01-01T00:00:00Z', 'currency': 'EUR',
                    'expected_total': f'{plan.total:.2f}', 'shortfall': str(plan.shortfall),
                    'mandate': {'verdict': 'NEEDS_APPROVAL' if plan.lines else 'REFUSED',
                                'reasons': [], 'reason_codes': list(plan.reason_codes)},
                    'lines': [{'product_id': line.product_id, 'quantity': f'{line.quantity.normalize():f}',
                               'unit': line.unit, 'why': line.why, 'unknown_stock': line.unknown_stock}
                              for line in plan.lines]}
            self.quotes[oid] = data
        elif path == '/tools/simulate_order':
            data = self.quotes[body['offer_id']]
        elif path == '/tools/request_approval':
            data = {'approval_id': 'a1', 'status': 'PENDING'}
        else:
            return httpx.Response(403, json={'error': {'code': 'FORBIDDEN'}})
        return httpx.Response(200, json=data)


def run_case(scenario, policy):
    async def run():
        gateway = GatewayClient(transport=httpx.MockTransport(scenario))
        lookup = scenario.catalog.get
        steps = [tool('search_products', query='original', filters={}),
                 tool('get_offer', product_ids=[scenario.source], need_id='need', requested_date='2026-11-16'),
                 tool('simulate_order', offer_id='offer-1'), tool('request_approval', offer_id='offer-1')]
        try:
            async with create_connected_server_and_client_session(build_server(gateway)) as session:
                buyer = Buyer(Scripted(steps), session, gateway, need_id='need', requested_date='2026-11-16',
                              catalog_lookup=lookup, allergen_policy=policy,
                              substitute_planner=SubstitutePlanner(lookup, policy))
                return await buyer.run('Chef request')
        finally:
            await gateway.close()
    return asyncio.run(run())


def test_s02_buyer_proposes_supplier_gap_by_weight_then_catalog_option():
    catalog = {'465138': product('465138', known=False, substitutes=['462300','475752']),
               '462300': product('462300', contains=['GO']), '475752': product('475752'),
               'catalog': product('catalog'), 'unknown': product('unknown', known=False)}
    offers = {
        '465138': _offer('465138','PH7',_row('465138','KI','ST',[('KI',1)]),'64.27','7.65','KG','16',False,measure='KG'),
        '462300': _offer('462300','Elovena',_row('462300','BAG','ST',[('BAG',1)]),'3.58','8.95','KG',None,False,measure='KG'),
        '475752': _offer('475752','Late',_row('475752','KI','ST',[('KI',1)]),'17.86','11.16','KG',None,True,measure='KG'),
        'catalog': _offer('catalog','Other',_row('catalog','ST','KG',[('ST',1)]),'5.00','5.00','KG','200',False,measure='KG')}
    scenario = Scenario(catalog, offers, '465138', '168', 'KG', fallback=['unknown','catalog'])
    result = run_case(scenario, AllergenPolicy())
    assert result['status'] == 'SENT_FOR_APPROVAL'
    options = result['substitute_options']
    assert [option['tier'] for option in options] == ['good','better','best']
    assert options[1]['source'] == 'supplier'
    assert [(line['product_id'],line['quantity']) for line in options[1]['lines']] == [('465138','16'),('462300','84')]
    assert options[1]['expected_total'] == '1329.04'  # 1028.32 + 300.72, engine-owned
    assert options[0]['allergen_data_known'] is False
    assert options[1]['stock_confirmed'] is False
    assert all(option['requires_chef_approval'] for option in options)
    assert 'unknown' not in {pid for basket in scenario.baskets for pid in basket}
    assert not any(event['tool'] == 'place_order' for event in scenario.events.values())


def test_s03_coeliac_school_never_quotes_oatly_or_unknown_allergens():
    catalog = {'468465': product('468465', contains=['GO'], substitutes=['470863','unknown','rye']),
               '470863': product('470863', contains=['AW','GO']),
               'unknown': product('unknown', known=False), 'rye': product('rye', may=['NR'])}
    offers = {'468465': _offer('468465','Oddlygood',_row('468465','ST','LTR',[('ST',1)]),'1.17','1.17','L',None,False,measure='L')}
    scenario = Scenario(catalog, offers, '468465', '60', 'L', fallback=['470863','unknown','rye'])
    result = run_case(scenario, AllergenPolicy(('AW',)))
    assert result['status'] == 'SENT_FOR_APPROVAL'
    assert {pid for basket in scenario.baskets for pid in basket} == {'468465'}
    assert {line['product_id'] for option in result['substitute_options'] for line in option['lines']} == {'468465'}


def test_unknown_allergen_policy_codes_fail_closed():
    with pytest.raises(ValueError):
        AllergenPolicy(('not-an-allergen',))


def _original_option(lines):
    class FakeBuyer:
        offer_products = {'offer-1': ['463380']}
    catalog = {pid: product(pid) for pid in ('463380', '463335')}

    async def read(name, args):
        return {'products': []}
    simulation = {'offer_id': 'offer-1', 'expected_total': '2579.29', 'currency': 'EUR',
                  'mandate': {'verdict': 'NEEDS_APPROVAL'}, 'lines': lines}
    planner = SubstitutePlanner(catalog.get, AllergenPolicy())
    options = asyncio.run(planner.plan(FakeBuyer(), simulation, read))
    assert options[0]['source'] == 'original'
    return options[0]


def test_original_option_with_unconfirmed_line_says_what_waits():
    option = _original_option([
        {'product_id': '463380', 'quantity': '698', 'unit': 'ST', 'unknown_stock': False},
        {'product_id': '463335', 'quantity': '302', 'unit': 'ST', 'unknown_stock': True}])
    assert 'confirmed portion only' not in option['why']
    assert option['why'] == "The Buyer's basket as proposed: 698 ST confirmed, 302 ST waits for stock confirmation."
    assert option['stock_confirmed'] is False


def test_original_option_all_confirmed_keeps_confirmed_portion_text():
    option = _original_option([
        {'product_id': '463380', 'quantity': '698', 'unit': 'ST', 'unknown_stock': False}])
    assert option['why'] == 'Requested product, confirmed portion only.'
    assert option['stock_confirmed'] is True
