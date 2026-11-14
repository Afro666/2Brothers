import io
import unittest
from contextlib import redirect_stdout
from unittest import mock

from pymongo.errors import OperationFailure

from store import loader


class LoaderTests(unittest.TestCase):
    def test_no_atlas_search_still_finishes(self):
        db = mock.MagicMock()
        db.command.return_value = {"dataSize": 0, "indexSize": 0}
        out = io.StringIO()
        with mock.patch("sys.argv", ["loader"]), \
                mock.patch.object(loader, "get_db", return_value=db), \
                mock.patch.object(loader, "load", return_value=3), \
                mock.patch.object(loader, "ensure_search_index",
                                  side_effect=OperationFailure("not Atlas")), \
                redirect_stdout(out):
            loader.main()
        self.assertIn("search index: not created (not Atlas)", out.getvalue())


if __name__ == "__main__":
    unittest.main()
