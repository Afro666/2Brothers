"""A placed order says RECORDED, never SENT: no order is sent to a supplier.

Valio's challenge API has no order route. The signed receipt says `supplier_outcome:
NOT_SENT`; the order answer must say the same fact (docs/contract.md, "Order status").
A lookup is a read: it writes no audit line.
"""

from datetime import date

from gateway.kitchen_routes import incoming_orders_query
from gateway.tests.test_gateway_app import HUMAN, K, env, milk  # noqa: F401  (env is a fixture)
from gateway.tests.test_resolve_unknown_send import kinds, read_failed, resolve
from gateway.verify_offer import check_receipt
from store import orders


def approve(client, p, key="rec-1"):
    r = client.post(f"{K}/proposals/{p['proposal_id']}/approve", headers=HUMAN,
                    json={"expected_total": p["expected_total"], "idempotency_key": key})
    assert r.status_code == 200, r.text
    return r.json()


def test_a_placed_order_is_recorded_and_its_receipt_still_verifies(env):
    client, _, db = env
    out = approve(client, milk(client))
    assert (out["outcome"], out["status"]) == ("CONFIRMED", "RECORDED")
    assert db.orders.find_one({"_id": out["order_id"]})["status"] == "RECORDED"
    ok, message, claims = check_receipt(out, client.get("/.well-known/jwks.json").json())
    assert ok, message
    assert claims["supplier_outcome"] == "NOT_SENT"          # the receipt is unchanged
    for answer in (client.get(f"{K}/orders/{out['order_id']}", headers=HUMAN).json(),
                   client.get(f"{K}/orders", headers=HUMAN).json()["orders"][0]):
        assert (answer["outcome"], answer["status"]) == ("CONFIRMED", "RECORDED")


def test_an_order_stored_as_sent_is_answered_as_recorded(env):
    client, _, db = env
    out = approve(client, milk(client))
    db.orders.update_one({"_id": out["order_id"]}, {"$set": {"status": "SENT"}})   # a row from before
    order_id = out["order_id"]
    answers = [client.get(f"{K}/orders/{order_id}", headers=HUMAN).json(),
               client.get(f"{K}/orders", headers=HUMAN).json()["orders"][0],
               client.get(f"{K}/orders/{order_id}/resolution", headers=HUMAN).json(),
               client.get("/tools/get_order_status", params={"order_id": order_id}, headers=HUMAN).json()]
    assert [a["status"] for a in answers] == ["RECORDED"] * 4
    pid = out["lines"][0]["product_id"]
    page = client.get(f"{K}/catalog/products/{pid}", headers=HUMAN).json()
    assert {o["status"] for o in page["kitchen"]["orders"]} == {"RECORDED"}


def test_recorded_and_legacy_sent_orders_both_count_as_incoming(env):
    client, _, db = env
    first = approve(client, milk(client), key="rec-a")
    query = incoming_orders_query("demo-kitchen")
    assert db.orders.count_documents(query) == 1
    db.orders.update_one({"_id": first["order_id"]}, {"$set": {"status": "SENT"}})
    assert db.orders.count_documents(query) == 1


def test_a_recorded_order_can_be_marked_received(env):
    client, _, _ = env
    out = approve(client, milk(client))
    r = client.post(f"{K}/orders/{out['order_id']}/received", headers=HUMAN,
                    json={"idempotency_key": "got-1", "delivery_date": date.today().isoformat(),
                          "complete": True})
    assert r.status_code != 409, r.text


def test_the_resolution_lookup_writes_no_audit_line_and_the_resolve_does(env):
    client, _, db = env
    _, order_id = read_failed(client, db)
    before = kinds(db, order_id)
    for _ in range(3):
        assert client.get(f"{K}/orders/{order_id}/resolution", headers=HUMAN).status_code == 200
    assert kinds(db, order_id) == before
    assert db.audit_log.count_documents({"event.kind": "order_lookup"}) == 0
    r = resolve(client, order_id, resolution="placed", supplier_order_ref="VAL-9")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "RECORDED"
    assert len(kinds(db, order_id)) == len(before) + 1
    assert orders.get_order(db, order_id)["status"] == "RECORDED"
