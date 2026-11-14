"""Choosing an option on a proposal, and the "confirmed stock only" option (gateway/options.py).

Live case 2026-11-14: every milk proposal in the demo inbox had a line with unconfirmed
stock, so no Approve button worked. The engine already knew the part Valio confirms
(`partial_fill.now`); it was read-only. It is now an option a person can choose and approve.
"""

from gateway.tests.test_gateway_app import AGENT, HUMAN, K, env, milk  # noqa: F401 (fixture)


def choose(client, p, offer_id, key="c1", headers=HUMAN):
    return client.post(f"{K}/proposals/{p['proposal_id']}/choose-option", headers=headers,
                       json={"offer_id": offer_id, "idempotency_key": key})


def approve(client, p, key="a1"):
    return client.post(f"{K}/proposals/{p['proposal_id']}/approve", headers=HUMAN,
                       json={"expected_total": p["expected_total"], "idempotency_key": key})


def confirmed(p):
    return next(o for o in p["substitute_options"] if o["source"] == "confirmed")


def test_a_short_order_offers_the_confirmed_part_as_an_option(env):
    client, _, _ = env
    p = milk(client, quantity="1000")
    option = confirmed(p)
    assert [(ln["product_id"], ln["quantity"]) for ln in option["lines"]] == [("462775", "51")]
    assert option["stock_confirmed"] is True and option["requires_chef_approval"] is True
    assert option["tier"] == "good" and option["currency"] == "EUR"
    assert option["held"] == {"quantity": "949", "unit": "L"}
    assert "51 L now" in option["why"] and "949 L" in option["why"]
    assert option["offer_id"] != p["offer_id"]            # its own stored quote
    assert option["expected_total"] != p["expected_total"]
    # The proposal itself is unchanged: still the engine's full plan, still not placeable.
    assert [(ln["product_id"], ln["quantity"]) for ln in p["lines"]] == [("462775", "51"), ("463335", "949")]
    assert approve(client, p).json()["error"]["code"] == "STOCK_UNKNOWN"


def test_no_option_when_the_plan_is_fully_confirmed(env):
    client, _, _ = env
    p = milk(client, quantity="51")
    assert p["substitute_options"] == []


def test_choosing_the_confirmed_part_makes_the_proposal_approvable(env):
    client, _, db = env
    p = milk(client, quantity="1000")
    option = confirmed(p)
    r = choose(client, p, option["offer_id"])
    assert r.status_code == 200, r.text
    chosen = r.json()
    assert chosen["status"] == "READY" and chosen["proposal_id"] == p["proposal_id"]
    assert [(ln["product_id"], ln["quantity"]) for ln in chosen["lines"]] == [("462775", "51")]
    assert chosen["expected_total"] == option["expected_total"]
    assert all(ln["unknown_stock"] is False for ln in chosen["lines"])
    # The chosen entry carries the fresh offer id: the client finds the choice by comparing.
    assert confirmed(chosen)["offer_id"] == chosen["offer_id"]
    assert db.orders.count_documents({}) == 0                      # nothing approved, nothing sent
    ok = approve(client, chosen)
    assert ok.status_code == 200, ok.text
    assert db.orders.count_documents({}) == 1
    order = db.orders.find_one({})
    assert [(ln["product_id"], str(ln["quantity"])) for ln in order["lines"]] == [("462775", "51")]
    kinds = [e["event"]["kind"] if "kind" in e.get("event", {}) else e.get("kind") for e in db.audit_log.find({})]
    assert "option_chosen" in kinds


def test_the_old_total_is_refused_after_a_choice(env):
    client, _, _ = env
    p = milk(client, quantity="1000")
    choose(client, p, confirmed(p)["offer_id"])
    r = approve(client, p)                                         # the total of the old basket
    assert r.status_code == 409 and r.json()["error"]["code"] == "TOTAL_MISMATCH"


def test_only_a_person_can_choose(env):
    client, _, _ = env
    p = milk(client, quantity="1000")
    r = choose(client, p, confirmed(p)["offer_id"], headers=AGENT)
    assert r.status_code == 403 and r.json()["error"]["code"] == "HUMAN_SESSION_REQUIRED"


def test_unknown_option_unknown_proposal_and_missing_fields(env):
    client, _, _ = env
    p = milk(client, quantity="1000")
    assert choose(client, p, "not-an-option").json()["error"]["code"] == "OPTION_NOT_FOUND"
    assert choose(client, {"proposal_id": "nope"}, "x").json()["error"]["code"] == "PROPOSAL_NOT_FOUND"
    r = client.post(f"{K}/proposals/{p['proposal_id']}/choose-option", headers=HUMAN, json={"offer_id": "x"})
    assert r.status_code == 422


def test_a_repeat_with_the_same_key_changes_nothing_and_another_body_is_refused(env):
    client, _, db = env
    p = milk(client, quantity="1000")
    option = confirmed(p)
    first = choose(client, p, option["offer_id"], key="same").json()
    offers = db.offers.count_documents({})
    again = choose(client, p, option["offer_id"], key="same")
    assert again.status_code == 200 and again.json()["offer_id"] == first["offer_id"]
    assert db.offers.count_documents({}) == offers                 # no second quote
    other = choose(client, p, "another-offer", key="same")
    assert other.status_code == 409 and other.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"


def test_a_decided_proposal_cannot_be_changed(env):
    client, _, _ = env
    p = milk(client, quantity="1000")
    option = confirmed(p)
    client.post(f"{K}/proposals/{p['proposal_id']}/reject", headers=HUMAN,
                json={"reason": "not this week", "idempotency_key": "r1"})
    r = choose(client, p, option["offer_id"])
    assert r.status_code == 409 and r.json()["error"]["code"] == "NOT_PENDING"


def test_when_the_confirmed_stock_is_gone_the_choice_is_refused_and_nothing_changes(env):
    client, fake, _ = env
    p = milk(client, quantity="1000")
    option = confirmed(p)
    for product in fake.avail_data["products"]:                    # Valio no longer reports the stock
        if product["productId"] == "462775":
            for line in product.get("scheduleLines", []):
                line["availableAmount"] = 999999
    r = choose(client, p, option["offer_id"])
    assert r.status_code == 409 and r.json()["error"]["code"] == "STOCK_UNKNOWN"
    after = client.get(f"{K}/proposals/{p['proposal_id']}", headers=HUMAN).json()
    assert after["offer_id"] == p["offer_id"]                      # it keeps the basket it had


def test_at_most_three_options_with_distinct_tiers(env):
    client, _, db = env
    p = milk(client, quantity="1000")
    mine = confirmed(p)
    extra = [{**mine, "source": "catalog", "offer_id": f"agent-{n}", "tier": tier, "stock_confirmed": False}
             for n, tier in enumerate(("good", "better", "best"))]
    db.proposals.update_one({"_id": p["proposal_id"]}, {"$set": {"substitute_options": extra}})
    options = client.get(f"{K}/proposals/{p['proposal_id']}", headers=HUMAN).json()["substitute_options"]
    assert [o["tier"] for o in options] == ["good", "better", "best"]
    assert options[0]["source"] == "confirmed" and [o["offer_id"] for o in options[1:]] == ["agent-0", "agent-1"]


def test_a_proposal_made_through_the_buyer_tools_gets_the_option_too(env):
    """The Nemotron Buyer does not call POST /proposals: it stores a need, asks for an offer
    and requests approval. Its proposal must offer the confirmed part as well."""
    client, _, _ = env
    need = client.post(K + "/needs", headers=AGENT,
                       json={"quantity": "1000", "unit": "L", "requested_date": "2026-11-16"}).json()
    offer = client.post("/tools/get_offer", headers=AGENT,
                        json={"need_id": need["need_id"], "product_ids": ["462775", "463335"]}).json()
    asked = client.post("/tools/request_approval", headers=AGENT,
                        json={"offer_id": offer["offer_id"], "idempotency_key": "buyer-1"})
    assert asked.status_code == 200, asked.text
    p = client.get(f"{K}/proposals/{asked.json()['proposal_id']}", headers=HUMAN).json()
    option = confirmed(p)
    assert [(ln["product_id"], ln["quantity"]) for ln in option["lines"]] == [("462775", "51")]
    chosen = choose(client, p, option["offer_id"]).json()
    assert approve(client, chosen).status_code == 200


def test_a_failing_confirmed_option_is_logged_and_the_proposal_is_still_made(env, caplog, monkeypatch):
    import logging

    from gateway import options

    def boom(*args, **kwargs):
        raise KeyError("requested_date")

    monkeypatch.setattr(options, "_confirmed_option", boom)
    client, _, _ = env
    with caplog.at_level(logging.WARNING, logger="gateway.options"):
        p = milk(client, quantity="1000")
    assert p["proposal_id"] and p["substitute_options"] == []
    records = [r for r in caplog.records if r.name == "gateway.options"]
    assert len(records) == 1 and records[0].levelno == logging.WARNING
    assert records[0].exc_info is not None
    assert p["proposal_id"] in records[0].getMessage()
