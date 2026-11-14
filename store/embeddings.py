"""Product embeddings for semantic search (Atlas Vector Search, #366).

One vector per product, kept on the product row under `embedding` as float32 binary,
with the model name and dimension beside it. Two embedding services are supported; the
first whose key is set is used:

- `NVIDIA_API_KEY`: NVIDIA's Nemotron embedding model.
- `MONGODB_AI_API_KEY` (and `MONGODB_AI_ENDPOINT`, default `ai.mongodb.com`): MongoDB's
  embedding API, model `voyage-4`. Checked live on 2026-11-14: 1024 dimensions.

`python -m store.embeddings` embeds the products that have no current vector: new rows,
rows whose text changed, and rows embedded with another model or size.

A machine can hold the embedding key or the database address, not always both. So the
vectors can also travel as a file:

    python -m store.embeddings --export-from vendor/valio/valio_aimo_junction26_product_data.json --out vectors.jsonl.gz
    python -m store.embeddings --import-from vectors.jsonl.gz     # needs no key

The export reads the catalog file and calls the embedding service; the import writes the
vectors to the product rows whose text is still the same.
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import json
import os
from pathlib import Path
import struct
import time

from bson.binary import Binary, BinaryVectorDtype
from dotenv import load_dotenv
import httpx
from pymongo import UpdateOne

EMBED_DIMENSIONS = 1024  # must equal numDimensions in store/vector_index.json
PROVIDERS = {
    # name: (key variable, model, what "a product" and "a search" are called there)
    "nvidia": ("NVIDIA_API_KEY", "nvidia/nemotron-3.5-embed-1b", {"passage": "passage", "query": "query"}),
    "mongodb": ("MONGODB_AI_API_KEY", "voyage-4", {"passage": "document", "query": "query"}),
}
EMBED_MODEL = PROVIDERS["nvidia"][1]   # the first provider's model, for callers that name it
EMBED_URL = "https://integrate.api.nvidia.com/v1/embeddings"


class EmbeddingError(RuntimeError):
    """The embedding service failed. Never carries the key or a response body."""


def provider() -> str | None:
    """Which embedding service this machine can call, or None when no key is set."""
    load_dotenv()
    for name, (variable, _, _) in PROVIDERS.items():
        if os.environ.get(variable):
            return name
    return None


def current_model() -> str | None:
    name = provider()
    return PROVIDERS[name][1] if name else None


def _request(name: str, texts: list[str], input_type: str) -> tuple[str, dict]:
    _, model, kinds = PROVIDERS[name]
    if name == "nvidia":
        return EMBED_URL, {"model": model, "input": texts, "input_type": kinds[input_type],
                           "dimensions": EMBED_DIMENSIONS, "encoding_format": "float", "truncate": "END"}
    host = (os.environ.get("MONGODB_AI_ENDPOINT") or "ai.mongodb.com").strip().rstrip("/")
    base = host if host.startswith("http") else f"https://{host}"
    return f"{base}/v1/embeddings", {"model": model, "input": texts, "input_type": kinds[input_type],
                                     "output_dimension": EMBED_DIMENSIONS}


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


def text_sha(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()


def embed(texts: list[str], input_type: str, post=httpx.post, sleep=time.sleep) -> list[list[float]]:
    """Vectors for `texts`. `input_type` is "passage" for products and "query" for a search.

    Retries a rate limit or a server error a few times; any other failure raises.
    """
    name = provider()
    if name is None:
        raise EmbeddingError("no embedding key is set (NVIDIA_API_KEY or MONGODB_AI_API_KEY)")
    key = os.environ[PROVIDERS[name][0]]
    url, body = _request(name, texts, input_type)
    for attempt in range(5):
        try:
            response = post(url, json=body, timeout=60,
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


def stale(docs, model: str | None = None) -> list[tuple[str, str, str]]:
    """`(product_id, text, text_sha)` for rows whose vector is missing or out of date:
    a new row, a changed text, another model or another size."""
    model = model or current_model() or EMBED_MODEL
    todo = []
    for doc in docs:
        text = product_text(doc)
        sha = text_sha(text)
        have = doc.get("embedding") or {}
        current = (have.get("model"), have.get("dimensions"), have.get("text_sha"))
        if text and current != (model, EMBED_DIMENSIONS, sha):
            todo.append((doc["_id"], text, sha))
    return todo


def embed_products(db, embedder=embed, batch_size: int = 64) -> int:
    """Embed every product without a current vector. Returns how many were embedded.

    Written batch by batch, so an interrupted run continues where it stopped.
    """
    fields = {"names": 1, "brand": 1, "claims": 1, "raw.synkkaData.keyIngredients": 1,
              "embedding.model": 1, "embedding.dimensions": 1, "embedding.text_sha": 1}
    model = current_model() or EMBED_MODEL
    todo = stale(db.products.find({}, fields), model)
    for start in range(0, len(todo), batch_size):
        batch = todo[start:start + batch_size]
        vectors = embedder([text for _, text, _ in batch], "passage")
        if len(vectors) != len(batch) or any(len(v) != EMBED_DIMENSIONS for v in vectors):
            raise EmbeddingError("embedder returned the wrong number or size of vectors")
        db.products.bulk_write([
            UpdateOne({"_id": product_id}, {"$set": {"embedding": {
                "vector": to_binary(vector), "model": model,
                "dimensions": EMBED_DIMENSIONS, "text_sha": sha}}})
            for (product_id, _, sha), vector in zip(batch, vectors)], ordered=False)
    return len(todo)


def _pack(vector: list[float]) -> str:
    return base64.b64encode(struct.pack(f"<{len(vector)}f", *vector)).decode()


def _unpack(text: str) -> list[float]:
    raw = base64.b64decode(text)
    return list(struct.unpack(f"<{len(raw) // 4}f", raw))


def _lines(path: Path):
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def export_vectors(catalog: Path, out: Path, embedder=embed, batch_size: int = 96,
                   limit: int | None = None, log=print) -> int:
    """Embed every product of a catalog file into a gzip JSON-lines file: a first line
    with the model and size, then one `{product_id, text_sha, vector}` a line.

    Needs the embedding key, not the database. A run that stopped can be started again:
    products already in the file are skipped. Returns how many were embedded now.
    """
    from store.products import flatten

    model = current_model() or EMBED_MODEL
    done: set[str] = set()
    if out.exists():
        rows = _lines(out)
        first = next(rows, {})
        if (first.get("model"), first.get("dimensions")) != (model, EMBED_DIMENSIONS):
            raise EmbeddingError(f"{out.name} holds vectors of another model or size")
        done = {row["product_id"] for row in rows}
    todo = []
    for raw in json.loads(catalog.read_text(encoding="utf-8")):
        doc = flatten(raw)
        text = product_text({**doc, "raw": raw})
        if text and doc["_id"] not in done:
            todo.append((doc["_id"], text))
    if limit is not None:
        todo = todo[:limit]
    fresh = not out.exists()
    with gzip.open(out, "at", encoding="utf-8") as handle:
        if fresh:
            handle.write(json.dumps({"model": model, "dimensions": EMBED_DIMENSIONS}) + "\n")
        for start in range(0, len(todo), batch_size):
            batch = todo[start:start + batch_size]
            vectors = embedder([text for _, text in batch], "passage")
            if len(vectors) != len(batch) or any(len(v) != EMBED_DIMENSIONS for v in vectors):
                raise EmbeddingError("embedder returned the wrong number or size of vectors")
            for (product_id, text), vector in zip(batch, vectors):
                handle.write(json.dumps({"product_id": product_id, "text_sha": text_sha(text),
                                         "vector": _pack(vector)}) + "\n")
            handle.flush()
            log(f"embedded {min(start + batch_size, len(todo))} of {len(todo)}")
    return len(todo)


def import_vectors(db, source: Path, batch_size: int = 500) -> dict[str, int]:
    """Write the vectors of an export file to the product rows. Needs no key.

    A vector is written only when the row exists and its text is still the text that was
    embedded; a changed or missing product is counted and left alone.
    """
    fields = {"names": 1, "brand": 1, "claims": 1, "raw.synkkaData.keyIngredients": 1}
    counts = {"written": 0, "text_changed": 0, "missing": 0}
    rows = _lines(source)
    first = next(rows)
    model, dimensions = first["model"], first["dimensions"]
    if dimensions != EMBED_DIMENSIONS:
        raise EmbeddingError("the file's vectors do not fit the vector index")

    def flush(batch: list[dict]) -> None:
        docs = {doc["_id"]: doc for doc in db.products.find(
            {"_id": {"$in": [row["product_id"] for row in batch]}}, fields)}
        writes = []
        for row in batch:
            doc = docs.get(row["product_id"])
            if doc is None:
                counts["missing"] += 1
                continue
            if text_sha(product_text(doc)) != row["text_sha"]:
                counts["text_changed"] += 1
                continue
            vector = _unpack(row["vector"])
            if len(vector) != EMBED_DIMENSIONS:
                raise EmbeddingError("a vector in the file has the wrong size")
            writes.append(UpdateOne({"_id": row["product_id"]}, {"$set": {"embedding": {
                "vector": to_binary(vector), "model": model, "dimensions": dimensions,
                "text_sha": row["text_sha"]}}}))
        if writes:
            db.products.bulk_write(writes, ordered=False)
            counts["written"] += len(writes)

    batch: list[dict] = []
    for row in rows:
        batch.append(row)
        if len(batch) >= batch_size:
            flush(batch)
            batch = []
    if batch:
        flush(batch)
    return counts


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--export-from", type=Path, help="catalog JSON file to embed into --out")
    parser.add_argument("--out", type=Path, default=Path("vectors.jsonl.gz"))
    parser.add_argument("--import-from", type=Path, help="vectors file to write to the database")
    parser.add_argument("--limit", type=int, help="export only the first N products (a test run)")
    args = parser.parse_args()
    if args.export_from:
        count = export_vectors(args.export_from, args.out, limit=args.limit)
        print(f"exported {count} vectors to {args.out} with {current_model()} ({EMBED_DIMENSIONS} dims)")
        return
    from store.db import get_db
    from store.search import ensure_vector_index

    db = get_db()
    if args.import_from:
        print(f"imported: {import_vectors(db, args.import_from)}")
    else:
        print(f"embedded {embed_products(db)} products with {current_model()} ({EMBED_DIMENSIONS} dims)")
    print(f"vector index: {ensure_vector_index(db)}")


if __name__ == "__main__":
    main()
