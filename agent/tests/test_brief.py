# agent/tests/test_brief.py
"""The brief worker makes one gated call and keeps all text out of the error path."""
import asyncio
import json

import pytest

from agent import brief as spec
from agent.brief_service import BriefWriter, _rows


class Model:
    def __init__(self, reply=None, error=None, close_error=False):
        self.reply, self.error, self.calls = reply, error, 0
        self.closed, self.close_error = False, close_error
        self.meter = None

    async def complete_json(self, messages, schema, name, *, max_tokens, role):
        self.calls += 1
        assert schema is spec.SCHEMA and role == 'kitchen_brief'
        if self.error:
            raise self.error
        return {'content': self.reply}

    async def close(self):
        self.closed = True
        if self.close_error:
            raise RuntimeError('secret https://key.example')


def row(**kw):
    base = {'kind': 'CUTOFF', 'ref_id': 'po-1', 'variants': ['Cutoff for po-1 is 14:00.'],
            'numbers': ['14:00']}
    base.update(kw)
    return base


def writer(model, timeout=30):
    def err(status, code):
        exc = RuntimeError(code)
        exc.status, exc.code = status, code
        return exc
    return BriefWriter(err, model_factory=lambda: model, timeout=timeout)


def good(rows):
    return json.dumps({'lines': [{'text': r['variants'][0], 'kind': r['kind'],
                                  'ref_id': r['ref_id'], 'numbers': r['numbers']} for r in rows]})


def test_one_call_and_no_secret_in_the_prompt_or_reply(monkeypatch):
    monkeypatch.setenv('GATEWAY_AGENT_TOKEN', 'agent-secret-token')
    model = Model(good([row()]))
    out = asyncio.run(writer(model).write([row()], 'en'))
    assert model.calls == 1 and model.closed
    assert out['lines'][0]['text'] == row()['variants'][0]
    user = spec.messages([row()], 'fi')[1]['content']
    assert 'agent-secret-token' not in user and 'Finnish' in user


def test_deadline_closes_the_model(monkeypatch):
    seen = []
    async def slow(msgs, schema, name, **kw):
        try:
            await asyncio.sleep(5)
        finally:
            seen.append('cancelled')
    async def run():
        model = Model()
        model.complete_json = slow
        with pytest.raises(RuntimeError) as err:
            await writer(model, timeout=0.01).write([row()], 'en')
        assert model.closed and seen == ['cancelled']
        assert (err.value.status, err.value.code) == (504, 'BRIEF_TIMEOUT')
    asyncio.run(run())


def test_model_service_error_is_unavailable():
    async def run():
        with pytest.raises(RuntimeError) as err:
            await writer(Model(error=RuntimeError('upstream body'))).write([row()], 'en')
        assert err.value.code == 'BRIEF_UNAVAILABLE' and 'upstream' not in str(err.value)
    asyncio.run(run())


def test_bad_rows_never_reach_the_model():
    assert _rows([row()])[0]['ref_id'] == 'po-1'
    for bad in ([], [row(extra=1)], [row(kind='NOPE')], [row(numbers=['x' * 25])],
                [row(variants=['', 'b', 'c'])]):
        assert _rows(bad) is None
