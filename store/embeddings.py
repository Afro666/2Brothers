"""Product embeddings for semantic search (Atlas Vector Search, #366).

One vector per product from an NVIDIA Nemotron embedding model, kept on the product
row under `embedding` as float32 binary, with the model name and dimension beside it.
`python -m store.embeddings` embeds the products that have no current vector: new
rows, rows whose text changed, and rows embedded with another model or size.
"""

from __future__ import annotations

import hashlib
import os
import time

from bson.binary import Binary, BinaryVectorDtype
from dotenv import load_dotenv
import httpx
from pymongo import UpdateOne

EMBED_MODEL = "nvidia/nemotron-3.5-embed-1b"
EMBED_DIMENSIONS = 1024  # must equal numDimensions in store/vector_index.json
EMBED_URL = "https://integrate.api.nvidia.com/v1/embeddings"


class EmbeddingError(RuntimeError):
    """The embedding service failed. Never carries the key or a response body."""


def product_text(doc: dict) -> str:
    """What is embedded for one product: names, brand, claims and key ingredients.

    The category is left out: the catalog only has 5-character codes, which carry no
    meaning for a language model.
    """
    names = doc.get("names") or {}
    parts = list(dict.fromkeys(name for name in (names.get("fi"), names.get("en")) if name))
    if doc.get("brand"):
        parts.append(doc["brand"])
    parts += [claim.replace("_", " ").lower() for claim in doc.get("claims") or []]
    listed = ((doc.get("raw") or {}).get("synkkaData") or {}).get("keyIngredients") or []
    ingredients = {item.get("language"): item.get("value") for item in listed}
    if ingredients.get("en") or ingredients.get("fi"):
        parts.append((ingredients.get("en") or ingredients.get("fi"))[:300])
    return ". ".join(parts)


def embed(texts: list[str], input_type: str, post=httpx.post, sleep=time.sleep) -> list[list[float]]:
    """Vectors for `texts`. `input_type` is "passage" for products and "query" for a search.

    Retries a rate limit or a server error a few times; any other failure raises.
    """
    load_dotenv()
    key = os.environ.get("NVIDIA_API_KEY", "")
    if not key:
        raise EmbeddingError("NVIDIA_API_KEY is not set")
    body = {"model": EMBED_MODEL, "input": texts, "input_type": input_type,
            "dimensions": EMBED_DIMENSIONS, "encoding_format": "float", "truncate": "END"}
    for attempt in range(5):
        try:
            response = post(EMBED_URL, json=body, timeout=60,
                            headers={"Authorization": f"Bearer {key}"})
        except httpx.HTTPError:
            raise EmbeddingError("embedding request failed: network error") from None
        if response.status_code == 429 or response.status_code >= 500:
            sleep(2 ** attempt)
            continue
        if response.status_code != 200:
            raise EmbeddingError(f"embedding request failed: HTTP {response.status_code}")
        rows = sorted(response.json()["data"], key=lambda row: row["index"])
        vectors = [row["embedding"] for row in rows]
        if len(vectors) != len(texts) or any(len(v) != EMBED_DIMENSIONS for v in vectors):
            raise EmbeddingError("embedding service returned the wrong number or size of vectors")
        return vectors
    raise EmbeddingError("embedding request failed: still rate-limited or failing after 5 tries")


def to_binary(vector: list[float]) -> Binary:
    """float32 binary: 4 bytes a dimension. Number arrays would not fit the free tier."""
    return Binary.from_vector(vector, BinaryVectorDtype.FLOAT32)


def stale(docs) -> list[tuple[str, str, str]]:
    """`(product_id, text, text_sha)` for rows whose vector is missing or out of date:
    a new row, a changed text, another model or another size."""
    todo = []
    for doc in docs:
        text = product_text(doc)
        sha = hashlib.sha1(text.encode()).hexdigest()
        have = doc.get("embedding") or {}
        current = (have.get("model"), have.get("dimensions"), have.get("text_sha"))
        if text and current != (EMBED_MODEL, EMBED_DIMENSIONS, sha):
            todo.append((doc["_id"], text, sha))
    return todo


def embed_products(db, embedder=embed, batch_size: int = 64) -> int:
    """Embed every product without a current vector. Returns how many were embedded.

    Written batch by batch, so an interrupted run continues where it stopped.
    """
    fields = {"names": 1, "brand": 1, "claims": 1, "raw.synkkaData.keyIngredients": 1,
              "embedding.model": 1, "embedding.dimensions": 1, "embedding.text_sha": 1}
    todo = stale(db.products.find({}, fields))
    for start in range(0, len(todo), batch_size):
        batch = todo[start:start + batch_size]
        vectors = embedder([text for _, text, _ in batch], "passage")
        if len(vectors) != len(batch) or any(len(v) != EMBED_DIMENSIONS for v in vectors):
            raise EmbeddingError("embedder returned the wrong number or size of vectors")
        db.products.bulk_write([
            UpdateOne({"_id": product_id}, {"$set": {"embedding": {
                "vector": to_binary(vector), "model": EMBED_MODEL,
                "dimensions": EMBED_DIMENSIONS, "text_sha": sha}}})
            for (product_id, _, sha), vector in zip(batch, vectors)], ordered=False)
    return len(todo)


def main() -> None:
    from store.db import get_db
    from store.search import ensure_vector_index

    db = get_db()
    print(f"embedded {embed_products(db)} products with {EMBED_MODEL} ({EMBED_DIMENSIONS} dims)")
    print(f"vector index: {ensure_vector_index(db)}")


if __name__ == "__main__":
    main()
