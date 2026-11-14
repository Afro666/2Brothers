"""Learning rows from a change or a human decision (#1302): reason, note and context."""

from decimal import Decimal

from gateway.tests.test_autoapprove import ROUTINE, history, switch_on
from gateway.tests.test_change_proposal import change
from gateway.tests.test_gateway_app import AGENT, HUMAN, K, env, milk  # noqa: F401 (fixture)
from gateway.tests.test_plan_proposal import WINDOW, setup
from store.feedback import changes_for


def approve(client, p, key="a1"):
    return client.post(f"{K}/proposals/{p['proposal_id']}/approve", headers=HUMAN,
                       json={"expected_total": p["expected_total"], "idempotency_key": key})


def reject(client, p, reason="Too much milk for a short week", key="r1"):
    return client.post(f"{K}/proposals/{p['proposal_id']}/reject", headers=HUMAN,
                       json={"reason": reason, "idempotency_key": key})


def token(client, scopes):
    r = client.post(K + "/tokens", headers=HUMAN, json={"name": "claude", "scopes": scopes})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def decision_rows(db, p, kind):
    return list(db.feedback.find({"proposal_id": p["proposal_id"], "kind": kind}))


def test_a_reason_and_note_are_validated_before_the_proposal_changes(env):
    client, _, db = env
    p = milk(client, quantity="51")
    bad = [
        {"product_id": "462775", "quantity": "40", "reason": "WRONG"},
        {"product_id": "462775", "quantity": "40", "note": "because"},
        {"product_id": "462775", "quantity": "40", "reason": "OTHER", "note": "x" * 201},
        {"product_id": "462775", "quantity": "40", "reason": "OTHER", "note": 5},
    ]
    for i, entry in enumerate(bad):
        r = change(client, p, lines=[entry], key=f"bad{i}")
        assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_REQUEST", r.text
    assert db.feedback.count_documents({}) == 0

    ok = change(client, p, lines=[{"product_id": "462775", "quantity": "40", "reason": "OTHER",
                                   "note": "y" * 200}], key="ok")
    assert ok.status_code == 200, ok.text
    row = db.feedback.find_one({"proposal_id": p["proposal_id"]})
    assert (row["reason"], row["note"]) == ("OTHER", "y" * 200)


def test_the_idempotency_payload_covers_reason_and_note(env):
    client, _, db = env
    p = milk(client, quantity="51")
    first = change(client, p, lines=[{"product_id": "462775", "quantity": "40",
                                      "reason": "TOO_MUCH"}], key="same")
    assert first.status_code == 200, first.text
    assert len(list(db.feedback.find({"proposal_id": p["proposal_id"]}))) == 1

    again = change(client, p, lines=[{"product_id": "462775", "quantity": "40",
                                      "reason": "TOO_MUCH"}], key="same")
    assert again.status_code == 200 and again.json()["offer_id"] == first.json()["offer_id"]
    assert len(list(db.feedback.find({"proposal_id": p["proposal_id"]}))) == 1

    other = change(client, p, lines=[{"product_id": "462775", "quantity": "40",
                                      "reason": "TOO_LITTLE"}], key="same")
    assert other.status_code == 409 and other.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"

    absent = change(client, p, lines=[{"product_id": "462775", "quantity": "30"}], key="nulls")
    explicit = change(client, p, lines=[{"product_id": "462775", "quantity": "30",
                                         "reason": None, "note": None}], key="nulls")
    assert absent.status_code == 200 and explicit.status_code == 200
    assert explicit.json()["offer_id"] == absent.json()["offer_id"]
    assert len(list(db.feedback.find({"proposal_id": p["proposal_id"]}))) == 2


def test_an_agent_or_a_token_change_writes_no_feedback(env):
    client, _, db = env
    p = milk(client, quantity="51")
    r = change(client, p, lines=[{"product_id": "462775", "quantity": "40", "reason": "TOO_MUCH"}],
               key="agent", headers=AGENT)
    assert r.status_code == 200, r.text
    assert db.feedback.count_documents({}) == 0

    propose_token = token(client, ["kitchen:read", "kitchen:propose"])
    p2 = milk(client, key="p2", quantity="51")
    r = change(client, p2, lines=[{"product_id": "462775", "quantity": "40"}],
               key="token", headers=propose_token)
    assert r.status_code == 200, r.text
    assert db.feedback.count_documents({}) == 0


def test_context_is_server_read_and_client_context_is_ignored(env):
    client, _, db = env
    p = milk(client, quantity="51")
    r = change(client, p, lines=[{"product_id": "462775", "quantity": "40", "reason": "TOO_MUCH",
                                  "context": {"forecast_need": "999", "offer_id": "fake"}}], key="ctx")
    assert r.status_code == 200, r.text
    row = changes_for(db, "demo-kitchen", product_id="462775")[0]
    assert row["reason"] == "TOO_MUCH" and row["note"] is None
    assert row["context"] == {"forecast_need": None, "stock_position": None, "covers": None,
                              "requested_date": "2026-11-16", "made_by": "request",
                              "offer_id": p["offer_id"]}
    assert row["outcome"] == {"next_count_at": None, "next_count": None, "ran_out": None}


def test_a_plan_proposal_stores_the_unlearned_forecast_need(env):
    client, _, db = env
    setup(client, [{"product_id": "462775", "on_hand": "5", "unit": "L"}])
    p = client.post(K + "/proposals", headers=AGENT,
                    json={**WINDOW, "idempotency_key": "plan-feedback"}).json()
    assert p["request"]["needs"][0]["quantity"] == "20"
    r = change(client, p, lines=[{"product_id": "462775", "quantity": "15", "reason": "TOO_MUCH"}],
               key="plan-change")
    assert r.status_code == 200, r.text
    ctx = changes_for(db, "demo-kitchen", product_id="462775")[0]["context"]
    assert (ctx["forecast_need"], ctx["made_by"]) == ("20", "menu_plan")
    assert ctx["requested_date"] == "2026-11-16" and ctx["offer_id"] == p["offer_id"]


def test_approve_writes_one_human_row_and_an_idempotent_repeat_keeps_it_one(env):
    client, _, db = env
    p = milk(client, quantity="51")
    first = approve(client, p, key="a1")
    assert first.status_code == 200, first.text
    rows = decision_rows(db, p, "approved")
    assert len(rows) == 1 and rows[0]["user"] == "aron"
    assert Decimal(str(rows[0]["total"])) == Decimal(p["expected_total"])
    again = approve(client, p, key="a1")
    assert again.status_code == 200
    assert len(decision_rows(db, p, "approved")) == 1


def test_a_personal_approval_token_writes_its_person_as_the_user(env):
    from gateway.tests.test_approval_tokens import personal

    client, _, db = env
    _, headers = personal(client, db)
    p = milk(client, quantity="51")
    r = client.post(f"{K}/proposals/{p['proposal_id']}/approve", headers=headers,
                    json={"expected_total": p["expected_total"], "idempotency_key": "chat-yes"})
    assert r.status_code == 200, r.text
    rows = decision_rows(db, p, "approved")
    assert len(rows) == 1 and rows[0]["user"] == "aron@example.com"


def test_reject_writes_one_row_with_its_free_text_and_total(env):
    client, _, db = env
    p = milk(client, quantity="51")
    first = reject(client, p)
    assert first.status_code == 200, first.text
    rows = decision_rows(db, p, "rejected")
    assert len(rows) == 1 and rows[0]["reason"] == "Too much milk for a short week"
    assert Decimal(str(rows[0]["total"])) == Decimal(p["expected_total"])
    assert reject(client, p).status_code == 200
    assert len(decision_rows(db, p, "rejected")) == 1


def test_auto_approval_writes_no_human_decision_row(env):
    client, _, db = env
    history(db)
    switch_on(client)
    p = client.post(K + "/proposals", headers=AGENT,
                    json={**ROUTINE, "idempotency_key": "auto-feedback"}).json()
    assert p["status"] == "APPROVED"
    assert decision_rows(db, p, "approved") == []


def test_feedback_failure_never_fails_an_approval(env, monkeypatch):
    client, _, db = env

    def boom(*args, **kwargs):
        raise RuntimeError("feedback store is down")

    monkeypatch.setattr("store.feedback.record_feedback", boom)
    p = milk(client, quantity="51")
    r = approve(client, p, key="a1")
    assert r.status_code == 200, r.text
    assert r.json()["order_id"] and db.orders.count_documents({}) == 1
    assert db.feedback.count_documents({}) == 0


def test_a_second_change_still_measures_against_the_engines_original_quantity(env):
    """The unlearned base never becomes the person's own earlier edit (#1309 lesson): a second
    change of a plan line keeps forecast_need at the engine's quantity from the original offer."""
    client, _, db = env
    setup(client, [{"product_id": "462775", "on_hand": "5", "unit": "L"}])
    p = client.post(K + "/proposals", headers=AGENT,
                    json={**WINDOW, "idempotency_key": "plan-twice"}).json()
    first = change(client, p, lines=[{"product_id": "462775", "quantity": "15", "reason": "TOO_MUCH"}],
                   key="twice-1")
    assert first.status_code == 200, first.text
    second = change(client, first.json(), lines=[{"product_id": "462775", "quantity": "10", "reason": "TOO_MUCH"}],
                    key="twice-2")
    assert second.status_code == 200, second.text
    rows = changes_for(db, "demo-kitchen", product_id="462775")
    assert [(r["from_qty"], r["to_qty"], r["context"]["forecast_need"]) for r in rows] == [
        ("20", "15", "20"), ("15", "10", "20")]
    assert db.proposals.find_one({"_id": p["proposal_id"]})["original_offer_id"] == p["offer_id"]
