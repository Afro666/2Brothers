import asyncio

import pytest

from agent.service import BuyerWorker, WorkerError
from agent.tests.test_service import ScriptedBuyer, environment
from agent.tests.test_single_pick import Pick
from gateway.tests.test_gateway_app import NOW


@pytest.mark.parametrize('strategy', ['loop', 'single_pick'])
@pytest.mark.parametrize('receipt', ['direct', 'legacy', 'wrong_approval', 'wrong_proposal'])
def test_receipt_reads_one_proposal_and_never_repeats_a_mutation(monkeypatch, strategy, receipt):
    async def run():
        db, gateway = environment(monkeypatch)
        original = gateway.request
        calls = {'list': 0, 'detail': 0, 'mutation': 0}
        async def request(method, path, **kw):
            if method == 'GET' and path.endswith('/proposals'):
                calls['list'] += 1
            if method == 'GET' and '/proposals/' in path:
                calls['detail'] += 1
            result = await original(method, path, **kw)
            if path == '/tools/request_approval':
                calls['mutation'] += 1
                if receipt == 'legacy':
                    result.pop('proposal_id', None)
            if method == 'GET' and '/proposals/' in path:
                if receipt == 'wrong_approval':
                    result['approval_id'] = 'other'
                elif receipt == 'wrong_proposal':
                    result['proposal_id'] = 'other'
            return result
        gateway.request = request
        worker = BuyerWorker(db, gateway, strategy=strategy,
            model_factory=ScriptedBuyer if strategy == 'loop' else Pick, now=lambda: NOW)
        try:
            body = {'text': '51 L milk', 'requested_date': '2026-11-16', 'idempotency_key': 'receipt'}
            if receipt.startswith('wrong'):
                with pytest.raises(WorkerError) as err:
                    await worker.run('demo-kitchen', body)
                assert err.value.code == 'BUYER_RECONCILIATION_REQUIRED' and not err.value.fallback_safe
            else:
                assert (await worker.run('demo-kitchen', body))['status'] == 'READY'
            assert calls == {'list': int(receipt == 'legacy'), 'detail': int(receipt != 'legacy'), 'mutation': 1}
            assert db.proposals.count_documents({}) == 1 and db.orders.count_documents({}) == 0
        finally:
            await gateway.close()
    asyncio.run(run())
