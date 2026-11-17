"""Cheap evidence version for cached kitchen facts, shared across worker processes.

Feedback and delivery observations are append-only. Selector revisions only rise;
disabled overrides only become inactive. These counters change at each supported
evidence mutation, without loading the underlying history or depending on wall time.
"""


def revision(db, kitchen_id):
    feedback = db.feedback.count_documents({'meta.kitchen_id': kitchen_id})
    disabled = db.learned_overrides.count_documents({'kitchen_id': kitchen_id, 'active': False})
    observed = db.delivery_results.count_documents({'kitchen_id': kitchen_id})
    current = list(db.delivery_result_current.aggregate([
        {'$match': {'kitchen_id': kitchen_id}},
        {'$group': {'_id': None, 'rows': {'$sum': 1}, 'revision': {'$sum': '$revision'}}},
    ]))
    selected = (current[0]['rows'], current[0]['revision']) if current else (0, 0)
    return feedback, disabled, observed, *selected
