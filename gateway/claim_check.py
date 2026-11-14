"""Check the numbers in a sentence a model wrote against the facts it was given (#1176; #1173
reuses it).

A model may choose words; it may never bring a number of its own. Each sentence names the
facts it is about, and every number in its text must be one of those facts' values, read in
the sentence's language. A number word for a quantity ("two", "kaksi", "hundred") is refused,
because it cannot be checked. Nothing here repairs text: a failed check drops it.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re

SPACES = "   "
# Finnish: a space groups thousands (1 000), a comma or a point is the decimal mark (12,5).
# English: a comma or a space groups thousands (1,000), a point is the decimal mark (12.5).
_GROUPS = {"fi": f"[{SPACES}]", "en": f"[,{SPACES}]"}
_DECIMAL = {"fi": "[,.]", "en": r"\."}

NUMBER_WORDS = {
    "en": ("one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven",
           "twelve", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety",
           "hundred", "hundreds", "thousand", "thousands", "million", "dozen", "dozens", "half",
           "couple", "single", "double", "twice", "triple"),
    "fi": ("yksi", "yhden", "yhdelle", "yhdeltä", "kaksi", "kahden", "kahdelle", "kahdelta", "kolme",
           "kolmen", "kolmelle", "neljä", "neljän", "neljälle", "viisi", "viiden", "viidelle", "kuusi",
           "kuuden", "kuudelle", "seitsemän", "seitsemälle", "kahdeksan", "kahdeksalle", "yhdeksän",
           "yhdeksälle", "kymmenen", "kymmenelle", "sata", "sadan", "satoja", "tuhat", "tuhannen",
           "tuhansia", "miljoona", "puoli", "puolet", "tusina", "tusinaa", "pari", "kaksinkertainen"),
}


def _pattern(lang: str) -> re.Pattern:
    g, d = _GROUPS[lang], _DECIMAL[lang]
    return re.compile(rf"(?<![\w.,])(\d{{1,3}}(?:{g}\d{{3}})+|\d+)(?:{d}(\d+))?(?![\d])")


_PATTERNS = {lang: _pattern(lang) for lang in _GROUPS}


def value(raw, lang: str = "en") -> Decimal | None:
    """One number as written (`"1 000"`, `"12,5"`, `698`), or None when it is not one."""
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, Decimal)):
        return Decimal(raw).normalize()
    if not isinstance(raw, str):
        return None
    found = numbers_in(raw.strip(), lang)
    return found[0] if len(found) == 1 and _PATTERNS[lang].fullmatch(raw.strip()) else None


def numbers_in(text: str, lang: str = "en") -> list[Decimal]:
    """Every number written in `text`, in order, read in the sentence's language."""
    out = []
    for m in _PATTERNS[lang].finditer(text):
        whole = re.sub(_GROUPS[lang], "", m.group(1))
        try:
            out.append(Decimal(whole + ("." + m.group(2) if m.group(2) else "")).normalize())
        except InvalidOperation:
            continue
    return out


def number_word(text: str, lang: str = "en") -> str | None:
    """The first number word in `text` (in either language), or None."""
    words = re.findall(r"[^\W\d_]+", text.casefold())
    banned = set(NUMBER_WORDS["en"]) | set(NUMBER_WORDS[lang])
    return next((w for w in words if w in banned), None)


def strip_names(text: str, names) -> str:
    """`text` without the exact strings in `names` (product names), so a "1 L" inside a
    product name is not read as a quantity."""
    for s in names:
        if s:
            text = re.sub(re.escape(s), " ", text, flags=re.IGNORECASE)
    return text


def check_sentence(text: str, declared, allowed, lang: str = "en", *, strip=()) -> str | None:
    """None when the sentence holds only allowed numbers, else the rule it broke.

    `declared` is the sentence's own list of the numbers it uses; `allowed` the values of
    the facts it names. `strip` are product names taken out first (`strip_names`)."""
    text = strip_names(text, strip)
    if number_word(text, lang):
        return "NUMBER_WORD"
    allowed = {Decimal(str(a)).normalize() for a in allowed if a is not None}
    written = numbers_in(text, lang)
    if any(n not in allowed for n in written):
        return "NUMBER_NOT_IN_ROW"
    listed = [value(d, lang) for d in declared] if isinstance(declared, list) else None
    if listed is None or None in listed or set(listed) != set(written):
        return "NUMBERS_LIST_MISMATCH"
    return None
