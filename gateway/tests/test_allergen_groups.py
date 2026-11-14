"""#672: a group code in a kitchen's excluded allergens means the whole group, in both
directions, and the gateway and the Buyer agent read the rule through one helper."""

import pytest

mongomock = pytest.importorskip("mongomock")

from agent.substitutes import AllergenPolicy  # noqa: E402
from gateway.service import Gateway, GatewayError  # noqa: E402
from store.allergen_groups import GROUPS, excluded_allergen_codes  # noqa: E402

K = "demo-kitchen"
NUTS = ("SA", "SC", "SH", "SM", "SP", "SR", "ST", "SW")
CEREALS = ("UW", "NR", "GB", "GS", "GK")


def row(pid, contains=(), may=(), undeclared=(), known=True):
    return {"_id": pid, "names": {"en": pid}, "allergen_data_known": known,
            "allergens": {"contains": list(contains), "may_contain": list(may),
                          "undeclared": list(undeclared)}}


def gateway_refuses(excluded, product):
    """True when gateway `_allergen_refusals` leaves the product out for this policy."""
    db = mongomock.MongoClient(tz_aware=True)["test"]
    db.kitchen_settings.insert_one({"_id": K, "excluded_allergens": list(excluded)})
    db.products.insert_one(dict(product))
    return product["_id"] in Gateway(db, None)._allergen_refusals(K, [product["_id"]])


def agent_refuses(excluded, product):
    """True when the Buyer's AllergenPolicy does not allow the product."""
    doc = {**product, "product_id": product["_id"]}
    return not AllergenPolicy(tuple(excluded)).allowed(doc)


def test_the_group_tables_come_from_the_search_code_tables():
    assert GROUPS == {"AW": CEREALS, "AN": NUTS}


def test_a_group_code_or_name_excludes_every_member():
    assert excluded_allergen_codes(["AN"]) == sorted(("AN",) + NUTS)
    assert excluded_allergen_codes(["an"]) == excluded_allergen_codes(["nuts"])
    assert excluded_allergen_codes(["AW"]) == sorted(("AW",) + CEREALS)
    assert excluded_allergen_codes(["AW"]) == excluded_allergen_codes(["gluten"])


def test_a_member_code_also_excludes_its_group_code_but_not_its_siblings():
    # A product that declares only "tree nuts" may be almond: unknown is never safe.
    assert excluded_allergen_codes(["SA"]) == ["AN", "SA"]
    assert excluded_allergen_codes(["wheat"]) == ["AW", "UW"]
    assert excluded_allergen_codes(["NR", "AM"]) == ["AM", "AW", "NR"]


def test_oats_stay_outside_the_gluten_group_in_both_directions():
    # docs/decisions.md 2026-11-13 23:32: `gluten` does not exclude oats.
    assert "GO" not in excluded_allergen_codes(["AW"])
    assert "GO" not in excluded_allergen_codes(["gluten"])
    assert excluded_allergen_codes(["GO"]) == ["GO"]
    assert excluded_allergen_codes(["oats"]) == ["GO"]


def test_codes_without_a_group_and_empty_rules_are_unchanged():
    assert excluded_allergen_codes(["AM", "milk", "AP"]) == ["AM", "AP"]
    assert excluded_allergen_codes(["lactose"]) == ["ML"]      # lactose is not the milk group
    assert excluded_allergen_codes([]) == []
    assert excluded_allergen_codes(None) == []


@pytest.mark.parametrize("bad", ["mlik", "AX", "nutz", ""])
def test_a_misspelt_allergen_is_still_an_error_everywhere(bad):
    with pytest.raises(ValueError):
        excluded_allergen_codes(["AN", bad])
    with pytest.raises(ValueError):
        AllergenPolicy(("AN", bad))
    with pytest.raises(GatewayError) as caught:
        gateway_refuses(["AN", bad], row("p1"))
    assert caught.value.status == 409 and caught.value.code == "KITCHEN_POLICY_INVALID"


# (excluded allergens, product, refused): all products have known allergen data.
CASES = [
    (["AN"], row("almond", contains=["SA"]), True),            # the #672 gap
    (["AN"], row("hazel-trace", may=["SH"]), True),
    (["AN"], row("pecan-undeclared", undeclared=["SP"]), True),
    (["AN"], row("nuts", contains=["AN"]), True),
    (["nuts"], row("almond", contains=["SA"]), True),
    (["SA"], row("nuts", contains=["AN"]), True),              # which nut is unknown
    (["SA"], row("nuts-trace", may=["AN"]), True),
    (["SA"], row("nuts-undeclared", undeclared=["AN"]), True),
    (["SA"], row("hazel", contains=["SH"]), False),            # another nut, not excluded
    (["SA"], row("almond", contains=["SA"]), True),
    (["AP", "AN", "AS"], row("walnut", contains=["SW"]), True),   # the seeded demo policy
    (["AP", "AN", "AS"], row("milk", contains=["AM"]), False),
    (["AW"], row("rye", may=["NR"]), True),                    # AW as before
    (["AW"], row("wheat", contains=["UW"]), True),
    (["AW"], row("cereal", contains=["AW"]), True),
    (["AW"], row("oats", contains=["GO"]), False),             # the oats decision
    (["gluten"], row("oats", contains=["GO"]), False),
    (["GO"], row("oats", contains=["GO"]), True),
    (["GO"], row("cereal", contains=["AW"]), False),           # oats are not in the AW group
    (["UW"], row("cereal", contains=["AW"]), True),            # which cereal is unknown
    (["UW"], row("rye", contains=["NR"]), False),
    (["milk"], row("milk", contains=["AM"]), True),
    (["milk"], row("plain", contains=[]), False),
    (["AN"], row("plain", contains=[]), False),
]


@pytest.mark.parametrize("excluded, product, refused", CASES,
                         ids=[f"{'+'.join(c[0])}:{c[1]['_id']}" for c in CASES])
def test_the_gateway_and_the_agent_give_the_same_answer(excluded, product, refused):
    assert gateway_refuses(excluded, product) is refused
    assert agent_refuses(excluded, product) is refused


def test_unknown_allergen_data_is_never_made_safe_by_the_group_rule():
    unknown = row("unknown", known=False)
    # Agent: a restricted kitchen never gets a product with unknown allergen data.
    assert agent_refuses(["AN"], unknown) is True
    assert agent_refuses(["SA"], {"_id": "broken", "allergens": None}) is True
    # Gateway: no ALLERGEN_RULE hit; the line keeps ALLERGEN_DATA_MISSING (contract, S04).
    assert gateway_refuses(["AN"], unknown) is False
    from engine import allergen_codes
    assert allergen_codes(unknown) == ("ALLERGEN_DATA_MISSING",)


def test_the_gateway_reason_names_the_codes_the_product_lists():
    db = mongomock.MongoClient(tz_aware=True)["test"]
    db.kitchen_settings.insert_one({"_id": K, "excluded_allergens": ["AN"]})
    db.products.insert_one(row("almond", contains=["SA"], may=["SH"]))
    assert Gateway(db, None)._allergen_refusals(K, ["almond"]) == {"almond": ("SA", "SH")}
