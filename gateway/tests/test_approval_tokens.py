"""Personal approval tokens (decision 2026-11-14): a person approves from their own chat.

Agent and kitchen tokens still never approve; the open demo creates only `open-demo` tokens
in its own kitchen (decision 2026-11-14 18:08 UTC, #1446); the token never proposes; every
use is audited with via: personal_token.
"""

import json
from datetime import timedelta

import pytest

from gateway import approval_tokens, users
from gateway.tests.test_gateway_app import AGENT, HUMAN, K, NOW, env, milk  # noqa: F401 (fixture)

PW = "correct horse 42"
MCP_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json",
               "MCP-Protocol-Version": "2025-06-18"}
AGENT_TOOLS = {"search_products", "get_offer", "simulate_order", "place_order",
               "request_approval", "get_order_status", "get_audit_log", "change_proposal"}
PERSON_TOOLS = {"search_products", "get_order_status", "get_audit_log",
                "list_proposals", "get_proposal", "list_orders", "approve_proposal", "reject_proposal"}


def people(db):
    users.create_user(db, "aron@example.com", PW, name="Aron", role="approver", kitchen_id="demo-kitchen")
    users.create_user(db, "chef@example.com", PW, name="Chef", role="chef", kitchen_id="demo-kitchen")


def sign_in(client, email):
    client.cookies.clear()
    r = client.post("/v1/auth/login", json={"email": email, "password": PW})
    assert r.status_code == 200, r.text


def personal(client, db, hours=None):
    """A personal approval token of aron@example.com, made in a real signed-in session."""
    people(db)
    sign_in(client, "aron@example.com")
    r = client.post(K + "/approval-tokens", json={"hours": hours} if hours else {})
    assert r.status_code == 200, r.text
    client.cookies.clear()
    out = r.json()
    return out, {"Authorization": "Bearer " + out["token"]}


def approve_body(p, key="chat-yes"):
    return {"expected_total": p["expected_total"], "idempotency_key": key}


# ---- creation ---------------------------------------------------------------------------

def test_a_signed_in_approver_creates_one_stored_hashed_and_listed_without_value(env):
    client, _, db = env
    out, _ = personal(client, db)
    assert out["token"].startswith("tka_") and out["person"] == "aron@example.com"
    assert out["kitchen_id"] == "demo-kitchen" and out["kind"] == "personal_approval"
    hours = (approval_tokens._parse(out["expires_at"]) - approval_tokens._parse(out["created_at"]))
    assert hours == timedelta(hours=8)
    stored = db.approval_tokens.find_one({"_id": out["token_id"]})
    assert out["token"] not in json.dumps(stored, default=str)          # only the hash is kept
    sign_in(client, "aron@example.com")
    listed = client.get(K + "/approval-tokens").json()["tokens"]
    assert [t["token_id"] for t in listed] == [out["token_id"]]
    assert "token" not in listed[0] and out["token"] not in json.dumps(listed)
    events = [e["kind"] for e in client.get(K + "/audit", headers=AGENT).json()["events"]]
    assert "approval_token_created" in events


def test_hours_default_8_max_24(env):
    client, _, db = env
    people(db)
    sign_in(client, "aron@example.com")
    assert client.post(K + "/approval-tokens", json={"hours": 25}).status_code == 422
    assert client.post(K + "/approval-tokens", json={"hours": 0}).status_code == 422
    assert client.post(K + "/approval-tokens", json={"hours": "8"}).status_code == 422
    assert client.post(K + "/approval-tokens", json={"hours": 24}).status_code == 200


def open_demo_token(client, hours=None):
    r = client.post(K + "/approval-tokens", headers=HUMAN, json={"hours": hours} if hours else {})
    assert r.status_code == 200, r.text
    out = r.json()
    return out, {"Authorization": "Bearer " + out["token"]}


def test_the_open_demo_creates_an_open_demo_token_that_approves_only_in_its_kitchen(env):
    client, _, db = env
    out, tka = open_demo_token(client)
    assert out["person"] == "open-demo" and out["created_by"] == "open-demo"
    assert out["kitchen_id"] == "demo-kitchen" and out["token"].startswith("tka_")
    assert "aron" not in json.dumps({k: v for k, v in out.items() if k != "token"})   # not the X-User name
    hours = approval_tokens._parse(out["expires_at"]) - approval_tokens._parse(out["created_at"])
    assert hours == timedelta(hours=8)                                  # the same expiry as an account's
    created = db.audit_log.find_one({"event.kind": "approval_token_created"})["event"]
    assert created["actor"] == "open-demo" and created["token_id"] == out["token_id"]
    me = client.get("/v1/me", headers=tka).json()
    assert me["kind"] == "personal" and me["name"] == "open-demo" and me["can_approve"] is True
    assert client.post(K + "/proposals", headers=tka, json={}).status_code == 403   # never proposes
    other = client.get("/v1/kitchens/other-kitchen/proposals", headers=tka)
    assert other.status_code == 403 and other.json()["error"]["code"] == "KITCHEN_SCOPE"
    p = milk(client)
    r = client.post(f"{K}/proposals/{p['proposal_id']}/approve", headers=tka, json=approve_body(p))
    assert r.status_code == 200, r.text
    placed = db.audit_log.find_one({"event.kind": "order_placed"})["event"]
    assert placed["actor"] == "open-demo"
    assert placed["via"] == "personal_token" and placed["token_id"] == out["token_id"]
    assert out["token"] not in json.dumps([e["event"] for e in db.audit_log.find()], default=str)


def test_each_open_demo_token_is_its_own_in_the_audit(env):
    client, _, db = env
    first, tk1 = open_demo_token(client)
    second, tk2 = open_demo_token(client)
    assert first["token_id"] != second["token_id"]
    p = milk(client)
    assert client.post(f"{K}/proposals/{p['proposal_id']}/reject", headers=tk2,
                       json={"reason": "judge 2", "idempotency_key": "r"}).status_code == 200
    event = db.audit_log.find_one({"event.kind": "proposal_rejected"})["event"]
    assert event["actor"] == "open-demo" and event["token_id"] == second["token_id"]


def test_the_open_demo_creates_tokens_only_in_its_own_kitchen(env, monkeypatch):
    client, _, _ = env
    r = client.post("/v1/kitchens/other-kitchen/approval-tokens", headers=HUMAN, json={})
    assert r.status_code == 403 and r.json()["error"]["code"] == "KITCHEN_SCOPE"
    monkeypatch.setenv("GATEWAY_KITCHEN_ID", "other-kitchen")
    assert client.post("/v1/kitchens/other-kitchen/approval-tokens", headers=HUMAN, json={}).status_code == 200
    assert client.post(K + "/approval-tokens", headers=HUMAN, json={}).status_code == 403


def test_the_open_demo_sees_only_open_demo_tokens_never_another_persons_and_no_email(env):
    """Live check 14 Nov (#1575): the open demo listed every token with the person's email,
    and anyone could revoke it. The open demo lists and revokes only `open-demo` tokens."""
    client, _, db = env
    out, _ = personal(client, db)
    demo, _ = open_demo_token(client)
    listed = client.get(K + "/approval-tokens", headers=HUMAN)
    assert listed.status_code == 200
    assert [t["token_id"] for t in listed.json()["tokens"]] == [demo["token_id"]]
    assert "aron@example.com" not in listed.text and out["token_id"] not in listed.text
    assert demo["token"] not in listed.text                             # never the full token again
    gone = client.delete(f"{K}/approval-tokens/{out['token_id']}", headers=HUMAN)
    assert gone.status_code == 404 and gone.json()["error"]["code"] == "TOKEN_NOT_FOUND"
    assert "aron@example.com" not in gone.text
    assert db.approval_tokens.find_one({"_id": out["token_id"]})["revoked_at"] is None
    sign_in(client, "aron@example.com")                                 # and a person never sees open-demo's
    assert [t["token_id"] for t in client.get(K + "/approval-tokens").json()["tokens"]] == [out["token_id"]]
    r = client.delete(f"{K}/approval-tokens/{demo['token_id']}")
    assert r.status_code == 404 and r.json()["error"]["code"] == "TOKEN_NOT_FOUND"


def test_the_open_demo_cannot_revoke_a_real_persons_token(env):
    client, _, db = env
    out, tka = personal(client, db)
    r = client.delete(f"{K}/approval-tokens/{out['token_id']}", headers=HUMAN)
    assert r.status_code == 404 and r.json()["error"]["code"] == "TOKEN_NOT_FOUND"
    assert db.approval_tokens.find_one({"_id": out["token_id"]})["revoked_at"] is None
    assert client.get(K + "/proposals", headers=tka).status_code == 200    # aron's still works
    assert not db.audit_log.find_one({"event.kind": "approval_token_revoked"})


def test_the_open_demo_lists_and_revokes_its_own_tokens(env):
    client, _, db = env
    demo, tka = open_demo_token(client)
    r = client.delete(f"{K}/approval-tokens/{demo['token_id']}", headers=HUMAN)
    assert r.status_code == 200 and r.json()["revoked_at"] is not None
    assert client.get(K + "/proposals", headers=tka).status_code == 401
    row = client.get(K + "/approval-tokens", headers=HUMAN).json()["tokens"][0]
    assert row["token_id"] == demo["token_id"] and row["revoked_at"] is not None
    revoked = db.audit_log.find_one({"event.kind": "approval_token_revoked"})["event"]
    assert revoked["actor"] == "open-demo" and revoked["token_id"] == demo["token_id"]


def test_open_demo_tokens_are_capped_the_oldest_revoked_first(env, monkeypatch):
    client, _, db = env
    monkeypatch.setattr(approval_tokens, "OPEN_DEMO_CAP", 2)
    out, _ = personal(client, db)                                       # a person's token is never capped
    made = []
    for i in range(3):                                                  # the test clock stands still
        made.append(open_demo_token(client))
        db.approval_tokens.update_one({"_id": made[-1][0]["token_id"]},
                                      {"$set": {"created_at": NOW + timedelta(seconds=i)}})
    (first, tk1), (second, _), (third, tk3) = made
    active = [t["token_id"] for t in client.get(K + "/approval-tokens", headers=HUMAN).json()["tokens"]
              if t["revoked_at"] is None]
    assert active == [third["token_id"], second["token_id"]]
    assert client.get(K + "/proposals", headers=tk1).status_code == 401
    assert client.get(K + "/proposals", headers=tk3).status_code == 200
    capped = db.audit_log.find_one({"event.kind": "approval_token_revoked"})["event"]
    assert capped["token_id"] == first["token_id"] and capped["reason"] == "open_demo_cap"
    assert db.approval_tokens.find_one({"_id": out["token_id"]})["revoked_at"] is None


def test_open_demo_off_needs_a_signed_in_account_and_stops_open_demo_tokens(env, monkeypatch):
    client, _, db = env
    _, tka = open_demo_token(client)
    out, tk_person = personal(client, db)
    monkeypatch.setattr(approval_tokens, "open_demo_on", lambda: False)    # shared token still resolves
    for method, path in (("POST", K + "/approval-tokens"), ("GET", K + "/approval-tokens"),
                         ("DELETE", f"{K}/approval-tokens/{out['token_id']}")):
        r = client.request(method, path, headers=HUMAN, json={} if method == "POST" else None)
        assert r.status_code == 403 and r.json()["error"]["code"] == "PERSONAL_TOKEN_NEEDS_SIGN_IN", path
    assert client.get(K + "/proposals", headers=tka).status_code == 401
    monkeypatch.undo()
    monkeypatch.setenv("GATEWAY_HUMAN_TOKEN", "human-test-token")
    monkeypatch.setenv("GATEWAY_AGENT_TOKEN", "agent-test-token")
    monkeypatch.setenv("GATEWAY_REQUIRE_LOGIN", "true")                    # the real switch
    assert client.post(K + "/approval-tokens", headers=HUMAN, json={}).status_code == 401
    assert client.get(K + "/proposals", headers=tka).status_code == 401
    assert client.get(K + "/proposals", headers=tk_person).status_code == 200
    sign_in(client, "aron@example.com")
    assert client.post(K + "/approval-tokens", json={}).status_code == 200


def test_another_approver_neither_sees_nor_revokes_my_token(env):
    client, _, db = env
    out, _ = personal(client, db)
    users.create_user(db, "maciek@example.com", PW, name="Maciek", role="approver", kitchen_id="demo-kitchen")
    sign_in(client, "maciek@example.com")
    assert client.get(K + "/approval-tokens").json()["tokens"] == []
    r = client.delete(f"{K}/approval-tokens/{out['token_id']}")
    assert r.status_code == 404 and r.json()["error"]["code"] == "TOKEN_NOT_FOUND"
    assert db.approval_tokens.find_one({"_id": out["token_id"]})["revoked_at"] is None


def test_a_chef_cannot_create_one(env):
    client, _, db = env
    people(db)
    sign_in(client, "chef@example.com")
    r = client.post(K + "/approval-tokens", json={})
    assert r.status_code == 403 and r.json()["error"]["code"] == "ROLE_REQUIRED"


def test_agent_kitchen_and_personal_tokens_cannot_create_one(env):
    client, _, db = env
    kitchen = client.post(K + "/tokens", headers=HUMAN, json={"name": "k", "scopes": ["kitchen:read", "kitchen:propose"]}).json()
    _, tka = personal(client, db)
    for headers in (AGENT, {"Authorization": "Bearer " + kitchen["token"]}, tka):
        r = client.post(K + "/approval-tokens", headers=headers, json={})
        assert r.status_code == 403 and r.json()["error"]["code"] == "HUMAN_SESSION_REQUIRED"


def test_another_kitchen_is_refused(env):
    client, _, db = env
    people(db)
    sign_in(client, "aron@example.com")
    r = client.post("/v1/kitchens/other-kitchen/approval-tokens", json={})
    assert r.status_code == 403 and r.json()["error"]["code"] == "KITCHEN_SCOPE"


def test_create_checks_the_account_exists_and_is_an_approver(env):
    _, _, db = env
    people(db)
    with pytest.raises(approval_tokens.ApprovalTokenError) as gone:
        approval_tokens.create(db, "nobody@example.com", "demo-kitchen", "operator-cli")
    assert gone.value.code == "UNKNOWN_PERSON"
    with pytest.raises(approval_tokens.ApprovalTokenError) as chef:
        approval_tokens.create(db, "chef@example.com", "demo-kitchen", "operator-cli")
    assert chef.value.code == "ROLE_REQUIRED"
    with pytest.raises(approval_tokens.ApprovalTokenError) as other:
        approval_tokens.create(db, "aron@example.com", "other-kitchen", "operator-cli")
    assert other.value.code == "KITCHEN_SCOPE"


# ---- what it can do ---------------------------------------------------------------------

def test_approve_via_rest_is_audited_with_the_person_and_via(env):
    client, _, db = env
    out, tka = personal(client, db)
    me = client.get("/v1/me", headers=tka).json()
    assert me["kind"] == "personal" and me["name"] == "aron@example.com" and me["can_approve"] is True
    assert me["via"] == "personal_token" and me["scopes"] == ["kitchen:read"]
    p = milk(client)
    r = client.post(f"{K}/proposals/{p['proposal_id']}/approve", headers=tka, json=approve_body(p))
    assert r.status_code == 200, r.text
    placed = db.audit_log.find_one({"event.kind": "order_placed"})["event"]
    assert placed["actor"] == "aron@example.com"
    assert placed["via"] == "personal_token" and placed["token_id"] == out["token_id"]
    assert out["token"] not in json.dumps([e["event"] for e in db.audit_log.find()], default=str)
    assert db.orders.find_one({})["approved_by"] == "aron@example.com"


def test_reject_via_rest_is_audited_with_via(env):
    client, _, db = env
    out, tka = personal(client, db)
    p = milk(client)
    r = client.post(f"{K}/proposals/{p['proposal_id']}/reject", headers=tka,
                    json={"reason": "too much", "idempotency_key": "r"})
    assert r.status_code == 200 and r.json()["status"] == "REJECTED"
    event = db.audit_log.find_one({"event.kind": "proposal_rejected"})["event"]
    assert event["actor"] == "aron@example.com"
    assert event["via"] == "personal_token" and event["token_id"] == out["token_id"]


def test_total_mismatch_and_required_fields_still_apply(env):
    client, _, db = env
    _, tka = personal(client, db)
    p = milk(client)
    url = f"{K}/proposals/{p['proposal_id']}/approve"
    r = client.post(url, headers=tka, json={"expected_total": "1.00", "idempotency_key": "x"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "TOTAL_MISMATCH"
    assert client.post(url, headers=tka, json={"idempotency_key": "x"}).status_code == 422
    assert client.post(url, headers=tka, json={"expected_total": p["expected_total"]}).status_code == 422
    first = client.post(url, headers=tka, json=approve_body(p, "k1"))
    again = client.post(url, headers=tka, json=approve_body(p, "k1"))       # replay, same order
    assert first.status_code == again.status_code == 200 and first.json()["order_id"] == again.json()["order_id"]
    other = client.post(url, headers=tka, json=approve_body(p, "k2"))
    assert other.status_code == 409 and other.json()["error"]["code"] == "NOT_PENDING"
    assert db.orders.count_documents({}) == 1


def test_a_person_who_is_no_longer_an_approver_cannot_approve(env):
    client, _, db = env
    _, tka = personal(client, db)
    db.users.update_one({"_id": "aron@example.com"}, {"$set": {"role": "chef"}})
    p = milk(client)
    r = client.post(f"{K}/proposals/{p['proposal_id']}/approve", headers=tka, json=approve_body(p))
    assert r.status_code == 403 and r.json()["error"]["code"] == "ROLE_REQUIRED"
    db.users.delete_one({"_id": "aron@example.com"})
    assert client.get(K + "/proposals", headers=tka).status_code == 401


def test_a_person_moved_to_another_kitchen_cannot_approve(env):
    client, _, db = env
    _, tka = personal(client, db)
    p = milk(client)
    db.users.update_one({"_id": "aron@example.com"}, {"$set": {"kitchen_id": "other-kitchen"}})
    r = client.post(f"{K}/proposals/{p['proposal_id']}/approve", headers=tka, json=approve_body(p))
    assert r.status_code == 401 and r.json()["error"]["code"] == "UNAUTHENTICATED"
    assert db.orders.count_documents({}) == 0


# ---- what it cannot do ------------------------------------------------------------------

def test_agent_and_kitchen_tokens_still_cannot_approve(env):
    client, _, db = env
    kitchen = client.post(K + "/tokens", headers=HUMAN, json={"name": "k", "scopes": ["kitchen:read", "kitchen:propose"]}).json()
    p = milk(client)
    for headers in (AGENT, {"Authorization": "Bearer " + kitchen["token"]}):
        r = client.post(f"{K}/proposals/{p['proposal_id']}/approve", headers=headers, json=approve_body(p))
        assert r.status_code == 403 and r.json()["error"]["code"] == "HUMAN_SESSION_REQUIRED"
    assert db.orders.count_documents({}) == 0


def test_expired_and_revoked_tokens_are_401(env):
    client, _, db = env
    out, tka = personal(client, db)
    old = approval_tokens.create(db, "aron@example.com", "demo-kitchen", "operator-cli",
                                 hours=8, now=NOW - timedelta(hours=9))
    r = client.get(K + "/proposals", headers={"Authorization": "Bearer " + old["token"]})
    assert r.status_code == 401 and r.json()["error"]["code"] == "UNAUTHENTICATED"
    assert client.get(K + "/proposals", headers=tka).status_code == 200
    sign_in(client, "aron@example.com")
    gone = client.delete(f"{K}/approval-tokens/{out['token_id']}")
    assert gone.status_code == 200 and gone.json()["revoked_at"]
    client.cookies.clear()
    assert client.get(K + "/proposals", headers=tka).status_code == 401
    assert client.get("/v1/me", headers={"Authorization": "Bearer tka_made-up"}).status_code == 401


def test_it_cannot_propose(env):
    client, _, db = env
    _, tka = personal(client, db)
    p = milk(client)
    calls = (
        ("POST", K + "/proposals", {"product_ids": ["462775"], "quantity": "5", "unit": "L",
                                    "requested_date": "2026-11-16", "idempotency_key": "x"}),
        ("POST", K + "/proposals", {"text": "40 L milk", "requested_date": "2026-11-16", "idempotency_key": "y"}),
        ("POST", K + "/needs", {"quantity": "5", "unit": "L", "requested_date": "2026-11-16"}),
        ("POST", f"{K}/proposals/{p['proposal_id']}/change",
         {"idempotency_key": "c", "lines": [{"product_id": "462775", "quantity": "1"}]}),
        ("POST", "/tools/get_offer", {"need_id": "n", "product_ids": ["462775"]}),
        ("POST", "/tools/simulate_order", {"offer_id": p["offer_id"]}),
        ("POST", "/tools/request_approval", {"offer_id": p["offer_id"], "idempotency_key": "q"}),
        ("POST", "/tools/place_order", {"offer_id": p["offer_id"], "expected_total": p["expected_total"],
                                        "idempotency_key": "o"}),
        ("POST", "/tools/change_proposal", {"proposal_id": p["proposal_id"], "idempotency_key": "c"}),
    )
    for method, path, body in calls:
        r = client.request(method, path, headers=tka, json=body)
        assert r.status_code == 403 and r.json()["error"]["code"] == "SCOPE_REQUIRED", (path, r.text)
    assert db.proposals.count_documents({}) == 1


def test_it_cannot_call_settings_users_tokens_or_sharing(env):
    client, _, db = env
    _, tka = personal(client, db)
    for method, path, body in (
        ("PUT", K + "/settings", {"service_level": 0.9}),
        ("PUT", K + "/sharing", {"supplier_id": "valio", "share_forecast": True}),
        ("PUT", K + "/auto-approve", {"enabled": False}),
        ("POST", K + "/tokens", {"name": "x", "scopes": ["kitchen:read"]}),
        ("GET", K + "/tokens", None),
        ("GET", K + "/approval-tokens", None),
        ("POST", K + "/webhooks", {"url": "https://example.com/h", "events": ["order_placed"]}),
    ):
        r = client.request(method, path, headers=tka, json=body)
        assert r.status_code == 403, (path, r.text)
        assert r.json()["error"]["code"] == "HUMAN_SESSION_REQUIRED", (path, r.text)
    r = client.post("/v1/auth/change-password", headers=tka, json={"current_password": PW, "new_password": "x" * 12})
    assert r.status_code == 401


# ---- MCP --------------------------------------------------------------------------------

def rpc(client, method, params, auth):
    return client.post("/mcp", headers={**MCP_HEADERS, **auth},
                       json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params})


def tools(client, auth):
    r = rpc(client, "tools/list", {}, auth)
    assert r.status_code == 200, r.text
    return {t["name"]: t for t in r.json()["result"]["tools"]}


def call(client, auth, tool, arguments):
    r = rpc(client, "tools/call", {"name": tool, "arguments": arguments}, auth)
    assert r.status_code == 200, r.text
    result = r.json()["result"]
    data = json.loads(result["content"][0]["text"]) if result.get("content") and not result.get("isError") else None
    return result, data


@pytest.fixture()
def mcp_env(env):
    client, fake, db = env
    with client:                 # runs the MCP session manager
        yield client, fake, db


def test_tools_list_depends_on_the_caller(mcp_env):
    client, _, db = mcp_env
    kitchen = client.post(K + "/tokens", headers=HUMAN, json={"name": "k", "scopes": ["kitchen:read", "kitchen:propose"]}).json()
    assert set(tools(client, AGENT)) == AGENT_TOOLS
    assert set(tools(client, {"Authorization": "Bearer " + kitchen["token"]})) == AGENT_TOOLS
    _, tka = personal(client, db)
    listed = tools(client, tka)
    assert set(listed) == PERSON_TOOLS
    for name in ("approve_proposal", "reject_proposal"):
        text = " ".join(listed[name]["description"].split()).lower()
        assert "only works with a person's approval token; show the person the total and get their explicit yes before calling" in text
    assert set(tools(client, AGENT)) == AGENT_TOOLS            # nothing leaks into the next call


def test_approve_over_mcp_with_the_personal_token(mcp_env):
    client, _, db = mcp_env
    out, tka = personal(client, db)
    p = milk(client)
    _, listed = call(client, tka, "list_proposals", {})
    assert p["proposal_id"] in [row["proposal_id"] for row in listed["proposals"]]
    _, shown = call(client, tka, "get_proposal", {"proposal_id": p["proposal_id"]})
    assert shown["expected_total"] == p["expected_total"]
    bad, _ = call(client, tka, "approve_proposal", {"proposal_id": p["proposal_id"], "expected_total": "1.00",
                                                    "idempotency_key": "m0"})
    assert bad["isError"] is True and "TOTAL_MISMATCH" in bad["content"][0]["text"]
    result, order = call(client, tka, "approve_proposal", {"proposal_id": p["proposal_id"],
                                                           "expected_total": p["expected_total"],
                                                           "idempotency_key": "m1"})
    assert not result.get("isError"), result
    assert order["order_id"]
    placed = db.audit_log.find_one({"event.kind": "order_placed"})["event"]
    assert placed["actor"] == "aron@example.com" and placed["via"] == "personal_token"
    assert placed["token_id"] == out["token_id"]
    _, orders = call(client, tka, "list_orders", {})
    assert [o["order_id"] for o in orders["orders"]] == [order["order_id"]]


def test_reject_over_mcp_with_the_personal_token(mcp_env):
    client, _, db = mcp_env
    _, tka = personal(client, db)
    p = milk(client)
    result, out = call(client, tka, "reject_proposal", {"proposal_id": p["proposal_id"], "reason": "not today",
                                                        "idempotency_key": "r1"})
    assert not result.get("isError"), result
    assert out["status"] == "REJECTED"
    assert db.audit_log.find_one({"event.kind": "proposal_rejected"})["event"]["via"] == "personal_token"


def test_hidden_tools_with_agent_or_kitchen_token_get_the_routes_403(mcp_env):
    client, _, db = mcp_env
    kitchen = client.post(K + "/tokens", headers=HUMAN, json={"name": "k", "scopes": ["kitchen:read", "kitchen:propose"]}).json()
    p = milk(client)
    for auth in (AGENT, {"Authorization": "Bearer " + kitchen["token"]}):
        result, _ = call(client, auth, "approve_proposal", {"proposal_id": p["proposal_id"],
                                                            "expected_total": p["expected_total"],
                                                            "idempotency_key": "agent-tries"})
        assert result["isError"] is True and "403 HUMAN_SESSION_REQUIRED" in result["content"][0]["text"]
        result, _ = call(client, auth, "reject_proposal", {"proposal_id": p["proposal_id"], "reason": "x",
                                                           "idempotency_key": "agent-tries"})
        assert result["isError"] is True and "403 HUMAN_SESSION_REQUIRED" in result["content"][0]["text"]
    assert db.orders.count_documents({}) == 0


def test_personal_token_cannot_propose_over_mcp(mcp_env):
    client, _, db = mcp_env
    _, tka = personal(client, db)
    p = milk(client)
    result, _ = call(client, tka, "request_approval", {"offer_id": p["offer_id"]})
    assert result["isError"] is True and "403 SCOPE_REQUIRED" in result["content"][0]["text"]
    result, _ = call(client, tka, "simulate_order", {"offer_id": p["offer_id"]})
    assert result["isError"] is True and "403 SCOPE_REQUIRED" in result["content"][0]["text"]


def test_expired_personal_token_is_401_on_mcp(mcp_env):
    client, _, db = mcp_env
    people(db)
    old = approval_tokens.create(db, "aron@example.com", "demo-kitchen", "operator-cli",
                                 hours=1, now=NOW - timedelta(hours=2))
    r = rpc(client, "tools/list", {}, {"Authorization": "Bearer " + old["token"]})
    assert r.status_code == 401


def test_personal_token_of_a_person_moved_to_another_kitchen_is_401_on_mcp(mcp_env):
    client, _, db = mcp_env
    _, tka = personal(client, db)
    db.users.update_one({"_id": "aron@example.com"}, {"$set": {"kitchen_id": "other-kitchen"}})
    assert rpc(client, "tools/list", {}, tka).status_code == 401


# ---- connector link: /mcp/t/<token> (#1693) ------------------------------------------------

def rpc_path(client, token, method, params, headers=None, slash=""):
    return client.post(f"/mcp/t/{token}{slash}", headers={**MCP_HEADERS, **(headers or {})},
                       json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params})


def call_path(client, token, tool, arguments):
    r = rpc_path(client, token, "tools/call", {"name": tool, "arguments": arguments})
    assert r.status_code == 200, r.text
    result = r.json()["result"]
    data = json.loads(result["content"][0]["text"]) if result.get("content") and not result.get("isError") else None
    return result, data


def test_path_token_lists_the_person_tools_and_approves_with_expected_total(mcp_env):
    client, _, db = mcp_env
    out, _ = personal(client, db)
    token = out["token"]
    for slash in ("", "/"):
        r = rpc_path(client, token, "tools/list", {}, slash=slash)
        assert r.status_code == 200, r.text
        assert {t["name"] for t in r.json()["result"]["tools"]} == PERSON_TOOLS
    p = milk(client)
    bad, _ = call_path(client, token, "approve_proposal", {"proposal_id": p["proposal_id"]})
    assert bad["isError"] is True                      # expected_total is still required
    result, order = call_path(client, token, "approve_proposal", {"proposal_id": p["proposal_id"],
                                                                  "expected_total": p["expected_total"],
                                                                  "idempotency_key": "path-yes"})
    assert not result.get("isError"), result
    assert order["order_id"]
    placed = db.audit_log.find_one({"event.kind": "order_placed"})["event"]
    assert placed["actor"] == "aron@example.com" and placed["via"] == "personal_token"
    assert placed["token_id"] == out["token_id"]
    secret = token[8:]
    for row in db.audit_log.find({}):
        assert secret not in json.dumps(row, default=str)


def test_path_token_open_demo_works_only_in_its_kitchen(mcp_env):
    client, _, _ = mcp_env
    out, _ = open_demo_token(client)
    r = rpc_path(client, out["token"], "tools/list", {})
    assert r.status_code == 200 and {t["name"] for t in r.json()["result"]["tools"]} == PERSON_TOOLS


def test_path_refuses_agent_kitchen_human_unknown_expired_and_revoked_the_same_way(mcp_env, monkeypatch):
    client, _, db = mcp_env
    kitchen = client.post(K + "/tokens", headers=HUMAN, json={"name": "k", "scopes": ["kitchen:read", "kitchen:propose"]}).json()
    out, _ = personal(client, db)
    old = approval_tokens.create(db, "aron@example.com", "demo-kitchen", "operator-cli",
                                 hours=1, now=NOW - timedelta(hours=2))
    revoked = approval_tokens.create(db, "aron@example.com", "demo-kitchen", "operator-cli", hours=8, now=NOW)
    approval_tokens.revoke(db, "demo-kitchen", revoked["token_id"])
    bad = [AGENT["Authorization"][7:], HUMAN["Authorization"][7:], kitchen["token"], "tka_made-up",
           old["token"], revoked["token"], out["token"] + "/extra", ""]
    answers = set()
    for token in bad:
        r = rpc_path(client, token, "tools/list", {})
        assert r.status_code == 401, (token[:8], r.text)
        assert "www-authenticate" not in r.headers
        answers.add(r.text)
    assert answers == {'{"error":{"code":"UNAUTHENTICATED","message":"unauthenticated"}}'}


def test_path_token_wins_over_a_header_token(mcp_env):
    client, _, db = mcp_env
    out, _ = personal(client, db)
    r = rpc_path(client, out["token"], "tools/list", {}, headers=AGENT)
    assert {t["name"] for t in r.json()["result"]["tools"]} == PERSON_TOOLS
    r = rpc_path(client, AGENT["Authorization"][7:], "tools/list", {}, headers={"Authorization": "Bearer " + out["token"]})
    assert r.status_code == 401


def test_path_token_is_masked_in_every_uvicorn_and_gateway_log_line(mcp_env, caplog):
    import logging

    from gateway.mcp_http import mask_path_token
    client, _, db = mcp_env
    out, _ = personal(client, db)
    token = out["token"]
    assert mask_path_token(f"POST /mcp/t/{token} HTTP/1.1") == f"POST /mcp/t/{token[:8]}... HTTP/1.1"
    assert mask_path_token("POST /mcp HTTP/1.1") == "POST /mcp HTTP/1.1"
    with caplog.at_level(logging.INFO):
        # uvicorn's access logger passes the path in the args tuple; its formatter unpacks five.
        logging.getLogger("uvicorn.access").info('%s - "%s %s HTTP/%s" %d', "1.2.3.4", "POST", f"/mcp/t/{token}", "1.1", 200)
        logging.getLogger("uvicorn.error").info(f"error at /gateway/mcp/t/{token}/")
        logging.getLogger("gateway").info("seen %s", f"/mcp/t/{token}")
        logging.getLogger("gateway.app").info(f"child saw /mcp/t/{token}")  # propagates past logger filters (#1710)
        rpc_path(client, token, "tools/list", {})
    assert caplog.records
    for record in caplog.records:
        assert token[8:] not in record.getMessage()
    access = [r for r in caplog.records if r.name == "uvicorn.access"][0]
    assert isinstance(access.args, tuple) and len(access.args) == 5 and access.args[2] == f"/mcp/t/{token[:8]}..."
    child = [r for r in caplog.records if r.name == "gateway.app"][0]
    assert child.getMessage() == f"child saw /mcp/t/{token[:8]}..."


# ---- operator CLI -----------------------------------------------------------------------

def test_the_operator_cli_lists_and_revokes_every_persons_token(env, monkeypatch, capsys):
    client, _, db = env
    aron, _ = personal(client, db)
    users.create_user(db, "maciek@example.com", PW, name="Maciek", role="approver", kitchen_id="demo-kitchen")
    sign_in(client, "maciek@example.com")
    maciek = client.post(K + "/approval-tokens", json={}).json()
    from gateway import tokens
    import store.db
    monkeypatch.setattr(store.db, "get_db", lambda: db)
    capsys.readouterr()
    assert tokens.main(["list-approvers"]) == 0
    listing = capsys.readouterr().out
    assert aron["token_id"] in listing and maciek["token_id"] in listing
    for out in (aron, maciek):
        assert tokens.main(["remove-approver", "--token-id", out["token_id"]]) == 0
        assert db.approval_tokens.find_one({"_id": out["token_id"]})["revoked_at"] is not None


def test_cli_add_list_remove(env, monkeypatch, capsys):
    _, _, db = env
    people(db)
    from gateway import tokens
    import store.db
    monkeypatch.setattr(store.db, "get_db", lambda: db)
    assert tokens.main(["add-approver", "--email", "Aron@Example.com", "--hours", "4"]) == 0
    printed = capsys.readouterr().out
    row = db.approval_tokens.find_one({})
    assert row["person"] == "aron@example.com" and row["created_by"] == "operator-cli"
    secret = [w for w in printed.split() if w.startswith("tka_")]
    assert len(secret) == 1                                            # printed once, to this terminal
    assert tokens.main(["list-approvers"]) == 0
    listing = capsys.readouterr().out
    assert row["_id"] in listing and secret[0] not in listing
    assert tokens.main(["remove-approver", "--token-id", row["_id"]]) == 0
    assert db.approval_tokens.find_one({})["revoked_at"] is not None
    assert tokens.main(["add-approver", "--email", "chef@example.com"]) == 1
    assert tokens.main(["add-approver", "--email", "aron@example.com", "--hours", "25"]) == 1
    kinds = [e["event"]["kind"] for e in db.audit_log.find()]
    assert "approval_token_created" in kinds and "approval_token_revoked" in kinds
