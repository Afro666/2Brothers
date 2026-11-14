"""Load the Valio catalog into MongoDB: `python -m store.loader [--dir vendor/valio] [--skip-embeddings]`.

Reads the three files downloaded from the Valio API (see store/README.md), flattens
every product, upserts in batches and creates the indexes, including the Atlas
Search index. Safe to run again. `--skip-embeddings` skips the product vectors (they
can take hours on a free-tier embedding API); run `python -m store.embeddings` later.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from pymongo.errors import OperationFailure

from store.db import ensure_indexes, get_db
from store.products import flatten, upsert_products
from store.embeddings import embed_products
from store.search import ensure_search_index, ensure_vector_index

PREFIX = "valio_aimo_junction26_"


def _by_product(path: Path) -> dict[str, float]:
    """`productId,<value>` rows -> {code: value}. A missing file means all unknown."""
    if not path.exists():
        print(f"warning: {path.name} not found; those values stay unknown")
        return {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = csv.reader(handle)
        next(rows)
        return {row[0]: float(row[1]) for row in rows if row and row[1] != ""}


def load(directory: Path, db) -> int:
    reliability = _by_product(directory / f"{PREFIX}delivery_reliability.csv")
    carbon = _by_product(directory / f"{PREFIX}carbon_footprint.csv")
    with (directory / f"{PREFIX}product_data.json").open(encoding="utf-8") as handle:
        records = json.load(handle)
    docs = [flatten(r, reliability.get(str(r["id"])), carbon.get(str(r["id"]))) for r in records]
    if len({doc["_id"] for doc in docs}) != len(docs):
        raise ValueError("duplicate product codes in the catalog file")
    ensure_indexes(db)
    return upsert_products(db, docs)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dir", type=Path, default=Path("vendor/valio"))
    parser.add_argument("--skip-embeddings", action="store_true",
                        help="do not embed products or create the vector index")
    args = parser.parse_args()
    db = get_db()
    count = load(args.dir, db)
    stats = db.command("dbstats")
    megabytes = (stats["dataSize"] + stats["indexSize"]) / 1e6
    print(f"upserted {count} products; products in {db.name}: {db.products.count_documents({})}")
    print(f"data + indexes: {megabytes:.0f} MB of the 512 MB free tier")
    try:
        print(f"search index: {ensure_search_index(db)}")
    except OperationFailure as exc:  # not Atlas, or no search-index rights
        print(f"search index: not created ({exc})")
    from store import embeddings
    if args.skip_embeddings:
        print("embeddings skipped (--skip-embeddings); run `python -m store.embeddings` later")
    elif embeddings.provider() is None:
        print("embeddings skipped: no embedding key is set (hybrid search needs them)")
    else:
        try:
            print(f"embedded {embed_products(db)} new or changed products")
            print(f"vector index: {ensure_vector_index(db)}")
        except (embeddings.EmbeddingError, OperationFailure) as exc:
            print(f"embeddings: not finished ({exc})")


if __name__ == "__main__":
    main()
