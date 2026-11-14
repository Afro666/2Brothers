"""#570: a product with reliability and carbon (binary floats in the catalog) still gets an offer."""

from gateway.tests.test_gateway_app import AGENT, HUMAN, K, env, milk  # noqa: F401 (fixture)


def test_offer_for_a_product_with_reliability_and_carbon_is_stored_and_answers_numbers(env):
    client, _, db = env
    db.products.update_one({"_id": "462775"}, {"$set": {"reliability": 1.0, "carbon_kg_co2e_per_kg": 1.1}})
    p = milk(client)
    line = next(ln for ln in p["lines"] if ln["product_id"] == "462775")
    assert line["reliability"] == 1 and line["carbon_kg_co2e_per_kg"] == 1.1
    assert not isinstance(line["reliability"], str)          # the contract says number or null
    again = client.get(f"{K}/proposals/{p['proposal_id']}", headers=AGENT).json()
    assert next(ln for ln in again["lines"] if ln["product_id"] == "462775")["carbon_kg_co2e_per_kg"] == 1.1


def test_tool_offer_keeps_unknown_reliability_and_carbon_as_null(env):
    client, _, db = env
    db.products.update_one({"_id": "462775"}, {"$set": {"reliability": 0.97}})
    need = client.post(K + "/needs", headers=AGENT, json={"quantity": "20", "unit": "L", "requested_date": "2026-11-16"}).json()
    r = client.post("/tools/get_offer", headers=AGENT, json={"need_id": need["need_id"], "product_ids": ["462775"]})
    assert r.status_code == 200, r.text
    line = r.json()["lines"][0]
    assert line["reliability"] == 0.97 and line["carbon_kg_co2e_per_kg"] is None
    sim = client.post("/tools/simulate_order", headers=AGENT, json={"offer_id": r.json()["offer_id"]})
    assert sim.status_code == 200 and sim.json()["lines"][0]["reliability"] == 0.97


def test_approved_order_lines_answer_numbers_too(env):
    client, _, db = env
    db.products.update_one({"_id": "462775"}, {"$set": {"reliability": 1.0, "carbon_kg_co2e_per_kg": 1.1}})
    p = milk(client)
    r = client.post(f"{K}/proposals/{p['proposal_id']}/approve", headers=HUMAN,
                    json={"expected_total": p["expected_total"], "idempotency_key": "a1"})
    assert r.status_code == 200, r.text
    order = client.get(f"{K}/orders/{r.json()['order_id']}", headers=AGENT).json()
    assert order["lines"][0]["reliability"] == 1 and order["lines"][0]["carbon_kg_co2e_per_kg"] == 1.1
    assert not any(isinstance(v, float) for ln in db.orders.find_one({})["lines"] for v in ln.values())


def test_order_lookup_answers_reliability_and_carbon_as_numbers(env):
    client, _, db = env
    db.products.update_one({"_id": "462775"}, {"$set": {"reliability": 0.97, "carbon_kg_co2e_per_kg": 1.1}})
    p = milk(client)
    r = client.post(f"{K}/proposals/{p['proposal_id']}/approve", headers=HUMAN,
                    json={"expected_total": p["expected_total"], "idempotency_key": "a1"})
    assert r.status_code == 200, r.text
    known = client.get(f"{K}/orders/{r.json()['order_id']}/resolution", headers=HUMAN)
    assert known.status_code == 200, known.text
    line = next(ln for ln in known.json()["lines"] if ln["product_id"] == "462775")
    assert line["reliability"] == 0.97 and line["carbon_kg_co2e_per_kg"] == 1.1
    assert not isinstance(line["reliability"], str)          # the contract says number or null


def test_short_order_with_an_alternative_and_a_partial_fill_is_stored(env):
    client, _, db = env
    db.products.update_many({}, {"$set": {"reliability": 0.9, "carbon_kg_co2e_per_kg": 1.1}})
    p = milk(client, quantity="1000")
    assert p["lines"] and all(ln["reliability"] == 0.9 for ln in p["lines"])
