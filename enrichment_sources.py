"""Bounded public AniList and Kitsu metadata adapters.

These adapters are deliberately separate from downloadable ``SourceRegistry``.
They return normalized records only and never retain raw API payloads.
"""

from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, wait
import json
import time
import urllib.error
import urllib.parse
import urllib.request

try:
    from .enrichment_model import (
        ExternalMangaCandidate, PopularitySignal, RatingSignal,
        VolumeBoundaryEvidence,
    )
    from .version_info import USER_AGENT
except ImportError:
    from enrichment_model import ExternalMangaCandidate, PopularitySignal, RatingSignal, VolumeBoundaryEvidence
    from version_info import USER_AGENT


ANILIST_URL = 'https://graphql.anilist.co'
KITSU_URL = 'https://kitsu.io/api/edge/manga'
DEFAULT_LIMIT = 10
ENRICHMENT_WINDOW_SECONDS = 5.0


class EnrichmentRateLimited(RuntimeError):
    def __init__(self, service, retry_after=None):
        self.service = service
        self.retry_after = retry_after
        suffix = f' Retry after {retry_after}s.' if retry_after is not None else ''
        super().__init__(f'{service} rate limit reached.{suffix}')


class EnrichmentAdapter(ABC):
    service_id = ''
    display_name = ''

    @abstractmethod
    def search(self, query, limit=DEFAULT_LIMIT, check_cancel=None):
        pass


def _request_json(url, method='GET', data=None, headers=None, timeout=5.0):
    request = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode('utf-8')), dict(response.headers.items())
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            retry = exc.headers.get('Retry-After') if exc.headers else None
            try:
                retry = int(retry)
            except (TypeError, ValueError):
                retry = None
            raise EnrichmentRateLimited('External enrichment', retry) from exc
        raise


def _year(value):
    try:
        return int(str(value or '')[:4])
    except (TypeError, ValueError):
        return None


def _count(value):
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


class AniListAdapter(EnrichmentAdapter):
    service_id = 'anilist'
    display_name = 'AniList'

    QUERY = '''query ($search: String!, $perPage: Int!) {
      Page(page: 1, perPage: $perPage) {
        media(search: $search, type: MANGA, sort: SEARCH_MATCH) {
          id idMal type format status chapters volumes countryOfOrigin isAdult
          title { english romaji native } synonyms description(asHtml: false) genres startDate { year }
          averageScore meanScore popularity favourites
          staff(perPage: 6, sort: RELEVANCE) { edges { role node { name { full } } } }
        }
      }
    }'''

    def __init__(self, request_json=None):
        self._request_json = request_json or _request_json
        self._next_allowed_at = 0.0

    def search(self, query, limit=DEFAULT_LIMIT, check_cancel=None):
        if time.time() < self._next_allowed_at:
            raise EnrichmentRateLimited(self.display_name, max(1, int(self._next_allowed_at - time.time())))
        if check_cancel:
            check_cancel()
        payload = json.dumps({
            'query': self.QUERY,
            'variables': {'search': str(query), 'perPage': min(DEFAULT_LIMIT, max(1, int(limit)))},
        }).encode('utf-8')
        try:
            body, headers = self._request_json(
                ANILIST_URL, method='POST', data=payload,
                headers={'User-Agent': USER_AGENT, 'Content-Type': 'application/json', 'Accept': 'application/json'},
                timeout=5.0,
            )
        except EnrichmentRateLimited as exc:
            if exc.retry_after:
                self._next_allowed_at = max(self._next_allowed_at, time.time() + exc.retry_after)
            raise EnrichmentRateLimited(self.display_name, exc.retry_after) from exc
        if check_cancel:
            check_cancel()
        if (body or {}).get('errors'):
            raise RuntimeError('AniList returned a GraphQL error.')
        try:
            if int(headers.get('X-RateLimit-Remaining', 1)) <= 0:
                reset = float(headers.get('X-RateLimit-Reset') or 0)
                self._next_allowed_at = max(self._next_allowed_at, reset if reset > time.time() else time.time() + 60)
        except (TypeError, ValueError):
            pass
        rows = (((body or {}).get('data') or {}).get('Page') or {}).get('media') or ()
        return tuple(self._normalize(row) for row in rows if row and row.get('id') is not None), headers

    def _normalize(self, row):
        title = dict(row.get('title') or {})
        authors = []
        for edge in ((row.get('staff') or {}).get('edges') or ()):
            role = str(edge.get('role') or '').casefold()
            if any(word in role for word in ('story', 'art', 'original', 'creator')):
                name = (((edge.get('node') or {}).get('name') or {}).get('full') or '').strip()
                if name:
                    authors.append(name)
        retrieved = time.time()
        chapters = _count(row.get('chapters')); volumes = _count(row.get('volumes'))
        return ExternalMangaCandidate(
            service=self.service_id, external_id=str(row['id']),
            primary_title=title.get('english') or title.get('romaji') or title.get('native') or '',
            english_title=title.get('english') or '', romanized_title=title.get('romaji') or '',
            native_title=title.get('native') or '', aliases=tuple(row.get('synonyms') or ()),
            authors=tuple(dict.fromkeys(authors)), description=str(row.get('description') or ''),
            tags=tuple(row.get('genres') or ()), start_year=_count((row.get('startDate') or {}).get('year')),
            format=str(row.get('format') or ''), reported_chapter_count=chapters,
            reported_volume_count=volumes,
            cross_ids={'anilist_id': str(row['id']), **({'mal_id': str(row['idMal'])} if row.get('idMal') else {})},
            rating=RatingSignal(
                score_10=(float(row['averageScore']) / 10.0) if row.get('averageScore') is not None else None,
                sample_count=None, service=self.service_id,
            ),
            popularity=PopularitySignal(
                readers=_count(row.get('popularity')), favourites=_count(row.get('favourites')),
                service=self.service_id,
            ),
            adult=row.get('isAdult') if isinstance(row.get('isAdult'), bool) else None,
            retrieved_at=retrieved,
            volume_context=VolumeBoundaryEvidence(
                reported_total_chapters=chapters, reported_total_volumes=volumes,
                explicit_volume_boundaries=(), provenance=self.service_id,
                confidence='reported_totals', retrieved_at=retrieved,
            ),
        )


class KitsuAdapter(EnrichmentAdapter):
    service_id = 'kitsu'
    display_name = 'Kitsu'

    def __init__(self, request_json=None):
        self._request_json = request_json or _request_json

    def search(self, query, limit=DEFAULT_LIMIT, check_cancel=None):
        if check_cancel:
            check_cancel()
        url = KITSU_URL + '?' + urllib.parse.urlencode({
            'filter[text]': str(query), 'page[limit]': min(DEFAULT_LIMIT, max(1, int(limit))),
        })
        try:
            body, headers = self._request_json(
                url, headers={'User-Agent': USER_AGENT, 'Accept': 'application/vnd.api+json'}, timeout=5.0,
            )
        except EnrichmentRateLimited as exc:
            raise EnrichmentRateLimited(self.display_name, exc.retry_after) from exc
        if check_cancel:
            check_cancel()
        return tuple(self._normalize(row) for row in (body or {}).get('data') or () if row), headers

    def _normalize(self, row):
        attrs = dict(row.get('attributes') or {})
        titles = dict(attrs.get('titles') or {})
        alternates = list(attrs.get('abbreviatedTitles') or ())
        alternates.extend(value for value in titles.values() if value)
        frequencies = dict(attrs.get('ratingFrequencies') or {})
        sample_count = sum(_count(value) or 0 for value in frequencies.values()) or None
        average = attrs.get('averageRating')
        retrieved = time.time()
        chapters = _count(attrs.get('chapterCount')); volumes = _count(attrs.get('volumeCount'))
        relationships = dict(row.get('relationships') or {})
        # The documented chapters relationship is only a link here; without
        # explicit chapter->volume data no boundaries are manufactured.
        boundaries = ()
        return ExternalMangaCandidate(
            service=self.service_id, external_id=str(row.get('id') or ''),
            primary_title=attrs.get('canonicalTitle') or titles.get('en') or titles.get('en_jp') or '',
            english_title=titles.get('en') or '', romanized_title=titles.get('en_jp') or '',
            native_title=titles.get('ja_jp') or '', aliases=tuple(dict.fromkeys(alternates)),
            description=str(attrs.get('synopsis') or ''),
            start_year=_year(attrs.get('startDate')), format=str(attrs.get('subtype') or ''),
            reported_chapter_count=chapters, reported_volume_count=volumes,
            cross_ids={'kitsu_id': str(row.get('id') or '')},
            rating=RatingSignal(
                score_10=(float(average) / 10.0) if average not in (None, '') else None,
                sample_count=sample_count, service=self.service_id,
            ),
            popularity=PopularitySignal(
                readers=_count(attrs.get('userCount')), favourites=_count(attrs.get('favoritesCount')),
                service_rank=_count(attrs.get('popularityRank')), service=self.service_id,
            ),
            adult=bool(attrs.get('nsfw')) if attrs.get('nsfw') is not None else None,
            retrieved_at=retrieved,
            volume_context=VolumeBoundaryEvidence(
                reported_total_chapters=chapters, reported_total_volumes=volumes,
                explicit_volume_boundaries=boundaries, provenance=self.service_id,
                confidence='reported_totals' if not boundaries else 'explicit_relationship',
                retrieved_at=retrieved,
            ),
        )


class EnrichmentRegistry:
    """Independent optional metadata-service registry with a bounded window."""

    def __init__(self, services=()):
        self._services = {service.service_id: service for service in services}

    def all(self):
        return tuple(self._services.values())

    def search(self, query, limit=DEFAULT_LIMIT, timeout=ENRICHMENT_WINDOW_SECONDS, check_cancel=None):
        candidates = []; errors = {}
        pool = ThreadPoolExecutor(max_workers=max(1, len(self._services)), thread_name_prefix='manganana-enrichment')
        futures = {
            pool.submit(service.search, query, limit, check_cancel): service
            for service in self._services.values()
        }
        done, pending = wait(tuple(futures), timeout=max(0.1, float(timeout)))
        for future in done:
            service = futures[future]
            try:
                rows, _headers = future.result()
                candidates.extend(rows)
            except Exception as exc:
                errors[service.service_id] = str(exc)
        for future in pending:
            service = futures[future]
            future.cancel()
            errors[service.service_id] = 'Timed out; normal content search continued.'
        pool.shutdown(wait=False, cancel_futures=True)
        return tuple(candidates), errors


DEFAULT_ENRICHMENT_REGISTRY = EnrichmentRegistry((AniListAdapter(), KitsuAdapter()))
