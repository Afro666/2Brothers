"""What a kitchen calls things: aliases a person sets, and unknown items it remembers."""

from gateway import memory
from gateway.tests.test_gateway_app import AGENT, HUMAN, K, env  # noqa: F401 (fixture)


def test_normalise_keeps_letters_of_any_language():
    assert memory.normalise("  House-Milk!! ") == "house milk"
    assert memory.normalise("Talon   MAITO, 1 l") == "talon maito 1 l"
    assert memory.normalise("kermaa (ruoka)") == "kermaa ruoka"


def test_alias_is_set_by_a_person_and_used_by_the_parser(env):
    client, _, db = env
    assert client.put(K + "/aliases", headers=AGENT, json={"phrase": "house milk", "product_id": "462775"}).status_code == 403
    bad = client.put(K + "/aliases", headers=HUMAN, json={"phrase": "house milk", "product_id": "nope"})
    assert bad.status_code == 422
    made = client.put(K + "/aliases", headers=HUMAN, json={"phrase": "House Milk", "product_id": "462775"})
    assert made.status_code == 200 and made.json()["phrase"] == "house milk"
    # "house milk" matches nothing in the catalog search of this test; the alias answers it.
    r = client.post(K + "/proposals", headers=AGENT, json={"text": "40 l house milk by Monday", "idempotency_key": "m1"})
    assert r.status_code == 200, r.text
    p = r.json()
    assert [ln["product_id"] for ln in p["lines"]] == ["462775"] and str(p["lines"][0]["quantity"]) in ("40", "40.0")
    listed = client.get(K + "/aliases", headers=AGENT).json()
    assert listed["aliases"][0]["phrase"] == "house milk" and listed["aliases"][0]["uses"] == 1


def test_unknown_item_is_remembered_and_linking_it_clears_it(env):
    client, _, db = env
    for key in ("u1", "u2"):
        r = client.post(K + "/proposals", headers=AGENT, json={"text": "10 kg unicorn steak by Monday", "idempotency_key": key})
        assert r.status_code == 422 and r.json()["error"]["code"] == "NO_PRODUCTS_FOUND"
        assert r.json()["error"]["remembered"] is True
    unknown = client.get(K + "/aliases", headers=AGENT).json()["unknown_items"]
    assert unknown[0]["phrase"] == "unicorn steak" and unknown[0]["times"] == 2
    assert db.products.count_documents({"names.en": "unicorn steak"}) == 0        # nothing invented
    client.put(K + "/aliases", headers=HUMAN, json={"phrase": "unicorn steak", "product_id": "463335"})
    assert client.get(K + "/aliases", headers=AGENT).json()["unknown_items"] == []


def test_alias_leads_the_buyers_shortlist_and_can_be_removed(env):
    client, _, db = env
    client.put(K + "/aliases", headers=HUMAN, json={"phrase": "house milk", "product_id": "463335"})
    need = client.post(K + "/needs", headers=AGENT, json={
        "quantity": "20", "unit": "L", "requested_date": "2026-11-16", "text": "20 L house milk"}).json()
    found = client.post("/tools/search_products", headers=AGENT, json={
        "query": "milk", "filters": {}, "need_id": need["need_id"]}).json()
    first = found["products"][0]
    assert first["product_id"] == "463335" and first["alias"] is True
    assert client.delete(K + "/aliases?phrase=house%20milk", headers=HUMAN).json() == {"deleted": True}
    assert client.delete(K + "/aliases?phrase=house%20milk", headers=HUMAN).status_code == 404
    assert memory.lookup(db, "demo-kitchen", "house milk") is None


def test_another_kitchens_words_mean_nothing_here(env):
    client, _, db = env
    memory.set_alias(db, "other-kitchen", "house milk", "462775", "someone")
    assert memory.lookup(db, "demo-kitchen", "house milk") is None
