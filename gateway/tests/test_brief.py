import asyncio
from copy import deepcopy
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi.responses import JSONResponse

from gateway.brief import checked_lines, mount_brief
from gateway.app import create_app
from gateway.service import Gateway, GatewayError
from gateway.tests.test_gateway_app import env, AGENT, HUMAN, NOW  # noqa: F401


def rows():
    return [dict(kind='CUTOFF', ref_id='p', urgent=True,
                 variants=['Milk: 20 L before 17:00.'], numbers=['20', '17', '0']),
            dict(kind='RECALL', ref_id='r', urgent=True,
                 variants=['Recall: coffee, 3 KG.'], numbers=['3'])]


def reply(source):
    return {'lines': [dict(kind=r['kind'], ref_id=r['ref_id'], text=r['variants'][0],
                           numbers=r['numbers']) for r in source]}


def test_wrong_row_number_and_invented_product_fail_individually():
    source = rows()
    raw = reply(source)
    raw['lines'][0].update(text='Milk: 3 L before 17:00.', numbers=['3', '17', '0'])
    lines, count = checked_lines(raw, source, 'en')
    assert count == 1 and lines[0]['text'] == source[0]['variants'][0]
    raw = reply(source)
    raw['lines'][0]['text'] = 'Poison: 20 L before 17:00.'
    assert checked_lines(raw, source, 'en')[1] == 1
    assert checked_lines({'lines': [True, None, {'text': 'extra'}]}, source, 'en')[1] == 0


def test_finnish_decimal_comma_and_thousands():
    source = [dict(kind='DELIVERY', ref_id='o', urgent=False,
                   variants=['Maitoa 1 000,5 L.'], numbers=['1000.5'])]
    raw = reply(source)
    raw['lines'][0]['numbers'] = ['1 000,5']
    assert checked_lines(raw, source, 'fi')[1] == 1


def make(worker=None, source=None):
    events, seen = [], []
    source = rows() if source is None else source
    gw = SimpleNamespace(_audit=lambda *a, **kw: events.append(kw))
    who = SimpleNamespace(name='test', need=lambda *a: None)
    def collect(gw, k, when, lang):
        seen.append((k, when, lang))
        return deepcopy(source)
    app = FastAPI()
    @app.exception_handler(GatewayError)
    async def error(request, exc):
        return JSONResponse(status_code=exc.status, content={'error': {'code': exc.code}})
    mount_brief(app, lambda: gw, lambda: who, worker, collector=collect)
    return app, events, source, seen


URL = '/v1/kitchens/test-brief/brief?when=morning&lang=en'


def test_cache_invalidation_and_key_scope():
    calls = []
    async def model(k, source, lang):
        calls.append((k, lang))
        return reply(source)
    app, events, source, seen = make(model)
    with TestClient(app) as c:
        assert c.get(URL).json()['made_by'] == 'model'
        assert c.get(URL).json()['made_by'] == 'model'
        assert len(calls) == 1 and events[-1]['cached']
        source[0]['variants'] = ['Milk: 30 L before 17:00.']
        source[0]['numbers'] = ['30', '17', '0']
        assert '30 L' in c.get(URL).json()['lines'][0]['text']
        c.get(URL.replace('test-brief', 'other'))
        c.get(URL.replace('morning', 'evening'))
        c.get(URL.replace('lang=en', 'lang=fi'))
    assert len(calls) == 5
    assert 'Milk' not in str(events) and all(set(e) == {'rows','model_lines','rule_lines','duration_ms','cached','when','lang'} for e in events)


def test_empty_missing_config_and_worker_failure(monkeypatch):
    monkeypatch.delenv('BUYER_WORKER_URL', raising=False)
    app, _, _, _ = make(source=[])
    result = TestClient(app).get(URL).json()
    assert result['nothing_urgent'] and result['lines'] == []
    assert result['made_by'] == 'rule' and result['model'] is None
    app, _, _, _ = make()
    assert TestClient(app).get(URL).json()['model'] is None
    async def failed(*args):
        raise httpx.ReadTimeout('private upstream text')
    app, _, _, _ = make(failed)
    result = TestClient(app).get(URL).json()
    assert result['made_by'] == 'rule' and len(result['lines']) == 2
    assert 'private' not in str(result)


def test_fact_change_during_model_wait_drops_old_reply():
    source = rows()
    async def model(*args):
        old = reply(deepcopy(source))
        source.clear()
        return old
    app, _, _, _ = make(model, source)
    result = TestClient(app).get(URL).json()
    assert result['lines'] == [] and result['made_by'] == 'rule'


def test_concurrent_reader_does_not_duplicate_call():
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        calls = []
        async def model(k, source, lang):
            calls.append(k)
            entered.set()
            await release.wait()
            return reply(source)
        app, _, _, _ = make(model)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://test') as client:
            first = asyncio.create_task(client.get(URL))
            await entered.wait()
            second = await client.get(URL)
            assert second.json()['made_by'] == 'rule'
            release.set()
            assert (await first).json()['made_by'] == 'model'
        assert len(calls) == 1
    asyncio.run(run())


@pytest.mark.parametrize('query', ['', '?when=night&lang=en', '?when=morning&lang=de',
                                 '?when=morning&lang=en&lang=fi', '?when=morning&lang=en&x=1'])
def test_strict_params(query):
    app, _, _, _ = make(source=[])
    assert TestClient(app).get(URL.split('?')[0]+query).status_code == 422


def test_real_auth_checks_before_read(env, monkeypatch):
    _, _, db = env
    monkeypatch.setenv('GATEWAY_KITCHEN_ID', 'demo-kitchen')
    monkeypatch.setattr('gateway.brief_facts.collect', lambda *a: [])
    gw = Gateway(db, None, now=lambda: NOW)
    c = TestClient(create_app(gw))
    from gateway import tokens
    token = tokens.create(db, 'demo-kitchen', 'brief-reader', ['kitchen:read'], 'test')['token']
    headers = {'Authorization': 'Bearer '+token}
    assert c.get('/v1/kitchens/demo-kitchen/brief?when=morning&lang=en', headers=AGENT).status_code == 200
    assert c.get(URL, headers=headers).status_code == 403
    assert c.get(URL).status_code == 401
