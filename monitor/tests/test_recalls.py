import json
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from monitor.recalls import audit, match, parse_date, record, scan

try:
    import mongomock
except ImportError:  # the test extra: pip install -e ".[test]"
    mongomock = None

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "ruokavirasto.json"
NOW = datetime(2026, 11, 13, 22, 0, tzinfo=timezone.utc)

# Store-shaped product documents (store.products.flatten), written by hand.
COFFEE = {"product_id": "461332", "brand": "Kulta Katriina",
          "names": {"en": "Kulta Katriina Traditional fine ground filter coffee RAC 5x1kg",
                    "fi": "Kulta Katriina Perinteinen hieno jauhatus kahvi RAC 5x1kg"},
          "units": [{"unit": "KI", "gtin": "6420105651947"}]}
EGGS = {"product_id": "463982", "brand": "Kieku",
        "names": {"en": "Kieku Barn Eggs L180 12300g", "fi": "Kieku Vapaan kanan muna L180 12300g"},
        "units": [{"unit": "KI", "gtin": "6430029763329"}]}
OATS = {"product_id": "460200", "brand": "Elovena",
        "names": {"en": "Elovena 1kg wholegrain oat flakes", "fi": "Elovena 1kg täysjyvä kaurahiutale"},
        "units": [{"unit": "ST", "gtin": "6408641027082"}]}


def kitchen(**overrides):
    k = {"kitchen_id": "K10", "name": "Hotel 1", "products": [COFFEE, EGGS, OATS],
         "stock": {"461332": (5.5, "KG"), "463982": (58.0, "KG")},
         "recipes": {"460200": ["breakfast_buffet"]}, "proposal": [],
         "replacements": {"461332": [{"product_id": "475842", "brand": "Löfbergs",
                                      "names": {"en": "Löfbergs Crescendo Ground Coffee 500g"}}]}}
    k.update(overrides)
    return k


class ParseDateTest(unittest.TestCase):
    def test_formats(self):
        self.assertEqual(parse_date("2026-10-09"), date(2026, 10, 9))
        self.assertEqual(parse_date("9. lokakuuta 2026"), date(2026, 10, 9))
        self.assertEqual(parse_date("6. maaliskuuta 2026"), date(2026, 3, 6))
        self.assertIsNone(parse_date("someday"))
        self.assertIsNone(parse_date(None))


class MatchTest(unittest.TestCase):
    def test_barcode_is_exact(self):
        level, why = match({"product_name": "Kahvi", "gtin": "6420105651947"}, COFFEE)
        self.assertEqual(level, "exact")
        self.assertIn("6420105651947", why)

    def test_same_brand_and_word_is_possible(self):
        recalled = {"product_name": "Kulta Katriina Perinteinen suodatinkahvi", "brand": "Kulta Katriina"}
        self.assertEqual(match(recalled, COFFEE)[0], "possible")

    def test_other_brand_never_matches(self):
        recalled = {"product_name": "Laitilan Kanatarha Ulko L6", "brand": "Laitilan Kanatarha",
                    "gtin": "6430017904017"}
        self.assertIsNone(match(recalled, EGGS))

    def test_same_brand_needs_a_shared_product_word(self):
        recalled = {"product_name": "Kulta Katriina Tumma paahto kahvikapselit", "brand": "Kulta Katriina"}
        self.assertEqual(match(recalled, COFFEE)[0], "possible")  # shares 'kahvi'
        self.assertIsNone(match({"product_name": "Kulta Katriina tee", "brand": "Kulta Katriina"}, COFFEE))

    def test_no_brand_needs_same_kind_of_product(self):
        self.assertEqual(match({"product_name": "Kananmunat"}, EGGS)[0], "review")
        self.assertIsNone(match({"product_name": "Valmisateria kanan ja täysjyvä riisin kanssa"}, EGGS))
        self.assertIsNone(match({"product_name": "Valmisateria kanan ja täysjyvä riisin kanssa"}, OATS))

    def test_foreign_barcode_without_brand_is_no_match(self):
        self.assertIsNone(match({"product_name": "Kananmunat", "gtin": "6410405224316"}, EGGS))


class ScanRecordedPageTest(unittest.TestCase):
    """The recorded Ruokavirasto page (Context.dev, 2026-11-13)."""

    @classmethod
    def setUpClass(cls):
        cls.notices = json.loads(FIXTURE.read_text(encoding="utf-8"))["notices"]

    def test_coffee_recall_matches_the_demo_product(self):
        alerts = scan(self.notices, kitchen(), NOW)
        self.assertEqual([(a["product_id"], a["match"]) for a in alerts], [("461332", "possible")])
        a = alerts[0]
        self.assertEqual(a["type"], "recall.alert")
        self.assertIn("2027", a["recall"]["lot"])  # the recalled best-before dates
        self.assertIn("in stock: 5.5 KG", a["where"])
        self.assertEqual(a["replacement_proposal"][0]["product_id"], "475842")
        self.assertIn("Do not use it until checked", a["next_step"])

    def test_egg_recalls_of_other_brands_do_not_alert(self):
        titles = [n["title"] for n in self.notices]
        self.assertTrue(any("Kananmun" in t for t in titles))
        self.assertFalse([a for a in scan(self.notices, kitchen(), NOW) if a["product_id"] == "463982"])

    def test_unused_product_does_not_alert(self):
        self.assertEqual(scan(self.notices, kitchen(stock={}, recipes={}), NOW), [])

    def test_old_notices_are_ignored(self):
        self.assertEqual(scan(self.notices, kitchen(), NOW, lookback_days=30), [])

    def test_event_id_is_stable(self):
        a, b = scan(self.notices, kitchen(), NOW), scan(self.notices, kitchen(), NOW)
        self.assertEqual(a[0]["event_id"], b[0]["event_id"])


@unittest.skipUnless(mongomock, "install the test extra: pip install -e '.[test]'")
class AuditTest(unittest.TestCase):
    def test_alert_lands_in_audit_log_once(self):
        from store.audit import list_events, verify_chain
        db = mongomock.MongoClient(tz_aware=True).db
        notices = json.loads(FIXTURE.read_text(encoding="utf-8"))["notices"]
        alerts = scan(notices, kitchen(), NOW)
        audit(db, alerts, NOW)
        audit(db, alerts, NOW)  # the next poll sees the same recall: a replay
        entries = list_events(db, kitchen_id="K10")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["event"]["type"], "recall.alert")
        self.assertEqual(entries[0]["server"]["principal"], "recall-monitor")
        self.assertTrue(verify_chain(db)["ok"])


class RecordTest(unittest.TestCase):
    def test_record_reads_list_then_new_details(self):
        calls = []

        class Fake:
            def scrape_json(self, url, schema):
                calls.append(url)
                if url.endswith("/takaisinvedot/"):
                    return {"recalls": [{"date": "2026-10-09", "title": "A", "url": "https://x/a"},
                                        {"date": "2026-01-02", "title": "Old", "url": "https://x/old"}]}
                return {"title": "A", "date": "9. lokakuuta 2026", "products": [{"product_name": "Munat"}]}

        data = record(Fake(), since=date(2026, 3, 1))
        self.assertEqual([n["url"] for n in data["notices"]], ["https://x/a"])
        self.assertEqual(data["notices"][0]["date"], "2026-10-09")
        self.assertNotIn("https://x/old", calls)


if __name__ == "__main__":
    unittest.main()
