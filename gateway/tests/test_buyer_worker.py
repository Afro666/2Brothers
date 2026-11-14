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


def test_event_flag_reaches_the_worker(worker):
    """#530: an event request keeps its flag on the worker path."""
    seen = {}

    def handler(request):
        import json
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={'proposal_id': 'p1'})
    worker(handler)
    asyncio.run(buyer_worker.run_buyer('k1', {**BODY, 'event': True}))
    assert seen['event'] is True
    seen.clear()
    asyncio.run(buyer_worker.run_buyer('k1', BODY))
    assert 'event' not in seen


def test_a_misspelt_kitchen_rule_keeps_its_code(worker):
    """The worker fails closed with KITCHEN_POLICY_INVALID; the client must see that code."""
    worker(lambda req: httpx.Response(503, json={'error': {'code': 'KITCHEN_POLICY_INVALID', 'fallback_safe': True}}))
    err = _call()
    assert (err.status, err.code) == (409, 'KITCHEN_POLICY_INVALID')


def _sent(worker, body, monkeypatch, today='2026-11-14'):
    """What run_buyer posts to the worker for `body`, on the Saturday 14 Nov 2026."""
    import json
    from datetime import date
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={'proposal_id': 'p1'})
    worker(handler)
    monkeypatch.setattr(buyer_worker, '_today', lambda: date.fromisoformat(today))
    asyncio.run(buyer_worker.run_buyer('k1', body))
    return seen


def test_a_day_named_in_the_text_wins_over_the_forms_date(worker, monkeypatch):
    """Live on 2026-11-14: "by Monday" sent with the form's 2026-11-17 was quoted for the 17th."""
    form = {'idempotency_key': 'k-1', 'requested_date': '2026-11-17'}
    assert _sent(worker, {**form, 'text': '50 kg cheese by Monday'}, monkeypatch)['requested_date'] == '2026-11-16'
    assert _sent(worker, {**form, 'text': '500 L oat drink by Friday'}, monkeypatch)['requested_date'] == '2026-11-20'
    assert _sent(worker, {**form, 'text': '1000 l maitoa maanantaiksi'}, monkeypatch)['requested_date'] == '2026-11-16'


def test_the_forms_date_stays_when_the_text_names_no_day(worker, monkeypatch):
    sent = _sent(worker, {'idempotency_key': 'k-1', 'requested_date': '2026-11-17', 'text': '60 kg butter'}, monkeypatch)
    assert sent['requested_date'] == '2026-11-17'


def test_no_date_is_invented_when_the_body_has_none(worker, monkeypatch):
    """No day in the text and none in the body: the worker answers NEED_DATE, as before."""
    assert 'requested_date' not in _sent(worker, {'idempotency_key': 'k-1', 'text': '60 kg butter'}, monkeypatch)
    # A day in the text and none in the body: the gateway sends the day it read.
    sent = _sent(worker, {'idempotency_key': 'k-1', 'text': '60 kg butter by Monday'}, monkeypatch)
    assert sent['requested_date'] == '2026-11-16'


def test_a_text_the_gateway_cannot_date_goes_to_the_worker_unchanged(worker, monkeypatch):
    """A date that does not exist is the worker's and the parser's to refuse, not this step's."""
    sent = _sent(worker, {'idempotency_key': 'k-1', 'requested_date': '2026-11-17', 'text': '20 kg butter 31.2.'},
                 monkeypatch)
    assert sent['requested_date'] == '2026-11-17'
    sent = _sent(worker, {'idempotency_key': 'k-1', 'requested_date': '2026-11-17', 'text': 12345}, monkeypatch)
    assert sent['requested_date'] == '2026-11-17'
