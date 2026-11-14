"""#1384: when the Buyer's word search finds nothing, Atlas Vector Search runs once for the
same query and the same hard filters. Fakes only: no embedding call, no Atlas."""

import pytest

mongomock = pytest.importorskip("mongomock")

from gateway.service import Gateway  # noqa: E402
from gateway.tests.test_gateway_app import NOW, RAW, FakeValio  # noqa: E402
from gateway.valio_client import ValioClient  # noqa: E402
from store.embeddings import EmbeddingError  # noqa: E402

KITCHEN = "test-kitchen"
FOUND_BY_MEANING = "Found by meaning (Atlas Vector Search) after the word search found nothing."


def row(pid, name, contains=(), may_contain=(), known=True, unit="L", reasons=()):
    return {"product_id": pid, "names": {"en": name}, "allergen_data_known": known,
            "allergens": {"contains": list(contains), "may_contain": list(may_contain), "undeclared": []},
            "net_content": {"value": 1.0, "unit": unit}, "match_reasons": list(reasons)}


MILK = [row("462775", "Valio Zero lactose milk drink fat free 1 l"),
        row("462921", "Valio lactose free milk drink 5 l"),
        row("463335", "Valio Eila milk drink 3 % 1 l")]
for _row in MILK:
    _row["lactose_free"] = True      # the catalog's own flag: a lactose-free need keeps them (#1869)
BY_MEANING = [row(r["product_id"], r["names"]["en"], reasons=["similar meaning, no word match"]) for r in MILK]


def words(db, query, filters, limit, kitchen_id=None):
    """The word search: the rehearsed words find milk, a typo or a Finnish phrase finds nothing."""
    q = query.lower()
    return [dict(r) for r in MILK][:limit] if "lactose-free milk" in q or "lactose free milk" in q else []


class Meaning:
    """A fake vector search: records every call, gives `rows` or raises `fail`."""

    def __init__(self, rows=BY_MEANING, fail=None):
        self.rows, self.fail, self.calls = rows, fail, []

    def __call__(self, db, query, filters, limit, kitchen_id=None):
        self.calls.append({"query": query, "filters": dict(filters), "limit": limit, "kitchen_id": kitchen_id})
        if self.fail:
            raise self.fail
        return [dict(r) for r in self.rows][:limit]


def gateway(search=words, meaning=None):
    db = mongomock.MongoClient(tz_aware=True)["test"]
    for pid, raw in RAW.items():
        db.products.insert_one({"_id": pid, "names": {"en": f"milk {pid}"}, "lactose_free": True, "raw": raw})
    valio = ValioClient("test-not-a-real-key", transport=FakeValio().transport, ttl=0, now=lambda: NOW)
    return Gateway(db, valio, now=lambda: NOW, search=search, meaning=meaning)


def need(gw, text, quantity="20", unit="L"):
    return gw.create_need(KITCHEN, {"quantity": quantity, "unit": unit, "requested_date": "2026-11-16",
                                    "text": text}, "buyer-agent")["need_id"]


@pytest.mark.parametrize("text", ["20 L talon maito", "20 L lactos fre milk"])
def test_a_word_miss_finds_products_by_meaning(text):
    meaning = Meaning()
    gw = gateway(meaning=meaning)
    query = text.removeprefix("20 L ")
    filters = {"exclude_allergens": ["peanuts"], "allergen_strictness": "strict"}
    found = gw.tool_search(KITCHEN, query, filters, 20, need(gw, text))
    assert found["search"] == "meaning-fallback"
    assert sorted(p["product_id"] for p in found["products"]) == ["462775", "462921", "463335"]
    assert all("similar meaning, no word match" in p["match_reasons"] for p in found["products"])
    assert all(p["matched_by"] == "meaning" for p in found["products"])          # #1382's field
    assert "found by meaning (Atlas Vector Search) after the word search found nothing" in found["note"]
    # Once, with the same query and the same hard filters as the word search.
    assert [(c["query"], c["filters"]) for c in meaning.calls] == [(query, filters)]


def test_the_proposal_says_it_was_found_by_meaning():
    gw = gateway(meaning=Meaning())
    need_id = need(gw, "20 L talon maito")
    found = gw.tool_search(KITCHEN, "talon maito", {}, 20, need_id)
    offer = gw.tool_get_offer(KITCHEN, {"need_id": need_id, "product_ids": [found["products"][0]["product_id"]]})
    approval = gw.tool_request_approval(KITCHEN, {"offer_id": offer["offer_id"], "idempotency_key": "m1"},
                                        "buyer-agent")
    proposal = gw.get_proposal(KITCHEN, approval["proposal_id"])
    assert proposal["request"]["search"] == "meaning-fallback"
    assert proposal["decision_summary"]["searched"].endswith(FOUND_BY_MEANING)
    assert FOUND_BY_MEANING in proposal["decision_summary"]["text"]


def test_a_product_found_by_words_is_not_marked():
    gw = gateway(meaning=Meaning())
    need_id = need(gw, "20 L lactose-free milk")
    gw.tool_search(KITCHEN, "lactose-free milk", {}, 20, need_id)
    offer = gw.tool_get_offer(KITCHEN, {"need_id": need_id, "product_ids": ["462775"]})
    approval = gw.tool_request_approval(KITCHEN, {"offer_id": offer["offer_id"], "idempotency_key": "w1"},
                                        "buyer-agent")
    proposal = gw.get_proposal(KITCHEN, approval["proposal_id"])
    assert "search" not in proposal["request"]
    assert FOUND_BY_MEANING not in proposal["decision_summary"]["text"]


@pytest.mark.parametrize("text, quantity", [("1000 L lactose-free milk by Monday", "1000"),
                                            ("200 L lactose-free milk by Monday", "200")])
def test_the_rehearsed_requests_give_the_same_rows_as_before(text, quantity):
    meaning = Meaning()
    with_fallback, before = gateway(meaning=meaning), gateway()
    a = with_fallback.tool_search(KITCHEN, "lactose-free milk", {}, 20, need(with_fallback, text, quantity))
    b = before.tool_search(KITCHEN, "lactose-free milk", {}, 20, need(before, text, quantity))
    assert a == b and a["search"] == "text" and a["products"]
    assert meaning.calls == []                       # the words found products: no vector search


def test_an_excluded_allergen_never_comes_back():
    """The vector side may return a product the group rule refuses (a product that declares
    only the tree-nut group when almonds are excluded) or one with unknown allergen data
    under strict: the gateway drops both."""
    meaning = Meaning(rows=[row("462775", "almond drink", contains=["AN"]),
                            row("462921", "oat drink", known=False),
                            row("463335", "oat drink may contain almond", may_contain=["SA"]),
                            row("999001", "plain oat drink 1 l")])
    gw = gateway(meaning=meaning)
    filters = {"exclude_allergens": ["SA"], "allergen_strictness": "strict"}
    found = gw.tool_search(KITCHEN, "kaurajuoma", filters, 20, need(gw, "20 L kaurajuoma"))
    assert [p["product_id"] for p in found["products"]] == ["999001"]


def test_the_kitchen_allergen_rule_applies_to_the_meaning_rows_too():
    meaning = Meaning(rows=[row("462775", "peanut drink", contains=["AP"]), row("999001", "oat drink 1 l")])
    gw = gateway(meaning=meaning)
    gw.db.kitchen_settings.insert_one({"_id": KITCHEN, "excluded_allergens": ["AP"]})
    found = gw.tool_search(KITCHEN, "kaurajuoma", {}, 20, need(gw, "20 L kaurajuoma"))
    assert [p["product_id"] for p in found["products"]] == ["999001"]


PEANUT_BUTTER = [row("472710", "Snickers Creamy Peanut Butter bar", ["AN", "AP"], unit="KG"),
                 row("467313", "Biona Organic Peanut butter smooth 1kg", ["AN", "AP", "AS"], unit="KG")]


def test_peanut_butter_stays_refused_and_nothing_is_found_by_meaning():
    def peanut_words(db, query, filters, limit, kitchen_id=None):
        return [dict(r) for r in PEANUT_BUTTER] if "peanut butter" in query.lower() else []

    meaning = Meaning(rows=[row("999002", "Sunflower seed butter 1 kg", unit="KG")])
    gw = gateway(search=peanut_words, meaning=meaning)
    gw.db.kitchen_settings.insert_one({"_id": KITCHEN, "excluded_allergens": ["AP", "AN", "AS"]})
    need_id = need(gw, "15 kg peanut butter", "15", "KG")
    for query in ("peanut butter", "seed spread"):   # whatever the model asks
        found = gw.tool_search(KITCHEN, query, {"exclude_allergens": ["AP", "AN", "AS"]}, 20, need_id)
        assert found["products"] == [] and found["search"] == "text"
        assert found["note"].startswith("This kitchen excludes peanuts")
    assert meaning.calls == []


def test_products_removed_by_the_allergen_filter_are_not_replaced_by_meaning():
    """No refusal stored (the kitchen has no rule), but the caller's allergen filter removes
    every product the words find: the meaning search must not find something in their place."""
    def filtered_words(db, query, filters, limit, kitchen_id=None):
        if filters.get("exclude_allergens"):
            return []
        return [dict(r) for r in PEANUT_BUTTER] if "peanut butter" in query.lower() else []

    meaning = Meaning(rows=[row("999002", "Sunflower seed butter 1 kg", unit="KG")])
    gw = gateway(search=filtered_words, meaning=meaning)
    found = gw.tool_search(KITCHEN, "peanut butter", {"exclude_allergens": ["peanuts"]}, 20,
                           need(gw, "15 kg peanut butter", "15", "KG"))
    assert found["products"] == [] and found["search"] == "text"
    assert "allergen filter removes" in found["note"]
    assert meaning.calls == []


@pytest.mark.parametrize("failure", [EmbeddingError("embedding request failed: rate-limited"),
                                     TimeoutError("slow"), RuntimeError("no such index: products_vector")])
def test_when_the_query_vector_cannot_be_made_the_answer_stays_empty_with_a_note(failure):
    meaning = Meaning(fail=failure)
    gw = gateway(meaning=meaning)
    found = gw.tool_search(KITCHEN, "talon maito", {}, 20, need(gw, "20 L talon maito"))
    assert found["products"] == [] and found["search"] == "text"
    assert "meaning search could not run" in found["note"]
    assert len(meaning.calls) == 1


def test_a_search_without_a_meaning_search_stays_as_today():
    """An offline gateway with an injected word search and no meaning search: no fallback."""
    gw = gateway()
    found = gw.tool_search(KITCHEN, "talon maito", {}, 20, need(gw, "20 L talon maito"))
    assert found["products"] == [] and found["search"] == "text"
