"""The plain code around the model's split (#1375): which texts name several products, the
split with the model off, and the check that the model never sets a quantity."""

from datetime import date
from decimal import Decimal as D

import pytest

from gateway.parse import ParseError, asks_for_two
from gateway.split import check, days, quantities, rules_split, several

SAT = date(2026, 11, 14)


@pytest.mark.parametrize("text", [
    "20 L oat drink, 5 kg butter and 40 rolls for Monday",
    "100 L cream and 50 kg cheese by Monday",
    "100 l kermaa ja 50 kg juustoa maanantaiksi",
    "40 rolls and 5 kg butter tomorrow",
    "5 kg coffee + 40 L milk by Monday",
    "1,5 l maitoa ja 2 kg voita huomenna",
])
def test_texts_with_several_products(text):
    assert several(text)


@pytest.mark.parametrize("text", [
    "1,000 L lactose-free milk by Monday",
    "200 L milk in 1 l cartons by Monday",
    "200 L milk in 1,5 l bottles by Monday",
    "200 L milk, 1 l cartons by Monday",
    "50 kg flour, 25 kg sacks by Monday",
    "30 kg salt and pepper mix by Monday",
    "40 kg macaroni and cheese by Monday",
    "100 L milk for 40 people by Monday",
    "100 L milk, 40 guests, by 17 nov",
    "20 kg butter by 16.11.",
    "60 l milk tomorrow",
])
def test_one_product_texts_stay_on_the_single_path(text):
    assert not several(text)


def test_the_single_path_detector_is_unchanged_for_one_product():
    # Every text the old detector let through still goes the single way.
    for text in ("1,000 L lactose-free milk by Monday", "200 L milk in 1 l cartons by Monday",
                 "50 kg flour, 25 kg sacks by Monday", "100 L milk for 40 people by Monday"):
        assert not asks_for_two(text) and not several(text)


def test_quantities_read_units_counts_and_grams():
    got = [(q.value, q.unit) for q in quantities("20 L oat drink, 500 g butter and 40 rolls")]
    assert got == [(D(20), "L"), (D("0.5"), "KG"), (D(40), "ST")]
    fi = [(q.value, q.unit) for q in quantities("1,5 l maitoa ja 2 kg voita")]
    assert fi == [(D("1.5"), "L"), (D(2), "KG")]           # Finnish: the comma is the decimal mark


def test_rules_split():
    assert rules_split("20 L oat drink, 5 kg butter and 40 rolls for Monday") == [
        {"text": "oat drink", "quantity": "20", "unit": "L"},
        {"text": "butter", "quantity": "5", "unit": "KG"},
        {"text": "rolls", "quantity": "40", "unit": "ST"}]
    assert rules_split("100 l kermaa ja 50 kg juustoa maanantaiksi") == [
        {"text": "kerma", "quantity": "100", "unit": "L"},
        {"text": "juusto", "quantity": "50", "unit": "KG"}]


@pytest.mark.parametrize("text,why", [
    ("20 L and 5 kg butter by Monday", "no product named"),
    ("oat drink 20 L and butter 5 kg", "after each quantity"),
    (", ".join(f"{n + 1} kg thing{chr(97 + n % 26)}" for n in range(31)), "2 to 30"),
])
def test_rules_split_refuses_what_it_cannot_read(text, why):
    with pytest.raises(ParseError, match=why):
        rules_split(text)


def test_check_keeps_the_quantities_of_the_text():
    text = "20 L oat drink, 1,5 kg butter and 40 rolls for Monday"
    got = check(text, [{"text": "oat drink", "quantity": "20", "unit": "L"},
                       {"text": "butter", "quantity": "1.5", "unit": "KG"},
                       {"text": "rolls", "quantity": "40", "unit": "ST"}])
    assert [n["quantity"] for n in got] == ["20", "1.5", "40"]
    assert check("2 kg voita ja 20 l kaurajuomaa", [{"text": "voi", "quantity": "2", "unit": "KG"},
                                                    {"text": "kaurajuoma", "quantity": "20", "unit": "L"}])


@pytest.mark.parametrize("split", [
    [{"text": "cream", "quantity": "100", "unit": "L"}],                                     # dropped
    [{"text": "cream", "quantity": "100", "unit": "L"}, {"text": "cheese", "quantity": "50", "unit": "KG"},
     {"text": "milk", "quantity": "1", "unit": "L"}],                                          # added
    [{"text": "cream", "quantity": "100", "unit": "L"}, {"text": "cheese", "quantity": "5", "unit": "KG"}],
    [{"text": "cheese", "quantity": "100", "unit": "L"}, {"text": "cream", "quantity": "50", "unit": "KG"}],
    [{"text": "cream", "quantity": "100", "unit": "L"}, {"text": "cheese", "quantity": "50", "unit": "L"}],
    [{"text": "cream", "quantity": "100", "unit": "L"}, {"text": "gouda", "quantity": "50", "unit": "KG"}],
    [{"text": "cream 100", "quantity": "100", "unit": "L"}, {"text": "cheese", "quantity": "50", "unit": "KG"}],
    [{"text": "cream", "quantity": "100", "unit": "L"}, {"text": "cheese", "quantity": "50", "unit": "BOX"}],
    "not a list",
])
def test_check_refuses_a_split_that_invents_drops_adds_or_swaps(split):
    with pytest.raises(ParseError):
        check("100 L cream and 50 kg cheese by Monday", split)


def test_days():
    assert days("milk for Monday and bread for Tuesday", SAT) == {date(2026, 11, 16), date(2026, 11, 17)}
    assert days("20 L milk 16.11. and 5 kg butter 17.11.", SAT) == {date(2026, 11, 16), date(2026, 11, 17)}
    assert days("20 L milk and 5 kg butter by Monday", SAT) == {date(2026, 11, 16)}
    assert days("20 L milk and 5 kg butter", SAT) == set()
