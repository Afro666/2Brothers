"""Short-lived computed kitchen facts, owned by one database-bound Buyer worker."""
from collections import OrderedDict
from copy import deepcopy
from threading import Lock
from time import monotonic


class KitchenFactsCache:
    def __init__(self, *, keep=60, max_entries=128, clock=monotonic):
        self.keep, self.max_entries, self.clock = keep, max_entries, clock
        self._entries = OrderedDict()
        self._lock = Lock()  # guards _entries and _loading only, never a load
        self._loading = {}  # key -> [per-key lock, threads using it]

    def _cached(self, key):
        with self._lock:
            cached = self._entries.get(key)
            if cached is not None and self.clock() < cached[0]:
                self._entries.move_to_end(key)
                return True, deepcopy(cached[1])
            self._entries.pop(key, None)
            return False, None

    def get(self, kitchen, day, load, *, revision=None):
        """Coalesce reads per kitchen/day in worker threads; failed reads are never kept."""
        key = (kitchen, day, revision)
        hit, facts = self._cached(key)
        if hit:
            return facts
        with self._lock:
            slot = self._loading.setdefault(key, [Lock(), 0])
            slot[1] += 1
        try:
            with slot[0]:
                hit, facts = self._cached(key)
                if hit:
                    return facts
                facts = load()
                with self._lock:
                    self._entries[key] = (self.clock() + self.keep, deepcopy(facts))
                    while len(self._entries) > self.max_entries:
                        self._entries.popitem(last=False)
                return facts
        finally:
            with self._lock:
                slot[1] -= 1
                if not slot[1]:
                    del self._loading[key]
