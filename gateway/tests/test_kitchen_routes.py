"""Kitchen planning routes (#74): the Planner, Products, Suppliers and Stock pages for real."""

from datetime import date
from decimal import Decimal as D

from engine.menu_demand import gross_needs, net_needs, weeks_between
from gateway import users
from gateway.tests.test_gateway_app import AGENT, HUMAN, K, env  # noqa: F401 (fixture)

SOUP = {"recipe_id": "soup", "name": "Carrot soup", "ingredients": [
    {"product_id": "460708", "qty_per_portion": "0.1", "unit": "KG", "yield_pct": "85"},
    {"product_id": "469549", "qty_per_portion": "0.05", "unit": "L"}]}
PORRIDGE = {"recipe_id": "porridge", "name": "Oat porridge", "ingredients": [
    {"product_id": "469549", "qty_per_portion": "0.2", "unit": "L"}]}
COUNT = {"idempotency_key": "c1", "counted_at": "2026-11-13T22:00:00+02:00", "source": "manual",
         "counts": [{"product_id": "469549", "on_hand": "8", "unit": "L"},
                    {"product_id": "460708", "on_hand": None, "unit": "KG"}]}


def test_engine_yield_and_running_stock():
    rows, problems = gross_needs(
        [{"date": "2026-11-16", "recipe_id": "soup", "covers": 100},
         {"date": "2026-11-16", "recipe_id": "porridge", "covers": 50},
         {"date": "2026-11-17", "recipe_id": "soup", "covers": 100},
         {"date": "2026-11-17", "recipe_id": "nope", "covers": 10},
         {"date": "2026-11-17", "recipe_id": "soup", "covers": None}],
        {"soup": SOUP, "porridge": PORRIDGE})
    by = {(r["product_id"], r["date"]): r for r in rows}
    assert by[("460708", "2026-11-16")]["gross_need"] == D("11.765")       # 100 x 0.1 / 0.85
    assert by[("469549", "2026-11-16")]["gross_need"] == D("15.000")       # 5 + 10
    assert "85% yield" in by[("460708", "2026-11-16")]["why"]
    assert len(problems) == 2
    net = {(r["product_id"], r["date"]): r["net_need"] for r in net_needs(rows, {"469549": D(18)})}
    assert net[("469549", "2026-11-16")] == 0 and net[("469549", "2026-11-17")] == D("2.000")
    assert net[("460708", "2026-11-16")] is None                            # stock unknown, not zero
    assert weeks_between(date(2026, 11, 15), date(2026, 11, 23)) == ["2026-W46", "2026-W47", "2026-W48"]


def test_recipes_menu_plan_stock_and_demand_end_to_end(env):
    client, _, db = env
    for recipe in (SOUP, PORRIDGE):
        assert client.post(K + "/recipes", headers=HUMAN, json=recipe).status_code == 200
    plan = {"days": [{"date": "2026-11-16", "meal": "lunch", "recipe_id": "soup", "covers": 100},
                     {"date": "2026-11-17", "meal": "breakfast", "recipe_id": "porridge", "covers": 50}]}
    assert client.put(K + "/menu-plans/2026-W47", headers=HUMAN, json=plan).status_code == 200
    assert len(client.get(K + "/menu-plans/2026-W47", headers=AGENT).json()["days"]) == 2
    assert client.get(K + "/menu-plans/2026-W48", headers=AGENT).json()["days"] == []
    assert client.post(K + "/stock-counts", headers=HUMAN, json=COUNT).json()["stored"] == 2
    assert client.post(K + "/stock-counts", headers=HUMAN, json=COUNT).json()["stored"] == 2   # replay
    assert db.kitchen_stock.count_documents({}) == 2
    items = {i["product_id"]: i for i in client.get(K + "/stock", headers=AGENT).json()["items"]}
    assert items["469549"]["on_hand"] == "8" and items["460708"]["on_hand"] is None
    assert items["469549"]["on_order_known"] is False
    demand = client.get(K + "/demand?from=2026-11-16&to=2026-11-22", headers=AGENT).json()
    rows = {(r["product_id"], r["date"]): r for r in demand["rows"]}
    assert rows[("469549", "2026-11-16")]["gross_need"] == "5" and rows[("469549", "2026-11-16")]["net_need"] == "0"
    assert rows[("469549", "2026-11-17")]["net_need"] == "7"               # 10 needed, 3 left
    assert rows[("460708", "2026-11-16")]["net_need"] is None
    assert rows[("460708", "2026-11-16")]["source"] == "menu_plan"
    kinds = [e["kind"] for e in client.get(K + "/audit", headers=AGENT).json()["events"]]
    assert "menu_plan_changed" in kinds and "stock_counted" in kinds


def test_engine_unit_mismatch_is_unknown_with_a_problem():
    rows = [{"product_id": "460708", "date": "2026-11-16", "unit": "G", "gross_need": D(800)},
            {"product_id": "460708", "date": "2026-11-17", "unit": "G", "gross_need": D(800)}]
    problems: list[str] = []
    out = net_needs(rows, {"460708": ("KG", D(5))}, problems)
    assert [r["net_need"] for r in out] == [None, None]                # never a 1000x guess
    assert problems == ["460708: stock counted in KG, recipe uses G"]  # once per product


def test_demand_unit_mismatch_is_unknown_with_a_problem(env):
    client, _, _ = env
    salad = {"recipe_id": "salad", "name": "Carrot salad", "ingredients": [
        {"product_id": "460708", "qty_per_portion": "0.08", "unit": "L"}]}
    assert client.post(K + "/recipes", headers=HUMAN, json=salad).status_code == 200
    plan = {"days": [{"date": "2026-11-16", "meal": "lunch", "recipe_id": "salad", "covers": 10}]}
    assert client.put(K + "/menu-plans/2026-W47", headers=HUMAN, json=plan).status_code == 200
    count = {**COUNT, "idempotency_key": "c2",
             "counts": [{"product_id": "460708", "on_hand": "5", "unit": "KG"}]}
    assert client.post(K + "/stock-counts", headers=HUMAN, json=count).status_code == 200
    demand = client.get(K + "/demand?from=2026-11-16&to=2026-11-16", headers=AGENT).json()
    row = next(r for r in demand["rows"] if r["product_id"] == "460708")
    assert row["unit"] == "L" and row["net_need"] is None
    assert "460708: stock counted in KG, recipe uses L" in demand["problems"]


def test_suppliers_crud_and_validation(env):
    client, _, _ = env
    body = {"supplier_id": "sup-bakery", "name": "Bakery", "adapter": "manual",
            "terms": {"free_delivery_threshold_eur": "80.00", "delivery_fee_eur": None, "order_days": ["TUE", "FRI"]}}
    made = client.post(K + "/suppliers", headers=HUMAN, json=body)
    assert made.status_code == 200, made.text
    got = client.get(K + "/suppliers/sup-bakery", headers=AGENT).json()
    assert got["terms"]["delivery_fee_eur"] is None                         # unknown, never zero
    assert client.post(K + "/suppliers", headers=HUMAN, json={"name": "x", "adapter": "fax"}).status_code == 422
    assert client.delete(K + "/suppliers/sup-bakery", headers=HUMAN).json() == {"deleted": True}
    assert client.get(K + "/suppliers/sup-bakery", headers=AGENT).status_code == 404


def test_who_may_write(env):
    client, _, db = env
    assert client.post(K + "/recipes", headers=AGENT, json=SOUP).status_code == 403       # the Buyer never edits recipes
    token = client.post(K + "/tokens", headers=HUMAN, json={"name": "pos", "scopes": ["kitchen:write"]}).json()["token"]
    pos = {"Authorization": "Bearer " + token}
    assert client.post(K + "/stock-counts", headers=pos, json={**COUNT, "source": "pos"}).status_code == 200
    assert client.put(K + "/settings", headers=pos, json={"stockout_cap": "1.5"}).status_code == 403
    users.create_user(db, "view@example.com", "viewer pass 12", name="V", role="viewer", kitchen_id="demo-kitchen")
    client.post("/v1/auth/login", json={"email": "view@example.com", "password": "viewer pass 12"})
    assert client.get(K + "/recipes").status_code == 200
    assert client.post(K + "/recipes", json=SOUP).status_code == 403


def test_settings_and_sharing_are_an_approvers_and_audited(env):
    client, _, _ = env
    r = client.put(K + "/settings", headers=HUMAN, json={"stockout_cap": "1.5"})
    assert r.status_code == 200 and r.json()["stockout_cap"] == 1.5
    assert client.put(K + "/settings", headers=HUMAN, json={"stockout_cap": "9"}).status_code == 422
    share = {"supplier_id": "sup-valio", "share_forecast": True}
    assert client.put(K + "/sharing", headers=AGENT, json=share).status_code == 403
    shared = client.put(K + "/sharing", headers=HUMAN, json=share)
    assert shared.status_code == 200, shared.text
    assert shared.json()["sharing"][0]["share_forecast"] is True
    events = client.get(K + "/audit", headers=AGENT).json()["events"]
    assert "settings_changed" in [e.get("kind") for e in events]
    assert "share_granted" in [e.get("type") for e in events]
