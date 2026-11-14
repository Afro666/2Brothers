"""Learned delivery timing in a plan proposal (#1306): a late supplier's lead-time spread
adds safety stock to its lines, the line says why, and switching the fact off undoes it."""

from datetime import date, timedelta
from decimal import Decimal

from gateway.tests.test_gateway_app import AGENT, HUMAN, K, env  # noqa: F401 (fixture)
from gateway.tests.test_learned import audit, seed_corrections
from gateway.tests.test_plan_proposal import setup
from store.delivery_results import save_observation

VALIO = "sup-valio"
MILK = "462775"
COUNTED = [{"product_id": MILK, "on_hand": "5", "unit": "L"}]


def seed_deliveries(db, lateness=(0, 1, 0, 1, 1), supplier_id=VALIO, product_id=MILK,
                    kitchen_id="demo-kitchen", prefix="d"):
    """One delivery per entry, each ordered two days before its promised day and delivered
    that many days late."""
    for number, late in enumerate(lateness):
        requested = date(2026, 11, 2) + timedelta(days=number)
        delivered = requested + timedelta(days=late)
        save_observation(
            db, kitchen_id=kitchen_id, order_id=f"{prefix}-{number}", supplier_id=supplier_id,
            requested_date=requested, ordered_at=f"{requested - timedelta(days=2)}T10:00:00Z",
            delivery_date=delivered, checked_by="chef-1",
            checked_at=f"{delivered}T08:00:00Z", source="photo",
            lines=[{"supplier_id": supplier_id, "product_id": product_id, "status": "RECEIVED",
                    "ordered": "10", "delivered": "10", "unit": "L"}], not_ordered=[])


def plan(client, key, to="2026-11-22"):
    r = client.post(K + "/proposals", headers=AGENT, json={
        "from": "2026-11-16", "to": to, "requested_date": "2026-11-16", "idempotency_key": key})
    assert r.status_code == 200, r.text
    return r.json()


def need_of(proposal, product_id=MILK):
    return next(need for need in proposal["request"]["needs"] if need["product_id"] == product_id)


def line_of(proposal, product_id=MILK):
    return next(line for line in proposal["lines"] if line["product_id"] == product_id)


def late_fact(client):
    return next(fact for fact in client.get(K + "/learned", headers=AGENT).json()["facts"]
                if fact["kind"] == "SUPPLIER_LATE")


def test_a_late_supplier_adds_safety_stock_and_the_line_says_why(env):
    client, _, db = env
    setup(client, COUNTED)
    plain = need_of(plan(client, "before"))
    assert plain["quantity"] == "20" and "learned" not in plain

    seed_deliveries(db)
    fact = late_fact(client)
    assert fact["on_time_rate"] == 0.4 and fact["mean_days_late"] == 1 and fact["deliveries"] == 5

    proposal = plan(client, "late-1")
    need = need_of(proposal)
    # Gross need 25 L in 7 days = 3.571 L/day; 1.96 x 3.571 x 0.4899 days = 3.43 L.
    assert need["quantity"] == "23.43" and need["unlearned_quantity"] == "20"
    assert need["learned"] == {
        "fact_id": fact["id"], "kind": "SUPPLIER_LATE", "name": "Valio Aimo",
        "from_qty": "20", "to_qty": "23.43", "unit": "L", "safety_stock": "3.43",
        "sigma_lead_time": 0.49, "capped": False,
        "evidence": {"rows": 5, "late": 3, "scope": "product", "from": "2026-11-02",
                     "to": "2026-11-07", "last": "2026-11-07"}}
    line = line_of(proposal)
    assert line["learned"] == need["learned"] and "unlearned_quantity" not in line
    assert line["why"].startswith(
        "Includes 3.43 L learned safety stock on top of 20 L: Valio Aimo was late in 3 of its "
        "last 5 deliveries of this product (lead time varies by 0.49 days). "
        "Switch this learned fact off to order 20 L. ")
    assert Decimal(str(line["quantity"])) >= Decimal("23.43")
    # The note for the person stays a note: no date moves.
    assert any("order a day earlier" in text for text in proposal["request"]["problems"])
    assert proposal["request"]["requested_date"] == "2026-11-16"


def test_the_change_is_audited_and_keeps_the_unlearned_basis(env):
    client, _, db = env
    setup(client, COUNTED)
    seed_deliveries(db)
    proposal = plan(client, "late-audit")
    need = need_of(proposal)
    applied = audit(db, "learned_fact_applied")
    assert len(applied) == 1 and applied[0]["proposal_id"] == proposal["proposal_id"]
    assert {"product_id": MILK, "fact_id": need["learned"]["fact_id"], "from_qty": "20",
            "to_qty": "23.43", "unit": "L"} in applied[0]["applied"]
    offer = db.offers.find_one({"_id": proposal["offer_id"]})
    stored = next(line for line in offer["simulation"]["lines"] if line["product_id"] == MILK)
    expected = (Decimal(str(stored["quantity"])) * 20 / Decimal("23.43")).quantize(Decimal("0.001"))
    assert Decimal(stored["unlearned_quantity"]) == expected


def test_the_fact_switched_off_restores_the_plain_number(env):
    client, _, db = env
    setup(client, COUNTED)
    seed_deliveries(db)
    assert need_of(plan(client, "learned"))["quantity"] == "23.43"
    fact = late_fact(client)
    off = client.put(f"{K}/learned/{fact['id']}", headers=HUMAN, json={"active": False})
    assert off.status_code == 200 and off.json()["fact"]["active"] is False
    db.audit_log.delete_many({})

    proposal = plan(client, "undone")
    need = need_of(proposal)
    assert need["quantity"] == "20" and "learned" not in need and "unlearned_quantity" not in need
    assert all("learned" not in line for line in proposal["lines"])
    assert "learned safety stock" not in line_of(proposal)["why"]
    assert audit(db, "learned_fact_applied") == []


def test_another_kitchens_or_suppliers_deliveries_never_count(env):
    client, _, db = env
    setup(client, COUNTED)
    seed_deliveries(db, kitchen_id="other-kitchen", prefix="theirs")
    seed_deliveries(db, supplier_id="corner-bakery", prefix="bakery")
    proposal = plan(client, "not-ours")
    assert need_of(proposal)["quantity"] == "20"
    assert all("learned" not in line for line in proposal["lines"])
    assert audit(db, "learned_fact_applied") == []


def test_a_supplier_that_is_mostly_on_time_adds_nothing(env):
    client, _, db = env
    setup(client, COUNTED)
    seed_deliveries(db, lateness=(0, 0, 0, 0, 1))          # on-time rate 0.8, spread above 0
    proposal = plan(client, "on-time")
    assert need_of(proposal)["quantity"] == "20"
    assert all("learned" not in line for line in proposal["lines"])


def test_four_late_deliveries_are_too_few(env):
    client, _, db = env
    setup(client, COUNTED)
    seed_deliveries(db, lateness=(1, 0, 1, 1))
    assert need_of(plan(client, "too-few"))["quantity"] == "20"


def test_safety_stock_never_passes_a_quarter_of_the_need(env):
    client, _, db = env
    setup(client, COUNTED)
    seed_deliveries(db)
    # A one-day window: 20 L/day x 1.96 x 0.49 would add 19 L to a need of 15 L.
    need = need_of(plan(client, "one-day", to="2026-11-16"))
    assert need["unlearned_quantity"] == "15" and need["quantity"] == "18.75"
    assert need["learned"]["safety_stock"] == "3.75" and need["learned"]["capped"] is True


def test_a_line_the_chef_already_corrected_gets_no_safety_stock_on_top(env):
    client, _, db = env
    setup(client, COUNTED)
    seed_corrections(db)
    seed_deliveries(db)
    need = need_of(plan(client, "both"))
    assert need["quantity"] == "10" and need["learned"]["ratio"] == 0.5
    assert "kind" not in need["learned"] and "safety_stock" not in need["learned"]


def test_a_typed_request_never_gets_safety_stock(env):
    client, _, db = env
    seed_deliveries(db)
    r = client.post(K + "/proposals", headers=AGENT, json={
        "product_ids": [MILK], "quantity": "20", "unit": "L",
        "requested_date": "2026-11-16", "idempotency_key": "typed-late"})
    assert r.status_code == 200, r.text
    line = r.json()["lines"][0]
    assert line["quantity"] == "20" and "learned" not in line
    assert "learned safety stock" not in line["why"]


def test_valio_dates_are_not_moved(env):
    client, _, db = env
    setup(client, COUNTED)
    before = line_of(plan(client, "dates-before"))
    seed_deliveries(db)
    after = line_of(plan(client, "dates-after"))
    assert "learned" in after
    for key in ("available_date", "closing_time", "cutoff_passed"):
        assert after.get(key) == before.get(key)


def test_a_learned_safety_stock_proposal_waits_for_a_person(env):
    client, _, db = env
    from gateway import autoapprove
    from gateway.tests.test_autoapprove import history, switch_on
    from gateway.tests.test_gateway_app import NOW
    history(db)
    setup(client, COUNTED)
    seed_deliveries(db)
    assert switch_on(client, "2000").status_code == 200
    proposal = plan(client, "auto-late")
    assert proposal["status"] == "READY" and proposal["order_id"] is None
    doc = db.proposals.find_one({"_id": proposal["proposal_id"]})
    sim = db.offers.find_one({"_id": proposal["offer_id"]})["simulation"]
    ok, why, _ = autoapprove.decide(db, "demo-kitchen", sim, doc["request"], NOW)
    assert ok is False and "a learned adjustment needs a person" in why
