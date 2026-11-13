"""Load the Valio catalog into MongoDB: `python -m store.loader [--dir vendor/valio]`.

Reads the three files downloaded from the Valio API (see store/README.md), flattens
every product, upserts in batches and creates the indexes. Safe to run again.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from store.db import ensure_indexes, get_db
from store.products import flatten, upsert_products

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
    args = parser.parse_args()
    db = get_db()
    count = load(args.dir, db)
    stats = db.command("dbstats")
    megabytes = (stats["dataSize"] + stats["indexSize"]) / 1e6
    print(f"upserted {count} products; products in {db.name}: {db.products.count_documents({})}")
    print(f"data + indexes: {megabytes:.0f} MB of the 512 MB free tier")


if __name__ == "__main__":
    main()
