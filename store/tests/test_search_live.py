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

    def test_milk_gives_milk_first_not_hand_wash(self):
        # #1593: two Palmolive hand washes ("Almond Milk", "Milk & Olive") were first.
        rows = search_products(self.db, "milk", limit=5)
        self.assertEqual([row["category"] for row in rows], ["10400"] * 5, [r["names"] for r in rows])
        for row in rows:
            self.assertIn("milk", row["names"]["en"].lower())
            self.assertNotIn("hand wash", row["names"]["en"].lower())
            self.assertIn("AM", row["allergens"]["contains"])
        for query in ("lactose-free milk", "milk 1 l"):  # was chocolate first; was a jug first
            self.assertEqual(search_products(self.db, query, limit=1)[0]["category"], "10400", query)

    def test_a_non_food_query_still_finds_non_food(self):
        rows = search_products(self.db, "hand wash", limit=5)
        self.assertTrue(all("hand wash" in row["names"]["en"].lower() for row in rows))
        cups = search_products(self.db, "coffee cup", limit=5)
        self.assertTrue(all("cup" in row["names"]["en"].lower() for row in cups))

    def test_almond_milk_gives_food_first_not_the_hand_wash(self):
        # #1658: the only name with both words is "Palmolive Naturals Almond Milk liquid hand wash".
        from store.search import ALL_WORDS_BOOST, NON_FOOD_PREFIXES
        # "olive milk": the same picture with another hand wash ("Milk & Olive"), and no
        # plant drink of that name to answer it (#1699 answers "almond milk" with almond drinks).
        for query in ("almond milk", "olive milk"):
            rows = search_products(self.db, query, limit=50)
            self.assertFalse(rows[0]["category"].startswith(NON_FOOD_PREFIXES), rows[0]["names"])
            for row in rows[:3]:
                self.assertNotIn("hand wash", row["names"]["en"].lower())
            # A non-food name with both words must not look like a full match
            # (gateway/candidates.py would hand the Buyer only that row: the hand wash).
            self.assertTrue(all(row["score"] < ALL_WORDS_BOOST for row in rows
                                if row["category"].startswith(NON_FOOD_PREFIXES)), query)
            foods = [not row["category"].startswith(NON_FOOD_PREFIXES) for row in rows]
            self.assertEqual(foods, sorted(foods, reverse=True))  # every food row before any non-food row
        # A food name with every word keeps its full-match score in such a query.
        self.assertGreaterEqual(search_products(self.db, "lactose free milk", limit=1)[0]["score"],
                                ALL_WORDS_BOOST)
        jugs = search_products(self.db, "milk jug", limit=3)  # the last word is tableware
        self.assertEqual([row["category"] for row in jugs], ["20033"] * 3)

    def test_a_plant_milk_gives_the_plant_drink_first(self):
        # #1699: was almond ice cream for "almond milk", milk chocolate for "oat milk",
        # and nothing at all for "kauramaito".
        for query, word in (("almond milk", "almond drink"), ("oat milk", "oat drink"),
                            ("rice milk", "rice drink"), ("barista oat milk", "oat drink")):
            first = search_products(self.db, query, limit=1)[0]
            self.assertEqual(first["category"], "10402", (query, first["names"]))
            self.assertIn(word, first["names"]["en"].lower())
            if query != "barista oat milk":  # "Oat Drink Barista": the words, not the phrase
                self.assertIn(f'name contains "{word}"', first["match_reasons"])
        for query, word in (("kauramaito", "kaurajuoma"), ("mantelimaito", "mantelijuoma"),
                            ("soijamaito", "soijajuoma")):
            rows = search_products(self.db, query, limit=3)
            self.assertTrue(rows, query)
            self.assertTrue(all(word in row["names"]["fi"].lower() for row in rows), query)
        soy = search_products(self.db, "soy milk", limit=10)
        self.assertEqual([row["category"] for row in soy[:5]], ["10402"] * 5)
        self.assertFalse(any("soda" in row["names"]["en"].lower() for row in soy))  # one typo from "soya"
        litres = search_products(self.db, "oat milk 1 l", limit=5)
        self.assertTrue(all(row["net_content"] == ONE_LITRE and "oat drink" in row["names"]["en"].lower()
                            for row in litres))
        coconut = search_products(self.db, "coconut milk", limit=3)  # its own product, not a drink
        self.assertTrue(all("coconut milk" in row["names"]["en"].lower() for row in coconut))

    def test_the_meaning_search_keeps_the_hand_wash_out_of_a_food_query_too(self):
        # #1692. The query vector is the hand wash's own stored vector: the worst case, the
        # vector side ranks it first. No call to the embedding service.
        from unittest import mock
        from store import embeddings
        from store.search import NON_FOOD_PREFIXES
        soap = self.db.products.find_one({"names.en": {"$regex": "Almond Milk liquid hand wash"}},
                                         {"embedding.vector": 1})
        if not soap or "embedding" not in soap:
            self.skipTest("the product vectors are not loaded")
        vector = list(soap["embedding"]["vector"].as_vector().data)
        with mock.patch.object(embeddings, "current_model", return_value=None):
            rows = search_products(self.db, "almond milk", limit=20, hybrid=True,
                                   embedder=lambda texts, kind: [vector])
            wash = search_products(self.db, "hand wash", limit=3, hybrid=True,
                                   embedder=lambda texts, kind: [vector])
        self.assertFalse(rows[0]["category"].startswith(NON_FOOD_PREFIXES), rows[0]["names"])
        for row in rows[:3]:
            self.assertNotIn("hand wash", row["names"]["en"].lower())
        foods = [not row["category"].startswith(NON_FOOD_PREFIXES) for row in rows]
        self.assertEqual(foods, sorted(foods, reverse=True))  # every food row before any non-food row
        self.assertTrue(all(row["category"].startswith("63") for row in wash))  # a non-food query: as before

    def test_a_row_with_some_of_the_words_stays_under_the_all_words_line(self):
        from store.search import ALL_WORDS_BOOST
        rows = search_products(self.db, "milk honey", limit=20)
        some = [row for row in rows if "honey" not in " ".join(row["names"].values()).lower()]
        self.assertTrue(some)
        self.assertTrue(all(row["score"] < ALL_WORDS_BOOST for row in some))

    def test_the_same_search_gives_the_same_list_every_time(self):
        # #1657: equal scores cross the cut-off (seven rows tie around place 20 of "milk").
        for query, filters in (("cheese", {}), ("laktoositon maito", {}), ("milk", {}),
                               ("lactose free milk", {"category": "10400"})):  # the Buyer's kind search
            fifty = search_products(self.db, query, filters, limit=50)
            ids = [row["product_id"] for row in fifty]
            self.assertEqual(ids, [row["product_id"] for row in search_products(self.db, query, filters, limit=50)])
            self.assertEqual(fifty, sorted(fifty, key=lambda row: (-row["score"], row["product_id"])), query)
            # A shorter list is the start of a longer one: a tie at the cut is broken the same way.
            for limit in (5, 20):
                short = search_products(self.db, query, filters, limit=limit)
                self.assertEqual([row["product_id"] for row in short], ids[:limit], (query, limit))
        milk = search_products(self.db, "milk", limit=21)
        self.assertEqual(milk[19]["score"], milk[20]["score"])  # the tie this test is about is there

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
