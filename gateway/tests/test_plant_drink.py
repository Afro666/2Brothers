"""#1700: "20 L almond milk by Monday" was proposed as cow's milk. The kind rule read "milk"
as the product word and picked the dairy milk category. A plant drink is its own kind
(gateway/kind.py `plant_drink`), on the parser path, the Buyer's shortlist and every quote."""

from fastapi.testclient import TestClient
import mongomock
import pytest

from gateway.app import create_app
from gateway.kind import is_plant_drink, plant_drink
from gateway.service import Gateway
from gateway.tests import test_kind
from gateway.tests.test_gateway_app import AGENT, K, NOW, RAW, FakeValio
from gateway.tests.test_kind import MILK, many, product
from gateway.valio_client import ValioClient

# Names as in the Valio catalog (category 10402, 2026-11-14).
PLANT = many("pd", "10402", [
    ("Alpro No Sugars Almond drink unsweetened 1L", "Alpro No Sugars Mantelijuoma makeuttamaton 1L"),
    ("Alpro Almond drink, Original 1L", "Alpro Mantelijuoma, Original 1L"),
    ("Oatly Oat Drink Organic 1L", "Oatly Kaurajuoma Luomu 1L"),
    ("Oatly iKaffe Oat drink 1L", "Oatly iKaffe Kaurajuoma 1L"),
    ("Alpro Soya drink, Original 1L", "Alpro Soijajuoma, Original 1L"),
    ("Santa Maria 2900ml Coconut Milk", "Santa Maria 2900ml Kookosmaito")], unit="L")
HAND_WASH = [product("hw0", "63111", "Palmolive Almond Milk hand wash 500 ml", "Palmolive Almond Milk käsisaippua 500 ml", unit="L")]
CATALOG = test_kind.CATALOG + PLANT + HAND_WASH


def milk_only_search(db, query, filters, limit, kitchen_id=None):
    """The live search before #1711: "almond milk" found only names with "milk" (cow's
    milk, the hand wash), never the almond drinks; inside a category it finds the words."""
    words = query.lower().split()
    if filters.get("category") is None:
        words = [w for w in words if w in ("milk", "maito", "maitoa")]
    hits = [dict(r, score=200)
            for r in CATALOG
            if any(w in (r["names"]["en"] + " " + r["names"]["fi"]).lower().replace(",", " ").split() for w in words)
            and (filters.get("category") is None or r["category"] == filters["category"])]
    return hits[:limit]


@pytest.fixture()
def gateway(monkeypatch):
    monkeypatch.setenv("GATEWAY_HUMAN_TOKEN", "human-test-token")
    monkeypatch.setenv("GATEWAY_AGENT_TOKEN", "agent-test-token")
    db = mongomock.MongoClient(tz_aware=True)["test"]
    db.products.insert_many([{"_id": r["product_id"], **{k: v for k, v in r.items() if k != "product_id"}}
                             for r in CATALOG])
    for pid, raw in RAW.items():     # the recorded Valio milks, cow's milk in category 10400
        db.products.insert_one({"_id": pid, "category": "10400", "names": {"en": f"Valio milk {pid}"},
                                "source": "valio", "supplier_id": "valio_aimo", "raw": raw})
    valio = ValioClient("test-not-a-real-key", transport=FakeValio().transport, ttl=0, now=lambda: NOW)
    gw = Gateway(db, valio, now=lambda: NOW, search=milk_only_search)
    return TestClient(create_app(gw)), gw


def need(client, text, unit="L"):
    return client.post(K + "/needs", headers=AGENT, json={
        "quantity": "20", "unit": unit, "requested_date": "2026-11-16", "text": text}).json()


def shortlist(client, text, query):
    found = client.post("/tools/search_products", headers=AGENT, json={
        "query": query, "filters": {}, "need_id": need(client, text)["need_id"]})
    assert found.status_code == 200, found.text
    return found.json()


@pytest.mark.parametrize("text,plant", [
    ("20 L almond milk by Monday", "almond"),
    ("30 L oat milk by Monday", "oat"),
    ("20 L soy milk", "soya"), ("20 L soya drink", "soya"),
    ("20 L rice milk", "rice"), ("20 L coconut milk", "coconut"),
    ("50 L oat drinks, barista type", "oat"),
    ("20 L pea milk by Monday", "pea"),
    ("20 L vegan milk", ""),
    ("20 l mantelimaitoa maanantaiksi", "almond"),     # Finnish: one compound, partitive
    ("20 l kaurajuomaa maanantaiksi", "oat"),
    ("20 l soijamaitoa", "soya"), ("20 l kookosmaitoa", "coconut"),
    ("20 l kaura juomaa", "oat"),
    ("20 l havremjölk till måndag", "oat"),           # Swedish
    ("20 l mandeldryck", "almond"),
])
def test_a_plant_drink_is_read_in_english_finnish_and_swedish(text, plant):
    assert plant_drink(text) == plant


@pytest.mark.parametrize("text", [
    "1,000 L lactose-free milk by Monday", "200 L lactose free milk by Thursday",
    "1000 l laktoositonta maitoa maanantaiksi", "200 L milk", "20 l kahvimaitoa",
    "20 kg milk chocolate", "20 L chocolate milk", "20 L goat milk", "20 kg rice",
    "10 kg oatmeal", "20 L oat cream", "", None,
])
def test_cows_milk_and_other_words_are_not_a_plant_drink(text):
    assert plant_drink(text) is None


def test_only_a_plant_drink_of_that_plant_is_that_kind():
    almond, oat, coconut = PLANT[0], PLANT[2], PLANT[5]
    assert is_plant_drink(almond, "almond") and not is_plant_drink(oat, "almond")
    assert is_plant_drink(coconut, "coconut") and is_plant_drink(oat, "")
    assert not is_plant_drink(MILK[0], "almond")             # cow's milk
    assert not is_plant_drink(HAND_WASH[0], "almond")        # "Almond Milk" hand wash
    assert not is_plant_drink(None, "almond")                # unknown is not the kind asked
    own = {"product_id": "own1", "source": "own", "names": {"en": "House almond milk 1 l"}}
    assert is_plant_drink(own, "almond") and not is_plant_drink(own, "oat")


def test_almond_milk_gets_almond_drinks_never_cows_milk(gateway):
    client, _ = gateway
    found = shortlist(client, "20 L almond milk by Monday", "almond milk")
    assert [p["product_id"] for p in found["products"]] == ["pd0", "pd1"]


def test_the_model_searching_milk_still_gets_no_cows_milk(gateway):
    client, _ = gateway
    found = shortlist(client, "20 L almond milk by Monday", "milk")
    assert {p["product_id"] for p in found["products"]} == {"pd0", "pd1"}


def test_finnish_and_swedish_plant_drinks_are_searched_with_the_catalogs_words(gateway):
    client, _ = gateway
    assert {p["product_id"] for p in shortlist(client, "20 l mantelimaitoa maanantaiksi", "mantelimaitoa")["products"]} == {"pd0", "pd1"}
    assert {p["product_id"] for p in shortlist(client, "20 l havremjölk till måndag", "havremjölk")["products"]} == {"pd2", "pd3"}


def test_a_plant_drink_the_catalog_has_not_is_said_plainly(gateway):
    client, _ = gateway
    found = shortlist(client, "20 L pea milk by Monday", "pea milk")
    assert found["products"] == []
    assert "no pea drink" in found["note"] and "Cow's milk" in found["note"]


def test_the_parser_path_proposes_almond_drinks(gateway):
    _, gw = gateway
    read = gw._from_text("demo-kitchen", {"text": "20 L almond milk by Monday", "idempotency_key": "k"})
    assert read["product_ids"] == ["pd0", "pd1"]
    fi = gw._from_text("demo-kitchen", {"text": "20 l mantelimaitoa maanantaiksi", "idempotency_key": "k2"})
    assert fi["product_ids"] == ["pd0", "pd1"]


def test_the_parser_path_refuses_a_missing_plant_drink_with_the_reason(gateway):
    client, _ = gateway
    for text in ("20 L pea milk by Monday", "20 l hernemaitoa maanantaiksi"):
        r = client.post(K + "/proposals", headers=AGENT, json={"text": text, "idempotency_key": text})
        assert r.status_code == 422, r.text
        error = r.json()["error"]
        assert error["code"] == "NO_PRODUCTS_FOUND"
        assert "no pea drink" in error["message"] and "Cow's milk" in error["message"]


def test_a_quote_for_almond_milk_leaves_cows_milk_out_and_says_why(gateway):
    """The Buyer may quote any code it found with a plain search: the quote still never
    gives cow's milk for almond milk. It is listed under excluded, with the reason."""
    client, _ = gateway
    n = need(client, "20 L almond milk by Monday")
    offer = client.post("/tools/get_offer", headers=AGENT, json={
        "need_id": n["need_id"], "product_ids": list(RAW)}).json()
    assert offer["lines"] == []
    reasons = {e["product_id"]: e["reason"] for e in offer["excluded"]}
    assert set(reasons) == set(RAW)
    assert all(why.startswith("not the almond drink asked") for why in reasons.values())
    assert offer["mandate"]["reasons"][0].startswith("not the almond drink asked")


def test_a_lactose_free_milk_quote_is_not_touched(gateway):
    """The rehearsed 1,000 L and 200 L stories (golden scenarios S01) keep their lines."""
    client, _ = gateway
    for quantity in ("1000", "200"):
        n = client.post(K + "/needs", headers=AGENT, json={
            "quantity": quantity, "unit": "L", "requested_date": "2026-11-16",
            "text": f"{quantity} L lactose-free milk by Monday"}).json()
        offer = client.post("/tools/get_offer", headers=AGENT, json={
            "need_id": n["need_id"], "product_ids": list(RAW)}).json()
        assert offer["lines"], offer
        assert not any("drink asked" in e["reason"] for e in offer["excluded"])
        assert not any("drink asked" in r for r in offer["mandate"]["reasons"])


def test_the_parser_path_never_quotes_cows_milk_for_almond_milk_and_says_why(gateway):
    """A word link to cow's milk (or any other code) still does not answer "almond milk":
    the proposal has no line, and excluded and the mandate say why."""
    from gateway import memory
    client, gw = gateway
    memory.set_alias(gw.db, "demo-kitchen", "almond milk", "462775", "chef")
    r = client.post(K + "/proposals", headers=AGENT, json={
        "text": "20 L almond milk by Monday", "idempotency_key": "alias-almond"})
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["status"] == "REJECTED" and p["lines"] == []
    assert [(e["product_id"], e["reason"]) for e in p["excluded"]] == [
        ("462775", "not the almond drink asked: no other kind of product is proposed in its place")]
    assert p["mandate"]["reasons"][0].startswith("not the almond drink asked")
