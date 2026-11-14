"""GET /v1/kitchens/{id}/proposals/{pid}/addable (#129): what the buyer can add, ranked."""

from datetime import timedelta
from decimal import Decimal

from bson.decimal128 import Decimal128

from gateway.tests.test_gateway_app import AGENT, K, NOW, env, milk  # noqa: F401  (env is a fixture)


def stock(db, pid, unit, on_hand, used_per_day, days=7):
    """A stock count now plus `days` of usage history, stored as store.history stores them."""
    for d in range(1, days + 1):
        db.kitchen_stock.insert_one({"ts": NOW - timedelta(days=d), "unit": unit,
                                     "meta": {"kitchen_id": "demo-kitchen", "product_id": pid},
                                     "used": Decimal128(str(used_per_day)), "short": Decimal128("0")})
    db.kitchen_stock.insert_one({"ts": NOW, "unit": unit, "on_hand": Decimal128(str(on_hand)),
                                 "meta": {"kitchen_id": "demo-kitchen", "product_id": pid}})


def test_addable_rows_ranked_with_engine_quantity_price_and_why(env):  # noqa: F811
    client, _, db = env
    p = milk(client)
    db.products.insert_one({"_id": "777", "names": {"en": "napkins"}, "raw": {
        "id": "777", "salesUnit": "ST", "baseUnit": "ST", "allowedLotSize": 1,
        "units": [{"unitId": "ST", "sizeInBaseUnits": 1.0}]}})
    stock(db, "462775", "L", Decimal(0), 10)    # already on the proposal: left out
    stock(db, "462921", "L", Decimal(0), 10)    # nothing on hand: first
    stock(db, "777", "PCS", Decimal(2), 1)      # no Valio price: shown, cannot be added

    r = client.get(f"{K}/proposals/{p['proposal_id']}/addable", headers=AGENT)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["proposal_id"] == p["proposal_id"]
    rows = body["rows"]
    assert [row["product_id"] for row in rows] == ["462921", "777"]

    organic = rows[0]
    assert organic["rank"] == 1 and organic["timing"] == "TODAY"
    assert organic["unit"] == "KI" and organic["suggested_qty"] == "8"     # 40 L / 5 L per case
    assert organic["unit_price"] == "10.97" and organic["addable"] is True
    assert organic["on_hand"] == "0" and organic["on_order"] == "0"
    assert organic["why"] == "The engine says order today: 8 KI."

    napkins = rows[1]
    assert napkins["addable"] is False and napkins["unit_price"] is None
    assert napkins["why"].endswith("No price yet, so it cannot be added.")


def test_unknown_proposal_is_404_and_other_kitchen_cannot_read_it(env):  # noqa: F811
    client, _, _ = env
    p = milk(client)
    assert client.get(f"{K}/proposals/nope/addable", headers=AGENT).status_code == 404
    other = client.get(f"/v1/kitchens/other/proposals/{p['proposal_id']}/addable", headers=AGENT)
    assert other.status_code == 404


def test_no_token_no_access(env):  # noqa: F811
    client, _, _ = env
    p = milk(client)
    assert client.get(f"{K}/proposals/{p['proposal_id']}/addable").status_code == 401


def test_mov_padding_suggests_wanted_lines_to_reach_free_delivery(env):  # noqa: F811
    client, _, db = env
    db.suppliers.insert_one({"kitchen_id": "demo-kitchen", "adapter": "valio_api",
                             "terms": {"free_delivery_threshold_eur": "200", "delivery_fee_eur": "25"}})
    r = client.post(K + "/proposals", headers=AGENT, json={
        "product_ids": ["462775"], "quantity": "51", "unit": "L", "requested_date": "2026-11-16",
        "idempotency_key": "pad1"})
    p = r.json()                                   # 51 x 2.57 = 131.07: 68.93 under free delivery
    stock(db, "462921", "L", Decimal(0), 10)       # the engine wants 8 KI (87.76)
    pad = client.get(f"{K}/proposals/{p['proposal_id']}/addable", headers=AGENT).json()["mov_padding"]
    assert pad["add"] == [{"product_id": "462921", "quantity": "8", "unit": "KI", "value": "87.76"}]
    assert pad["saves_fee"] == "25.00" and pad["reason_codes"] == ["MOV_PADDED"]


def test_standing_order_that_no_longer_matches_usage_shows_drift(env):  # noqa: F811
    """#380: a kitchen's standing order is read from its settings and passed to the engine."""
    client, _, db = env
    p = milk(client)
    db.kitchen_settings.insert_one({"_id": "demo-kitchen", "standing_orders": {"462921": "12", "777": "1"}})
    stock(db, "462921", "L", Decimal(0), 10)       # usage 10 L x 3 days = 6 KI; the standing order says 12
    rows = client.get(f"{K}/proposals/{p['proposal_id']}/addable", headers=AGENT).json()["rows"]
    organic = rows[0]
    assert "STANDING_ORDER_DRIFT" in organic["reason_codes"]
    assert "Standing order 12 KI no longer matches usage (6 per delivery); this delivery needs 8." in organic["why"]


def test_standing_order_close_to_usage_is_no_drift(env):  # noqa: F811
    client, _, db = env
    p = milk(client)
    db.kitchen_settings.insert_one({"_id": "demo-kitchen", "standing_orders": {"462921": "6"}})
    stock(db, "462921", "L", Decimal(0), 10)
    organic = client.get(f"{K}/proposals/{p['proposal_id']}/addable", headers=AGENT).json()["rows"][0]
    assert "STANDING_ORDER_DRIFT" not in organic["reason_codes"]


def test_malformed_standing_order_is_skipped_not_a_500(env):  # noqa: F811
    """#415: a non-numeric standing order must not break the whole addable list."""
    client, _, db = env
    p = milk(client)
    db.kitchen_settings.insert_one({"_id": "demo-kitchen", "standing_orders": {"462921": "abc", "777": "5"}})
    stock(db, "462921", "L", Decimal(0), 10)
    r = client.get(f"{K}/proposals/{p['proposal_id']}/addable", headers=AGENT)
    assert r.status_code == 200
    organic = next(row for row in r.json()["rows"] if row["product_id"] == "462921")
    assert "STANDING_ORDER_DRIFT" not in organic["reason_codes"]


def test_a_person_sets_standing_orders_in_settings_and_drift_shows(env):  # noqa: F811
    """#380 live: PUT /settings stores the map (replaced, never merged) and the addable rows read it."""
    from gateway.tests.test_gateway_app import HUMAN
    client, _, _ = env
    p = milk(client)
    stock_rows = client.put(f"{K}/settings", headers=HUMAN, json={"standing_orders": {"462921": "12", "777": "1"}})
    assert stock_rows.status_code == 200, stock_rows.text
    r = client.put(f"{K}/settings", headers=HUMAN, json={"standing_orders": {"462921": "12"}})
    assert r.json()["standing_orders"] == {"462921": "12"}                    # replaced, not merged
    assert client.put(f"{K}/settings", headers=HUMAN, json={"standing_orders": {"462921": "-1"}}).status_code == 422
    assert client.put(f"{K}/settings", headers=AGENT, json={"standing_orders": {}}).status_code == 403


def test_standing_orders_from_settings_reach_the_addable_rows(env):  # noqa: F811
    from gateway.tests.test_gateway_app import HUMAN
    client, _, db = env
    p = milk(client)
    client.put(f"{K}/settings", headers=HUMAN, json={"standing_orders": {"462921": "12"}})
    stock(db, "462921", "L", Decimal(0), 10)
    row = client.get(f"{K}/proposals/{p['proposal_id']}/addable", headers=AGENT).json()["rows"][0]
    assert "STANDING_ORDER_DRIFT" in row["reason_codes"]
