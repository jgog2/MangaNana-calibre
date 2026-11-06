"""Bounded exact-listing bookmarks. No Qt, network, history or acquisition data."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
from urllib.parse import urlsplit, urlunsplit

from calibre_plugins.manganana.discovery.canonical_identity import edition_identity

SCHEMA_VERSION = 2
MAX_RECORDS = 500
MAX_BYTES = 1024 * 1024
PROVIDERS = frozenset(('mangadex', 'mangapill', 'weebcentral', 'mangak', 'atsu'))
TEXT_FIELDS = ('source_name', 'title', 'full_title', 'canonical_title', 'canonical_work_id',
    'work_family_id', '_canonical_identity_confidence', 'identity_confidence', 'author',
    'edition', 'edition_class', 'badge', 'publication_format', 'publication_type',
    'publication_layout', 'publication_identity', 'medium', 'language', 'language_policy')


def public_url(value):
    if not isinstance(value, str) or len(value) > 2048:
        return ''
    try:
        parts = urlsplit(value)
        if parts.scheme not in ('https', 'http') or not parts.hostname or parts.username or parts.password:
            return ''
        # Bookmark URLs must not retain session tokens or credentials in queries.
        return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path, '', ''))
    except ValueError:
        return ''


def clean_record(value):
    if not isinstance(value, dict) or not isinstance(value.get('source_id'), str) or value['source_id'] not in PROVIDERS:
        return None
    identity = value.get('id')
    if not isinstance(identity, (str, int)) or isinstance(identity, bool):
        return None
    identity = str(identity).strip()
    if not identity or len(identity) > 2048 or any(ord(c) < 32 for c in identity):
        return None
    if '://' in identity and public_url(identity) != identity:
        return None
    url = public_url(value.get('url'))
    if not url:
        return None
    result = dict(source_id=value['source_id'], id=identity, url=url)
    for key in TEXT_FIELDS:
        text = value.get(key)
        if isinstance(text, str) and text.strip():
            result[key] = ' '.join(text.split())[:512]
    result['title'] = result.get('title') or 'Untitled'
    cover = public_url(value.get('cover_url'))
    if cover:
        result['cover_url'] = cover
    for key in ('alternate_titles', 'available_languages'):
        values = value.get(key)
        if isinstance(values, (list, tuple)):
            result[key] = [s[:256] for s in values[:32] if isinstance(s, str) and s.strip()]
    external = value.get('external_ids')
    if isinstance(external, dict):
        result['external_ids'] = {k: str(v)[:128] for k, v in external.items()
            if k in ('anilist', 'kitsu', 'mangadex', 'mal', 'mangaupdates',
                     'anilist_id', 'kitsu_id', 'mangadex_id', 'mal_id', 'mangaupdates_id')
            and isinstance(v, (str, int))}
    if isinstance(value.get('is_colored'), bool):
        result['is_colored'] = value['is_colored']
    for key in ('year', 'chapter_count'):
        number = value.get(key)
        if isinstance(number, int) and not isinstance(number, bool) and 0 <= number < 1000000:
            result[key] = number
    return result


def favorite_key(record):
    row = clean_record(record)
    if row is None:
        return None
    identity = row['id']
    if row['source_id'] in ('mangadex', 'weebcentral'):
        identity = identity.casefold()
    parts = [row['source_id'], identity, edition_identity(row)]
    parts += [row.get(k, '').casefold() for k in
        ('publication_format', 'publication_type', 'publication_layout', 'publication_identity', 'language', 'language_policy')]
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


_owners = {}
_owners_lock = threading.RLock()


class _FavoritesState:
    """One coalescing disk writer, holding only immutable bytes, never widgets."""
    def __init__(self, config_directory):
        self.path = Path(config_directory) / 'plugins' / 'MangaNana-saved-manga.json'
        self.records = {}
        self.warning = ''
        self.read_only = False
        self._condition = threading.Condition()
        self._pending = None
        self._busy = False
        self.clients = 0
        self._thread = None
        self.error = ''
        self.writes = 0
        self.recovery_paths = set()
        self._load()

    def _load(self):
        recovery = list(self.path.parent.glob('.manganana-favorites-*'))
        if recovery:
            self.warning = (f'{len(recovery)} interrupted Saved Manga write(s) retained in '
                            f'{self.path.parent}. Review the recovery files before deleting them; '
                            'the last committed bookmarks are shown.')
        if not self.path.exists():
            return
        try:
            if self.path.stat().st_size > MAX_BYTES:
                raise ValueError('Saved Manga file exceeds its size limit')
            with self.path.open('rb') as source:
                data = source.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                raise ValueError('Saved Manga file exceeds its size limit')
            document = json.loads(data)
            if not isinstance(document, dict) or type(document.get('version')) is not int:
                raise ValueError('Invalid Saved Manga document')
            if document['version'] not in (1, SCHEMA_VERSION):
                raise ValueError('Unsupported Saved Manga schema; file preserved')
            rows = document.get('records')
            if not isinstance(rows, list) or len(rows) > MAX_RECORDS:
                raise ValueError('Invalid Saved Manga records')
            rejected = 0
            for entry in rows:
                # v1 stored unkeyed listing dictionaries; migrate in memory.
                row = clean_record(entry if document['version'] == 1 else entry.get('listing') if isinstance(entry, dict) else None)
                key = favorite_key(row)
                if key and (document['version'] == 1 or entry.get('key') == key):
                    self.records[key] = row
                else:
                    rejected += 1
            if rejected:
                self.warning = f'Skipped {rejected} invalid saved listing(s).'
        except (OSError, ValueError, TypeError, RecursionError) as exc:
            self.read_only = True
            self.warning = f'Saved Manga could not be read: {exc}. The file was preserved.'

    def contains(self, row):
        return favorite_key(row) in self.records

    def toggle(self, value):
        if self.read_only:
            raise ValueError(self.warning or 'Saved Manga is read-only')
        with self._condition:
            row = clean_record(value)
            key = favorite_key(row)
            if key is None:
                raise ValueError('This listing has no valid provider identity')
            updated = dict(self.records)
            if key in updated:
                del updated[key]
            else:
                if len(updated) >= MAX_RECORDS:
                    raise ValueError(f'Saved Manga supports up to {MAX_RECORDS} listings')
                updated[key] = row
            data = json.dumps(dict(version=SCHEMA_VERSION, records=[dict(key=k, listing=r)
                for k, r in updated.items()]), ensure_ascii=False, separators=(',', ':')).encode('utf-8')
            if len(data) > MAX_BYTES:
                raise ValueError('Saved Manga storage limit reached')
            self.records = updated
            self._pending = data
            if self._thread is None:
                self._thread = threading.Thread(target=self._write_loop, name='MangaAnka-favorites', daemon=True)
                self._thread.start()
            self._condition.notify_all()
            return key in updated

    def _write_loop(self):
        while True:
            with self._condition:
                if self._pending is None:
                    self._thread = None
                    break
                data, self._pending = self._pending, None
                self._busy = True
            temporary = None
            durable = False
            error = ''
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(dir=self.path.parent, prefix='.manganana-favorites-', delete=False) as output:
                    temporary = output.name
                    output.write(data)
                    output.flush()
                    os.fsync(output.fileno())
                durable = True
                os.replace(temporary, self.path)
                self.writes += 1
                # These files belong to this writer. A successful newer commit
                # contains its accumulated edits; do not remove foreign orphans.
                for recovery in tuple(self.recovery_paths):
                    try:
                        Path(recovery).unlink(missing_ok=True)
                        self.recovery_paths.discard(recovery)
                    except OSError:
                        pass
            except OSError as exc:
                error = f'Saved Manga could not be written: {exc}'
                if durable and temporary:
                    self.recovery_paths.add(temporary)
                    error += f'. Unsaved bookmarks retained for recovery: {temporary}'
            finally:
                if temporary and not (error and durable) and os.path.exists(temporary):
                    try:
                        os.unlink(temporary)
                    except OSError:
                        pass
                with self._condition:
                    self.error = error
                    self._busy = False
                    if error:
                        # Retain the newest edit in memory for the next explicit
                        # edit/reopen attempt; never retry in an unbounded loop.
                        if self._pending is None:
                            self._pending = data
                        self._thread = None
                    self._condition.notify_all()
            if error:
                break
        _release_idle(self)


def _release_idle(state):
    # Registry -> state is the only nested lock order. The writer invokes this
    # after releasing its condition; it never retains a dialog or Qt object.
    with _owners_lock, state._condition:
        if (_owners.get(state.owner_key) is state and not state.clients and not state._busy
                and state._pending is None and state._thread is None):
            _owners.pop(state.owner_key, None)


class FavoritesStore:
    """One path-owned writer across closing and reopened plugin windows.

    A close timeout releases this client, not the writer's ownership. Reopening
    sees the latest in-memory records and queues behind the same atomic writer.
    """
    def __init__(self, config_directory):
        key = os.path.normcase(str(Path(config_directory).resolve()))
        self._closed = False
        with _owners_lock:
            state = _owners.get(key)
            if state is None:
                state = _FavoritesState(config_directory)
                state.owner_key = key
                _owners[key] = state
            with state._condition:
                if not state._busy and state._pending is None:
                    # Permit external changes only when no unsaved edit exists.
                    state.records = {}
                    state.warning = ''
                    state.read_only = False
                    state._load()
                state.clients += 1
                if state._pending is not None and state._thread is None:
                    state._thread = threading.Thread(target=state._write_loop, name='MangaAnka-favorites', daemon=True)
                    state._thread.start()
            self._state = state

    def __getattr__(self, name):
        return getattr(self._state, name)

    def contains(self, row):
        return self._state.contains(row)

    def toggle(self, value):
        if self._closed:
            raise ValueError('Saved Manga is closed')
        return self._state.toggle(value)

    def close(self, timeout=2):
        state = self._state
        with state._condition:
            if not self._closed:
                self._closed = True
                state.clients -= 1
            thread = state._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=timeout)
        _release_idle(state)
        with state._condition:
            return not state.error and not state._busy and state._pending is None
