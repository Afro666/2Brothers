"""A person resolves an order whose send result is unknown (#291): placed or not_sent.

Never a resend, never a second attempt row, one resolution per order, all audited.
"""

import pytest

from gateway.tests.test_gateway_app import AGENT, HUMAN, K, env, milk  # noqa: F401  (env is a fixture)
from store import orders


def unconfirmed(client, db, monkeypatch, key="lost"):
    """The attempt row is written, then the approval call fails: the send result is unknown."""
    p = milk(client)
    real = orders.record_attempt

    def write_then_fail(*args, **kwargs):
        real(*args, **kwargs)
        raise RuntimeError("response lost")

    monkeypatch.setattr(orders, "record_attempt", write_then_fail)
    with pytest.raises(RuntimeError):
        client.post(f"{K}/proposals/{p['proposal_id']}/approve", headers=HUMAN,
                    json={"expected_total": p["expected_total"], "idempotency_key": key})
    monkeypatch.setattr(orders, "record_attempt", real)
    order = db.orders.find_one({"idempotency_key": key})
    return p, order["_id"]


def read_failed(client, db, key="read-failed"):
    """It landed at the supplier; only reading the answer failed."""
    p = milk(client)
    r = client.post(f"{K}/proposals/{p['proposal_id']}/approve", headers=HUMAN,
                    json={"expected_total": p["expected_total"], "idempotency_key": key})
    assert r.status_code == 200, r.text
    orders.set_outcome(db, r.json()["order_id"], outcome="SENT_READ_FAILED", status="SENT")
    return p, r.json()["order_id"]


def resolve(client, order_id, headers=HUMAN, **body):
    return client.post(f"{K}/orders/{order_id}/resolve", headers=headers,
                       json={"idempotency_key": "r-1", **body})


def kinds(db, order_id):
    return [e["event"]["kind"] for e in db.audit_log.find({"event.order_id": order_id}).sort("_id", 1)]


def test_a_failed_approval_after_the_attempt_row_is_unconfirmed_and_held(env, monkeypatch):  # noqa: F811
    client, _, db = env
    p, order_id = unconfirmed(client, db, monkeypatch)
    order = db.orders.find_one({"_id": order_id})
    assert (order["outcome"], order["status"]) == ("UNCONFIRMED", None)
    assert db.proposals.find_one({"_id": p["proposal_id"]})["status"] == "COMMITTING"


def test_lookup_returns_what_the_store_knows_and_is_audited(env, monkeypatch):  # noqa: F811
    client, _, db = env
    p, order_id = unconfirmed(client, db, monkeypatch)
    r = client.get(f"{K}/orders/{order_id}/resolution", headers=HUMAN)
    assert r.status_code == 200, r.text
    known = r.json()
    stored = db.orders.find_one({"_id": order_id})
    assert known["order_id"] == order_id and known["proposal_id"] == p["proposal_id"]
    assert known["idempotency_key"] == "lost" and known["payload_hash"] == stored["payload_hash"]
    assert known["outcome"] == "UNCONFIRMED" and known["status"] is None
    assert known["proposal_status"] == "COMMITTING" and known["approved_by"] == "aron"
    assert known["expected_total"] == p["expected_total"] and known["lines"]
    assert known["created_at"] and known["updated_at"]
    assert known["resolvable"] is True and known["resolution"] is None
    assert kinds(db, order_id) == ["order_lookup"]
    entry = db.audit_log.find_one({"event.order_id": order_id})
    assert entry["event"]["actor"] == "aron"


def test_unconfirmed_resolves_to_placed_with_the_supplier_reference(env, monkeypatch):  # noqa: F811
    client, _, db = env
    p, order_id = unconfirmed(client, db, monkeypatch)
    r = resolve(client, order_id, resolution="placed", supplier_order_ref="VAL-123")
    assert r.status_code == 200, r.text
    out = r.json()
    assert (out["outcome"], out["status"], out["proposal_status"]) == ("CONFIRMED", "SENT", "APPROVED")
    assert out["resolution"]["resolution"] == "placed"
    assert out["resolution"]["supplier_order_ref"] == "VAL-123"
    assert out["resolution"]["resolved_by"] == "aron" and out["resolution"]["from_outcome"] == "UNCONFIRMED"
    proposal = db.proposals.find_one({"_id": p["proposal_id"]})
    assert proposal["status"] == "APPROVED" and proposal["order_id"] == order_id
    assert "approving_key" not in proposal
    assert db.orders.count_documents({}) == 1                       # no second attempt row
    assert client.get(f"{K}/orders/{order_id}", headers=HUMAN).json()["outcome"] == "CONFIRMED"
    event = db.audit_log.find_one({"event.kind": "order_resolved"})["event"]
    assert event["actor"] == "aron" and event["order_id"] == order_id
    assert event["resolution"] == "placed" and event["supplier_order_ref"] == "VAL-123"
    assert event["from_outcome"] == "UNCONFIRMED" and event["resolved_at"]
    # The closed proposal cannot place another order.
    again = client.post(f"{K}/proposals/{p['proposal_id']}/approve", headers=HUMAN,
                        json={"expected_total": p["expected_total"], "idempotency_key": "other"})
    assert again.status_code == 409
    assert db.orders.count_documents({}) == 1


def test_unconfirmed_resolves_to_not_sent_and_a_person_can_decide_again(env, monkeypatch):  # noqa: F811
    client, _, db = env
    p, order_id = unconfirmed(client, db, monkeypatch)
    r = resolve(client, order_id, resolution="not_sent", note="sales desk: no such order")
    assert r.status_code == 200, r.text
    out = r.json()
    assert (out["outcome"], out["status"], out["proposal_status"]) == ("NOT_SENT", None, "READY")
    assert out["resolution"]["supplier_order_ref"] is None
    assert db.orders.count_documents({}) == 1
    assert kinds(db, order_id) == ["order_resolved"]
    proposal = client.get(f"{K}/proposals/{p['proposal_id']}", headers=HUMAN).json()
    assert proposal["status"] == "READY" and proposal["order_id"] is None
    # The old key only replays the closed attempt: nothing new is placed.
    old = client.post(f"{K}/proposals/{p['proposal_id']}/approve", headers=HUMAN,
                      json={"expected_total": p["expected_total"], "idempotency_key": "lost"})
    assert old.status_code == 200 and old.json()["outcome"] == "NOT_SENT"
    assert db.orders.count_documents({}) == 1
    # A new human decision, with a new key, places exactly one order.
    new = client.post(f"{K}/proposals/{p['proposal_id']}/approve", headers=HUMAN,
                      json={"expected_total": p["expected_total"], "idempotency_key": "second-decision"})
    assert new.status_code == 200, new.text
    assert new.json()["outcome"] == "CONFIRMED" and new.json()["order_id"] != order_id
    assert db.orders.count_documents({"outcome": "CONFIRMED"}) == 1
    assert db.orders.count_documents({}) == 2
    assert db.proposals.find_one({"_id": p["proposal_id"]})["order_id"] == new.json()["order_id"]


def test_sent_read_failed_resolves_to_not_sent_then_a_new_decision_works(env):  # noqa: F811
    client, _, db = env
    p, order_id = read_failed(client, db)
    first_approval = db.proposals.find_one({"_id": p["proposal_id"]})["approval_id"]
    r = resolve(client, order_id, resolution="not_sent")
    assert r.status_code == 200, r.text
    assert (r.json()["outcome"], r.json()["status"], r.json()["proposal_status"]) == ("NOT_SENT", None, "READY")
    assert r.json()["resolution"]["from_outcome"] == "SENT_READ_FAILED"
    proposal = db.proposals.find_one({"_id": p["proposal_id"]})
    assert proposal["order_id"] is None
    # The used approval stays in the record; a new PENDING one waits for the person.
    assert orders.get_approval(db, first_approval)["status"] == "APPROVED"
    assert proposal["approval_id"] != first_approval
    assert orders.get_approval(db, proposal["approval_id"])["status"] == "PENDING"
    new = client.post(f"{K}/proposals/{p['proposal_id']}/approve", headers=HUMAN,
                      json={"expected_total": p["expected_total"], "idempotency_key": "again"})
    assert new.status_code == 200, new.text
    assert orders.get_approval(db, proposal["approval_id"])["status"] == "APPROVED"
    assert db.orders.count_documents({"outcome": "CONFIRMED"}) == 1
    assert db.orders.count_documents({}) == 2


def test_after_not_sent_the_person_can_also_reject(env):  # noqa: F811
    client, _, db = env
    p, order_id = read_failed(client, db)
    assert resolve(client, order_id, resolution="not_sent").status_code == 200
    r = client.post(f"{K}/proposals/{p['proposal_id']}/reject", headers=HUMAN, json={"reason": "too late"})
    assert r.status_code == 200 and r.json()["status"] == "REJECTED"
    assert db.orders.count_documents({}) == 1


def test_sent_read_failed_resolves_to_placed(env):  # noqa: F811
    client, _, db = env
    p, order_id = read_failed(client, db)
    r = resolve(client, order_id, resolution="placed", supplier_order_ref="VAL-9")
    assert r.status_code == 200, r.text
    assert (r.json()["outcome"], r.json()["proposal_status"]) == ("CONFIRMED", "APPROVED")
    assert db.proposals.find_one({"_id": p["proposal_id"]})["order_id"] == order_id
    assert db.orders.count_documents({}) == 1


def test_not_sent_keeps_a_recall_hold(env, monkeypatch):  # noqa: F811
    client, _, db = env
    p, order_id = unconfirmed(client, db, monkeypatch)
    db.recall_alerts.insert_one({"_id": "recall-1", "kitchen_id": "demo-kitchen",
                                 "product_id": p["lines"][0]["product_id"], "match": "exact"})
    r = resolve(client, order_id, resolution="not_sent")
    assert r.status_code == 200, r.text
    assert r.json()["proposal_status"] == "BLOCKED_BY_RECALL"
    again = client.post(f"{K}/proposals/{p['proposal_id']}/approve", headers=HUMAN,
                        json={"expected_total": p["expected_total"], "idempotency_key": "after-recall"})
    assert again.status_code == 409 and again.json()["error"]["code"] == "BLOCKED_BY_RECALL"
    assert db.orders.count_documents({}) == 1


def test_the_agent_token_and_api_tokens_are_refused(env, monkeypatch):  # noqa: F811
    client, _, db = env
    _, order_id = unconfirmed(client, db, monkeypatch)
    token = client.post(K + "/tokens", headers=HUMAN,
                        json={"name": "pos", "scopes": ["kitchen:read", "kitchen:propose"]}).json()["token"]
    for headers in (AGENT, {"Authorization": f"Bearer {token}"}):
        r = resolve(client, order_id, headers=headers, resolution="placed", supplier_order_ref="VAL-1")
        assert r.status_code == 403 and r.json()["error"]["code"] == "HUMAN_SESSION_REQUIRED"
        r = client.get(f"{K}/orders/{order_id}/resolution", headers=headers)
        assert r.status_code == 403 and r.json()["error"]["code"] == "HUMAN_SESSION_REQUIRED"
    assert client.post(f"{K}/orders/{order_id}/resolve", json={}).status_code == 401
    order = db.orders.find_one({"_id": order_id})
    assert order["outcome"] == "UNCONFIRMED" and "resolution" not in order
    assert kinds(db, order_id) == []


def test_only_an_approver_resolves(env, monkeypatch):  # noqa: F811
    from gateway import users
    client, _, db = env
    _, order_id = unconfirmed(client, db, monkeypatch)
    users.create_user(db, "chef@example.com", "a-long-test-password", name="Chef", role="chef",
                      kitchen_id="demo-kitchen")
    assert client.post("/v1/auth/login", json={"email": "chef@example.com",
                                               "password": "a-long-test-password"}).status_code == 200
    r = client.post(f"{K}/orders/{order_id}/resolve", json={"resolution": "not_sent", "idempotency_key": "c"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "ROLE_REQUIRED"
    assert db.orders.find_one({"_id": order_id})["outcome"] == "UNCONFIRMED"


def test_an_order_in_another_outcome_is_refused(env):  # noqa: F811
    client, _, db = env
    p = milk(client)
    placed = client.post(f"{K}/proposals/{p['proposal_id']}/approve", headers=HUMAN,
                         json={"expected_total": p["expected_total"], "idempotency_key": "ok"}).json()
    for outcome, status in (("CONFIRMED", "SENT"), ("NOT_SENT", None)):
        orders.set_outcome(db, placed["order_id"], outcome=outcome, status=status)
        r = resolve(client, placed["order_id"], resolution="not_sent")
        assert r.status_code == 409, r.text
        assert r.json()["error"]["code"] == "ORDER_NOT_RESOLVABLE"
        assert r.json()["error"]["outcome"] == outcome
    assert "resolution" not in db.orders.find_one({"_id": placed["order_id"]})
    assert db.proposals.find_one({"_id": p["proposal_id"]})["status"] == "APPROVED"
    known = client.get(f"{K}/orders/{placed['order_id']}/resolution", headers=HUMAN).json()
    assert known["resolvable"] is False


def test_an_unknown_order_or_another_kitchens_order_is_not_found(env, monkeypatch):  # noqa: F811
    client, _, db = env
    _, order_id = unconfirmed(client, db, monkeypatch)
    r = resolve(client, "no-such-order", resolution="not_sent")
    assert r.status_code == 404 and r.json()["error"]["code"] == "ORDER_NOT_FOUND"
    other = "/v1/kitchens/other-kitchen"
    r = client.post(f"{other}/orders/{order_id}/resolve", headers=HUMAN,
                    json={"resolution": "not_sent", "idempotency_key": "x"})
    assert r.status_code == 404 and r.json()["error"]["code"] == "ORDER_NOT_FOUND"
    assert client.get(f"{other}/orders/{order_id}/resolution", headers=HUMAN).status_code == 404
    assert db.orders.find_one({"_id": order_id})["outcome"] == "UNCONFIRMED"


@pytest.mark.parametrize("body", [
    {"resolution": "resend"},
    {},
    {"resolution": "placed"},                                       # the reference is required
    {"resolution": "placed", "supplier_order_ref": "   "},
    {"resolution": "placed", "supplier_order_ref": 123},
    {"resolution": "placed", "supplier_order_ref": "x" * 201},
    {"resolution": "not_sent", "supplier_order_ref": "VAL-1"},      # nothing was sent: no reference
    {"resolution": "not_sent", "note": "n" * 501},
    {"resolution": "not_sent", "idempotency_key": ""},
])
def test_a_bad_body_is_refused_and_changes_nothing(env, monkeypatch, body):  # noqa: F811
    client, _, db = env
    _, order_id = unconfirmed(client, db, monkeypatch)
    r = resolve(client, order_id, **body)
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "INVALID_REQUEST"
    order = db.orders.find_one({"_id": order_id})
    assert order["outcome"] == "UNCONFIRMED" and "resolution" not in order


def test_repeating_the_same_resolution_returns_the_stored_result(env, monkeypatch):  # noqa: F811
    client, _, db = env
    p, order_id = unconfirmed(client, db, monkeypatch)
    first = resolve(client, order_id, resolution="placed", supplier_order_ref="VAL-123")
    again = client.post(f"{K}/orders/{order_id}/resolve", headers={**HUMAN, "X-User": "maciek"},
                        json={"resolution": "placed", "supplier_order_ref": " VAL-123 ", "idempotency_key": "r-2"})
    assert again.status_code == 200, again.text
    assert again.json() == first.json()                             # still resolved by aron, at the first time
    assert kinds(db, order_id) == ["order_resolved"]                # one audit entry, not two
    assert db.orders.count_documents({}) == 1


def test_a_conflicting_second_resolution_is_refused(env, monkeypatch):  # noqa: F811
    client, _, db = env
    p, order_id = unconfirmed(client, db, monkeypatch)
    assert resolve(client, order_id, resolution="placed", supplier_order_ref="VAL-123").status_code == 200
    for body in ({"resolution": "not_sent"}, {"resolution": "placed", "supplier_order_ref": "VAL-999"}):
        r = resolve(client, order_id, **body)
        assert r.status_code == 409, r.text
        assert r.json()["error"]["code"] == "ALREADY_RESOLVED"
        assert r.json()["error"]["resolution"]["supplier_order_ref"] == "VAL-123"
    order = db.orders.find_one({"_id": order_id})
    assert order["outcome"] == "CONFIRMED" and order["resolution"]["resolution"] == "placed"
    assert db.proposals.find_one({"_id": p["proposal_id"]})["status"] == "APPROVED"
    assert kinds(db, order_id) == ["order_resolved"]


def test_not_sent_then_placed_is_refused(env):  # noqa: F811
    client, _, db = env
    p, order_id = read_failed(client, db)
    assert resolve(client, order_id, resolution="not_sent").status_code == 200
    r = resolve(client, order_id, resolution="placed", supplier_order_ref="VAL-1")
    assert r.status_code == 409 and r.json()["error"]["code"] == "ALREADY_RESOLVED"
    assert db.orders.find_one({"_id": order_id})["outcome"] == "NOT_SENT"
    assert db.proposals.find_one({"_id": p["proposal_id"]})["status"] == "READY"


def test_a_resolution_that_stopped_halfway_is_finished_by_the_repeat(env, monkeypatch):  # noqa: F811
    from store import audit
    client, _, db = env
    p, order_id = unconfirmed(client, db, monkeypatch)
    real = audit.append_event

    def fail(*args, **kwargs):
        raise RuntimeError("audit write failed")

    monkeypatch.setattr(audit, "append_event", fail)
    with pytest.raises(RuntimeError):
        resolve(client, order_id, resolution="placed", supplier_order_ref="VAL-123")
    monkeypatch.setattr(audit, "append_event", real)
    assert kinds(db, order_id) == []
    r = resolve(client, order_id, resolution="placed", supplier_order_ref="VAL-123")
    assert r.status_code == 200, r.text
    assert kinds(db, order_id) == ["order_resolved"]
    assert db.proposals.find_one({"_id": p["proposal_id"]})["status"] == "APPROVED"
    assert db.orders.count_documents({}) == 1


def test_the_store_claim_is_atomic(env, monkeypatch):  # noqa: F811
    from store.order_resolution import resolve_order
    client, _, db = env
    _, order_id = unconfirmed(client, db, monkeypatch)
    first = resolve_order(db, "demo-kitchen", order_id, outcome="NOT_SENT", status=None,
                          resolution={"resolution": "not_sent"})
    second = resolve_order(db, "demo-kitchen", order_id, outcome="CONFIRMED", status="SENT",
                           resolution={"resolution": "placed"})
    assert first["outcome"] == "NOT_SENT" and first["resolution"] == {"resolution": "not_sent"}
    assert second is None
    assert resolve_order(db, "other-kitchen", order_id, outcome="NOT_SENT", status=None,
                         resolution={"resolution": "not_sent"}) is None
    with pytest.raises(ValueError):
        resolve_order(db, "demo-kitchen", order_id, outcome="UNCONFIRMED", status=None, resolution={})
