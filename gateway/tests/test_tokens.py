"""API tokens (#271): created by a person, scoped to one kitchen, never approve."""

import json

import pytest

from gateway.tests.test_gateway_app import AGENT, HUMAN, K, env, milk  # noqa: F401 (fixture)
from gateway.tests.test_mcp_http import MCP_HEADERS


def make(client, scopes, name="claude", kitchen=K):
    r = client.post(kitchen + "/tokens", headers=HUMAN, json={"name": name, "scopes": scopes})
    assert r.status_code == 200, r.text
    return r.json()


def bearer(token):
    return {"Authorization": "Bearer " + token}


def test_token_is_shown_once_and_stored_as_a_hash(env):
    client, _, db = env
    out = make(client, ["kitchen:read"])
    assert out["token"].startswith("tkb_") and out["prefix"] == out["token"][:8]
    stored = db.api_tokens.find_one({})
    assert out["token"] not in str(stored) and len(stored["hash"]) == 64
    listed = client.get(K + "/tokens", headers=HUMAN).json()["tokens"]
    assert listed[0]["name"] == "claude" and "token" not in listed[0]


def test_only_a_person_manages_tokens_and_approve_is_refused(env):
    client, _, _ = env
    assert client.post(K + "/tokens", headers=AGENT, json={"name": "x", "scopes": ["kitchen:read"]}).status_code == 403
    r = client.post(K + "/tokens", headers=HUMAN, json={"name": "x", "scopes": ["kitchen:approve"]})
    assert r.status_code == 422 and "only a person approves" in r.json()["error"]["message"]
    assert client.post(K + "/tokens", headers=HUMAN, json={"name": "x", "scopes": ["admin"]}).status_code == 422


def test_read_token_cannot_propose(env):
    client, _, _ = env
    t = make(client, ["kitchen:read"])["token"]
    assert client.get(K + "/orders", headers=bearer(t)).status_code == 200
    r = client.post(K + "/proposals", headers=bearer(t), json={
        "product_ids": ["462775"], "quantity": "10", "unit": "L", "requested_date": "2026-11-16",
        "idempotency_key": "p"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "SCOPE_REQUIRED"


def test_propose_token_proposes_but_can_never_approve(env):
    client, _, _ = env
    t = make(client, ["kitchen:read", "kitchen:propose"])["token"]
    r = client.post(K + "/proposals", headers=bearer(t), json={
        "product_ids": ["462775", "463335"], "quantity": "100", "unit": "L",
        "requested_date": "2026-11-16", "idempotency_key": "p"})
    assert r.status_code == 200, r.text
    p = r.json()
    r = client.post(f"{K}/proposals/{p['proposal_id']}/approve", headers=bearer(t),
                    json={"expected_total": p["expected_total"], "idempotency_key": "a"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "HUMAN_SESSION_REQUIRED"


def test_token_is_bound_to_its_kitchen(env):
    client, _, _ = env
    t = make(client, ["kitchen:read"])["token"]
    r = client.get("/v1/kitchens/other-kitchen/orders", headers=bearer(t))
    assert r.status_code == 403 and r.json()["error"]["code"] == "KITCHEN_SCOPE"


def test_revoked_token_gets_401_and_both_steps_are_audited(env):
    client, _, _ = env
    out = make(client, ["kitchen:read"])
    assert client.delete(f"{K}/tokens/{out['token_id']}", headers=HUMAN).status_code == 200
    assert client.get(K + "/orders", headers=bearer(out["token"])).status_code == 401
    kinds = [e["kind"] for e in client.get(K + "/audit", headers=HUMAN).json()["events"]]
    assert kinds == ["token_created", "token_revoked"]
    assert client.delete(f"{K}/tokens/nope", headers=HUMAN).status_code == 404


def test_mcp_accepts_a_propose_token_but_not_a_read_token(env):
    client, _, _ = env
    propose = make(client, ["kitchen:read", "kitchen:propose"], "claude")["token"]
    read = make(client, ["kitchen:read"], "dash")["token"]
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    with client:
        ok = client.post("/mcp", headers={**MCP_HEADERS, **bearer(propose)}, json=body)
        assert ok.status_code == 200, ok.text
        names = {t["name"] for t in ok.json()["result"]["tools"]}
        assert "place_order" in names and not any("approve" in n for n in names)
        assert client.post("/mcp", headers={**MCP_HEADERS, **bearer(read)}, json=body).status_code == 401


def test_mcp_tool_call_with_a_kitchen_token_acts_for_that_kitchen(env):
    client, _, db = env
    other = "/v1/kitchens/other-k"
    t = make(client, ["kitchen:read", "kitchen:propose"], kitchen=other)["token"]
    need = client.post(other + "/needs", headers=bearer(t),
                       json={"quantity": "60", "unit": "L", "requested_date": "2026-11-16"})
    assert need.status_code == 200, need.text

    def call(tool, arguments):
        body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": {"name": tool, "arguments": arguments}}
        r = client.post("/mcp", headers={**MCP_HEADERS, **bearer(t)}, json=body)
        assert r.status_code == 200, r.text
        result = r.json()["result"]
        assert not result.get("isError"), result
        return json.loads(result["content"][0]["text"])

    with client:
        # The need is in other-k: with the server agent token (demo-kitchen) it is not found.
        offer = call("get_offer", {"product_ids": ["462775"], "requested_date": "2026-11-16",
                                   "need_id": need.json()["need_id"]})
        call("simulate_order", {"offer_id": offer["offer_id"]})
        req = call("request_approval", {"offer_id": offer["offer_id"]})
    assert req["status"] == "PENDING"
    assert [p["kitchen_id"] for p in db.proposals.find({})] == ["other-k"]
    assert db.proposals.find_one({"_id": req["proposal_id"]})["kitchen_id"] == "other-k"
