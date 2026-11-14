"""Product names on proposal and order lines (#1130).

Live on 14 Nov the approval card showed "Option A: 698 ST 463380": the lines carried only
`product_id`. Every line kind and each excluded entry now carries `product_name`,
`product_name_fi` and `brand` (string or null, never invented), read in one query.
"""

from gateway import product_names
from gateway.tests.test_gateway_app import AGENT, HUMAN, K, env, milk  # noqa: F401 (fixture)

FIELDS = ("product_name", "product_name_fi", "brand")


def name_rows(db):
    db.products.update_one({"_id": "462775"}, {"$set": {
        "names": {"en": "Arla milk 1 L lactose free", "fi": "Arla maito 1 l laktoositon"}, "brand": "Arla"}})
    db.products.update_one({"_id": "463335"}, {"$set": {"names": {}}})    # nothing known


def every_line(p):
    """(where, line) for every line kind a proposal answer has."""
    out = [("lines", ln) for ln in p["lines"]]
    out += [("blocks", ln) for b in p["blocks"] for ln in b["lines"]]
    out += [("substitute_options", ln) for o in p["substitute_options"] for ln in o["lines"]]
    out += [("alternative", ln) for ln in (p.get("alternative") or {}).get("lines") or []]
    part = p.get("partial_fill") or {}
    out += [("partial_fill.now", ln) for ln in (part.get("now") or {}).get("lines") or []]
    out += [("partial_fill.rest", ln) for r in part.get("rest") or [] for ln in r["lines"]]
    out += [("excluded", e) for e in p["excluded"]]
    return out


def test_every_line_kind_carries_the_names_or_null(env):  # noqa: F811
    client, _, db = env
    name_rows(db)
    p = milk(client, quantity="1000")
    lines = every_line(p)
    kinds = {where for where, _ in lines}
    assert {"lines", "blocks", "substitute_options", "partial_fill.now"} <= kinds
    for where, ln in lines:
        assert set(FIELDS) <= ln.keys(), where
        if ln["product_id"] == "462775":
            assert (ln["product_name"], ln["product_name_fi"], ln["brand"]) == (
                "Arla milk 1 L lactose free", "Arla maito 1 l laktoositon", "Arla"), where
        elif ln["product_id"] == "463335":
            assert (ln["product_name"], ln["product_name_fi"], ln["brand"]) == (None, None, None), where
    # The same on a read and in the list.
    again = client.get(f"{K}/proposals/{p['proposal_id']}", headers=AGENT).json()
    assert every_line(again) == lines
    listed = client.get(f"{K}/proposals", headers=AGENT).json()
    listed = listed["proposals"] if isinstance(listed, dict) else listed
    assert every_line(next(x for x in listed if x["proposal_id"] == p["proposal_id"])) == lines


def test_an_excluded_product_carries_its_name_and_the_reason_starts_with_it(env):  # noqa: F811
    client, _, db = env
    db.kitchen_settings.insert_one({"_id": "demo-kitchen", "excluded_allergens": ["milk"]})
    db.products.update_one({"_id": "463335"}, {"$set": {
        "allergen_data_known": True, "allergens": {"contains": ["AM"], "may_contain": [], "undeclared": []}}})
    p = milk(client, quantity="100")
    excluded = next(e for e in p["excluded"] if e["product_id"] == "463335")
    assert excluded["product_name"] == "milk 463335"
    assert excluded["reason"].startswith("ALLERGEN_RULE")          # the entry's own reason is unchanged
    reasons = [r for r in p["mandate"]["reasons"] if "ALLERGEN_RULE" in r]
    assert reasons and all(r.startswith("milk 463335 (463335): ALLERGEN_RULE") for r in reasons)
    assert not any(r.startswith("463335:") for r in p["mandate"]["reasons"])


def test_a_reason_for_an_unknown_name_keeps_the_bare_code():
    found = {"1": {"product_name": None, "product_name_fi": None, "brand": None}}
    assert product_names.named_reason("1: too dear", found) == "1: too dear"
    assert product_names.named_reason("2: too dear", found) == "2: too dear"
    assert product_names.named_reason("Valio must confirm stock for: x.", {}) == "Valio must confirm stock for: x."
    known = {"463203": {"product_name": "Arla milk", "product_name_fi": None, "brand": None}}
    assert product_names.named_reason("463203: confirmed in stock, but 7.54 EUR per L", known) == (
        "Arla milk (463203): confirmed in stock, but 7.54 EUR per L")


def test_alternative_and_partial_rest_lines_are_named():
    found = {"A": {"product_name": "Milk A", "product_name_fi": "Maito A", "brand": "Valio"}}
    answer = {"lines": [], "excluded": [], "blocks": [], "substitute_options": [],
              "alternative": {"total_ex_vat": "1.00", "lines": [{"product_id": "A"}, {"product_id": "B"}]},
              "partial_fill": {"now": {"lines": []}, "rest": [{"kind": "LATER", "lines": [{"product_id": "A"}]}]},
              "mandate": {"reasons": ["A: x", "B: y"]}}
    out = product_names.name_proposal(answer, found)
    assert out["alternative"]["lines"] == [
        {"product_id": "A", "product_name": "Milk A", "product_name_fi": "Maito A", "brand": "Valio"},
        {"product_id": "B", "product_name": None, "product_name_fi": None, "brand": None}]
    assert out["partial_fill"]["rest"][0]["lines"][0]["product_name"] == "Milk A"
    assert out["mandate"]["reasons"] == ["Milk A (A): x", "B: y"]
    assert product_names.proposal_ids(answer) == {"A", "B"}
    assert answer["alternative"]["lines"][0] == {"product_id": "A"}       # the input is not changed


def test_names_are_read_in_one_query_per_proposal(env, monkeypatch):  # noqa: F811
    client, _, db = env
    p = milk(client, quantity="1000")
    milk(client, key="p2", quantity="51")
    calls = []
    real = product_names.labels

    def counted(*args, **kwargs):
        calls.append(args[1])
        return real(*args, **kwargs)
    monkeypatch.setattr(product_names, "labels", counted)
    client.get(f"{K}/proposals/{p['proposal_id']}", headers=AGENT)
    assert len(calls) == 1
    assert set(calls[0]) >= {"462775", "463335"}
    calls.clear()
    client.get(f"{K}/proposals", headers=AGENT)
    assert len(calls) == 2                        # one per proposal, never one per line


def test_another_kitchens_own_product_name_is_never_shown(env):  # noqa: F811
    _, _, db = env
    db.products.insert_one({"_id": "own-9", "kitchen_id": "k99", "names": {"en": "not ours"}})
    db.products.insert_one({"_id": "own-1", "kitchen_id": "demo-kitchen", "names": {"en": "our stock"}})
    found = product_names.labels(db, ["own-9", "own-1", "462775"], "demo-kitchen")
    assert set(found) == {"own-1", "462775"}
    assert found["own-1"]["product_name"] == "our stock"


def test_order_lines_carry_names_computed_at_read_time(env, monkeypatch):  # noqa: F811
    client, _, db = env
    name_rows(db)
    p = milk(client, quantity="51")
    r = client.post(f"{K}/proposals/{p['proposal_id']}/approve", headers=HUMAN,
                    json={"expected_total": p["expected_total"], "idempotency_key": "a1"})
    assert r.status_code == 200, r.text
    assert r.json()["lines"][0]["product_name"] == "Arla milk 1 L lactose free"
    stored = db.orders.find_one({})
    assert not any("product_name" in ln for ln in stored["lines"])      # never stored: read time only
    order = client.get(f"{K}/orders/{r.json()['order_id']}", headers=AGENT).json()
    line = next(ln for ln in order["lines"] if ln["product_id"] == "462775")
    assert (line["product_name"], line["product_name_fi"], line["brand"]) == (
        "Arla milk 1 L lactose free", "Arla maito 1 l laktoositon", "Arla")
    calls = []
    real = product_names.labels
    monkeypatch.setattr(product_names, "labels", lambda *a, **k: calls.append(a) or real(*a, **k))
    listed = client.get(f"{K}/orders", headers=AGENT).json()["orders"]
    assert listed[0]["lines"] == order["lines"]
    assert len(calls) == 1                         # one query for the whole list


def test_the_audit_summary_never_names_another_kitchens_own_product(env):  # noqa: F811
    _, _, db = env
    from gateway.service import Gateway
    db.products.insert_one({"_id": "own-9", "kitchen_id": "k99", "names": {"en": "not ours"}})
    sim = {"lines": [{"product_id": "own-9", "quantity": "1", "unit": "ST", "total": "1.00", "why": "x"}],
           "excluded": [], "expected_total": "1.24", "total_ex_vat": "1.00", "vat": "0.24"}
    request = {"product_ids": ["own-9"], "quantity": "1", "unit": "ST", "requested_date": "2026-11-16"}
    gw = Gateway(db, None)
    assert "not ours" not in gw._summary(request, sim, "demo-kitchen")["text"]
    assert "not ours" in gw._summary(request, sim, "k99")["text"]       # its own kitchen sees it
