"""Atlas facts: counts offline (mongomock), the Atlas-only parts on a throwaway database."""

import os
import unittest
from uuid import uuid4

from store.atlas import atlas_facts

try:
    import mongomock
except ImportError:  # the `test` extra is not installed
    mongomock = None


def vector(model, dimensions=1024):
    return {"vector": b"\x00", "model": model, "dimensions": dimensions}


@unittest.skipUnless(mongomock, "install the test extra: pip install -e '.[test]'")
class AtlasFactsTests(unittest.TestCase):
    def setUp(self):
        self.db = mongomock.MongoClient(tz_aware=True)["test"]

    def test_counts_products_vectors_by_model_and_audit_entries(self):
        self.db.products.insert_many([
            {"_id": "900001", "embedding": vector("voyage-4")},
            {"_id": "900002", "embedding": vector("voyage-4")},
            {"_id": "900003", "embedding": vector("another/model", 384)},
            {"_id": "900004"}])
        self.db.audit_log.insert_one({"_id": 1})
        facts = atlas_facts(self.db)
        self.assertEqual(facts["products"], 4)
        self.assertEqual(facts["vectors"], [
            {"model": "voyage-4", "dimensions": 1024, "count": 2},
            {"model": "another/model", "dimensions": 384, "count": 1}])
        self.assertEqual(facts["audit_entries"], 1)
        self.assertEqual(facts["change_stream_collections"], ["proposals", "approvals", "audit_log"])

    def test_what_cannot_be_read_is_unknown_not_zero(self):
        facts = atlas_facts(self.db)  # mongomock has no search indexes, dbstats or collection types
        self.assertEqual((facts["search_indexes"], facts["time_series"], facts["data_mb"]),
                         (None, None, None))
        self.assertEqual((facts["products"], facts["vectors"]), (0, []))  # read, and empty


@unittest.skipUnless(os.environ.get("STORE_LIVE_TESTS") == "1", "set STORE_LIVE_TESTS=1")
class LiveAtlasFactsTests(unittest.TestCase):
    def test_time_series_size_and_indexes_on_atlas(self):
        from store.db import get_db
        from store.history import ensure_history_collections
        db = get_db(f"two_brothers_test_{uuid4().hex[:8]}")
        self.addCleanup(db.client.drop_database, db.name)
        ensure_history_collections(db)
        db.products.insert_one({"_id": "900001"})
        facts = atlas_facts(db)
        self.assertIn({"collection": "covers", "documents": 0}, facts["time_series"])
        self.assertEqual(facts["search_indexes"], [])
        self.assertIsInstance(facts["data_mb"], int)
        self.assertRegex(facts["mongodb_version"], r"^\d+\.\d+")


if __name__ == "__main__":
    unittest.main()
