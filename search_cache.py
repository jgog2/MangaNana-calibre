"""Small, versioned SQLite cache for search metadata and inventories."""

from dataclasses import asdict, dataclass, is_dataclass
import hashlib
import json
from pathlib import Path
import sqlite3
import threading
import time


SCHEMA_VERSION = 1
SEARCH_ALGORITHM_VERSION = 'magician-live-provider-contract-v4'
INVENTORY_ALGORITHM_VERSION = 'provider-chapter-contract-v2'
INVENTORY_TTL = 3 * 60 * 60
QUERY_TTL = 24 * 60 * 60
QUERY_FRESH_SECONDS = 30 * 60
MAPPING_TTL = 7 * 24 * 60 * 60
METRICS_TTL = 7 * 24 * 60 * 60
IDENTITY_TTL = 30 * 24 * 60 * 60
HARD_LIMIT_BYTES = 50 * 1024 * 1024
EVICTION_TARGET_BYTES = 40 * 1024 * 1024
_SNAPSHOT_FORBIDDEN_KEYS = frozenset({
    'cover', 'cover_url', 'thumbnail', 'thumbnail_url', 'image', 'image_url',
    'page_bytes', 'image_bytes', 'raw_payload', 'raw_response',
    'thumb_requested',
})


@dataclass(frozen=True)
class CacheHit:
    value: object
    age_seconds: float
    fresh: bool
    displayable: bool = True


def query_cache_key(query, workflow, preferred_language, include_adult,
                    enabled_source_ids, prefer_colored, enrichment_enabled=True,
                    algorithm_version=SEARCH_ALGORITHM_VERSION):
    state = {
        'query': ' '.join(str(query or '').casefold().split()),
        'workflow': str(workflow or ''),
        'preferred_language': str(preferred_language or ''),
        'include_adult': bool(include_adult),
        'enabled_source_ids': sorted(str(value) for value in enabled_source_ids or ()),
        'prefer_colored': bool(prefer_colored),
        'enrichment_enabled': bool(enrichment_enabled),
        'algorithm_version': str(algorithm_version),
    }
    encoded = json.dumps(state, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(encoded.encode('utf-8')).hexdigest()


def default_cache_path(config_directory):
    return Path(config_directory) / 'plugins' / 'MangaNana-search-cache.sqlite3'


def _json_default(value):
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, tuple):
        return list(value)
    raise TypeError(f'Unsupported cache value: {type(value).__name__}')


def compact_search_snapshot(value):
    """Remove image/page/raw-response surfaces before query persistence."""
    if isinstance(value, dict):
        return {
            str(key): compact_search_snapshot(item)
            for key,item in value.items()
            if str(key).casefold() not in _SNAPSHOT_FORBIDDEN_KEYS
            and not isinstance(item, (bytes, bytearray, memoryview))
        }
    if isinstance(value, (list, tuple)):
        return [compact_search_snapshot(item) for item in value if not isinstance(item, (bytes, bytearray, memoryview))]
    return value


class SearchMetadataCache:
    """Thread-safe compact-value cache; opens no connection until first use."""

    TABLES = ('inventory', 'query_snapshot', 'external_metrics', 'provider_mapping', 'external_identity')
    TTLS = {
        'inventory': INVENTORY_TTL,
        'query_snapshot': QUERY_TTL,
        'external_metrics': METRICS_TTL,
        'provider_mapping': MAPPING_TTL,
        'external_identity': IDENTITY_TTL,
    }

    def __init__(self, path, clock=None, hard_limit=HARD_LIMIT_BYTES, eviction_target=EVICTION_TARGET_BYTES):
        self.path = Path(path)
        self.clock = clock or time.time
        self.hard_limit = int(hard_limit)
        self.eviction_target = int(eviction_target)
        self._lock = threading.RLock()
        self._connection = None

    def _connect(self):
        if self._connection is not None:
            return self._connection
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            connection = sqlite3.connect(str(self.path), timeout=2.5, check_same_thread=False)
            connection.execute('PRAGMA journal_mode=WAL')
            connection.execute('PRAGMA synchronous=NORMAL')
            connection.execute('SELECT 1')
        except sqlite3.DatabaseError:
            try:
                connection.close()
            except Exception:
                pass
            corrupt = self.path.with_suffix(self.path.suffix + '.corrupt')
            try:
                if corrupt.exists():
                    corrupt.unlink()
                self.path.replace(corrupt)
            except OSError:
                try:
                    self.path.unlink()
                except OSError:
                    pass
            connection = sqlite3.connect(str(self.path), timeout=2.5, check_same_thread=False)
            connection.execute('PRAGMA journal_mode=WAL')
        self._connection = connection
        self._initialize_schema()
        return connection

    def _initialize_schema(self):
        db = self._connection
        db.execute('CREATE TABLE IF NOT EXISTS cache_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        current = db.execute("SELECT value FROM cache_meta WHERE key='schema_version'").fetchone()
        if current and current[0] != str(SCHEMA_VERSION):
            for table in self.TABLES:
                db.execute(f'DROP TABLE IF EXISTS {table}')
        for table in self.TABLES:
            db.execute(
                f'CREATE TABLE IF NOT EXISTS {table} ('
                'cache_key TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at REAL NOT NULL, accessed_at REAL NOT NULL)'
            )
            db.execute(f'CREATE INDEX IF NOT EXISTS {table}_accessed_idx ON {table}(accessed_at)')
        db.execute(
            "INSERT OR REPLACE INTO cache_meta(key,value) VALUES('schema_version',?)",
            (str(SCHEMA_VERSION),),
        )
        db.commit()

    def close(self):
        with self._lock:
            if self._connection is not None:
                try:
                    self._connection.close()
                except Exception:
                    pass
                self._connection = None

    def put(self, layer, key, value, created_at=None):
        if layer not in self.TABLES:
            raise ValueError(f'Unknown cache layer: {layer}')
        # Only compact normalized JSON is accepted. Binary page/image content
        # cannot be serialized and therefore cannot enter this cache.
        payload = json.dumps(value, default=_json_default, ensure_ascii=False, separators=(',', ':'))
        now = float(self.clock() if created_at is None else created_at)
        with self._lock:
            db = self._connect()
            db.execute(
                f'INSERT OR REPLACE INTO {layer}(cache_key,payload,created_at,accessed_at) VALUES(?,?,?,?)',
                (str(key), payload, now, now),
            )
            db.commit()
            self.enforce_size_limit()

    def get(self, layer, key, allow_stale=False):
        if layer not in self.TABLES:
            raise ValueError(f'Unknown cache layer: {layer}')
        with self._lock:
            try:
                db = self._connect()
                row = db.execute(
                    f'SELECT payload,created_at FROM {layer} WHERE cache_key=?', (str(key),)
                ).fetchone()
                if row is None:
                    return None
                age = max(0.0, float(self.clock()) - float(row[1]))
                ttl = self.TTLS[layer]
                if age > ttl and not allow_stale:
                    return None
                value = json.loads(row[0])
                db.execute(f'UPDATE {layer} SET accessed_at=? WHERE cache_key=?', (float(self.clock()), str(key)))
                db.commit()
                fresh = age <= (QUERY_FRESH_SECONDS if layer == 'query_snapshot' else ttl)
                return CacheHit(value=value, age_seconds=age, fresh=fresh, displayable=age <= ttl)
            except (sqlite3.DatabaseError, json.JSONDecodeError, OSError):
                return None

    def delete(self, layer, key):
        if layer not in self.TABLES:
            return
        with self._lock:
            self._connect().execute(f'DELETE FROM {layer} WHERE cache_key=?', (str(key),))
            self._connection.commit()

    def clear(self):
        with self._lock:
            db = self._connect()
            for table in self.TABLES:
                db.execute(f'DELETE FROM {table}')
            db.commit()
            try:
                db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            except sqlite3.DatabaseError:
                pass
            db.execute('VACUUM')
            db.commit()
            self._checkpoint()

    def size_bytes(self):
        total = 0
        for suffix in ('', '-wal', '-shm'):
            try:
                total += Path(str(self.path) + suffix).stat().st_size
            except OSError:
                pass
        return total

    def size_megabytes(self):
        return self.size_bytes() / (1024.0 * 1024.0)

    def enforce_size_limit(self):
        if self.size_bytes() <= self.hard_limit:
            return
        db = self._connect(); now = float(self.clock())
        # Expired/volatile rows go first; stable identities are the final tier.
        for table in self.TABLES:
            ttl = self.TTLS[table]
            db.execute(f'DELETE FROM {table} WHERE created_at < ?', (now - ttl,))
        db.commit(); self._reclaim()
        if self.size_bytes() <= self.eviction_target:
            return
        for table in self.TABLES:
            while self.size_bytes() > self.eviction_target:
                keys = db.execute(
                    f'SELECT cache_key FROM {table} ORDER BY accessed_at ASC LIMIT 128'
                ).fetchall()
                if not keys:
                    break
                db.executemany(f'DELETE FROM {table} WHERE cache_key=?', keys)
                db.commit(); self._reclaim()

    def _checkpoint(self):
        try:
            self._connect().execute('PRAGMA wal_checkpoint(TRUNCATE)')
        except sqlite3.DatabaseError:
            pass

    def _reclaim(self):
        """Reclaim pages only during a hard-limit cleanup, never normal writes."""
        self._checkpoint()
        try:
            self._connect().execute('VACUUM')
            self._connect().commit()
            self._checkpoint()
        except sqlite3.DatabaseError:
            pass

    def put_query_snapshot(self, key, value, created_at=None):
        snapshot = compact_search_snapshot(value)
        if int((snapshot or {}).get('final_result_count') or 0) <= 0:
            self.delete('query_snapshot', key)
            return False
        self.put('query_snapshot', key, snapshot, created_at)
        return True

    def get_query_snapshot(self, key):
        hit = self.get('query_snapshot', key, allow_stale=False)
        if hit is not None and int((hit.value or {}).get('final_result_count') or 0) <= 0:
            # Safely remove snapshots written by the pre-v2 implementation.
            self.delete('query_snapshot', key)
            return None
        return hit

    def put_external_candidate(self, candidate):
        record = candidate.to_record() if hasattr(candidate, 'to_record') else dict(candidate)
        identity = {key: value for key, value in record.items() if key not in ('rating', 'popularity')}
        identity['rating'] = {}; identity['popularity'] = {}
        key = f"{record.get('service')}:{record.get('external_id')}"
        self.put('external_identity', key, identity, record.get('retrieved_at'))
        self.put('external_metrics', key, {
            'service': record.get('service'), 'external_id': record.get('external_id'),
            'rating': record.get('rating') or {}, 'popularity': record.get('popularity') or {},
        }, record.get('retrieved_at'))

    def put_inventory(self, key, value):
        normalized=tuple(key) if isinstance(key, (tuple, list)) else key
        self.put('inventory', repr((INVENTORY_ALGORITHM_VERSION,normalized)), value)

    def get_inventory(self, key):
        normalized=tuple(key) if isinstance(key, (tuple, list)) else key
        return self.get('inventory', repr((INVENTORY_ALGORITHM_VERSION,normalized)))

    def put_provider_mapping(self, source_id, provider_id, value):
        self.put('provider_mapping', f'{source_id}:{provider_id}', value)

    def get_provider_mapping(self, source_id, provider_id):
        return self.get('provider_mapping', f'{source_id}:{provider_id}')
