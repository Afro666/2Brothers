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


@pytest.mark.parametrize("text", [
    "100 L cream and 50 kg cheese by Monday",
    "100 l kermaa ja 50 kg juustoa maanantaiksi",
    "20 kg butter & 10 kg sugar tomorrow",
    "20 kg butter, 10 kg sugar and 5 L milk by Friday",
    "5 kg coffee + 40 L milk by Monday",
])
def test_two_products_in_one_request_are_refused(text):
    """Live on 2026-11-14: "100 L cream and 50 kg cheese" was read as 100 L of "cream and
    cheese" and answered with a cleaning product. One request names one product."""
    with pytest.raises(ParseError, match="one product per request"):
        parse_request(text, FRI)


@pytest.mark.parametrize("text,qty,unit", [
    ("200 L milk in 1 l cartons by Monday", D(200), "L"),      # a pack size, not a second product
    ("200 L milk in 1,5 l bottles by Monday", D(200), "L"),    # the comma of a decimal number
    ("30 kg salt and pepper mix by Monday", D(30), "KG"),      # "and" with one quantity
    ("40 kg macaroni and cheese by Monday", D(40), "KG"),
    ("50 kg flour, 25 kg sacks by Monday", D(50), "KG"),       # a pack size after a comma
    ("200 L milk, 1 l cartons by Monday", D(200), "L"),
    ("100 L milk and 1 l cartons by Monday", D(100), "L"),     # a pack size after "and"
    ("100 l maitoa ja 1 l tölkkejä maanantaiksi", D(100), "L"),
])
def test_one_quantity_or_a_pack_size_is_still_one_product(text, qty, unit):
    r = parse_request(text, FRI)
    assert (r.quantity, r.unit) == (qty, unit)


def test_finnish_comma_is_a_decimal_mark():
    assert parse_request("1,500 kg voita perjantaiksi", FRI).quantity == D("1.5")
    assert parse_request("1,000 L lactose-free milk by Monday", FRI).quantity == D(1000)


@pytest.mark.parametrize("text,qty,unit,when", [
    ("1 000 litraa laktoositonta maitoa maanantaiksi", D(1000), "L", MON),
    ("100 litraa kermaa torstaiksi", D(100), "L", date(2026, 11, 19)),
    ("400 kpl hedelmäjogurttia perjantaiksi", D(400), "ST", date(2026, 11, 20)),
])
def test_finnish_example_chips_parse(text, qty, unit, when):
    """The exact Finnish chip texts in web/src/i18n/fi/orders.ts (#1222) go to the gateway."""
    r = parse_request(text, FRI)
    assert (r.quantity, r.unit, r.requested_date, r.language) == (qty, unit, when, "fi")


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


@pytest.mark.parametrize("text,when", [
    ("50 kg cheese by Monday", MON),
    ("1000 l laktoositonta maitoa maanantaiksi", MON),
    ("500 L oat drink by Friday", date(2026, 11, 20)),
    ("20 kg perunoita huomenna", date(2026, 11, 14)),
    ("50 kg carrots on 16.11.", MON),
    ("115 kg hanger steak 2026-11-20", date(2026, 11, 20)),
    ("12 kpl ruisleipää 17 nov", date(2026, 11, 17)),
    ("200 L lactose-free milk", None),             # no day named: the form's date stays
    ("40 kg Edam cheese", None),
    ("monday", MON),                               # no quantity: the day is still read
    ("20 kg sun dried tomatoes", None),            # #1016: a short weekday form in a product name is no day
    ("20 kg sun dried tomatoes by mon", MON),      # ... and after a day word it is one
    ("50 kg cheese for fri", date(2026, 11, 20)),
    ("50 kg cheese next Mon", MON),
    ("30 kg sat fat free spread", None),
    ("20 kg tomatoes sunday", date(2026, 11, 15)), # a full name is always a day
    ("20 kg sun dried tomatoes perjantaiksi", date(2026, 11, 20)),  # Finnish full name: a day
    ("20 kg sun kuivattuja tomaatteja sunnuntaina", date(2026, 11, 15)),
    ("2 kg sun kuivattuja tomaatteja", None),      # Finnish text, a short form in the name: no day
    ("", None),
])
def test_named_day_reads_the_day_a_text_names(text, when):
    from gateway.parse import named_day
    assert named_day(text, FRI) == when


def test_named_day_agrees_with_the_parser():
    from gateway.parse import named_day
    for text in ("1,000 L lactose-free milk by Monday", "2,5 kg voita keskiviikkona", "500 g parmesan tomorrow"):
        assert named_day(text, FRI) == parse_request(text, FRI).requested_date


def test_named_day_refuses_a_date_that_does_not_exist():
    from gateway.parse import named_day
    with pytest.raises(ParseError):
        named_day("20 kg butter 31.2.", FRI)


def test_a_short_weekday_in_a_product_name_keeps_the_form_date_and_the_word():
    """#1016: "sun" in "sun dried tomatoes" moved the order to Sunday and left the query."""
    from gateway.parse import product_words
    picked = date(2026, 11, 20)
    parsed = parse_request("20 kg sun dried tomatoes", FRI, default_day=picked)
    assert parsed.requested_date == picked and parsed.query == "sun dried tomatoes"
    assert product_words("20 kg sun dried tomatoes") == "sun dried tomatoes"
    by_day = parse_request("20 kg sun dried tomatoes by sun", FRI, default_day=picked)
    assert by_day.requested_date == date(2026, 11, 15) and by_day.query == "sun dried tomatoes"
    assert parse_request("50 kg cheese by Monday", FRI, default_day=picked).requested_date == MON
    fi = parse_request("20 kg sun kuivattuja tomaatteja", FRI, default_day=picked)
    assert fi.requested_date == picked                               # Finnish text: the form date stays
    assert parse_request("20 kg tomaatteja maanantaiksi", FRI, default_day=picked).requested_date == MON
    with pytest.raises(ParseError, match="no delivery day"):       # no form date: never a guess
        parse_request("20 kg sun dried tomatoes", FRI)


def test_the_buyer_payload_keeps_the_form_date_for_a_short_weekday_in_a_name():
    from gateway.buyer_worker import buyer_payload
    kept = buyer_payload("k", {"text": "20 kg sun dried tomatoes", "requested_date": "2026-11-20"})
    assert kept["requested_date"] == "2026-11-20"
    moved = buyer_payload("k", {"text": "50 kg cheese by Monday", "requested_date": "2026-11-20"})
    assert moved["requested_date"] != "2026-11-20"
