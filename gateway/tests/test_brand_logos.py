"""Brand logos (docs/contract.md, "Product pictures"): the read-only route and the capped
operator command that asks Context.dev once per brand."""
from datetime import datetime, timezone

import pytest

mongomock = pytest.importorskip("mongomock")
pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from gateway import brand_logos  # noqa: E402
from gateway.app import create_app  # noqa: E402
from gateway.service import Gateway  # noqa: E402
from store import brand_logos as stored  # noqa: E402

NOW = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)
AGENT = {"Authorization": "Bearer agent-test-token"}
ICON = "https://media.brand.dev/icon-own.png"
SOURCE = {"provider": "Context.dev", "endpoint": "POST /v1/brand/retrieve"}


def credits(n):
    return {"key_metadata": {"credits_consumed": 10, "credits_remaining": n}}


def brand(title, domain, logos=None, remaining=600):
    return 200, {"brand": {"title": title, "domain": domain, "logos": logos if logos is not None else [
        {"type": "icon", "mode": "has_opaque_background", "url": ICON}]}, **credits(remaining)}


NOT_FOUND = (400, {"error_code": "NOT_FOUND", "key_metadata": {"credits_consumed": 0, "credits_remaining": 600}})


@pytest.fixture()
def db():
    return mongomock.MongoClient(tz_aware=True)["test"]


@pytest.fixture()
def client(db, monkeypatch):
    monkeypatch.setenv("GATEWAY_HUMAN_TOKEN", "human-test-token")
    monkeypatch.setenv("GATEWAY_AGENT_TOKEN", "agent-test-token")
    monkeypatch.delenv("GATEWAY_REQUIRE_LOGIN", raising=False)
    return TestClient(create_app(Gateway(db, None, now=lambda: NOW)))


@pytest.fixture()
def calls(monkeypatch):
    """Context.dev replaced by a queue of answers; every request body is recorded."""
    sent, answers = [], []

    def fake_post(payload, key):
        sent.append(payload)
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer
    monkeypatch.setattr(brand_logos, "_post", fake_post)
    return sent, answers


# ---- the route ------------------------------------------------------------------------

def test_the_route_answers_every_status_in_the_order_asked(client, db):
    stored.put(db, "Valio", status="found", checked_at=NOW, logo_url=ICON, background="own", domain="valio.fi")
    stored.put(db, "HK", status="none", checked_at=NOW)
    r = client.get("/v1/brands/logos", params=[("name", "Arla"), ("name", " Valio "), ("name", "HK"),
                                               ("name", "Valio")], headers=AGENT)
    assert r.status_code == 200, r.text
    assert r.json() == {"logos": [
        {"brand": "Arla", "status": "not_checked", "logo_url": None, "background": None, "domain": None,
         "checked_at": None, "source": None},
        {"brand": "Valio", "status": "found", "logo_url": ICON, "background": "own", "domain": "valio.fi",
         "checked_at": "2026-11-14T12:00:00+00:00", "source": SOURCE},
        {"brand": "HK", "status": "none", "logo_url": None, "background": None, "domain": None,
         "checked_at": "2026-11-14T12:00:00+00:00", "source": None},
    ]}


def test_the_route_never_calls_context_dev(client, monkeypatch):
    monkeypatch.setenv("CONTEXT_DEV_API_KEY", "test-key")
    monkeypatch.setattr(brand_logos, "_post", lambda *a: pytest.fail("the route called Context.dev"))
    assert client.get("/v1/brands/logos?name=Valio", headers=AGENT).json()["logos"][0]["status"] == "not_checked"


@pytest.mark.parametrize("query", ["", "?name=", "?name=%20%20", "?name=" + "x" * 101,
                                   "?" + "&".join(f"name=b{i}" for i in range(51))])
def test_a_bad_query_is_422(client, query):
    r = client.get("/v1/brands/logos" + query, headers=AGENT)
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "INVALID_REQUEST"


def test_fifty_names_are_allowed(client):
    query = "&".join(f"name=b{i}" for i in range(50))
    assert len(client.get("/v1/brands/logos?" + query, headers=AGENT).json()["logos"]) == 50


def test_the_route_needs_a_token(client):
    assert client.get("/v1/brands/logos?name=Valio").status_code == 401


def test_a_database_error_is_503(client, monkeypatch):
    from pymongo.errors import ServerSelectionTimeoutError

    def broken(db, names):
        raise ServerSelectionTimeoutError("down")
    monkeypatch.setattr(stored, "get_many", broken)
    r = client.get("/v1/brands/logos?name=Valio", headers=AGENT)
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "LOGOS_UNAVAILABLE"


# ---- matching and picking -------------------------------------------------------------

@pytest.mark.parametrize("name,title,domain,ok", [
    ("Valio", "Valio", "valio.fi", True),
    ("Santa Maria", "SantaMaria", "santamariaworld.com", True),
    ("Fazer", "Fazer Group", "fazer.com", True),           # the domain's first label
    ("Valio", "Valio Ltd", "www.valio.fi", True),
    ("Myllyn Paras", "Myllyn Paras Oy", "myllynparas.fi", True),
    ("Fresh", "Fresh Del Monte", "freshdelmontefoods.com", False),
    ("Nic", "Nicolas", "nicolas.com", False),
    ("Valio", None, None, False),
])
def test_a_logo_is_kept_only_when_the_answer_is_the_brand(name, title, domain, ok):
    assert brand_logos.matches(name, title, domain) is ok


def test_the_logo_picked_follows_the_contract_order():
    def logo(kind, mode, url):
        return {"type": kind, "mode": mode, "url": url}
    logos = [logo("logo", "dark", "https://x/logo-dark.svg"), logo("icon", "dark", "https://x/icon-dark.png"),
             logo("logo", "light", "https://x/logo-light.svg"), logo("icon", "light", "https://x/icon-light.png"),
             logo("icon", "has_opaque_background", "http://x/plain-http.png")]
    assert brand_logos.pick_logo(logos) == ("https://x/icon-light.png", "light")
    assert brand_logos.pick_logo(logos[:3]) == ("https://x/logo-light.svg", "light")
    assert brand_logos.pick_logo(logos[:2]) == ("https://x/icon-dark.png", "dark")
    assert brand_logos.pick_logo([logo("icon", "has_opaque_background", ICON)] + logos) == (ICON, "own")
    assert brand_logos.pick_logo([logo("logo", "has_opaque_background", ICON)]) == (ICON, "own")
    assert brand_logos.pick_logo([]) == (None, None)
    assert brand_logos.pick_logo("junk") == (None, None)


# ---- the operator command -------------------------------------------------------------

def test_warm_asks_once_per_brand_and_stores_the_answer(db, calls):
    sent, answers = calls
    answers += [brand("Valio", "valio.fi"), NOT_FOUND, brand("Fresh Del Monte", "freshdelmonte.com")]
    report = brand_logos.warm(db, "test-key", limit=10, brands=["Valio", "Arla", "Fresh"], now=lambda: NOW)
    assert sent == [{"type": "by_name", "name": n, "country_gl": "fi"} for n in ("Valio", "Arla", "Fresh")]
    assert [(r["brand"], r["status"]) for r in report["brands"]] == [("Valio", "found"), ("Arla", "none"),
                                                                     ("Fresh", "none")]
    rows = stored.get_many(db, ["Valio", "Arla", "Fresh"])
    assert rows["Valio"]["logo_url"] == ICON and rows["Valio"]["domain"] == "valio.fi"
    assert rows["Fresh"]["status"] == "none" and rows["Fresh"]["logo_url"] is None
    # A second run asks nothing: every brand has a row.
    again = brand_logos.warm(db, "test-key", limit=10, brands=["Valio", "Arla", "Fresh"], now=lambda: NOW)
    assert len(sent) == 3 and again["brands"] == []


def test_warm_takes_the_biggest_unchecked_brands_up_to_the_limit(db, calls):
    sent, answers = calls
    db.products.insert_many([{"_id": str(i), "source": "valio", "brand": b}
                             for i, b in enumerate(["Valio"] * 3 + ["Arla"] * 2 + ["Fazer"])])
    answers += [NOT_FOUND, NOT_FOUND]
    brand_logos.warm(db, "test-key", limit=2, now=lambda: NOW)
    assert [p["name"] for p in sent] == ["Valio", "Arla"]


def test_a_name_context_dev_cannot_take_is_none_without_a_call(db, calls):
    sent, _ = calls
    report = brand_logos.warm(db, "test-key", limit=5, brands=["HK", "x" * 31], now=lambda: NOW)
    assert sent == []
    assert [r["status"] for r in report["brands"]] == ["none", "none"]
    assert stored.get_many(db, ["HK"])["HK"]["status"] == "none"


def test_a_failed_call_stores_nothing_and_three_in_a_row_stop(db, calls):
    sent, answers = calls
    answers += [OSError("timeout"), (503, {}), ValueError("not json"), brand("Valio", "valio.fi")]
    report = brand_logos.warm(db, "test-key", limit=10, brands=["A1a", "B2b", "C3c", "Valio"], now=lambda: NOW)
    assert len(sent) == 3
    assert report["stopped"] == "three failed calls in a row"
    assert db.brand_logos.count_documents({}) == 0


@pytest.mark.parametrize("status", [401, 402, 429])
def test_an_account_error_stops_at_once(db, calls, status):
    sent, answers = calls
    answers += [(status, {}), brand("Valio", "valio.fi")]
    report = brand_logos.warm(db, "test-key", limit=10, brands=["Arla", "Valio"], now=lambda: NOW)
    assert len(sent) == 1 and report["stopped"] == f"Context.dev answered {status}"
    assert db.brand_logos.count_documents({}) == 0


def test_warm_stops_when_few_credits_remain(db, calls):
    sent, answers = calls
    answers += [brand("Valio", "valio.fi", remaining=299), brand("Arla", "arla.fi")]
    report = brand_logos.warm(db, "test-key", limit=10, brands=["Valio", "Arla"], now=lambda: NOW)
    assert len(sent) == 1
    assert report["stopped"] == "fewer than 300 credits remain"
    assert stored.get_many(db, ["Valio"])["Valio"]["status"] == "found"     # the paid answer is kept


def test_warm_without_a_key_calls_nothing(db, calls):
    sent, _ = calls
    report = brand_logos.warm(db, "", limit=10, brands=["Valio"], now=lambda: NOW)
    assert sent == [] and report["stopped"] == "no CONTEXT_DEV_API_KEY"


@pytest.mark.parametrize("args", [["--limit", "31"], ["--limit", "0"], ["--limit", "x"]])
def test_the_command_caps_the_limit(args):
    with pytest.raises(SystemExit):
        brand_logos.parse_args(args)


def test_the_command_defaults_to_ten():
    assert brand_logos.parse_args([]).limit == 10
    assert brand_logos.parse_args(["--brand", "Valio", "--brand", "Arla"]).brand == ["Valio", "Arla"]
