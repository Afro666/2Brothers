"""Short-lived product-choice cache. Prices, stock and offers are never cached here."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from uuid import uuid4

from pymongo.errors import DuplicateKeyError


def cache_key(kitchen, need, policy, rows):
    stable = [{k: row.get(k) for k in ('product_id', 'name', 'pack', 'can_arrive', 'alias')} for row in rows]
    payload = [kitchen, ' '.join(need['text'].casefold().split()), need['requested_date'], need['quantity'],
               need['unit'], sorted(policy or []), sorted(stable, key=lambda r: r['product_id'])]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def get(db, key, now=None):
    now = now or datetime.now(timezone.utc)
    row = db.buyer_pick_cache.find_one({'_id': key, 'state': 'READY', 'expires_at': {'$gt': now}})
    return row.get('product_ids') if row else None


def claim(db, key, now=None):
    now = now or datetime.now(timezone.utc)
    token = uuid4().hex
    try:
        result = db.buyer_pick_cache.update_one({'_id': key, 'expires_at': {'$lte': now}}, {'$set': {
            'state': 'RUNNING', 'token': token, 'expires_at': now + timedelta(seconds=30)}}, upsert=True)
    except DuplicateKeyError:
        return None
    return token if result.modified_count or result.upserted_id else None


def finish(db, key, token, product_ids, now=None):
    now = now or datetime.now(timezone.utc)
    db.buyer_pick_cache.update_one({'_id': key, 'token': token, 'state': 'RUNNING'}, {'$set': {
        'state': 'READY' if product_ids else 'FAILED', 'product_ids': product_ids,
        'expires_at': now + timedelta(seconds=600 if product_ids else 5)}})
