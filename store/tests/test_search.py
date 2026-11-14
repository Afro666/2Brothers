import json
from pathlib import Path
import unittest

from store.search import _reasons, allergen_codes, build_pipeline, parse_query


def compound(query="", filters=None, **kw):
    return build_pipeline(query, filters, **kw)[0]["$search"]["compound"]


class SearchQueryTests(unittest.TestCase):
    def test_size_is_read_from_the_query_text(self):
        self.assertEqual(parse_query("lactose free milk 1 l"),
                         ("lactose free milk", {"value": 1.0, "unit": "L"}))
        self.assertEqual(parse_query("butter 500g"), ("butter", {"value": 0.5, "unit": "KG"}))
        self.assertEqual(parse_query("cream 2,5 dl"), ("cream", {"value": 0.25, "unit": "L"}))
        self.assertEqual(parse_query("juice 33 cl")[1], {"value": 0.33, "unit": "L"})
        self.assertEqual(parse_query("yoghurt 150 ml")[1], {"value": 0.15, "unit": "L"})
        self.assertEqual(parse_query("carrot 10 KG")[1], {"value": 10.0, "unit": "KG"})
        self.assertEqual(parse_query("vitamin b12 gel"), ("vitamin b12 gel", None))
        self.assertEqual(parse_query("  3 % milk "), ("3 % milk", None))
        self.assertEqual(parse_query(None), ("", None))

    def test_allergens_by_name_or_gs1_code(self):
        self.assertEqual(allergen_codes(["milk"]), ["AM"])
        self.assertEqual(allergen_codes(["Milk", "am", "AE"]), ["AE", "AM"])
        self.assertIn("UW", allergen_codes(["gluten"]))
        self.assertNotIn("GO", allergen_codes(["gluten"]))  # gluten-free oats exist
        self.assertIn("SH", allergen_codes(["nuts"]))
        self.assertEqual(allergen_codes(None), [])

    def test_a_misspelt_allergen_is_an_error_not_ignored(self):
        with self.assertRaises(ValueError):
            allergen_codes(["mlik"])
        with self.assertRaises(ValueError):
            build_pipeline("bread", {"exclude_allergens": ["ZZ"]})

    def test_excluded_allergens_remove_contains_and_may_contain(self):
        clauses = compound("bread", {"exclude_allergens": ["milk"]})["mustNot"]
        self.assertEqual(clauses, [{"in": {"path": "allergens.contains", "value": ["AM"]}},
                                   {"in": {"path": "allergens.may_contain", "value": ["AM"]}}])

    def test_strict_also_drops_unknown_and_undeclared(self):
        clauses = compound("bread", {"exclude_allergens": ["AM"],
                                     "allergen_strictness": "strict"})["mustNot"]
        self.assertIn({"in": {"path": "allergens.undeclared", "value": ["AM"]}}, clauses)
        self.assertIn({"equals": {"path": "allergen_data_known", "value": False}}, clauses)
        with self.assertRaises(ValueError):
            build_pipeline("bread", {"allergen_strictness": "paranoid"})

    def test_plain_filters(self):
        filters = compound("", {"require_labels": ["EU_ORGANIC_FARMING", "FAIR_TRADE_MARK"],
                                "temperature": "frozen", "category": "10400",
                                "supplier_id": "valio_aimo"})["filter"]
        self.assertIn({"equals": {"path": "temperature", "value": "frozen"}}, filters)
        self.assertIn({"equals": {"path": "category", "value": "10400"}}, filters)
        self.assertIn({"equals": {"path": "supplier_id", "value": "valio_aimo"}}, filters)
        self.assertEqual(sum(f.get("equals", {}).get("path") == "labels" for f in filters), 2)

    def test_explicit_pack_size_filters_and_a_size_in_the_text_only_boosts(self):
        explicit = compound("milk 1 l", {"pack_size": {"value": 500, "unit": "ml"}})
        size = explicit["filter"][0]["compound"]["filter"]
        self.assertEqual(size[0], {"equals": {"path": "net_content.unit", "value": "L"}})
        self.assertAlmostEqual(size[1]["range"]["gte"], 0.495)
        self.assertAlmostEqual(size[1]["range"]["lte"], 0.505)
        self.assertEqual(explicit["must"][0]["text"]["query"], "milk")
        from_text = compound("milk 1 l")
        self.assertEqual(len(from_text["filter"]), 1)  # only the kitchen scope
        boosts = [c for c in from_text["should"] if "compound" in c]
        self.assertEqual(boosts[0]["compound"]["filter"][1]["range"]["path"], "net_content.value")

    def test_search_sees_the_catalog_and_only_the_asking_kitchens_own_products(self):
        catalog = {"compound": {"must": [{"exists": {"path": "supplier_id"}}],
                                "mustNot": [{"exists": {"path": "kitchen_id"}}]}}
        anonymous = compound("bread")["filter"][-1]["compound"]
        self.assertEqual(anonymous, {"should": [catalog], "minimumShouldMatch": 1})
        scoped = build_pipeline("bread", kitchen_id="k1")[0]["$search"]["compound"]["filter"][-1]
        self.assertEqual(scoped["compound"]["should"],
                         [catalog, {"equals": {"path": "kitchen_id", "value": "k1"}}])
        self.assertEqual(scoped["compound"]["minimumShouldMatch"], 1)

    def test_text_tolerates_one_typo_over_three_languages_and_brand(self):
        text = compound("maito")["must"][0]["text"]
        self.assertEqual(text["path"], ["names.en", "names.fi", "names.sv", "brand"])
        self.assertEqual(text["fuzzy"]["maxEdits"], 1)

    def test_bad_input_is_refused(self):
        for query, filters, limit in (("", None, 20), ("milk", {"colour": "red"}, 20),
                                      ("milk", None, 0), ("milk", None, 51), ("milk", None, True),
                                      ("milk", {"pack_size": {"value": 1, "unit": "oz"}}, 20),
                                      ("milk", {"pack_size": {"value": -1, "unit": "L"}}, 20),
                                      ("milk", {"pack_size": "1 l"}, 20),
                                      ("milk", {"require_labels": "EU_ORGANIC_FARMING"}, 20),
                                      ("milk", {"exclude_allergens": "AM"}, 20)):
            with self.assertRaises(ValueError, msg=(query, filters, limit)):
                build_pipeline(query, filters, limit)

    def test_rows_never_carry_the_raw_record(self):
        pipeline = build_pipeline("milk", limit=5)
        self.assertIn({"$project": {"raw": 0}}, pipeline)
        self.assertIn({"$limit": 5}, pipeline)

    def test_match_reasons(self):
        size = {"value": 1.0, "unit": "L"}
        doc = {"names": {"en": "Testi Lactose Free Milk 1 l"}, "allergen_data_known": False,
               "net_content": {"value": 1.0, "unit": "L"}, "net_content_source": "name",
               "allergens": {"contains": [], "may_contain": [], "undeclared": ["AE"]}}
        self.assertEqual(_reasons(doc, "lactose free milk", size, ["AE", "AM"]),
                         ["size 1 L matches", "size read from the name",
                          'name contains "lactose free milk"', "allergen data missing",
                          "eggs undeclared"])
        self.assertEqual(_reasons({"names": {}, "net_content": None, "allergen_data_known": True},
                                  "", size, []), ["size unknown"])
        self.assertEqual(_reasons({**doc, "net_content": {"value": 10.0, "unit": "L"},
                                   "allergen_data_known": True}, "", size, []), [])

    def test_index_definition_fits_the_free_tier(self):
        text = Path(__file__).parents[1].joinpath("search_index.json").read_text()
        self.assertLess(len(text.encode()), 3000)  # Atlas M0 limit: 3 KB
        fields = json.loads(text)["mappings"]["fields"]
        self.assertEqual(fields["names"]["fields"]["fi"]["analyzer"], "lucene.finnish")
        self.assertEqual(fields["names"]["fields"]["sv"]["analyzer"], "lucene.swedish")


if __name__ == "__main__":
    unittest.main()
