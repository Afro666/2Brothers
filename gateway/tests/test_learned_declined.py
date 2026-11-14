"""A product the kitchen keeps removing is left out of a plan proposal (#1307).

Shown, not hidden: the product is in `excluded` with the reason and the fact id, and
switching the fact off brings it back. A recipe ingredient stays, with a warning.
"""

from datetime import datetime, timezone

from gateway.tests.test_gateway_app import AGENT, HUMAN, K, env  # noqa: F401 (fixture)
from gateway.tests.test_plan_proposal import PLAN, RECIPES
from store.feedback import record_feedback

OLD = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
MILK, CREAM = "462775", "463335"       # the latte needs MILK; CREAM is forecast only
SENTENCE = ("LEARNED_DECLINED: not proposed: you removed it 3 times (last on 2026-11-01). "
            "Switch this learned fact off to get it back.")


def setup(client, db, kitchen_id="demo-kitchen"):
    """A latte on Monday (a recipe needs MILK) and a history forecast for CREAM on
    Wednesday, a day without a plan: no recipe needs CREAM in the window."""
    assert client.post(K + "/recipes", headers=HUMAN, json=RECIPES[0]).status_code == 200
    assert client.put(K + "/menu-plans/2026-W47", headers=HUMAN,
                      json={"days": [PLAN["days"][0]]}).status_code == 200
    db.forecasts.insert_one({"ts": datetime(2026, 11, 18, 12, tzinfo=timezone.utc),
                             "meta": {"kitchen_id": kitchen_id, "product_id": CREAM},
                             "need": 8.0, "unit": "L"})


def remove(db, times, product_id=CREAM, reason="TOO_MUCH", kitchen_id="demo-kitchen"):
    for number in range(times):
        record_feedback(db, kitchen_id, f"removed-{reason}-{number}", [{
            "kind": "line_removed", "product_id": product_id, "from_qty": "8",
            "unit": "L", "reason": reason,
            "context": {"forecast_need": "8", "made_by": "menu_plan"}}], user="chef-1")
    db.feedback.update_many({}, {"$set": {"ts": OLD}})


def plan(client, key):
    return client.post(K + "/proposals", headers=AGENT, json={
        "from": "2026-11-16", "to": "2026-11-22", "requested_date": "2026-11-16",
        "idempotency_key": key})


def proposal(client, key):
    r = plan(client, key)
    assert r.status_code == 200, r.text
    return r.json()


def ids(rows):
    return {row["product_id"] for row in rows}


def audit(db, kind):
    return [row["event"] for row in db.audit_log.find({})
            if row.get("event", {}).get("kind") == kind]


def test_without_removals_the_forecast_product_is_proposed(env):
    client, _, db = env
    setup(client, db)
    p = proposal(client, "none")
    assert ids(p["lines"]) == {MILK, CREAM} and p["excluded"] == []
    assert "learned_excluded" not in p["request"]


def test_three_removals_leave_it_out_and_say_why(env):
    client, _, db = env
    setup(client, db)
    remove(db, 3)
    p = proposal(client, "three")
    assert ids(p["lines"]) == {MILK}
    assert ids(p["request"]["needs"]) == {MILK} and p["request"]["product_ids"] == [MILK]
    fact = next(f for f in client.get(K + "/learned", headers=AGENT).json()["facts"]
                if f["kind"] == "DECLINED_PRODUCT")
    entry = next(e for e in p["excluded"] if e["product_id"] == CREAM)
    assert entry["reason"] == SENTENCE
    assert entry["fact_id"] == fact["id"] and entry["evidence"] == fact["evidence"]
    assert entry["evidence"]["rows"] == 3 and entry["evidence"]["last"] == "2026-11-01"
    assert (entry["quantity"], entry["unit"]) == ("8", "L")
    assert entry["product_name"] == "milk 463335"
    assert any(SENTENCE in reason for reason in p["mandate"]["reasons"])
    assert p["request"]["learned_excluded"] == [
        {key: entry[key] for key in ("product_id", "reason", "fact_id", "evidence", "quantity", "unit")}]


def test_the_left_out_product_is_audited_like_a_learned_adjustment(env):
    client, _, db = env
    setup(client, db)
    remove(db, 3)
    p = proposal(client, "audit")
    applied = audit(db, "learned_fact_applied")
    assert len(applied) == 1
    assert applied[0]["proposal_id"] == p["proposal_id"] and applied[0]["offer_id"] == p["offer_id"]
    assert applied[0]["applied"] == [{"product_id": CREAM, "fact_id": p["excluded"][0]["fact_id"],
                                      "from_qty": "8", "to_qty": "0", "unit": "L"}]


def test_two_removals_do_not_leave_it_out(env):
    client, _, db = env
    setup(client, db)
    remove(db, 2)
    p = proposal(client, "two")
    assert ids(p["lines"]) == {MILK, CREAM} and p["excluded"] == []
    assert audit(db, "learned_fact_applied") == []


def test_in_stock_and_menu_changed_removals_do_not_count(env):
    client, _, db = env
    setup(client, db)
    remove(db, 3, reason="IN_STOCK")
    remove(db, 3, reason="MENU_CHANGED")
    remove(db, 2, reason="TOO_MUCH")
    p = proposal(client, "in-stock")
    assert ids(p["lines"]) == {MILK, CREAM} and p["excluded"] == []


def test_another_kitchens_removals_never_count(env):
    client, _, db = env
    setup(client, db)
    remove(db, 3, kitchen_id="other-kitchen")
    p = proposal(client, "other")
    assert ids(p["lines"]) == {MILK, CREAM} and p["excluded"] == []


def test_switching_the_fact_off_brings_the_product_back(env):
    client, _, db = env
    setup(client, db)
    remove(db, 3)
    first = proposal(client, "before-undo")
    fact_id = first["excluded"][0]["fact_id"]
    off = client.put(f"{K}/learned/{fact_id}", headers=HUMAN, json={"active": False})
    assert off.status_code == 200, off.text
    again = proposal(client, "after-undo")
    assert ids(again["lines"]) == {MILK, CREAM} and again["excluded"] == []
    assert "learned_excluded" not in again["request"]
    # The first proposal is not re-quoted silently.
    kept = client.get(f"{K}/proposals/{first['proposal_id']}", headers=AGENT).json()
    assert ids(kept["lines"]) == {MILK}


def test_a_typed_request_still_gets_the_product(env):
    client, _, db = env
    setup(client, db)
    remove(db, 3)
    r = client.post(K + "/proposals", headers=AGENT, json={
        "product_ids": [CREAM], "quantity": "8", "unit": "L",
        "requested_date": "2026-11-16", "idempotency_key": "typed"})
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["request"]["made_by"] == "structured"
    assert ids(p["lines"]) == {CREAM}
    assert all("fact_id" not in e for e in p["excluded"])


def test_a_free_text_request_still_gets_the_product(env):
    client, _, db = env
    setup(client, db)
    remove(db, 3)
    remove(db, 3, product_id=MILK)
    r = client.post(K + "/proposals", headers=AGENT, json={
        "text": "1000 L milk", "requested_date": "2026-11-16", "idempotency_key": "text"})
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["request"]["made_by"] == "parser"
    assert {MILK, CREAM} <= ids(p["lines"])
    assert all("fact_id" not in e for e in p["excluded"])
    assert audit(db, "learned_fact_applied") == []


def test_a_recipe_ingredient_stays_with_a_warning(env):
    client, _, db = env
    setup(client, db)
    remove(db, 3, product_id=MILK)
    p = proposal(client, "recipe")
    assert ids(p["lines"]) == {MILK, CREAM} and p["excluded"] == []
    assert ("You removed milk 462775 from 3 proposals; it is still needed by the menu plan. "
            "Remove it again, or switch the fact off.") in p["request"]["problems"]


def test_when_every_need_is_declined_the_answer_says_why(env):
    client, _, db = env
    setup(client, db)
    client.put(K + "/menu-plans/2026-W47", headers=HUMAN, json={"days": []})
    remove(db, 3)
    r = plan(client, "all")
    assert r.status_code == 422 and r.json()["error"]["code"] == "NOTHING_NEEDED"
    assert any("milk 463335" in line and "you removed it 3 times" in line
               for line in r.json()["error"]["problems"])
    assert db.proposals.count_documents({}) == 0


def test_a_change_keeps_the_left_out_entry(env):
    client, _, db = env
    setup(client, db)
    remove(db, 3)
    p = proposal(client, "change")
    r = client.post(f"{K}/proposals/{p['proposal_id']}/change", headers=HUMAN, json={
        "idempotency_key": "change-1", "lines": [{"product_id": MILK, "quantity": "12"}]})
    assert r.status_code == 200, r.text
    assert [e["fact_id"] for e in r.json()["excluded"] if e["product_id"] == CREAM] == [
        p["excluded"][0]["fact_id"]]


def test_a_learning_error_leaves_the_product_in(env, monkeypatch):
    client, _, db = env
    setup(client, db)
    remove(db, 3)

    def broken(*args, **kwargs):
        raise RuntimeError("learning bug")

    monkeypatch.setattr("gateway.learned.compute_facts", broken)
    p = proposal(client, "broken")
    assert ids(p["lines"]) == {MILK, CREAM} and p["excluded"] == []
