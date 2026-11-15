import asyncio
from datetime import datetime, timedelta, timezone
import json

from fastapi import BackgroundTasks
from fastapi.testclient import TestClient
import pytest

from agent.tests.test_explanation import reply_for
from gateway.app import create_app
from gateway.explanations import enrich
from gateway.service import Gateway
from gateway.tests.test_gateway_app import AGENT, HUMAN, K, NOW, env, milk  # noqa: F401
from gateway.valio_client import ValioClient
from store import explanations


def setup(env, worker):
    _, fake, db = env
    gw = Gateway(db, ValioClient('fixture', transport=fake.transport, ttl=0, now=lambda: NOW), now=lambda: NOW)
    return gw, TestClient(create_app(gw, explanation_worker=worker))


def test_opt_in_background_result_cache_language_and_audit_privacy(env):
    calls = []
    async def worker(kitchen, payload):
        calls.append(payload)
        return reply_for(payload)
    gw, client = setup(env, worker)
    p = milk(client)
    url = K + '/proposals/' + p['proposal_id']
    assert 'explanation' not in client.get(url, headers=AGENT).json() and calls == []
    first = client.get(url, headers=AGENT, params={'explanation_language': 'fi'})
    assert first.status_code == 200 and first.json()['explanation'] is None
    result = client.get(url, headers=AGENT, params={'explanation_language': 'fi'}).json()['explanation']
    assert result['checked'] and result['language'] == 'fi' and 'Mitään ei tilata' in result['text']
    assert len(calls) == 1 and env[2].orders.count_documents({}) == 0
    events = list(env[2].audit_log.find({'event.kind': 'proposal_explanation_ready'}))
    assert len(events) == 1 and result['text'] not in json.dumps(events, default=str)
    assert client.get(url, headers=AGENT, params={'explanation_language': 'sv'}).status_code == 422
    assert client.get(url, params={'explanation_language': 'fi'}).status_code == 401


@pytest.mark.parametrize('failure', ['worker', 'wrong_number', 'stale'])
def test_invalid_unavailable_and_changed_proposal_never_publish_text(env, failure):
    calls = []
    async def worker(kitchen, payload):
        calls.append(1)
        if failure == 'worker':
            raise RuntimeError('unavailable')
        reply = reply_for(payload)
        if failure == 'wrong_number':
            reply['sentences'][0]['text'] = reply['sentences'][0]['text'].replace('51', '99999')
        if failure == 'stale':
            env[2].proposals.update_one({'_id': p['proposal_id']}, {'$set': {'status': 'REJECTED'}})
        return reply
    _, client = setup(env, worker)
    p = milk(client)
    url = K + '/proposals/' + p['proposal_id']
    for _ in range(2):
        r = client.get(url, headers=AGENT, params={'explanation_language': 'en'})
        assert r.status_code == 200 and r.json()['explanation'] is None
    # A refused or broken reply is asked for once more (#1973); a changed proposal is not.
    assert len(calls) == (1 if failure == 'stale' else 2)
    assert env[2].proposal_explanations.count_documents({'state': 'ready'}) == 0
    assert env[2].audit_log.count_documents({'event.kind': 'proposal_explanation_failed'}) == 1


def test_response_does_not_await_the_model_and_parallel_viewers_share_claim(env):
    async def worker(*args):
        raise AssertionError('response must not await model')
    gw, client = setup(env, worker)
    p = milk(client)
    one, two = BackgroundTasks(), BackgroundTasks()
    first = enrich(gw, 'demo-kitchen', p, 'en', one, 'chef', worker)
    second = enrich(gw, 'demo-kitchen', p, 'en', two, 'chef', worker)
    assert first['explanation'] is None and second['explanation'] is None
    assert len(one.tasks) == 1 and len(two.tasks) == 0


def test_durable_budget_failure_cooldown_and_interrupted_lease_recovery(env):
    db = env[2]
    now = datetime.now(timezone.utc)
    lease = explanations.claim(db, 'k', 'p', 'source', 'en', now)
    assert lease
    assert explanations.claim(db, 'k', 'p', 'source', 'fi', now) is None
    assert explanations.claim(db, 'k', 'p', 'source', 'en', now+timedelta(seconds=44)) is None
    recovered = explanations.claim(db, 'k', 'p', 'source', 'en', now+timedelta(seconds=46))
    assert recovered and recovered['token'] != lease['token']
    explanations.finish(db, lease, {'text': 'stale lease'}, now+timedelta(seconds=47))
    assert explanations.cached(db, 'k', 'p', 'source', 'en') is None
    explanations.finish(db, recovered, None, now+timedelta(seconds=48))
    assert explanations.claim(db, 'k', 'p', 'source', 'en', now+timedelta(minutes=4)) is None
    assert explanations.claim(db, 'k', 'p', 'source', 'en', now+timedelta(minutes=6))


def test_source_hash_changes_when_option_or_status_changes(env):
    from gateway.explanation_facts import context
    _, client = setup(env, None)
    p = milk(client)
    old = context(p, {}, 'en')['source_hash']
    assert context({**p, 'offer_id': 'another'}, {}, 'en')['source_hash'] != old
    assert context({**p, 'status': 'APPROVED'}, {}, 'en')['source_hash'] != old


@pytest.mark.parametrize('first', ['worker_503', 'refused', 'broken'])
def test_a_failed_first_call_gets_one_retry_and_the_text_is_published(env, first, caplog):
    """Live 14 and 15 Nov (#1973): the first call for a new card failed in under one second."""
    import httpx
    calls = []
    async def worker(kitchen, payload):
        calls.append(1)
        reply = reply_for(payload)
        if len(calls) > 1:
            return reply
        if first == 'worker_503':
            request = httpx.Request('POST', 'http://worker/explain')
            raise httpx.HTTPStatusError('503', request=request, response=httpx.Response(503, request=request))
        if first == 'refused':
            reply['sentences'][0]['numbers'] = ['99999']
            return reply
        return {'duration_ms': 1}
    _, client = setup(env, worker)
    url = K + '/proposals/' + milk(client)['proposal_id']
    with caplog.at_level('WARNING', logger='gateway.explanations'):
        assert client.get(url, headers=AGENT, params={'explanation_language': 'en'}).json()['explanation'] is None
    result = client.get(url, headers=AGENT, params={'explanation_language': 'en'}).json()['explanation']
    assert result['checked'] and 'Nothing is ordered' in result['text'] and len(calls) == 2
    kinds = [e['event']['kind'] for e in env[2].audit_log.find({'event.kind': {'$regex': 'explanation'}})]
    assert kinds == ['proposal_explanation_ready']
    logged = [r.getMessage() for r in caplog.records if 'one retry' in r.getMessage()]
    assert len(logged) == 1 and 'attempt 1 failed' in logged[0]
    assert {'worker_503': 'reason=worker status 503', 'refused': 'reason=explanation sentence or numbers changed',
            'broken': 'error=KeyError'}[first] in logged[0]


@pytest.mark.parametrize('failure', ['timeout', 'rejected_request', 'not_configured'])
def test_no_retry_when_a_second_call_cannot_help(env, failure, monkeypatch):
    import httpx
    from gateway import explanations as module
    calls = []
    async def worker(kitchen, payload):
        calls.append(1)
        if failure == 'timeout':
            raise httpx.ReadTimeout('slow')
        if failure == 'not_configured':
            raise module.NotConfigured('explanation worker is not configured')
        request = httpx.Request('POST', 'http://worker/explain')
        raise httpx.HTTPStatusError('422', request=request, response=httpx.Response(422, request=request))
    _, client = setup(env, worker)
    url = K + '/proposals/' + milk(client)['proposal_id']
    for _ in range(2):
        assert client.get(url, headers=AGENT, params={'explanation_language': 'en'}).json()['explanation'] is None
    assert len(calls) == 1


def test_the_retry_is_bounded_at_two_calls_per_claim(env):
    calls = []
    async def worker(kitchen, payload):
        calls.append(1)
        raise RuntimeError('unavailable')
    _, client = setup(env, worker)
    url = K + '/proposals/' + milk(client)['proposal_id']
    for _ in range(5):          # five views: one claim, then the 5 minute cooldown
        assert client.get(url, headers=AGENT, params={'explanation_language': 'en'}).json()['explanation'] is None
    assert len(calls) == 2


def test_a_stored_text_is_still_returned_after_the_offer_expires(env):
    """It explains a past decision (#1973); only a new text needs a valid offer."""
    calls, clock = [], {'now': NOW}
    async def worker(kitchen, payload):
        calls.append(1)
        return reply_for(payload)
    _, fake, db = env
    gw = Gateway(db, ValioClient('fixture', transport=fake.transport, ttl=0, now=lambda: NOW), now=lambda: clock['now'])
    client = TestClient(create_app(gw, explanation_worker=worker))
    url = K + '/proposals/' + milk(client)['proposal_id']
    client.get(url, headers=AGENT, params={'explanation_language': 'en'})
    live = client.get(url, headers=AGENT, params={'explanation_language': 'en'}).json()['explanation']
    assert live['checked'] and len(calls) == 1
    clock['now'] = NOW + timedelta(minutes=16)
    late = client.get(url, headers=AGENT, params={'explanation_language': 'en'}).json()
    assert late['explanation'] == live and len(calls) == 1
    # No stored text in the other language: an expired offer starts no new model call.
    assert client.get(url, headers=AGENT, params={'explanation_language': 'fi'}).json()['explanation'] is None
    assert len(calls) == 1


def test_the_live_text_uses_the_catalog_pack_size_not_the_unit_code(env):
    calls = []
    async def worker(kitchen, payload):
        calls.append(payload)
        return reply_for(payload)
    _, client = setup(env, worker)
    url = K + '/proposals/' + milk(client)['proposal_id']
    client.get(url, headers=AGENT, params={'explanation_language': 'en'})
    text = client.get(url, headers=AGENT, params={'explanation_language': 'en'}).json()['explanation']['text']
    assert ' ST ' not in text and 'per ST' not in text
    assert ' x ' in text or ' pieces of ' in text or ' piece of ' in text
