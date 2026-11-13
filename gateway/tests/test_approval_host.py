import asyncio
from copy import deepcopy
import unittest
from unittest.mock import patch

import mongomock
import httpx
import json

from gateway.approval_host import ApprovalError, ApprovalHost, HumanSession, build_approval_host
from gateway.mcp_server import GatewayClient
from store import audit, orders
from store.db import ensure_indexes


class ApprovalFlowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db = mongomock.MongoClient(tz_aware=True).test
        ensure_indexes(self.db)
        self.approval, _ = orders.request_approval(
            self.db, kitchen_id='k1', idempotency_key='request-1', offer_id='offer-1',
            expected_total='149.02')
        self.session = HumanSession('k1', 'chef-42', frozenset({'kitchen:approve'}))
        self.simulation = {'offer_id': 'offer-1', 'expected_total': '149.02', 'currency': 'EUR',
                           'mandate': {'verdict': 'NEEDS_APPROVAL'}}
        self.sends = []

        async def simulate(**kwargs):
            self.assertEqual(kwargs, {'kitchen_id': 'k1', 'offer_id': 'offer-1'})
            return deepcopy(self.simulation)

        async def place(**kwargs):
            # Models/gateway must see a recorded human approval before dispatch.
            stored = orders.get_approval(self.db, self.approval['approval_id'])
            self.assertEqual(stored['status'], 'APPROVED')
            self.assertEqual(stored['decided_by'], 'chef-42')
            self.assertTrue(audit.list_events(self.db, kitchen_id='k1'))
            self.sends.append(kwargs)
            order, created = orders.record_attempt(self.db, **kwargs, lines=[], payload_hash='h')
            self.assertTrue(created)
            orders.set_outcome(self.db, order['order_id'], outcome='CONFIRMED', status='SENT')
            return {'order_id': order['order_id'], 'status': 'SENT', 'outcome': 'CONFIRMED'}

        self.host = ApprovalHost(self.db, simulate=simulate, place=place)

    async def approve(self, **overrides):
        args = dict(session=self.session, kitchen_id='k1', approval_id=self.approval['approval_id'],
                    expected_total='149.02', idempotency_key='decision-1')
        return await self.host.approve(**{**args, **overrides})

    async def assert_error(self, code, **overrides):
        with self.assertRaises(ApprovalError) as caught:
            await self.approve(**overrides)
        self.assertEqual(caught.exception.code, code)

    async def test_human_approval_places_once_with_exact_simulated_total(self):
        first = await self.approve()
        replay = await self.approve()
        self.assertEqual(first, replay)
        self.assertEqual(first['order']['outcome'], 'CONFIRMED')
        self.assertEqual(len(self.sends), 1)
        self.assertEqual(self.sends[0]['expected_total'], '149.02')
        self.assertEqual(len(orders.list_orders(self.db, 'k1')), 1)
        self.assertTrue(audit.verify_chain(self.db)['ok'])

    async def test_concurrent_clicks_only_dispatch_once(self):
        entered = 0
        both = asyncio.Event()
        async def simulate(**kwargs):
            nonlocal entered
            entered += 1
            if entered == 2:
                both.set()
            await both.wait()
            return self.simulation
        self.host.simulate = simulate
        await asyncio.gather(self.approve(), self.approve())
        self.assertEqual(len(self.sends), 1)

    async def test_agent_and_other_kitchen_cannot_approve(self):
        for session in (None, {'user_id': 'chef-42'}, HumanSession('k1', 'agent', frozenset())):
            await self.assert_error('HUMAN_SESSION_REQUIRED', session=session)
        await self.assert_error('NOT_FOUND', kitchen_id='other')
        self.assertEqual(self.sends, [])

    async def test_changed_total_and_refusal_leave_pending(self):
        await self.assert_error('TOTAL_MISMATCH', expected_total='149.03')
        self.simulation['expected_total'] = '149.03'
        await self.assert_error('TOTAL_MISMATCH')
        self.simulation['expected_total'] = '149.02'
        self.simulation['mandate']['verdict'] = 'REFUSED'
        await self.assert_error('REFUSED')
        self.assertEqual(orders.get_approval(self.db, self.approval['approval_id'])['status'], 'PENDING')

    async def test_rejected_and_changed_retry_cannot_dispatch(self):
        await self.approve()
        await self.assert_error('IDEMPOTENCY_KEY_REUSED', idempotency_key='different')
        await self.assert_error('IDEMPOTENCY_KEY_REUSED', expected_total='150.00')
        self.assertEqual(len(self.sends), 1)
        second, _ = orders.request_approval(self.db, kitchen_id='k1', idempotency_key='r2', offer_id='o2')
        orders.decide_approval(self.db, second['approval_id'], status='REJECTED', decided_by='chef')
        await self.assert_error('ALREADY_DECIDED', approval_id=second['approval_id'])

    async def test_ambiguous_send_is_never_retried(self):
        async def timeout(**kwargs):
            self.sends.append(kwargs)
            raise TimeoutError('sensitive upstream detail')
        self.host.place = timeout
        first = await self.approve()
        self.assertEqual(first['placement_state'], 'RECONCILE')
        self.assertNotIn('sensitive', str(first))
        self.assertEqual(await self.approve(), first)
        self.assertEqual(len(self.sends), 1)

    async def test_crash_after_claim_leaves_in_progress_without_resend(self):
        async def crash(**kwargs):
            raise asyncio.CancelledError()
        self.host.place = crash
        with self.assertRaises(asyncio.CancelledError):
            await self.approve()
        replay = await self.approve()
        self.assertEqual(replay['placement_state'], 'CLAIMED')
        self.assertIsNone(replay['order'])

    async def test_audit_failure_prevents_send(self):
        with patch('gateway.approval_host.audit.append_event', side_effect=RuntimeError('private')):
            await self.assert_error('AUDIT_UNAVAILABLE')
        self.assertEqual(self.sends, [])
        self.assertEqual((await self.approve())['placement_state'], 'RECONCILE')

    async def test_bad_money_or_key_cannot_decide(self):
        for value in (149.02, True, 'NaN', '149.020', '-1.00'):
            await self.assert_error('INVALID_TOTAL', expected_total=value)
        await self.assert_error('MISSING_IDEMPOTENCY_KEY', idempotency_key=' ')

    async def test_gateway_transport_binding_uses_trusted_kitchen_and_one_post(self):
        posts = []
        def transport(request):
            payload = json.loads(request.content)
            if request.url.path == '/tools/simulate_order':
                self.assertEqual(payload, {'offer_id': 'offer-1'})
                return httpx.Response(200, json=self.simulation)
            self.assertEqual(request.url.path, '/tools/place_order')
            self.assertEqual(orders.get_approval(self.db, self.approval['approval_id'])['status'], 'APPROVED')
            posts.append(payload)
            return httpx.Response(200, json={'order_id': 'o1', 'outcome': 'CONFIRMED', 'status': 'SENT'})
        client = GatewayClient('http://scoped-gateway', transport=httpx.MockTransport(transport))
        def client_for(kitchen_id):
            self.assertEqual(kitchen_id, 'k1')
            return client
        try:
            self.host = build_approval_host(self.db, client_for)
            result = await self.approve()
            self.assertEqual(await self.approve(), result)
            self.assertEqual(len(posts), 1)
            self.assertEqual(posts[0]['expected_total'], '149.02')
        finally:
            await client.close()

    async def test_query_objects_cannot_be_used_as_identifiers(self):
        await self.assert_error('NOT_FOUND', approval_id={'$ne': None})
        await self.assert_error('NOT_FOUND', kitchen_id={'$ne': None})


if __name__ == '__main__':
    unittest.main()
