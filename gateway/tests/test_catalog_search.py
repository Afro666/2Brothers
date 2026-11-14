"""The gateway's catalog search: hybrid behind a switch, text as the fallback."""

import re

import mongomock
import pytest
from fastapi.testclient import TestClient

from gateway.app import create_app
from gateway.service import Gateway
from gateway.tests import test_gateway_app as app_tests
from gateway.valio_client import ValioClient

from gateway import catalog_search
from store import embeddings, search as store_search


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    catalog_search.reset()
    monkeypatch.delenv("SEARCH_HYBRID", raising=False)
    yield
    catalog_search.reset()


def fake_store(monkeypatch, fail=None):
    """Replace store.search.search_products: records each call, may fail the hybrid one."""
    calls = []

    def search_products(db, query="", filters=None, limit=20, kitchen_id=None, hybrid=False, embedder=None):
        calls.append({"query": query, "hybrid": hybrid, "limit": limit, "kitchen_id": kitchen_id})
        if hybrid:
            if fail:
                raise fail
            embedder([query], "query")
        return [{"product_id": "462775"}]

    monkeypatch.setattr(store_search, "search_products", search_products)
    return calls


def test_off_by_default_only_the_text_search_runs(monkeypatch):
    calls = fake_store(monkeypatch)
    rows, kind = catalog_search.search(None, "lactose free milk", {}, 20, "k1")
    assert (rows, kind) == ([{"product_id": "462775"}], "text")
    assert [c["hybrid"] for c in calls] == [False]


def test_on_uses_hybrid_and_keeps_the_query_vector(monkeypatch):
    monkeypatch.setenv("SEARCH_HYBRID", "true")
    calls = fake_store(monkeypatch)
    embedded = []
    monkeypatch.setattr(embeddings, "embed", lambda texts, kind, post=None, sleep=None: (
        embedded.append(texts[0]), [[0.0] * embeddings.EMBED_DIMENSIONS])[1])
    assert catalog_search.search(None, "Lactose free milk", {}, 20, "k1")[1] == "hybrid"
    assert catalog_search.search(None, "lactose free milk ", {}, 20, "k1")[1] == "hybrid"
    assert embedded == ["Lactose free milk"]          # the second search reused the vector
    assert [c["hybrid"] for c in calls] == [True, True]


@pytest.mark.parametrize("failure", [
    embeddings.EmbeddingError("embedding request failed: rate-limited"),
    TimeoutError("slow"),
    RuntimeError("no such index: products_vector"),
])
def test_any_failure_of_the_vector_side_falls_back_to_text(monkeypatch, failure):
    monkeypatch.setenv("SEARCH_HYBRID", "true")
    calls = fake_store(monkeypatch, fail=failure)
    rows, kind = catalog_search.search(None, "milk", {}, 20, "k1")
    assert (rows, kind) == ([{"product_id": "462775"}], "text")
    assert [c["hybrid"] for c in calls] == [True, False]


def test_after_a_failure_hybrid_rests_for_a_while(monkeypatch):
    monkeypatch.setenv("SEARCH_HYBRID", "true")
    calls = fake_store(monkeypatch, fail=embeddings.EmbeddingError("rate-limited"))
    clock = {"t": 100.0}
    catalog_search.search(None, "milk", {}, 20, now=lambda: clock["t"])
    catalog_search.search(None, "milk", {}, 20, now=lambda: clock["t"])
    assert [c["hybrid"] for c in calls] == [True, False, False]       # no second hybrid try
    clock["t"] += catalog_search.COOLDOWN_S + 1
    catalog_search.search(None, "milk", {}, 20, now=lambda: clock["t"])
    assert [c["hybrid"] for c in calls][-2:] == [True, False]         # tried again after the rest


def test_a_query_whose_vector_is_kept_stays_hybrid_while_hybrid_rests(monkeypatch):
    """Seen on the server on 2026-11-14: at the rate limit, a query asked seconds before
    came back as text, although its vector was in memory and needed no new call."""
    monkeypatch.setenv("SEARCH_HYBRID", "true")
    calls = fake_store(monkeypatch)
    embedded = []

    def embed(texts, kind, post=None, sleep=None):
        if len(embedded) >= 1:
            raise embeddings.EmbeddingError("embedding request failed: rate-limited")
        embedded.append(texts[0])
        return [[0.0] * embeddings.EMBED_DIMENSIONS]
    monkeypatch.setattr(embeddings, "embed", embed)
    clock = {"t": 100.0}
    now = lambda: clock["t"]
    assert catalog_search.search(None, "plain yoghurt", {}, 20, now=now)[1] == "hybrid"
    assert catalog_search.search(None, "oat drink", {}, 20, now=now)[1] == "text"        # the limit: hybrid rests
    assert catalog_search.search(None, "rye bread", {}, 20, now=now)[1] == "text"        # no call while it rests
    assert catalog_search.search(None, "Plain yoghurt ", {}, 20, now=now)[1] == "hybrid"  # its vector is kept
    assert embedded == ["plain yoghurt"]
    assert [c["hybrid"] for c in calls] == [True, True, False, False, True]


# ---- #1452: the Catalog page and the Buyer rest apart, and the Buyer keeps one call a minute ----

def _counting_embed(monkeypatch, fail_for=()):
    """embeddings.embed that records each text and fails (a 429) for the texts in `fail_for`."""
    embedded = []

    def embed(texts, kind, post=None, sleep=None):
        embedded.append(texts[0])
        if texts[0] in fail_for:
            raise embeddings.EmbeddingError("embedding request failed: HTTP 429")
        return [[0.0] * embeddings.EMBED_DIMENSIONS]
    monkeypatch.setattr(embeddings, "embed", embed)
    return embedded


def test_a_catalog_page_429_never_sends_the_buyers_search_to_words(monkeypatch):
    monkeypatch.setenv("SEARCH_HYBRID", "true")
    fake_store(monkeypatch)
    embedded = _counting_embed(monkeypatch, fail_for={"oat drink"})
    clock = {"t": 100.0}
    now = lambda: clock["t"]
    assert catalog_search.search(None, "oat drink", {}, 20, hybrid=True, caller="catalog", now=now)[1] == "text"
    assert catalog_search.search(None, "rye bread", {}, 20, hybrid=True, caller="catalog", now=now)[1] == "text"
    assert catalog_search.search(None, "plain yoghurt", {}, 20, now=now)[1] == "hybrid"    # the Buyer
    assert embedded == ["oat drink", "plain yoghurt"]       # the Catalog page rests; the Buyer does not


def test_a_buyer_429_never_rests_the_catalog_page(monkeypatch):
    monkeypatch.setenv("SEARCH_HYBRID", "true")
    fake_store(monkeypatch)
    embedded = _counting_embed(monkeypatch, fail_for={"oat drink"})
    clock = {"t": 100.0}
    now = lambda: clock["t"]
    assert catalog_search.search(None, "oat drink", {}, 20, now=now)[1] == "text"           # the Buyer
    assert catalog_search.search(None, "rye bread", {}, 20, now=now)[1] == "text"           # rests
    with pytest.raises(catalog_search.MeaningUnavailable):
        catalog_search.meaning(None, "talon maito", {}, 50, now=now)                         # the Buyer rests
    assert catalog_search.search(None, "rye bread", {}, 20, hybrid=True, caller="catalog", now=now)[1] == "hybrid"
    assert embedded == ["oat drink", "rye bread"]


def test_the_catalog_page_leaves_the_last_embedding_call_of_a_minute_to_the_buyer(monkeypatch):
    fake_store(monkeypatch)
    embedded = _counting_embed(monkeypatch)
    clock = {"t": 100.0}
    now = lambda: clock["t"]
    page = lambda q: catalog_search.search(None, q, {}, 20, hybrid=True, caller="catalog", now=now)[1]
    assert page("oat drink") == "hybrid"
    assert page("rye bread") == "hybrid"
    assert page("plain yoghurt") == "text"            # the third call of the minute is the Buyer's
    assert page("oat drink") == "hybrid"              # a kept vector needs no call
    assert catalog_search.meaning(None, "talon maito", {}, 50, now=now) == [{"product_id": "462775"}]
    assert embedded == ["oat drink", "rye bread", "talon maito"]
    clock["t"] += 61
    assert page("plain yoghurt") == "hybrid"          # a new minute: no rest, the page may ask again
    assert embedded[-1] == "plain yoghurt"


def test_the_buyer_is_never_held_back_by_the_slot_it_keeps(monkeypatch):
    monkeypatch.setenv("SEARCH_HYBRID", "true")
    fake_store(monkeypatch)
    embedded = _counting_embed(monkeypatch)
    clock = {"t": 100.0}
    for q in ("oat drink", "rye bread", "plain yoghurt"):
        assert catalog_search.search(None, q, {}, 20, now=lambda: clock["t"])[1] == "hybrid"
    assert embedded == ["oat drink", "rye bread", "plain yoghurt"]


def test_the_catalog_page_route_searches_as_the_catalog_caller(monkeypatch):
    AGENT = app_tests.AGENT
    seen = []

    def search(db, query, filters, limit, kitchen_id=None, *, injected=None, now=None,
               hybrid_ok=True, hybrid=None, caller="buyer"):
        seen.append(caller)
        return [{"product_id": "3"}], "text"

    monkeypatch.setattr(catalog_search, "search", search)
    client, _ = _app_client(monkeypatch, None)
    client.post("/tools/search_products", headers=AGENT, json={"query": "milk", "mode": "hybrid"})
    need = client.post(app_tests.K + "/needs", headers=AGENT,
                       json={"quantity": "60", "unit": "L", "requested_date": "2026-11-16"}).json()
    seen_page = list(seen)
    seen.clear()
    client.post("/tools/search_products", headers=AGENT, json={"query": "milk", "need_id": need["need_id"]})
    assert seen_page == ["catalog"] and seen and set(seen) == {"buyer"}


def test_hybrid_can_be_switched_off_for_one_call(monkeypatch):
    monkeypatch.setenv("SEARCH_HYBRID", "true")
    calls = fake_store(monkeypatch)
    assert catalog_search.search(None, "cheese", {"category": "10603"}, 20, hybrid_ok=False)[1] == "text"
    assert [c["hybrid"] for c in calls] == [False]


def test_hybrid_can_be_asked_for_one_call_while_the_switch_is_off(monkeypatch):
    """#1382: the Catalog page's "Search by meaning" switch, whatever SEARCH_HYBRID says."""
    calls = fake_store(monkeypatch)
    monkeypatch.setattr(embeddings, "embed", lambda texts, kind, post=None, sleep=None:
                        [[0.0] * embeddings.EMBED_DIMENSIONS])
    assert catalog_search.search(None, "lactose free milk", {}, 20, hybrid=True)[1] == "hybrid"
    assert catalog_search.search(None, "lactose free milk", {}, 20)[1] == "text"
    monkeypatch.setenv("SEARCH_HYBRID", "true")
    assert catalog_search.search(None, "lactose free milk", {}, 20, hybrid=False)[1] == "text"
    assert [c["hybrid"] for c in calls] == [True, False, False]


def test_a_hybrid_call_that_cannot_embed_falls_back_to_text(monkeypatch):
    calls = fake_store(monkeypatch, fail=embeddings.EmbeddingError("rate-limited"))
    assert catalog_search.search(None, "oat drink", {}, 20, hybrid=True)[1] == "text"
    assert [c["hybrid"] for c in calls] == [True, False]


def test_a_bad_filter_is_still_an_error_not_a_fallback(monkeypatch):
    monkeypatch.setenv("SEARCH_HYBRID", "true")
    fake_store(monkeypatch, fail=ValueError("limit must be an integer from 1 to 50"))
    with pytest.raises(ValueError):
        catalog_search.search(None, "milk", {}, 99)


def test_an_empty_query_never_embeds(monkeypatch):
    monkeypatch.setenv("SEARCH_HYBRID", "true")
    calls = fake_store(monkeypatch)
    assert catalog_search.search(None, "  ", {}, 20)[1] == "text"
    assert [c["hybrid"] for c in calls] == [False]


def test_the_gateways_injected_search_is_used_as_it_is(monkeypatch):
    monkeypatch.setenv("SEARCH_HYBRID", "true")
    calls = fake_store(monkeypatch)
    rows, kind = catalog_search.search("db", "milk", None, 8, "k1",
                                       injected=lambda db, q, f, n, kitchen_id=None: [{"product_id": q}])
    assert (rows, kind, calls) == ([{"product_id": "milk"}], "text", [])


def test_the_query_embedder_never_waits_or_retries(monkeypatch):
    seen = {}

    def embed(texts, kind, post=None, sleep=None):
        seen["kind"] = kind
        with pytest.raises(embeddings.EmbeddingError):
            sleep(1)                                   # a rate limit is an error at once
        return [[1.0] * embeddings.EMBED_DIMENSIONS]

    monkeypatch.setattr(embeddings, "embed", embed)
    vectors = catalog_search._query_embedder()(["oat drink"], "query")
    assert seen["kind"] == "query" and len(vectors[0]) == embeddings.EMBED_DIMENSIONS


def test_the_tool_answer_says_which_search_ran(monkeypatch):
    monkeypatch.setenv("GATEWAY_AGENT_TOKEN", "agent-test-token")
    db = mongomock.MongoClient(tz_aware=True)["test"]
    fake = app_tests.FakeValio()
    gw = Gateway(db, ValioClient("k", transport=fake.transport, ttl=0, now=lambda: app_tests.NOW),
                 now=lambda: app_tests.NOW,
                 search=lambda db, q, f, n, kitchen_id=None: [{"product_id": "462775"}])
    client = TestClient(create_app(gw))
    plain = client.post("/tools/search_products", headers=app_tests.AGENT, json={"query": "milk"})
    assert plain.status_code == 200 and plain.json()["search"] == "text"
    need = client.post(app_tests.K + "/needs", headers=app_tests.AGENT,
                       json={"quantity": "60", "unit": "L", "requested_date": "2026-11-16"}).json()
    short = client.post("/tools/search_products", headers=app_tests.AGENT,
                        json={"query": "milk", "need_id": need["need_id"]})
    assert short.status_code == 200 and short.json()["search"] == "text"


def _app_client(monkeypatch, search):
    monkeypatch.setenv("GATEWAY_AGENT_TOKEN", "agent-test-token")
    db = mongomock.MongoClient(tz_aware=True)["test"]
    fake = app_tests.FakeValio()
    gw = Gateway(db, ValioClient("k", transport=fake.transport, ttl=0, now=lambda: app_tests.NOW),
                 now=lambda: app_tests.NOW, search=search)
    return TestClient(create_app(gw)), gw


def test_mode_hybrid_runs_meaning_for_the_catalog_page_only(monkeypatch):
    """#1382: `mode: "hybrid"` turns hybrid on for one request; a need's shortlist (the
    Buyer) ignores it, so the rehearsed basket never changes."""
    AGENT, K = app_tests.AGENT, app_tests.K
    asked = []

    def search(db, query, filters, limit, kitchen_id=None, *, injected=None, now=None,
               hybrid_ok=True, hybrid=None, caller="buyer"):
        asked.append(hybrid)
        if hybrid:
            return [{"product_id": "1", "matched_by": "meaning"},
                    {"product_id": "2", "matched_by": "both"}], "hybrid"
        return [{"product_id": "3"}], "text"

    monkeypatch.setattr(catalog_search, "search", search)
    client, _ = _app_client(monkeypatch, None)
    on = client.post("/tools/search_products", headers=AGENT,
                     json={"query": "lactose-free milk", "mode": "hybrid"})
    assert on.status_code == 200, on.text
    body = on.json()
    assert body["search"] == "hybrid" and "meaning_unavailable" not in body
    assert [p["matched_by"] for p in body["products"]] == ["meaning", "both"]
    off = client.post("/tools/search_products", headers=AGENT, json={"query": "lactose-free milk"}).json()
    assert off["search"] == "text" and [p["matched_by"] for p in off["products"]] == ["words"]
    text = client.post("/tools/search_products", headers=AGENT, json={"query": "milk", "mode": "text"})
    assert text.status_code == 200
    assert asked == [True, None, False]
    need = client.post(K + "/needs", headers=AGENT,
                       json={"quantity": "60", "unit": "L", "requested_date": "2026-11-16"}).json()
    asked.clear()
    short = client.post("/tools/search_products", headers=AGENT,
                        json={"query": "milk", "need_id": need["need_id"], "mode": "hybrid"})
    assert short.status_code == 200 and short.json()["search"] == "text"
    assert asked and all(h is None for h in asked)      # the Buyer's path: SEARCH_HYBRID decides
    assert all(p["matched_by"] == "words" for p in short.json()["products"])


def test_mode_hybrid_that_falls_back_says_so(monkeypatch):
    AGENT = app_tests.AGENT
    client, _ = _app_client(monkeypatch, lambda db, q, f, n, kitchen_id=None: [{"product_id": "462775"}])
    body = client.post("/tools/search_products", headers=AGENT,
                       json={"query": "lactose-free milk", "mode": "hybrid"}).json()
    assert body["search"] == "text" and body["meaning_unavailable"] is True
    assert body["products"][0]["matched_by"] == "words"
    plain = client.post("/tools/search_products", headers=AGENT, json={"query": "milk"}).json()
    assert "meaning_unavailable" not in plain


@pytest.mark.parametrize("mode", ["meaning", 1, True, ""])
def test_an_unknown_mode_is_refused(monkeypatch, mode):
    AGENT = app_tests.AGENT
    client, _ = _app_client(monkeypatch, lambda db, q, f, n, kitchen_id=None: [])
    r = client.post("/tools/search_products", headers=AGENT, json={"query": "milk", "mode": mode})
    assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_REQUEST"


def test_the_mcp_tool_never_sends_mode():
    import inspect
    from gateway import mcp_server
    source = inspect.getsource(mcp_server.build_server)
    tool = source[source.index("async def search_products"):source.index("async def get_offer")]
    assert not re.search(r"\bmode\b", tool)      # model_dump is fine; a `mode` key is not


# ---- the meaning search alone: the Buyer's fallback when the words find nothing (#1384) ----

def test_meaning_runs_the_vector_search_with_the_same_filters_whatever_the_switch_says(monkeypatch):
    calls = fake_store(monkeypatch)
    monkeypatch.setattr(embeddings, "embed", lambda texts, kind, post=None, sleep=None: (
        [[0.0] * embeddings.EMBED_DIMENSIONS]))
    filters = {"exclude_allergens": ["milk"], "allergen_strictness": "strict"}
    rows = catalog_search.meaning(None, "talon maito", filters, 50, "k1")
    assert rows == [{"product_id": "462775"}]
    assert calls == [{"query": "talon maito", "hybrid": True, "limit": 50, "kitchen_id": "k1"}]


@pytest.mark.parametrize("failure", [
    embeddings.EmbeddingError("embedding request failed: rate-limited"),
    TimeoutError("slow"),
    RuntimeError("no such index: products_vector"),
])
def test_meaning_says_it_cannot_run_and_then_rests(monkeypatch, failure):
    calls = fake_store(monkeypatch, fail=failure)
    clock = {"t": 100.0}
    with pytest.raises(catalog_search.MeaningUnavailable):
        catalog_search.meaning(None, "talon maito", {}, 50, now=lambda: clock["t"])
    with pytest.raises(catalog_search.MeaningUnavailable):
        catalog_search.meaning(None, "other words", {}, 50, now=lambda: clock["t"])
    assert len(calls) == 1                                 # no second embedding call while it rests


def test_meaning_keeps_a_bad_filter_an_error(monkeypatch):
    fake_store(monkeypatch, fail=ValueError("unknown allergen: 'peanutz'"))
    with pytest.raises(ValueError):
        catalog_search.meaning(None, "talon maito", {"exclude_allergens": ["peanutz"]}, 50)


def test_meaning_with_no_words_finds_nothing_and_embeds_nothing(monkeypatch):
    calls = fake_store(monkeypatch)
    assert catalog_search.meaning(None, "  ", {}, 50) == [] and calls == []


def test_meaning_uses_the_gateways_injected_one(monkeypatch):
    calls = fake_store(monkeypatch)
    rows = catalog_search.meaning("db", "maito", {}, 8, "k1",
                                  injected=lambda db, q, f, n, kitchen_id=None: [{"product_id": q}])
    assert (rows, calls) == ([{"product_id": "maito"}], [])

    def slow(db, q, f, n, kitchen_id=None):
        raise TimeoutError("slow")
    with pytest.raises(catalog_search.MeaningUnavailable):
        catalog_search.meaning("db", "maito", {}, 8, injected=slow)
