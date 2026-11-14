"""Recall evidence and proposal holds; Mongo access stays in store."""
from store.products import get_products


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


def blocked_ids(db, kitchen_id):
    return {row['product_id'] for row in db.recall_alerts.find({
        'kitchen_id': kitchen_id, 'match': {'$in': ['exact', 'possible']}})}


def hold(db, kitchen_id, proposal_id, alert):
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
