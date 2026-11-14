"""A demo supplier (#1604) in a real proposal: its own block, its price, VAT, unknown stock."""

import pytest

pytest.importorskip("mongomock")
pytest.importorskip("fastapi")

from demo.suppliers import load  # noqa: E402
from gateway.tests.test_gateway_app import AGENT, K, env  # noqa: E402, F401


def test_a_demo_supplier_gives_a_priced_block_with_vat_and_unknown_stock(env):
    client, _, db = env
    load(db)
    r = client.post(K + "/proposals", headers=AGENT, json={
        "product_ids": ["own-demo-salmon-fillet"], "quantity": "6", "unit": "KG",
        "requested_date": "2026-11-18", "idempotency_key": "fish-1"})
    assert r.status_code == 200, r.text
    p = r.json()
    (block,) = p["blocks"]
    assert block["supplier_id"] == "sup-demo-fish" and block["name"] == "Baltic Catch Fish Wholesale (demo)"
    (line,) = p["lines"]
    assert (line["quantity"], line["unit_price"], line["vat_rate"], line["unknown_stock"]) == ("6", "22.90", "13.5", True)
    assert p["total_incl_vat"] == "155.95"               # 137.40 + 13.5 % VAT
    assert block["delivery_fee"] == "18.00"              # under the 150 EUR minimum
