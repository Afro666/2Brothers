"""Atomic human approval and single dispatch claim, shared by gateway hosts."""
from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid5

from pymongo import ReturnDocument

from store.orders import IdempotencyConflict, NotPending, get_approval


def scoped_approval(db, kitchen_id, approval_id):
    row = get_approval(db, approval_id)
    return row if row and row['kitchen_id'] == kitchen_id else None


def claim(db, *, kitchen_id, approval_id, user_id, expected_total, idempotency_key):
    """Decide and claim in one document update, before any placement call.

    A crash after claiming requires reconciliation, never automatic redispatch.
    Keys for placement derive from the approval, not a browser's retry key.
    """
    dispatch_key = str(uuid5(NAMESPACE_URL, f'2brothers:{kitchen_id}:{approval_id}:place'))
    row = db.approvals.find_one_and_update(
        {'_id': approval_id, 'kitchen_id': kitchen_id, 'status': 'PENDING'},
        {'$set': {'status': 'APPROVED', 'decided_by': user_id,
                  'decided_at': datetime.now(timezone.utc),
                  'dispatch': {'state': 'CLAIMED', 'expected_total': expected_total,
                               'decision_key': idempotency_key, 'placement_key': dispatch_key}}},
        return_document=ReturnDocument.AFTER)
    if row:
        row['approval_id'] = row.pop('_id')
        return row, True
    row = scoped_approval(db, kitchen_id, approval_id)
    if not row or row['status'] != 'APPROVED' or not row.get('dispatch'):
        raise NotPending(approval_id)
    dispatch = row['dispatch']
    if dispatch['expected_total'] != expected_total or dispatch['decision_key'] != idempotency_key:
        raise IdempotencyConflict('approval decision differs from its recorded dispatch')
    return row, False


def finish(db, *, kitchen_id, approval_id, state, result=None):
    if state not in ('FINISHED', 'RECONCILE'):
        raise ValueError('invalid dispatch state')
    db.approvals.update_one(
        {'_id': approval_id, 'kitchen_id': kitchen_id, 'dispatch.state': 'CLAIMED'},
        {'$set': {'dispatch.state': state, 'dispatch.result': result}})
