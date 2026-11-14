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
               hybrid_ok=True, hybrid=None):
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
