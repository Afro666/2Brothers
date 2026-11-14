"""Short-lived computed kitchen facts, owned by one database-bound Buyer worker."""
from collections import OrderedDict
from copy import deepcopy
from threading import Lock
from time import monotonic


class KitchenFactsCache:
    def __init__(self, *, keep=60, max_entries=128, clock=monotonic):
        self.keep, self.max_entries, self.clock = keep, max_entries, clock
        self._entries = OrderedDict()
        self._lock = Lock()

    def get(self, kitchen, day, load):
        """Coalesce reads in worker threads; failed reads are never kept."""
        key = (kitchen, day)
        with self._lock:
            now = self.clock()
            cached = self._entries.get(key)
            if cached is not None and now < cached[0]:
                self._entries.move_to_end(key)
                return deepcopy(cached[1])
            self._entries.pop(key, None)
            facts = load()
            self._entries[key] = (self.clock() + self.keep, deepcopy(facts))
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)
            return facts
