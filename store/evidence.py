"""Dated external evidence projections on proposals; no ordering authority."""


def save_product_evidence(db, kitchen_id, proposal_id, rows):
    result = db.proposals.update_one({'_id': proposal_id, 'kitchen_id': kitchen_id, 'status': 'READY',
        'product_evidence': {'$ne': rows}}, {'$set': {'product_evidence': rows}})
    return bool(result.modified_count)
