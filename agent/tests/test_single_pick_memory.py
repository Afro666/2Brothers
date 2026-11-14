"""The Buyer's product pick sees kitchen facts, and never fails because of them (#1308)."""
import asyncio
import json

from agent.service import BuyerWorker
from agent.tests.test_service import environment
from agent.tests.test_single_pick import NEED, Pick
import agent.single_pick as single_pick
from gateway.tests.test_gateway_app import NOW

FACT = {'id': 'lf-milk', 'kind': 'DECLINED_PRODUCT', 'product_id': '462775',
        'supplier_id': None, 'name': 'milk 462775', 'value': 1,
        'evidence': {'rows': 3, 'last': '2026-11-09'}, 'active': True}


async def pick(monkeypatch, compute):
    monkeypatch.setattr(single_pick, 'compute_facts', compute)
    db, gateway = environment(monkeypatch)
    model = Pick()
    try:
        result = await BuyerWorker(db, gateway, model_factory=lambda: model,
                                   now=lambda: NOW).run('demo-kitchen', NEED)
    finally:
        await gateway.close()
    return result, model


def test_the_pick_system_prompt_has_the_memory_block_after_one_guiding_line(monkeypatch):
    async def run():
        result, model = await pick(monkeypatch, lambda *args: [FACT])
        assert result['status'] == 'READY' and model.calls == 1
        messages = model.prompts[0]
        system = messages[0]['content']
        assert system.split('\n', 2)[:2] == [single_pick.SYSTEM, single_pick.MEMORY_NOTE]
        assert 'What this kitchen taught' in system and 'lf-milk' in system
        assert messages[1]['role'] == 'user'
    asyncio.run(run())


def test_without_facts_the_pick_messages_are_exactly_the_existing_ones(monkeypatch):
    async def run():
        _, model = await pick(monkeypatch, lambda *args: [])
        messages = model.prompts[0]
        assert messages[0] == {'role': 'system', 'content': single_pick.SYSTEM}
        assert single_pick.MEMORY_NOTE not in messages[0]['content']
        payload = json.loads(messages[1]['content'])
        assert messages[1]['role'] == 'user'
        assert set(payload) == {'request', 'products'} and payload['request'] == NEED['text']
    asyncio.run(run())


def test_a_facts_error_leaves_the_pick_working_without_memory(monkeypatch):
    def unavailable(*args):
        raise RuntimeError('feedback store down')

    async def run():
        result, model = await pick(monkeypatch, unavailable)
        assert result['status'] == 'READY' and model.calls == 1
        assert model.prompts[0][0] == {'role': 'system', 'content': single_pick.SYSTEM}
        assert single_pick.MEMORY_NOTE not in model.prompts[0][0]['content']
    asyncio.run(run())
