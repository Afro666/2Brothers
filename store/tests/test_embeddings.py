"""Embeddings and hybrid search without the real model: a fake embedder and fake HTTP."""

import json
import os
from pathlib import Path
import unittest
from unittest import mock
from uuid import uuid4

from bson.binary import BinaryVectorDtype
import httpx

from store import embeddings
from store.embeddings import (EMBED_DIMENSIONS, EmbeddingError, embed, embed_products,
                              product_text, stale)
from store.products import upsert_products
from store.search import build_hybrid_pipeline, search_products, vector_filter


def fake_embedder(texts, input_type):
    """One distinct, right-sized vector per text."""
    return [[float(len(text))] + [0.0] * (EMBED_DIMENSIONS - 1) for text in texts]


class Response:
    def __init__(self, status, vectors=()):
        self.status_code = status
        self._data = [{"index": i, "embedding": v} for i, v in enumerate(vectors)]

    def json(self):
        return {"data": list(reversed(self._data))}  # the service may answer out of order


class ProductTextTests(unittest.TestCase):
    def test_text_has_names_brand_claims_and_ingredients(self):
        doc = {"names": {"fi": "Testi kaurajuoma 1 l", "en": "Testi oat drink 1 l", "sv": "x"},
               "brand": "Testi", "claims": ["FREE_FROM_LACTOSE", "VEGAN"], "category": "10402",
               "raw": {"synkkaData": {"keyIngredients": [
                   {"language": "fi", "value": "vesi, KAURA"}, {"language": "en", "value": "water, OATS"}]}}}
        self.assertEqual(product_text(doc), "Testi kaurajuoma 1 l. Testi oat drink 1 l. Testi. "
                                            "free from lactose. vegan. water, OATS")

    def test_an_own_product_with_one_name_is_not_repeated(self):
        self.assertEqual(product_text({"names": {"fi": "Ruisleipä", "en": "Ruisleipä"}}), "Ruisleipä")
        self.assertEqual(product_text({}), "")


class EmbedTests(unittest.TestCase):
    def call(self, responses, texts=("a", "b")):
        posts, sleeps = [], []

        def post(url, **kwargs):
            posts.append((url, kwargs))
            return responses[len(posts) - 1]
        with mock.patch.dict("os.environ", {"NVIDIA_API_KEY": "test-not-a-real-key"}):
            return embed(list(texts), "passage", post=post, sleep=sleeps.append), posts, sleeps

    def test_request_and_answer_order(self):
        vectors = [[1.0] * EMBED_DIMENSIONS, [2.0] * EMBED_DIMENSIONS]
        result, posts, _ = self.call([Response(200, vectors)])
        self.assertEqual(result, vectors)
        url, kwargs = posts[0]
        self.assertEqual(url, embeddings.EMBED_URL)
        self.assertEqual(kwargs["json"]["model"], embeddings.EMBED_MODEL)
        self.assertEqual(kwargs["json"]["input_type"], "passage")
        self.assertEqual(kwargs["json"]["dimensions"], EMBED_DIMENSIONS)
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer test-not-a-real-key")

    def test_a_rate_limit_is_retried_and_other_errors_are_not(self):
        vectors = [[1.0] * EMBED_DIMENSIONS, [2.0] * EMBED_DIMENSIONS]
        result, posts, sleeps = self.call([Response(429), Response(503), Response(200, vectors)])
        self.assertEqual((len(posts), sleeps), (3, [1, 2]))
        self.assertEqual(result, vectors)
        with self.assertRaises(EmbeddingError) as caught:
            self.call([Response(401)])
        self.assertNotIn("test-not-a-real-key", str(caught.exception))

    def test_wrong_size_or_count_is_refused(self):
        with self.assertRaises(EmbeddingError):
            self.call([Response(200, [[1.0] * 8, [2.0] * 8])])
        with self.assertRaises(EmbeddingError):
            self.call([Response(200, [[1.0] * EMBED_DIMENSIONS])])

    def test_a_missing_key_or_network_error_is_an_embedding_error(self):
        with mock.patch.dict("os.environ", {"NVIDIA_API_KEY": ""}):
            with self.assertRaises(EmbeddingError):
                embed(["a"], "query", post=lambda *a, **k: Response(200))

        def broken(url, **kwargs):
            raise httpx.ConnectError("no route")
        with mock.patch.dict("os.environ", {"NVIDIA_API_KEY": "test-not-a-real-key"}):
            with self.assertRaises(EmbeddingError):
                embed(["a"], "query", post=broken)


class StaleTests(unittest.TestCase):
    def test_only_new_changed_or_differently_embedded_rows_are_stale(self):
        def row(product_id, name, **embedding):
            return {"_id": product_id, "names": {"fi": name}, "embedding": embedding or None}
        fresh = stale([row("900001", "Testi maito")])
        self.assertEqual([(i, text) for i, text, _ in fresh], [("900001", "Testi maito")])
        sha = fresh[0][2]
        current = dict(model=embeddings.EMBED_MODEL, dimensions=EMBED_DIMENSIONS, text_sha=sha)
        self.assertEqual(stale([row("900001", "Testi maito", **current)]), [])
        for changed in (row("900001", "Testi laktoositon maito", **current),
                        row("900001", "Testi maito", **{**current, "model": "another/model"}),
                        row("900001", "Testi maito", **{**current, "dimensions": 384})):
            self.assertEqual(len(stale([changed])), 1)
        self.assertEqual(stale([{"_id": "900003", "names": {}}]), [])  # nothing to embed


@unittest.skipUnless(os.environ.get("STORE_LIVE_TESTS") == "1", "set STORE_LIVE_TESTS=1")
class LiveEmbedProductsTests(unittest.TestCase):
    """Bulk writes on real MongoDB, with the fake embedder: a throwaway database."""

    def setUp(self):
        from store.db import get_db
        self.db = get_db(f"two_brothers_test_{uuid4().hex[:8]}")
        self.addCleanup(self.db.client.drop_database, self.db.name)
        upsert_products(self.db, [
            {"_id": "900001", "names": {"fi": "Testi maito"}, "brand": "Testi", "claims": []},
            {"_id": "900002", "names": {"fi": "Testi kaurajuoma"}, "brand": None, "claims": ["VEGAN"]},
            {"_id": "900003", "names": {}, "brand": None, "claims": []}])  # nothing to embed

    def test_only_new_and_changed_products_are_embedded(self):
        self.assertEqual(embed_products(self.db, fake_embedder), 2)
        stored = self.db.products.find_one({"_id": "900001"})["embedding"]
        self.assertEqual((stored["model"], stored["dimensions"]),
                         (embeddings.EMBED_MODEL, EMBED_DIMENSIONS))
        vector = stored["vector"].as_vector()
        self.assertEqual((vector.dtype, len(vector.data)), (BinaryVectorDtype.FLOAT32, EMBED_DIMENSIONS))
        self.assertNotIn("embedding", self.db.products.find_one({"_id": "900003"}))
        self.assertEqual(embed_products(self.db, fake_embedder), 0)  # nothing changed
        upsert_products(self.db, [{"_id": "900001", "names": {"fi": "Testi laktoositon maito"},
                                   "brand": "Testi", "claims": []}])
        self.assertEqual(embed_products(self.db, fake_embedder), 1)  # only the renamed one

    def test_reloading_the_catalog_keeps_the_vectors_and_readers_never_see_them(self):
        from store.products import get_product, get_products
        embed_products(self.db, fake_embedder)
        upsert_products(self.db, [{"_id": "900002", "names": {"fi": "Testi kaurajuoma"},
                                   "brand": None, "claims": ["VEGAN"], "category": "10402"}])
        row = self.db.products.find_one({"_id": "900002"})
        self.assertEqual(row["category"], "10402")
        self.assertIn("embedding", row)
        self.assertEqual(embed_products(self.db, fake_embedder), 0)
        self.assertNotIn("embedding", get_product(self.db, "900002"))
        self.assertNotIn("embedding", get_product(self.db, "900002", raw=True))
        self.assertNotIn("embedding", get_products(self.db, ["900002"])[0])

    def test_a_wrong_size_vector_is_never_stored(self):
        with self.assertRaises(EmbeddingError):
            embed_products(self.db, lambda texts, kind: [[0.5] * 8 for _ in texts])
        self.assertIsNone(self.db.products.find_one({"embedding": {"$exists": True}}))


class HybridQueryTests(unittest.TestCase):
    def test_vector_filter_keeps_every_hard_filter(self):
        clauses = vector_filter({"exclude_allergens": ["milk"], "allergen_strictness": "strict",
                                 "require_labels": ["EU_ORGANIC_FARMING"], "temperature": "chilled",
                                 "pack_size": {"value": 1, "unit": "l"}}, kitchen_id="k1")["$and"]
        self.assertIn({"$or": [{"source": {"$ne": "own"}}, {"kitchen_id": "k1"}]}, clauses)
        for level in ("contains", "may_contain", "undeclared"):
            self.assertIn({f"allergens.{level}": {"$nin": ["AM"]}}, clauses)
        self.assertIn({"allergen_data_known": {"$ne": False}}, clauses)
        self.assertIn({"labels": "EU_ORGANIC_FARMING"}, clauses)
        self.assertIn({"temperature": "chilled"}, clauses)
        self.assertIn({"net_content.unit": "L"}, clauses)

    def test_declared_mode_keeps_unknown_products_and_no_kitchen_means_catalog_only(self):
        clauses = vector_filter({"exclude_allergens": ["AM"]})["$and"]
        self.assertEqual(clauses, [{"$or": [{"source": {"$ne": "own"}}]},
                                   {"allergens.contains": {"$nin": ["AM"]}},
                                   {"allergens.may_contain": {"$nin": ["AM"]}}])

    def test_hybrid_pipeline_fuses_text_and_vector_over_the_same_filters(self):
        pipeline = build_hybrid_pipeline("oat drink", "VECTOR", {"exclude_allergens": ["gluten"]}, 5, "k1")
        sides = pipeline[0]["$rankFusion"]["input"]["pipelines"]
        self.assertEqual(sorted(sides), ["text", "vector"])
        self.assertIn("mustNot", sides["text"][0]["$search"]["compound"])
        vector = sides["vector"][0]["$vectorSearch"]
        self.assertEqual((vector["index"], vector["path"], vector["queryVector"]),
                         ("products_vector", "embedding.vector", "VECTOR"))
        self.assertIn({"allergens.contains": {"$nin": ["AW", "GB", "GK", "GS", "NR", "UW"]}},
                      vector["filter"]["$and"])
        self.assertIn({"$limit": 5}, pipeline)
        self.assertIn({"$project": {"raw": 0, "embedding": 0}}, pipeline)
        with self.assertRaises(ValueError):
            build_hybrid_pipeline("oat drink", "VECTOR", {"exclude_allergens": ["mlik"]})

    def test_bad_filters_are_refused_before_the_embedding_call(self):
        calls = []
        with self.assertRaises(ValueError):
            search_products(None, "milk", {"colour": "red"}, hybrid=True,
                            embedder=lambda texts, kind: calls.append(texts))
        self.assertEqual(calls, [])

    def test_index_definition_matches_the_model(self):
        fields = json.loads(Path(__file__).parents[1].joinpath("vector_index.json").read_text())["fields"]
        self.assertEqual(fields[0]["numDimensions"], EMBED_DIMENSIONS)
        paths = {field["path"] for field in fields if field["type"] == "filter"}
        for needed in ("allergens.contains", "allergens.may_contain", "allergens.undeclared",
                       "allergen_data_known", "labels", "source", "kitchen_id"):
            self.assertIn(needed, paths)


if __name__ == "__main__":
    unittest.main()
