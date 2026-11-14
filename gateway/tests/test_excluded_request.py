"""#974: a kitchen that excludes peanuts asks for peanut butter. The answer is a refusal
that names the allergen, never plain butter. Rows below copy the names and allergen facts
of the live catalog search (2026-11-14)."""

import pytest

mongomock = pytest.importorskip("mongomock")
pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from gateway.app import create_app  # noqa: E402
from gateway.parse import parse_request, product_words  # noqa: E402
from gateway.refusal import excluded_request  # noqa: E402
from gateway.service import Gateway  # noqa: E402
from gateway.tests.test_gateway_app import AGENT, K, NOW, RAW, FakeValio  # noqa: E402
from gateway.valio_client import ValioClient  # noqa: E402

DEMO_RULE = ("AN", "AP", "AS", "SA", "SC", "SH", "SM", "SP", "SR", "ST", "SW")   # AP, AN, AS expanded


def row(pid, name, contains=(), known=True, unit="KG"):
    return {"product_id": pid, "names": {"en": name}, "allergen_data_known": known,
            "allergens": {"contains": list(contains), "may_contain": [], "undeclared": []},
            "net_content": {"value": 1.0, "unit": unit}}


PEANUT_BUTTER = [
    row("472710", "24x Snickers Creamy Peanut Butter chocolate bar 36,5g", ["AN", "AP"]),
    row("473868", "URTEKRAM Organic Peanut Butter Smooth  230g", ["AN", "AP", "AS", "SA"]),
    row("464315", "PCD 500G PEANUT BUTTER", known=False),
    row("467313", "Biona Organic Peanut butter smooth 1kg", ["AN", "AP", "AS"]),
    row("465025", "Green Choice Creamy peanut butter organic 6x350g", ["AP", "AS", "SA"]),
]
BUTTER = [
    row("472127", "Porlammin Clarified butter 1,8kg"),
    row("476740", "Juustoportti Butter 200 g"),
]


def test_the_best_matches_are_all_refused_so_the_request_is_refused_and_names_the_allergen():
    got = excluded_request("peanut butter", PEANUT_BUTTER + BUTTER, DEMO_RULE)
    assert got["code"] == "ALLERGEN_RULE" and got["allergens"] == ["peanuts"]
    assert got["product_ids"] == ["472710", "473868", "467313", "465025"]      # the refused ones, never butter
    assert got["message"].startswith('This kitchen excludes peanuts, so "peanut butter" cannot be ordered')
    assert "no allergen data" in got["message"]                      # the PCD row: unknown is not safe


def test_a_request_where_only_some_matches_are_refused_goes_on():
    # "butter": peanut butter is refused, plain butter is not.
    assert excluded_request("butter", PEANUT_BUTTER + BUTTER, DEMO_RULE) is None
    # Oat drinks: one may contain nuts, the others do not.
    rows = [row("1", "Oatly Oat Drink Organic 1L", unit="L"), row("2", "Nutty Oat Drink 1L", ["SA"], unit="L")]
    assert excluded_request("oat drink", rows, DEMO_RULE) is None


def test_a_request_with_nothing_to_do_with_the_rule_does_not_change():
    rows = [row("466215", "Brunberg Lactose free milk chocolate 150 g"),
            row("464179", "Arla 10 L Novobox Suomi semi skimmed lactose free milk drink", unit="L")]
    assert excluded_request("lactose free milk", rows, DEMO_RULE) is None
    assert excluded_request("lactose free milk", rows, ()) is None           # no rule at all
    assert excluded_request("unicorn", rows, DEMO_RULE) is None             # no word matches a name
    assert excluded_request("", rows, DEMO_RULE) is None


def test_almond_milk_for_a_kitchen_without_tree_nuts():
    # The live catalog's only "almond milk" is a hand wash with no excluded allergen: it is
    # not this rule's job to judge it. A real almond drink is refused.
    wash = row("466273", "Palmolive Naturals Almond Milk liquid hand wash 300ml", unit="L")
    bar = row("472501", "12 x Rawbite Crunchy Almond fruit and nut bar 45g", ["AN", "SA"])
    assert excluded_request("almond milk", [wash, bar], DEMO_RULE) is None
    drink = row("9", "Alpro Almond milk drink 1L", ["SA"], unit="L")
    got = excluded_request("almond milk", [drink, bar], DEMO_RULE)
    assert got["allergens"] == ["tree nuts"] and got["product_ids"] == ["9"]


def test_missing_allergen_data_alone_never_refuses_a_request():
    rows = [row("468417", "OAT DRINK CHOCO 1 L", known=False, unit="L")]
    assert excluded_request("oat drink", rows, DEMO_RULE) is None
    # One declared hit among many rows without data is not enough either.
    rows = [row(str(n), "PCD PEANUT BUTTER", known=False) for n in range(3)] + [PEANUT_BUTTER[1]]
    assert excluded_request("peanut butter", rows, DEMO_RULE) is None


def test_extra_words_in_the_request_do_not_hide_the_refused_products():
    got = excluded_request("peanut butter dessert station", PEANUT_BUTTER + BUTTER, DEMO_RULE)
    assert got is not None and got["allergens"] == ["peanuts"]


def test_product_words_reads_a_text_with_or_without_a_day():
    assert product_words("15 kg peanut butter") == "peanut butter"
    assert product_words("1,000 L lactose-free milk by Monday") == "lactose free milk"
    assert product_words("1000 l laktoositonta maitoa maanantaiksi") == "laktoositon maito"
    assert product_words("") == ""
    for text in ("1,000 L lactose-free milk by Monday", "20 kg butter 16.11.", "60 l milk tomorrow"):
        assert product_words(text) == parse_request(text, NOW.date()).query


def test_the_parser_takes_the_day_of_the_form_only_when_asked():
    from datetime import date
    from gateway.parse import ParseError
    with pytest.raises(ParseError):
        parse_request("15 kg peanut butter", NOW.date())
    read = parse_request("15 kg peanut butter", NOW.date(), default_day=date(2026, 11, 16))
    assert read.requested_date == date(2026, 11, 16) and read.query == "peanut butter"
    named = parse_request("15 kg butter by Monday", NOW.date(), default_day=date(2026, 11, 20))
    assert named.requested_date == date(2026, 11, 16)          # the text wins


# ---- through the HTTP gateway ---------------------------------------------------------

def search(db, query, filters, limit, kitchen_id=None):
    if "peanut" in query:
        return [dict(r) for r in PEANUT_BUTTER + BUTTER]
    if "butter" in query:
        return [dict(r) for r in BUTTER + PEANUT_BUTTER]
    if "milk" not in query:
        return []
    return [{"product_id": d["_id"], "names": d["names"], "net_content": {"value": 1.0, "unit": "L"},
             "allergens": d.get("allergens"), "allergen_data_known": d.get("allergen_data_known")}
            for d in db.products.find({"_id": {"$in": sorted(RAW)}}).sort("_id", 1)]


@pytest.fixture()
def kitchen(monkeypatch):
    monkeypatch.setenv("GATEWAY_HUMAN_TOKEN", "human-test-token")
    monkeypatch.setenv("GATEWAY_AGENT_TOKEN", "agent-test-token")
    db = mongomock.MongoClient(tz_aware=True)["test"]
    for pid, raw in RAW.items():
        db.products.insert_one({"_id": pid, "names": {"en": f"milk {pid}"}, "raw": raw})
    for r in PEANUT_BUTTER + BUTTER:
        db.products.insert_one({"_id": r["product_id"], **{k: v for k, v in r.items() if k != "product_id"}})
    db.kitchen_settings.insert_one({"_id": "demo-kitchen", "excluded_allergens": ["AP", "AN", "AS"]})
    fake = FakeValio()
    gw = Gateway(db, ValioClient("test-not-a-real-key", transport=fake.transport, ttl=0, now=lambda: NOW),
                 now=lambda: NOW, search=search)
    calls = []

    async def buyer(kitchen_id, body):
        """A Buyer that does what the real one did: it proposes plain butter."""
        calls.append(body["text"])
        return {"proposal_id": "from-the-buyer", "status": "READY", "lines": [{"product_id": "472127"}]}

    return TestClient(create_app(gw, buyer_worker=buyer)), TestClient(create_app(gw)), db, calls


def refused(p):
    assert p["status"] == "REJECTED" and p["lines"] == [] and p["approval_id"] is None
    assert p["mandate"]["verdict"] == "REFUSED" and "ALLERGEN_RULE" in p["mandate"]["reason_codes"]
    assert p["mandate"]["reasons"][0].startswith(
        'This kitchen excludes peanuts, so "peanut butter" cannot be ordered')
    assert p["request"]["refusal"]["code"] == "ALLERGEN_RULE"
    assert p["request"]["refusal"]["allergens"] == ["peanuts"]
    assert p["request"]["refusal"]["message"] == p["mandate"]["reasons"][0]
    assert p["request"]["product_ids"] == ["472710", "473868", "467313", "465025"]
    assert {e["product_id"] for e in p["excluded"]} == {"472710", "473868", "467313", "465025"}
    assert p["request"]["refusal"]["message"] in p["decision_summary"]["text"]
    return p


def test_peanut_butter_is_refused_before_the_buyer_runs(kitchen):
    with_buyer, _, db, calls = kitchen
    body = {"text": "15 kg peanut butter", "requested_date": "2026-11-16", "idempotency_key": "pb1"}
    r = with_buyer.post(K + "/proposals", headers=AGENT, json=body)
    assert r.status_code == 200, r.text
    p = refused(r.json())
    assert calls == []                                    # the Buyer never saw the request
    assert p["request"]["made_by"] == "parser" and p["request"]["quantity"] == "15"
    again = with_buyer.post(K + "/proposals", headers=AGENT, json=body)
    assert again.json()["proposal_id"] == p["proposal_id"] and db.proposals.count_documents({}) == 1
    other = with_buyer.post(K + "/proposals", headers=AGENT, json={**body, "text": "15 kg butter"})
    assert other.status_code == 409 and other.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    assert calls == []


def test_a_request_the_rule_does_not_touch_still_goes_to_the_buyer(kitchen):
    with_buyer, _, _, calls = kitchen
    for n, text in enumerate(("60 kg butter", "200 L lactose-free milk by Monday", "some milk please")):
        r = with_buyer.post(K + "/proposals", headers=AGENT, json={
            "text": text, "requested_date": "2026-11-16", "idempotency_key": f"ok{n}"})
        assert r.status_code == 200 and r.json()["proposal_id"] == "from-the-buyer"
    assert calls == ["60 kg butter", "200 L lactose-free milk by Monday", "some milk please"]


def test_the_parser_path_refuses_it_too(kitchen):
    _, no_buyer, _, _ = kitchen
    r = no_buyer.post(K + "/proposals", headers=AGENT, json={
        "text": "15 kg peanut butter by Monday", "idempotency_key": "pb2"})
    assert r.status_code == 200, r.text
    refused(r.json())


def test_the_parser_path_still_proposes_when_only_some_matches_are_refused(kitchen):
    """Milk for a kitchen that excludes soy, which one of the three milks contains: the
    others are still proposed, the refused one is left out (S03 as before)."""
    _, no_buyer, db, _ = kitchen
    db.kitchen_settings.update_one({"_id": "demo-kitchen"}, {"$set": {"excluded_allergens": ["AY"]}})
    db.products.update_one({"_id": "463335"}, {"$set": {
        "allergen_data_known": True, "allergens": {"contains": ["AY"], "may_contain": [], "undeclared": []}}})
    db.products.update_one({"_id": "462775"}, {"$set": {
        "allergen_data_known": True, "allergens": {"contains": ["AM"], "may_contain": [], "undeclared": []}}})
    r = no_buyer.post(K + "/proposals", headers=AGENT, json={
        "text": "60 l milk by Monday", "idempotency_key": "some"})
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["status"] == "READY" and p["lines"] and "refusal" not in p["request"]
    assert all(ln["product_id"] != "463335" for ln in p["lines"])


def test_any_agent_on_the_tools_gets_the_refusal_not_butter(kitchen):
    """The Buyer worker, or any MCP client, with the stored need: the search is empty and
    says why, and an offer for plain butter comes back with no line."""
    _, client, _, _ = kitchen
    need = client.post(K + "/needs", headers=AGENT, json={
        "quantity": "15", "unit": "KG", "requested_date": "2026-11-16", "text": "15 kg peanut butter"}).json()
    assert set(need) == {"need_id", "quantity", "unit", "requested_date", "text"}
    for query in ("peanut butter", "butter"):
        found = client.post("/tools/search_products", headers=AGENT, json={
            "query": query, "filters": {}, "need_id": need["need_id"]}).json()
        assert found["products"] == [] and found["note"].startswith("This kitchen excludes peanuts")
    offer = client.post("/tools/get_offer", headers=AGENT, json={
        "need_id": need["need_id"], "product_ids": ["472127"], "requested_date": "2026-11-16"}).json()
    assert offer["lines"] == [] and offer["mandate"]["verdict"] == "REFUSED"
    assert offer["mandate"]["reasons"][0].startswith("This kitchen excludes peanuts")
    assert all(e["product_id"] != "472127" for e in offer["excluded"])
    r = client.post("/tools/request_approval", headers=AGENT, json={
        "offer_id": offer["offer_id"], "idempotency_key": "x"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "NOTHING_TO_APPROVE"


def test_a_need_for_plain_butter_is_searched_as_before(kitchen):
    _, client, _, _ = kitchen
    need = client.post(K + "/needs", headers=AGENT, json={
        "quantity": "60", "unit": "KG", "requested_date": "2026-11-16", "text": "60 kg butter"}).json()
    found = client.post("/tools/search_products", headers=AGENT, json={
        "query": "butter", "filters": {}, "need_id": need["need_id"]}).json()
    assert [p["product_id"] for p in found["products"]][:2] == ["472127", "476740"]
    assert found["note"].startswith("can_arrive false")
