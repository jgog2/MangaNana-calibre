"""Bounded MangaBaka publication-metadata validation prototype.

This module deliberately has no Calibre or MangaNana UI dependency.  It models
only fields exposed by MangaBaka's documented public JSON API and fails closed
when a requested capability (notably per-volume artwork) is absent.
"""

from urllib.parse import urlencode
import json
import urllib.request

try:
    from .canonical_identity import normalize_identity_text
    from .reference_metadata import PublicationArtwork, PublicationMatch
except ImportError:
    from canonical_identity import normalize_identity_text
    from reference_metadata import PublicationArtwork, PublicationMatch


BASE = 'https://api.mangabaka.org/v1'


def _titles(row):
    values = [row.get('title'), row.get('native_title'), row.get('romanized_title')]
    for entries in (row.get('secondary_titles') or {}).values():
        for item in entries or ():
            if isinstance(item, dict):
                values.append(item.get('title'))
    return tuple(str(value).strip() for value in values if str(value or '').strip())


def _preferred_title(row):
    return str(row.get('title') or '').strip() or (_titles(row)[0] if _titles(row) else '')


class MangaBakaPublicationAdapter:
    """Small API client used only by the source-validation gate.

    MangaBaka exposes a work-level series record.  It does not claim an
    edition, volume, or cover mapping that its schema does not explicitly
    provide.
    """

    source_id = 'mangabaka'

    def __init__(self, request_json=None):
        self.request_count = 0
        self._request_json = request_json or self._http_json
        self._cache = {}

    @staticmethod
    def _http_json(url):
        request = urllib.request.Request(url, headers={
            'User-Agent': 'MangaNana source-validation prototype/0.11',
            'Accept': 'application/json',
        })
        with urllib.request.urlopen(request, timeout=12) as response:
            return json.loads(response.read().decode('utf-8'))

    def _fetch(self, url):
        if url not in self._cache:
            self.request_count += 1
            value = self._request_json(url)
            if isinstance(value, dict):
                self._cache[url] = value
        return self._cache.get(url, {})

    @staticmethod
    def _identities(evidence):
        row = dict(evidence or {})
        return {normalize_identity_text(value) for value in
                (row.get('title'), *(row.get('aliases') or ()), *(row.get('alternate_titles') or ()))
                if normalize_identity_text(value)}

    def match_publication(self, evidence):
        identities = self._identities(evidence)
        title = str(dict(evidence or {}).get('title') or '').strip()
        if not identities or not title:
            return PublicationMatch(self.source_id, '', '', 'no_match', 'No title evidence.')
        query = urlencode({'q': title, 'page': 1, 'limit': 50})
        payload = self._fetch(BASE + '/series/search?' + query)
        candidates = []
        for row in payload.get('data') or ():
            if not isinstance(row, dict) or row.get('type') != 'manga':
                continue
            row_titles = {normalize_identity_text(value) for value in _titles(row)}
            if row_titles & identities:
                candidates.append(row)
        # Do not resolve edition siblings or duplicate title records by ranking.
        unique = {str(row.get('id')): row for row in candidates if row.get('id') is not None}
        if len(unique) != 1:
            return PublicationMatch(self.source_id, '', '',
                                    'ambiguous' if unique else 'no_match',
                                    'No unique exact MangaBaka manga result.')
        row = next(iter(unique.values()))
        publication_id = str(row['id'])
        return PublicationMatch(self.source_id, publication_id, _preferred_title(row), 'confident',
                                'Unique exact title/alias matched to MangaBaka numeric series ID.',
                                edition='unknown',
                                url=str(row.get('canonical_url') or BASE + '/series/' + publication_id),
                                edition_id=publication_id)

    def get_volume_list(self, match):
        """Fail closed: current series schema has a volume count, not records."""
        return ()

    def get_volume_covers(self, match):
        """Fail closed: no exact per-volume artwork exists in the API schema."""
        return ()

    def get_edition_artwork(self, match):
        row = self._detail(match)
        cover = row.get('cover') if isinstance(row, dict) else None
        raw = (cover or {}).get('raw') if isinstance(cover, dict) else None
        url = str((raw or {}).get('url') or '') if isinstance(raw, dict) else ''
        if not url:
            return ()
        return (PublicationArtwork(url, 'work', '', self.source_id, 'work_level',
                                   match.publication_id, match.edition_id),)

    def get_description(self, match):
        # The response does not declare a description language, so callers must
        # not attach one by inference.
        return str(self._detail(match).get('description') or '').strip()

    def get_tags(self, match):
        values = []
        for tag in self._detail(match).get('tags') or ():
            if isinstance(tag, dict) and str(tag.get('name') or '').strip():
                values.append(str(tag['name']).strip())
        return tuple(dict.fromkeys(values))

    def get_external_ids(self, match):
        """Return declared source identifiers without following any provider."""
        source = self._detail(match).get('source') or {}
        return {name: value.get('id') for name, value in source.items()
                if isinstance(value, dict) and value.get('id') is not None}

    def _detail(self, match):
        url = BASE + '/series/' + str(match.publication_id) + '?schema=full'
        payload = self._fetch(url)
        row = payload.get('data') if isinstance(payload, dict) else None
        return row if isinstance(row, dict) and str(row.get('id')) == str(match.publication_id) else {}
