"""Sign-in, sessions, roles and change password (#270)."""

from gateway import users
from gateway.tests.test_gateway_app import AGENT, HUMAN, K, env  # noqa: F401 (fixture)

PW = "correct horse 42"
NEW = "new pass 12345"
REQUEST = {"product_ids": ["462775"], "quantity": "40", "unit": "L",
           "requested_date": "2026-11-16", "idempotency_key": "p"}


def people(db):
    users.create_user(db, "Aron@Example.com", PW, name="Aron", role="approver", kitchen_id="demo-kitchen")
    users.create_user(db, "chef@example.com", PW, name="Chef", role="chef", kitchen_id="demo-kitchen")
    users.create_user(db, "view@example.com", PW, name="Viewer", role="viewer", kitchen_id="demo-kitchen")


def sign_in(client, email, password=PW):
    client.cookies.clear()
    return client.post("/v1/auth/login", json={"email": email, "password": password})


def test_password_is_hashed_and_login_sets_an_httponly_cookie(env):
    client, _, db = env
    people(db)
    stored = db.users.find_one({"_id": "aron@example.com"})
    assert PW.encode() not in stored["password"] and len(stored["password"]) == 32
    r = sign_in(client, "ARON@example.com")
    assert r.status_code == 200 and r.json()["role"] == "approver"
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    me = client.get("/v1/me").json()
    assert me["name"] == "aron@example.com" and me["can_approve"] is True


def test_wrong_password_and_unknown_email_look_the_same_then_lock(env):
    client, _, db = env
    people(db)
    a = sign_in(client, "aron@example.com", "nope nope nope")
    b = sign_in(client, "nobody@example.com", "nope nope nope")
    assert a.status_code == b.status_code == 401 and a.json() == b.json()
    for _ in range(4):
        sign_in(client, "aron@example.com", "nope nope nope")
    locked = sign_in(client, "aron@example.com")
    assert locked.status_code == 429 and locked.json()["error"]["code"] == "ACCOUNT_LOCKED"


def test_roles_viewer_reads_chef_asks_only_approver_approves(env):
    client, _, db = env
    people(db)
    sign_in(client, "view@example.com")
    assert client.get(K + "/orders").status_code == 200
    r = client.post(K + "/proposals", json=REQUEST)
    assert r.status_code == 403 and r.json()["error"]["code"] == "ROLE_REQUIRED"
    sign_in(client, "chef@example.com")
    p = client.post(K + "/proposals", json=REQUEST).json()
    approve = {"expected_total": p["expected_total"], "idempotency_key": "a"}
    r = client.post(f"{K}/proposals/{p['proposal_id']}/approve", json=approve)
    assert r.status_code == 403 and r.json()["error"]["code"] == "ROLE_REQUIRED"
    assert client.post(K + "/tokens", json={"name": "x", "scopes": ["kitchen:read"]}).status_code == 403
    sign_in(client, "aron@example.com")
    r = client.post(f"{K}/proposals/{p['proposal_id']}/approve", json=approve)
    assert r.status_code == 200, r.text
    assert db.orders.find_one({})["approved_by"] == "aron@example.com"


def test_session_is_bound_to_its_kitchen_and_logout_ends_it(env):
    client, _, db = env
    people(db)
    sign_in(client, "aron@example.com")
    assert client.get("/v1/kitchens/other/orders").status_code == 403
    assert client.post("/v1/auth/logout").json() == {"signed_out": True}
    assert client.get(K + "/orders").status_code == 401


def test_change_password_ends_other_sessions(env):
    client, _, db = env
    people(db)
    old = sign_in(client, "aron@example.com").cookies.get(users.COOKIE)
    sign_in(client, "aron@example.com")
    bad = client.post("/v1/auth/change-password", json={"current_password": "wrong", "new_password": NEW})
    assert bad.status_code == 401
    weak = client.post("/v1/auth/change-password", json={"current_password": PW, "new_password": "short"})
    assert weak.status_code == 422 and weak.json()["error"]["code"] == "WEAK_PASSWORD"
    ok = client.post("/v1/auth/change-password", json={"current_password": PW, "new_password": NEW})
    assert ok.status_code == 200
    assert client.get("/v1/me").status_code == 200       # this session stays
    assert users.session_user(db, old) is None            # the other one is gone
    assert sign_in(client, "aron@example.com").status_code == 401
    assert sign_in(client, "aron@example.com", NEW).status_code == 200


def test_require_login_switches_off_the_shared_human_token(env, monkeypatch):
    client, _, db = env
    assert client.get(K + "/orders", headers=HUMAN).status_code == 200
    monkeypatch.setenv("GATEWAY_REQUIRE_LOGIN", "true")
    assert client.get(K + "/orders", headers=HUMAN).status_code == 401
    assert client.get(K + "/orders", headers=AGENT).status_code == 200   # the Buyer still works


def test_demo_approver_is_seeded_from_the_server_env(env, monkeypatch):
    client, _, db = env
    monkeypatch.setenv("DEMO_USER_EMAIL", "demo@example.com")
    monkeypatch.setenv("DEMO_USER_PASSWORD", "demo password 1")
    assert sign_in(client, "demo@example.com", "demo password 1").status_code == 200
    assert db.users.count_documents({}) == 1


def test_wrong_current_password_counts_toward_the_lockout(env):
    client, _, db = env
    people(db)
    sign_in(client, "aron@example.com")
    for _ in range(users.MAX_FAILS):
        bad = client.post("/v1/auth/change-password", json={"current_password": "wrong", "new_password": NEW})
        assert bad.status_code == 401
    locked = client.post("/v1/auth/change-password", json={"current_password": PW, "new_password": NEW})
    assert locked.status_code == 429 and locked.json()["error"]["code"] == "ACCOUNT_LOCKED"
    assert sign_in(client, "aron@example.com").status_code == 429


class _RacingUsers:
    """find_one misses, as if a concurrent first login had not inserted yet; insert_one is real."""

    def __init__(self, real):
        self.real = real

    def find_one(self, *args, **kwargs):
        return None

    def insert_one(self, doc):
        return self.real.insert_one(doc)


def test_seed_user_does_not_raise_when_inserted_concurrently(env):
    _, _, db = env
    users.create_user(db, "demo@example.com", "demo password 1", name="D", role="approver", kitchen_id="k")
    racing = type("RacingDb", (), {"users": _RacingUsers(db.users)})()
    assert users.seed_user(racing, "demo@example.com", "demo password 1", "k") is False
    assert db.users.count_documents({}) == 1
