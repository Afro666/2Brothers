"""A proposal whose approval row write failed is staged PENDING and repaired on replay.

A crash between storing the proposal and storing its approval row must never leave a
READY proposal with no approval row: a person could otherwise approve something the
inbox never asked them to decide. The replay of the same idempotency key finishes the
staged proposal, using the approval row's own idempotency key.
"""

import pytest

from gateway import service
from gateway.tests.test_gateway_app import AGENT, HUMAN, K, env, milk  # noqa: F401


def _proposal_row(db, key):
    return db.proposals.find_one({"kitchen_id": "demo-kitchen", "idempotency_key": key})


def _approval_rows(db, proposal_id):
    return list(db.approvals.find({"idempotency_key": f"proposal:{proposal_id}"}))


def _fail_request_approval_once(monkeypatch):
    real = service.orders.request_approval
    calls = {"n": 0}

    def fail_once(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("approval storage failed")
        return real(*args, **kwargs)

    monkeypatch.setattr(service.orders, "request_approval", fail_once)
    return calls


def test_proposal_replay_finishes_a_pending_proposal(env, monkeypatch):
    client, _, db = env
    _fail_request_approval_once(monkeypatch)

    with pytest.raises(RuntimeError, match="approval storage failed"):
        milk(client, key="staged-proposal")

    row = _proposal_row(db, "staged-proposal")
    assert row["status"] == "PENDING"
    assert row["approval_id"] is None
    assert _approval_rows(db, row["_id"]) == []
    pending = client.get(f"{K}/proposals/{row['_id']}", headers=HUMAN)
    assert pending.status_code == 200
    refused = client.post(f"{K}/proposals/{row['_id']}/approve", headers=HUMAN,
                          json={"expected_total": pending.json()["expected_total"],
                                "idempotency_key": "approve-staged"})
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "NOT_PENDING"

    replayed = milk(client, key="staged-proposal")
    assert replayed["proposal_id"] == row["_id"]
    assert replayed["status"] == "READY"
    assert replayed["approval_id"]
    rows = _approval_rows(db, row["_id"])
    assert len(rows) == 1
    assert rows[0]["_id"] == replayed["approval_id"]
    assert rows[0]["status"] == "PENDING"

    approved = client.post(f"{K}/proposals/{row['_id']}/approve", headers=HUMAN,
                           json={"expected_total": replayed["expected_total"],
                                 "idempotency_key": "approve-replayed"})
    assert approved.status_code == 200, approved.text


def test_normal_proposal_is_ready_with_one_approval_row(env):
    client, _, db = env
    proposal = milk(client, key="normal-proposal")
    assert proposal["status"] == "READY"
    assert proposal["approval_id"]
    rows = _approval_rows(db, proposal["proposal_id"])
    assert len(rows) == 1
    assert rows[0]["_id"] == proposal["approval_id"]


def test_tool_request_approval_replay_finishes_a_pending_proposal(env, monkeypatch):
    client, _, db = env
    need = client.post(K + "/needs", headers=AGENT, json={
        "quantity": "60", "unit": "L", "requested_date": "2026-11-16"}).json()
    offer = client.post("/tools/get_offer", headers=AGENT, json={
        "need_id": need["need_id"], "product_ids": ["462775"]}).json()
    _fail_request_approval_once(monkeypatch)

    body = {"offer_id": offer["offer_id"], "idempotency_key": "staged-tool-request"}
    with pytest.raises(RuntimeError, match="approval storage failed"):
        client.post("/tools/request_approval", headers=AGENT, json=body)

    row = _proposal_row(db, "staged-tool-request")
    assert row["status"] == "PENDING"
    assert row["approval_id"] is None
    assert _approval_rows(db, row["_id"]) == []
    refused = client.post(f"{K}/proposals/{row['_id']}/approve", headers=HUMAN,
                          json={"expected_total": offer["expected_total"],
                                "idempotency_key": "approve-staged-tool"})
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "NOT_PENDING"

    replayed = client.post("/tools/request_approval", headers=AGENT, json=body)
    assert replayed.status_code == 200, replayed.text
    assert replayed.json()["proposal_id"] == row["_id"]
    assert replayed.json()["approval_id"]
    repaired = db.proposals.find_one({"_id": row["_id"]})
    assert repaired["status"] == "READY"
    assert repaired["approval_id"] == replayed.json()["approval_id"]
    rows = _approval_rows(db, row["_id"])
    assert len(rows) == 1
    assert rows[0]["_id"] == replayed.json()["approval_id"]

    approved = client.post(f"{K}/proposals/{row['_id']}/approve", headers=HUMAN,
                           json={"expected_total": offer["expected_total"],
                                 "idempotency_key": "approve-replayed-tool"})
    assert approved.status_code == 200, approved.text
