"""Kitchen-scoped trusted catalog/policy reads and chef option storage."""
from store.products import get_product
from datetime import datetime, timedelta


def product(db, kitchen_id, product_id):
    row = get_product(db, product_id)
    if row and row.get('kitchen_id') not in (None, kitchen_id):
        return None
    return row


def excluded_allergens(db, kitchen_id):
    settings = db.kitchen_settings.find_one({'_id': kitchen_id}) or {}
    # Missing policy is unknown; do not infer exclusions from a model's text.
    values = settings.get('excluded_allergens')
    if not isinstance(values, list) or any(not isinstance(v, str) for v in values):
        return None
    return values


def pick_facts(db, kitchen_id, offer_id, product_ids, now):
    """Private exact-quote evidence, declared diet claims and observed recent orders."""
    ids = set(product_ids)
    offer = db.offers.find_one({'_id': offer_id, 'kitchen_id': kitchen_id},
                              {'selection_facts': 1, 'valid_until': 1})
    if not offer:
        return {}
    try:
        expires = datetime.fromisoformat(offer['valid_until'].replace('Z', '+00:00'))
        if expires.tzinfo is None or expires <= now:
            return {}
    except (KeyError, ValueError, TypeError):
        return {}
    products = {p['_id']: p for p in db.products.find(
        {'_id': {'$in': list(ids)}, '$or': [{'kitchen_id': {'$exists': False}}, {'kitchen_id': kitchen_id}]},
        {'lactose_free': 1, 'gluten_free': 1})}
    counts = {pid: 0 for pid in ids}
    for order in db.orders.find({'kitchen_id': kitchen_id, 'outcome': 'CONFIRMED',
        'created_at': {'$gte': now - timedelta(days=56), '$lte': now},
        'placed_by': {'$ne': 'demo-seed'}, 'approved_by': {'$ne': 'demo-seed'}}, {'lines.product_id': 1}):
        for pid in {line.get('product_id') for line in order.get('lines') or []} & ids:
            counts[pid] += 1
    out = {}
    for pid, fact in (offer.get('selection_facts') or {}).items():
        if pid not in ids:
            continue
        product = products.get(pid, {})
        claims = {key: product.get(key) if isinstance(product.get(key), bool) else None
                  for key in ('lactose_free', 'gluten_free')}
        out[pid] = {**fact, 'ordered_before': counts[pid], 'diet_claims': claims}
    return out


def save_options(db, kitchen_id, proposal_id, options):
    db.proposals.update_one({'_id': proposal_id, 'kitchen_id': kitchen_id, 'status': 'READY'},
                            {'$set': {'substitute_options': options}})


def seed_demo_policy(db):
    """Default synthetic demo mandate only; never overwrite explicit settings."""
    kitchen_id = 'demo-kitchen'
    kitchen = db.kitchens.find_one({'_id': kitchen_id})
    if not kitchen or kitchen.get('synthetic') is not True:
        raise ValueError('A synthetic demo-kitchen is required')
    defaults = {'excluded_allergens': ['AP', 'AN', 'AS'],
                'excluded_allergens_source': 'synthetic web demo mandate'}
    db.kitchen_settings.update_one({'_id': kitchen_id}, {'$setOnInsert': defaults}, upsert=True)
    db.kitchen_settings.update_one({'_id': kitchen_id, 'excluded_allergens': {'$exists': False}},
                                  {'$set': defaults})
    return excluded_allergens(db, kitchen_id)


if __name__ == '__main__':
    from store.db import get_db
    try:
        seed_demo_policy(get_db())
        print('Synthetic demo policy configured; explicit settings preserved')
    except Exception:
        raise SystemExit('Demo policy setup failed; check synthetic kitchen and storage configuration') from None
