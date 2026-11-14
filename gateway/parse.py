"""Deterministic request parser (#276): the fallback when the Nemotron Buyer is down.

"1,000 L lactose-free milk by Monday"  /  "1000 l laktoositonta maitoa maanantaiksi"
-> {"quantity": "1000", "unit": "L", "query": "lactose free milk", "requested_date": ...}

English and Finnish. No model: what it cannot read it refuses with a reason, it never guesses.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
import re

UNITS = {
    "l": "L", "ltr": "L", "litre": "L", "litres": "L", "liter": "L", "liters": "L",
    "litra": "L", "litraa": "L", "litran": "L",
    "kg": "KG", "kilo": "KG", "kilos": "KG", "kiloa": "KG", "kilogram": "KG", "kilograms": "KG",
    "g": "G", "gram": "G", "grams": "G", "grammaa": "G",
    "pcs": "ST", "pc": "ST", "piece": "ST", "pieces": "ST", "kpl": "ST", "kappaletta": "ST",
    "st": "ST",
}

WEEKDAYS = {
    # English
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6,
    "mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6,
    # Finnish: base, "by" (-ksi) and "on" (-na) forms
    "maanantai": 0, "maanantaiksi": 0, "maanantaina": 0,
    "tiistai": 1, "tiistaiksi": 1, "tiistaina": 1,
    "keskiviikko": 2, "keskiviikoksi": 2, "keskiviikkona": 2,
    "torstai": 3, "torstaiksi": 3, "torstaina": 3,
    "perjantai": 4, "perjantaiksi": 4, "perjantaina": 4,
    "lauantai": 5, "lauantaiksi": 5, "lauantaina": 5,
    "sunnuntai": 6, "sunnuntaiksi": 6, "sunnuntaina": 6,
}
RELATIVE = {"today": 0, "tänään": 0, "tomorrow": 1, "huomenna": 1, "huomiseksi": 1,
            "ylihuomenna": 2}
MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8,
          "sep": 9, "oct": 10, "nov": 11, "dec": 12}

# Finnish partitive / inflected food words -> the base form the catalog names use.
FI_STEMS = {
    "maitoa": "maito", "maitojuomaa": "maitojuoma", "laktoositonta": "laktoositon",
    "kermaa": "kerma", "voita": "voi", "juustoa": "juusto", "jogurttia": "jogurtti",
    "kananmunia": "kananmuna", "munia": "kananmuna", "perunoita": "peruna", "perunaa": "peruna",
    "porkkanoita": "porkkana", "porkkanaa": "porkkana", "sipulia": "sipuli", "jauhelihaa": "jauheliha",
    "kanaa": "kana", "lohta": "lohi", "riisiä": "riisi", "pastaa": "pasta", "kauraa": "kaura",
    "leipää": "leipä", "ruisleipää": "ruisleipä", "kahvia": "kahvi", "tomaatteja": "tomaatti",
    "kurkkua": "kurkku", "salaattia": "salaatti", "jauhoja": "jauho", "öljyä": "öljy",
    "luomu": "luomu", "rasvatonta": "rasvaton", "kevyttä": "kevyt",
}
FILLER = {
    "i", "we", "need", "needs", "want", "please", "of", "for", "by", "on", "the", "a", "an", "some",
    "order", "get", "buy", "until", "before", "next", "this", "deliver", "delivery", "to", "us",
    "tarvitsen", "tarvitsemme", "tilaa", "haluan", "haluamme", "ole", "hyvä", "kiitos", "mennessä",
    "ensi", "tällä", "viikolla", "ja",
}


class ParseError(ValueError):
    """The request cannot be read without guessing; the message says what is missing."""


@dataclass(frozen=True)
class ParsedRequest:
    quantity: Decimal
    unit: str            # L, KG or ST (grams are converted to KG)
    query: str           # product words for the catalog search
    requested_date: date
    language: str        # "fi" or "en"

    def as_need(self) -> dict:
        return {"quantity": f"{self.quantity.normalize():f}", "unit": self.unit,
                "requested_date": self.requested_date.isoformat(), "query": self.query}


_NUM = r"(\d{1,3}(?:[ ,. ]\d{3})+|\d+(?:[.,]\d+)?)"
_QTY = re.compile(_NUM + r"\s*(" + "|".join(sorted(UNITS, key=len, reverse=True)) + r")\b", re.I)
# A pack word right after a quantity makes it a pack size, not a second product:
# "50 kg flour, 25 kg sacks", "100 L milk and 1 l cartons".
_PACK = (r"(?:(?:carton|bottle|sack|bag|pack|packet|box|can|tin|jar|tub|bucket|crate|case"
         r"|keg|canister|pouch|container)(?:e?s)?"
         r"|(?:pussi|pullo|tölk|säk|purk|rasi|laatik|pakkau|kanist|ämpär|astia)\w*)\b")
# Two products in one text: a second quantity after "and", "ja", "sekä", "och", "&", "+"
# or a comma (not the comma of a decimal number, "1,5 l"), that is not a pack size.
_SECOND = re.compile(r"(?:\b(?:and|ja|sekä|och)\b|[&+]|(?<!\d),)\s*" + _QTY.pattern
                     + r"(?!\s*" + _PACK + ")", re.I)
_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_DMY = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})?")
_DMON = re.compile(r"\b(\d{1,2})\s+(" + "|".join(MONTHS) + r")[a-z]*\b", re.I)


def _number(raw: str, language: str = "en") -> Decimal:
    s = raw.replace(" ", " ").strip()
    groups = r"[ .]" if language == "fi" else r"[ ,.]"   # Finnish: comma is the decimal mark
    if re.fullmatch(r"\d{1,3}(?:" + groups + r"\d{3})+", s):
        s = re.sub(groups, "", s)                 # 1,000 / 1 000 / 1.000 = thousands
    else:
        s = s.replace(",", ".")                   # 1,5 = one and a half
    try:
        value = Decimal(s)
    except InvalidOperation:
        raise ParseError(f"cannot read the number {raw!r}") from None
    if value <= 0:
        raise ParseError("the quantity must be positive")
    return value


def _next_weekday(today: date, weekday: int) -> date:
    days = (weekday - today.weekday()) % 7
    return today + timedelta(days=days or 7)       # "by Monday" on a Monday means next Monday


ONE_PRODUCT = ("one product per request: this text asks for more than one "
               "(ask for each product in its own request)")


def asks_for_two(text: str) -> bool:
    """True when the text joins two quantities with "and" (or "ja", "&", "+", a comma):
    "100 L cream and 50 kg cheese". Two products are two requests: the first one alone
    would be a guess, and the words of both together find neither. A pack size is not a
    second product ("200 L milk in 1 l cartons")."""
    low = (text or "")[:500].lower()
    m = _QTY.search(low)
    return bool(m and _SECOND.search(low, m.end()))


def product_words(text: str) -> str:
    """The product words of a request, as `parse_request` finds them, for a text that may
    name no quantity or no day (the Buyer's stored need, #974). It never raises."""
    low = (text or "")[:500].lower()
    m = _QTY.search(low)
    rest = low[:m.start()] + " " + low[m.end():] if m else low
    for pattern in (_ISO, _DMY, _DMON):
        d = pattern.search(rest)
        if d:
            rest = rest[:d.start()] + " " + rest[d.end():]
            break
    kept = [FI_STEMS.get(w, w) for w in re.findall(r"[a-zåäö%-]+", rest)
            if w not in WEEKDAYS and w not in RELATIVE and w not in FILLER]
    return " ".join(" ".join(kept).replace("-", " ").split())


def _written_date(rest: str, today: date) -> tuple[date | None, str]:
    """A date written with digits ("2026-11-20", "16.11.", "17 nov") and the text without
    it; `(None, rest)` when there is none. A date that does not exist is a ParseError."""
    for pattern in (_ISO, _DMY, _DMON):
        d = pattern.search(rest)
        if not d:
            continue
        try:
            if pattern is _ISO:
                when = date(int(d.group(1)), int(d.group(2)), int(d.group(3)))
            elif pattern is _DMY:
                year = int(d.group(3)) if d.group(3) else today.year
                when = date(year, int(d.group(2)), int(d.group(1)))
            else:
                when = date(today.year, MONTHS[d.group(2)[:3].lower()], int(d.group(1)))
        except ValueError:
            raise ParseError(f"not a real date: {d.group(0)!r}") from None
        if pattern is not _ISO and when < today:
            when = when.replace(year=when.year + 1)
        return when, rest[:d.start()] + " " + rest[d.end():]
    return None, rest


def named_day(text: str, today: date) -> date | None:
    """The delivery day a text names, read as `parse_request` reads it, or None when it
    names none. For a text that may have no quantity (the Buyer path: a day in the text
    wins over the date picked in a form). A date that does not exist is a ParseError."""
    low = (text or "")[:500].lower()
    m = _QTY.search(low)
    rest = low[:m.start()] + " " + low[m.end():] if m else low
    when, rest = _written_date(rest, today)
    if when is not None:
        return when
    for w in re.findall(r"[a-zåäö%-]+", rest):
        if w in WEEKDAYS:
            return _next_weekday(today, WEEKDAYS[w])
        if w in RELATIVE:
            return today + timedelta(days=RELATIVE[w])
    return None


def parse_request(text: str, today: date, default_day: date | None = None) -> ParsedRequest:
    """`default_day`: the delivery day when the text names none (the day picked in a form)."""
    if not text or not text.strip():
        raise ParseError("the request is empty")
    if len(text) > 500:
        raise ParseError("the request is too long (500 characters at most)")
    low = text.lower()
    language = "fi" if re.search(r"[äö]|ksi\b|aa\b|tta\b|tarvi|maito|kpl", low) else "en"

    m = _QTY.search(low)
    if not m:
        raise ParseError("no quantity with a unit (for example '1000 L' or '20 kg')")
    quantity, unit = _number(m.group(1), language), UNITS[m.group(2).lower()]
    if unit == "G":
        quantity, unit = quantity / 1000, "KG"
    rest = low[:m.start()] + " " + low[m.end():]
    if asks_for_two(text):
        raise ParseError(ONE_PRODUCT)

    when, rest = _written_date(rest, today)
    words = re.findall(r"[a-zåäö%-]+", rest)
    kept = []
    for w in words:
        if when is None and w in WEEKDAYS:
            when = _next_weekday(today, WEEKDAYS[w])
            continue
        if when is None and w in RELATIVE:
            when = today + timedelta(days=RELATIVE[w])
            continue
        if w in WEEKDAYS or w in RELATIVE or w in FILLER:
            continue
        kept.append(FI_STEMS.get(w, w))
    when = when or default_day
    if when is None:
        raise ParseError("no delivery day (for example 'by Monday', 'maanantaiksi' or '16.11.')")
    if when < today:
        raise ParseError("the delivery day is in the past")
    query = " ".join(" ".join(kept).replace("-", " ").split())
    if not query:
        raise ParseError("no product named")
    return ParsedRequest(quantity, unit, query, when, language)
