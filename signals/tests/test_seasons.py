import unittest
from datetime import date

from signals.seasons import calendar, chef_suggestions, in_season, match_product, season_info


class SeasonsTests(unittest.TestCase):
    def test_calendar_sources_and_months(self):
        data = calendar()
        self.assertEqual(data['region'], 'FI')
        self.assertGreaterEqual(len(data['items']), 11)
        self.assertEqual(len({e['id'] for e in data['items']}), len(data['items']))
        for entry in data['items']:
            self.assertTrue(entry['sources'])
            self.assertTrue(all(s.startswith('https://') for s in entry['sources']))
            for field in ('harvest_months', 'peak_months', 'storage_months'):
                self.assertTrue(all(type(m) is int and 1 <= m <= 12 for m in entry[field]))
            self.assertTrue(set(entry['peak_months']) <= set(entry['harvest_months']))

    def test_aliases_have_no_mojibake(self):
        for entry in calendar()['items']:
            for alias in entry['aliases']:
                self.assertNotIn('?', alias)

    def test_nordic_letter_aliases_match(self):
        self.assertEqual(match_product('keräkaali')['id'], 'cabbage')
        self.assertEqual(match_product('blåbär')['id'], 'bilberry')

    def test_strawberry_peak_and_outside_season(self):
        self.assertTrue(season_info('mansikka', date(2026, 7, 1))['peak'])
        self.assertFalse(in_season('strawberries', date(2026, 1, 1)))

    def test_storage_is_not_harvest(self):
        info = season_info('porkkana', date(2026, 12, 1))
        self.assertTrue(info['storage_season'])
        self.assertFalse(info['in_season'])

    def test_store_names_pack_brand_and_category(self):
        product = {'names': {'fi': 'Brand Luomu mansikka 5kg', 'en': 'Brand fresh strawberries 5 kg'}, 'brand': 'Brand'}
        self.assertEqual(match_product(product)['id'], 'strawberry')
        self.assertEqual(match_product({'category': 'beetroot'})['id'], 'beetroot')
        self.assertIsNone(match_product({'category': '12345'}))
        self.assertIsNone(match_product({'name': 'potatoes'}))

    def test_processed_frozen_imported_and_ambiguous_excluded(self):
        products = [
            {'name': 'strawberry jam', 'category': 'strawberry'},
            {'names': {'fi': 'mansikka', 'en': 'strawberry yogurt'}},
            {'name': 'fresh strawberries', 'temperature': 'frozen'},
            {'name': 'strawberry', 'country': 'ES'},
            {'name': 'pickled beetroot'}, {'name': 'carrot soup'},
            {'names': {'fi': 'mansikka', 'en': 'carrot'}},
        ]
        for product in products:
            with self.subTest(product=product):
                self.assertIsNone(match_product(product))

    def test_fish_wild_only_and_year_boundary(self):
        self.assertTrue(in_season('burbot', date(2026, 12, 31)))
        self.assertTrue(in_season('burbot', date(2027, 1, 1)))
        self.assertFalse(in_season('burbot', date(2027, 7, 1)))
        self.assertIsNone(match_product({'name': 'perch', 'production_method': 'farmed'}))
        self.assertEqual(match_product({'name': 'perch', 'production_method': 'wild_caught'})['id'], 'perch')
        self.assertIsNone(season_info('perch', date(2026, 5, 1))['peak'])

    def test_unknown_is_not_false_and_invalid_date_rejected(self):
        self.assertIsNone(in_season('unknown', date(2026, 7, 1)))
        with self.assertRaises(TypeError):
            in_season('carrot', '2026-07-01')

    def test_suggestions_require_origin_and_chef_approval(self):
        rows = [{'product_id': '1', 'name': 'strawberry', 'country': 'FI'},
                {'product_id': '2', 'name': 'strawberry'},
                {'product_id': '3', 'name': 'strawberry', 'country': 'ES'}]
        result = chef_suggestions(rows, date(2026, 7, 1))
        self.assertEqual([r['product_id'] for r in result], ['1'])
        self.assertTrue(result[0]['requires_chef_approval'])
        self.assertNotIn('price', result[0])
        self.assertEqual(chef_suggestions(rows, date(2026, 12, 1)), [])


if __name__ == '__main__':
    unittest.main()
