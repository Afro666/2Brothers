"""Replay metadata on a menu-photo proposal; images are never persisted."""


def cached_result(db, kitchen_id, key):
    proposal = db.proposals.find_one({'kitchen_id': kitchen_id, 'idempotency_key': key},
                                     {'menu_photo': 1, 'status': 1})
    if proposal is None:
        return None
    photo = proposal.get('menu_photo') or {}
    return {'fingerprint': photo.get('fingerprint'), 'response': photo.get('response'),
            'proposal': {'proposal_id': proposal['_id'], 'status': proposal['status']}}
