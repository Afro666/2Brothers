"""Atlas facts route (#1383). Contract: docs/contract.md, "Atlas facts".

- GET /v1/kitchens/{kitchen_id}/atlas (`kitchen:read`): what MongoDB Atlas holds and runs
  for the product, for the About page. A thin wrapper over `store.atlas.atlas_facts`.
- The numbers are for the whole database, so one answer serves every kitchen. It is kept
  for a minute: about ten small reads per answer, and the page may be open on many phones.
- Counts and index states only: the store function never reads an address or a key.
"""

from __future__ import annotations

import threading
import time
from typing import Callable

from fastapi import Depends, FastAPI

from store.atlas import atlas_facts

KEEP_SECONDS = 60.0


class FactsCache:
    """One answer, kept for KEEP_SECONDS. A failed read is never kept."""

    def __init__(self, facts: Callable = atlas_facts, clock: Callable[[], float] = time.monotonic,
                 keep: float = KEEP_SECONDS) -> None:
        self._facts, self._clock, self._keep = facts, clock, keep
        self._answer: dict | None = None
        self._read_at = 0.0
        self._lock = threading.Lock()

    def get(self, db) -> dict:
        with self._lock:
            now = self._clock()
            if self._answer is None or now - self._read_at >= self._keep:
                self._answer = self._facts(db)
                self._read_at = now
            return self._answer


def mount_atlas(app: FastAPI, gw, principal) -> None:
    cache = FactsCache()        # one per app

    @app.get("/v1/kitchens/{kitchen_id}/atlas")
    def atlas(kitchen_id: str, who=Depends(principal)):
        who.need("kitchen:read", kitchen_id)
        return cache.get(gw().db)
