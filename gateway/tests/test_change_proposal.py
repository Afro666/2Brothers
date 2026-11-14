"""Changing a proposal's lines (#303): POST /proposals/{id}/change and the MCP tool.

Aron, 2026-11-14: "user cannot edit pcs" on a proposal. A person or an agent may set a
line's quantity, remove a line or add a product the addable list offers; the gateway
re-quotes live, the engine rounds to the lot size, and only a person approves the new
exact total.
"""

from decimal import Decimal

from gateway.tests.test_addable_route import stock
from gateway.tests.test_gateway_app import AGENT, HUMAN, K, env, milk  # noqa: F401 (fixture)


def change(client, p, lines=None, add=None, key="ch1", headers=HUMAN):
    body = {"idempotency_key": key}
    if lines is not None:
        body["lines"] = lines
    if add is not None:
        body["add"] = add
    return client.post(f"{K}/proposals/{p['proposal_id']}/change", headers=headers, json=body)


def approve(client, p, total, key="a1"):
    return client.post(f"{K}/proposals/{p['proposal_id']}/approve", headers=HUMAN,
                       json={"expected_total": total, "idempotency_key": key})


def qty(p):
    return [(ln["product_id"], ln["quantity"]) for ln in p["lines"]]


def events(db, kind):
    return [e["event"] for e in db.audit_log.find({}) if e.get("event", {}).get("kind") == kind]


def test_a_person_sets_a_lines_quantity_and_the_gateway_requotes(env):
    client, _, db = env
    p = milk(client, quantity="51")
    assert qty(p) == [("462775", "51")]
    r = change(client, p, lines=[{"product_id": "462775", "quantity": "40"}])
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["proposal_id"] == p["proposal_id"] and out["status"] == "READY"
    assert qty(out) == [("462775", "40")]
    assert out["offer_id"] != p["offer_id"] and out["offer_hash"]
    assert out["expected_total"] != p["expected_total"]
    assert out["lines"][0]["why"].startswith("Quantity set by aron.")
    assert out["mandate"]["verdict"] == "NEEDS_APPROVAL"
    # The GET shape answers the same proposal.
    got = client.get(f"{K}/proposals/{p['proposal_id']}", headers=HUMAN).json()
    assert got["offer_id"] == out["offer_id"] and qty(got) == [("462775", "40")]
    assert set(got) == set(out)
    assert db.orders.count_documents({}) == 0             # nothing approved, nothing sent


def test_the_engine_rounds_to_the_lot_size_and_says_so(env):
    client, _, _ = env
    p = milk(client, quantity="51")
    out = change(client, p, lines=[{"product_id": "462775", "quantity": "2.5"}]).json()
    assert qty(out) == [("462775", "3")]
    why = out["lines"][0]["why"]
    assert why.startswith("Quantity set by aron") and "2.5" in why and "rounded up to 3 ST" in why
    assert "LOT_SIZE_ROUNDED" in out["lines"][0]["reason_codes"]


def test_quantity_zero_removes_a_line_and_the_rest_can_be_approved(env):
    client, _, db = env
    p = milk(client, quantity="1000")
    assert qty(p) == [("462775", "51"), ("463335", "949")]
    assert p["lines"][1]["unknown_stock"] is True     # a yes now would send it waiting for Valio (2026-11-14)
    out = change(client, p, lines=[{"product_id": "463335", "quantity": 0}]).json()
    assert qty(out) == [("462775", "51")]
    ok = approve(client, out, out["expected_total"], key="a2")
    assert ok.status_code == 200, ok.text
    order = db.orders.find_one({})
    assert [(ln["product_id"], str(ln["quantity"])) for ln in order["lines"]] == [("462775", "51")]


def test_removing_every_line_is_refused(env):
    client, _, _ = env
    p = milk(client, quantity="51")
    r = change(client, p, lines=[{"product_id": "462775", "quantity": "0"}])
    assert r.status_code == 422 and r.json()["error"]["code"] == "EMPTY_PROPOSAL"
    assert client.get(f"{K}/proposals/{p['proposal_id']}", headers=HUMAN).json()["offer_id"] == p["offer_id"]


def test_a_product_from_the_addable_list_can_be_added(env):
    client, _, db = env
    p = milk(client, quantity="51")
    stock(db, "463335", "PCS", Decimal(0), 10)
    addable = client.get(f"{K}/proposals/{p['proposal_id']}/addable", headers=HUMAN).json()
    assert any(r["product_id"] == "463335" and r["addable"] for r in addable["rows"])
    r = change(client, p, add=[{"product_id": "463335", "quantity": "12"}])
    assert r.status_code == 200, r.text
    out = r.json()
    assert qty(out) == [("462775", "51"), ("463335", "12")]
    added = out["lines"][1]
    assert added["why"].startswith("Quantity set by aron.") and added["unknown_stock"] is True


def test_a_product_not_on_the_addable_list_cannot_be_added(env):
    client, _, _ = env
    p = milk(client, quantity="51")
    r = change(client, p, add=[{"product_id": "463335", "quantity": "12"}])
    assert r.status_code == 409 and r.json()["error"]["code"] == "NOT_ADDABLE"


def test_a_line_not_on_the_proposal_and_bad_bodies(env):
    client, _, _ = env
    p = milk(client, quantity="51")
    r = change(client, p, lines=[{"product_id": "463335", "quantity": "5"}])
    assert r.status_code == 404 and r.json()["error"]["code"] == "LINE_NOT_FOUND"
    for lines in ([{"product_id": "462775", "quantity": "-1"}], [{"product_id": "462775", "quantity": "lots"}],
                  [{"product_id": "462775"}], [], "462775",
                  [{"product_id": "462775", "quantity": "1"}, {"product_id": "462775", "quantity": "2"}]):
        r = change(client, p, lines=lines)
        assert r.status_code == 422, (lines, r.text)
    r = client.post(f"{K}/proposals/{p['proposal_id']}/change", headers=HUMAN,
                    json={"lines": [{"product_id": "462775", "quantity": "5"}]})
    assert r.status_code == 422                                  # no idempotency_key
    assert change(client, {"proposal_id": "nope"}, lines=[{"product_id": "1", "quantity": "1"}]).status_code == 404


def test_only_a_ready_proposal_can_change(env):
    client, _, db = env
    p = milk(client, quantity="51")
    client.post(f"{K}/proposals/{p['proposal_id']}/reject", headers=HUMAN,
                json={"reason": "not this week", "idempotency_key": "r1"})
    r = change(client, p, lines=[{"product_id": "462775", "quantity": "40"}])
    assert r.status_code == 409 and r.json()["error"]["code"] == "NOT_PENDING"


def test_a_recall_held_proposal_cannot_change(env):
    client, _, db = env
    p = milk(client, quantity="51")
    db.proposals.update_one({"_id": p["proposal_id"]}, {"$set": {"status": "BLOCKED_BY_RECALL"}})
    r = change(client, p, lines=[{"product_id": "462775", "quantity": "40"}])
    assert r.status_code == 409 and r.json()["error"]["code"] == "NOT_PENDING"
    assert "recall" in r.json()["error"]["message"]


def test_a_repeat_with_the_same_key_changes_nothing_and_another_body_is_refused(env):
    client, _, db = env
    p = milk(client, quantity="51")
    first = change(client, p, lines=[{"product_id": "462775", "quantity": "40"}], key="same").json()
    offers = db.offers.count_documents({})
    again = change(client, p, lines=[{"product_id": "462775", "quantity": "40"}], key="same")
    assert again.status_code == 200 and again.json()["offer_id"] == first["offer_id"]
    assert db.offers.count_documents({}) == offers                 # no second quote
    assert len(events(db, "proposal_changed")) == 1
    other = change(client, p, lines=[{"product_id": "462775", "quantity": "30"}], key="same")
    assert other.status_code == 409 and other.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"


def test_the_old_total_cannot_be_approved_after_a_change(env):
    client, _, db = env
    p = milk(client, quantity="51")
    out = change(client, p, lines=[{"product_id": "462775", "quantity": "40"}]).json()
    r = approve(client, p, p["expected_total"])                     # the total of the old basket
    assert r.status_code == 409 and r.json()["error"]["code"] == "TOTAL_MISMATCH"
    assert r.json()["error"]["expected_total"] == out["expected_total"]
    assert db.orders.count_documents({}) == 0
    ok = approve(client, out, out["expected_total"], key="a2")
    assert ok.status_code == 200, ok.text
    assert Decimal(str(db.orders.find_one({})["expected_total"])) == Decimal(out["expected_total"])


def test_the_change_is_in_the_audit_log_with_before_and_after(env):
    client, _, db = env
    p = milk(client, quantity="1000")
    out = change(client, p, lines=[{"product_id": "462775", "quantity": "40"},
                                   {"product_id": "463335", "quantity": "0"}]).json()
    [event] = events(db, "proposal_changed")
    assert event["actor"] == "aron" and event["proposal_id"] == p["proposal_id"]
    assert event["from_offer_id"] == p["offer_id"] and event["offer_id"] == out["offer_id"]
    assert event["from_total"] == p["expected_total"] and event["expected_total"] == out["expected_total"]
    assert event["changes"] == [
        {"product_id": "462775", "unit": "ST", "from_qty": "51", "asked_qty": "40", "to_qty": "40"},
        {"product_id": "463335", "unit": "ST", "from_qty": "949", "asked_qty": "0", "to_qty": "0"}]
    feedback = sorted((f["kind"], f["meta"]["product_id"]) for f in db.feedback.find({}))
    assert feedback == [("line_removed", "463335"), ("qty_changed", "462775")]


def test_an_agent_may_change_but_never_approve(env):
    client, _, db = env
    p = milk(client, quantity="51")
    r = change(client, p, lines=[{"product_id": "462775", "quantity": "40"}], headers=AGENT)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["lines"][0]["why"].startswith("Quantity set by buyer-agent.")
    assert db.feedback.count_documents({}) == 0                     # learning data is what a person did
    refused = client.post(f"{K}/proposals/{p['proposal_id']}/approve", headers=AGENT,
                          json={"expected_total": out["expected_total"], "idempotency_key": "x"})
    assert refused.status_code == 403


def test_the_tools_route_changes_the_same_proposal(env):
    client, _, _ = env
    p = milk(client, quantity="51")
    r = client.post("/tools/change_proposal", headers=AGENT, json={
        "proposal_id": p["proposal_id"], "idempotency_key": "t1",
        "lines": [{"product_id": "462775", "quantity": "40"}]})
    assert r.status_code == 200, r.text
    assert qty(r.json()) == [("462775", "40")]
