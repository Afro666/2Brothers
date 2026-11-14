"""Reason codes reach the proposal through HTTP: EVENT_LINE (S05), ALLERGEN_DATA_MISSING (S02/S04)."""

from gateway.tests.test_gateway_app import AGENT, K, env  # noqa: F401  (env is a fixture)


def propose(client, key, **extra):
    r = client.post(K + "/proposals", headers=AGENT, json={
        "product_ids": ["462775"], "quantity": "51", "unit": "L", "requested_date": "2026-11-16",
        "idempotency_key": key, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def test_event_request_is_marked_event_line(env):  # noqa: F811
    client, _, _ = env
    assert "EVENT_LINE" in propose(client, "e1", event=True)["mandate"]["reason_codes"]
    assert "EVENT_LINE" not in propose(client, "e2")["mandate"]["reason_codes"]


def test_catalog_row_decides_allergen_flag(env):  # noqa: F811
    client, _, db = env
    p = propose(client, "a1")      # test rows carry no allergen fields: unknown, flagged
    assert "ALLERGEN_DATA_MISSING" in p["lines"][0]["reason_codes"]
    db.products.update_one({"_id": "462775"}, {"$set": {"allergen_data_known": True}})
    p = propose(client, "a2")
    assert "ALLERGEN_DATA_MISSING" not in p["lines"][0]["reason_codes"]
