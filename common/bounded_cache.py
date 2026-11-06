"""Small per-dialog LRU caches with explicit retained-memory budgets."""
from collections import OrderedDict
from collections.abc import MutableMapping


class BoundedCache(MutableMapping):
    def __init__(self, max_bytes, max_entries, cost=len, on_evict=None):
        self.max_bytes = max_bytes
        self.max_entries = max_entries
        self.cost = cost
        self.on_evict = on_evict
        self.bytes_used = 0
        self._items = OrderedDict()

    def __getitem__(self, key):
        value, _ = self._items[key]
        self._items.move_to_end(key)
        return value

    def __setitem__(self, key, value):
        if key in self._items:
            del self[key]
        size = max(0, int(self.cost(value)))
        # The caller can still present an oversized image without retaining it.
        if size > self.max_bytes:
            return
        self._items[key] = (value, size)
        self.bytes_used += size
        while self.bytes_used > self.max_bytes or len(self) > self.max_entries:
            del self[next(iter(self._items))]

    def __delitem__(self, key):
        value, size = self._items.pop(key)
        self.bytes_used -= size
        if self.on_evict is not None:
            self.on_evict(key, value)

    def __iter__(self):
        # Iterating must not reorder the LRU, including Mapping.values().
        return iter(tuple(self._items))

    def __len__(self):
        return len(self._items)


def pixmap_bytes(value):
    return value.width() * value.height() * value.depth() // 8 if value is not None else 0


def artwork_caches():
    scaled = BoundedCache(16 * 1024 * 1024, 256, pixmap_bytes)
    def evict_variants(url, _):
        for key in tuple(scaled):
            if key[0] == url:
                del scaled[key]
    raw = BoundedCache(16 * 1024 * 1024, 256, on_evict=evict_variants)
    return raw, scaled
