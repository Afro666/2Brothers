"""One request with several products (#1375): read every quantity, split, and check a split.

"20 L oat drink, 5 kg butter and 40 rolls for Monday" asks for three products. Nemotron may
split it (agent/split.py); this module is the plain code around the model:

- `quantities`: every quantity the person wrote, a number with a unit ("20 L") or a plain
  count before a word ("40 rolls" = 40 pieces). A pack size is not a quantity of its own
  ("200 L milk in 1 l cartons"), and neither is a count of people ("for 40 guests") or a
  date ("17 nov").
- `check`: a model's split passes only when it has one need per quantity in the text, each
  need's quantity and unit is one of them (each used once), and its product words are words
  that follow that quantity in the text. The quantities that go on are the ones read from
  the text: the model never sets one.
- `rules_split`: the split with the model off: the text is cut before each quantity.
- `days`: the delivery days a text names; one request has one delivery day.
No model, no database. What it cannot read it refuses with a reason; it never guesses.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
import re

from gateway.parse import (_PACK, _QTY, MONTHS, RELATIVE, UNITS, WEEKDAYS, ParseError,
                           _number, _written_date, language, product_words)

MIN_NEEDS, MAX_NEEDS = 2, 30
MAX_NEED_TEXT = 120
# A count of people or days is not a product: "for 40 guests", "40 hengelle".
_PEOPLE = {"people", "persons", "person", "guests", "guest", "covers", "cover", "portions", "portion",
           "diners", "pax", "hengelle", "henkeä", "hengen", "henkilöä", "henkilölle", "annosta",
           "annokselle", "vierasta", "vieraalle", "days", "day", "weeks", "week", "päivää", "viikkoa"}
_MONTHS = {*MONTHS, "sept", *("january february march april june july august september october november "
                               "december tammikuuta helmikuuta maaliskuuta huhtikuuta toukokuuta kesäkuuta "
                               "heinäkuuta elokuuta syyskuuta lokakuuta marraskuuta joulukuuta").split()}
_COUNT = re.compile(r"(?<![\d.,:/-])(\d{1,5})\s+([a-zåäö][a-zåäö-]*)", re.I)
_SEP = re.compile(r"(?:\s*(?:\b(?:and|ja|sekä|och|plus)\b|[&+,;]|\n)\s*)+$", re.I)
_WORD = re.compile(r"[a-zåäö]+")
_CLOCK_AFTER = {"am", "pm", "h"}
_CLOCK_BEFORE = re.compile(r"\b(?:klo|kello|at)\s*$", re.I)
_PERCENT = re.compile(r"\d+(?:[.,]\d+)?\s*%")

ONE_DAY = "one delivery day per request: this text names more than one (ask for each day in its own request)"


@dataclass(frozen=True)
class Quantity:
    value: Decimal       # in `unit`; grams already read as kilos
    unit: str            # L, KG or ST
    start: int
    end: int


def _norm(value: Decimal, unit: str) -> tuple[Decimal, str]:
    return (value / 1000, "KG") if unit == "G" else (value, unit)


def quantities(text: str) -> list[Quantity]:
    """Every quantity in the text, in the order written. The language (and so the decimal
    mark) is read once, from the whole text. ParseError for a number that cannot be read."""
    low = (text or "")[:500].lower()
    lang = language(low)
    found: list[Quantity] = []
    every = list(_QTY.finditer(low))
    for m in every:
        if re.match(r"\s*" + _PACK, low[m.end():]):
            continue                                    # "1 l cartons": a pack size
        if re.search(r"\bin\s*$", low[:m.start()]):
            continue                                    # "milk in 1 l": a pack size
        value, unit = _norm(_number(m.group(1), lang), UNITS[m.group(2).lower()])
        found.append(Quantity(value, unit, m.start(), m.end()))
    taken = [(m.start(), m.end()) for m in every]
    for m in _COUNT.finditer(low):
        word = m.group(2)
        if any(s <= m.start() < e for s, e in taken) or word in UNITS or word in _PEOPLE:
            continue
        if word in WEEKDAYS or word in RELATIVE or word in _MONTHS:
            continue                                    # "17 nov": a date
        if (word in _CLOCK_AFTER or (word == "o" and low.startswith("'clock", m.end(2)))
                or _CLOCK_BEFORE.search(low[:m.start()])):
            continue                                    # "10 am", "klo 10": a clock time
        if re.match(_PACK, word):
            continue                                    # "2 cartons": a pack count, not a product
        found.append(Quantity(_number(m.group(1), lang), "ST", m.start(), m.start() + len(m.group(1))))
    return sorted(found, key=lambda q: q.start)


def several(text: str) -> bool:
    """True when the text asks for two or more products: two quantities, and a separator
    ("and", "ja", "&", "+", a comma) before a later one. A pack size or a count of people
    is not a product. Every other text goes to the single-product path as before."""
    try:
        found = quantities(text)
    except ParseError:
        return False
    low = (text or "")[:500].lower()
    return len(found) >= 2 and any(_SEP.search(low[:q.start]) for q in found[1:])


def days(text: str, today: date) -> set[date]:
    """Every delivery day the text names (written dates, weekdays, today/tomorrow).
    ParseError for a date that does not exist."""
    rest = (text or "")[:500].lower()
    out: set[date] = set()
    while True:
        when, rest = _written_date(rest, today)
        if when is None:
            break
        out.add(when)
    for word in _WORD.findall(rest):
        if word in WEEKDAYS:
            ahead = (WEEKDAYS[word] - today.weekday()) % 7
            out.add(today + timedelta(days=ahead or 7))
        elif word in RELATIVE:
            out.add(today + timedelta(days=RELATIVE[word]))
    return out


def _segments(low: str, found: list[Quantity]) -> list[str]:
    """Per quantity, the words after it up to the next quantity, separators cut off."""
    out = []
    for i, q in enumerate(found):
        end = found[i + 1].start if i + 1 < len(found) else len(low)
        out.append(_SEP.sub("", low[q.end:end]))
    return out


def rules_split(text: str) -> list[dict]:
    """The needs of a text with the model off: one per quantity, the product words after it
    up to the next quantity. ParseError when a part cannot be read without guessing."""
    low = (text or "")[:500].lower()
    found = quantities(text)
    if not MIN_NEEDS <= len(found) <= MAX_NEEDS:
        raise ParseError(f"a request names {MIN_NEEDS} to {MAX_NEEDS} products")
    if product_words(low[:found[0].start]):
        raise ParseError("the product words must come after each quantity ('20 L oat drink, 5 kg butter')")
    needs = []
    for q, segment in zip(found, _segments(low, found)):
        words = product_words(re.sub(r"\d", " ", segment))
        if not words:
            raise ParseError(f"no product named after {low[q.start:q.end].strip()!r}")
        needs.append({"text": words[:MAX_NEED_TEXT], "quantity": f"{q.value.normalize():f}", "unit": q.unit})
    return needs


def _holds(words: set[str], word: str) -> bool:
    """The word is in the text, or a form of it ("kaurajuoma" for "kaurajuomaa")."""
    return word in words or (len(word) >= 3 and any(
        w.startswith(word) or (len(w) >= 4 and word.startswith(w)) for w in words))


def check(text: str, split) -> list[dict]:
    """The model's split, checked against the person's own words. Returns the needs with the
    quantities read from the text. ParseError when the split adds, drops or changes a
    quantity, or when a need's words are not words that follow its own quantity (so two
    quantities cannot be swapped: "100 L cheese, 50 kg cream" for "100 L cream, 50 kg cheese")."""
    if not isinstance(split, list):
        raise ParseError("the split is not a list")
    found = quantities(text)
    if len(split) != len(found):
        raise ParseError("the split does not have one product per quantity in the text")
    if not MIN_NEEDS <= len(found) <= MAX_NEEDS:
        raise ParseError(f"a request names {MIN_NEEDS} to {MAX_NEEDS} products")
    low = (text or "")[:500].lower()
    lang = language(low)
    own = [set(_WORD.findall(segment)) for segment in _segments(low, found)]
    unused = list(range(len(found)))
    out = []
    for need in split:
        if not isinstance(need, dict) or not all(isinstance(need.get(k), str) for k in ("text", "quantity", "unit")):
            raise ParseError("a part of the split has no text, quantity or unit")
        unit = need["unit"].strip().upper()
        if unit not in ("L", "KG", "G", "ST"):
            raise ParseError(f"unit {need['unit']!r} is not L, KG, G or ST")
        value, unit = _norm(_number(need["quantity"].strip(), lang), unit)
        name = " ".join(need["text"].strip().lower().split())
        bare = _PERCENT.sub(" ", name)               # "3 % milk": a fat level is a product word
        named = _WORD.findall(bare)
        if not name or len(name) > MAX_NEED_TEXT or re.search(r"\d", bare) or not named:
            raise ParseError("a product in the split has no words, or has a number in it")
        match = next((i for i in unused if found[i].value == value and found[i].unit == unit
                      and all(_holds(own[i], w) for w in named)), None)
        if match is None:
            raise ParseError(f"{need['quantity']} {need['unit']} {need['text']!r} is not a quantity "
                             "of the text with those product words after it")
        unused.remove(match)
        q = found[match]
        out.append({"text": name, "quantity": f"{q.value.normalize():f}", "unit": q.unit})
    return out
