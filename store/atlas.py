"""What MongoDB Atlas holds and runs for this product, read live (#1393, for #1383).

For a page that shows the Atlas features to a person. Counts and index states only:
never an address, a key or a document. A part that cannot be read is None (unknown),
never zero.
"""

from __future__ import annotations

from store.trust import WATCHED

HAS_VECTOR = {"embedding.vector": {"$exists": True}}


def _read(part):
    try:
        return part()
    except Exception:  # not Atlas, no rights, a test database: unknown, and the page still loads
        return None


def _megabytes(db) -> int:
    stats = db.command("dbstats")
    return round((stats["dataSize"] + stats["indexSize"]) / 1e6)


def _vectors(db) -> list[dict]:
    """One row per model and size: two rows while the vectors are being replaced."""
    groups = db.products.aggregate([
        {"$match": HAS_VECTOR},
        {"$group": {"_id": {"model": "$embedding.model", "dimensions": "$embedding.dimensions"},
                    "count": {"$sum": 1}}}])
    rows = [{"model": g["_id"].get("model"), "dimensions": g["_id"].get("dimensions"),
             "count": g["count"]} for g in groups]
    return sorted(rows, key=lambda row: -row["count"])


def _search_indexes(db) -> list[dict]:
    return [{"name": index["name"], "type": index.get("type") or "search",
             "status": index.get("status"), "queryable": index.get("queryable")}
            for index in db.products.list_search_indexes()]


def _time_series(db) -> list[dict]:
    names = sorted(c["name"] for c in db.list_collections(filter={"type": "timeseries"}))
    return [{"collection": name, "documents": db[name].count_documents({})} for name in names]


def atlas_facts(db) -> dict:
    """The live numbers behind each Atlas feature the product uses."""
    return {
        "mongodb_version": _read(lambda: db.client.server_info()["version"]),
        "data_mb": _read(lambda: _megabytes(db)),                    # data + indexes
        "products": _read(db.products.estimated_document_count),     # Atlas Search reads these
        "vectors": _read(lambda: _vectors(db)),                      # Atlas Vector Search
        "search_indexes": _read(lambda: _search_indexes(db)),
        "time_series": _read(lambda: _time_series(db)),              # behind the drift aggregation
        "audit_entries": _read(db.audit_log.estimated_document_count),  # the hash chain's length
        "change_stream_collections": list(WATCHED),                  # the live inbox
    }
