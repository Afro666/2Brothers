"""Drift routes (#377): shape, week, names, consent, scopes, error mapping.

`store.drift`'s aggregation needs Atlas / MongoDB 7 (`$dateTrunc`, `$setWindowFields`), so
these tests replace `standing_order_drift` and check what the gateway adds around it.
"""

from datetime import datetime, timezone

import pytest

mongomock = pytest.importorskip("mongomock")
pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402
from pymongo.errors import OperationFailure  # noqa: E402

from gateway import drift_routes, tokens  # noqa: E402
from gateway.app import create_app  # noqa: E402
from gateway.service import Gateway  # noqa: E402
from store.history import set_sharing  # noqa: E402

NOW = datetime(2026, 11, 18, 9, 0, tzinfo=timezone.utc)      # a Wednesday
WEEK = datetime(2026, 11, 9, tzinfo=timezone.utc)            # Monday of the last full week
HUMAN = {"Authorization": "Bearer human-test-token", "X-User": "aron"}
AGENT = {"Authorization": "Bearer agent-test-token"}
SUPPLIER = "/v1/suppliers/sup-valio/demand/drift"


def warning(product_id: str, change: float, kind: str = "portion_creep") -> dict:
    """One row as `store.drift.flag` returns it (with its `week` datetime)."""
    return {"product_id": product_id, "week": WEEK, "kind": kind, "change": change, "unit": "ST",
            "qty_per_100": 14.0, "baseline_qty": 10.0, "spend_per_100": 35.98,
            "baseline_spend": 25.7, "baseline_weeks": 4, "why": "14.0 ST per 100 guests last week."}


@pytest.fixture()
def env(monkeypatch):
    monkeypatch.setenv("GATEWAY_HUMAN_TOKEN", "human-test-token")
    monkeypatch.setenv("GATEWAY_AGENT_TOKEN", "agent-test-token")
    monkeypatch.delenv("GATEWAY_REQUIRE_LOGIN", raising=False)
    db = mongomock.MongoClient(tz_aware=True)["test"]
    db.products.insert_one({"_id": "462775", "names": {"en": "Lactose-free milk 1 l"}})
    db.kitchens.insert_many([{"_id": "K01", "name": "Hotel Kuusi"}, {"_id": "K02", "name": "School Koivu"},
                             {"_id": "K03", "name": "Bistro Leppa"}])
    by_kitchen: dict[str, list[dict]] = {}
    calls: list[tuple] = []

    def fake(db_, kitchen_id, now=None, **_):
        calls.append((kitchen_id, now))
        return [dict(row) for row in by_kitchen.get(kitchen_id, [])]

    monkeypatch.setattr(drift_routes, "standing_order_drift", fake)
    client = TestClient(create_app(Gateway(db, None, now=lambda: NOW)))
    return client, db, by_kitchen, calls


def test_kitchen_drift_names_the_week_and_the_product(env):
    client, _, by_kitchen, calls = env
    by_kitchen["K01"] = [warning("462775", 0.4), warning("999999", 0.2, "cost_creep")]
    r = client.get("/v1/kitchens/K01/drift", headers=AGENT)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["week"] == "2026-11-09"
    first, second = body["warnings"]
    assert first == {"product_id": "462775", "product_name": "Lactose-free milk 1 l",
                     "kind": "portion_creep", "change": 0.4, "unit": "ST", "qty_per_100": 14.0,
                     "baseline_qty": 10.0, "spend_per_100": 35.98, "baseline_spend": 25.7,
                     "baseline_weeks": 4, "why": "14.0 ST per 100 guests last week."}
    # A product the catalog does not know gets no name, and no per-warning `week`.
    assert second["product_id"] == "999999" and second["kind"] == "cost_creep"
    assert "product_name" not in second and "week" not in second
    assert calls == [("K01", NOW)]      # the store counts the same week the answer names


def test_kitchen_without_drift_still_names_the_week(env):
    client, *_ = env
    r = client.get("/v1/kitchens/K01/drift", headers=HUMAN)
    assert r.status_code == 200
    assert r.json() == {"week": "2026-11-09", "warnings": []}


@pytest.mark.parametrize("now, monday", [
    (datetime(2026, 11, 16, 0, 0, tzinfo=timezone.utc), "2026-11-09"),     # Monday 00:00
    (datetime(2026, 11, 15, 23, 59, tzinfo=timezone.utc), "2026-11-02"),   # Sunday night
    (datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc), "2025-12-22"),      # across a year end
])
def test_week_is_the_monday_of_the_last_full_week(now, monday):
    assert drift_routes.last_full_week(now).date().isoformat() == monday


def test_week_matches_the_store_window():
    from datetime import timedelta
    from store.drift import _monday
    for day in range(1, 29):
        now = datetime(2026, 11, day, 13, 30, tzinfo=timezone.utc)
        assert drift_routes.last_full_week(now) == _monday(now) - timedelta(weeks=1)


def test_kitchen_drift_auth(env):
    client, db, *_ = env
    assert client.get("/v1/kitchens/K01/drift").status_code == 401
    made = tokens.create(db, "K01", "reader", ["kitchen:read"], "aron")
    own = {"Authorization": "Bearer " + made["token"]}
    assert client.get("/v1/kitchens/K01/drift", headers=own).status_code == 200
    other = client.get("/v1/kitchens/K02/drift", headers=own)
    assert other.status_code == 403 and other.json()["error"]["code"] == "KITCHEN_SCOPE"
    made = tokens.create(db, "K01", "proposer", ["kitchen:propose"], "aron")
    r = client.get("/v1/kitchens/K01/drift", headers={"Authorization": "Bearer " + made["token"]})
    assert r.status_code == 403 and r.json()["error"]["code"] == "SCOPE_REQUIRED"


def test_supplier_drift_lists_consenting_kitchens_only(env):
    client, db, by_kitchen, calls = env
    set_sharing(db, "K01", "sup-valio", True, "aron")
    set_sharing(db, "K02", "sup-valio", True, "aron")
    set_sharing(db, "K03", "sup-other", True, "aron")          # consent for another supplier
    by_kitchen["K01"] = [warning("462775", 0.2)]
    by_kitchen["K02"] = [warning("462775", 0.5), warning("999999", 0.16, "cost_creep")]
    by_kitchen["K03"] = [warning("462775", 0.9)]
    r = client.get(SUPPLIER, headers=HUMAN)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["week"] == "2026-11-09"
    rows = [(w["kitchen_id"], w["kitchen_name"], w["product_id"], w["change"]) for w in body["warnings"]]
    assert rows == [("K02", "School Koivu", "462775", 0.5), ("K01", "Hotel Kuusi", "462775", 0.2),
                    ("K02", "School Koivu", "999999", 0.16)]            # biggest change first
    assert body["warnings"][0]["product_name"] == "Lactose-free milk 1 l"
    assert all("week" not in w for w in body["warnings"])
    assert "K03" not in r.text and "Bistro" not in r.text
    assert sorted(kitchen for kitchen, _ in calls) == ["K01", "K02"]   # K03 is never even read


def test_supplier_drift_drops_a_kitchen_that_revoked(env):
    client, db, by_kitchen, _ = env
    set_sharing(db, "K01", "sup-valio", True, "aron")
    set_sharing(db, "K01", "sup-valio", False, "aron")
    by_kitchen["K01"] = [warning("462775", 0.4)]
    assert client.get(SUPPLIER, headers=HUMAN).json() == {"week": "2026-11-09", "warnings": []}


def test_supplier_drift_without_any_consent_is_empty(env):
    client, _, _, calls = env
    r = client.get("/v1/suppliers/nobody/demand/drift", headers=HUMAN)
    assert r.status_code == 200 and r.json() == {"week": "2026-11-09", "warnings": []}
    assert calls == []


def test_supplier_drift_needs_the_supplier_scope(env):
    client, db, *_ = env
    assert client.get(SUPPLIER).status_code == 401
    # The Buyer agent and kitchen API tokens hold kitchen scopes only.
    made = tokens.create(db, "K01", "reader", ["kitchen:read", "kitchen:propose"], "aron")
    for headers in (AGENT, {"Authorization": "Bearer " + made["token"]}):
        r = client.get(SUPPLIER, headers=headers)
        assert r.status_code == 403 and r.json()["error"]["code"] == "SCOPE_REQUIRED"


@pytest.mark.parametrize("path", ["/v1/kitchens/K01/drift", SUPPLIER])
def test_database_failure_is_a_clean_503(env, monkeypatch, path):
    client, db, *_ = env
    set_sharing(db, "K01", "sup-valio", True, "aron")

    def broken(*_, **__):
        raise OperationFailure("Unrecognized pipeline stage at cluster0.example.mongodb.net")

    monkeypatch.setattr(drift_routes, "standing_order_drift", broken)
    r = client.get(path, headers=HUMAN)
    assert r.status_code == 503
    assert r.json() == {"error": {"code": "DRIFT_UNAVAILABLE",
                                  "message": "drift cannot be computed right now"}}
    assert "mongodb.net" not in r.text
