"""The wholesaler's demand view (#33): only consenting kitchens, availability never invented."""

from datetime import datetime, timezone

from bson.decimal128 import Decimal128

from gateway.tests.test_gateway_app import AGENT, HUMAN, env  # noqa: F401 (fixture)
from store.history import set_sharing

URL = "/v1/suppliers/sup-valio/demand?from=2026-11-16&to=2026-11-16"


def seed(db):
    db.sharing.create_index([("kitchen_id", 1), ("supplier_id", 1)], unique=True)
    for kid, name in (("K1", "Hotel One"), ("K2", "School Two"), ("K3", "Private Three")):
        db.kitchens.insert_one({"_id": kid, "name": name})
    set_sharing(db, "K1", "sup-valio", True, "seed")
    set_sharing(db, "K2", "sup-valio", True, "seed")           # K3 never agreed
    for pid, content in (("462775", 1.0), ("462921", 1.0), ("463335", 1.0)):
        db.products.update_one({"_id": pid}, {"$set": {
            "sales_unit": "ST" if pid != "462921" else "KI", "net_content": {"value": content, "unit": "L"},
            "units": [{"unit": "ST", "size_in_base_units": 1.0}, {"unit": "KI", "size_in_base_units": 5.0}]}})
    day = datetime(2026, 11, 16, tzinfo=timezone.utc)
    for kid, pid, need in (("K1", "462775", "40"), ("K2", "462775", "30"), ("K3", "462775", "500"),
                           ("K1", "463335", "25"), ("K2", "462921", "10")):
        db.forecasts.insert_one({"ts": day, "meta": {"kitchen_id": kid, "product_id": pid},
                                 "need": Decimal128(need), "unit": "L"})


def test_demand_sums_only_consenting_kitchens_and_flags_shortage(env):
    client, _, db = env
    seed(db)
    data = client.get(URL, headers=HUMAN).json()
    rows = {r["product_id"]: r for r in data["rows"]}
    milk = rows["462775"]
    assert data["kitchens_sharing"] == 2
    assert milk["demand"] == "70" and milk["kitchens"] == 2                 # K3's 500 L is nowhere
    assert [k["kitchen_name"] for k in milk["by_kitchen"]] == ["Hotel One", "School Two"]
    assert "Private Three" not in str(data)
    assert milk["available"] == "51" and milk["shortage"] == "19" and milk["risk"] == "SHORT"
    assert milk["suggested_buy"] == "19"
    assert rows["463335"]["available"] is None and rows["463335"]["risk"] == "UNKNOWN"   # sentinel: unknown
    assert rows["463335"]["shortage"] is None and rows["463335"]["suggested_buy"] is None


def test_shortage_risk_lists_only_rows_that_are_not_ok_and_product_filter(env):
    client, _, db = env
    seed(db)
    db.forecasts.update_one({"meta.kitchen_id": "K2", "meta.product_id": "462775"}, {"$set": {"need": Decimal128("5")}})
    risk = client.get(URL.replace("/demand?", "/demand/shortage-risk?"), headers=HUMAN).json()
    assert "462775" not in [r["product_id"] for r in risk["rows"]]          # 45 needed, 51 there: OK
    assert all(r["risk"] != "OK" for r in risk["rows"]) and risk["rows"]
    one = client.get(URL + "&product=462775", headers=HUMAN).json()
    assert [r["product_id"] for r in one["rows"]] == ["462775"] and one["rows"][0]["risk"] == "OK"


def test_revoked_consent_disappears_and_the_buyer_token_cannot_read_it(env):
    client, _, db = env
    seed(db)
    set_sharing(db, "K2", "sup-valio", False, "seed")
    milk = [r for r in client.get(URL, headers=HUMAN).json()["rows"] if r["product_id"] == "462775"][0]
    assert milk["demand"] == "40" and milk["kitchens"] == 1
    assert client.get(URL, headers=AGENT).status_code == 403
    assert client.get("/v1/suppliers/sup-valio/demand?from=2026-11-16&to=2027-01-16", headers=HUMAN).status_code == 422


def test_a_kitchen_bound_person_cannot_read_a_suppliers_view(env):
    """#599: consent names the supplier, not other kitchens. A person signed in to one
    kitchen never sees the supplier's cross-kitchen view; the demo's server session does."""
    from gateway import users
    client, _, db = env
    seed(db)
    users.create_user(db, "chef@k1.example", "chef pass 1234", name="C", role="approver", kitchen_id="K1")
    client.post("/v1/auth/login", json={"email": "chef@k1.example", "password": "chef pass 1234"})
    for url in (URL, "/v1/suppliers/sup-valio/demand/shortage-risk?from=2026-11-16&to=2026-11-16",
                "/v1/suppliers/sup-valio/demand/drift"):
        r = client.get(url)
        assert r.status_code == 403 and r.json()["error"]["code"] == "SCOPE_REQUIRED", url
    client.cookies.clear()
    assert client.get(URL, headers=HUMAN).status_code == 200
