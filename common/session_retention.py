"""Memory ownership for disposable dialog history and inventory snapshots."""
from collections import deque
import sys

from calibre_plugins.manganana.common.bounded_cache import BoundedCache


def payload_bytes(value, limit=16 * 1024 * 1024):
    """Estimate a plain worker payload once, off the GUI thread.

    Shared objects count once. Unknown objects and over-budget graphs are not
    retained; callers may still present them normally.
    """
    pending, seen, total = [value], set(), 0
    while pending:
        item = pending.pop()
        identity = id(item)
        if identity in seen:
            continue
        seen.add(identity)
        total += sys.getsizeof(item)
        if total > limit:
            return limit + 1
        if isinstance(item, dict):
            pending.extend(item.keys())
            pending.extend(item.values())
        elif isinstance(item, (list, tuple, set, frozenset)):
            pending.extend(item)
        elif not isinstance(item, (str, bytes, int, float, bool, type(None))):
            return limit + 1
    return total


def measured_payload(**fields):
    fields['_cache_bytes'] = payload_bytes(fields) + 1024
    return fields


def session_caches():
    # Unmeasured injected/legacy payloads remain usable but are not cached.
    def cost(value):
        return value.get('_cache_bytes', 16 * 1024 * 1024 + 1)
    return (BoundedCache(4 * 1024 * 1024, 64, cost),
            BoundedCache(16 * 1024 * 1024, 32, cost))


class ActivityHistory:
    """Bound UI history without hiding truncation in copied/saved logs."""
    def __init__(self, max_rows=1000, max_bytes=1024 * 1024, max_line_bytes=16 * 1024):
        self.max_rows, self.max_bytes, self.max_line_bytes = max_rows, max_bytes, max_line_bytes
        self.clear()

    def clear(self):
        self.sizes = deque()
        self.bytes_used = self.dropped = 0

    def prepare(self, text):
        data = str(text).encode('utf8')
        suffix = b' [message truncated]'
        if len(data) > self.max_line_bytes:
            return data[:self.max_line_bytes-len(suffix)].decode('utf8', errors='ignore') + suffix.decode()
        return str(text)

    def append(self, text):
        size = len(text.encode('utf8'))
        self.sizes.append(size)
        self.bytes_used += size
        removed = 0
        while len(self.sizes) > self.max_rows or self.bytes_used > self.max_bytes:
            self.bytes_used -= self.sizes.popleft()
            removed += 1
        self.dropped += removed
        return removed

    def export(self, lines):
        prefix = ([f'[Activity history: {self.dropped} older messages omitted to bound memory.]']
                  if self.dropped else [])
        return '\n'.join([*prefix, *lines])
