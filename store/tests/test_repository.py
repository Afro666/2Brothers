"""Repository tests: contract shapes, validation and kitchen isolation.

Set MONGODB_TEST_URI to run against a real MongoDB (a throwaway database is created
and dropped). Without it the tests use mongomock, an in-memory MongoDB.
"""

from decimal import Decimal
import os
import unittest
import uuid

from store.repository import Repository, own_product_row


def _test_db():
    uri = os.environ.get("MONGODB_TEST_URI")
    if uri:
        from pymongo import MongoClient

        client = MongoClient(uri)
        name = f"test_{uuid.uuid4().hex[:8]}"
        return client[name], lambda: client.drop_database(name)
    import mongomock

    return mongomock.MongoClient()["test"], lambda: None


SUPPLIER = {
    "supplier_id": "sup-valio", "name": "Valio Aimo", "adapter": "valio_api",
    "terms": {"free_delivery_threshold_eur": "300.00", "delivery_fee_eur": "25.00",
              "order_days": ["MON", "TUE", "WED", "THU", "FRI"], "cutoff_time": "15:00",
              "lead_time_days": 1,
              "discount_tiers": [{"product_id": "900001", "min_qty": "100", "unit": "ST",
                                  "unit_price_eur": "0.95"}]},
}
RECIPE = {"recipe_id": "rec-soup-1", "name": "Carrot soup", "portions": 1,
          "ingredients": [{"product_id": "900002", "qty_per_portion": "0.100", "unit": "KG",
                           "yield_pct": "85"}]}
OWN = {"name": " Rye sourdough loaf 800 g ", "unit": "ST", "base_unit": "KG",
       "pack_size_in_base_units": "0.8", "unit_price_eur": "4.20", "supplier_id": "sup-bakery"}


class RepositoryTest(unittest.TestCase):
    def setUp(self):
        db, self._drop = _test_db()
        self.repo = Repository(db)

    def tearDown(self):
        self._drop()

    # Suppliers

    def test_supplier_in_the_contract_shape_with_decimal_money(self):
        s = self.repo.suppliers.create("k1", SUPPLIER)
        self.assertEqual((s["supplier_id"], s["kitchen_id"]), ("sup-valio", "k1"))
        self.assertNotIn("_id", s)
        self.assertEqual(s["terms"]["free_delivery_threshold_eur"], Decimal("300.00"))
        self.assertEqual(s["terms"]["discount_tiers"][0]["unit_price_eur"], Decimal("0.95"))
        self.assertEqual(s["terms"]["order_days"][0], "MON")
        self.assertEqual(self.repo.suppliers.get("k1", "sup-valio"), s)

    def test_missing_supplier_terms_stay_unknown(self):
        s = self.repo.suppliers.create("k1", {"name": "Local farm", "adapter": "manual"})
        self.assertTrue(s["supplier_id"])
        self.assertEqual(s["terms"], {"free_delivery_threshold_eur": None, "delivery_fee_eur": None,
                                      "order_days": None, "cutoff_time": None,
                                      "lead_time_days": None, "discount_tiers": []})

    def test_changing_one_term_keeps_the_others(self):
        self.repo.suppliers.create("k1", SUPPLIER)
        s = self.repo.suppliers.update("k1", "sup-valio", {"terms": {"delivery_fee_eur": "30.00"},
                                                           "supplier_id": "other", "kitchen_id": "k2"})
        self.assertEqual(s["terms"]["delivery_fee_eur"], Decimal("30.00"))
        self.assertEqual(s["terms"]["free_delivery_threshold_eur"], Decimal("300.00"))
        self.assertEqual(s["terms"]["cutoff_time"], "15:00")
        self.assertEqual((s["supplier_id"], s["kitchen_id"]), ("sup-valio", "k1"))
        self.assertIsNone(self.repo.suppliers.update("k1", "nope", {"name": "x"}))

    def test_supplier_validation(self):
        good = {"name": "X", "adapter": "manual"}
        for bad in ({"adapter": "fax"}, {"name": ""},
                    {"terms": {"delivery_fee_eur": 25.0}}, {"terms": {"delivery_fee_eur": "-1"}},
                    {"terms": {"order_days": ["mon"]}}, {"terms": {"order_days": "MON"}},
                    {"terms": {"cutoff_time": "25:00"}}, {"terms": {"cutoff_time": "3pm"}},
                    {"terms": {"lead_time_days": -1}}, {"terms": {"lead_time_days": 1.5}},
                    {"terms": {"mov": "300"}},
                    {"terms": {"discount_tiers": [{"min_qty": "100", "unit": "ST"}]}}):
            with self.assertRaises((ValueError, TypeError), msg=bad):
                self.repo.suppliers.create("k1", {**good, **bad})
        for bad in ({"terms": ["delivery_fee_eur"]}, {"terms": "free delivery"},
                    {"terms": {"discount_tiers": "10%"}}, {"terms": {"discount_tiers": ["10%"]}},
                    {"terms": {"discount_tiers": {"min_qty": "100"}}}):
            with self.assertRaises(ValueError, msg=bad):  # a clear 400, not a crash
                self.repo.suppliers.create("k1", {**good, **bad})

    # Kitchen isolation

    def test_duplicate_id_in_one_kitchen_is_a_value_error(self):
        self.repo.suppliers.create("k1", SUPPLIER)
        with self.assertRaises(ValueError):
            self.repo.suppliers.create("k1", SUPPLIER)
        self.repo.recipes.create("k1", RECIPE)
        with self.assertRaises(ValueError):
            self.repo.recipes.create("k1", RECIPE)
        self.repo.own_products.create("k1", {**OWN, "product_id": "own-rye"})
        with self.assertRaises(ValueError):
            self.repo.own_products.create("k1", {**OWN, "product_id": "own-rye"})

    def test_one_kitchen_never_sees_or_changes_another_kitchens_rows(self):
        self.repo.suppliers.create("k1", SUPPLIER)
        self.repo.suppliers.create("k2", {**SUPPLIER, "name": "Valio for kitchen 2"})  # same id
        self.repo.recipes.create("k1", RECIPE)
        self.repo.menu_plans.put("k1", "2026-W47", [])
        product = self.repo.own_products.create("k1", OWN)

        self.assertEqual([s["name"] for s in self.repo.suppliers.list("k1")], ["Valio Aimo"])
        self.assertEqual([s["name"] for s in self.repo.suppliers.list("k2")], ["Valio for kitchen 2"])
        self.assertEqual(self.repo.suppliers.list("k3"), [])
        self.assertIsNone(self.repo.recipes.get("k2", "rec-soup-1"))
        self.assertIsNone(self.repo.recipes.update("k2", "rec-soup-1", {"name": "Stolen"}))
        self.assertFalse(self.repo.recipes.delete("k2", "rec-soup-1"))
        self.assertIsNone(self.repo.menu_plans.get("k2", "2026-W47"))
        self.assertFalse(self.repo.menu_plans.delete("k2", "2026-W47"))
        self.assertIsNone(self.repo.own_products.get("k2", product["product_id"]))
        self.assertIsNone(self.repo.own_products.update("k2", product["product_id"], {"name": "x"}))
        self.assertFalse(self.repo.own_products.delete("k2", product["product_id"]))
        self.assertEqual(self.repo.own_products.list("k2"), [])

        self.assertEqual(self.repo.recipes.get("k1", "rec-soup-1")["name"], "Carrot soup")
        self.assertEqual(len(self.repo.own_products.list("k1")), 1)
        self.assertTrue(self.repo.suppliers.delete("k1", "sup-valio"))
        self.assertEqual(len(self.repo.suppliers.list("k2")), 1)

    # Own products

    def test_own_product_crud_allergens_unknown_by_default(self):
        p = self.repo.own_products.create("k1", OWN)
        self.assertTrue(p["product_id"].startswith("own-"))
        self.assertEqual((p["name"], p["kitchen_id"]), ("Rye sourdough loaf 800 g", "k1"))
        self.assertEqual(p["allergen_data"], "UNKNOWN")  # unknown, not free-from
        self.assertEqual(p["allergens"], [])
        self.assertEqual(p["unit_price_eur"], Decimal("4.20"))
        self.assertEqual((p["base_unit"], p["pack_size_in_base_units"]), ("KG", Decimal("0.8")))

        p = self.repo.own_products.update("k1", p["product_id"], {
            "allergen_data": "ENTERED", "kitchen_id": "k2",  # the kitchen cannot be changed
            "allergens": [{"code": "aw", "level": "CONTAINS"}, {"code": "AS", "level": "MAY_CONTAIN"}]})
        self.assertEqual(p["allergens"], [{"code": "AW", "level": "CONTAINS"},
                                          {"code": "AS", "level": "MAY_CONTAIN"}])
        self.assertEqual((p["allergen_data"], p["kitchen_id"]), ("ENTERED", "k1"))
        self.assertEqual(self.repo.own_products.get("k1", p["product_id"]), p)
        self.assertEqual(self.repo.own_products.list("k1", supplier_id="sup-bakery"), [p])
        self.assertEqual(self.repo.own_products.list("k1", supplier_id="other"), [])
        self.assertIsNone(self.repo.own_products.update("k1", "own-missing", {"name": "x"}))
        self.assertTrue(self.repo.own_products.delete("k1", p["product_id"]))
        self.assertEqual(self.repo.own_products.list("k1"), [])

    def test_own_product_is_stored_as_a_common_product_row(self):
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
        good = {"name": "Loaf", "unit": "ST", "supplier_id": "s1"}
        for bad in ({"unit_price_eur": 4.2}, {"unit_price_eur": "-1"}, {"unit_price_eur": "cheap"},
                    {"base_unit": "KG"}, {"base_unit": "kg", "pack_size_in_base_units": "1"},
                    {"base_unit": "KG", "pack_size_in_base_units": "0"},
                    {"allergen_data": "NONE"}, {"allergens": ["gluten"]},
                    {"allergens": [{"code": "AW", "level": "FREE_FROM"}]}, {"name": ""}):
            with self.assertRaises((ValueError, TypeError), msg=bad):
                self.repo.own_products.create("k1", {**good, **bad})

    # Settings

    def test_settings_change_only_the_fields_given(self):
        self.assertEqual(self.repo.settings.get("k1"), {"excluded_allergens": None})  # unknown
        settings, changed = self.repo.settings.put("k1", {
            "service_level": {"A": "0.98", "B": "0.95"}, "max_cover_days": {"fish": 2},
            "stockout_cap": "1.8", "budget_warning_order_eur": "1500.00",
            "excluded_allergens": ["AP", "nuts"]})
        self.assertEqual(settings["service_level"], {"A": Decimal("0.98"), "B": Decimal("0.95")})
        self.assertEqual(sorted(changed), ["budget_warning_order_eur", "excluded_allergens",
                                           "max_cover_days", "service_level", "stockout_cap"])
        self.assertEqual(changed["excluded_allergens"], {"from": None, "to": ["AP", "nuts"]})

        settings, changed = self.repo.settings.put("k1", {
            "service_level": {"A": "0.99"}, "budget_warning_order_eur": None, "stockout_cap": "1.8"})
        self.assertEqual(settings["service_level"], {"A": Decimal("0.99"), "B": Decimal("0.95")})
        self.assertIsNone(settings["budget_warning_order_eur"])  # null: no warning
        self.assertEqual(settings["excluded_allergens"], ["AP", "nuts"])  # the policy is kept
        self.assertEqual(settings["max_cover_days"], {"fish": 2})
        self.assertEqual(sorted(changed), ["budget_warning_order_eur", "service_level"])
        self.assertEqual(changed["service_level"]["from"], {"A": Decimal("0.98"), "B": Decimal("0.95")})
        self.assertEqual(self.repo.settings.get("k1"), settings)
        self.assertEqual(self.repo.settings.put("k1", {})[1], {})
        self.assertEqual(self.repo.settings.get("k2"), {"excluded_allergens": None})

    def test_settings_are_stored_where_the_engine_and_the_buyer_read_them(self):
        from engine.params import KitchenParams
        from store.buyer_context import excluded_allergens
        self.repo.settings.put("k1", {"service_level": {"C": "0.92"}, "max_cover_days": {"fish": 1},
                                      "stockout_cap": "2", "budget_warning_week_eur": "6000",
                                      "excluded_allergens": []})
        db = self.repo.settings._coll.database
        doc = db.kitchen_settings.find_one({"_id": "k1"})
        self.assertEqual(sorted(doc), ["_id", "engine", "excluded_allergens"])
        params = KitchenParams.from_dict(self.repo.settings.get("k1"))
        self.assertEqual(params.service_level["C"], Decimal("0.92"))
        self.assertEqual(params.service_level["A"], Decimal("0.975"))  # the default stays
        self.assertEqual((params.cover_days("fish"), params.stockout_cap), (1, 2.0))
        self.assertEqual(params.budget_warning_week_eur, Decimal("6000"))
        self.assertEqual(excluded_allergens(db, "k1"), [])  # explicitly none, not unknown

    def test_settings_validation(self):
        for bad in ({"service_level": {"A": "97.5"}}, {"service_level": {"A": "1"}},
                    {"service_level": {"A": "0"}}, {"service_level": {"D": "0.9"}},
                    {"service_level": {"A": 0.975}}, {"service_level": "0.975"},
                    {"max_cover_days": {"Dairy": 5}}, {"max_cover_days": {"fish": 0}},
                    {"max_cover_days": {"fish": "2"}}, {"stockout_cap": "0.9"},
                    {"stockout_cap": "4"}, {"stockout_cap": None},
                    {"budget_warning_order_eur": "-1"}, {"budget_warning_week_eur": 6000.0},
                    {"excluded_allergens": None}, {"excluded_allergens": "AP"},
                    {"excluded_allergens": ["peanut butter"]}, {"excluded_allergens": [7]},
                    {"excluded_allergens": ["ZZ"]}, {"excluded_allergens": ["AP", "ZZ"]},
                    {"auto_approve": True}):
            with self.assertRaises((ValueError, TypeError), msg=bad):
                self.repo.settings.put("k1", bad)
        self.assertEqual(self.repo.settings.get("k1"), {"excluded_allergens": None})
        self.repo.settings.put("k1", {"excluded_allergens": ["AW", "AM", "nuts"]})  # known ones save
        self.assertEqual(self.repo.settings.get("k1")["excluded_allergens"], ["AW", "AM", "nuts"])

    def test_standing_orders_are_replaced_not_merged(self):
        settings, _ = self.repo.settings.put("k1", {"standing_orders": {"900001": "2", "own-ab12": "0.5"}})
        self.assertEqual(settings["standing_orders"], {"900001": Decimal("2"), "own-ab12": Decimal("0.5")})
        self.repo.settings.put("k1", {"standing_orders": {"900002": "3"}})
        self.assertEqual(self.repo.settings.get("k1")["standing_orders"], {"900002": Decimal("3")})
        self.repo.settings.put("k1", {"standing_orders": {}})  # {} clears them all
        self.assertEqual(self.repo.settings.get("k1")["standing_orders"], {})

    def test_standing_orders_validation(self):
        for bad in ({"900001": "0"}, {"900001": "-1"}, {"900001": 2.0}, {"900001": "many"},
                    {"a.b": "1"}, {"$x": "1"}, {"": "1"}, {"x" * 65: "1"}, ["900001"]):
            with self.assertRaises((ValueError, TypeError), msg=bad):  # both answer 422
                self.repo.settings.put("k1", {"standing_orders": bad})
        self.assertNotIn("standing_orders", self.repo.settings.get("k1"))

    # Recipes

    def test_recipe_in_the_contract_shape(self):
        r = self.repo.recipes.create("k1", RECIPE)
        self.assertEqual(r["ingredients"], [{"product_id": "900002", "unit": "KG",
                                             "qty_per_portion": Decimal("0.100"),
                                             "yield_pct": Decimal("85")}])
        self.assertEqual(r["portions"], 1)
        r = self.repo.recipes.update("k1", "rec-soup-1", {"name": "Carrot and ginger soup"})
        self.assertEqual((r["name"], len(r["ingredients"])), ("Carrot and ginger soup", 1))
        plain = self.repo.recipes.create("k1", {"name": "Porridge", "ingredients": [
            {"product_id": "900003", "qty_per_portion": "0.2", "unit": "L"}]})
        self.assertIsNone(plain["ingredients"][0]["yield_pct"])  # null means 100
        self.assertEqual(len(self.repo.recipes.list("k1")), 2)
        self.assertTrue(self.repo.recipes.delete("k1", "rec-soup-1"))

    def test_recipe_validation(self):
        def ingredient(**over):
            return {"name": "X", "ingredients": [{"product_id": "900002", "qty_per_portion": "0.1",
                                                  "unit": "KG", **over}]}
        for bad in (ingredient(qty_per_portion="0"), ingredient(qty_per_portion=0.1),
                    ingredient(unit="kg"), ingredient(unit="ST"), ingredient(yield_pct="0"),
                    ingredient(yield_pct="120"), ingredient(product_id=""),
                    {"name": "X", "portions": 0}, {"name": ""}):
            with self.assertRaises((ValueError, TypeError), msg=bad):
                self.repo.recipes.create("k1", bad)
        for bad in ({"name": "X", "ingredients": "carrot"}, {"name": "X", "ingredients": ["carrot"]},
                    {"name": "X", "ingredients": {"product_id": "900002"}}):
            with self.assertRaises(ValueError, msg=bad):  # a clear 400, not a crash
                self.repo.recipes.create("k1", bad)

    # Menu plans

    def test_menu_plan_is_replaced_per_week(self):
        days = [{"date": "2026-11-16", "meal": "lunch", "recipe_id": "rec-soup-1", "covers": 180}]
        plan = self.repo.menu_plans.put("k1", "2026-W47", days)
        self.assertEqual(plan, {"kitchen_id": "k1", "week": "2026-W47", "days": days})
        self.repo.menu_plans.put("k1", "2026-W47", [{**days[0], "covers": 90},
                                                    {**days[0], "date": "2026-11-17"}])
        stored = self.repo.menu_plans.get("k1", "2026-W47")
        self.assertEqual([d["covers"] for d in stored["days"]], [90, 180])
        self.repo.menu_plans.put("k1", "2026-W48", [])
        self.assertEqual([p["week"] for p in self.repo.menu_plans.list("k1")],
                         ["2026-W47", "2026-W48"])
        self.assertTrue(self.repo.menu_plans.delete("k1", "2026-W48"))
        self.assertIsNone(self.repo.menu_plans.get("k1", "2026-W48"))

    def test_menu_plan_validation(self):
        day = {"date": "2026-11-16", "meal": "lunch", "recipe_id": "r1", "covers": 10}
        for week, bad in (("2026-47", day), ("2026-W54", day),
                          ("2026-W47", {**day, "date": "2026-11-23"}),  # the week after
                          ("2026-W47", {**day, "meal": "brunch"}),
                          ("2026-W47", {**day, "covers": -1}), ("2026-W47", {**day, "covers": None}),
                          ("2026-W47", {**day, "covers": 1.5}), ("2026-W47", {**day, "recipe_id": ""}),
                          ("2026-W47", {**day, "date": "16.11.2026"})):
            with self.assertRaises(ValueError, msg=(week, bad)):
                self.repo.menu_plans.put("k1", week, [bad])
        for bad in ("2026-11-16", {"date": "2026-11-16"}, ["2026-11-16"], [7]):
            with self.assertRaises(ValueError, msg=bad):  # a clear 400, not a crash
                self.repo.menu_plans.put("k1", "2026-W47", bad)


if __name__ == "__main__":
    unittest.main()
