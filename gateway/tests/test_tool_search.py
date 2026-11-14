"""search_products with the need (demo blocker 2026-11-14): a request in litres must get
milk it can still order, not chocolate and not a product whose cut-off has passed."""

from gateway.tests.test_gateway_app import AGENT, K, env  # noqa: F401 (fixture)

CATALOG = [
    {"product_id": "choc", "net_content": {"value": 1.0, "unit": "KG"}},          # top text hit, wrong measure
    {"product_id": "462921", "net_content": {"value": 5.0, "unit": "L"}},         # litres, cut-off passed
    {"product_id": "462775", "net_content": {"value": 1.0, "unit": "L"}},         # litres, can arrive
    {"product_id": "463335", "net_content": {"value": 1.0, "unit": "L"}},         # litres, can arrive
]


def test_search_with_need_keeps_the_measure_and_puts_deliverable_first(env):
    client, _, _ = env
    from gateway.service import Gateway
    original = Gateway.tool_search

    def with_catalog(self, *args, **kwargs):
        self._search = lambda db, query, filters, limit, kitchen_id=None: [dict(r) for r in CATALOG][:limit]
        return original(self, *args, **kwargs)

    Gateway.tool_search = with_catalog
    try:
        need = client.post(K + "/needs", headers=AGENT, json={
            "quantity": "20", "unit": "L", "requested_date": "2026-11-16"}).json()
        found = client.post("/tools/search_products", headers=AGENT, json={
            "query": "lactose-free milk", "filters": {}, "need_id": need["need_id"]}).json()
        ids = [p["product_id"] for p in found["products"]]
        assert "choc" not in ids and found["measure"] == "L"
        assert ids[:2] == ["462775", "463335"] and ids[-1] == "462921"
        assert [p["can_arrive"] for p in found["products"]] == [True, True, False]
        plain = client.post("/tools/search_products", headers=AGENT, json={"query": "milk", "filters": {}}).json()
        assert [p["product_id"] for p in plain["products"]][0] == "choc" and "measure" not in plain
        bad = client.post("/tools/search_products", headers=AGENT, json={"query": "milk", "need_id": "nope"})
        assert bad.status_code == 422
    finally:
        Gateway.tool_search = original


def test_unknown_cutoff_gives_can_arrive_null_between_true_and_false(env):
    """Valio gave no closingTime (cutoff_passed None): unknown, not undeliverable (#641)."""
    client, _, _ = env
    from gateway.service import Gateway
    from gateway.valio_client import ValioClient
    original, original_availability = Gateway.tool_search, ValioClient.availability

    def with_catalog(self, *args, **kwargs):
        self._search = lambda db, query, filters, limit, kitchen_id=None: [dict(r) for r in CATALOG][:limit]
        return original(self, *args, **kwargs)

    def no_closing_time(self, *args, **kwargs):
        out = original_availability(self, *args, **kwargs)
        for product in out["products"]:
            if product["productId"] == "463335":
                product["cutoff_passed"] = None
        return out

    Gateway.tool_search, ValioClient.availability = with_catalog, no_closing_time
    try:
        need = client.post(K + "/needs", headers=AGENT, json={
            "quantity": "20", "unit": "L", "requested_date": "2026-11-16"}).json()
        found = client.post("/tools/search_products", headers=AGENT, json={
            "query": "lactose-free milk", "filters": {}, "need_id": need["need_id"]}).json()
        assert [(p["product_id"], p["can_arrive"]) for p in found["products"]] == [
            ("462775", True), ("463335", None), ("462921", False)]
    finally:
        Gateway.tool_search, ValioClient.availability = original, original_availability
