"""The kind of product a request names, read from the catalog (gateway/kind.py), and the
shortlists that use it: the Buyer's search (`Gateway.tool_search`) and the parser path."""

from fastapi.testclient import TestClient
import mongomock
import pytest

from gateway.candidates import of_kind
from gateway.kind import Kinds, product_phrase, product_word
from gateway.app import create_app
from gateway.service import Gateway
from gateway.tests.test_gateway_app import AGENT, K, NOW, FakeValio
from gateway.valio_client import ValioClient


def product(pid, category, en, fi=None, unit="KG", value=1.0, score=None):
    row = {"product_id": pid, "category": category, "names": {"en": en, "fi": fi or en},
           "net_content": {"value": value, "unit": unit}, "source": "valio", "supplier_id": "valio_aimo"}
    if score is not None:
        row["score"] = score
    return row


def many(prefix, category, names, **kwargs):
    return [product(f"{prefix}{n}", category, en, fi, **kwargs) for n, (en, fi) in enumerate(names)]


# A small catalog with the shapes of the real one (names as on the live site, 2026-11-14).
CHEESE = many("ch", "10603", [
    ("Valio grated cheese 2 kg", "Valio juustoraaste 2 kg"), ("Arla Edam cheese 1 kg", "Arla Edam juusto 1 kg"),
    ("Valio Oltermanni cheese 900 g", "Valio Oltermanni juusto 900 g"), ("Gouda cheese cube 1kg", "Gouda juustokuutio 1kg"),
    ("Emmental cheese slices 1 kg", "Emmental juusto viipale 1 kg"), ("Mozzarella shred 2 kg", "Mozzarellaraaste 2 kg")])
SNACKS = many("sn", "41755", [
    ("McCain Chili Cheese Nuggets 1 kg", None), ("Salud Blue Cheese Bites 1kg", None), ("Fish fingers 1 kg", None),
    ("Spring rolls 1 kg", None), ("Onion rings 1 kg", None), ("Potato croquettes 1 kg", None),
    ("Mozzarella sticks 1 kg", None), ("Falafel 1 kg", None), ("Corn dogs 1 kg", None), ("Hash browns 1 kg", None),
    ("Mac and Cheese Bites 1 kg", None), ("Jalapeno poppers 1 kg", None)])
SAUCE = many("sa", "21994", [
    ("Santa Maria 970G Habanero Cheese Sauce", "Santa Maria 970G Habanero juustokastike"),
    ("Old El Paso 320g Cheese Salsa", None), ("Taco sauce 800 g", None), ("Salsa dip 1 kg", None),
    ("Guacamole dip 1 kg", None), ("Nacho dip 1 kg", None), ("Chili sauce 1 kg", None), ("BBQ sauce 1 kg", None),
    ("Garlic sauce 1 kg", None), ("Burger sauce 1 kg", None), ("Curry sauce 1 kg", None)])
MILK = many("mi", "10400", [
    ("Valio skimmed milk 1 l", "Valio rasvaton maito 1 l"), ("Arla whole milk 10 L", "Arla täysmaito 10 L"),
    ("Valio coffee milk 1 l lactose free UHT", "Valio kahvimaito 1 l laktoositon UHT"),
    ("Arla Café milk 1 L UHT lactose free", "Arla Café maito 1 L UHT laktoositon"),
    ("Valio semi skimmed milk 1 l lactose free", "Valio kevytmaito 1 l laktoositon"),
    ("Valio Eila milk drink 1 l lactose free", "Valio Eila maitojuoma 1 l laktoositon")], unit="L")
CONDENSED = many("co", "10404", [
    ("Dovgan Lactose free Condensed milk, sweetened 283 ml", "Dovgan Laktoositon Kondensoitu maito, makeutettu 283 ml"),
    ("Dovgan Condensed milk, sweetened 370 ml", "Dovgan Kondensoitu maito, makeutettu 370 ml"),
    ("Condensed milk caramelized 1 kg", "Kondensoitu maito karamellisoitu 1 kg"),
    ("Sweet condensed milk 1000g", "Makea kondensoitu maito 1000g"),
    ("Condensed milk 397 g", "Kondensoitu maito 397 g"), ("Condensed milk tube 170 g", "Kondensoitu maito tuubi 170 g")], unit="L")
CREAM = many("cr", "10401", [
    ("Valio whipping cream 1 l", "Valio kuohukerma 1 l"), ("Valio cooking cream 1 l", "Valio ruokakerma 1 l"),
    ("Arla coffee cream 1 l", "Arla kahvikerma 1 l"), ("Valio whipping cream 2 dl", "Valio vispikerma 2 dl"),
    ("Arla Pro Cooking cream 10% 1 L", "Arla Pro ruokakerma 10% 1 L")], unit="L")
ICE = many("ic", "41820", [
    (f"GelatoLAB 5L ice cream {taste}", f"GelatoLAB 5L jäätelö {taste}")
    for taste in ("Vanilla", "Whisky Cream", "Cherry", "Lemon", "Mango", "Coffee", "Mint", "Pear")], unit="L")
CLEANER = many("cl", "63114", [
    ("Cif Cleaner Cream Pink 500 ml", "Cif cream pink puhdistusaine 500 ml"),
    ("Cif Lemon Cream cleaner 500 ml", "Cif Cream Lemon Puhdistusaine 500 ml"),
    ("Oven cleaner 1 l", "Uuninpuhdistusaine 1 l"), ("Floor cleaner 5 l", "Lattianpuhdistusaine 5 l"),
    ("Glass cleaner 1 l", "Lasinpuhdistusaine 1 l"), ("Grill cleaner 1 l", "Grillinpuhdistusaine 1 l")], unit="L")
BUTTER = many("bu", "10500", [
    ("Valio butter 500 g salted", "Valio voi 500 g"), ("Valio butter 4x5 kg unsalted", "Valio voi 4x5 kg"),
    ("Porlammin Clarified butter 1,8kg", "Porlammin Kirkastettu voi 1,8kg"), ("Juustoportti Butter 200 g", "Juustoportti Kirnuvoi 200 g"),
    ("Valio organic butter 200 g", "Valio Luomu voi 200 g")])
PEANUT = many("pb", "21453", [
    ("PCD 500G PEANUT BUTTER", "PCD 500G MAAPÄHKINÄVOI"), ("Organic Peanut Butter Smooth 230g", "Luomu Maapähkinävoi Smooth 230g"),
    ("Creamy peanut butter 350 g", "Maapähkinävoi 350 g"), ("Crunchy peanut butter 350 g", "Maapähkinävoi crunchy 350 g"),
    ("Peanut butter 1 kg", "Maapähkinävoi 1 kg"), ("Almond spread 170g", "Mantelitahna 170g")])
CATALOG = CHEESE + SNACKS + SAUCE + MILK + CONDENSED + CREAM + ICE + CLEANER + BUTTER + PEANUT
KINDS = Kinds(CATALOG)


@pytest.mark.parametrize("text,word", [
    ("50 kg cheese by Monday", "cheese"),
    ("1,000 L lactose-free milk by Monday", "milk"),
    ("1000 l laktoositonta maitoa maanantaiksi", "maito"),
    ("25 kg grated cheese for pizza, not Edam", "cheese"),      # what follows "for" is a use
    ("50 L oat drink, barista type", "drink"),
    ("1,000 L lactose-free milk for the cafe", "milk"),         # the comma of a number is not a cut
    ("100 kg potatoes by Monday", "potato"),                    # plural to singular
    ("by Monday", ""),
])
def test_the_product_word_is_the_last_word_of_the_product_phrase(text, word):
    assert product_word(text)[0] == word


def test_the_product_phrase_is_in_the_base_form_of_the_catalog_names():
    assert product_phrase("1000 l laktoositonta maitoa maanantaiksi") == "laktoositon maito"
    assert product_phrase("25 kg grated cheese for pizza, not Edam") == "grated cheese"
    assert product_phrase("by Monday") == ""


@pytest.mark.parametrize("text,categories", [
    ("50 kg cheese by Monday", ("10603",)),             # not the sauce, not the nuggets
    ("100 L cream by Monday", ("10401",)),              # not ice cream, not the cleaner
    ("100 l kermaa tiistaiksi", ("10401",)),            # Finnish: the end of a compound
    ("200 L milk by Thursday", ("10400",)),             # not condensed milk
    ("1000 l laktoositonta maitoa maanantaiksi", ("10400",)),
    ("20 kg butter for Wednesday", ("10500",)),         # not peanut butter
    ("15 kg peanut butter", ("10500", "21453")),        # the request has the word it is glued to
    ("30 L ice cream", ("41820", "10401")),
    ("30 kg chicken breast by Tuesday", ()),            # the catalog shows no kind: nothing changes
    ("20 kg xy", ()),
    ("", ()),
])
def test_the_kind_of_a_request_is_read_from_the_catalog(text, categories):
    assert KINDS.categories(text) == categories


def test_own_products_and_rows_without_a_category_do_not_count():
    class Products:
        def find(self, query, projection):
            assert query == {"source": {"$ne": "own"}}
            return CHEESE + [{"names": {"en": "cheese with no category"}}]

    class Db:
        products = Products()

    assert Kinds.from_db(Db()).categories("50 kg cheese") == ("10603",)


def scored(rows, score):
    return [{**r, "score": score} for r in rows]


def test_of_kind_keeps_the_kind_and_drops_the_rest():
    rows = scored(SAUCE[:1] + SNACKS[:1], 240) + scored(CHEESE[:2], 215)
    assert [r["product_id"] for r in of_kind(rows, ("10603",), "KG")] == ["ch0", "ch1"]


def test_of_kind_orders_by_score_and_keeps_the_search_order_of_equal_scores():
    rows = scored(CHEESE[:1], 210) + scored(CHEESE[1:3], 220) + scored(SAUCE[:1], 240)
    assert [r["product_id"] for r in of_kind(rows, ("10603",), "KG")] == ["ch1", "ch2", "ch0"]


def test_of_kind_changes_nothing_without_a_kind_or_without_a_hit_of_the_kind():
    rows = scored(SAUCE[:2], 240)
    assert of_kind(rows, (), "KG") == rows
    assert of_kind(rows, ("10603",), "KG") == rows


def test_of_kind_changes_nothing_when_the_kind_is_not_sold_in_the_asked_measure():
    """"30 kg cream": cream is sold in litres. The rule does not see what is meant."""
    rows = scored(CREAM[:2], 220) + scored(SAUCE[:1], 215)
    assert of_kind(rows, ("10401",), "KG") == rows
    assert [r["product_id"] for r in of_kind(rows, ("10401",), "L")] == ["cr0", "cr1"]
    assert [r["product_id"] for r in of_kind(rows, ("10401",), "ST")] == ["cr0", "cr1"]   # pieces: no measure


def test_hits_with_only_some_of_the_search_words_are_dropped_first():
    """"coconut milk": plain milk holds one of the two words. It is not offered, and with
    no hit of the kind left, the coconut milk stays."""
    coconut = scored([product("cm1", "10406", "Coconut milk 1 l", unit="L")], 215)
    rows = coconut + scored(MILK[:3], 6)
    assert of_kind(rows, ("10400",), "L") == coconut


def test_rows_without_a_score_keep_their_order():
    rows = SAUCE[:1] + CHEESE[:2]            # an injected search gives no score
    assert [r["product_id"] for r in of_kind(rows, ("10603",), "KG")] == ["ch0", "ch1"]


# ---- the Buyer's search and the parser path, over the catalog above -----------------

def word_search(db, query, filters, limit, kitchen_id=None):
    """A stand-in for the live word search: names that hold a query word, the names with
    the fewest words first (as Atlas scores them), cut at `limit`; it knows `category`."""
    words = query.lower().replace("-", " ").split()
    hits = [dict(r, score=200 + 40 - len(r["names"]["en"].split()))
            for r in CATALOG
            if any(w in (r["names"]["en"] + " " + r["names"]["fi"]).lower().split() for w in words)
            and (filters.get("category") is None or r["category"] == filters["category"])]
    return sorted(hits, key=lambda r: -r["score"])[:limit]


@pytest.fixture()
def gateway(monkeypatch):
    monkeypatch.setenv("GATEWAY_HUMAN_TOKEN", "human-test-token")
    monkeypatch.setenv("GATEWAY_AGENT_TOKEN", "agent-test-token")
    db = mongomock.MongoClient(tz_aware=True)["test"]
    db.products.insert_many([{"_id": r["product_id"], **{k: v for k, v in r.items() if k != "product_id"}}
                             for r in CATALOG])
    valio = ValioClient("test-not-a-real-key", transport=FakeValio().transport, ttl=0, now=lambda: NOW)
    gw = Gateway(db, valio, now=lambda: NOW, search=word_search)
    return TestClient(create_app(gw)), gw


def shortlist(client, text, unit, query, limit=None):
    need = client.post(K + "/needs", headers=AGENT, json={
        "quantity": "50", "unit": unit, "requested_date": "2026-11-16", "text": text}).json()
    body = {"query": query, "filters": {}, "need_id": need["need_id"]}
    if limit:
        body["limit"] = limit
    found = client.post("/tools/search_products", headers=AGENT, json=body)
    assert found.status_code == 200, found.text
    return found.json()


def test_cheese_gets_cheese_not_a_cheese_sauce_or_nuggets(gateway):
    """Live on 2026-11-14: "50 kg cheese by Monday" -> Habanero Cheese Sauce and Chili Cheese
    Nuggets. The 50 best hits of the live word search held no cheese; the cheese category does."""
    client, gw = gateway
    inner = gw._search

    def no_cheese_on_top(db, query, filters, limit, kitchen_id=None):
        rows = inner(db, query, filters, limit, kitchen_id)
        return rows if filters.get("category") is not None else [r for r in rows if r["category"] != "10603"]
    gw._search = no_cheese_on_top
    plain = client.post("/tools/search_products", headers=AGENT, json={"query": "cheese", "filters": {}}).json()
    assert {p["category"] for p in plain["products"]} == {"21994", "41755"}
    found = shortlist(client, "50 kg cheese by Monday", "KG", "cheese")
    assert found["products"] and {p["category"] for p in found["products"]} == {"10603"}
    assert found["measure"] == "KG"


def test_milk_in_finnish_gets_milk_not_condensed_milk(gateway):
    """Live: "1000 l laktoositonta maitoa" was filled up with sweetened condensed milk."""
    client, _ = gateway
    found = shortlist(client, "1000 l laktoositonta maitoa maanantaiksi", "L", "laktoositon maito")
    assert found["products"] and {p["category"] for p in found["products"]} == {"10400"}


def test_cream_gets_cream_not_ice_cream_or_a_cleaner(gateway):
    client, _ = gateway
    found = shortlist(client, "100 L cream by Monday", "L", "cream")
    assert found["products"] and {p["category"] for p in found["products"]} == {"10401"}


def test_the_kind_comes_from_the_persons_words_not_from_the_models_query(gateway):
    client, _ = gateway
    found = shortlist(client, "100 L cream by Monday", "L", "cream cleaner")
    assert {p["category"] for p in found["products"]} == {"10401"}


def test_the_measure_filter_and_the_can_arrive_order_still_run_after_the_kind(gateway):
    client, gw = gateway
    extra = product("ch-litre", "10603", "Liquid cheese 1 l", unit="L")
    CATALOG.append(extra)
    try:
        gw._kinds = None
        found = shortlist(client, "50 kg cheese by Monday", "KG", "cheese")
    finally:
        CATALOG.remove(extra)
    ids = [p["product_id"] for p in found["products"]]
    assert "ch-litre" not in ids and found["measure"] == "KG"
    order = [0 if p["can_arrive"] else (1 if p["can_arrive"] is None else 2) for p in found["products"]]
    assert order == sorted(order)


def test_the_kind_is_searched_with_the_persons_words_when_the_models_query_finds_nothing(gateway):
    """Real model, 2026-11-14: for "20 kg voita keskiviikoksi" the model searched "voita".
    No name has that word; the fuzzy search found white icing, and that was proposed."""
    client, gw = gateway
    inner = gw._search

    def fuzzy(db, query, filters, limit, kitchen_id=None):
        if query == "voita":      # the live search: "voita" is one edit from the Swedish "vita"
            return [] if filters.get("category") else [dict(SAUCE[0], score=201)]
        return inner(db, query, filters, limit, kitchen_id)
    gw._search = fuzzy
    found = shortlist(client, "20 kg voita keskiviikoksi", "KG", "voita")
    assert found["products"] and {p["category"] for p in found["products"]} == {"10500"}


def test_a_need_with_no_text_uses_the_query(gateway):
    """An outside MCP client stores a need with no text and searches "lactose-free milk":
    live on 2026-11-14 the first two hits that could arrive were condensed milk."""
    client, _ = gateway
    found = shortlist(client, "", "L", "lactose free milk")
    assert found["products"] and {p["category"] for p in found["products"]} == {"10400"}


def test_the_answers_kept_in_memory_are_bounded():
    from gateway import kind
    kinds = Kinds(CHEESE)
    for n in range(kind.CACHE_SIZE + 10):
        kinds.categories(f"5 kg word{n}")
    assert len(kinds._cache) <= kind.CACHE_SIZE


def test_a_request_with_no_kind_in_the_catalog_gets_the_search_answer_as_before(gateway):
    client, _ = gateway
    found = shortlist(client, "30 kg nuggets by Monday", "KG", "nuggets")
    assert [p["product_id"] for p in found["products"]] == ["sn0"]


def test_a_search_without_a_need_is_not_narrowed(gateway):
    client, _ = gateway
    plain = client.post("/tools/search_products", headers=AGENT, json={"query": "cheese", "filters": {}}).json()
    assert {"21994", "41755"} <= {p["category"] for p in plain["products"]}


def test_a_failing_kind_search_never_fails_the_search(gateway):
    client, gw = gateway
    inner = gw._search

    def broken(db, query, filters, limit, kitchen_id=None):
        if filters.get("category") is not None:
            raise RuntimeError("search is down")
        return inner(db, query, filters, limit, kitchen_id)
    gw._search = broken
    found = shortlist(client, "50 kg cheese by Monday", "KG", "cheese")
    assert found["products"]


def test_the_parser_path_prices_the_kind_only(gateway):
    """The fallback parser: "100 L cream" must never be priced as a cleaner."""
    _, gw = gateway
    read = gw._from_text("demo-kitchen", {"text": "100 L cream by Monday", "idempotency_key": "k"})
    assert read["product_ids"] and all(pid.startswith("cr") for pid in read["product_ids"])


def test_the_kinds_are_read_again_after_the_ttl(gateway):
    """#1044: a catalog reload is seen by the kind rule without a gateway restart."""
    from datetime import timedelta
    from gateway.service import KINDS_TTL
    _, gw = gateway
    clock = [NOW]
    gw.now = lambda: clock[0]
    gw._of_kind([], "cheese", {}, "50 kg cheese", "KG")
    assert gw._kinds.categories("50 kg cheese") == ("10603",)
    new = many("nc", "10699", [(f"{brand} cheese 1 kg", f"{brand} juusto 1 kg")
                               for brand in ("Alpha", "Bravo", "Delta", "Gamma", "Sigma", "Omega")])
    gw.db.products.insert_many([{"_id": r["product_id"], **{k: v for k, v in r.items() if k != "product_id"}}
                                for r in new])
    clock[0] = NOW + KINDS_TTL - timedelta(seconds=1)
    gw._of_kind([], "cheese", {}, "50 kg cheese", "KG")
    assert gw._kinds.categories("50 kg cheese") == ("10603",)      # still the old snapshot
    clock[0] = NOW + KINDS_TTL
    gw._of_kind([], "cheese", {}, "50 kg cheese", "KG")
    assert "10699" in gw._kinds.categories("50 kg cheese")
