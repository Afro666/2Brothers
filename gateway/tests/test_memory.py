"""What a kitchen calls things: aliases a person sets, and unknown items it remembers."""

from fastapi.testclient import TestClient

from gateway import memory
from gateway.app import create_app
from gateway.service import Gateway
from gateway.tests.test_gateway_app import AGENT, HUMAN, K, NOW, env  # noqa: F401 (fixture)
from gateway.valio_client import ValioClient


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
    assert unknown[0]["suggestions"] == []                                       # nothing near: no guess
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


def test_alias_to_a_product_in_another_measure_does_not_lead_a_litre_shortlist(env):
    client, fake, db = env
    # The aliased product is sold by the kilo and is not among the litre search hits,
    # so it would be fetched on its own: it must not jump to the top of a litre shortlist.
    db.products.update_one({"_id": "463335"}, {"$set": {"net_content": {"value": 1.0, "unit": "KG"}}})

    def search(db, query, filters, limit, kitchen_id=None):
        return [{"product_id": pid, "net_content": {"value": 1.0, "unit": "L"}} for pid in ("462775", "462921")]

    gw = Gateway(db, ValioClient("k", transport=fake.transport, ttl=0, now=lambda: NOW), now=lambda: NOW,
                 search=search)
    client = TestClient(create_app(gw))
    client.put(K + "/aliases", headers=HUMAN, json={"phrase": "house milk", "product_id": "463335"})
    need = client.post(K + "/needs", headers=AGENT, json={
        "quantity": "20", "unit": "L", "requested_date": "2026-11-16", "text": "20 L house milk"}).json()
    found = client.post("/tools/search_products", headers=AGENT, json={
        "query": "milk", "filters": {}, "need_id": need["need_id"]}).json()
    assert found["measure"] == "L"
    assert found["products"][0]["product_id"] != "463335"
    assert not any(p.get("alias") for p in found["products"])


def test_another_kitchens_words_mean_nothing_here(env):
    client, _, db = env
    memory.set_alias(db, "other-kitchen", "house milk", "462775", "someone")
    assert memory.lookup(db, "demo-kitchen", "house milk") is None


def test_unknown_words_get_nearest_products_as_suggestions_once(env):
    client, _, db = env
    memory.note_unknown(db, "demo-kitchen", "talon maito")      # the test search knows "maito"
    first = client.get(K + "/aliases", headers=AGENT).json()["unknown_items"][0]
    assert first["phrase"] == "talon maito" and first["suggested_by"] == "words"
    assert [s["product_id"] for s in first["suggestions"]] == ["462775", "462921", "463335"]
    assert first["suggestions"][0]["product_name"] == "milk 462775"
    db.products.delete_many({})                                 # stored: the next call does not search again
    again = client.get(K + "/aliases", headers=AGENT).json()["unknown_items"][0]
    assert [s["product_id"] for s in again["suggestions"]] == ["462775", "462921", "463335"]


def test_meaning_search_falls_back_to_words_and_a_limit_per_call(monkeypatch):
    import mongomock
    import store.search
    db = mongomock.MongoClient(tz_aware=True)["t"]
    db.products.insert_one({"_id": "p1", "names": {"en": "Valio butter 500 g"}})
    calls = []

    def fake(db, phrase, filters, limit, kitchen_id=None, hybrid=False, embedder=None):
        calls.append(hybrid)
        if hybrid:
            raise RuntimeError("429 over the free tier")
        return [{"product_id": "p1"}]
    monkeypatch.setattr(store.search, "search_products", fake)
    found, how = memory.suggest(db, "k", "voi")
    assert how == "words" and found == [{"product_id": "p1", "product_name": "Valio butter 500 g"}]
    assert calls == [True, False]
    for i in range(5):
        memory.note_unknown(db, "k", f"word {i}")
    rows = memory.list_unknown(db, "k", with_suggestions=True)
    assert sum(1 for r in rows if r["suggestions"] is not None) == memory.NEW_SUGGESTIONS_PER_CALL
