"""`get_db` ensures the indexes once per database name. Offline: the client is faked."""

import unittest
from unittest import mock

from store import db as store_db


class _FakeDb:
    def __init__(self, name):
        self.name = name


class _FakeClient:
    def get_database(self, name, codec_options=None):
        return _FakeDb(name)

    def get_default_database(self, default=None, codec_options=None):
        return _FakeDb(default)


class GetDbIndexTests(unittest.TestCase):
    def setUp(self):
        patches = [
            mock.patch.object(store_db, "_client", _FakeClient()),
            mock.patch.object(store_db, "_indexed", set()),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_indexes_are_ensured_once_per_database_name(self):
        with mock.patch.object(store_db, "ensure_indexes") as ensure:
            first = store_db.get_db("a")
            store_db.get_db("a")
            store_db.get_db("b")
            store_db.get_db()
            store_db.get_db()
        names = [call.args[0].name for call in ensure.call_args_list]
        self.assertEqual(names, ["a", "b", store_db.DEFAULT_DB])
        self.assertEqual(first.name, "a")


if __name__ == "__main__":
    unittest.main()
