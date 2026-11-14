"""The buying-note worker (#1176): one schema-constrained call, only row facts go in."""
import asyncio
import json
from pathlib import Path

import httpx
import pytest

from agent.buying_note_service import BuyingNoteWriter
from agent.receiving import RecordedModel
from agent.service import WorkerError, create_app

FIXTURES = Path(__file__).resolve().parents[1] / 'fixtures' / 'buying_note'
ROWS = json.loads((FIXTURES / 'rows.json').read_text(encoding='utf-8'))


def recorded(lang):
    reply = json.loads((FIXTURES / f'{lang}.reply.json').read_text(encoding='utf-8'))
    model = RecordedModel({'content': json.dumps({'lines': reply['lines']})})
    model.close = lambda: asyncio.sleep(0)
    return model


def test_one_structured_call_with_the_rows_and_the_language():
    model = recorded('fi')
    result = asyncio.run(BuyingNoteWriter(WorkerError, model_factory=lambda: model).write(ROWS, 'fi'))
    assert [line['row'] for line in result['lines']] == [0, 1, 2]
    assert len(model.requests) == 1 and model.requests[0]['name'] == 'buying_note'
    user = model.requests[0]['messages'][1]['content']
    assert 'Finnish' in user and '462775' in user
    assert 'by_kitchen' not in json.dumps(model.requests[0]['messages'])      # rows.json had it; pick() dropped it


@pytest.mark.parametrize('content', ['not json', json.dumps({'lines': [{'row': 0}]}),
                                     json.dumps({'lines': [], 'extra': 1})])
def test_a_reply_outside_the_schema_is_refused_whole(content):
    model = RecordedModel({'content': content})
    model.close = lambda: asyncio.sleep(0)
    with pytest.raises(WorkerError) as err:
        asyncio.run(BuyingNoteWriter(WorkerError, model_factory=lambda: model).write(ROWS, 'en'))
    assert err.value.code == 'REPLY_INVALID'


@pytest.mark.parametrize('timeout', [True, False])
def test_a_failed_single_call_closes_the_client(timeout):
    class Model:
        calls, closed = 0, False
        async def complete_json(self, *args, **kwargs):
            self.calls += 1
            if timeout:
                await asyncio.sleep(10)
            raise RuntimeError('provider unavailable')
        async def close(self):
            self.closed = True
    model = Model()
    with pytest.raises(WorkerError) as err:
        asyncio.run(BuyingNoteWriter(WorkerError, model_factory=lambda: model, timeout=0.01).write(ROWS, 'en'))
    assert err.value.code == ('BUYING_NOTE_TIMEOUT' if timeout else 'BUYING_NOTE_UNAVAILABLE')
    assert model.calls == 1 and model.closed


def test_no_model_key_is_unavailable():
    def factory():
        raise ValueError('VERDA_INFERENCE_KEY is required')
    with pytest.raises(WorkerError) as err:
        asyncio.run(BuyingNoteWriter(WorkerError, model_factory=factory).write(ROWS, 'en'))
    assert err.value.code == 'BUYING_NOTE_UNAVAILABLE'


def test_worker_route_needs_the_agent_token_and_only_documented_row_fields(monkeypatch):
    monkeypatch.setenv('GATEWAY_AGENT_TOKEN', 'test-agent')
    seen = []
    class Writer:
        async def write(self, rows, lang):
            seen.append((rows, lang))
            return {'model': 'nemotron-3.5-super-vl', 'lines': []}
    auth = {'Authorization': 'Bearer test-agent'}
    body = {'supplier_id': 'sup-valio', 'lang': 'en', 'rows': ROWS}
    async def run():
        app = create_app(buying_note=Writer())
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://worker') as client:
            assert (await client.post('/buying-note', json=body)).status_code == 401
            assert (await client.post('/buying-note', headers=auth, json={**body, 'lang': 'sv'})).status_code == 422
            leak = [{**ROWS[0], 'by_kitchen': [{'kitchen_name': 'Hotel One'}]}]
            assert (await client.post('/buying-note', headers=auth, json={**body, 'rows': leak})).status_code == 422
            assert (await client.post('/buying-note', headers=auth, json={**body, 'rows': []})).status_code == 422
            assert (await client.post('/buying-note', headers=auth, json=body)).status_code == 200
    asyncio.run(run())
    assert len(seen) == 1 and seen[0][1] == 'en'
