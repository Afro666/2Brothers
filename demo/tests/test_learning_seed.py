"""The demo's sample learning history (#1305): a learned line appears on the next weekly
plan proposal, marked as sample data, and a repeat run writes nothing."""
from datetime import date

from demo.learning_seed import USER, pick_product, seed
from gateway.tests.test_gateway_app import AGENT, HUMAN, K, env  # noqa: F401 (fixture)
from gateway.tests.test_learned import plan
from gateway.tests.test_plan_proposal import setup

TODAY = date(2026, 11, 13)     # the test clock's day (a Friday): next week's plan is 2026-W47, as in the fixture


def test_the_seed_makes_the_next_weekly_plan_show_a_learned_line(env):
    client, _, db = env
    setup(client, [{"product_id": "462775", "on_hand": "5", "unit": "L"}])
    product = pick_product(db, "demo-kitchen", TODAY)
    assert product is not None

    dry = seed(db, today=TODAY, dry_run=True)
    assert dry["written"] == 0 and dry["would_write"] == 8 and db.feedback.count_documents({}) == 0

    done = seed(db, today=TODAY)
    assert done["written"] == 8 and done["product_id"] == product["product_id"]
    assert set(db.feedback.distinct("user")) == {USER}              # every row is labelled sample data
    assert all(p.startswith("sample-learning-") for p in db.feedback.distinct("proposal_id"))

    facts = client.get(K + "/learned", headers=HUMAN).json()["facts"]
    fact = next(f for f in facts if f["kind"] == "CORRECTION_RATIO")
    assert fact["product_id"] == product["product_id"] and fact["value"] == 0.5 and fact["active"] is True

    proposal = plan(client, "after-seed")
    line = next(line for line in proposal["lines"] if line["product_id"] == product["product_id"])
    assert line["learned"]["fact_id"] == fact["id"] and line["learned"]["ratio"] == 0.5


def test_a_repeat_run_writes_nothing_and_the_fact_can_be_switched_off(env):
    client, _, db = env
    setup(client, [{"product_id": "462775", "on_hand": "5", "unit": "L"}])
    seed(db, today=TODAY)
    again = seed(db, today=TODAY)
    assert again["written"] == 0 and db.feedback.count_documents({}) == 8

    fact = next(f for f in client.get(K + "/learned", headers=HUMAN).json()["facts"]
                if f["kind"] == "CORRECTION_RATIO")
    r = client.put(f"{K}/learned/{fact['id']}", headers=HUMAN, json={"active": False})
    assert r.status_code == 200, r.text
    proposal = plan(client, "after-undo")
    line = next(line for line in proposal["lines"] if line["product_id"] == fact["product_id"])
    assert "learned" not in line                                    # undo restores the plain number
