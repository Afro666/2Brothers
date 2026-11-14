"""VAT per product (#1603): the catalog's `vatCode` -> `vat_code` + `vat_rate`, never a guess."""

import unittest

from store.products import VAT_SOURCE, flatten, vat
from store.repository import Repository, own_product_row
from store.tests.test_products import record

try:
    import mongomock
except ImportError:  # the `test` extra is not installed
    mongomock = None


def with_code(code):
    raw = record()
    if code is None:
        raw["synkkaData"].pop("vatCode", None)
    else:
        raw["synkkaData"]["vatCode"] = code
    return raw


class VatCodeTest(unittest.TestCase):
    def test_each_finnish_code_has_its_2026_rate(self):
        self.assertEqual(vat("STANDARD"), ("STANDARD", "25.5"))
        self.assertEqual(vat("MEDIUM"), ("MEDIUM", "13.5"))      # food: fish and vegetables alike
        self.assertEqual(vat("LOW"), ("LOW", "10"))
        self.assertEqual(vat("NOT_APPLICABLE"), ("NOT_APPLICABLE", "0"))

    def test_a_repeated_code_is_that_code(self):
        self.assertEqual(vat("MEDIUM MEDIUM"), ("MEDIUM", "13.5"))

    def test_missing_empty_mixed_or_unknown_is_unknown_never_a_guess(self):
        for code in (None, "", "  ", "STANDARD MEDIUM", "REDUCED", 14, ["MEDIUM"]):
            with self.subTest(code=code):
                self.assertEqual(vat(code), (None, None))

    def test_flatten_puts_the_rate_and_its_source_on_the_row(self):
        row = flatten(with_code("STANDARD"))
        self.assertEqual((row["vat_code"], row["vat_rate"], row["vat_source"]),
                         ("STANDARD", "25.5", VAT_SOURCE))
        row = flatten(with_code(None))
        self.assertEqual((row["vat_code"], row["vat_rate"], row["vat_source"]), (None, None, None))

    def test_the_row_source_is_the_line_enum_not_free_text(self):
        # #1609: one vocabulary for `vat_source` on a row and on a line
        self.assertEqual(VAT_SOURCE, "catalog")
        self.assertEqual(flatten(with_code("MEDIUM"))["vat_source"], "catalog")

    def test_rate_is_text_so_the_store_never_holds_a_float(self):
        self.assertIsInstance(flatten(with_code("MEDIUM"))["vat_rate"], str)


@unittest.skipIf(mongomock is None, "mongomock not installed")
class BackfillTest(unittest.TestCase):
    def setUp(self):
        self.db = mongomock.MongoClient()["test"]
        rows = []
        for pid, code in (("1", "MEDIUM"), ("2", "STANDARD MEDIUM"), ("3", None), ("4", "STANDARD")):
            row = flatten({**with_code(code), "id": pid})
            for key in ("vat_code", "vat_rate", "vat_source"):   # a catalog loaded before #1603
                row.pop(key)
            rows.append(row)
        self.db.products.insert_many(rows)
        Repository(self.db).own_products.create("k1", {"product_id": "own-x", "name": "X", "unit": "ST",
                                                       "supplier_id": "sup-x"})

    def test_dry_run_counts_and_writes_nothing(self):
        from store.vat import backfill
        self.assertEqual(backfill(self.db, apply=False), {"checked": 4, "changed": 4, "known": 2, "unknown": 2})
        self.assertIsNone(self.db.products.find_one({"_id": "1"}).get("vat_rate"))

    def test_apply_sets_the_fields_from_the_stored_record_and_is_idempotent(self):
        from store.vat import backfill
        backfill(self.db, apply=True)
        got = {d["_id"]: (d["vat_code"], d["vat_rate"]) for d in self.db.products.find({"source": "valio"})}
        self.assertEqual(got, {"1": ("MEDIUM", "13.5"), "2": (None, None), "3": (None, None),
                               "4": ("STANDARD", "25.5")})
        self.assertEqual(backfill(self.db, apply=True)["changed"], 0)
        own = self.db.products.find_one({"_id": "own-x"})
        self.assertIsNone(own["vat_rate"])                   # an own product is never touched
        src = {d["_id"]: d["vat_source"] for d in self.db.products.find({"source": "valio"})}
        self.assertEqual(src, {"1": "catalog", "2": None, "3": None, "4": "catalog"})

    def test_apply_rewrites_the_old_free_text_source_and_is_idempotent(self):
        # #1609: rows filled with the old text get the enum; null when the rate is unknown
        from store.vat import backfill
        old = "Valio product data, vatCode"
        self.db.products.update_many({"source": "valio"}, {"$set": {"vat_source": old}})
        backfill(self.db, apply=True)
        self.db.products.update_many({"_id": {"$in": ["1", "3"]}}, {"$set": {"vat_source": old}})
        self.assertEqual(backfill(self.db, apply=False)["changed"], 2)
        backfill(self.db, apply=True)
        src = {d["_id"]: d["vat_source"] for d in self.db.products.find({"source": "valio"})}
        self.assertEqual(src, {"1": "catalog", "2": None, "3": None, "4": "catalog"})
        self.assertEqual(backfill(self.db, apply=True)["changed"], 0)


class OwnProductVatTest(unittest.TestCase):
    BASE = {"kitchen_id": "k1", "name": "Salmon fillet", "unit": "KG", "supplier_id": "sup-fish"}

    def test_entered_rate_category_and_catalog_link_are_kept(self):
        row = own_product_row({**self.BASE, "vat_rate": "13.5", "category": "18701",
                               "catalog_product_id": "461903"}, "own-salmon")
        self.assertEqual((row["vat_rate"], row["vat_source"], row["vat_code"]), ("13.5", "entered", None))
        self.assertEqual((row["category"], row["catalog_product_id"]), ("18701", "461903"))

    def test_no_rate_is_unknown(self):
        row = own_product_row(self.BASE, "own-salmon")
        self.assertEqual((row["vat_rate"], row["vat_source"], row["category"], row["catalog_product_id"]),
                         (None, None, None, None))

    def test_bad_values_are_refused(self):
        for bad in ({"vat_rate": "-1"}, {"vat_rate": "101"}, {"vat_rate": "abc"},
                    {"category": "187"}, {"category": 18701}, {"catalog_product_id": ""}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                own_product_row({**self.BASE, **bad}, "own-salmon")

    @unittest.skipIf(mongomock is None, "mongomock not installed")
    def test_contract_shape_returns_the_new_fields(self):
        repo = Repository(mongomock.MongoClient()["test"])
        out = repo.own_products.create("k1", {**self.BASE, "vat_rate": "13.5", "category": "18701",
                                              "catalog_product_id": "461903"})
        self.assertEqual((out["vat_rate"], out["category"], out["catalog_product_id"]),
                         ("13.5", "18701", "461903"))


if __name__ == "__main__":
    unittest.main()
