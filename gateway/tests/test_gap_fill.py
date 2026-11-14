"""S02 live (#731): a short order's gap is filled by weight with a substitute sold in another unit."""
from copy import deepcopy

from gateway.scenarios import MON, _Gateway, _row

BREAD, ROLLS = "465138", "462300"


def _product(g, pid, name, sales, price, cmp, available):
    """Bread in cases (KI) or rolls in bags (BAG); prices and stock as docs/scenarios.md S02."""
    g.db.products.insert_one({"_id": pid, "names": {"en": name}, "allergen_data_known": True,
                              "allergens": {"contains": [], "may_contain": [], "undeclared": []},
                              "raw": _row(pid, sales, sales, [(sales, 1.0)], lot=1)})
    row = deepcopy(next(p for p in g.price["products"] if p["productId"] == "463335"))
    row.update(productId=pid, comparisonUnit="KG")
    row["catalogPrice"]["value"], row["comparisonPrice"]["value"] = price, cmp
    g.price["products"].append(row)
    stock = deepcopy(next(p for p in g.avail["products"] if p["productId"] == "463335"))
    stock.update(productId=pid)
    stock["scheduleLines"][0]["availableAmount"] = available
    g.avail["products"].append(stock)


def _gateway():
    g = _Gateway()
    _product(g, BREAD, "PH7 gluten free oat bread", "KI", 64.27, 7.65, 16)     # 8.4 kg a case
    _product(g, ROLLS, "Elovena gluten free oat-carrot rolls 400 g", "BAG", 3.58, 8.95, 9999999999.0)
    return g


def _ask(g, ids, key):
    r = g.client.post(g.k + "/proposals", headers=g.agent, json={
        "product_ids": ids, "quantity": "20", "unit": "KI", "requested_date": MON.isoformat(),
        "idempotency_key": key, "text": "20 cases of gluten free bread by Monday"})
    r.raise_for_status()
    return r.json()


def test_the_gap_is_filled_by_weight_and_needs_a_yes():
    p = _ask(_gateway(), [BREAD, ROLLS], "s02-gap")
    lines = {ln["product_id"]: ln for ln in p["lines"]}
    assert (lines[BREAD]["quantity"], lines[BREAD]["unit"]) == ("16", "KI")
    assert (lines[ROLLS]["quantity"], lines[ROLLS]["unit"]) == ("84", "BAG")   # 4 cases x 8.4 kg / 0.4 kg
    assert lines[ROLLS]["total"] == "300.72"
    assert "SUBSTITUTE_NEEDS_OK" in lines[ROLLS]["reason_codes"]
    assert "SUBSTITUTE_NEEDS_OK" not in lines[BREAD]["reason_codes"]
    assert {"PARTIAL_STOCK", "SUBSTITUTE_NEEDS_OK"} <= set(p["mandate"]["reason_codes"])
    assert ROLLS not in {e["product_id"] for e in p["excluded"]}


def test_without_a_substitute_the_order_stays_short():
    p = _ask(_gateway(), [BREAD], "s02-short")
    assert [(ln["product_id"], ln["quantity"]) for ln in p["lines"]] == [(BREAD, "16")]
    assert "SUBSTITUTE_NEEDS_OK" not in p["mandate"]["reason_codes"]
