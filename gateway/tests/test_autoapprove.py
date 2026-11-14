"""Earned auto-approve (#299): off by default, earned from decisions, never for risky orders."""

from datetime import timedelta

from gateway.tests.test_gateway_app import AGENT, HUMAN, K, NOW, env  # noqa: F401 (fixture)

ROUTINE = {"product_ids": ["462775"], "quantity": "40", "unit": "L", "requested_date": "2026-11-16"}


def history(db, *, weeks=5, decisions=24, edited=0, orders_with_product=4):
    """A kitchen that has decided `decisions` proposals over `weeks` weeks."""
    db.products.update_one({"_id": "462775"}, {"$set": {"allergen_data_known": True}})
    for i in range(decisions):
        when = NOW - timedelta(weeks=weeks) + timedelta(hours=i)
        db.approvals.insert_one({"_id": f"a{i}", "kitchen_id": "demo-kitchen", "idempotency_key": f"h{i}",
                                 "status": "APPROVED", "decided_by": "aron", "decided_at": when})
        db.proposals.insert_one({"_id": f"hp{i}", "kitchen_id": "demo-kitchen", "idempotency_key": f"hp{i}",
                                 "approval_id": f"a{i}", "status": "APPROVED"})
        if i < edited:
            db.feedback.insert_one({"meta": {"kitchen_id": "demo-kitchen", "product_id": "999"},
                                    "proposal_id": f"hp{i}", "kind": "qty_changed"})
        if i < orders_with_product:
            db.orders.insert_one({"_id": f"o{i}", "kitchen_id": "demo-kitchen", "idempotency_key": f"o{i}",
                                  "outcome": "CONFIRMED", "approved_by": "aron", "proposal_id": f"hp{i}",
                                  "lines": [{"product_id": "462775"}]})


def propose(client, key, **changes):
    r = client.post(K + "/proposals", headers=AGENT, json={**ROUTINE, **changes, "idempotency_key": key})
    assert r.status_code == 200, r.text
    return r.json()


def switch_on(client, limit="500"):
    return client.put(K + "/auto-approve", headers=HUMAN, json={"enabled": True, "limit_eur": limit})


def test_off_by_default_and_cannot_be_switched_on_before_the_learning_period(env):
    client, _, db = env
    status = client.get(K + "/auto-approve", headers=AGENT).json()
    assert status["enabled"] is False and status["learning"]["learning_done"] is False
    r = switch_on(client)
    assert r.status_code == 409 and r.json()["error"]["code"] == "LEARNING_PERIOD"
    assert propose(client, "p1")["status"] == "READY"
    history(db, weeks=5, decisions=24, edited=6)          # 25% edited: not learned yet
    assert switch_on(client).status_code == 409


def test_only_an_approver_switches_it_and_the_limit_is_bounded(env):
    client, _, db = env
    history(db)
    r = client.put(K + "/auto-approve", headers=AGENT, json={"enabled": True, "limit_eur": "500"})
    assert r.status_code == 403
    assert switch_on(client, "999999").status_code == 422
    assert switch_on(client, "0").status_code == 422
    assert switch_on(client).json()["enabled"] is True


def test_routine_order_is_approved_with_evidence_in_the_audit_log(env):
    client, _, db = env
    history(db)
    assert switch_on(client).status_code == 200
    p = propose(client, "p1")
    assert p["status"] == "APPROVED" and p["order_id"]
    order = db.orders.find_one({"_id": p["order_id"]})
    assert order["approved_by"] == "auto-approve (rule set by aron)"
    events = client.get(K + "/audit", headers=AGENT).json()["events"]
    auto = [e for e in events if e["kind"] == "auto_approved"][0]
    assert auto["evidence"]["weeks"] >= 4 and auto["evidence"]["decisions"] >= 20
    assert [e["kind"] for e in events].count("order_placed") == 1


def test_never_cases_still_wait_for_a_person(env):
    client, fake, db = env
    history(db)
    switch_on(client, "100")
    assert propose(client, "over-limit")["status"] == "READY"            # 116.68 > 100
    switch_on(client, "2000")
    assert propose(client, "unknown-stock", product_ids=["463335"], quantity="10")["status"] == "READY"
    assert propose(client, "short", quantity="60")["status"] == "READY"   # only 51 confirmed
    assert propose(client, "excluded", product_ids=["462775", "462921"])["status"] == "READY"
    db.orders.delete_many({"kitchen_id": "demo-kitchen", "_id": {"$in": ["o1", "o2", "o3"]}})
    assert propose(client, "new-product")["status"] == "READY"            # fewer than 3 approved orders
    assert db.orders.count_documents({"approved_by": {"$regex": "^auto"}}) == 0


def test_auto_approvals_do_not_count_as_learning_and_switching_off_is_instant(env):
    client, _, db = env
    history(db)
    switch_on(client)
    before = client.get(K + "/auto-approve", headers=AGENT).json()["learning"]["decisions"]
    assert propose(client, "p1")["status"] == "APPROVED"
    assert client.get(K + "/auto-approve", headers=AGENT).json()["learning"]["decisions"] == before
    off = client.put(K + "/auto-approve", headers=HUMAN, json={"enabled": False})
    assert off.status_code == 200 and off.json()["enabled"] is False
    assert propose(client, "p2", quantity="5")["status"] == "READY"
