"""Replay metadata on a menu-photo proposal; images are never persisted."""
import hashlib
import json


def _key(kitchen_id, key):
    return hashlib.sha256(json.dumps([kitchen_id, key]).encode()).hexdigest()


def cached_result(db, kitchen_id, key):
    proposal = db.proposals.find_one({'kitchen_id': kitchen_id, 'idempotency_key': key},
                                     {'menu_photo': 1, 'status': 1})
    if proposal is None:
        return db.menu_photo_results.find_one({'_id': _key(kitchen_id, key)}, {'_id': 0})
    photo = proposal.get('menu_photo') or {}
    return {'fingerprint': photo.get('fingerprint'), 'response': photo.get('response'),
            'proposal': {'proposal_id': proposal['_id'], 'status': proposal['status']}}


def remember_empty_result(db, kitchen_id, key, fingerprint, response):
    """A successful no-proposal read also consumes its key; no image is stored."""
    db.menu_photo_results.update_one({'_id': _key(kitchen_id, key)}, {'$setOnInsert': {
        'fingerprint': fingerprint, 'response': response, 'proposal': None}}, upsert=True)
    return cached_result(db, kitchen_id, key)
