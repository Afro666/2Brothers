"""#715: a proposal never stays COMMITTING without an order attempt, even when the
rollback after a failed send cannot write."""

import concurrent.futures
from datetime import timedelta
import threading

import mongomock
import pytest

from gateway.tests.test_gateway_app import HUMAN, K, NOW, env, milk  # noqa: F401  (env is a fixture)
from store import orders


def test_a_failed_rollback_write_is_audited_and_a_later_approve_releases_it(env, monkeypatch):  # noqa: F811
    client, _, db = env
    p = milk(client)
    real_attempt, real_update = orders.record_attempt, mongomock.collection.Collection.update_one
    down = {"on": False}

    def fail(*args, **kwargs):
        down["on"] = True          # from here on the database refuses proposal writes
        raise RuntimeError("write failed")

    def update_one(self, *args, **kwargs):
        if down["on"] and self.name == "proposals":
            raise RuntimeError("database down")
        return real_update(self, *args, **kwargs)

    monkeypatch.setattr(orders, "record_attempt", fail)
    monkeypatch.setattr(mongomock.collection.Collection, "update_one", update_one)
    body = {"expected_total": p["expected_total"], "idempotency_key": "stuck"}
    url = f"{K}/proposals/{p['proposal_id']}/approve"
    with pytest.raises(RuntimeError, match="write failed"):
        client.post(url, headers=HUMAN, json=body)
    down["on"] = False
    monkeypatch.setattr(orders, "record_attempt", real_attempt)

    assert db.proposals.find_one({"_id": p["proposal_id"]})["status"] == "COMMITTING"
    assert db.orders.count_documents({}) == 0
    assert db.audit_log.find_one({"event.kind": "approve_rollback_failed"}) is not None

    # Inside the in-flight window it is not released: it may still be a live approval.
    assert client.post(url, headers=HUMAN, json=body).status_code == 409

    db.proposals.update_one({"_id": p["proposal_id"]}, {"$set": {"committing_at": NOW - timedelta(minutes=5)}})
    r = client.post(url, headers=HUMAN, json=body)
    assert r.status_code == 200, r.text
    assert db.proposals.find_one({"_id": p["proposal_id"]})["status"] == "APPROVED"
    assert db.orders.count_documents({}) == 1
    assert db.audit_log.find_one({"event.kind": "stuck_commit_released"}) is not None


def test_a_committing_claim_with_an_attempt_row_is_never_released(env, monkeypatch):  # noqa: F811
    client, _, db = env
    p = milk(client)
    real = orders.record_attempt

    def write_then_fail(*args, **kwargs):
        real(*args, **kwargs)
        raise RuntimeError("response lost")

    monkeypatch.setattr(orders, "record_attempt", write_then_fail)
    body = {"expected_total": p["expected_total"], "idempotency_key": "lost"}
    url = f"{K}/proposals/{p['proposal_id']}/approve"
    with pytest.raises(RuntimeError):
        client.post(url, headers=HUMAN, json=body)
    monkeypatch.setattr(orders, "record_attempt", real)
    db.proposals.update_one({"_id": p["proposal_id"]}, {"$set": {"committing_at": NOW - timedelta(minutes=5)}})
    body["idempotency_key"] = "other"
    assert client.post(url, headers=HUMAN, json=body).status_code == 409
    assert db.proposals.find_one({"_id": p["proposal_id"]})["status"] == "COMMITTING"
    assert db.orders.count_documents({}) == 1


def test_a_stale_worker_that_resumes_after_its_claim_was_released_places_no_second_order(env, monkeypatch):  # noqa: F811
    client, _, db = env
    p = milk(client)
    entered, release = threading.Event(), threading.Event()
    real = orders.record_attempt

    def record(*a, **kw):
        if kw['idempotency_key'] == 'slow-key':
            entered.set()
            assert release.wait(8)
        return real(*a, **kw)

    monkeypatch.setattr('gateway.service.orders.record_attempt', record)
    url = f"{K}/proposals/{p['proposal_id']}/approve"

    def approve(key):
        return client.post(url, headers=HUMAN,
                           json={'idempotency_key': key, 'expected_total': p['expected_total']})

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(approve, 'slow-key')
        assert entered.wait(4)
        try:
            db.proposals.update_one({'_id': p['proposal_id']},
                                    {'$set': {'committing_at': NOW - timedelta(seconds=120)}})
            second = approve('second-key')
        finally:
            release.set()
        first_response = first.result()

    assert second.status_code == 200
    assert first_response.status_code == 409
    assert db.orders.count_documents({'proposal_id': p['proposal_id']}) == 1
    order = db.orders.find_one({'proposal_id': p['proposal_id']})
    assert order['outcome'] == 'CONFIRMED'
    assert order['idempotency_key'] == 'second-key'
    proposal = db.proposals.find_one({'_id': p['proposal_id']})
    assert proposal['status'] == 'APPROVED'
    assert proposal['order_id'] == order['_id']
    assert db.audit_log.find_one({'event.kind': 'superseded_commit_discarded'}) is not None


def test_an_approval_key_of_another_proposal_is_refused_and_leaves_the_proposal_ready(env):  # noqa: F811
    client, _, db = env
    a = milk(client, key='proposal-a')
    b = milk(client, key='proposal-b')
    a_url = K + '/proposals/' + a['proposal_id'] + '/approve'
    b_url = K + '/proposals/' + b['proposal_id'] + '/approve'

    r = client.post(a_url, headers=HUMAN,
                    json={'expected_total': a['expected_total'], 'idempotency_key': 'same-key'})
    assert r.status_code == 200, r.text

    r = client.post(b_url, headers=HUMAN,
                    json={'expected_total': b['expected_total'], 'idempotency_key': 'same-key'})
    assert r.status_code == 409, r.text
    assert r.json()['error']['code'] == 'IDEMPOTENCY_CONFLICT'
    assert db.proposals.find_one({'_id': b['proposal_id']})['status'] == 'READY'
    assert db.orders.count_documents({'proposal_id': b['proposal_id']}) == 0

    r = client.post(b_url, headers=HUMAN,
                    json={'expected_total': b['expected_total'], 'idempotency_key': 'b-key'})
    assert r.status_code == 200, r.text
    assert db.orders.count_documents({'proposal_id': b['proposal_id']}) == 1


def test_a_stranded_claim_of_another_proposals_key_is_released_after_the_stale_window(env):  # noqa: F811
    client, _, db = env
    a = milk(client, key='proposal-a')
    b = milk(client, key='proposal-b')
    r = client.post(K + '/proposals/' + a['proposal_id'] + '/approve', headers=HUMAN,
                    json={'expected_total': a['expected_total'], 'idempotency_key': 'same-key'})
    assert r.status_code == 200, r.text
    db.proposals.update_one({'_id': b['proposal_id']}, {'$set': {
        'status': 'COMMITTING', 'approving_key': 'same-key',
        'committing_at': NOW - timedelta(minutes=5)}})

    r = client.post(K + '/proposals/' + b['proposal_id'] + '/approve', headers=HUMAN,
                    json={'expected_total': b['expected_total'], 'idempotency_key': 'new-key'})
    assert r.status_code == 200, r.text
    assert db.proposals.find_one({'_id': b['proposal_id']})['status'] == 'APPROVED'
    order = db.orders.find_one({'proposal_id': b['proposal_id']})
    assert order is not None
    assert order['idempotency_key'] == 'new-key'
    assert db.audit_log.find_one({'event.kind': 'stuck_commit_released'}) is not None


def test_a_key_conflict_inside_place_releases_the_claim(env, monkeypatch):  # noqa: F811
    client, _, db = env
    a = milk(client, key='proposal-a')
    b = milk(client, key='proposal-b')
    r = client.post(K + '/proposals/' + a['proposal_id'] + '/approve', headers=HUMAN,
                    json={'expected_total': a['expected_total'], 'idempotency_key': 'same-key'})
    assert r.status_code == 200, r.text

    real = orders.attempt_for_key
    calls = {'n': 0}

    def miss_once(*args, **kwargs):
        calls['n'] += 1
        if calls['n'] == 1:
            return None
        return real(*args, **kwargs)

    monkeypatch.setattr('gateway.service.orders.attempt_for_key', miss_once)
    r = client.post(K + '/proposals/' + b['proposal_id'] + '/approve', headers=HUMAN,
                    json={'expected_total': b['expected_total'], 'idempotency_key': 'same-key'})
    assert r.status_code == 409, r.text
    assert r.json()['error']['code'] == 'IDEMPOTENCY_CONFLICT'
    assert db.proposals.find_one({'_id': b['proposal_id']})['status'] == 'READY'
