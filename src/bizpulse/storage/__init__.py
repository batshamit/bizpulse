"""Storage layer — tenant / business / run persistence.

Phase-9 ships an in-memory impl. A Postgres impl arrives in a follow-up commit
under the same protocol so callers don't change.
"""

from __future__ import annotations

from bizpulse.storage.memory import (
    InMemoryStore,
    get_default_store,
    reset_default_store_for_tests,
)

__all__ = ["InMemoryStore", "get_default_store", "reset_default_store_for_tests"]
