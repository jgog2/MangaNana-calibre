"""Synchronous MangaK adapter; complete readers come from Next.js page data."""

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from calibre_plugins.manganana.providers.transport import read_response, TEXT_LIMIT, IMAGE_LIMIT

from calibre_plugins.manganana.providers.source_adapter import SourceAdapter
from calibre_plugins.manganana.publication.chapter_workflow import chapter_sort_key
from calibre_plugins.manganana.discovery.canonical_identity import normalize_identity_text
from calibre_plugins.manganana.version_info import USER_AGENT
from calibre_plugins.manganana.providers import mangak_continuations


BASE_URL = 'https://mangak.io'
API_URL = 'https://api.mangak.io'
TITLE_PATH = re.compile(r'^/([a-z0-9]+(?:-[a-z0-9]+)*)/?$')
READER_PATH = re.compile(r'^/([a-z0-9]+(?:-[a-z0-9]+)*)/((?:vol-(?:\d+|tbd)-)?chapter-[a-z0-9-]+)/?$')
RESERVED = frozenset({'home', 'search', 'login', 'register', 'bookmarks', 'history',
                      'genres', 'authors', 'tags', 'contact', 'dmca', 'sitemap'})


def _author_names(authors):
    """Exclude the site's explicit pending-credit entity, not similar names."""
    return [item['name'] for item in authors or [] if item.get('name') and not (
        str(item['name']).strip().casefold() == 'updating' and
        str(item.get('slug') or item.get('id') or '').strip().casefold() == 'updating')]


class MangaKSource(SourceAdapter):
    source_id = 'mangak'
    key = source_id
    display_name = 'MangaK'
    domains = ('mangak.io', 'www.mangak.io')
    enabled_by_default = True
    content_languages = ('en',)
    capabilities = frozenset({'search', 'direct_series', 'direct_chapters', 'metadata',
                              'chapters', 'covers', 'pages', 'binary', 'adult_metadata',
                              'alternate_titles', 'authors'})

    def __init__(self, fetch_text=None, fetch_binary=None, cancel_check=None, sleeper=None):
        self._text_transport = fetch_text
        self._binary_transport = fetch_binary
        self._cancel_check = cancel_check or (lambda: None)
        self._sleep = sleeper or time.sleep
        self._build_id = None

    def with_cancel_check(self, cancel_check):
        return type(self)(self._text_transport, self._binary_transport, cancel_check, self._sleep)

    def _request(self, url, *, binary=False, timeout=40, retries=3, retry_callback=None):
        headers = {'User-Agent': USER_AGENT, 'Referer': BASE_URL + '/',
                   'Accept': '*/*' if binary else 'application/json,text/html;q=0.9'}
        from calibre_plugins.manganana.diagnostics.thumbnail_diagnostics import http_event
        last = None
        for attempt in range(retries):
            self._cancel_check()
            try:
                transport = self._binary_transport if binary else self._text_transport
                if transport:
                    result = transport(url, headers=headers, timeout=timeout)
                else:
                    request = urllib.request.Request(url, headers=headers)
                    if binary:http_event('http.start',url=url,provider=self.source_id,attempt=attempt+1,headers=headers)
                    with urllib.request.urlopen(request, timeout=timeout) as response:
                        result = read_response(response, IMAGE_LIMIT if binary else TEXT_LIMIT, self._cancel_check)
                        if binary:http_event('http.finish',url=url,provider=self.source_id,status=getattr(response,'status',None),bytes=len(result),content_type=response.headers.get('Content-Type',''))
                    if not binary:
                        result = result.decode('utf-8')
                self._cancel_check()
                return result
            except InterruptedError:
                raise
            except urllib.error.HTTPError as exc:
                if binary:http_event('http.failure',url=url,provider=self.source_id,status=exc.code,error=type(exc).__name__)
                if exc.code == 403:
                    raise RuntimeError('MangaK access blocked by site protection (HTTP 403).') from exc
                if exc.code < 500 and exc.code != 429:
                    raise
                last = exc
            except (OSError, TimeoutError) as exc:
                if binary:http_event('http.failure',url=url,provider=self.source_id,status=None,error=type(exc).__name__)
                last = exc
            if attempt + 1 < retries:
                if retry_callback:
                    retry_callback(f'MangaK request retry {attempt + 1}/{retries}')
                remaining = min(4, 0.75 * 2 ** attempt)
                while remaining > 0:
                    self._cancel_check()
                    interval = min(0.1, remaining)
                    self._sleep(interval)
                    remaining -= interval
        raise RuntimeError(f'MangaK request failed after {retries} attempts: {last}')

    def _json(self, url):
        try:
            result = json.loads(self._request(url))
        except (ValueError, TypeError) as exc:
            raise RuntimeError('MangaK returned malformed JSON.') from exc
        if not isinstance(result, dict) or result.get('success') is False:
            raise RuntimeError('MangaK returned an unsuccessful response.')
        return result

    def parse_manga_ref(self, value):
        text = str(value or '').strip()
        parsed = urllib.parse.urlparse(text if '://' in text else 'https://' + text)
        if (parsed.scheme not in ('http', 'https') or parsed.hostname not in self.domains
                or parsed.username or parsed.password):
            return None
        match = TITLE_PATH.fullmatch(parsed.path) or READER_PATH.fullmatch(parsed.path)
        return match.group(1) if match and match.group(1) not in RESERVED else None

    def _public_url(self, value, reader=False):
        url = urllib.parse.urljoin(BASE_URL + '/', str(value or ''))
        parsed = urllib.parse.urlparse(url)
        pattern = READER_PATH if reader else TITLE_PATH
        if not self.parse_manga_ref(url) or not pattern.fullmatch(parsed.path):
            raise ValueError('Enter a valid MangaK ' + ('chapter' if reader else 'title') + ' URL.')
        return BASE_URL + parsed.path.rstrip('/')

    def _discover_build(self):
        html = self._request(BASE_URL + '/home')
        match = re.search(r'<script\b[^>]*\bid=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', html, re.S)
        build = None
        if match:
            try:
                build = json.loads(match.group(1)).get('buildId')
            except (ValueError, AttributeError):
                pass
        if not build:
            match = re.search(r'/_next/static/([A-Za-z0-9_-]+)/_buildManifest', html)
            build = match.group(1) if match else None
        if not isinstance(build, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', build):
            raise RuntimeError('MangaK did not advertise its current Next.js build.')
        self._build_id = build

    def _page_props(self, url):
        path = urllib.parse.urlparse(url).path.rstrip('/')
        for attempt in range(2):
            if not self._build_id:
                self._discover_build()
            try:
                data = self._json(f'{BASE_URL}/_next/data/{self._build_id}{path}.json')
            except urllib.error.HTTPError as exc:
                if exc.code == 404 and attempt == 0:
                    self._build_id = None
                    continue
                raise
            props = data.get('pageProps')
            if not isinstance(props, dict) or props.get('initialError'):
                raise RuntimeError('MangaK page data is unavailable.')
            return props

    def _title(self, value):
        slug = self.parse_manga_ref(value)
        if not slug:
            raise ValueError('Enter a valid MangaK title or chapter URL.')
        url = BASE_URL + '/' + slug
        manga = self._page_props(url).get('initialManga')
        if not isinstance(manga, dict) or not manga.get('id') or not manga.get('name'):
            raise RuntimeError('MangaK title response did not contain metadata.')
        if self._public_url(manga.get('url')) != url:
            raise RuntimeError('MangaK returned metadata for a different title.')
        return manga, url

    def resolve_manga_ref(self, value):
        return str(self._title(value)[0]['id'])

    def get_manga(self, value, preferred='en'):
        manga, url = self._title(value)
        title = manga['name']
        aliases = [item['name'] for item in manga.get('altNames') or [] if item.get('name')]
        year = str(manga.get('releaseDate') or '')
        return {'uuid': str(manga['id']), 'title': title,
                'author': ', '.join(_author_names(manga.get('authors'))),
                'titles': [{'language': 'en', 'title': title, 'primary': True}] +
                          [{'language': '', 'title': alias, 'primary': False} for alias in aliases],
                'alternate_titles': aliases, 'year': int(year) if re.fullmatch(r'\d{4}', year) else None,
                'available_languages': ['en'], 'original_language': '',
                'main_cover_url': manga.get('cover') or '', 'source_url': url,
                'description': manga.get('summary') or '', 'adult': manga.get('isAdult')}

    def search(self, query, offset=0, limit=12, include_adult=False, preferred='en', availability_cache=None):
        limit = max(1, int(limit)); offset = max(0, int(offset))
        params = urllib.parse.urlencode({'page': offset // limit + 1, 'limit': limit, 'q': query})
        data = self._json(API_URL + '/titles/search?' + params).get('data')
        if not isinstance(data, dict) or not isinstance(data.get('items'), list) or not isinstance(data.get('pagination'), dict):
            raise RuntimeError('MangaK search response is incomplete.')
        rows = []
        for item in data['items']:
            if not include_adult and item.get('is_adult') is True:
                continue
            if not item.get('id') or not item.get('name'):
                continue
            title = item['name']
            rows.append({'id': str(item['id']), 'url': self._public_url(item.get('url')),
                         'title': title, 'full_title': title, 'author': '',
                         'alternate_titles': [a['name'] for a in item.get('alt_names') or [] if a.get('name')],
                         'year': None, 'available_languages': ['en'], 'adult': item.get('is_adult'),
                         'cover_url': item.get('cover') or '', 'badge': '',
                         'score': 1000 if normalize_identity_text(title) == normalize_identity_text(query) else 250})
        pagination = data['pagination']
        return {'query': query, 'offset': offset, 'next_offset': offset + limit, 'limit': limit,
                'total': int(pagination.get('total') or 0), 'rows': rows,
                'fetched_count': len(data['items']), 'has_more': bool(pagination.get('has_next')),
                'filtered_doujinshi': 0, 'filtered_empty': 0}

    @SourceAdapter.capture_chapter_inventory
    def get_chapters(self, value, language, start_volume=None, end_volume=None):
        if language and language != 'en' or start_volume is not None or end_volume is not None:
            return []
        manga, url = self._title(value)
        title_id = urllib.parse.quote(str(manga['id']), safe='')
        query = '?' + urllib.parse.urlencode({'cv': manga['cv']}) if manga.get('cv') is not None else ''
        data = self._json(f'{API_URL}/titles/{title_id}/chapters{query}').get('data')
        if not isinstance(data, dict) or not isinstance(data.get('chapters'), list):
            raise RuntimeError('MangaK chapter inventory is incomplete.')
        rows = []; seen = set()
        for item in data['chapters']:
            # The API's number is an internal index, not the displayed number.
            label = str(item.get('name') or '').strip()
            label = re.sub(r'^Vol\.\s*\d+\s+', '', label, flags=re.I)
            match = re.fullmatch(r'Chapter\s+(\d+(?:\.\d+)?)(?:\s*:\s*(.*))?', label, re.I)
            number = match.group(1) if match else re.sub(r'^Chapter\s+', '', label, flags=re.I)
            chapter_url = self._public_url(item.get('url'), reader=True)
            if self.parse_manga_ref(chapter_url) != self.parse_manga_ref(url) or not item.get('id') or not number:
                raise RuntimeError('MangaK returned an invalid chapter record.')
            if chapter_url in seen:
                continue
            seen.add(chapter_url)
            rows.append({'id': chapter_url, 'volume': None, 'chapter': number,
                         '_provider_record_id': str(item['id']), '_provider_label': str(item.get('name') or ''),
                         'title': (match.group(2) or '') if match else '', 'pages': None})
        return sorted(rows, key=chapter_sort_key)

    def get_download_plan(self, value, language, start_volume=None, end_volume=None):
        chapters = self.get_chapters(value, language, start_volume, end_volume)
        return {'volumes': [], 'pages_by_volume': {}, 'chapters_by_volume': {},
                'bonus_pages': 0, 'bonus_chapters': len(chapters), 'aggregate_error': '', 'feed_error': ''}

    def get_volume_covers(self, value):
        cover = self.get_manga(value)['main_cover_url']
        return {None: cover} if cover else {}

    def get_page_manifest(self, chapter_id, retry_callback=None, *, expected_record_id=None):
        url = self._public_url(chapter_id, reader=True)
        chapter = self._page_props(url).get('initialChapter')
        if not isinstance(chapter, dict) or self._public_url(chapter.get('url'), reader=True) != url:
            raise RuntimeError('MangaK reader did not identify the requested chapter.')
        if expected_record_id is not None and str(chapter.get('id') or '') != expected_record_id:
            raise ValueError('MangaK reader record ID differs from the explicit catalog acquisition')
        images = chapter.get('images'); pages = chapter.get('pages')
        if not isinstance(images, list) or not images:
            raise RuntimeError('MangaK reader did not contain complete page images.')
        if not isinstance(pages, list) or [p.get('url') for p in pages] != images:
            raise RuntimeError('MangaK reader page lists are inconsistent.')
        if any(not isinstance(u, str) or urllib.parse.urlparse(u).scheme not in ('http', 'https') for u in images):
            raise RuntimeError('MangaK reader contains invalid image URLs.')
        # /images API captures contain only three pages: never use them as a full manifest.
        if os.environ.get('MANGAANKA_MANGAK_CONTINUATIONS_ENABLED') == '1':
            paired = mangak_continuations.manifest_pages(chapter, url)
            if paired is not None:
                return {'full': paired, 'data_saver': []}
        return {'full': list(images), 'data_saver': []}

    def fetch_binary(self, url, timeout=45, retries=4, retry_callback=None, **kwargs):
        if (os.environ.get('MANGAANKA_MANGAK_CONTINUATIONS_ENABLED') == '1'
                and urllib.parse.urlparse(url).scheme == mangak_continuations.SCHEME):
            return mangak_continuations.fetch_page(url,
                lambda raw: self._request(raw, binary=True, timeout=timeout, retries=retries,
                                          retry_callback=retry_callback), self._cancel_check)
        if urllib.parse.urlparse(url).scheme not in ('http', 'https'):
            raise ValueError('MangaK binary URL must use HTTP or HTTPS.')
        return self._request(url, binary=True, timeout=timeout, retries=retries, retry_callback=retry_callback)

    def fetch_preview_page(self, saver_url, full_url, page_number, log=None, check_cancel=None):
        if check_cancel:
            check_cancel()
        blob = self.fetch_binary(full_url or saver_url)
        if check_cancel:
            check_cancel()
        return blob, True
