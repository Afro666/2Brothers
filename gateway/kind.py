"""Which catalog categories are the kind of product a request names.

Why. Live on 2026-11-14 "50 kg cheese" was answered with a cheese sauce and chili cheese
nuggets, "100 L cream" with coconut cream, and a Finnish request for lactose-free milk was
filled up with sweetened condensed milk. The word search ranks every name that holds the
word, and the catalog has 439 names with "cheese" in 51 categories: the 50 best hits held
no plain cheese at all. The catalog has a category code on every product and no category
names, so the kind is read from the catalog itself.

The rule, for the product word of a request (its last word: "milk" in "lactose free milk"):

1. A product carries the word when its English or Finnish name has it as a word, or as
   the end of a compound ("kuohukerma" carries "kerma", "juustokastike" does not carry
   "juusto": there the word only describes a sauce). Swedish names are not read: "pasta"
   is also the Swedish word for a paste.
2. A category is of that kind when at least `MIN_PRODUCTS` of its products carry the word
   and they are at least `MIN_SHARE` of the category.
3. Not when the word is glued to one other word in most of them (`MAX_TIED`), and the
   request does not have that word: "ice cream", "condensed milk", "milk powder", "cream
   cheese" and "peanut butter" are other kinds than "cream", "milk" and "butter".

No category passes for a word the catalog does not name that way ("breast", "type"): then
there is no kind and nothing changes. The answer only orders or narrows what a search
found; it never adds a product, and the engine still sizes every line.
"""

from __future__ import annotations

from collections import Counter
import re

MIN_PRODUCTS = 5
MIN_SHARE = 0.5
MAX_TIED = 0.75
CACHE_SIZE = 512        # answers kept per process; a request text is a stranger's input
_LANGUAGES = ("en", "fi")
_WORD = re.compile(r"[a-zåäöé]+")
# Words that end the product phrase of a request: what follows describes a use or a wish.
_CUT = re.compile(r"\b(?:for|with|without|in|from|not|to)\b|,(?!\d)|[(;:]")   # not the comma of "1,000"
# Size and pack words are never the word a product word is glued to.
_SIZE_WORDS = {"g", "kg", "l", "dl", "cl", "ml", "x", "pcs", "kpl", "st", "e", "n", "ca", "ap"}


def _norm(word: str) -> str:
    """Plural to singular, the same way for a request and a name: "potatoes" -> "potato"."""
    if len(word) > 4 and word.endswith("oes"):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _tokens(name) -> list[str]:
    return [_norm(w) for w in _WORD.findall(str(name or "").lower())]


def product_phrase(text: str) -> str:
    """The product words of a request text, in the base form the catalog names use
    ("1000 l laktoositonta maitoa maanantaiksi" -> "laktoositon maito"); "" when none.

    They are what `gateway.parse.product_words` keeps, up to the first word that starts a
    use or a wish ("cheese for pizza", "oat drink, barista type")."""
    from gateway.parse import product_words
    low = (text or "")[:500].lower()
    cut = _CUT.search(low)
    words = product_words(low[:cut.start()] if cut else low)
    if not words and cut:
        words = product_words(low)
    return " ".join(w for w in words.split() if _WORD.fullmatch(w))


def product_word(text: str) -> tuple[str, set[str]]:
    """`(the product word, all product words)` of a request text, plural to singular;
    ("", set()) when none. The product word is the last word of `product_phrase`."""
    words = [_norm(w) for w in product_phrase(text).split()]
    return (words[-1], set(words)) if words else ("", set())


class Kinds:
    """The catalog's names and categories, read once, and the kind rule over them."""

    def __init__(self, rows):
        """`rows`: dicts with `category` and `names` (catalog products, not a kitchen's own)."""
        self._products: list[tuple[str, list[list[str]]]] = []
        self._size: Counter = Counter()
        for row in rows:
            category = row.get("category")
            if not category:
                continue
            names = row.get("names") or {}
            self._products.append((str(category), [_tokens(names.get(lang)) for lang in _LANGUAGES]))
            self._size[str(category)] += 1
        self._cache: dict[tuple[str, frozenset], tuple[str, ...]] = {}

    @classmethod
    def from_db(cls, db) -> "Kinds":
        return cls(db.products.find({"source": {"$ne": "own"}}, {"category": 1, "names": 1}))

    def categories(self, text: str) -> tuple[str, ...]:
        """The categories that are the kind of product `text` asks for, largest first.
        Empty when the catalog does not show one: the caller then changes nothing."""
        word, said = product_word(text)
        if len(word) < 3:
            return ()
        key = (word, frozenset(said))
        if key not in self._cache:
            if len(self._cache) >= CACHE_SIZE:
                self._cache.clear()
            self._cache[key] = self._categories(word, said)
        return self._cache[key]

    def _categories(self, word: str, said: set[str]) -> tuple[str, ...]:
        carrying: Counter = Counter()
        glued: dict[str, Counter] = {}
        for category, names in self._products:
            near = _neighbours(names, word)
            if near is None:
                continue
            carrying[category] += 1
            glued.setdefault(category, Counter()).update(near - said)
        kinds = []
        for category, n in carrying.items():
            if n < MIN_PRODUCTS or n < MIN_SHARE * self._size[category]:
                continue
            tied = max(glued[category].values(), default=0)
            if tied > MAX_TIED * n:
                continue
            kinds.append((n, category))
        return tuple(category for n, category in sorted(kinds, key=lambda k: (-k[0], k[1])))


def _neighbours(names: list[list[str]], word: str) -> set[str] | None:
    """None when no name carries `word`. Otherwise the words it is glued to in the first
    name that carries it: the word before, the word after, or the front of the compound."""
    for tokens in names:
        for i, token in enumerate(tokens):
            if token == word:
                near = set()
                if i > 0:
                    near.add(tokens[i - 1])
                if i + 1 < len(tokens):
                    near.add(tokens[i + 1])
                return {w for w in near if len(w) > 2 and w not in _SIZE_WORDS}
            if len(token) > len(word) + 1 and token.endswith(word):
                return {token[:-len(word)]}
    return None


def kind_first(rows: list[dict], categories) -> tuple[list[dict], list[dict]]:
    """`(rows of the kind, the other rows)`, each in the order given."""
    wanted = set(categories)
    return ([r for r in rows if str(r.get("category")) in wanted],
            [r for r in rows if str(r.get("category")) not in wanted])
