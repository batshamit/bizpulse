"""Storage layer — tenant / business / run persistence.

Two backends ship today; both expose the same method surface so callers
swap via env var (`BIZPULSE_STORE=memory|postgres`).

  - InMemoryStore   in-process dict; default; what tests use.
  - PostgresStore   psycopg-pool against the bizpulse schema in init.sql.

`get_default_store()` returns whichever is configured. Tests should call
`reset_default_store_for_tests()` to wipe the singleton.
"""

from __future__ import annotations

import contextlib
import os

from bizpulse.storage.memory import InMemoryStore
from bizpulse.storage.postgres import PostgresStore

Store = InMemoryStore | PostgresStore


_default_store: Store | None = None


def get_default_store() -> Store:
    global _default_store
    if _default_store is not None:
        return _default_store
    backend = os.environ.get("BIZPULSE_STORE", "memory").lower()
    _default_store = PostgresStore() if backend == "postgres" else InMemoryStore()
    return _default_store


def reset_default_store_for_tests() -> None:
    """Wipe the singleton so tests start from a fresh InMemoryStore.

    If the previous singleton was a PostgresStore, close its connection
    pool first — otherwise the orphaned pool keeps holding PG connections
    and successive test resets exhaust max_connections (we hit ~100
    leaked conns after ~15 resets in CI).

    Note: when BIZPULSE_STORE=postgres, this re-creates a PostgresStore
    pointing at the same DB — it does NOT truncate tables. Tests that
    target Postgres must clean up after themselves.
    """
    global _default_store
    if _default_store is not None and isinstance(_default_store, PostgresStore):
        with contextlib.suppress(Exception):
            _default_store.close()
    _default_store = None


__all__ = [
    "InMemoryStore",
    "PostgresStore",
    "Store",
    "get_default_store",
    "reset_default_store_for_tests",
]
