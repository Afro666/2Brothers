"""Kitchen-scoped trusted catalog/policy reads and chef option storage."""
from store.products import get_product


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
