"""#975: a request in pieces. The rows copy the units of the live catalog (2026-11-14)."""

from decimal import Decimal as D

import pytest

from engine import pack_info
from engine.packs import PackDataError


def row(pid, sales, base, units):
    return {"id": pid, "salesUnit": sales, "baseUnit": base, "allowedLotSize": 0.01,
            "units": [{"unitId": u, "sizeInBaseUnits": float(n)} for u, n in units]}


CUP_CASE = row("463805", "KI", "ST", [("KI", 20), ("ST", 1)])              # fruity yoghurt 150 g, case of 20
CUP = row("467274", "PRK", "PRK", [("PRK", 1), ("KRS", 160), ("KI", 20)])  # yoghurt 150 g, sold by the cup
CASE_ONLY = row("472710", "KI", "KI", [("KI", 1)])                         # 24x chocolate bar, sold by the case
BY_WEIGHT = row("470619", "KG", "KG", [("KG", 1)])                         # Edam loaf


@pytest.mark.parametrize("unit", ["PCS", "ST"])
def test_a_request_in_pieces_uses_the_piece_count_of_the_pack(unit):
    case = pack_info(CUP_CASE, measure=unit)
    assert (case.sales_unit, case.measure, case.size, case.derived) == ("KI", unit, D(20), False)
    cup = pack_info(CUP, measure=unit)                       # a cup is a piece, whatever Valio calls it
    assert (cup.sales_unit, cup.measure, cup.size) == ("PRK", unit, D(1))


@pytest.mark.parametrize("unit", ["PCS", "ST"])
def test_a_pack_with_no_piece_count_says_so_and_names_a_unit_that_works(unit):
    with pytest.raises(PackDataError) as case:
        pack_info(CASE_ONLY, price=D("20.00"), comparison_price=D("22.83"), comparison_unit="KG", measure=unit)
    assert str(case.value) == ("the catalog does not say how many pieces one KI holds; "
                               "ask for this product in KG")
    with pytest.raises(PackDataError) as weight:
        pack_info(BY_WEIGHT, price=D("8.00"), comparison_price=D("8.00"), comparison_unit="KG", measure=unit)
    assert str(weight.value) == "this product is sold by weight, not by the piece; ask for it in KG"
    with pytest.raises(PackDataError) as bare:
        pack_info(CASE_ONLY, measure=unit)                    # no comparison price either
    assert str(bare.value).endswith("ask for this product in KG or L")


def test_litres_and_kilograms_are_read_as_before():
    milk = row("462921", "KI", "ST", [("KI", 5), ("ST", 1)])
    got = pack_info(milk, price=D("10.97"), comparison_price=D("2.19"), comparison_unit="L", measure="L")
    assert (got.measure, got.size, got.derived) == ("L", D(5), True)
    with pytest.raises(PackDataError, match="no way to convert L to KI"):
        pack_info(milk, measure="L")
