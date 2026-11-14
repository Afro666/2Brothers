"""S06: just under free delivery, pad only with lines the engine wants (docs/plan.md)."""

from decimal import Decimal as D

from engine import Wanted, pad_to_free_delivery

MILK = Wanted("469549", "Valio semi skimmed milk 1 l ESL", D(30), "ST", D("1.00"))
CARROT = Wanted("460708", "Carrot 10 kg sack", D(1), "ST", D("11.18"))


def test_s06_smallest_wanted_line_that_closes_the_gap():
    pad = pad_to_free_delivery(D("271.40"), threshold=D(300), fee=D(25), wanted=[CARROT, MILK])
    assert [(a.product_id, a.quantity) for a in pad.add] == [("469549", D(30))]
    assert pad.total == D("301.40") and pad.saves_fee == D(25)
    assert pad.reason_codes == ("MOV_PADDED",)
    assert "saves the 25.00 EUR delivery fee" in pad.why


def test_already_over_the_threshold_adds_nothing():
    pad = pad_to_free_delivery(D("310.00"), threshold=D(300), fee=D(25), wanted=[MILK])
    assert pad.add == () and pad.saves_fee == 0 and pad.reason_codes == ()

    assert pad.why == "Free delivery already reached."


def test_no_fee_under_the_threshold_adds_nothing():
    pad = pad_to_free_delivery(D("271.40"), threshold=D(300), fee=D(0), wanted=[MILK])
    assert pad.add == () and pad.saves_fee == 0 and pad.reason_codes == ()
    assert pad.why == "No delivery fee: no padding."


def test_nothing_wanted_fits_pay_the_fee():
    pad = pad_to_free_delivery(D("271.40"), threshold=D(300), fee=D(25), wanted=[CARROT])
    assert pad.add == () and pad.total == D("271.40")
    assert pad.why == "Nothing the engine wants closes the 28.60 EUR gap: pay the 25.00 EUR delivery fee."


def test_lines_that_would_spoil_are_never_used():
    spoils = Wanted("469549", "milk", D(30), "ST", D("1.00"), keeps_until_used=False)
    assert pad_to_free_delivery(D("271.40"), threshold=D(300), fee=D(25), wanted=[spoils]).add == ()


def test_several_small_lines_close_the_gap_smallest_first():
    a = Wanted("a", "a", D(1), "ST", D("10.00"))
    b = Wanted("b", "b", D(1), "ST", D("12.00"))
    c = Wanted("c", "c", D(1), "ST", D("15.00"))
    pad = pad_to_free_delivery(D("280.00"), threshold=D(300), fee=D(25), wanted=[c, b, a])
    assert [x.product_id for x in pad.add] == ["a", "b"]       # 22.00 >= 20.00 gap
    assert pad.total == D("302.00")


def test_padding_whose_holding_cost_is_above_the_fee_is_not_worth_it():
    # The goods are wanted anyway; what padding costs is holding them earlier (docs/plan.md).
    big = Wanted("big", "big", D(1), "ST", D("80.00"), holding_cost=D("30.00"))
    pad = pad_to_free_delivery(D("280.00"), threshold=D(300), fee=D(25), wanted=[big])
    assert pad.add == ()
    assert "holding" in pad.why


def test_unknown_terms_never_pad():
    pad = pad_to_free_delivery(D("271.40"), threshold=None, fee=None, wanted=[MILK])
    assert pad.add == () and pad.reason_codes == ()
