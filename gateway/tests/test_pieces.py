"""#975: the Buyer worker stores a request in pieces as unit PCS. The offer must have lines."""

from gateway.tests.test_gateway_app import AGENT, K, env  # noqa: F401 (fixture)


def test_a_need_in_pieces_gets_an_offer_with_lines(env):
    client, _, _ = env
    need = client.post(K + "/needs", headers=AGENT, json={
        "quantity": "30", "unit": "PCS", "requested_date": "2026-11-16",
        "text": "30 pcs lactose-free milk"}).json()
    offer = client.post("/tools/get_offer", headers=AGENT, json={
        "need_id": need["need_id"], "product_ids": ["462775", "463335"]}).json()
    assert offer["lines"], offer["mandate"]["reasons"]
    assert offer["measure"] == "PCS" and offer["shortfall"] == "0"
    assert sum(int(ln["quantity"]) for ln in offer["lines"]) == 30     # sold by the piece (ST)
    assert not any("pack size unknown" in e["reason"] for e in offer["excluded"])


def test_a_product_with_no_piece_count_is_left_out_in_plain_words(env):
    client, _, db = env
    db.products.update_one({"_id": "463335"}, {"$set": {
        "raw.salesUnit": "KI", "raw.baseUnit": "KI", "raw.units": [{"unitId": "KI", "sizeInBaseUnits": 1.0}]}})
    need = client.post(K + "/needs", headers=AGENT, json={
        "quantity": "30", "unit": "PCS", "requested_date": "2026-11-16"}).json()
    offer = client.post("/tools/get_offer", headers=AGENT, json={
        "need_id": need["need_id"], "product_ids": ["463335"]}).json()
    assert offer["lines"] == []
    assert offer["excluded"][0]["reason"] == (
        "pack size unknown: the catalog does not say how many pieces one KI holds; "
        "ask for this product in L")
