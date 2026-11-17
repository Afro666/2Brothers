from copy import deepcopy
from datetime import timedelta
from unittest.mock import patch

from gateway.tests.test_gateway_app import env, milk, HUMAN, K


def test_old_pending_proposal_is_counted_and_reachable_across_pages(env):
    client, _, db = env
    original = milk(client)
    row = db.proposals.find_one({'_id': original['proposal_id']})
    for i in range(100):
        newer = deepcopy(row)
        newer.update(_id=f'new-{i:03}', idempotency_key=f'new-{i}', status='REJECTED', created_at=row['created_at'] + timedelta(seconds=i + 1))
        db.proposals.insert_one(newer)
    other = deepcopy(row)
    other.update(_id='other-kitchen', kitchen_id='other')
    db.proposals.insert_one(other)
    with patch.object(db.offers, 'find', wraps=db.offers.find) as offers, patch.object(db.products, 'find', wraps=db.products.find) as products:
        first = client.get(K + '/proposals', headers=HUMAN).json()
        assert first['pending_count'] == 1
        assert len(first['proposals']) == 100
        assert offers.call_count == 1
        assert products.call_count == 2  # labels and label-check evidence, batched across the page
    second = client.get(K + '/proposals', params={'cursor': first['next_cursor']}, headers=HUMAN).json()
    assert [p['proposal_id'] for p in second['proposals']] == [original['proposal_id']]
    assert second['next_cursor'] is None
    assert second['pending_count'] == 1
    assert client.get(K + '/proposals?cursor=other-kitchen', headers=HUMAN).status_code == 422


def test_equal_timestamps_use_id_tiebreaker(env):
    client, _, db = env
    original = milk(client)
    row = db.proposals.find_one({'_id': original['proposal_id']})
    db.proposals.delete_many({})
    for i in range(102):
        db.proposals.insert_one({**row, '_id': f'p-{i:03}', 'idempotency_key': f'new-{i}'})
    first = client.get(K + '/proposals', headers=HUMAN).json()
    second = client.get(K + '/proposals', params={'cursor': first['next_cursor']}, headers=HUMAN).json()
    ids = [p['proposal_id'] for p in first['proposals'] + second['proposals']]
    assert len(ids) == len(set(ids)) == 102
