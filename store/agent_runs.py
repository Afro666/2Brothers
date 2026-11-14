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


USAGE_SUMS = ('calls', 'prompt_tokens', 'completion_tokens', 'reasoning_tokens')


def _count(value):
    """A stored count, or 0 when it is missing or is not a whole number of 0 or more."""
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _seconds(value):
    ok = isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value < float('inf')
    return float(value) if ok else 0.0


def usage_totals(db, kitchen_id):
    """What the Buyer's model used for this kitchen (#365): the sum of `result.buyer_usage`
    over its runs. A run without usage (from before the meter, not finished, or ended
    without a proposal) is counted in `runs_without_usage` and adds nothing to the sums.
    `since` is when the oldest counted run started, `last_run_at` when the newest one
    finished; both None when no run is counted."""
    out = {'runs': 0, 'finished_runs': 0, 'runs_without_usage': 0, 'seconds': 0.0,
           'since': None, 'last_run_at': None, **dict.fromkeys(USAGE_SUMS, 0)}
    rows = db.agent_runs.find({'kitchen_id': kitchen_id},
                              {'state': 1, 'created_at': 1, 'finished_at': 1, 'result.buyer_usage': 1})
    for row in rows:
        out['runs'] += 1
        out['finished_runs'] += row.get('state') == 'READY'
        result = row.get('result')
        usage = result.get('buyer_usage') if isinstance(result, dict) else None
        if not isinstance(usage, dict):
            out['runs_without_usage'] += 1
            continue
        for field in USAGE_SUMS:
            out[field] += _count(usage.get(field))
        out['seconds'] += _seconds(usage.get('seconds'))
        started, finished = row.get('created_at'), row.get('finished_at')
        if isinstance(started, datetime) and (out['since'] is None or started < out['since']):
            out['since'] = started
        if isinstance(finished, datetime) and (out['last_run_at'] is None or finished > out['last_run_at']):
            out['last_run_at'] = finished
    return out
