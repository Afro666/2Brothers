"""The request splitter (#1375) makes one call and returns only schema-checked rows."""
import asyncio
import json

import pytest

from agent import split as spec
from agent.split_service import Splitter


class Model:
    def __init__(self, reply=None, error=None):
        self.reply, self.error, self.calls, self.closed, self.meter = reply, error, 0, False, None

    async def complete_json(self, messages, schema, name, *, max_tokens, role):
        self.calls += 1
        assert schema is spec.SCHEMA and role == 'request_split'
        if self.error:
            raise self.error
        return {'content': self.reply}

    async def close(self):
        self.closed = True


class Err(Exception):
    def __init__(self, status, code):
        super().__init__(code)
        self.status, self.code = status, code


def splitter(model, timeout=30):
    return Splitter(Err, model_factory=lambda: model, timeout=timeout)


def test_one_call_returns_the_rows():
    needs = [{'text': 'oat drink', 'quantity': '20', 'unit': 'L'},
             {'text': 'rolls', 'quantity': '40', 'unit': 'ST'}]
    model = Model(json.dumps({'needs': needs}))
    out = asyncio.run(splitter(model).split('20 L oat drink and 40 rolls for Monday'))
    assert out['needs'] == needs and model.calls == 1 and model.closed
    user = spec.messages('20 L oat drink')[1]['content']
    assert '20 L oat drink' in user


@pytest.mark.parametrize('reply', ['not json', json.dumps({'needs': [{'text': 'x', 'quantity': '1',
                                                                        'unit': 'BOX'}]})])
def test_a_reply_outside_the_schema_is_refused(reply):
    with pytest.raises(Err) as got:
        asyncio.run(splitter(Model(reply)).split('20 L milk and 5 kg butter'))
    assert got.value.code == 'REPLY_INVALID'


def test_a_slow_model_is_a_timeout():
    class Slow(Model):
        async def complete_json(self, *a, **k):
            await asyncio.sleep(1)
    model = Slow()
    with pytest.raises(Err) as got:
        asyncio.run(splitter(model, timeout=0.01).split('20 L milk and 5 kg butter'))
    assert got.value.code == 'SPLIT_TIMEOUT' and model.closed


def test_no_model_key_is_unavailable():
    def none():
        raise ValueError('VERDA_INFERENCE_KEY is required')
    with pytest.raises(Err) as got:
        asyncio.run(Splitter(Err, model_factory=none).split('20 L milk and 5 kg butter'))
    assert got.value.code == 'SPLIT_UNAVAILABLE'
