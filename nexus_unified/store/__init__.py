"""nexus_unified.store — magasins open source enfichables (point 7)."""
from .backends import (
    RecordStore, JSONLStore, SQLiteStore, PostgresStore, Neo4jStore,
    open_store, StoreUnavailable,
)

__all__ = ["RecordStore", "JSONLStore", "SQLiteStore", "PostgresStore",
           "Neo4jStore", "open_store", "StoreUnavailable"]
