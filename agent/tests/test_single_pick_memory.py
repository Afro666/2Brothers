"""The Buyer's product pick sees kitchen facts, and never fails because of them (#1308)."""
import asyncio
import json
from threading import Event

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
        assert set(payload) == {'request', 'need', 'products'} and payload['request'] == NEED['text']
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


def test_a_slow_memory_read_does_not_block_the_async_loop(monkeypatch):
    entered, release = Event(), Event()
    def slow(*args):
        entered.set()
        assert release.wait(2)
        return [FACT]
    monkeypatch.setattr(single_pick, 'compute_facts', slow)
    async def run():
        model = single_pick.SinglePickModel(None, None, 'demo-kitchen',
            {'text': NEED['text']}, 'need', [], today=NOW.date())
        task = asyncio.create_task(model.memory([{'product_id': FACT['product_id']}], {}))
        try:
            assert await asyncio.to_thread(entered.wait, 1)
            await asyncio.sleep(0)  # the pending store read cannot hold up this coroutine
            assert not task.done()
        finally:
            release.set()
        assert 'lf-milk' in await task
    asyncio.run(run())


def test_feedback_refresh_and_undo_change_cached_product_choice(monkeypatch):
    from agent.memory_cache import KitchenFactsCache
    from gateway.tests.test_learned import seed_corrections
    from store import learned
    async def run():
        db, gateway = environment(monkeypatch)
        seed_corrections(db)
        model = Pick()
        worker = BuyerWorker(db, gateway, model_factory=lambda: model, now=lambda: NOW)
        clock = [0]
        worker.memory_cache = KitchenFactsCache(clock=lambda: clock[0])
        try:
            await worker.run('demo-kitchen', NEED)
            assert model.calls == 1 and 'CORRECTION_RATIO' in model.prompts[0][0]['content']
            await worker.run('demo-kitchen', {**NEED, 'idempotency_key': 'same-memory'})
            assert model.calls == 1
            # Approved human feedback changes the evidence, hence the compact memory.
            db.feedback.update_many({'kind': 'qty_changed'}, {'$set': {'to_qty': '15'}})
            clock[0] = 61
            await worker.run('demo-kitchen', {**NEED, 'idempotency_key': 'new-evidence'})
            assert model.calls == 2
            assert model.prompts[0][0]['content'] != model.prompts[1][0]['content']
            facts = single_pick.compute_facts(single_pick._FactsGateway(db, NOW),
                                               'demo-kitchen', NOW.date())
            fact = next(f for f in facts if f['kind'] == 'CORRECTION_RATIO')
            learned.disable(db, 'demo-kitchen', fact['id'], 'chef-1', NOW)
            clock[0] = 122
            await worker.run('demo-kitchen', {**NEED, 'idempotency_key': 'undo-memory'})
            assert model.calls == 3
            assert model.prompts[2][0] == {'role': 'system', 'content': single_pick.SYSTEM}
            assert db.orders.count_documents({}) == 0
        finally:
            await gateway.close()
    asyncio.run(run())
