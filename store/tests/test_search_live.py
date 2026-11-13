"""Acceptance for product search, against the loaded catalog on the live cluster.

Run with `STORE_LIVE_TESTS=1 python -m unittest store.tests.test_search_live -v`.
Read-only. Atlas Search cannot run locally, so this is skipped offline.
"""

import os
import unittest

from store.db import get_db
from store.search import ensure_search_index, search_products

ONE_LITRE = {"value": 1.0, "unit": "L"}


@unittest.skipUnless(os.environ.get("STORE_LIVE_TESTS") == "1", "set STORE_LIVE_TESTS=1")
class SearchAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = get_db()
        if ensure_search_index(cls.db) != "READY":
            raise unittest.SkipTest("the search index is still building; run again in a minute")

    def test_one_litre_lactose_free_milks_come_first(self):
        rows = search_products(self.db, "lactose free milk 1 l", limit=10)
        self.assertEqual(len(rows), 10)
        for row in rows:
            self.assertEqual(row["net_content"], ONE_LITRE, row["names"])
            self.assertTrue(row["lactose_free"], row["names"])
            self.assertIn("milk", row["names"]["en"].lower())
            self.assertIn("size 1 L matches", row["match_reasons"])
            self.assertNotIn("raw", row)
            self.assertIsInstance(row["product_id"], str)

    def test_excluding_milk_removes_every_product_that_contains_it(self):
        self.assertTrue(any("AM" in row["allergens"]["contains"]
                            for row in search_products(self.db, "milk chocolate", limit=50)))
        for query in ("lactose free milk 1 l", "milk chocolate", "cheese"):
            rows = search_products(self.db, query, {"exclude_allergens": ["milk"]}, limit=50)
            self.assertTrue(rows)
            for row in rows:
                listed = row["allergens"]["contains"] + row["allergens"]["may_contain"]
                self.assertNotIn("AM", listed, row["names"])

    def test_products_without_allergen_data_stay_but_are_marked(self):
        rows = search_products(self.db, "parmesan", {"exclude_allergens": ["eggs"]}, limit=50)
        unknown = [row for row in rows if not row["allergen_data_known"]]
        self.assertTrue(unknown)
        for row in unknown:
            self.assertIn("allergen data missing", row["match_reasons"])
        strict = search_products(self.db, "parmesan", {"exclude_allergens": ["eggs"],
                                                       "allergen_strictness": "strict"}, limit=50)
        self.assertTrue(strict)
        self.assertTrue(all(row["allergen_data_known"] for row in strict))

    def test_one_typo_is_tolerated(self):
        rows = search_products(self.db, "lactose free mlik 1 l", limit=5)
        self.assertTrue(rows)
        self.assertTrue(all(row["net_content"] == ONE_LITRE for row in rows))

    def test_filters_alone_work_without_a_query(self):
        rows = search_products(self.db, "", {"require_labels": ["EU_ORGANIC_FARMING"],
                                             "temperature": "frozen"}, limit=20)
        self.assertTrue(rows)
        for row in rows:
            self.assertIn("EU_ORGANIC_FARMING", row["labels"])
            self.assertEqual(row["temperature"], "frozen")
        sized = search_products(self.db, "butter", {"pack_size": {"value": 500, "unit": "g"}})
        self.assertTrue(sized)
        self.assertTrue(all(row["net_content"] == {"value": 0.5, "unit": "KG"} for row in sized))


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(os.environ.get("STORE_LIVE_TESTS") == "1", "set STORE_LIVE_TESTS=1")
class OwnProductSearch(unittest.TestCase):
    """Writes one own product for a made-up kitchen and removes it again."""

    def test_an_own_product_is_found_by_its_kitchen_only(self):
        import time
        from uuid import uuid4
        from store.repository import Repository

        db = get_db()
        if ensure_search_index(db) != "READY":
            raise unittest.SkipTest("the search index is still building; run again in a minute")
        kitchen, word = f"test-kitchen-{uuid4().hex[:8]}", f"zyx{uuid4().hex[:8]}"
        repo = Repository(db)
        product = repo.own_products.create(kitchen, {
            "name": f"Testi {word} loaf 800 g", "unit": "ST",
            "supplier_id": "test-supplier", "base_unit": "KG", "pack_size_in_base_units": "0.8",
            "unit_price_eur": "4.20", "allergen_data": "ENTERED",
            "allergens": [{"code": "AW", "level": "CONTAINS"}]})
        try:
            for _ in range(30):  # Atlas Search indexes new rows within seconds
                rows = search_products(db, word, kitchen_id=kitchen)
                if rows:
                    break
                time.sleep(2)
            self.assertEqual([row["product_id"] for row in rows], [product["product_id"]])
            self.assertEqual(rows[0]["source"], "own")
            self.assertEqual(rows[0]["net_content"], {"value": 0.8, "unit": "KG"})
            self.assertEqual(search_products(db, word), [])
            self.assertEqual(search_products(db, word, kitchen_id="another-kitchen"), [])
            self.assertEqual(search_products(db, word, {"exclude_allergens": ["gluten"]},
                                             kitchen_id=kitchen), [])
            milk = search_products(db, "lactose free milk 1 l", limit=5, kitchen_id=kitchen)
            self.assertEqual(len(milk), 5)  # the catalog is still there for a kitchen
        finally:
            self.assertTrue(repo.own_products.delete(kitchen, product["product_id"]))
