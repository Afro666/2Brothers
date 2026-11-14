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

    def test_skip_embeddings_never_calls_the_embedding_service(self):
        db = mock.MagicMock()
        db.command.return_value = {"dataSize": 0, "indexSize": 0}
        out = io.StringIO()
        fail = AssertionError("embedding service called")
        with mock.patch("sys.argv", ["loader", "--skip-embeddings"]), \
                mock.patch.dict("os.environ", {"NVIDIA_API_KEY": "fake"}), \
                mock.patch.object(loader, "get_db", return_value=db), \
                mock.patch.object(loader, "load", return_value=3), \
                mock.patch.object(loader, "ensure_search_index", return_value="ok"), \
                mock.patch.object(loader, "embed_products", side_effect=fail), \
                mock.patch.object(loader, "ensure_vector_index", side_effect=fail), \
                mock.patch("store.embeddings.embed", side_effect=fail), \
                redirect_stdout(out):
            loader.main()
        self.assertIn("embeddings skipped (--skip-embeddings)", out.getvalue())
        self.assertIn("python -m store.embeddings", out.getvalue())


if __name__ == "__main__":
    unittest.main()
