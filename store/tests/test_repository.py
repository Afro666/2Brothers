"""CRUD tests against a test database.

Set MONGODB_TEST_URI to run against a real MongoDB (a throwaway database is created
and dropped). Without it the tests use mongomock, an in-memory MongoDB.
"""

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

    def test_own_product_crud_allergens_unknown_by_default(self):
        sup = self.repo.suppliers.create({"name": "Farm", "adapter": "manual"})
        p = self.repo.own_products.create(
            {"name": "Rye bread", "unit": "kg", "pack_size": 2, "price_eur": 6.5,
             "supplier_id": sup["id"]}
        )
        self.assertIsNone(p["allergens"])  # unknown, not free-from
        p = self.repo.own_products.update(p["id"], {"allergens": ["gluten"]})
        self.assertEqual(p["allergens"], ["gluten"])
        self.assertEqual(self.repo.own_products.list(supplier_id=sup["id"]), [p])
        self.assertTrue(self.repo.own_products.delete(p["id"]))
        self.assertEqual(self.repo.own_products.list(), [])

    def test_own_product_scoped_to_kitchen(self):
        p = self.repo.own_products.create(
            {"name": "Rye bread", "unit": "kg", "supplier_id": "s1", "kitchen_id": "k1"}
        )
        own = self.repo.own_products
        self.assertIsNone(own.get(p["id"], kitchen_id="k2"))
        self.assertIsNone(own.update(p["id"], {"price_eur": 1.0}, kitchen_id="k2"))
        self.assertIsNone(own.update(p["id"], {}, kitchen_id="k2"))
        self.assertFalse(own.delete(p["id"], kitchen_id="k2"))
        self.assertEqual(own.get(p["id"]), p)  # untouched
        self.assertEqual(own.get(p["id"], kitchen_id="k1"), p)
        self.assertTrue(own.delete(p["id"], kitchen_id="k1"))

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
