"""Trusted human approval host. Not an MCP tool and never driven by the LLM.

The HTTP/session layer supplies a verified HumanSession and two kitchen-scoped
gateway callables. Placement still enforces all #19 guards independently.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re

from store import approval_dispatch, audit
from store.orders import IdempotencyConflict, NotPending


@dataclass(frozen=True)
class HumanSession:
    kitchen_id: str
    user_id: str
    scopes: frozenset[str]


class ApprovalError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _total(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d+\.\d{2}', value):
        raise ApprovalError('INVALID_TOTAL')
    try:
        if not Decimal(value).is_finite():
            raise ApprovalError('INVALID_TOTAL')
    except InvalidOperation:
        raise ApprovalError('INVALID_TOTAL') from None
    return value


class ApprovalHost:
    def __init__(self, db, *, simulate, place):
        self.db, self.simulate, self.place = db, simulate, place

    async def approve(self, *, session, kitchen_id, approval_id, expected_total, idempotency_key):
        # A route must construct this from its server-side authenticated human
        # session, not deserialize it from JSON or trust an actor/user header.
        if (not isinstance(session, HumanSession) or not isinstance(session.user_id, str)
                or not session.user_id.strip()
                or 'kitchen:approve' not in session.scopes):
            raise ApprovalError('HUMAN_SESSION_REQUIRED')
        if any(not isinstance(value, str) or not value.strip()
               for value in (kitchen_id, approval_id)):
            raise ApprovalError('NOT_FOUND')
        if session.kitchen_id != kitchen_id:
            raise ApprovalError('NOT_FOUND')
        expected_total = _total(expected_total)
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            raise ApprovalError('MISSING_IDEMPOTENCY_KEY')
        row = approval_dispatch.scoped_approval(self.db, kitchen_id, approval_id)
        if not row:
            raise ApprovalError('NOT_FOUND')
        if row['status'] == 'PENDING':
            # A stale browser must not approve an updated offer even if the new
            # simulation is still internally consistent.
            if row.get('expected_total') != expected_total:
                raise ApprovalError('TOTAL_MISMATCH')
            simulation = await self.simulate(kitchen_id=kitchen_id, offer_id=row['offer_id'])
            if (simulation.get('offer_id') != row['offer_id']
                    or simulation.get('currency') != 'EUR'
                    or simulation.get('expected_total') != expected_total):
                raise ApprovalError('TOTAL_MISMATCH')
            if simulation.get('mandate', {}).get('verdict') != 'NEEDS_APPROVAL':
                raise ApprovalError('REFUSED')
        try:
            row, created = approval_dispatch.claim(
                self.db, kitchen_id=kitchen_id, approval_id=approval_id, user_id=session.user_id,
                expected_total=expected_total, idempotency_key=idempotency_key)
        except NotPending:
            raise ApprovalError('ALREADY_DECIDED') from None
        except IdempotencyConflict:
            raise ApprovalError('IDEMPOTENCY_KEY_REUSED') from None
        if not created:
            return self.receipt(row)
        try:
            audit.append_event(self.db, {
                'event_id': row['dispatch']['placement_key'] + ':approval',
                'type': 'approval_decided', 'approval_id': approval_id,
                'offer_id': row['offer_id'], 'expected_total': expected_total,
                'status': 'APPROVED'},
                {'kitchen_id': kitchen_id, 'principal': session.user_id})
        except Exception:
            # No send if its durable audit could not be written.
            approval_dispatch.finish(self.db, kitchen_id=kitchen_id,
                                     approval_id=approval_id, state='RECONCILE')
            raise ApprovalError('AUDIT_UNAVAILABLE') from None
        try:
            result = await self.place(kitchen_id=kitchen_id, offer_id=row['offer_id'],
                                      expected_total=expected_total,
                                      idempotency_key=row['dispatch']['placement_key'])
            if (not isinstance(result, dict) or not isinstance(result.get('order_id'), str)
                    or not result['order_id'] or result.get('outcome') not in
                    ('CONFIRMED', 'NOT_SENT', 'UNCONFIRMED', 'SENT_READ_FAILED')
                    or result.get('status') not in
                    (None, 'SENT', 'CONFIRMED', 'PARTIAL', 'REJECTED', 'UNCONFIRMED')):
                raise ValueError('invalid placement receipt')
            # Never store arbitrary upstream response fields (credentials/errors).
            result = {k: result.get(k) for k in ('order_id', 'outcome', 'status')}
            approval_dispatch.finish(self.db, kitchen_id=kitchen_id,
                                     approval_id=approval_id, state='FINISHED', result=result)
        except Exception:
            approval_dispatch.finish(self.db, kitchen_id=kitchen_id,
                                     approval_id=approval_id, state='RECONCILE')
        return self.receipt(approval_dispatch.scoped_approval(self.db, kitchen_id, approval_id))

    @staticmethod
    def receipt(row):
        dispatch = row['dispatch']
        return {'approval_id': row['approval_id'], 'status': row['status'],
                'placement_state': dispatch['state'], 'order': dispatch.get('result')}


def build_approval_host(db, gateway_for_kitchen):
    """Bind existing GatewayClient transports, selected from trusted kitchen scope.

    The factory must return a client authenticated for that kitchen, never a
    global client whose kitchen is supplied by browser or model arguments.
    Client lifetime belongs to the application, not each approval request.
    """
    async def simulate(*, kitchen_id, offer_id):
        return await gateway_for_kitchen(kitchen_id).request(
            'POST', '/tools/simulate_order', payload={'offer_id': offer_id})

    async def place(*, kitchen_id, offer_id, expected_total, idempotency_key):
        return await gateway_for_kitchen(kitchen_id).request(
            'POST', '/tools/place_order', payload={
                'offer_id': offer_id, 'expected_total': expected_total,
                'idempotency_key': idempotency_key})

    return ApprovalHost(db, simulate=simulate, place=place)
