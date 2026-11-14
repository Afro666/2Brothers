import asyncio
from datetime import date
import json
from unittest.mock import AsyncMock

import httpx
import mongomock
import pytest
from fastapi.testclient import TestClient

from agent.service import BuyerWorker, WorkerError, create_app, parse_need
from gateway.app import create_app as gateway_app
from gateway.service import Gateway
from gateway.valio_client import ValioClient
from gateway.mcp_server import GatewayClient
from gateway.tests.test_gateway_app import RAW, FakeValio, NOW
from agent.tests.test_runner import tool


def test_explicit_need_parser_does_not_invent_quantities():
    need = parse_need({'text': '1,000 L lactose-free milk by Monday'}, today=date(2026, 11, 13))
    assert need['quantity'] == '1000' and need['unit'] == 'L'
    assert need['requested_date'] == '2026-11-16'
    for text in ('some milk', '10 L or 20 L milk', '0 L milk', '-10 L milk'):
        with pytest.raises(WorkerError):
            parse_need({'text': text, 'requested_date': '2026-11-16'})


class ScriptedBuyer:
    def __init__(self):
        self.calls = 0
    async def close(self):
        pass
    async def complete(self, messages, definitions):
        need = json.loads(messages[1]['content'])
        steps = [tool('search_products', query='lactose-free milk', filters={}),
                 tool('get_offer', product_ids=['462775'], requested_date=need['requested_date'], need_id=need['need_id']),
                 tool('simulate_order', offer_id=None), tool('request_approval', offer_id=None)]
        result = steps[self.calls]
        if self.calls >= 2:
            offers = [json.loads(m['content']) for m in messages if m['role'] == 'tool']
            offer = next(row['offer_id'] for row in offers if 'offer_id' in row)
            result['tool_calls'][0]['function']['arguments'] = json.dumps({'offer_id': offer})
        self.calls += 1
        return result


def environment(monkeypatch):
    monkeypatch.setenv('GATEWAY_AGENT_TOKEN', 'test-agent-only')
    db = mongomock.MongoClient(tz_aware=True).test
    for pid, raw in RAW.items():
        db.products.insert_one({'_id': pid, 'names': {'en': 'milk'}, 'raw': raw})
    fake = FakeValio()
    core = Gateway(db, ValioClient('fixture-key', transport=fake.transport, ttl=0, now=lambda: NOW), now=lambda: NOW)
    app = gateway_app(core)
    upstream = httpx.ASGITransport(app=app)
    class Transport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            if request.url.path == '/tools/search_products':
                return httpx.Response(200, json={'products': [{'product_id': '462775'}]})
            return await upstream.handle_async_request(request)
    return db, GatewayClient('http://gateway', token='test-agent-only', transport=Transport())


def test_real_buyer_worker_creates_ready_proposal_and_durable_audit_once(monkeypatch):
    async def run():
        db, gateway = environment(monkeypatch)
        model = ScriptedBuyer()
        worker = BuyerWorker(db, gateway, model_factory=lambda: model, now=lambda: NOW)
        body = {'text': '51 L milk', 'requested_date': '2026-11-16', 'idempotency_key': 'request-1'}
        try:
            proposal = await worker.run('demo-kitchen', body)
            assert proposal['status'] == 'READY' and proposal['approval_id']
            assert proposal['buyer_model'] == 'nemotron-3.5-super-vl'
            assert await worker.run('demo-kitchen', body) == proposal
            assert model.calls == 4
            assert db.needs.count_documents({}) == 1
            assert db.orders.count_documents({}) == 0
            assert db.audit_log.count_documents({'event.run_id': proposal['buyer_run_id']}) == 8
            with pytest.raises(WorkerError) as caught:
                await worker.run('demo-kitchen', {**body, 'text': '52 L milk'})
            assert caught.value.code == 'IDEMPOTENCY_KEY_REUSED'
        finally:
            await gateway.close()
    asyncio.run(run())


def test_invalid_allergen_code_fails_closed_before_any_buyer_run(monkeypatch):
    async def run():
        db, gateway = environment(monkeypatch)
        db.kitchen_settings.insert_one({'_id': 'demo-kitchen', 'excluded_allergens': ['not-an-allergen']})
        factory = AsyncMock(side_effect=AssertionError('model must not start'))
        worker = BuyerWorker(db, gateway, model_factory=factory, now=lambda: NOW)
        body = {'text': '51 L milk', 'requested_date': '2026-11-16', 'idempotency_key': 'bad-policy'}
        try:
            with pytest.raises(WorkerError) as caught:
                await worker.run('demo-kitchen', body)
            assert (caught.value.status, caught.value.code) == (503, 'KITCHEN_POLICY_INVALID')
            assert caught.value.fallback_safe
            factory.assert_not_called()
            assert db.agent_runs.count_documents({}) == 0
            assert db.needs.count_documents({}) == 0
        finally:
            await gateway.close()
    asyncio.run(run())


def test_timeout_never_restarts_an_ambiguous_run(monkeypatch):
    class Slow(ScriptedBuyer):
        async def complete(self, *args):
            await asyncio.sleep(10)
    async def run():
        db, gateway = environment(monkeypatch)
        worker = BuyerWorker(db, gateway, model_factory=Slow, timeout=0.02)
        body = {'text': '51 L milk', 'requested_date': '2026-11-16', 'idempotency_key': 'timeout'}
        try:
            with pytest.raises(WorkerError) as caught:
                await worker.run('demo-kitchen', body)
            assert caught.value.code == 'BUYER_TIMEOUT'
            assert db.agent_runs.find_one({})['state'] == 'RECONCILE'
            with pytest.raises(WorkerError) as caught:
                await worker.run('demo-kitchen', body)
            assert caught.value.code == 'BUYER_RECONCILIATION_REQUIRED'
        finally:
            await gateway.close()
    asyncio.run(run())


def test_internal_worker_requires_agent_token_and_fixed_kitchen(monkeypatch):
    monkeypatch.setenv('GATEWAY_AGENT_TOKEN', 'internal-test-token')
    worker = AsyncMock()
    client = TestClient(create_app(worker))
    assert client.post('/run', json={}).status_code == 401
    response = client.post('/run', headers={'Authorization': 'Bearer internal-test-token'}, json={'kitchen_id': 'other'})
    assert response.status_code == 403
    worker.run.assert_not_called()


def test_public_free_text_route_hands_off_to_worker(monkeypatch):
    monkeypatch.setenv('GATEWAY_AGENT_TOKEN', 'internal-test-token')
    called = AsyncMock(return_value={'proposal_id': 'p', 'status': 'READY'})
    # Auth now consults the gateway's session repository before the injected
    # worker. Keep this test independent of a developer's .env / live database.
    gateway = Gateway(mongomock.MongoClient(tz_aware=True).test, None)
    client = TestClient(gateway_app(gateway, buyer_worker=called))
    body = {'text': '51 L milk', 'requested_date': '2026-11-16', 'idempotency_key': 'k'}
    result = client.post('/v1/kitchens/demo-kitchen/proposals', headers={'Authorization': 'Bearer internal-test-token'}, json=body)
    assert result.status_code == 200 and result.json()['status'] == 'READY'
    called.assert_awaited_once_with('demo-kitchen', body)
