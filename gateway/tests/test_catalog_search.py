"""The gateway's catalog search: hybrid behind a switch, text as the fallback."""

import pytest

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


def test_the_tool_answer_says_which_search_ran():
    from gateway.tests.test_gateway_app import AGENT, K
    import importlib
    app_tests = importlib.import_module("gateway.tests.test_gateway_app")
    import mongomock
    from fastapi.testclient import TestClient
    from gateway.app import create_app
    from gateway.service import Gateway
    from gateway.valio_client import ValioClient

    db = mongomock.MongoClient(tz_aware=True)["test"]
    fake = app_tests.FakeValio()
    gw = Gateway(db, ValioClient("k", transport=fake.transport, ttl=0, now=lambda: app_tests.NOW),
                 now=lambda: app_tests.NOW,
                 search=lambda db, q, f, n, kitchen_id=None: [{"product_id": "462775"}])
    import os
    os.environ.setdefault("GATEWAY_AGENT_TOKEN", "agent-test-token")
    client = TestClient(create_app(gw))
    plain = client.post("/tools/search_products", headers=AGENT, json={"query": "milk"})
    assert plain.status_code == 200 and plain.json()["search"] == "text"
    need = client.post(K + "/needs", headers=AGENT,
                       json={"quantity": "60", "unit": "L", "requested_date": "2026-11-16"}).json()
    short = client.post("/tools/search_products", headers=AGENT,
                        json={"query": "milk", "need_id": need["need_id"]})
    assert short.status_code == 200 and short.json()["search"] == "text"
