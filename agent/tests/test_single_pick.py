import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

import pytest

from agent.service import BuyerWorker, WorkerError
from agent.tests.test_service import environment
from gateway.tests.test_gateway_app import NOW
from store import buyer_picks

NEED = {'text': '51 L milk', 'requested_date': '2026-11-16', 'idempotency_key': 'first'}


def test_legacy_mode_retains_model_retry_defaults(monkeypatch):
    import agent.service as service
    calls = []
    monkeypatch.setattr(service, 'Nemotron', lambda **kw: calls.append(kw))
    BuyerWorker(None, None, strategy='loop').model_factory()
    BuyerWorker(None, None, strategy='single_pick').model_factory()
    assert calls == [{}, {'max_attempts': 1}]


class Pick:
    def __init__(self, reply=None):
        self.calls, self.prompts, self.closed = 0, [], False
        self.reply = reply or {'picks': [{'index': 0, 'reason': 'Matches the requested milk'}]}
    async def complete_json(self, messages, schema, name, **kw):
        self.calls += 1
        self.prompts.append(messages)
        assert kw == {'max_tokens': 512, 'role': 'buyer_pick'}
        return {'content': json.dumps(self.reply)}
    async def close(self):
        self.closed = True


def test_one_model_call_then_cached_ids_with_fresh_price_and_new_offer(monkeypatch):
    from gateway.tests.test_gateway_app import FakeValio
    original = FakeValio.transport
    factor = [1]
    def price_changes(self, path, payload, headers):
        result = original(self, path, payload, headers)
        if path == '/api/price':
            for p in result['products']:
                for field in ('catalogPrice', 'comparisonPrice'):
                    if p.get(field, {}).get('value') is not None:
                        p[field]['value'] = float(p[field]['value']) * factor[0]
        return result
    monkeypatch.setattr(FakeValio, 'transport', price_changes)
    async def run():
        db, gateway = environment(monkeypatch)
        model = Pick()
        worker = BuyerWorker(db, gateway, model_factory=lambda: model, now=lambda: NOW)
        assert worker.strategy == 'single_pick'
        try:
            first = await worker.run('demo-kitchen', NEED)
            again = await worker.run('demo-kitchen', NEED)
            assert first == again and model.calls == 1
            factor[0] = 2
            second = await worker.run('demo-kitchen', {**NEED, 'idempotency_key': 'second'})
            assert second['offer_id'] != first['offer_id'] and model.calls == 2
            assert float(second['expected_total']) > float(first['expected_total'])
            assert first['lines'][0]['quantity'] == '51'
            assert next(s for s in first['model_trace']['steps'] if s['tool'] == 'pick')['by'] == 'model'
            third = await worker.run('demo-kitchen', {**NEED, 'idempotency_key': 'third'})
            assert model.calls == 2
            assert next(s for s in third['model_trace']['steps'] if s['tool'] == 'pick')['code'] == 'CACHED_PICK'
            assert all(s['by'] == 'code' for s in first['model_trace']['steps'] if s['tool'] != 'pick')
            assert db.orders.count_documents({}) == 0 and db.proposals.count_documents({}) == 3
            sent = json.loads(model.prompts[0][1]['content'])
            assert len(json.dumps(model.prompts[0])) < 6000
            assert set(sent['products'][0]) == {'index', 'product_id', 'name', 'pack', 'can_arrive', 'alias',
                                               'price_per_unit', 'price_unit', 'engine_selected', 'selection'}
        finally:
            await gateway.close()
    asyncio.run(run())


def test_same_choice_in_flight_waits_for_the_leader_pick(monkeypatch):
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        class Blocking(Pick):
            async def complete_json(self, *a, **kw):
                self.calls += 1
                entered.set()
                await release.wait()
                return {'content': json.dumps(self.reply)}
        db, gateway = environment(monkeypatch)
        models = []
        def factory():
            model = Blocking()
            models.append(model)
            return model
        worker = BuyerWorker(db, gateway, model_factory=factory, now=lambda: NOW)
        first = asyncio.create_task(worker.run('demo-kitchen', NEED))
        try:
            await asyncio.wait_for(entered.wait(), 2)
            second = asyncio.create_task(worker.run('demo-kitchen', {**NEED, 'idempotency_key': 'concurrent'}))
            await asyncio.sleep(0.3)
            assert not second.done() and sum(m.calls for m in models) == 1
            release.set()
            leader, follower = await first, await asyncio.wait_for(second, 5)
            assert leader['status'] == follower['status'] == 'READY'
            ids = lambda r: [l['product_id'] for l in r['lines']]
            assert ids(follower) == ids(leader) and sum(m.calls for m in models) == 1
            assert next(s for s in follower['model_trace']['steps'] if s['tool'] == 'pick')['code'] == 'CACHED_PICK'
            assert db.orders.count_documents({}) == 0
        finally:
            release.set()
            await first
            await gateway.close()
    asyncio.run(run())


def test_number_word_in_a_pick_reason_still_makes_a_proposal(monkeypatch):
    async def run():
        db, gateway = environment(monkeypatch)
        model = Pick({'picks': [{'index': 0, 'reason': 'the only one in stock'}]})
        try:
            worker = BuyerWorker(db, gateway, model_factory=lambda: model, now=lambda: NOW)
            result = await worker.run('demo-kitchen', NEED)
            assert result['status'] == 'READY' and model.calls == 1
            assert result['lines'] and db.proposals.count_documents({}) == 1
        finally:
            await gateway.close()
    asyncio.run(run())


@pytest.mark.parametrize('reply', [
    {'picks': [{'index': 19, 'reason': 'not in this shortlist'}]},
    {'picks': [{'index': 0, 'reason': 'x', 'quantity': '10000'}]},
    {'picks': [{'index': 0, 'reason': 'x'}, {'index': 0, 'reason': 'duplicate'}]}])
def test_bad_pick_stops_before_approval_with_safe_parser_fallback(monkeypatch, reply):
    async def run():
        db, gateway = environment(monkeypatch)
        model = Pick(reply)
        try:
            worker = BuyerWorker(db, gateway, model_factory=lambda: model, now=lambda: NOW)
            with pytest.raises(WorkerError) as err:
                await worker.run('demo-kitchen', NEED)
            assert err.value.fallback_safe
            assert db.proposals.count_documents({}) == 0 and db.orders.count_documents({}) == 0
            assert model.calls == 1 and model.closed
        finally:
            await gateway.close()
    asyncio.run(run())


def test_slow_model_has_a_single_deadline_and_never_retries(monkeypatch):
    from agent.single_pick import SinglePickModel
    original = SinglePickModel.__init__
    def short(self, *a, **kw):
        original(self, *a, **kw, timeout=0.01)
    monkeypatch.setattr(SinglePickModel, '__init__', short)
    class Slow(Pick):
        async def complete_json(self, *a, **kw):
            self.calls += 1
            await asyncio.sleep(10)
    async def run():
        db, gateway = environment(monkeypatch)
        model = Slow()
        try:
            with pytest.raises(WorkerError) as err:
                await BuyerWorker(db, gateway, model_factory=lambda: model, now=lambda: NOW).run('demo-kitchen', NEED)
            assert err.value.code == 'BUYER_TIMEOUT' and err.value.fallback_safe
            assert model.calls == 1 and model.closed
            assert db.proposals.count_documents({}) == 0
        finally:
            await gateway.close()
    asyncio.run(run())


def test_pick_cache_expiry_policy_scope_and_interrupted_claims(monkeypatch):
    import mongomock
    from agent.service import parse_need
    db = mongomock.MongoClient(tz_aware=True).test
    need = parse_need(NEED)
    rows = [{'product_id': 'p', 'name': 'Milk', 'pack': {'value': 1, 'unit': 'L'}, 'can_arrive': True}]
    key = buyer_picks.cache_key('k', need, ['AP'], rows)
    assert buyer_picks.cache_key('other', need, ['AP'], rows) != key
    assert buyer_picks.cache_key('k', need, ['AM'], rows) != key
    assert buyer_picks.cache_key('k', {**need, 'requested_date': '2026-11-17'}, ['AP'], rows) != key
    assert buyer_picks.cache_key('k', need, ['AP'], [{**rows[0], 'price_per_unit': '999'}]) == key
    now = datetime.now(timezone.utc)
    token = buyer_picks.claim(db, key, now)
    assert token and buyer_picks.claim(db, key, now) is None
    assert buyer_picks.claim(db, key, now + timedelta(seconds=59)) is None
    replacement = buyer_picks.claim(db, key, now + timedelta(seconds=61))
    assert replacement and replacement != token
    assert not buyer_picks.finish(db, key, token, ['stale'], now + timedelta(seconds=62))
    assert buyer_picks.get(db, key, now + timedelta(seconds=62)) is None
    assert buyer_picks.finish(db, key, replacement, ['p'], now + timedelta(seconds=62))
    assert buyer_picks.get(db, key, now + timedelta(seconds=63)) == ['p']
    assert buyer_picks.get(db, key, now + timedelta(seconds=663)) is None


def test_lost_cache_claim_never_requests_approval(monkeypatch):
    original = buyer_picks.finish
    def lost(db, key, token, ids, *a, **kw):
        if ids:
            return False
        return original(db, key, token, ids, *a, **kw)
    monkeypatch.setattr(buyer_picks, 'finish', lost)
    async def run():
        db, gateway = environment(monkeypatch)
        try:
            with pytest.raises(WorkerError) as err:
                await BuyerWorker(db, gateway, model_factory=Pick, now=lambda: NOW).run('demo-kitchen', NEED)
            assert err.value.fallback_safe and db.proposals.count_documents({}) == 0
        finally:
            await gateway.close()
    asyncio.run(run())
