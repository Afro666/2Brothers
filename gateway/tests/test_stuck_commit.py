"""#715: a proposal never stays COMMITTING without an order attempt, even when the
rollback after a failed send cannot write."""

from datetime import timedelta

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
