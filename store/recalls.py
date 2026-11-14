"""Recall evidence and proposal holds; Mongo access stays in store."""
from store.orders import NotPending, decide_approval
from store.products import get_products
from pymongo import ReturnDocument


def context(db, kitchen_id):
    proposals = list(db.proposals.find({'kitchen_id': kitchen_id,
        'status': {'$in': ['READY', 'APPROVING', 'BLOCKED_BY_RECALL']}}))
    ids = set()
    for proposal in proposals:
        offer = db.offers.find_one({'_id': proposal['offer_id']}) or {}
        ids.update(line['product_id'] for line in offer.get('simulation', {}).get('lines', []))
    return {'kitchen_id': kitchen_id, 'products': get_products(db, sorted(ids), kitchen_id),
            'proposal': sorted(ids), 'stock': {}, 'recipes': {}}, proposals


def remember(db, alert):
    db.recall_alerts.update_one({'_id': alert['event_id'], 'kitchen_id': alert['kitchen_id']},
        {'$setOnInsert': {k: v for k, v in alert.items() if k != 'event_id'}}, upsert=True)
    saved = db.recall_alerts.find_one({'_id': alert['event_id'], 'kitchen_id': alert['kitchen_id']})
    return {'event_id': saved.pop('_id'), **saved}


def blocked_ids(db, kitchen_id):
    return {row['product_id'] for row in db.recall_alerts.find({
        'kitchen_id': kitchen_id, 'status': {'$ne': 'dismissed'}, 'match': {'$in': ['exact', 'possible']}})}


def hold(db, kitchen_id, proposal_id, alert):
    current = db.recall_alerts.find_one({'_id': alert['event_id'], 'kitchen_id': kitchen_id})
    if alert.get('status') == 'dismissed' or (current and current.get('status') == 'dismissed'):
        return False
    query = {'_id': proposal_id, 'kitchen_id': kitchen_id}
    db.proposals.update_one(query, {'$addToSet': {'recall_alerts': alert}})
    if alert['match'] == 'review':
        return False
    # Shares the approval state machine. COMMITTING is the order commit point;
    # a later notice is an incident, never a claim that an order was cancelled.
    db.proposals.update_one({**query, 'status': {'$in': ['READY', 'APPROVING']}},
        {'$set': {'status': 'BLOCKED_BY_RECALL'}})
    row = db.proposals.find_one(query) or {}
    return row.get('status') == 'BLOCKED_BY_RECALL'


def link(db, kitchen_id, proposal_id, **fields):
    db.proposals.update_one({'_id': proposal_id, 'kitchen_id': kitchen_id,
        'status': 'BLOCKED_BY_RECALL'}, {'$set': fields})


def candidates(db, kitchen_id, source):
    ids = source.get('substitutions') or []
    if not ids and source.get('category'):
        ids = [row['_id'] for row in db.products.find({'category': source['category']}, {'_id': 1}).limit(20)]
    return get_products(db, ids[:20], kitchen_id)


def reject_replacement(db, kitchen_id, proposal_id, reason):
    """A partial recall replacement must not stay approvable in the inbox."""
    row = db.proposals.find_one_and_update({'_id': proposal_id, 'kitchen_id': kitchen_id, 'status': 'READY'},
        {'$set': {'status': 'REJECTED', 'reject_reason': reason}})
    if row and row.get('approval_id'):
        try:
            decide_approval(db, row['approval_id'], status='REJECTED', decided_by='recall-monitor', reason=reason)
        except NotPending:
            pass
    return row is not None


def dismiss(db, kitchen_id, event_id, *, human, reason, at):
    query = {'_id': event_id, 'kitchen_id': kitchen_id}
    row = db.recall_alerts.find_one_and_update({**query, 'status': {'$ne': 'dismissed'}},
        {'$set': {'status': 'dismissed', 'dismissed_by': human, 'dismissed_at': at,
                  'dismiss_reason': reason}}, return_document=ReturnDocument.AFTER)
    return row or db.recall_alerts.find_one(query)


def visible_alerts(db, kitchen_id, alerts):
    ids = [a['event_id'] for a in alerts]
    saved = {row['_id']: row for row in db.recall_alerts.find({'kitchen_id': kitchen_id, '_id': {'$in': ids}})}
    out = []
    for alert in alerts:
        latest = saved.get(alert['event_id'], alert)
        out.append({**alert, 'status': latest.get('status', 'active'),
                    **{key: latest[key] for key in ('dismissed_by', 'dismissed_at', 'dismiss_reason') if key in latest}})
    return out


def reject_basket(db, kitchen_id, proposal_id, *, human, reason, at):
    query = {'_id': proposal_id, 'kitchen_id': kitchen_id}
    row = db.proposals.find_one_and_update({**query, 'status': {'$in': ['READY', 'BLOCKED_BY_RECALL']}},
        {'$set': {'status': 'REJECTED', 'reject_reason': reason, 'rejected_by': human, 'rejected_at': at}},
        return_document=ReturnDocument.AFTER)
    row = row or db.proposals.find_one(query)
    if row and row.get('status') == 'REJECTED' and row.get('approval_id'):
        try:
            decide_approval(db, row['approval_id'], status='REJECTED',
                            decided_by=row.get('rejected_by', human), reason=row.get('reject_reason', ''))
        except NotPending:
            pass
    return row
