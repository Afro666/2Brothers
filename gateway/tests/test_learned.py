"""Learned facts (#1305-#1307): computed from a kitchen's changes and deliveries."""

from datetime import date, datetime, timedelta, timezone

from gateway.tests.test_gateway_app import AGENT, HUMAN, K, NOW, env  # noqa: F401 (fixture)
from gateway.tests.test_plan_proposal import PLAN, setup  # noqa: F401 (setup helper)
from store.delivery_results import save_observation
from store.feedback import record_feedback

OLD = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)


def seed_corrections(db, product_id="462775", kitchen_id="demo-kitchen"):
    """Three approved TOO_MUCH changes against an unlearned 40, each correcting to 20."""
    for number in range(3):
        proposal_id = f"history-{number}"
        record_feedback(db, kitchen_id, proposal_id, [{
            "kind": "qty_changed", "product_id": product_id, "from_qty": "40",
            "to_qty": "20", "unit": "L", "reason": "TOO_MUCH",
            "context": {"forecast_need": "40", "made_by": "menu_plan", "offer_id": "o-old"}}],
            user="chef-1")
        record_feedback(db, kitchen_id, proposal_id, [{"kind": "approved"}], user="chef-1")
    db.feedback.update_many({}, {"$set": {"ts": OLD}})


def seed_declines(db, product_id="462775", kitchen_id="demo-kitchen"):
    """Three removals for OTHER: a declined product fact, but no ratio correction."""
    for number in range(3):
        record_feedback(db, kitchen_id, f"decline-{number}", [{
            "kind": "line_removed", "product_id": product_id, "from_qty": "20",
            "unit": "L", "reason": "OTHER", "note": "not this week",
            "context": {"forecast_need": "20", "made_by": "menu_plan"}}], user="chef-1")
    db.feedback.update_many({}, {"$set": {"ts": OLD}})


def seed_late_deliveries(db, supplier_id="late-supplier", product_id="462775",
                         kitchen_id="demo-kitchen"):
    """Five deliveries, four exactly one day late: on_time_rate 0.2."""
    for number in range(5):
        requested = date(2026, 11, 1) + timedelta(days=number)
        delivered = requested + timedelta(days=1 if number < 4 else 0)
        save_observation(
            db, kitchen_id=kitchen_id, order_id=f"late-{number}", supplier_id=supplier_id,
            requested_date=requested, ordered_at="2026-10-30T10:00:00Z",
            delivery_date=delivered, checked_by="chef-1",
            checked_at=f"{delivered}T08:00:00Z", source="photo",
            lines=[{"supplier_id": supplier_id, "product_id": product_id, "status": "RECEIVED",
                    "ordered": "10", "delivered": "10", "unit": "L"}], not_ordered=[])


def plan(client, key):
    r = client.post(K + "/proposals", headers=AGENT, json={
        "from": "2026-11-16", "to": "2026-11-22", "requested_date": "2026-11-16",
        "idempotency_key": key})
    assert r.status_code == 200, r.text
    return r.json()


def audit(db, kind):
    return [row["event"] for row in db.audit_log.find({})
            if row.get("event", {}).get("kind") == kind]


def test_get_returns_the_correction_fact_for_this_kitchen_only(env):
    client, _, db = env
    seed_corrections(db)
    facts = client.get(K + "/learned", headers=AGENT).json()["facts"]
    assert [fact["kind"] for fact in facts] == ["CORRECTION_RATIO"]
    fact = facts[0]
    assert fact["value"] == 0.5 and fact["applicable"] is True and fact["active"] is True
    assert fact["product_id"] == "462775" and fact["name"] == "milk 462775"
    assert fact["evidence"]["rows"] == 3 and fact["since"] == fact["evidence"]["last"]
    assert client.get("/v1/kitchens/other-kitchen/learned", headers=HUMAN).json() == {"facts": []}


def test_put_switches_a_fact_off_once_and_is_idempotent(env):
    client, _, db = env
    seed_corrections(db)
    fact = client.get(K + "/learned", headers=AGENT).json()["facts"][0]
    url = f"{K}/learned/{fact['id']}"
    first = client.put(url, headers=HUMAN, json={"active": False})
    assert first.status_code == 200, first.text
    assert first.json()["fact"]["active"] is False and first.json()["fact"]["id"] == fact["id"]
    again = client.put(url, headers=HUMAN, json={"active": False})
    assert again.status_code == 200 and again.json()["fact"]["active"] is False
    assert db.learned_overrides.count_documents({}) == 1
    assert len(audit(db, "learned_fact_switched_off")) == 1
    assert client.get(K + "/learned", headers=AGENT).json()["facts"][0]["active"] is False


def test_put_refuses_other_bodies_and_unknown_facts(env):
    client, _, db = env
    seed_corrections(db)
    fact = client.get(K + "/learned", headers=AGENT).json()["facts"][0]
    url = f"{K}/learned/{fact['id']}"
    assert client.put(url, headers=HUMAN, json={"active": True}).status_code == 422
    assert client.put(url, headers=HUMAN, json={"active": False, "x": 1}).status_code == 422
    assert client.put(url, headers=HUMAN, json={}).status_code == 422
    unknown = client.put(f"{K}/learned/lf_nope", headers=HUMAN, json={"active": False})
    assert unknown.status_code == 404 and unknown.json()["error"]["code"] == "LEARNED_FACT_NOT_FOUND"


def test_put_needs_an_approver_not_an_agent_or_a_chef(env):
    client, _, db = env
    from gateway import users
    seed_corrections(db)
    fact = client.get(K + "/learned", headers=AGENT).json()["facts"][0]
    url = f"{K}/learned/{fact['id']}"
    agent = client.put(url, headers=AGENT, json={"active": False})
    assert agent.status_code == 403
    users.create_user(db, "chef@example.com", "a long test password", name="Chef",
                      role="chef", kitchen_id="demo-kitchen")
    assert client.post("/v1/auth/login", json={
        "email": "chef@example.com", "password": "a long test password"}).status_code == 200
    chef = client.put(url, json={"active": False})
    assert chef.status_code == 403 and chef.json()["error"]["code"] == "ROLE_REQUIRED"


def test_a_plan_proposal_applies_the_ratio_and_keeps_the_unlearned_basis(env):
    client, _, db = env
    setup(client, [{"product_id": "462775", "on_hand": "5", "unit": "L"}])
    seed_corrections(db)
    proposal = plan(client, "learn-1")
    needs = {need["product_id"]: need for need in proposal["request"]["needs"]}
    learned = needs["462775"]
    assert learned["quantity"] == "10" and learned["unlearned_quantity"] == "20"
    assert learned["learned"]["from_qty"] == "20" and learned["learned"]["to_qty"] == "10"
    assert learned["learned"]["unit"] == "L" and learned["learned"]["ratio"] == 0.5
    line = next(line for line in proposal["lines"] if line["product_id"] == "462775")
    assert line["learned"] == learned["learned"] and "unlearned_quantity" not in line
    offer = db.offers.find_one({"_id": proposal["offer_id"]})
    stored = next(line for line in offer["simulation"]["lines"] if line["product_id"] == "462775")
    assert stored["unlearned_quantity"] == "20"
    applied = audit(db, "learned_fact_applied")
    assert len(applied) == 1
    assert applied[0]["proposal_id"] == proposal["proposal_id"] and applied[0]["offer_id"] == proposal["offer_id"]
    assert applied[0]["applied"] == [{"product_id": "462775",
                                      "fact_id": learned["learned"]["fact_id"],
                                      "from_qty": "20", "to_qty": "10", "unit": "L"}]


def test_a_disabled_fact_is_not_applied(env):
    client, _, db = env
    setup(client, [{"product_id": "462775", "on_hand": "5", "unit": "L"}])
    seed_corrections(db)
    fact = client.get(K + "/learned", headers=AGENT).json()["facts"][0]
    assert client.put(f"{K}/learned/{fact['id']}", headers=HUMAN,
                      json={"active": False}).status_code == 200
    proposal = plan(client, "learn-2")
    need = next(need for need in proposal["request"]["needs"] if need["product_id"] == "462775")
    assert need["quantity"] == "20" and "learned" not in need and "unlearned_quantity" not in need
    assert all("learned" not in line for line in proposal["lines"])
    assert audit(db, "learned_fact_applied") == []


def test_a_typed_request_is_never_adjusted(env):
    client, _, db = env
    seed_corrections(db)
    r = client.post(K + "/proposals", headers=AGENT, json={
        "product_ids": ["462775"], "quantity": "20", "unit": "L",
        "requested_date": "2026-11-16", "idempotency_key": "typed-1"})
    assert r.status_code == 200, r.text
    proposal = r.json()
    assert proposal["request"]["made_by"] == "structured"
    assert proposal["lines"][0]["quantity"] == "20" and "learned" not in proposal["lines"][0]


def test_a_learned_plan_proposal_is_not_auto_approved(env):
    client, _, db = env
    from gateway import autoapprove
    from gateway.tests.test_autoapprove import history, switch_on
    history(db)
    setup(client, [{"product_id": "462775", "on_hand": "5", "unit": "L"}])
    client.put(K + "/menu-plans/2026-W47", headers=HUMAN,
               json={"days": [PLAN["days"][0]]})
    seed_corrections(db)
    assert switch_on(client, "2000").status_code == 200
    proposal = plan(client, "auto-learned")
    assert proposal["status"] == "READY" and proposal["order_id"] is None
    doc = db.proposals.find_one({"_id": proposal["proposal_id"]})
    sim = db.offers.find_one({"_id": proposal["offer_id"]})["simulation"]
    ok, why, _ = autoapprove.decide(db, "demo-kitchen", sim, doc["request"], NOW)
    assert ok is False and "a learned adjustment needs a person" in why
    assert audit(db, "auto_approved") == []


def test_a_declined_product_stays_with_a_warning(env):
    client, _, db = env
    setup(client)
    seed_declines(db)
    proposal = plan(client, "declined-1")
    assert any(line["product_id"] == "462775" for line in proposal["lines"])
    assert ("You removed milk 462775 from 3 proposals; it is still needed by the menu plan. "
            "Remove it again, or switch the fact off.") in proposal["request"]["problems"]


def test_a_late_supplier_adds_the_order_earlier_warning(env):
    client, _, db = env
    setup(client)
    seed_late_deliveries(db)
    proposal = plan(client, "late-1")
    assert ("late-supplier was late in 4 of the last 5 deliveries: order a day earlier."
            in proposal["request"]["problems"])
