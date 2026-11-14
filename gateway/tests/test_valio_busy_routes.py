"""What the gateway answers while Valio rests after a 429 (#1237): 503 SUPPLIER_BUSY where a
live answer is needed, unknown where the view can do without one. Fake transport only."""

from urllib.error import HTTPError

import pytest

from gateway.tests.test_gateway_app import AGENT, HUMAN, K, env  # noqa: F401 (fixture)
from gateway.tests.test_supplier_routes import URL, seed
from gateway.valio_client import ValioBusy


def rest(fake):
    """The next Valio call answers 429 (no Retry-After): the client rests for 30 s."""
    def hook():
        fake.hook = None
        raise HTTPError("hidden", 429, "Too Many Requests", {}, None)
    fake.hook = hook


def busy(answer):
    assert answer.status_code == 503, answer.text
    error = answer.json()["error"]
    assert error["code"] == "SUPPLIER_BUSY"
    assert 1 <= error["retry_after"] <= 30
    assert answer.headers["Retry-After"] == str(error["retry_after"])
    assert "test-not-a-real-key" not in answer.text
    return error


def test_get_offer_answers_supplier_busy_and_sends_nothing_during_the_rest(env):
    client, fake, db = env
    need = client.post(K + "/needs", headers=AGENT, json={
        "quantity": "60", "unit": "L", "requested_date": "2026-11-16"}).json()
    rest(fake)
    offer = {"need_id": need["need_id"], "product_ids": ["462775"]}
    assert busy(client.post("/tools/get_offer", headers=AGENT, json=offer))["retry_after"] == 30
    sent = []
    fake.hook = lambda: sent.append(1)
    busy(client.post("/tools/get_offer", headers=AGENT, json=offer))       # still resting
    assert sent == []                                                      # nothing reached Valio
    assert db.offers.count_documents({}) == 0


def test_a_proposal_from_product_ids_answers_supplier_busy(env):
    client, fake, db = env
    rest(fake)
    busy(client.post(K + "/proposals", headers=AGENT, json={
        "product_ids": ["462775"], "quantity": "51", "unit": "L",
        "requested_date": "2026-11-16", "idempotency_key": "rest-1"}))
    assert db.proposals.count_documents({}) == 0


def test_the_planner_view_shows_demand_with_unknown_availability_during_the_rest(env):
    client, fake, db = env
    seed(db)
    rest(fake)
    answer = client.get(URL, headers=HUMAN)
    assert answer.status_code == 200, answer.text
    rows = answer.json()["rows"]
    assert rows and all(r["risk"] == "UNKNOWN" and r["available"] is None for r in rows)
    assert {r["product_id"]: r["demand"] for r in rows}["462775"] == "70"   # the demand still shows


def test_a_supplier_offer_during_the_rest_is_supplier_busy_not_no_shortage(monkeypatch):
    from gateway.tests.test_supplier_offers import World
    w = World(monkeypatch)
    rest(w.fake)
    with pytest.raises(ValioBusy):             # the 429: Valio now rests for 30 s
        w.gw.valio.availability(["462775"], "2026-11-16")
    busy(w.offer())
    assert w.db.supplier_offers.count_documents({}) == 0
