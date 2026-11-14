"""One request with several products becomes one proposal (#1375).

The list body `needs: [{text, quantity, unit}]` and a free text with several products, split
by Nemotron (mocked here) and checked by plain code, or split by plain code with the model
off. One total, the supplier blocks, one approval, signed. A need that cannot be ordered is
listed with its reason and the others go on."""

import asyncio

import pytest

mongomock = pytest.importorskip("mongomock")
pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from gateway import autoapprove  # noqa: E402
from gateway.app import create_app  # noqa: E402
from gateway.service import Gateway  # noqa: E402
from gateway.tests.test_excluded_request import BUTTER, PEANUT_BUTTER  # noqa: E402
from gateway.tests.test_gateway_app import AGENT, HUMAN, K, NOW, RAW, FakeValio  # noqa: E402
from gateway.tests.test_multi_supplier import BAKERY_DAYS, OAT, bakery  # noqa: E402
from gateway.valio_client import ValioClient  # noqa: E402

MON = "2026-11-16"        # NOW is Friday evening in Helsinki: "Monday" is the 16th
MILK = ("462775", "462921", "463335")


def search(db, query, filters, limit, kitchen_id=None):
    if "peanut" in query:
        return [dict(r) for r in PEANUT_BUTTER + BUTTER]
    if "oat" in query:
        return [{"product_id": OAT, "names": {"en": "Oat drink 1 L"}}]
    if "milk" in query:
        return [{"product_id": pid, "names": {"en": f"milk {pid}"}, "lactose_free": True} for pid in MILK]
    return []


@pytest.fixture()
def kitchen(monkeypatch):
    monkeypatch.setenv("GATEWAY_HUMAN_TOKEN", "human-test-token")
    monkeypatch.setenv("GATEWAY_AGENT_TOKEN", "agent-test-token")
    monkeypatch.delenv("BUYER_WORKER_URL", raising=False)
    db = mongomock.MongoClient(tz_aware=True)["test"]
    for pid, raw in RAW.items():
        db.products.insert_one({"_id": pid, "names": {"en": f"milk {pid}"}, "lactose_free": True, "raw": raw})
    for r in PEANUT_BUTTER + BUTTER:
        db.products.insert_one({"_id": r["product_id"], **{k: v for k, v in r.items() if k != "product_id"}})
    bakery(db, {**BAKERY_DAYS, "free_delivery_threshold_eur": "100.00", "delivery_fee_eur": "9.50"})
    db.kitchen_settings.insert_one({"_id": "demo-kitchen", "excluded_allergens": ["AP"]})
    gw = Gateway(db, ValioClient("test-not-a-real-key", transport=FakeValio().transport, ttl=0, now=lambda: NOW),
                 now=lambda: NOW, search=search)
    calls = {"buyer": [], "split": []}
    replies = {"split": None}

    async def buyer(kitchen_id, body):
        calls["buyer"].append(body["text"])
        return {"proposal_id": "from-the-buyer", "status": "READY", "lines": []}

    async def splitter(kitchen_id, text):
        calls["split"].append(text)
        reply = replies["split"]
        if isinstance(reply, BaseException):
            raise reply
        return reply

    app = create_app(gw, buyer_worker=buyer, split_worker=splitter)
    return TestClient(app), db, calls, replies


def post(client, body, status=200):
    r = client.post(K + "/proposals", headers=AGENT, json=body)
    assert r.status_code == status, r.text
    return r.json()


def two(key="l1", **extra):
    return {"needs": [{"text": "milk", "quantity": "51", "unit": "L"},
                      {"text": "oat drink", "quantity": "20", "unit": "l"}],
            "requested_date": MON, "idempotency_key": key, **extra}


# ---- the list body ---------------------------------------------------------------------

def test_a_list_across_two_suppliers_is_one_proposal_one_total_one_approval_signed(kitchen):
    client, db, calls, _ = kitchen
    p = post(client, two(text="51 L milk and 20 L oat drink"))
    assert p["status"] == "READY" and p["approval_id"] and p["offer_hash"] and p["signature"]
    assert [(ln["product_id"], ln["quantity"]) for ln in p["lines"]] == [("462775", "51"), (OAT, "20")]
    assert [b["supplier_id"] for b in p["blocks"]] == ["sup-valio", "sup-bakery"]
    assert sum(float(b["expected_total"]) for b in p["blocks"]) == pytest.approx(float(p["expected_total"]))
    req = p["request"]
    assert req["made_by"] == "list" and req["quantity"] == "2" and req["unit"] == "products"
    assert [i["result"] for i in req["items"]] == ["proposed", "proposed"]
    assert req["items"][1]["unit"] == "L" and req["problems"] == []
    assert "NEED_REFUSED" not in p["mandate"]["reason_codes"]
    assert "needs" not in req                        # request.needs is the menu plan's shape
    assert p["model_trace"]["made_by"] == "rule"
    assert calls == {"buyer": [], "split": []}       # no model call for a list
    assert db.approvals.count_documents({}) == 1


def test_a_need_the_allergen_rule_refuses_is_listed_and_the_others_go_on(kitchen):
    client, _, _, _ = kitchen
    body = {"needs": [{"text": "milk", "quantity": "51", "unit": "L"},
                      {"text": "peanut butter", "quantity": "5", "unit": "KG"}],
            "requested_date": MON, "idempotency_key": "a1"}
    p = post(client, body)
    assert p["status"] == "READY" and [ln["product_id"] for ln in p["lines"]] == ["462775"]
    milk, pb = p["request"]["items"]
    assert milk["result"] == "proposed"
    assert pb["result"] == "refused" and pb["problem"]["code"] == "ALLERGEN_RULE"
    assert pb["problem"]["allergens"] == ["peanuts"]
    assert p["request"]["problems"] == [f"5 KG peanut butter: {pb['problem']['message']}"]
    assert pb["problem"]["message"].startswith('This kitchen excludes peanuts, so "peanut butter"')
    assert p["mandate"]["reasons"][0] == p["request"]["problems"][0]
    assert {"ALLERGEN_RULE", "NEED_REFUSED"} <= set(p["mandate"]["reason_codes"])
    assert "Not proposed: 5 KG peanut butter" in p["decision_summary"]["text"]
    assert "NEED_REFUSED" in autoapprove.NEVER_CODES  # a person sees what was left out


def test_the_allergen_rule_runs_before_the_kitchens_own_words(kitchen):
    """An alias that points to a product with no allergen data is no way around #974."""
    client, db, _, _ = kitchen
    from gateway import memory
    memory.set_alias(db, "demo-kitchen", "peanut butter", "464315", "aron")    # PCD: no allergen data
    assert memory.lookup(db, "demo-kitchen", "peanut butter") == "464315"
    body = {"needs": [{"text": "milk", "quantity": "51", "unit": "L"},
                      {"text": "peanut butter", "quantity": "5", "unit": "KG"}],
            "requested_date": MON, "idempotency_key": "a2"}
    p = post(client, body)
    assert p["request"]["items"][1]["problem"]["code"] == "ALLERGEN_RULE"
    assert "464315" not in [ln["product_id"] for ln in p["lines"]]


def test_every_need_refused_is_a_rejected_proposal(kitchen):
    client, _, _, _ = kitchen
    body = {"needs": [{"text": "peanut butter", "quantity": "5", "unit": "KG"},
                      {"text": "unicorn steak", "quantity": "3", "unit": "KG"}],
            "requested_date": MON, "idempotency_key": "r1"}
    p = post(client, body)
    assert p["status"] == "REJECTED" and p["lines"] == [] and p["approval_id"] is None
    assert p["mandate"]["verdict"] == "REFUSED"
    assert [i["problem"]["code"] for i in p["request"]["items"]] == ["ALLERGEN_RULE", "NO_PRODUCTS_FOUND"]
    assert p["expected_total"] == "0.00" and "PARTIAL_STOCK" not in p["mandate"]["reason_codes"]
    assert "Nothing can be ordered. 5 KG peanut butter" in p["decision_summary"]["text"]


def test_a_need_whose_products_are_on_the_proposal_already_says_so(kitchen):
    client, _, _, _ = kitchen
    body = {"needs": [{"text": "milk", "quantity": "51", "unit": "L"},
                      {"text": "lactose free milk", "quantity": "10", "unit": "L"}],
            "requested_date": MON, "idempotency_key": "d1"}
    p = post(client, body)
    second = p["request"]["items"][1]
    # The second need is priced on what is left (463335, 462921): never the same line twice.
    ids = [ln["product_id"] for ln in p["lines"]]
    assert len(ids) == len(set(ids)) and ids[0] == "462775"
    assert second["result"] == "proposed" and "462775" not in ids[1:]


def test_a_need_left_with_no_product_of_its_own_is_not_available(kitchen):
    client, db, _, _ = kitchen
    from gateway import memory
    memory.set_alias(db, "demo-kitchen", "house milk", "462775", "aron")
    body = {"needs": [{"text": "milk", "quantity": "51", "unit": "L"},
                      {"text": "house milk", "quantity": "5", "unit": "L"}],
            "requested_date": MON, "idempotency_key": "d2"}
    second = post(client, body)["request"]["items"][1]
    assert second["result"] == "refused" and second["problem"]["code"] == "NOT_AVAILABLE"
    assert second["problem"]["message"].startswith("same product as need 1")


def test_a_replay_returns_the_same_proposal_and_another_body_is_a_conflict(kitchen):
    client, db, _, _ = kitchen
    first = post(client, two("k1"))
    assert post(client, two("k1"))["proposal_id"] == first["proposal_id"]
    changed = two("k1")
    changed["needs"][0]["quantity"] = "52"
    r = client.post(K + "/proposals", headers=AGENT, json=changed)
    assert r.status_code == 409 and r.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    assert db.proposals.count_documents({}) == 1


@pytest.mark.parametrize("needs,why", [
    ([{"text": "milk", "quantity": "51", "unit": "L"}], "2 to 30 rows"),
    ([{"text": f"milk {chr(97 + n % 26)}{n}", "quantity": "1", "unit": "L"} for n in range(31)], "2 to 30 rows"),
    ([{"text": "milk", "quantity": "0", "unit": "L"}, {"text": "oat drink", "quantity": "1", "unit": "L"}], "need 1"),
    ([{"text": "milk", "quantity": "Infinity", "unit": "L"}, {"text": "oat", "quantity": "1", "unit": "L"}], "need 1"),
    ([{"text": "milk", "quantity": "1", "unit": "BOX"}, {"text": "oat", "quantity": "1", "unit": "L"}], "unit"),
    ([{"text": "milk", "quantity": "1", "unit": "L"}, {"text": "Milk", "quantity": "2", "unit": "L"}], "same product"),
    ([{"text": "milk", "quantity": "1", "unit": "L"}, {"text": "  ", "quantity": "2", "unit": "L"}], "need 2"),
])
def test_a_bad_list_is_refused_with_the_row_named(kitchen, needs, why):
    client, db, _, _ = kitchen
    r = client.post(K + "/proposals", headers=AGENT,
                    json={"needs": needs, "requested_date": MON, "idempotency_key": "bad"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_REQUEST"
    assert why in r.json()["error"]["message"]
    assert db.proposals.count_documents({}) == 0


def test_grams_are_read_as_kilos(kitchen):
    client, _, _, _ = kitchen
    body = {"needs": [{"text": "milk", "quantity": "51", "unit": "L"},
                      {"text": "unicorn", "quantity": "500", "unit": "G"}],
            "requested_date": MON, "idempotency_key": "g1"}
    item = post(client, body)["request"]["items"][1]
    assert (item["quantity"], item["unit"]) == ("0.5", "KG")


# ---- free text with several products ------------------------------------------------------

TEXT = "51 L milk and 20 L oat drink by Monday"


def test_free_text_split_by_the_model_is_one_proposal_and_the_buyer_never_runs(kitchen):
    client, _, calls, replies = kitchen
    replies["split"] = [{"text": "milk", "quantity": "51", "unit": "L"},
                        {"text": "oat drink", "quantity": "20", "unit": "L"}]
    p = post(client, {"text": TEXT, "requested_date": "2026-11-20", "idempotency_key": "t1"})
    assert p["status"] == "READY" and len(p["lines"]) == 2 and len(p["blocks"]) == 2
    assert p["request"]["split_by"] == "model" and p["request"]["text"] == TEXT
    assert p["request"]["requested_date"] == MON           # the day in the text wins over the form
    assert calls["split"] == [TEXT] and calls["buyer"] == []
    again = post(client, {"text": TEXT, "requested_date": "2026-11-20", "idempotency_key": "t1"})
    assert again["proposal_id"] == p["proposal_id"] and calls["split"] == [TEXT]   # no second model call
    r = client.post(K + "/proposals", headers=AGENT, json={"text": TEXT + "!", "idempotency_key": "t1"})
    assert r.status_code == 409


@pytest.mark.parametrize("split", [
    [{"text": "milk", "quantity": "510", "unit": "L"}, {"text": "oat drink", "quantity": "20", "unit": "L"}],
    [{"text": "milk", "quantity": "51", "unit": "L"}, {"text": "oat drink", "quantity": "20", "unit": "L"},
     {"text": "butter", "quantity": "5", "unit": "KG"}],
    [{"text": "oat drink", "quantity": "51", "unit": "L"}, {"text": "milk", "quantity": "20", "unit": "L"}],
    [{"text": "cream", "quantity": "51", "unit": "L"}, {"text": "oat drink", "quantity": "20", "unit": "L"}],
])
def test_a_split_that_invents_adds_or_swaps_is_refused(kitchen, split):
    client, db, _, replies = kitchen
    replies["split"] = split
    r = client.post(K + "/proposals", headers=AGENT, json={"text": TEXT, "idempotency_key": "x1"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "CANNOT_READ_REQUEST"
    assert r.json()["error"]["message"].startswith("one product per request")
    assert db.proposals.count_documents({}) == 0


def test_with_the_model_off_plain_code_splits_the_text(kitchen):
    client, _, calls, _ = kitchen      # the split worker answers None: not configured
    p = post(client, {"text": "51 L milk, 20 L oat drink and 3 unicorns for Monday", "idempotency_key": "o1"})
    assert p["request"]["split_by"] == "rules" and calls["buyer"] == []
    assert [(i["text"], i["quantity"], i["unit"]) for i in p["request"]["items"]] == [
        ("milk", "51", "L"), ("oat drink", "20", "L"), ("unicorns", "3", "ST")]
    assert p["status"] == "READY" and p["request"]["items"][2]["problem"]["code"] == "NO_PRODUCTS_FOUND"


def test_a_failing_model_falls_back_to_plain_code(kitchen):
    client, _, _, replies = kitchen
    replies["split"] = RuntimeError("upstream text https://secret.example")
    p = post(client, {"text": TEXT, "idempotency_key": "f1"})
    assert p["request"]["split_by"] == "rules" and "secret" not in str(p)


def test_a_split_timeout_skips_the_model_but_not_the_buyer(kitchen):
    client, _, calls, replies = kitchen
    replies["split"] = asyncio.TimeoutError()
    assert post(client, {"text": TEXT, "idempotency_key": "b1"})["request"]["split_by"] == "rules"
    replies["split"] = [{"text": "milk", "quantity": "51", "unit": "L"},
                        {"text": "oat drink", "quantity": "20", "unit": "L"}]
    assert post(client, {"text": TEXT, "idempotency_key": "b2"})["request"]["split_by"] == "rules"
    assert len(calls["split"]) == 1                       # the split breaker is open
    post(client, {"text": "51 L milk by Monday", "idempotency_key": "b3"})
    assert calls["buyer"] == ["51 L milk by Monday"]      # one product: the Buyer as before


def test_two_delivery_days_in_one_text_are_refused(kitchen):
    client, _, calls, _ = kitchen
    r = client.post(K + "/proposals", headers=AGENT,
                    json={"text": "51 L milk for Monday and 20 L oat drink for Tuesday", "idempotency_key": "d2"})
    assert r.status_code == 422 and r.json()["error"]["message"].startswith("one delivery day per request")
    assert calls == {"buyer": [], "split": []}


def test_a_text_with_no_day_takes_the_form_day_and_none_is_refused(kitchen):
    client, _, _, _ = kitchen
    p = post(client, {"text": "51 L milk and 20 L oat drink", "requested_date": MON, "idempotency_key": "n1"})
    assert p["request"]["requested_date"] == MON
    r = client.post(K + "/proposals", headers=AGENT, json={"text": "51 L milk and 20 L oat drink",
                                                           "idempotency_key": "n2"})
    assert r.status_code == 422 and "no delivery day" in r.json()["error"]["message"]


def test_a_part_with_no_product_words_is_refused(kitchen):
    client, _, _, _ = kitchen
    r = client.post(K + "/proposals", headers=AGENT, json={"text": "51 L milk and 20 L by Monday",
                                                           "idempotency_key": "w1"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "CANNOT_READ_REQUEST"


def test_a_list_proposal_is_approved_once_like_any_proposal(kitchen):
    client, db, _, _ = kitchen
    p = post(client, two("ap1"))
    r = client.post(f"{K}/proposals/{p['proposal_id']}/approve", headers=HUMAN,
                    json={"expected_total": p["expected_total"], "idempotency_key": "ap1"})
    assert r.status_code == 200, r.text
    assert db.orders.count_documents({}) == 1
    assert {ln["product_id"] for ln in r.json()["lines"]} == {"462775", OAT}


def test_a_person_can_change_a_list_proposal(kitchen):
    client, _, _, _ = kitchen
    body = {"needs": [{"text": "milk", "quantity": "51", "unit": "L"},
                      {"text": "peanut butter", "quantity": "5", "unit": "KG"}],
            "requested_date": MON, "idempotency_key": "c1"}
    p = post(client, body)
    r = client.post(f"{K}/proposals/{p['proposal_id']}/change", headers=HUMAN,
                    json={"idempotency_key": "ch1", "lines": [{"product_id": "462775", "quantity": "40"}]})
    assert r.status_code == 200, r.text
    changed = r.json()
    assert [(ln["product_id"], ln["quantity"]) for ln in changed["lines"]] == [("462775", "40")]
    assert changed["request"]["problems"] == p["request"]["problems"]       # the refused need stays said
    assert changed["request"]["made_by"] == "list" and len(changed["request"]["items"]) == 2
