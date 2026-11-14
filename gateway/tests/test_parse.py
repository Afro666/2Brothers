from datetime import date
from decimal import Decimal as D

import pytest

from gateway.parse import ParseError, parse_request

FRI = date(2026, 11, 13)
MON = date(2026, 11, 16)


@pytest.mark.parametrize("text,qty,unit,query,when", [
    ("1,000 L lactose-free milk by Monday", D(1000), "L", "lactose free milk", MON),
    ("I need 1000 litres of lactose free milk by Monday", D(1000), "L", "lactose free milk", MON),
    ("1000 l laktoositonta maitoa maanantaiksi", D(1000), "L", "laktoositon maito", MON),
    ("Tarvitsen 20 kg perunoita huomenna", D(20), "KG", "peruna", date(2026, 11, 14)),
    ("50 kg carrots on 16.11.", D(50), "KG", "carrots", MON),
    ("115 kg hanger steak 2026-11-20", D(115), "KG", "hanger steak", date(2026, 11, 20)),
    ("60 l gluten free oat drink by tuesday please", D(60), "L", "gluten free oat drink", date(2026, 11, 17)),
    ("500 g parmesan tomorrow", D("0.5"), "KG", "parmesan", date(2026, 11, 14)),
    ("1 000 l kermaa perjantaiksi", D(1000), "L", "kerma", date(2026, 11, 20)),
    ("12 kpl ruisleipää 17 nov", D(12), "ST", "ruisleipä", date(2026, 11, 17)),
    ("2,5 kg voita keskiviikkona", D("2.5"), "KG", "voi", date(2026, 11, 18)),
])
def test_phrasings(text, qty, unit, query, when):
    r = parse_request(text, FRI)
    assert (r.quantity, r.unit, r.query, r.requested_date) == (qty, unit, query, when)


def test_same_weekday_means_next_week():
    assert parse_request("10 l milk by friday", FRI).requested_date == date(2026, 11, 20)


def test_language_is_detected():
    assert parse_request("1000 l laktoositonta maitoa maanantaiksi", FRI).language == "fi"
    assert parse_request("1000 L milk by Monday", FRI).language == "en"


@pytest.mark.parametrize("text,why", [
    ("lactose free milk by Monday", "quantity"),
    ("1000 L lactose free milk", "delivery day"),
    ("1000 L by Monday", "product"),
    ("1000 L milk 2026-11-01", "past"),
    ("1000 L milk 31.02.2027", "real date"),
    ("", "empty"),
    ("0 L milk by Monday", "positive"),
])
def test_refuses_instead_of_guessing(text, why):
    with pytest.raises(ParseError, match=why):
        parse_request(text, FRI)
