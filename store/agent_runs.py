"""Durable deduplication for bounded Buyer jobs; database access stays in store."""
from datetime import datetime, timezone
import hashlib
import json

from pymongo.errors import DuplicateKeyError
from store.orders import IdempotencyConflict


def claim(db, kitchen_id, key, payload):
    run_id = hashlib.sha256(json.dumps([kitchen_id, key]).encode()).hexdigest()
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    row = {'_id': run_id, 'kitchen_id': kitchen_id, 'payload_hash': digest,
           'state': 'RUNNING', 'created_at': datetime.now(timezone.utc)}
    try:
        db.agent_runs.insert_one(row)
        return row, True
    except DuplicateKeyError:
        row = db.agent_runs.find_one({'_id': run_id, 'kitchen_id': kitchen_id})
        if row['payload_hash'] != digest:
            raise IdempotencyConflict('Buyer request key reused') from None
        return row, False


def finish(db, run_id, *, state, result):
    db.agent_runs.update_one({'_id': run_id, 'state': 'RUNNING'}, {'$set': {
        'state': state, 'result': result, 'finished_at': datetime.now(timezone.utc)}})
