"""Remote MCP at /mcp (#280): MCP JSON-RPC over HTTP against the real gateway app."""

import json

import pytest

mongomock = pytest.importorskip("mongomock")
pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from gateway.app import create_app  # noqa: E402
from gateway.service import Gateway  # noqa: E402
from gateway.tests.test_gateway_app import FakeValio, NOW, RAW  # noqa: E402
from gateway.valio_client import ValioClient  # noqa: E402

AGENT = "Bearer agent-test-token"
MCP_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json",
               "MCP-Protocol-Version": "2025-06-18"}
K = "/v1/kitchens/demo-kitchen"


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("GATEWAY_HUMAN_TOKEN", "human-test-token")
    monkeypatch.setenv("GATEWAY_AGENT_TOKEN", "agent-test-token")
    db = mongomock.MongoClient(tz_aware=True)["test"]
    for pid, raw in RAW.items():
        db.products.insert_one({"_id": pid, "names": {"en": f"milk {pid}"}, "raw": raw})
    valio = ValioClient("test-not-a-real-key", transport=FakeValio().transport, ttl=0, now=lambda: NOW)
    with TestClient(create_app(Gateway(db, valio, now=lambda: NOW))) as c:  # runs the MCP lifespan
        yield c


def rpc(client, method, params=None, auth=AGENT, id=1):
    headers = {**MCP_HEADERS, **({"Authorization": auth} if auth else {})}
    return client.post("/mcp", headers=headers,
                       json={"jsonrpc": "2.0", "id": id, "method": method, "params": params or {}})


def call(client, tool, arguments):
    r = rpc(client, "tools/call", {"name": tool, "arguments": arguments})
    assert r.status_code == 200, r.text
    result = r.json()["result"]
    data = None
    if result.get("content") and not result.get("isError"):
        data = json.loads(result["content"][0]["text"])
    return result, data


def init(client):
    r = rpc(client, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                   "clientInfo": {"name": "test", "version": "0"}})
    assert r.status_code == 200, r.text
    return r.json()["result"]


def test_tools_listed_without_approve(client):
    assert init(client)["serverInfo"]["name"] == "2Brothers purchasing gateway"
    tools = {t["name"] for t in rpc(client, "tools/list").json()["result"]["tools"]}
    assert tools == {"search_products", "get_offer", "simulate_order", "place_order",
                     "request_approval", "get_order_status", "get_audit_log"}
    assert not {t for t in tools if "approve" in t or "cancel" in t or "reject" in t}


def test_milk_flow_up_to_pending(client):
    init(client)
    need = client.post(K + "/needs", headers={"Authorization": AGENT},
                       json={"quantity": "60", "unit": "L", "requested_date": "2026-11-16"}).json()
    _, offer = call(client, "get_offer", {"product_ids": ["462775"], "requested_date": "2026-11-16",
                                          "need_id": need["need_id"]})
    assert offer["lines"][0]["quantity"] == "51"  # sized by the gateway from the need
    _, sim = call(client, "simulate_order", {"offer_id": offer["offer_id"]})
    assert 'expected_total' not in offer
    assert sim['offer_id'] == offer['offer_id'] and isinstance(sim['expected_total'], str)
    assert sim["mandate"]["verdict"] == "NEEDS_APPROVAL"
    _, req = call(client, "request_approval", {"offer_id": offer["offer_id"]})
    assert req["status"] == "PENDING"
    _, again = call(client, "request_approval", {"offer_id": offer["offer_id"]})
    assert again["approval_id"] == req["approval_id"]  # stable key: a replay, not a second request
    result, _ = call(client, "place_order", {"offer_id": offer["offer_id"],
                                             "expected_total": sim["expected_total"], "idempotency_key": "x"})
    assert result["isError"] is True and "NEEDS_APPROVAL" in result["content"][0]["text"]


@pytest.mark.parametrize("auth", [None, "Bearer wrong", "Bearer human-test-token", "agent-test-token"])
def test_only_the_agent_token_gets_in(client, auth):
    r = rpc(client, "tools/list", auth=auth)
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "UNAUTHENTICATED"
    assert r.headers["www-authenticate"].startswith("Bearer")


def test_rest_api_still_works(client):
    assert client.get("/health").status_code == 200
    assert client.get(K + "/orders").status_code == 401
