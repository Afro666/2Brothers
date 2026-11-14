"""#1869: a lactose-free request had an option with a low lactose milk. A diet word in the
request (gateway/diet.py) is a hard rule on the shortlist and on every quote: the Buyer
path (need, search, offer, substitute options) and the plain-code path."""

import asyncio

from fastapi.testclient import TestClient
import mongomock
import pytest

from agent.substitutes import AllergenPolicy, SubstitutePlanner
from gateway import diet
from gateway.app import create_app
from gateway.service import Gateway
from gateway.tests.test_gateway_app import AGENT, K, NOW, RAW, FakeValio
from gateway.valio_client import ValioClient

FREE, LOW, PLAIN = "462775", "463335", "462921"     # the recorded Valio offers (fixtures)
ALLERGENS = {"contains": ["AM"], "may_contain": [], "undeclared": []}
# Catalog rows as the live site answers them (2026-11-15): 463380 and 463047.
ROWS = {
    FREE: {"names": {"en": "Arla Cafè milk 1 L UHT lactose free", "fi": "Arla Cafè maito 1 L UHT laktoositon"},
           "lactose_free": True, "claims": ["FREE_FROM_LACTOSE"], "free_from": ["ML"], "allergens": ALLERGENS},
    LOW: {"names": {"en": "Arla Whole milk 1 L Suomesta low lactose Uht",
                    "fi": "Arla Täysmaito 1 L Suomesta vähälaktoosinen Uht"},
          "lactose_free": False, "claims": ["LOW_LACTOSE"], "free_from": [],
          "allergens": {"contains": ["AM", "ML"], "may_contain": [], "undeclared": []}},
    PLAIN: {"names": {"en": "Valio whole milk 1 l", "fi": "Valio täysmaito 1 l"},
            "lactose_free": False, "claims": [], "free_from": [], "allergens": ALLERGENS},
}


def search(db, query, filters, limit, kitchen_id=None):
    """A word search as the live one: every milk holds "milk"; the low lactose milk also
    holds "lactose"."""
    return [{"product_id": pid, **row, "category": "10400", "net_content": {"value": 1.0, "unit": "L"},
             "allergen_data_known": True} for pid, row in ROWS.items()][:limit]


@pytest.fixture()
def gateway(monkeypatch):
    monkeypatch.setenv("GATEWAY_HUMAN_TOKEN", "human-test-token")
    monkeypatch.setenv("GATEWAY_AGENT_TOKEN", "agent-test-token")
    db = mongomock.MongoClient(tz_aware=True)["test"]
    for pid, row in ROWS.items():
        db.products.insert_one({"_id": pid, "category": "10400", "source": "valio", "supplier_id": "valio_aimo",
                                "net_content": {"value": 1.0, "unit": "L"}, "allergen_data_known": True,
                                "substitutions": [], "raw": RAW[pid], **row})
    valio = ValioClient("test-not-a-real-key", transport=FakeValio().transport, ttl=0, now=lambda: NOW)
    gw = Gateway(db, valio, now=lambda: NOW, search=search)
    return TestClient(create_app(gw)), gw


def need(client, text, quantity="1000"):
    return client.post(K + "/needs", headers=AGENT, json={
        "quantity": quantity, "unit": "L", "requested_date": "2026-11-16", "text": text}).json()


def offer(client, need_id, ids):
    r = client.post("/tools/get_offer", headers=AGENT, json={"need_id": need_id, "product_ids": ids})
    assert r.status_code == 200, r.text
    return r.json()


# ---- the rule ---------------------------------------------------------------------------

@pytest.mark.parametrize("text,keys", [
    ("1,000 L lactose-free milk by Monday", ["lactose_free"]),
    ("1,000 litres of lactose free milk by Monday", ["lactose_free"]),
    ("1000 l laktoositonta maitoa maanantaiksi", ["lactose_free"]),
    ("laktoositon maito", ["lactose_free"]),
    ("100 l laktosfri mjölk", ["lactose_free"]),
    ("60 litres of the gluten-free oat drink for the coeliac pupils", ["gluten_free"]),
    ("20 kg gluteenitonta leipää", ["gluten_free"]),
    ("20 kg glutenfritt bröd", ["gluten_free"]),
    ("10 kg gluten free and lactose free bread", ["lactose_free", "gluten_free"]),
    ("200 L milk", []), ("50 L low lactose milk", []), ("50 l vähälaktoosista maitoa", []),
    ("", []), (None, []),
])
def test_the_diet_of_a_request_is_read_in_english_finnish_and_swedish(text, keys):
    assert [d.key for d in diet.asked(text)] == keys


def test_low_lactose_is_not_lactose_free():
    lactose, gluten = diet.DIETS
    assert diet.meets(ROWS[FREE], lactose)
    assert not diet.meets(ROWS[LOW], lactose)
    assert not diet.meets(ROWS[PLAIN], lactose)
    assert not diet.meets(None, lactose) and not diet.meets({}, lactose)      # unknown is not a match
    # A name is proof when the catalog has no claim; a declared allergen that contradicts wins.
    assert diet.meets({"names": {"fi": "Talon laktoositon maito 1 l"}}, lactose)
    assert not diet.meets({"names": {"en": "Milk lactose free"}, "allergens": {"contains": ["ML"]}}, lactose)
    assert not diet.meets({"lactose_free": True, "allergens": {"may_contain": ["ML"]}}, lactose)
    assert diet.meets({"claims": ["FREE_FROM_GLUTEN"], "allergens": {"contains": ["GO"]}}, gluten)   # oats
    assert not diet.meets({"claims": ["FREE_FROM_GLUTEN"], "allergens": {"contains": ["UW"]}}, gluten)
    assert not diet.meets({"claims": ["FREE_FROM_LACTOSE"], "names": {"en": "Rye bread"}}, gluten)


# ---- the Buyer path ---------------------------------------------------------------------

def test_a_quote_for_lactose_free_milk_leaves_the_low_lactose_milk_out_and_says_why(gateway):
    client, _ = gateway
    n = need(client, "1,000 L lactose-free milk by Monday")
    quote = offer(client, n["need_id"], [FREE, LOW, PLAIN])
    assert quote["lines"] and {line["product_id"] for line in quote["lines"]} == {FREE}
    reasons = {e["product_id"]: e["reason"] for e in quote["excluded"]}
    assert reasons[LOW].startswith("not lactose-free as asked")
    assert reasons[PLAIN].startswith("not lactose-free as asked")


def test_a_quote_with_only_low_lactose_milk_has_no_line(gateway):
    client, _ = gateway
    n = need(client, "1000 l laktoositonta maitoa maanantaiksi")
    quote = offer(client, n["need_id"], [LOW])
    assert quote["lines"] == []
    assert quote["mandate"]["reasons"][0].startswith("not lactose-free as asked")


def test_the_buyers_shortlist_for_lactose_free_milk_has_no_low_lactose_milk(gateway):
    client, _ = gateway
    n = need(client, "1,000 L lactose-free milk by Monday")
    found = client.post("/tools/search_products", headers=AGENT, json={
        "query": "Arla Cafè milk 1 L UHT lactose free", "filters": {}, "need_id": n["need_id"]}).json()
    assert [p["product_id"] for p in found["products"]] == [FREE]


def test_a_request_with_no_diet_word_keeps_every_milk(gateway):
    client, _ = gateway
    n = need(client, "1,000 L milk by Monday")
    quote = offer(client, n["need_id"], [FREE, LOW, PLAIN])
    assert not any("as asked" in e["reason"] for e in quote["excluded"])
    found = client.post("/tools/search_products", headers=AGENT, json={
        "query": "milk", "filters": {}, "need_id": n["need_id"]}).json()
    assert {p["product_id"] for p in found["products"]} == {FREE, LOW, PLAIN}


def test_the_buyers_substitute_options_never_hold_a_low_lactose_milk(gateway):
    """The live fault: `SubstitutePlanner` (agent/substitutes.py) searched by the name of the
    first product and offered the low lactose milk as the catalog option."""
    client, gw = gateway
    n = need(client, "1,000 L lactose-free milk by Monday")
    first = offer(client, n["need_id"], [FREE])

    def lookup(pid):
        from store.products import get_product
        return get_product(gw.db, pid)

    class Buyer:
        offer_products = {first["offer_id"]: [FREE]}
        products = {FREE}
        need_id, requested_date = n["need_id"], "2026-11-16"

    async def read(tool, body):
        if tool == "search_products":
            body = {**body, "need_id": n["need_id"]}
        r = client.post(f"/tools/{tool}", headers=AGENT, json=body)
        assert r.status_code == 200, r.text
        return r.json()

    options = asyncio.run(SubstitutePlanner(lookup, AllergenPolicy()).plan(Buyer, first, read))
    assert options, "the Buyer's own basket is an option"
    assert all(line["product_id"] == FREE for option in options for line in option["lines"]), options


# ---- the plain-code path ----------------------------------------------------------------

def test_the_plain_code_path_proposes_only_lactose_free_milk(gateway):
    client, gw = gateway
    read = gw._from_text("demo-kitchen", {"text": "1,000 L lactose-free milk by Monday", "idempotency_key": "k"})
    assert read["product_ids"] == [FREE]
    r = client.post(K + "/proposals", headers=AGENT, json={
        "text": "1,000 L lactose-free milk by Monday", "idempotency_key": "plain"})
    assert r.status_code == 200, r.text
    p = r.json()
    every = [line for option in p.get("substitute_options") or [] for line in option["lines"]] + p["lines"]
    assert every and all(line["product_id"] == FREE for line in every), p


def test_a_word_link_to_a_low_lactose_milk_does_not_answer_lactose_free(gateway):
    from gateway import memory
    client, gw = gateway
    memory.set_alias(gw.db, "demo-kitchen", "lactose free milk", LOW, "chef")
    r = client.post(K + "/proposals", headers=AGENT, json={
        "text": "1,000 L lactose-free milk by Monday", "idempotency_key": "alias"})
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["lines"] == []
    assert [(e["product_id"], e["reason"]) for e in p["excluded"]] == [
        (LOW, "not lactose-free as asked: no other product is proposed in its place")]


def test_a_list_keeps_the_diet_of_each_need(gateway):
    client, _ = gateway
    r = client.post(K + "/proposals", headers=AGENT, json={
        "needs": [{"text": "lactose-free milk", "quantity": "100", "unit": "L"},
                  {"text": "gluten-free oat drink", "quantity": "20", "unit": "L"}],
        "requested_date": "2026-11-16", "idempotency_key": "list"})
    assert r.status_code == 200, r.text
    assert {line["product_id"] for line in r.json()["lines"]} == {FREE}, r.json()     # no milk is gluten-free


def test_a_word_link_in_a_list_does_not_answer_the_diet(gateway):
    from gateway import memory
    client, gw = gateway
    memory.set_alias(gw.db, "demo-kitchen", "lactose free milk", LOW, "chef")
    r = client.post(K + "/proposals", headers=AGENT, json={
        "needs": [{"text": "lactose-free milk", "quantity": "100", "unit": "L"},
                  {"text": "gluten-free oat drink", "quantity": "20", "unit": "L"}],
        "requested_date": "2026-11-16", "idempotency_key": "list-alias"})
    assert r.status_code == 200, r.text
    assert r.json()["lines"] == [], r.json()
