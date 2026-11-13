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
