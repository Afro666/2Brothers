"""CRUD tests against a test database.

Set MONGODB_TEST_URI to run against a real MongoDB (a throwaway database is created
and dropped). Without it the tests use mongomock, an in-memory MongoDB.
"""

from decimal import Decimal
import os
import unittest
import uuid

from store.repository import Repository


def _test_db():
    uri = os.environ.get("MONGODB_TEST_URI")
    if uri:
        from pymongo import MongoClient

        client = MongoClient(uri)
        name = f"test_{uuid.uuid4().hex[:8]}"
        return client[name], lambda: client.drop_database(name)
    import mongomock

    return mongomock.MongoClient()["test"], lambda: None


class RepositoryTest(unittest.TestCase):
    def setUp(self):
        db, self._drop = _test_db()
        self.repo = Repository(db)

    def tearDown(self):
        self._drop()

    def test_supplier_crud_with_user_set_terms(self):
        s = self.repo.suppliers.create({"name": "Valio Aimo", "adapter": "valio_api"})
        self.assertIsNone(s["free_delivery_threshold_eur"])  # no default from Valio
        self.assertEqual(self.repo.suppliers.get(s["id"]), s)

        updated = self.repo.suppliers.update(
            s["id"],
            {"free_delivery_threshold_eur": 150.0, "delivery_fee_eur": 25.0,
             "order_days": ["mon", "thu"], "cutoff_time": "12:00", "lead_time_days": 1},
        )
        self.assertEqual(updated["order_days"], ["mon", "thu"])
        self.assertEqual(updated["cutoff_time"], "12:00")

        self.repo.suppliers.create({"name": "Local farm", "adapter": "manual"})
        self.assertEqual(len(self.repo.suppliers.list()), 2)
        self.assertEqual(len(self.repo.suppliers.list(adapter="manual")), 1)

        self.assertTrue(self.repo.suppliers.delete(s["id"]))
        self.assertIsNone(self.repo.suppliers.get(s["id"]))
        self.assertFalse(self.repo.suppliers.delete(s["id"]))

    def test_supplier_validation(self):
        with self.assertRaises(ValueError):
            self.repo.suppliers.create({"name": "X", "adapter": "fax"})
        with self.assertRaises(ValueError):
            self.repo.suppliers.create({"adapter": "manual"})

    def test_create_duplicate_id_raises_value_error(self):
        self.repo.suppliers.create({"id": "s1", "name": "Farm", "adapter": "manual"})
        with self.assertRaises(ValueError):
            self.repo.suppliers.create({"id": "s1", "name": "Farm", "adapter": "manual"})
        own = {"product_id": "own-1", "kitchen_id": "k1", "name": "Loaf", "unit": "ST",
               "supplier_id": "s1"}
        self.repo.own_products.create(own)
        with self.assertRaises(ValueError):
            self.repo.own_products.create(own)

    def test_own_product_crud_allergens_unknown_by_default(self):
        sup = self.repo.suppliers.create({"name": "Farm", "adapter": "manual"})
        p = self.repo.own_products.create(
            {"kitchen_id": "k1", "name": " Rye sourdough loaf 800 g ", "unit": "ST",
             "base_unit": "KG", "pack_size_in_base_units": "0.8", "unit_price_eur": "4.20",
             "supplier_id": sup["id"]}
        )
        self.assertTrue(p["product_id"].startswith("own-"))
        self.assertEqual(p["name"], "Rye sourdough loaf 800 g")
        self.assertEqual(p["allergen_data"], "UNKNOWN")  # unknown, not free-from
        self.assertEqual(p["allergens"], [])
        self.assertEqual(p["unit_price_eur"], Decimal("4.20"))
        self.assertEqual((p["base_unit"], p["pack_size_in_base_units"]), ("KG", Decimal("0.8")))

        p = self.repo.own_products.update(p["product_id"], {
            "allergen_data": "ENTERED", "kitchen_id": "k2",  # the kitchen cannot be changed
            "allergens": [{"code": "aw", "level": "CONTAINS"}, {"code": "AS", "level": "MAY_CONTAIN"}]})
        self.assertEqual(p["allergens"], [{"code": "AW", "level": "CONTAINS"},
                                          {"code": "AS", "level": "MAY_CONTAIN"}])
        self.assertEqual((p["allergen_data"], p["kitchen_id"]), ("ENTERED", "k1"))
        self.assertEqual(self.repo.own_products.get(p["product_id"]), p)
        self.assertEqual(self.repo.own_products.list(kitchen_id="k1", supplier_id=sup["id"]), [p])
        self.assertEqual(self.repo.own_products.list(kitchen_id="k2"), [])
        self.assertIsNone(self.repo.own_products.update("own-missing", {"name": "x"}))
        self.assertTrue(self.repo.own_products.delete(p["product_id"]))
        self.assertEqual(self.repo.own_products.list(), [])

    def test_own_product_is_stored_as_a_common_product_row(self):
        from store.repository import own_product_row
        row = own_product_row({"kitchen_id": "k1", "name": "Oat cookie", "unit": "PAK",
                               "supplier_id": "s1", "allergen_data": "ENTERED",
                               "allergens": [{"code": "GO", "level": "CONTAINS"},
                                             {"code": "GO", "level": "MAY_CONTAIN"}]}, "own-1")
        self.assertEqual((row["_id"], row["source"], row["kitchen_id"]), ("own-1", "own", "k1"))
        self.assertEqual(row["names"], {"en": "Oat cookie", "fi": "Oat cookie", "sv": "Oat cookie"})
        self.assertEqual(row["allergens"], {"contains": ["GO"], "may_contain": [], "undeclared": []})
        self.assertTrue(row["allergen_data_known"])
        self.assertFalse(row["no_declarable_allergens"])
        self.assertIsNone(row["net_content"])
        entered_none = own_product_row({"kitchen_id": "k1", "name": "Salt", "unit": "ST",
                                        "supplier_id": "s1", "allergen_data": "ENTERED"}, "own-2")
        self.assertTrue(entered_none["no_declarable_allergens"])
        unknown = own_product_row({"kitchen_id": "k1", "name": "Mystery", "unit": "ST",
                                   "supplier_id": "s1"}, "own-3")
        self.assertFalse(unknown["allergen_data_known"])
        self.assertFalse(unknown["no_declarable_allergens"])

    def test_own_product_validation(self):
        good = {"kitchen_id": "k1", "name": "Loaf", "unit": "ST", "supplier_id": "s1"}
        for bad in ({"unit_price_eur": 4.2}, {"unit_price_eur": "-1"}, {"unit_price_eur": "cheap"},
                    {"base_unit": "KG"}, {"base_unit": "kg", "pack_size_in_base_units": "1"},
                    {"base_unit": "KG", "pack_size_in_base_units": "0"},
                    {"allergen_data": "NONE"}, {"allergens": ["gluten"]},
                    {"allergens": [{"code": "AW", "level": "FREE_FROM"}]},
                    {"kitchen_id": None}, {"name": ""}):
            with self.assertRaises((ValueError, TypeError), msg=bad):
                self.repo.own_products.create({**good, **bad})
        with self.assertRaises(ValueError):
            self.repo.own_products.list(name="Loaf")

    def test_recipe_crud(self):
        r = self.repo.recipes.create(
            {"name": "Porridge",
             "items": [{"product_id": "valio-milk-1l", "qty_per_portion": 0.2},
                       {"product_id": "own-oats", "qty_per_portion": 0.05}]}
        )
        self.assertEqual(len(self.repo.recipes.get(r["id"])["items"]), 2)
        r = self.repo.recipes.update(r["id"], {"name": "Oat porridge"})
        self.assertEqual(r["name"], "Oat porridge")
        with self.assertRaises(ValueError):
            self.repo.recipes.update(r["id"], {"items": [{"product_id": "x", "qty_per_portion": 0}]})
        self.assertTrue(self.repo.recipes.delete(r["id"]))

    def test_menu_plan_crud(self):
        m = self.repo.menu_plans.create(
            {"date": "2026-11-16", "meal": "lunch", "recipe_id": "r1", "covers": 120}
        )
        self.repo.menu_plans.create(
            {"date": "2026-11-17", "meal": "lunch", "recipe_id": "r1", "covers": 90}
        )
        self.assertEqual(len(self.repo.menu_plans.list(date="2026-11-16")), 1)
        m = self.repo.menu_plans.update(m["id"], {"covers": 130})
        self.assertEqual(m["covers"], 130)
        with self.assertRaises(ValueError):
            self.repo.menu_plans.update(m["id"], {"covers": -1})
        self.assertTrue(self.repo.menu_plans.delete(m["id"]))
        self.assertEqual(len(self.repo.menu_plans.list()), 1)

    def test_update_missing_returns_none(self):
        self.assertIsNone(self.repo.recipes.update("nope", {"name": "x"}))


if __name__ == "__main__":
    unittest.main()
