"""Error mapping of the gateway -> buyer worker handoff (run_buyer)."""
import asyncio

import httpx
import pytest

from gateway import buyer_worker
from gateway.service import GatewayError

BODY = {'text': '20 kg potatoes', 'idempotency_key': 'k-1'}


@pytest.fixture
def worker(monkeypatch):
    monkeypatch.setenv('BUYER_WORKER_URL', 'http://worker.test')
    monkeypatch.setenv('GATEWAY_AGENT_TOKEN', 'secret')
    real = httpx.AsyncClient

    def use(handler):
        def client(*args, **kwargs):
            return real(*args, transport=httpx.MockTransport(handler), **kwargs)
        monkeypatch.setattr(buyer_worker.httpx, 'AsyncClient', client)
    return use


def _call():
    with pytest.raises(GatewayError) as caught:
        asyncio.run(buyer_worker.run_buyer('k1', BODY))
    return caught.value


def test_not_configured_is_buyer_unavailable(monkeypatch):
    monkeypatch.delenv('BUYER_WORKER_URL', raising=False)
    monkeypatch.setenv('GATEWAY_AGENT_TOKEN', 'secret')
    err = _call()
    assert (err.status, err.code) == (503, 'BUYER_UNAVAILABLE')


def test_need_details_keeps_fallback_safe(worker):
    worker(lambda req: httpx.Response(422, json={'error': {'code': 'NEED_DETAILS', 'fallback_safe': True}}))
    err = _call()
    assert (err.status, err.code) == (422, 'NEED_DETAILS')
    assert err.extra['fallback_safe'] is True


def test_unknown_500_is_buyer_unavailable(worker):
    worker(lambda req: httpx.Response(500, json={'error': {'code': 'SOMETHING_ODD'}}))
    err = _call()
    assert (err.status, err.code) == (503, 'BUYER_UNAVAILABLE')
    assert err.extra['fallback_safe'] is False


def test_transport_error_requires_reconciliation(worker):
    def fail(req):
        raise httpx.ConnectError('down', request=req)
    worker(fail)
    err = _call()
    assert (err.status, err.code) == (503, 'BUYER_RECONCILIATION_REQUIRED')
    assert err.extra.get('fallback_safe', False) is False


def test_success_without_proposal_id_requires_reconciliation(worker):
    worker(lambda req: httpx.Response(200, json={'status': 'ok'}))
    err = _call()
    assert (err.status, err.code) == (503, 'BUYER_RECONCILIATION_REQUIRED')
