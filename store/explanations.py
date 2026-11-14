"""Durable language/revision cache and bounded explanation claims; no model text in audit."""
from datetime import timedelta
import hashlib
import json
from uuid import uuid4

from pymongo.errors import DuplicateKeyError


def key(kitchen, proposal, source, language):
    return hashlib.sha256(json.dumps([kitchen, proposal, source, language]).encode()).hexdigest()


def cached(db, kitchen, proposal, source, language):
    row = db.proposal_explanations.find_one({'_id': key(kitchen, proposal, source, language), 'state': 'ready'})
    return row.get('result') if row else None


def claim(db, kitchen, proposal, source, language, now):
    ident = key(kitchen, proposal, source, language)
    row = db.proposal_explanations.find_one({'_id': ident})
    if row and (row['state'] == 'ready' or row['retry_at'] > now):
        return None
    budget = 'budget:' + hashlib.sha256(kitchen.encode()).hexdigest()
    token = uuid4().hex
    try:
        slot = db.proposal_explanation_limits.update_one({'_id': budget,
            'next_attempt': {'$lte': now}, 'busy_until': {'$lte': now}}, {'$set': {
                'token': token, 'next_attempt': now + timedelta(seconds=30),
                'busy_until': now + timedelta(seconds=45)}}, upsert=True)
    except DuplicateKeyError:
        return None
    if not (slot.modified_count or slot.upserted_id):
        return None
    db.proposal_explanations.update_one({'_id': ident}, {'$set': {'state': 'running', 'token': token,
        'retry_at': now + timedelta(seconds=45)}}, upsert=True)
    return {'key': ident, 'budget': budget, 'token': token}


def finish(db, lease, result, now):
    db.proposal_explanations.update_one({'_id': lease['key'], 'token': lease['token']}, {'$set': {
        'state': 'ready' if result else 'failed', 'result': result,
        'retry_at': now + timedelta(minutes=5)}})
    db.proposal_explanation_limits.update_one({'_id': lease['budget'], 'token': lease['token']},
                                             {'$set': {'busy_until': now}})
