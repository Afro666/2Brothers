"""Onboarding lookup (#375): the contract answer from a recorded Context.dev response.

No network: `gateway.onboarding._post` is replaced. The fixture is one real
`POST /v1/brand/retrieve` answer (by_domain, scandichotels.com), trimmed, without the
request id, the credit counters or any key.
"""

import json
from pathlib import Path

import pytest

mongomock = pytest.importorskip("mongomock")
pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from gateway import onboarding, tokens  # noqa: E402
from gateway.app import create_app  # noqa: E402
from gateway.service import Gateway  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "context_brand_retrieve.json"
HUMAN = {"Authorization": "Bearer human-test-token", "X-User": "aron"}
AGENT = {"Authorization": "Bearer agent-test-token"}
KEY = "ctx-test-key-never-real"
URL = "/v1/onboarding/lookup"
SOURCE = {"provider": "Context.dev", "endpoint": "POST /v1/brand/retrieve"}
UNKNOWN = {"value": None, "source": None}


def recorded() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture()
def env(monkeypatch):
    monkeypatch.setenv("GATEWAY_HUMAN_TOKEN", "human-test-token")
    monkeypatch.setenv("GATEWAY_AGENT_TOKEN", "agent-test-token")
    monkeypatch.setenv("CONTEXT_DEV_API_KEY", KEY)
    monkeypatch.delenv("GATEWAY_REQUIRE_LOGIN", raising=False)
    db = mongomock.MongoClient(tz_aware=True)["test"]
    upstream = {"answer": (200, recorded()), "calls": []}

    def fake_post(payload, key):
        upstream["calls"].append((payload, key))
        if isinstance(upstream["answer"], Exception):
            raise upstream["answer"]
        return upstream["answer"]

    monkeypatch.setattr(onboarding, "_post", fake_post)
    return TestClient(create_app(Gateway(db, None))), upstream, db


def test_website_fills_the_profile(env):
    client, upstream, _ = env
    r = client.post(URL, headers=HUMAN, json={"website": "https://www.ScandicHotels.com/en/hotels?x=1"})
    assert r.status_code == 200, r.text
    assert r.json() == {
        "domain": "scandichotels.com",
        "found": True,
        "name": {"value": "Scandic Hotels", "source": SOURCE},
        # the first `logo` in light mode, not the opaque-background icon
        "logo_url": {"value": "https://media.brand.dev/88e73623-d68f-47ec-ad51-595628effab3.svg",
                     "source": SOURCE},
        "colors": {"value": ["#d02f32", "#e48c94", "#040404"], "source": SOURCE},
        "address": {"value": {"street": "Sveavägen 167", "postal_code": "102 33",
                              "city": "Stockholm", "country": "Sweden"}, "source": SOURCE},
        "kitchen_type": {"value": "hotel", "source": SOURCE},
        "opening_hours": UNKNOWN,
    }
    assert upstream["calls"] == [({"type": "by_domain", "domain": "scandichotels.com"}, KEY)]
    assert KEY not in r.text


def test_email_is_looked_up_by_email(env):
    client, upstream, _ = env
    r = client.post(URL, headers=HUMAN, json={"email": " Chef@ScandicHotels.com "})
    assert r.status_code == 200, r.text
    assert r.json()["domain"] == "scandichotels.com" and r.json()["found"] is True
    assert upstream["calls"][0][0] == {"type": "by_email", "email": "Chef@scandichotels.com"}


@pytest.mark.parametrize("website, domain", [
    ("hotelkuusi.fi", "hotelkuusi.fi"),
    ("www.hotelkuusi.fi/", "hotelkuusi.fi"),
    ("HTTP://Hotelkuusi.FI:8080/contact", "hotelkuusi.fi"),
    ("https://ravintola-ähtäri.fi", "xn--ravintola-htri-fibc.fi"),
])
def test_website_forms(env, website, domain):
    client, upstream, _ = env
    r = client.post(URL, headers=HUMAN, json={"website": website})
    assert r.status_code == 200, r.text
    assert r.json()["domain"] == domain
    assert upstream["calls"][0][0] == {"type": "by_domain", "domain": domain}


@pytest.mark.parametrize("body", [
    {}, {"email": "a@b.fi", "website": "b.fi"}, {"email": None}, {"email": 7}, {"website": ["x.fi"]},
    {"email": "not-an-email"}, {"email": "a@@b.fi"}, {"email": "a b@c.fi"}, {"email": "@b.fi"},
    {"email": "chef@localhost"}, {"website": ""}, {"website": "kuusi"}, {"website": "http://127.0.0.1/"},
    {"website": "http://[::1]/"}, {"website": "ftp://hotelkuusi.fi"}, {"website": "https://a:b@hotelkuusi.fi"},
    {"website": "https://hotel kuusi.fi"}, {"website": "javascript:alert(1)"}, {"website": "x" * 2001 + ".fi"},
])
def test_bad_query_is_422_and_never_reaches_context_dev(env, body):
    client, upstream, _ = env
    r = client.post(URL, headers=HUMAN, json=body)
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "INVALID_QUERY"
    assert upstream["calls"] == []


def test_body_must_be_a_json_object(env):
    client, upstream, _ = env
    r = client.post(URL, headers=HUMAN, content=b"[1]")
    assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_JSON"
    assert upstream["calls"] == []


@pytest.mark.parametrize("code", ["FREE_EMAIL_DETECTED", "DISPOSABLE_EMAIL_DETECTED"])
@pytest.mark.parametrize("shape", ["flat", "nested"])
def test_free_email_asks_for_the_website(env, code, shape):
    client, upstream, _ = env
    error = {"error_code": code, "message": "x"} if shape == "flat" else {"error": {"code": code}}
    upstream["answer"] = (422, error)
    r = client.post(URL, headers=HUMAN, json={"email": "chef@gmail.com"})
    assert r.status_code == 422
    assert r.json() == {"error": {"code": "FREE_EMAIL", "message": "Type the kitchen's website instead."}}


def test_unknown_domain_is_found_false_with_every_field_unknown(env):
    client, upstream, _ = env
    upstream["answer"] = (400, {"status": "error", "error_code": "NOT_FOUND", "message": "Brand not found"})
    r = client.post(URL, headers=HUMAN, json={"website": "no-such-kitchen.fi"})
    assert r.status_code == 200
    assert r.json() == {"domain": "no-such-kitchen.fi", "found": False, "name": UNKNOWN, "logo_url": UNKNOWN,
                        "colors": UNKNOWN, "address": UNKNOWN, "kitchen_type": UNKNOWN,
                        "opening_hours": UNKNOWN}


def test_upstream_422_is_invalid_query(env):
    client, upstream, _ = env
    upstream["answer"] = (422, {"error_code": "VALIDATION_ERROR", "message": "bad domain"})
    r = client.post(URL, headers=HUMAN, json={"website": "odd-domain.fi"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_QUERY"


@pytest.mark.parametrize("answer", [
    (401, {"message": "invalid key " + KEY}), (402, {"error_code": "OUT_OF_CREDITS"}),
    (408, {}), (429, {}), (500, {}), (503, {}), (400, {"error_code": "SOMETHING_ELSE"}),
    (200, {}), (200, {"brand": None}), (200, {"status": "ok", "brand": "soon"}),
    TimeoutError("timed out"), ConnectionResetError("reset"), OSError("dns " + KEY), ValueError("not json"),
])
def test_context_dev_trouble_is_502(env, answer):
    client, upstream, _ = env
    upstream["answer"] = answer
    r = client.post(URL, headers=HUMAN, json={"website": "hotelkuusi.fi"})
    assert r.status_code == 502, r.text
    assert r.json()["error"]["code"] == "LOOKUP_UNAVAILABLE"
    assert KEY not in r.text and "timed out" not in r.text


def test_missing_key_is_502_without_a_call(env, monkeypatch):
    client, upstream, _ = env
    monkeypatch.setenv("CONTEXT_DEV_API_KEY", "  ")
    r = client.post(URL, headers=HUMAN, json={"website": "hotelkuusi.fi"})
    assert r.status_code == 502 and r.json()["error"]["code"] == "LOOKUP_UNAVAILABLE"
    assert upstream["calls"] == []


def test_only_a_person_may_look_up(env):
    client, upstream, db = env
    assert client.post(URL, json={"website": "hotelkuusi.fi"}).status_code == 401
    made = tokens.create(db, "K01", "claude", ["kitchen:read", "kitchen:propose"], "aron")
    for headers in (AGENT, {"Authorization": "Bearer " + made["token"]}):
        r = client.post(URL, headers=headers, json={"website": "hotelkuusi.fi"})
        assert r.status_code == 403 and r.json()["error"]["code"] == "HUMAN_SESSION_REQUIRED"
    assert upstream["calls"] == []       # a refused caller costs no Context.dev credit


def test_nothing_is_saved(env):
    client, _, db = env

    def rows():
        return {name: db[name].count_documents({}) for name in db.list_collection_names()}

    before = rows()
    assert client.post(URL, headers=HUMAN, json={"website": "scandichotels.com"}).status_code == 200
    assert client.post(URL, headers=HUMAN, json={"email": "chef@scandichotels.com"}).status_code == 200
    assert rows() == before and not any(before.values())      # no profile, no audit entry


# ---- field rules (docs/contract.md table) -------------------------------------------

def test_missing_parts_are_null_never_guessed():
    out = onboarding.profile("x.fi", {"title": "  ", "logos": [], "colors": [],
                                      "address": {"city": "Tampere", "street": ""},
                                      "industries": {"eic": [{"industry": "Technology",
                                                              "subindustry": "Software"}]}})
    assert out["found"] is True
    assert out["name"] == UNKNOWN and out["logo_url"] == UNKNOWN and out["colors"] == UNKNOWN
    assert out["kitchen_type"] == UNKNOWN and out["opening_hours"] == UNKNOWN
    assert out["address"] == {"value": {"street": None, "postal_code": None, "city": "Tampere",
                                        "country": None}, "source": SOURCE}
    empty = onboarding.profile("x.fi", {"address": {"country_code": "FI"}, "logos": None, "colors": "red"})
    assert empty["address"] == UNKNOWN and empty["colors"] == UNKNOWN and empty["logo_url"] == UNKNOWN


def test_logo_choice():
    logo = onboarding._logo
    dark = {"url": "https://x/dark.svg", "mode": "dark", "type": "logo"}
    light_icon = {"url": "https://x/icon.png", "mode": "light", "type": "icon"}
    assert logo([dark, light_icon]) == "https://x/icon.png"          # light mode first
    assert logo([dark]) == "https://x/dark.svg"                      # else another mode
    assert logo([{"url": "http://x/plain.svg", "mode": "light", "type": "logo"}]) is None   # https only
    assert logo([{"url": "https://x/b.png", "mode": "light", "type": "backdrop"}, "junk", {}]) is None


def test_colors_are_lower_case_six_digit_hex_without_repeats():
    colors = onboarding._colors
    assert colors([{"hex": "#1F4D3A"}, {"hex": "#e9d8a6"}, {"hex": "#1f4d3a"}, {"hex": "red"},
                   {"hex": "#fff"}, {"name": "no hex"}, "x"]) == ["#1f4d3a", "#e9d8a6"]
    assert colors([{"hex": "nope"}]) is None


@pytest.mark.parametrize("industry, subindustry, expected", [
    ("Hospitality & Tourism", "Hotels & Accommodation", "hotel"),
    ("Hospitality & Tourism", "Restaurants & Food Service", "restaurant"),
    ("Education", "Primary & Secondary Education", "school"),
    ("Healthcare", "Hospitals & Health Care", "hospital"),
    ("Hospitality & Tourism", None, None),               # "Hospitality" is not "hospital"
    ("Hospitality & Tourism", "Travel Agencies", None),
    ("Education", "Higher Education", None),
    ("Healthcare", "Pharmaceuticals", None),             # the subindustry decides
    ("Technology", "Software", None),
])
def test_kitchen_type_only_when_the_industry_clearly_says_so(industry, subindustry, expected):
    line = {"industry": industry, "subindustry": subindustry}
    assert onboarding._kitchen_type({"eic": [line]}) == expected


def test_kitchen_type_is_unknown_when_industries_disagree():
    eic = [{"industry": "Hospitality & Tourism", "subindustry": "Hotels & Accommodation"},
           {"industry": "Hospitality & Tourism", "subindustry": "Restaurants & Food Service"}]
    assert onboarding._kitchen_type({"eic": eic}) is None
    assert onboarding._kitchen_type({"eic": eic[:1] * 2}) == "hotel"
    assert onboarding._kitchen_type(None) is None and onboarding._kitchen_type({"eic": ["x"]}) is None


def test_post_sends_the_key_only_in_the_header(monkeypatch):
    """The real `_post`, with urlopen replaced: URL, method, headers, timeout, body."""
    import io
    import urllib.error
    seen = {}

    class Answer(io.BytesIO):
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    def fake_urlopen(request, timeout):
        seen.update(url=request.full_url, method=request.get_method(), timeout=timeout,
                    headers={k.lower(): v for k, v in request.header_items()}, data=request.data)
        return Answer(b'{"status": "ok", "brand": {"title": "X"}}')

    monkeypatch.setattr(onboarding.urllib.request, "urlopen", fake_urlopen)
    status, body = onboarding._post({"type": "by_domain", "domain": "x.fi"}, KEY)
    assert (status, body) == (200, {"status": "ok", "brand": {"title": "X"}})
    assert seen["url"] == "https://api.context.dev/v1/brand/retrieve" and seen["method"] == "POST"
    assert seen["headers"]["authorization"] == "Bearer " + KEY
    assert seen["headers"]["user-agent"] == "2brothers-onboarding/0.1"
    assert seen["timeout"] >= 10                       # contract: at least 10,000 ms
    assert json.loads(seen["data"]) == {"type": "by_domain", "domain": "x.fi"} and KEY.encode() not in seen["data"]

    def refuse(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 422, "Unprocessable", {},
                                     io.BytesIO(b'{"error_code": "FREE_EMAIL_DETECTED"}'))

    monkeypatch.setattr(onboarding.urllib.request, "urlopen", refuse)
    assert onboarding._post({}, KEY) == (422, {"error_code": "FREE_EMAIL_DETECTED"})

    monkeypatch.setattr(onboarding.urllib.request, "urlopen",
                        lambda request, timeout: Answer(b"<html>gateway timeout</html>"))
    assert onboarding._post({}, KEY) == (200, {})      # not JSON: no brand, so the route says 502


# ---- credit limits (#604): a short cache by domain and a rate limit per caller ------

@pytest.fixture()
def clock(monkeypatch):
    """The module's clock, moved by hand: no test sleeps."""
    now = {"t": 1000.0}
    monkeypatch.setattr(onboarding, "_now", lambda: now["t"])
    return now


def test_same_domain_again_makes_no_second_context_dev_call(env, clock):
    client, upstream, _ = env
    first = client.post(URL, headers=HUMAN, json={"website": "https://www.scandichotels.com/en"})
    clock["t"] += 599
    again = client.post(URL, headers=HUMAN, json={"website": "ScandicHotels.com"})
    assert again.status_code == 200 and again.json() == first.json() and first.json()["found"] is True
    assert len(upstream["calls"]) == 1


def test_cache_expires_after_the_ttl(env, clock, monkeypatch):
    client, upstream, _ = env
    client.post(URL, headers=HUMAN, json={"website": "scandichotels.com"})
    clock["t"] += 600
    assert client.post(URL, headers=HUMAN, json={"website": "scandichotels.com"}).status_code == 200
    assert len(upstream["calls"]) == 2
    monkeypatch.setenv("ONBOARDING_CACHE_TTL_S", "5")        # the override, read at call time
    clock["t"] += 600
    client.post(URL, headers=HUMAN, json={"website": "scandichotels.com"})
    clock["t"] += 5
    client.post(URL, headers=HUMAN, json={"website": "scandichotels.com"})
    assert len(upstream["calls"]) == 4


@pytest.mark.parametrize("trouble", [(402, {"error_code": "OUT_OF_CREDITS"}), TimeoutError("timed out"),
                                     (422, {"error_code": "VALIDATION_ERROR"})])
def test_failed_lookup_is_not_cached(env, clock, trouble):
    client, upstream, _ = env
    upstream["answer"] = trouble
    assert client.post(URL, headers=HUMAN, json={"website": "scandichotels.com"}).status_code in (502, 422)
    upstream["answer"] = (200, recorded())
    r = client.post(URL, headers=HUMAN, json={"website": "scandichotels.com"})
    assert r.status_code == 200 and r.json()["found"] is True      # not the failure, not an empty profile
    assert len(upstream["calls"]) == 2


def test_not_found_is_cached_only_briefly(env, clock):
    client, upstream, _ = env
    upstream["answer"] = (400, {"error_code": "NOT_FOUND"})
    assert client.post(URL, headers=HUMAN, json={"website": "new-kitchen.fi"}).json()["found"] is False
    clock["t"] += 59
    assert client.post(URL, headers=HUMAN, json={"website": "new-kitchen.fi"}).json()["found"] is False
    assert len(upstream["calls"]) == 1
    upstream["answer"] = (200, recorded())      # Context.dev has read the site by now
    clock["t"] += 1
    assert client.post(URL, headers=HUMAN, json={"website": "new-kitchen.fi"}).json()["found"] is True
    assert len(upstream["calls"]) == 2


def test_email_and_website_of_one_domain_are_cached_apart(env, clock):
    client, upstream, _ = env
    assert client.post(URL, headers=HUMAN, json={"website": "gmail.com"}).status_code == 200
    upstream["answer"] = (422, {"error_code": "FREE_EMAIL_DETECTED"})
    r = client.post(URL, headers=HUMAN, json={"email": "chef@gmail.com"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "FREE_EMAIL"    # not the cached brand
    upstream["answer"] = (200, recorded())
    client.post(URL, headers=HUMAN, json={"email": "chef@scandichotels.com"})
    client.post(URL, headers=HUMAN, json={"email": "owner@scandichotels.com"})  # same domain: the cache
    assert [call[0]["type"] for call in upstream["calls"]] == ["by_domain", "by_email", "by_email"]


def test_past_the_limit_is_429_without_a_call_and_recovers_after_the_window(env, clock):
    client, upstream, _ = env
    for n in range(10):
        clock["t"] += 1
        assert client.post(URL, headers=HUMAN, json={"website": f"kitchen-{n}.fi"}).status_code == 200
    r = client.post(URL, headers=HUMAN, json={"website": "kitchen-10.fi"})
    assert r.status_code == 429, r.text
    assert r.json()["error"]["code"] == "LOOKUP_RATE_LIMITED" and r.json()["error"]["retry_after_s"] == 51
    assert r.headers["retry-after"] == "51"         # the first call leaves the window in 51 s
    assert "found" not in r.json() and KEY not in r.text       # a limit is never an empty profile
    assert len(upstream["calls"]) == 10
    # What is cached costs nothing, so it still answers; a bad query is still a 422.
    assert client.post(URL, headers=HUMAN, json={"website": "kitchen-3.fi"}).status_code == 200
    assert client.post(URL, headers=HUMAN, json={"website": "kuusi"}).status_code == 422
    clock["t"] += 50
    assert client.post(URL, headers=HUMAN, json={"website": "kitchen-10.fi"}).status_code == 429
    clock["t"] += 1
    assert client.post(URL, headers=HUMAN, json={"website": "kitchen-10.fi"}).status_code == 200
    assert len(upstream["calls"]) == 11


def test_failed_calls_count_against_the_limit(env, clock, monkeypatch):
    client, upstream, _ = env
    monkeypatch.setenv("ONBOARDING_RATE_LIMIT", "2")
    monkeypatch.setenv("ONBOARDING_RATE_WINDOW_S", "30")
    upstream["answer"] = (500, {})
    for _ in range(2):
        assert client.post(URL, headers=HUMAN, json={"website": "hotelkuusi.fi"}).status_code == 502
    r = client.post(URL, headers=HUMAN, json={"website": "hotelkuusi.fi"})
    assert r.status_code == 429 and r.headers["retry-after"] == "30"
    assert len(upstream["calls"]) == 2


def test_limit_is_per_caller_and_x_user_is_not_an_identity(env, clock, monkeypatch):
    client, upstream, db = env
    monkeypatch.setenv("ONBOARDING_RATE_LIMIT", "1")
    assert client.post(URL, headers=HUMAN, json={"website": "a-kitchen.fi"}).status_code == 200
    other_name = {**HUMAN, "X-User": "someone-else"}       # same address, a new name: same bucket
    assert client.post(URL, headers=other_name, json={"website": "b-kitchen.fi"}).status_code == 429
    from gateway import users
    for email in ("one@example.com", "two@example.com"):
        users.create_user(db, email, "correct horse battery staple", name=email, role="chef", kitchen_id="K01")
        client.cookies.clear()
        client.post("/v1/auth/login", json={"email": email, "password": "correct horse battery staple"})
        assert client.post(URL, json={"website": f"{email[:3]}-kitchen.fi"}).status_code == 200    # own bucket
        assert client.post(URL, json={"website": f"{email[:3]}-other.fi"}).status_code == 429
    assert len(upstream["calls"]) == 3


def test_behind_the_proxy_each_forwarded_client_has_its_own_bucket(env, clock, monkeypatch):
    _, upstream, db = env
    monkeypatch.setenv("ONBOARDING_RATE_LIMIT", "1")
    proxied = TestClient(create_app(Gateway(db, None)), client=("127.0.0.1", 5000))
    for n, visitor in enumerate(("198.51.100.7", "198.51.100.8")):
        # A client-sent entry on the left is ignored: Caddy appends the real one on the right.
        headers = {**HUMAN, "X-Forwarded-For": f"10.0.0.{n}, {visitor}"}
        assert proxied.post(URL, headers=headers, json={"website": f"v{n}-kitchen.fi"}).status_code == 200
        assert proxied.post(URL, headers=headers, json={"website": f"v{n}-other.fi"}).status_code == 429
    assert len(upstream["calls"]) == 2


def test_a_direct_public_client_is_keyed_by_its_own_address(env, clock, monkeypatch):
    _, upstream, db = env
    monkeypatch.setenv("ONBOARDING_RATE_LIMIT", "1")
    direct = TestClient(create_app(Gateway(db, None)), client=("203.0.113.5", 5000))
    assert direct.post(URL, headers={**HUMAN, "X-Forwarded-For": "198.51.100.1"},
                       json={"website": "a-kitchen.fi"}).status_code == 200
    # A spoofed header from a public peer does not open a new bucket.
    assert direct.post(URL, headers={**HUMAN, "X-Forwarded-For": "198.51.100.2"},
                       json={"website": "b-kitchen.fi"}).status_code == 429
    assert len(upstream["calls"]) == 1


def test_cache_and_limit_live_in_the_process_not_in_the_database(env, clock):
    client, upstream, db = env
    for _ in range(12):
        client.post(URL, headers=HUMAN, json={"website": "scandichotels.com"})
    assert len(upstream["calls"]) == 1
    assert not any(db[name].count_documents({}) for name in db.list_collection_names())
    # Another gateway app (a restart) starts empty.
    fresh = TestClient(create_app(Gateway(db, None)))
    assert fresh.post(URL, headers=HUMAN, json={"website": "scandichotels.com"}).status_code == 200
    assert len(upstream["calls"]) == 2
