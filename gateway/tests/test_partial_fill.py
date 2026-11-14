"""The proposal carries the engine's partial-fill option (#288): 51 L now, 949 L held."""

from gateway.partial_fill import partial_out
from gateway.tests.test_gateway_app import AGENT, K, env, milk  # noqa: F401  (env is a fixture)


def test_milk_proposal_carries_the_partial_fill(env):  # noqa: F811
    client, _, _ = env
    p = milk(client, quantity="1000")
    part = p["partial_fill"]
    assert (part["need"], part["measure"], part["remaining"]) == ("1000", "L", "949")
    # The test products have no allergen data: unknown, so the option says so.
    assert part["reason_codes"] == ["PARTIAL_STOCK", "PACK_SIZE_DERIVED", "ALLERGEN_DATA_MISSING"]
    now = part["now"]
    assert (now["kind"], now["quantity"], now["deliver_on"], now["total_ex_vat"]) == ("NOW", "51", "2026-11-16", "131.07")
    assert [(ln["product_id"], ln["quantity"], ln["unit"], ln["unknown_stock"]) for ln in now["lines"]] == [
        ("462775", "51", "ST", False)]
    assert part["rest"] == [{
        "kind": "HOLD", "quantity": "949", "measure": "L", "deliver_on": None, "total_ex_vat": None,
        "why": "Hold the remaining 949 L until Valio confirms stock: "
               "no offer shows confirmed stock for a later delivery date.",
        "lines": []}]
    assert part["why"] == f"{now['why']} {part['rest'][0]['why']}"
    assert "51 L" in part["why"] and "949 L" in part["why"]
    # The main basket is unchanged: the partial option is extra, never applied by itself.
    assert [(ln["product_id"], ln["quantity"]) for ln in p["lines"]] == [("462775", "51"), ("463335", "949")]
    assert p["total_ex_vat"] == "1459.67"


def test_same_partial_fill_on_read_and_on_the_agent_offer(env):  # noqa: F811
    client, _, _ = env
    p = milk(client, quantity="1000")
    again = client.get(f"{K}/proposals/{p['proposal_id']}", headers=AGENT)
    assert again.status_code == 200, again.text
    assert again.json()["partial_fill"] == p["partial_fill"]


def test_no_partial_fill_when_confirmed_stock_covers_the_request(env):  # noqa: F811
    client, _, _ = env
    assert milk(client, quantity="51")["partial_fill"] is None


def test_partial_out_of_nothing_is_none():
    assert partial_out(None) is None
