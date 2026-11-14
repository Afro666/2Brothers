"""The permissions table (#273) and proof that every "never" row is really refused."""

from gateway import permissions
from gateway.tests.test_gateway_app import AGENT, HUMAN, K, env, milk  # noqa: F401 (fixture)


def test_matrix_is_served_and_has_the_three_groups(env):
    client, _, _ = env
    m = client.get(K + "/permissions", headers=AGENT).json()
    assert set(m) == {"alone", "person", "never"}
    assert all({"action", "audit_kind", "rule"} <= set(row) for group in m.values() for row in group)
    assert client.get(K + "/permissions").status_code == 401


def test_every_never_row_has_a_proof_below():
    proven = {"approve", "place_unapproved", "cancel", "change_quantity", "other_kitchen"}
    assert {row["id"] for row in permissions.NEVER} == proven


def test_never_approve_or_reject(env):
    client, _, _ = env
    p = milk(client)
    token = client.post(K + "/tokens", headers=HUMAN, json={"name": "t", "scopes": ["kitchen:read", "kitchen:propose"]}).json()["token"]
    for headers in (AGENT, {"Authorization": "Bearer " + token}):
        for action, body in (("approve", {"expected_total": p["expected_total"], "idempotency_key": "a"}),
                             ("reject", {"reason": "no", "idempotency_key": "r"})):
            r = client.post(f"{K}/proposals/{p['proposal_id']}/{action}", headers=headers, json=body)
            assert r.status_code == 403 and r.json()["error"]["code"] == "HUMAN_SESSION_REQUIRED"
    r = client.post(K + "/tokens", headers=HUMAN, json={"name": "t2", "scopes": ["kitchen:approve"]})
    assert r.status_code == 422


def test_never_place_an_unapproved_order(env):
    client, _, db = env
    p = milk(client)
    r = client.post("/tools/place_order", headers=AGENT, json={
        "offer_id": p["offer_id"], "expected_total": p["expected_total"], "idempotency_key": "x"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "NEEDS_APPROVAL"
    assert db.orders.count_documents({}) == 0


def test_never_cancel_and_never_change_a_quantity(env):
    client, _, _ = env
    p = milk(client)
    for method, path in (("DELETE", f"{K}/proposals/{p['proposal_id']}"), ("DELETE", f"{K}/orders/any"),
                         ("POST", f"{K}/orders/any/cancel"), ("POST", "/tools/cancel_order"),
                         ("PUT", f"{K}/orders/any"), ("PATCH", f"{K}/orders/any")):
        assert client.request(method, path, headers=AGENT, json={}).status_code in (404, 405), path
    # A quantity from the model is ignored: the need decides.
    need = client.post(K + "/needs", headers=AGENT, json={"quantity": "20", "unit": "L", "requested_date": "2026-11-16"}).json()
    offer = client.post("/tools/get_offer", headers=AGENT, json={
        "need_id": need["need_id"], "product_ids": ["462775"], "quantity": "9999"}).json()
    assert offer["lines"][0]["quantity"] == "20"


def test_never_act_for_another_kitchen(env):
    client, _, _ = env
    token = client.post(K + "/tokens", headers=HUMAN, json={"name": "t", "scopes": ["kitchen:read"]}).json()["token"]
    r = client.get("/v1/kitchens/other-kitchen/orders", headers={"Authorization": "Bearer " + token})
    assert r.status_code == 403 and r.json()["error"]["code"] == "KITCHEN_SCOPE"
