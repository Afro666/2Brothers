"""The fallback parser's choice of products to price (gateway/candidates.py)."""

from gateway.candidates import CANDIDATES, pick_candidates


def row(pid, value, unit, category="10400"):
    content = None if unit is None else {"value": value, "unit": unit}
    return {"product_id": pid, "net_content": content, "category": category}


# The top of the live search for "lactose free milk" on 2026-11-14, in its order.
LIVE = [
    row("466215", 0.15, "KG", "52201"),    # Brunberg lactose free milk chocolate
    row("474627", 0.25, "KG", "52202"),
    row("461474", 0.42, "KG", "21320"),    # bread flour mix
    row("464179", 10.0, "L"),              # Arla 10 L lactose free milk drink
    row("465905", 2.98, "KG", "41763"),    # cake base
    row("473625", 0.283, "L", "10404"),    # condensed milk
    row("462703", 10.0, "L", "10401"),     # cooking cream
    row("469330", 1.0, "L"),
    row("463380", 1.0, "L"),
    row("463335", 1.0, "L"),               # Valio Eila 3 % milk drink 1 l
]


def test_litre_request_drops_weight_products_and_puts_milk_first():
    ids = pick_candidates(LIVE, "L")
    assert ids[:4] == ["464179", "469330", "463380", "463335"]      # the milk category
    assert ids[4:] == ["473625", "462703"]                           # other litre products after
    assert not {"466215", "474627", "461474", "465905"} & set(ids)   # nothing measured in kg


def test_kilogram_request_keeps_weight_products_only():
    assert pick_candidates(LIVE, "KG") == ["466215", "474627", "461474", "465905"]


def test_unknown_net_content_is_kept_after_the_known_matches():
    rows = [row("A", None, None), row("B", 1.0, "L"), row("C", 0.5, "KG")]
    assert pick_candidates(rows, "L") == ["B", "A"]


def test_a_request_in_pieces_keeps_the_search_order():
    assert pick_candidates(LIVE, "ST", cap=3) == ["466215", "474627", "461474"]


def test_cap_and_empty():
    many = [row(str(n), 1.0, "L") for n in range(50)]
    assert len(pick_candidates(many, "L")) == CANDIDATES
    assert pick_candidates([], "L") == []


def test_rows_without_category_do_not_crash():
    rows = [{"product_id": "X", "net_content": {"value": 1, "unit": "l"}}, {"product_id": "Y"}]
    assert pick_candidates(rows, "L") == ["X", "Y"]
