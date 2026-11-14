"""An order for the menu plan (#74): POST /proposals with a window becomes one proposal for
every product the plan needs, each sized by the engine."""

from gateway.tests.test_gateway_app import AGENT, HUMAN, K, env  # noqa: F401 (fixture)

RECIPES = [
    {"recipe_id": "latte", "name": "Latte", "ingredients": [
        {"product_id": "462775", "qty_per_portion": "0.2", "unit": "L"}]},
    {"recipe_id": "cocoa", "name": "Cocoa", "ingredients": [
        {"product_id": "463335", "qty_per_portion": "0.1", "unit": "L"},
        {"product_id": "462775", "qty_per_portion": "0.1", "unit": "L"}]},
]
PLAN = {"days": [{"date": "2026-11-16", "meal": "breakfast", "recipe_id": "latte", "covers": 100},
                 {"date": "2026-11-17", "meal": "breakfast", "recipe_id": "cocoa", "covers": 50}]}
WINDOW = {"from": "2026-11-16", "to": "2026-11-22", "requested_date": "2026-11-16"}


def setup(client, counts=None):
    for recipe in RECIPES:
        assert client.post(K + "/recipes", headers=HUMAN, json=recipe).status_code == 200
    assert client.put(K + "/menu-plans/2026-W47", headers=HUMAN, json=PLAN).status_code == 200
    if counts is not None:
        body = {"idempotency_key": "c1", "counted_at": "2026-11-13T22:00:00+02:00", "source": "manual", "counts": counts}
        assert client.post(K + "/stock-counts", headers=HUMAN, json=body).status_code == 200


def test_plan_window_becomes_one_proposal_with_a_line_per_product(env):
    client, _, _ = env
    setup(client, [{"product_id": "462775", "on_hand": "5", "unit": "L"},
                   {"product_id": "463335", "on_hand": "0", "unit": "L"}])
    r = client.post(K + "/proposals", headers=AGENT, json={**WINDOW, "idempotency_key": "plan-1"})
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["status"] == "READY" and p["request"]["made_by"] == "menu_plan"
    lines = {ln["product_id"]: ln for ln in p["lines"]}
    assert str(lines["462775"]["quantity"]) in ("20", "20.0")       # 20 + 5 needed, 5 in stock
    assert str(lines["463335"]["quantity"]) in ("5", "5.0") and lines["463335"]["unknown_stock"] is True
    assert {n["product_id"]: n["quantity"] for n in p["request"]["needs"]} == {"462775": "20", "463335": "5"}
    again = client.post(K + "/proposals", headers=AGENT, json={**WINDOW, "idempotency_key": "plan-1"})
    assert again.json()["proposal_id"] == p["proposal_id"]
    other = client.post(K + "/proposals", headers=AGENT, json={**WINDOW, "to": "2026-11-18", "idempotency_key": "plan-1"})
    assert other.status_code == 409


def test_uncounted_stock_orders_the_full_need_and_says_so(env):
    client, _, _ = env
    setup(client)                                                   # nothing counted
    p = client.post(K + "/proposals", headers=AGENT, json={**WINDOW, "idempotency_key": "plan-2"}).json()
    needs = {n["product_id"]: n for n in p["request"]["needs"]}
    assert needs["462775"]["quantity"] == "25" and needs["462775"]["stock_counted"] is False


def test_shortfall_per_product_is_reported_and_blocks_nothing_silently(env):
    client, _, _ = env
    setup(client, [{"product_id": "462775", "on_hand": "0", "unit": "L"}])
    big = {"days": [{"date": "2026-11-16", "meal": "breakfast", "recipe_id": "latte", "covers": 400}]}
    client.put(K + "/menu-plans/2026-W47", headers=HUMAN, json=big)   # 80 L needed, 51 confirmed
    p = client.post(K + "/proposals", headers=AGENT, json={**WINDOW, "idempotency_key": "plan-3"}).json()
    assert p["shortfalls"] == [{"product_id": "462775", "shortfall": "29", "unit": "L"}]
    assert "PARTIAL_STOCK" in p["mandate"]["reason_codes"]


def test_nothing_needed_and_bad_window(env):
    client, _, _ = env
    setup(client, [{"product_id": "462775", "on_hand": "500", "unit": "L"},
                   {"product_id": "463335", "on_hand": "500", "unit": "L"}])
    r = client.post(K + "/proposals", headers=AGENT, json={**WINDOW, "idempotency_key": "plan-4"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "NOTHING_NEEDED"
    r = client.post(K + "/proposals", headers=AGENT, json={"from": "2026-11-16", "to": "2027-11-16", "idempotency_key": "x"})
    assert r.status_code == 422


def test_approving_a_plan_proposal_places_it_once(env):
    client, _, db = env
    setup(client, [{"product_id": "462775", "on_hand": "5", "unit": "L"}])
    only_latte = {"days": [PLAN["days"][0]]}
    client.put(K + "/menu-plans/2026-W47", headers=HUMAN, json=only_latte)
    p = client.post(K + "/proposals", headers=AGENT, json={**WINDOW, "idempotency_key": "plan-5"}).json()
    done = client.post(f"{K}/proposals/{p['proposal_id']}/approve", headers=HUMAN,
                       json={"expected_total": p["expected_total"], "idempotency_key": "a1"})
    assert done.status_code == 200, done.text
    assert db.orders.count_documents({}) == 1
