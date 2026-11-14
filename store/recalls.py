"""Recall evidence and proposal holds; Mongo access stays in store."""
from store.history import current_stock
from store.orders import NotPending, decide_approval
from store.products import get_products
from store.repository import Repository
from pymongo import ReturnDocument


def context(db, kitchen_id):
    """The kitchen the recall monitor scans, and its open proposals.

    A recalled product matters where the kitchen has it: on an open proposal, on the shelf
    or in a recipe. `stock` is the newest count per product, `{product_id: (on_hand, unit)}`;
    a count of zero is not on the shelf, and a product that was listed but not counted keeps
    `None` (unknown, never zero). `recipes` is `{product_id: [recipe name, ...]}`."""
    proposals = list(db.proposals.find({'kitchen_id': kitchen_id,
        'status': {'$in': ['READY', 'APPROVING', 'BLOCKED_BY_RECALL']}}))
    ids = set()
    for proposal in proposals:
        offer = db.offers.find_one({'_id': proposal['offer_id']}) or {}
        ids.update(line['product_id'] for line in offer.get('simulation', {}).get('lines', []))
    stock = {}
    for row in current_stock(db, kitchen_id):
        on_hand = row.get('on_hand')
        if on_hand is None or on_hand > 0:
            stock[row['product_id']] = (None if on_hand is None else float(on_hand), row['unit'])
    recipes = {}
    for recipe in sorted(Repository(db).recipes.list(kitchen_id), key=lambda row: row['name']):
        for item in recipe.get('ingredients') or []:
            names = recipes.setdefault(item['product_id'], [])
            if recipe['name'] not in names:
                names.append(recipe['name'])
    used = sorted(ids | set(stock) | set(recipes))
    return {'kitchen_id': kitchen_id, 'products': get_products(db, used, kitchen_id),
            'proposal': sorted(ids), 'stock': stock, 'recipes': recipes}, proposals


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
    # One entry per event_id: a re-poll carries a new detected_at, so $addToSet would duplicate.
    db.proposals.update_one({**query, 'recall_alerts.event_id': {'$ne': alert['event_id']}},
        {'$push': {'recall_alerts': alert}})
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


# ---- read side of GET /recalls and POST /recalls/check (#358); additive ----

def alerts(db, kitchen_id):
    """Every recorded alert of one kitchen, newest first, with `event_id` and a status."""
    rows = db.recall_alerts.find({'kitchen_id': kitchen_id}).sort('detected_at', -1).limit(200)
    return [{'event_id': row.pop('_id'), **row, 'status': row.get('status', 'active')} for row in rows]


def carrying(db, kitchen_id):
    """This kitchen's proposals that carry a recall alert, newest first."""
    return list(db.proposals.find({'kitchen_id': kitchen_id, 'recall_alerts.0': {'$exists': True}})
                .sort('created_at', -1).limit(100))


def check_entry(db, kitchen_id, event_id=None):
    """The audit entry of one recall check (`event_id`), or of the newest one; else None."""
    query = {'server.kitchen_id': kitchen_id, 'event.kind': 'recall_check'}
    if event_id is not None:
        query['event.event_id'] = event_id
    return db.audit_log.find_one(query, sort=[('_id', -1)])
