"""`flatten()` on synthetic records shaped like the real catalog. No Valio data here."""

import unittest
from unittest import mock

from store.products import flatten, get_products, upsert_products

try:
    import mongomock
except ImportError:  # the `test` extra is not installed
    mongomock = None


def record(**over):
    """A made-up product with every field the real records carry."""
    raw = {
        "id": "900001", "salesUnit": "ST", "baseUnit": "ST", "category": "99901",
        "allowedLotSize": 0.01, "vendorName": "TESTI OY", "countryOfOrigin": "fi",
        "temperatureCondition": 3, "deleted": False, "deposits": [],
        "units": [{"unitId": "KI", "sizeInBaseUnits": 12.0, "gtin": "0000000000017"},
                  {"unitId": "ST", "sizeInBaseUnits": 1.0, "gtin": "0000000000024"}],
        "synkkaData": {
            "names": [{"language": "en", "value": "Testi oat drink 1 l "},
                      {"language": "fi", "value": "Testi kaurajuoma 1 l"},
                      {"language": "sv", "value": "Testi havredryck 1 l"},
                      {"language": "es", "value": "Testi bebida"}],
            "brand": "Testi ",
            "minTemperature": 2.0, "maxTemperature": 6.0,
            "unitConversions": [{"synkkaPackagingType": "BASE_UNIT_OR_EACH",
                                 "volume": {"unit": "LTR", "value": 1.0},
                                 "netWeight": {"unit": "GRM", "value": 1030.0}}],
            "classifications": [
                {"name": "allergen", "type": "ENUM", "values": [
                    {"id": "GO", "unit": "CONTAINS"}, {"id": "AN", "unit": "MAY_CONTAIN"},
                    {"id": "AY", "unit": "UNDECLARED"}]},
                {"name": "nonAllergen", "type": "ENUM", "values": [
                    {"id": "AM", "unit": "FREE_FROM"}, {"id": "ML", "unit": "FREE_FROM"}]},
                {"name": "packagingMarkedLabel", "type": "ENUM", "values": [
                    {"id": "EU_ORGANIC_FARMING", "synkkaId": "EU_ORGANIC_FARMING"},
                    {"id": "coolTemperature"}]},
                {"name": "nutritionalClaim", "type": "ENUM", "values": [
                    {"id": "VEGAN", "synkkaId": "VEGAN", "unit": "DIET"}]},
            ],
        },
    }
    synkka = over.pop("synkka", {})
    raw.update(over)
    raw["synkkaData"].update(synkka)
    return raw


def classification(name, *values):
    return {"name": name, "type": "ENUM", "values": list(values)}


class FlattenTests(unittest.TestCase):
    def test_plain_fields(self):
        doc = flatten(record(), reliability=0.975, carbon=1.44)
        self.assertEqual(doc["_id"], "900001")
        self.assertEqual((doc["source"], doc["supplier_id"]), ("valio", "valio_aimo"))
        self.assertEqual(doc["names"], {"en": "Testi oat drink 1 l", "fi": "Testi kaurajuoma 1 l",
                                        "sv": "Testi havredryck 1 l"})
        self.assertEqual(doc["brand"], "Testi")
        self.assertEqual((doc["category"], doc["vendor"], doc["country"]),
                         ("99901", "TESTI OY", "fi"))
        self.assertEqual(doc["units"][0],
                         {"unit": "KI", "size_in_base_units": 12.0, "gtin": "0000000000017"})
        self.assertIsNone(doc["lot_size"])
        self.assertEqual(doc["substitutions"], [])  # the key is absent on most records
        self.assertEqual((doc["reliability"], doc["carbon_kg_co2e_per_kg"]), (0.975, 1.44))
        self.assertEqual(doc["raw"]["synkkaData"]["names"][3]["language"], "es")  # raw is whole

    def test_codes_are_always_strings_and_optional_data_may_be_missing(self):
        doc = flatten({"id": 900002, "units": [], "synkkaData": {"names": []}})
        self.assertEqual(doc["_id"], "900002")
        self.assertIsNone(doc["brand"])
        self.assertIsNone(doc["reliability"])
        self.assertIsNone(doc["net_content"])
        self.assertIsNone(doc["temperature"])
        self.assertFalse(doc["allergen_data_known"])

    def test_allergen_levels_stay_apart(self):
        doc = flatten(record())
        self.assertEqual(doc["allergens"],
                         {"contains": ["GO"], "may_contain": ["AN"], "undeclared": ["AY"]})
        self.assertEqual(doc["free_from"], ["AM", "ML"])
        self.assertTrue(doc["allergen_data_known"])
        self.assertFalse(doc["no_declarable_allergens"])

    def test_missing_allergen_data_is_unknown_not_allergen_free(self):
        doc = flatten(record(synkka={"classifications": [
            classification("allergen"), classification("nonAllergen")]}))
        self.assertFalse(doc["allergen_data_known"])
        self.assertEqual(doc["allergens"], {"contains": [], "may_contain": [], "undeclared": []})
        self.assertFalse(doc["no_declarable_allergens"])

    def test_x99_means_no_declarable_allergens_not_an_allergen(self):
        doc = flatten(record(synkka={"classifications": [
            classification("allergen", {"id": "X99", "unit": "CONTAINS"})]}))
        self.assertEqual(doc["allergens"]["contains"], [])
        self.assertTrue(doc["allergen_data_known"])
        self.assertTrue(doc["no_declarable_allergens"])

    def test_contradictions_resolve_to_the_riskier_statement(self):
        doc = flatten(record(synkka={"classifications": [
            classification("allergen", {"id": "AM", "unit": "CONTAINS"},
                           {"id": "AM", "unit": "MAY_CONTAIN"}, {"id": "ML", "unit": "MAY_CONTAIN"},
                           {"id": "AE", "unit": "SOMETHING_NEW"}),
            classification("nonAllergen", {"id": "AM", "unit": "FREE_FROM"},
                           {"id": "ML", "unit": "FREE_FROM"}),
            classification("nutritionalClaim", {"id": "FREE_FROM_LACTOSE", "unit": "FREE_FROM"})]}))
        self.assertEqual(doc["allergens"]["contains"], ["AE", "AM"])
        self.assertEqual(doc["allergens"]["may_contain"], ["ML"])
        self.assertEqual(doc["free_from"], [])
        self.assertFalse(doc["lactose_free"])

    def test_lactose_free_from_claim_or_free_from_code(self):
        self.assertTrue(flatten(record())["lactose_free"])  # nonAllergen ML
        by_claim = flatten(record(synkka={"classifications": [
            classification("allergen", {"id": "AM", "unit": "CONTAINS"}),
            classification("nutritionalClaim", {"id": "FREE_FROM_LACTOSE", "unit": "FREE_FROM"})]}))
        self.assertTrue(by_claim["lactose_free"])  # lactose-free milk still contains milk
        self.assertEqual(by_claim["allergens"]["contains"], ["AM"])
        low = flatten(record(synkka={"classifications": [
            classification("nutritionalClaim", {"id": "LOW_LACTOSE", "unit": "LOW"})]}))
        self.assertFalse(low["lactose_free"])

    def test_labels_exclude_storage_tags_and_claims_are_kept(self):
        doc = flatten(record())
        self.assertEqual(doc["labels"], ["EU_ORGANIC_FARMING"])
        self.assertEqual(doc["claims"], ["VEGAN"])

    def test_temperature(self):
        tag = lambda *ids: {"classifications": [
            classification("packagingMarkedLabel", *({"id": i} for i in ids))]}
        self.assertEqual(flatten(record())["temperature"], "chilled")
        self.assertEqual(flatten(record(temperatureCondition=7))["temperature"], "frozen")
        self.assertEqual(flatten(record(temperatureCondition=8))["temperature"], "ambient")
        unknown = flatten(record(temperatureCondition=5, synkka=tag()))
        self.assertIsNone(unknown["temperature"])
        self.assertEqual(unknown["temperature_condition"], 5)
        self.assertEqual(flatten(record(temperatureCondition=9, synkka=tag("freezeTemperature")))
                         ["temperature"], "frozen")
        self.assertIsNone(flatten(record(temperatureCondition=None, synkka=tag(
            "freezeTemperature", "warmTemperature")))["temperature"])
        self.assertEqual((unknown["min_temperature_c"], unknown["max_temperature_c"]), (2.0, 6.0))

    def net(self, **over):
        doc = flatten(record(**over))
        return doc["net_content"], doc["net_content_source"]

    def test_net_content_of_the_piece_not_the_case(self):
        self.assertEqual(self.net(), ({"value": 1.0, "unit": "L"}, "synkka"))

    def test_net_content_falls_back_to_net_weight_when_volume_counts_pieces(self):
        conversions = [{"synkkaPackagingType": "BASE_UNIT_OR_EACH",
                        "volume": {"unit": "H87", "value": 4.0},
                        "netWeight": {"unit": "GRM", "value": 400.0}}]
        self.assertEqual(self.net(synkka={"unitConversions": conversions}),
                         ({"value": 0.4, "unit": "KG"}, "synkka"))

    def test_net_content_of_a_measured_case_is_divided_by_the_case_size(self):
        conversions = [{"synkkaPackagingType": "CASE", "volume": {"unit": "LTR", "value": 6.0}}]
        self.assertEqual(self.net(synkka={"unitConversions": conversions}),
                         ({"value": 0.5, "unit": "L"}, "synkka_case"))

    def test_net_content_from_the_name_is_flagged(self):
        gross_only = [{"synkkaPackagingType": "CASE", "grossWeight": {"unit": "GRM", "value": 5300.0}}]
        self.assertEqual(self.net(synkka={"unitConversions": gross_only}),
                         ({"value": 1.0, "unit": "L"}, "name"))

    def test_sizes_in_names(self):
        def named(name, units=(("ST", 1.0),)):
            return self.net(units=[{"unitId": u, "sizeInBaseUnits": s} for u, s in units],
                            synkka={"unitConversions": [], "names": [{"language": "fi", "value": name}]})[0]
        self.assertEqual(named("TESTI 7X1,2KG LEIPÄ", (("KI", 1.0),)), {"value": 8.4, "unit": "KG"})
        self.assertEqual(named("12x1 l Testi juoma", (("KI", 12.0), ("ST", 1.0))),
                         {"value": 1.0, "unit": "L"})
        self.assertEqual(named("Testi juusto e750 g"), {"value": 0.75, "unit": "KG"})
        self.assertEqual(named("Testi 2,5 dl kerma"), {"value": 0.25, "unit": "L"})
        self.assertEqual(named("PORKKANA 10KG/SK"), {"value": 10.0, "unit": "KG"})
        self.assertIsNone(named("Testi lusikka 130 mm 20 kpl"))
        self.assertIsNone(named("Testi 500 grammaa"))

    def test_products_sold_by_weight_hold_one_kilogram_per_base_unit(self):
        conversions = [{"synkkaPackagingType": "BASE_UNIT_OR_EACH",
                        "volume": {"unit": "KGM", "value": 2.0}}]
        self.assertEqual(self.net(baseUnit="KG", allowedLotSize=10.0,
                                  synkka={"unitConversions": conversions}),
                         ({"value": 1.0, "unit": "KG"}, "base_unit"))
        self.assertEqual(flatten(record(allowedLotSize=10.0))["lot_size"], 10.0)

    def test_substitutions_are_a_list_of_codes(self):
        doc = flatten(record(substitutions=[{"product": "900001", "substituteProduct": "900009"}]))
        self.assertEqual(doc["substitutions"], ["900009"])


@unittest.skipUnless(mongomock, "install the test extra: pip install -e '.[test]'")
class GetProductsTests(unittest.TestCase):
    def setUp(self):
        self.db = mongomock.MongoClient()["test"]
        self.db.products.insert_many([
            {"_id": "900001", "source": "valio", "names": {"fi": "Maito"}, "raw": {"big": True}},
            {"_id": "900002", "source": "valio", "names": {"fi": "Kerma"}, "raw": {}},
            {"_id": "own-1", "source": "own", "kitchen_id": "k1", "names": {"fi": "Leipä"}},
            {"_id": "own-2", "source": "own", "kitchen_id": "k2", "names": {"fi": "Pulla"}},
        ])

    def ids(self, wanted, **kw):
        return [row["product_id"] for row in get_products(self.db, wanted, **kw)]

    def test_rows_come_in_the_order_asked_without_unknown_codes_or_raw(self):
        rows = get_products(self.db, ["900002", "nope", 900001, "900002"])
        self.assertEqual([row["product_id"] for row in rows], ["900002", "900001"])
        self.assertNotIn("raw", rows[0])
        self.assertNotIn("_id", rows[0])
        self.assertEqual(get_products(self.db, []), [])

    def test_own_products_are_only_returned_to_their_kitchen(self):
        wanted = ["900001", "own-1", "own-2"]
        self.assertEqual(self.ids(wanted), ["900001"])
        self.assertEqual(self.ids(wanted, kitchen_id="k1"), ["900001", "own-1"])
        self.assertEqual(self.ids(wanted, kitchen_id="k2"), ["900001", "own-2"])


@unittest.skipUnless(mongomock, "install the test extra: pip install -e '.[test]'")
class UpsertProductsTests(unittest.TestCase):
    @staticmethod
    def bulk_write(collection, requests, ordered=True):
        # mongomock cannot run pymongo>=4.11's ReplaceOne in bulk_write: apply each one.
        for op in requests:
            collection.replace_one(op._filter, op._doc, upsert=op._upsert)

    def setUp(self):
        patcher = mock.patch.object(mongomock.Collection, "bulk_write", self.bulk_write)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_reload_drops_stale_fields_but_keeps_the_embedding(self):
        db = mongomock.MongoClient()["test"]
        upsert_products(db, [{"_id": "900001", "names": {"fi": "Maito"}, "labels": ["luomu"]}])
        db.products.update_one({"_id": "900001"}, {"$set": {"embedding": [0.1, 0.2]}})
        upsert_products(db, [{"_id": "900001", "names": {"fi": "Maito 2"}},
                             {"_id": "900002", "names": {"fi": "Kerma"}}])
        row = db.products.find_one({"_id": "900001"})
        self.assertNotIn("labels", row)
        self.assertEqual(row["names"], {"fi": "Maito 2"})
        self.assertEqual(row["embedding"], [0.1, 0.2])
        self.assertNotIn("embedding", db.products.find_one({"_id": "900002"}))


if __name__ == "__main__":
    unittest.main()
