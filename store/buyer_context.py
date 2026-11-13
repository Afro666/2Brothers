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
