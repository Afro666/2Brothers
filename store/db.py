"""MongoDB connection and indexes. `store` is the only package that talks to Mongo."""

from __future__ import annotations

from decimal import Decimal
import os

from bson.codec_options import CodecOptions, TypeCodec, TypeRegistry
from bson.decimal128 import Decimal128
from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.database import Database

DEFAULT_DB = "two_brothers"


class _DecimalCodec(TypeCodec):
    """Money is `Decimal` in Python and `Decimal128` in Mongo, never a binary float."""

    python_type = Decimal
    bson_type = Decimal128

    def transform_python(self, value):
        return Decimal128(value)

    def transform_bson(self, value):
        return value.to_decimal()


CODEC = CodecOptions(type_registry=TypeRegistry([_DecimalCodec()]), tz_aware=True)
_client: MongoClient | None = None


def get_db(name: str | None = None) -> Database:
    """The database named here, else the one in `MONGODB_URI`, else `two_brothers`."""
    global _client
    if _client is None:
        load_dotenv()
        uri = os.environ.get("MONGODB_URI")
        if not uri:
            raise RuntimeError("MONGODB_URI is required; put it in .env")
        _client = MongoClient(uri, serverSelectionTimeoutMS=15000)
    if name:
        return _client.get_database(name, codec_options=CODEC)
    return _client.get_default_database(default=DEFAULT_DB, codec_options=CODEC)


def ensure_indexes(db: Database) -> None:
    """Create every index. Safe to run again: existing indexes are left alone."""
    for field in ("category", "vendor", "labels", "allergens.contains",
                  "allergens.may_contain", "temperature", "supplier_id"):
        db.products.create_index(field)
    db.offers.create_index("fetched_at")
    db.orders.create_index("idempotency_key", unique=True)
    db.approvals.create_index("idempotency_key", unique=True)
    # audit_log: `_id` is the sequence number, so the chain is linear by construction.
    db.audit_log.create_index("event.event_id", unique=True)
    db.audit_log.create_index("event.run_id")
    db.audit_log.create_index("event.order_id")
