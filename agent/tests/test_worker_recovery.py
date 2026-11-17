"""No live services: cancellation must close claims, DB waits must leave the loop free."""
import asyncio
from threading import Event
from unittest.mock import patch

import mongomock
import pytest

from agent.service import BuyerWorker, WorkerError
from store import agent_runs

BODY = {'text': '10 L milk', 'requested_date': '2026-11-20', 'idempotency_key': 'recovery'}


class WaitingGateway:
    def __init__(self):
        self.started = asyncio.Event()

    async def request(self, *args, **kwargs):
        self.started.set()
        await asyncio.Event().wait()


def test_cancellation_closes_run_and_preserves_safe_retry_refusal():
    async def check():
        db = mongomock.MongoClient().test
        gateway = WaitingGateway()
        worker = BuyerWorker(db, gateway)
        with patch('agent.service.buyer_context.excluded_allergens', return_value=[]):
            task = asyncio.create_task(worker.run('k', BODY))
            await asyncio.wait_for(gateway.started.wait(), 2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert db.agent_runs.find_one()['state'] == 'RECONCILE'
            with pytest.raises(WorkerError) as caught:
                await worker.run('k', BODY)
            assert caught.value.code == 'BUYER_RECONCILIATION_REQUIRED'
            assert db.agent_runs.count_documents({}) == 1
    asyncio.run(check())


def test_cancellation_during_threaded_claim_cannot_orphan_a_run():
    async def check():
        db = mongomock.MongoClient().test
        entered, release = Event(), Event()
        original = agent_runs.claim
        def claim(*args):
            entered.set()
            assert release.wait(2)
            return original(*args)
        worker = BuyerWorker(db, WaitingGateway())
        with patch('agent.service.buyer_context.excluded_allergens', return_value=[]), patch('agent.service.agent_runs.claim', claim):
            task = asyncio.create_task(worker.run('k', BODY))
            try:
                assert await asyncio.to_thread(entered.wait, 2)
                task.cancel()
                await asyncio.sleep(0)
            finally:
                release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert db.agent_runs.find_one()['state'] == 'RECONCILE'
    asyncio.run(check())


def test_policy_read_does_not_block_event_loop():
    async def check():
        entered, release = Event(), Event()
        def slow(*args):
            entered.set()
            assert release.wait(2)
            raise RuntimeError('stop before gateway or model work')
        worker = BuyerWorker(mongomock.MongoClient().test, WaitingGateway())
        with patch('agent.service.buyer_context.excluded_allergens', slow):
            task = asyncio.create_task(worker.run('k', BODY))
            try:
                assert await asyncio.to_thread(entered.wait, 1)
                assert not task.done()
            finally:
                release.set()
            with pytest.raises(RuntimeError):
                await task
    asyncio.run(check())


def test_repeated_cancellation_does_not_interrupt_durable_cleanup():
    async def check():
        db = mongomock.MongoClient().test
        entered, release = Event(), Event()
        original = agent_runs.finish
        def finish(*args, **kwargs):
            entered.set()
            assert release.wait(2)
            return original(*args, **kwargs)
        gateway = WaitingGateway()
        worker = BuyerWorker(db, gateway)
        with patch('agent.service.buyer_context.excluded_allergens', return_value=[]), patch('agent.service.agent_runs.finish', finish):
            task = asyncio.create_task(worker.run('k', BODY))
            await gateway.started.wait()
            task.cancel()
            try:
                assert await asyncio.to_thread(entered.wait, 1)
                task.cancel()
                await asyncio.sleep(0)
            finally:
                release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert db.agent_runs.find_one()['state'] == 'RECONCILE'
    asyncio.run(check())


@pytest.mark.parametrize('failure', ['timeout', 'error'])
def test_cancellation_while_finalizing_failure_cannot_skip_reconciliation(failure):
    async def check():
        db = mongomock.MongoClient().test
        entered, release = Event(), Event()
        original = agent_runs.finish
        def finish(*args, **kwargs):
            entered.set()
            assert release.wait(2)
            return original(*args, **kwargs)
        class ErrorGateway:
            async def request(self, *args, **kwargs):
                raise RuntimeError('fixture error before model initialization')
        worker = BuyerWorker(db, WaitingGateway() if failure == 'timeout' else ErrorGateway(), timeout=0.01)
        with patch('agent.service.buyer_context.excluded_allergens', return_value=[]), patch('agent.service.agent_runs.finish', finish):
            task = asyncio.create_task(worker.run('k', BODY))
            try:
                assert await asyncio.to_thread(entered.wait, 1)
                task.cancel()
                await asyncio.sleep(0)
                task.cancel()
            finally:
                release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert db.agent_runs.find_one()['state'] == 'RECONCILE'
    asyncio.run(check())
