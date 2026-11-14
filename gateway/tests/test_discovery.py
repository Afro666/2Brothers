"""Agent discovery (#293): the agent card and llms.txt say only what the gateway serves."""

import re

import pytest

from gateway import discovery, tokens
from gateway.tests.test_gateway_app import HUMAN, K, env  # noqa: F401 (fixture)
from gateway.tests.test_mcp_http import MCP_HEADERS

CARD = "/.well-known/agent-card.json"
PUBLIC = {"Host": "kitchen.example", "X-Forwarded-Proto": "https"}
BASE = "https://kitchen.example/gateway"


@pytest.fixture()
def client(env, monkeypatch):  # noqa: F811
    monkeypatch.setenv("GATEWAY_PUBLIC_PREFIX", "/gateway")
    return env[0]


def card(client):
    r = client.get(CARD, headers=PUBLIC)
    assert r.status_code == 200, r.text
    return r


def token(client, scopes):
    r = client.post(K + "/tokens", headers=HUMAN, json={"name": "byoa", "scopes": scopes})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def routes(client):
    return {(m, r.path) for r in client.app.routes for m in (getattr(r, "methods", None) or ())}


def test_both_files_are_public_and_typed(client):
    r = card(client)
    assert r.headers["content-type"] == "application/json"
    t = client.get("/llms.txt", headers=PUBLIC)
    assert t.status_code == 200 and t.headers["content-type"] == "text/plain; charset=utf-8"
    assert t.text.startswith("# ")


def test_card_has_the_required_fields(client):
    c = card(client).json()
    for field in ("name", "description", "url", "version", "provider", "capabilities", "skills",
                  "securitySchemes", "security", "defaultInputModes", "defaultOutputModes", "links"):
        assert c[field], field
    assert c["name"] == client.app.title and c["version"] == client.app.version
    assert c["url"] == BASE and c["provider"]["organization"] and c["provider"]["url"]
    bearer = c["securitySchemes"]["bearer"]
    assert bearer["type"] == "http" and bearer["scheme"] == "bearer"
    assert set(bearer["scopes"]) == set(tokens.SCOPES) == set(c["security"][0]["bearer"])
    assert "kitchen:approve" not in str(c["security"])
    assert c["capabilities"]["a2aMessaging"] is False      # honest: discovery only, no A2A RPC
    assert c["links"]["openapi"] == BASE + "/openapi.json" and c["links"]["mcp"] == BASE + "/mcp"


def test_every_skill_is_a_route_this_app_serves(client):
    c = card(client).json()
    served = routes(client)
    ids = [s["id"] for s in c["skills"]]
    assert {"search_products", "get_offer", "simulate_order", "request_approval"} <= set(ids)
    assert len(ids) == len(set(ids)) == len(discovery.SKILLS)
    for skill in c["skills"]:
        assert (skill["method"], skill["path"]) in served, skill["id"]
        assert skill["url"] == BASE + skill["path"]
        assert skill["scope"] in tokens.SCOPES and skill["description"]


def test_every_skill_route_wants_a_token_and_the_scope_the_card_names(client):
    """Call each listed route: 401 without a token; a read-only token is refused (403
    SCOPE_REQUIRED) exactly on the skills the card marks kitchen:propose."""
    read_only = token(client, ["kitchen:read"])
    for skill in card(client).json()["skills"]:
        path = skill["path"].replace("{kitchen_id}", "demo-kitchen")
        send = client.post if skill["method"] == "POST" else client.get
        kwargs = {"json": {}} if skill["method"] == "POST" else {"params": {"order_id": "x", "run_id": "x"}}
        assert send(path, **kwargs).status_code == 401, skill["id"]
        r = send(path, headers=read_only, **kwargs)
        refused = r.status_code == 403 and r.json()["error"]["code"] == "SCOPE_REQUIRED"
        assert refused == (skill["scope"] == "kitchen:propose"), (skill["id"], r.status_code, r.text)


def test_approval_is_human_only_and_not_a_skill(client):
    c = card(client).json()
    assert not any("approve" in s["id"] or s["path"].endswith(("/approve", "/reject")) for s in c["skills"])
    served = routes(client)
    assert {h["id"] for h in c["humanOnly"]} >= {"approve", "reject"}
    for h in c["humanOnly"]:
        assert (h["method"], h["path"]) in served
    both = token(client, ["kitchen:read", "kitchen:propose"])
    r = client.post(K + "/proposals/none/approve", headers=both, json={"expected_total": "1.00", "idempotency_key": "a"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "HUMAN_SESSION_REQUIRED"


def test_mcp_tools_in_the_card_are_the_tools_the_server_lists(client):
    c = card(client).json()
    with client:    # the MCP session manager runs in the app lifespan
        r = client.post("/mcp", headers={**MCP_HEADERS, "Authorization": "Bearer agent-test-token"},
                        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert r.status_code == 200, r.text
    live = {t["name"] for t in r.json()["result"]["tools"]}
    mcp = next(i for i in c["additionalInterfaces"] if i["transport"].startswith("MCP"))
    assert mcp["url"] == BASE + "/mcp" and set(mcp["tools"]) == live
    assert {s["mcp_tool"] for s in c["skills"] if s["mcp_tool"]} == live
    assert not any("approve" == t or "reject" in t or "cancel" in t for t in live)


def test_a_skill_whose_route_is_gone_is_not_listed(client):
    app = client.app
    app.router.routes[:] = [r for r in app.router.routes if getattr(r, "path", "") != "/tools/place_order"]
    ids = {s["id"] for s in card(client).json()["skills"]}
    assert "place_order" not in ids and "get_offer" in ids
    assert "/tools/place_order" not in client.get("/llms.txt", headers=PUBLIC).text


def test_llms_txt_names_the_flow_the_rules_and_real_urls(client):
    text = client.get("/llms.txt", headers=PUBLIC).text
    for needle in ("Base URL: " + BASE, "Authorization: Bearer", "kitchen:read", "kitchen:propose",
                   "POST /tools/search_products", "POST /tools/get_offer", "POST /tools/simulate_order",
                   "POST /tools/request_approval", "A person approves", "unknown_stock", "never approve",
                   "Totals come from simulate", "idempotency_key", BASE + "/openapi.json", BASE + "/mcp",
                   "docs/contract.md", BASE + CARD):
        assert needle in text, needle
    served = routes(client)
    for method, path in re.findall(r"`(GET|POST|DELETE) (/[^` ]*)`", text):
        assert (method, path) in served, (method, path)
    for method, url in re.findall(r"`(GET|POST|DELETE) (https://[^` ]*)`", text):      # full URLs too
        assert url.startswith(BASE) and (method, url[len(BASE):]) in served, (method, url)
    assert "tkb_" in text and not re.search(r"tkb_[A-Za-z0-9_\-]{8,}", text)     # the prefix, never a token


def test_urls_follow_the_request_and_the_prefix(client, monkeypatch):
    monkeypatch.delenv("GATEWAY_PUBLIC_PREFIX")
    c = client.get(CARD).json()
    assert c["url"] == "http://testserver" and c["links"]["openapi"] == "http://testserver/openapi.json"
    monkeypatch.setenv("GATEWAY_PUBLIC_PREFIX", "gateway/")
    assert client.get(CARD, headers=PUBLIC).json()["url"] == BASE
    monkeypatch.setenv("GATEWAY_PUBLIC_PREFIX", "/x\"><script>")
    assert client.get(CARD, headers=PUBLIC).json()["url"] == "https://kitchen.example"
    bad = client.get(CARD, headers={"Host": "evil.example/<b>", "X-Forwarded-Proto": "javascript"}).json()
    assert bad["url"] == "http://localhost"


def test_the_files_are_not_in_the_openapi_and_need_no_token_under_login_mode(client, monkeypatch):
    monkeypatch.setenv("GATEWAY_REQUIRE_LOGIN", "true")
    assert client.get(CARD).status_code == 200 and client.get("/llms.txt").status_code == 200
    paths = client.get("/openapi.json").json()["paths"]
    assert CARD not in paths and "/llms.txt" not in paths
