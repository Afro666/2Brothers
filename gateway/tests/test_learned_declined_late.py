"""A declined product (#1307) and a late supplier (#1306) in the same plan window (#1702):
the declined product is left out first, the learned safety stock goes only on the lines
that stay, and the audit has one `learned_fact_applied` change per changed line."""

from gateway.tests.test_gateway_app import AGENT, env  # noqa: F401 (fixture)
from gateway.tests.test_learned_declined import CREAM, MILK, audit, ids, proposal, remove, setup
from gateway.tests.test_learned_timing import seed_deliveries


def test_declined_is_left_out_first_and_safety_stock_goes_on_the_rest(env):
    client, _, db = env
    setup(client, db)
    remove(db, 3)                                   # CREAM: removed 3 times
    seed_deliveries(db, product_id=MILK)            # Valio late for MILK
    seed_deliveries(db, product_id=CREAM, prefix="c")
    p = proposal(client, "declined-late")

    assert ids(p["lines"]) == {MILK}
    assert ids(p["request"]["needs"]) == {MILK}
    assert [e["product_id"] for e in p["excluded"]] == [CREAM]

    milk = next(n for n in p["request"]["needs"] if n["product_id"] == MILK)
    assert milk["learned"]["kind"] == "SUPPLIER_LATE"
    assert milk["quantity"] == milk["learned"]["to_qty"] != milk["unlearned_quantity"]
    line = next(ln for ln in p["lines"] if ln["product_id"] == MILK)
    assert line["why"].startswith(f"Includes {milk['learned']['safety_stock']} L learned safety stock")
    assert all(ln["product_id"] != CREAM for ln in p["lines"])

    applied = audit(db, "learned_fact_applied")
    assert len(applied) == 1 and applied[0]["proposal_id"] == p["proposal_id"]
    changes = applied[0]["applied"]
    assert sorted(c["product_id"] for c in changes) == sorted([MILK, CREAM])
    assert {"product_id": MILK, "fact_id": milk["learned"]["fact_id"],
            "from_qty": milk["unlearned_quantity"], "to_qty": milk["quantity"], "unit": "L"} in changes
    assert {"product_id": CREAM, "fact_id": p["excluded"][0]["fact_id"],
            "from_qty": "8", "to_qty": "0", "unit": "L"} in changes


def test_a_product_in_two_units_gets_only_its_own_units_learned_change(env):
    """Lines match their need by product and unit: the ratio of the litre need never
    touches the line of the same product planned in pieces."""
    import mongomock
    from gateway.service import Gateway
    from gateway.tests.test_gateway_app import NOW, RAW, FakeValio
    from gateway.valio_client import ValioClient
    db = mongomock.MongoClient(tz_aware=True)["two-units"]
    for pid, raw in RAW.items():
        db.products.insert_one({"_id": pid, "names": {"en": f"milk {pid}"}, "raw": raw})
    valio = ValioClient("test-not-a-real-key", transport=FakeValio().transport, ttl=0, now=lambda: NOW)
    gw = Gateway(db, valio, now=lambda: NOW, search=lambda *a, **k: [])
    sim = gw._basket("demo-kitchen", {
        "requested_date": "2026-11-16", "made_by": "menu_plan", "needs": [
            {"product_id": MILK, "quantity": "10", "unit": "L", "unlearned_quantity": "20",
             "learned": {"ratio": "0.5", "fact_id": "f-1", "from_qty": "20", "to_qty": "10", "unit": "L"}},
            {"product_id": MILK, "quantity": "4", "unit": "ST"}]})
    lines = [ln for ln in sim["lines"] if ln["product_id"] == MILK]
    assert len(lines) == 2
    assert sum("unlearned_quantity" in ln for ln in lines) == 1
