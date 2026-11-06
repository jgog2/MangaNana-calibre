"""Synchronous Atsu JSON adapter with chapter-native acquisition."""

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from calibre_plugins.manganana.providers.transport import read_response, TEXT_LIMIT, IMAGE_LIMIT
from datetime import datetime, timezone

from calibre_plugins.manganana.providers.source_policy import supported_media
from calibre_plugins.manganana.providers.cross_source_fallback import normalize_chapter_number
from calibre_plugins.manganana.providers.source_adapter import SourceAdapter
from calibre_plugins.manganana.publication.chapter_workflow import chapter_sort_key
from calibre_plugins.manganana.discovery.canonical_identity import normalize_identity_text
from calibre_plugins.manganana.version_info import USER_AGENT
from calibre_plugins.manganana.providers.atsu_acquisition import recommended_inventory


BASE_URL = 'https://atsu.moe'
CDN_URL = 'https://cdn.atsu.moe'
TITLE_PATH = re.compile(r'^/manga/([A-Za-z0-9_-]+)/?$')
READER_PATH = re.compile(r'^/read/([A-Za-z0-9_-]+)/([A-Za-z0-9_-]+)/?$')


def packaged_volume(item):
    match=re.fullmatch(r'\s*(?:Volume|Vol\.?)\s+(\d+(?:\.\d+)?)\s*', str(item.get('title') or ''), re.I)
    if not match: return None
    label=normalize_chapter_number(match.group(1))
    if label is None: return None
    number=item.get('number')
    if number is not None and normalize_chapter_number(number) != label: return None
    return float(label)


class AtsuSource(SourceAdapter):
    source_id = 'atsu'
    key = source_id
    display_name = 'Atsu'
    domains = ('atsu.moe', 'www.atsu.moe')
    enabled_by_default = True
    content_languages = ('en',)
    inventory_contract = 'atsu-groups-v1'
    capabilities = frozenset({'search', 'direct_series', 'direct_chapters', 'metadata',
                              'chapters', 'volumes', 'covers', 'pages', 'binary', 'adult_metadata',
                              'alternate_titles', 'authors'})

    def __init__(self, fetch_text=None, fetch_binary=None, cancel_check=None, sleeper=None):
        self._text_transport = fetch_text
        self._binary_transport = fetch_binary
        self._cancel_check = cancel_check or (lambda: None)
        self._sleep = sleeper or time.sleep

    def with_cancel_check(self, cancel_check):
        return type(self)(self._text_transport, self._binary_transport, cancel_check, self._sleep)

    def _request(self, url, *, binary=False, timeout=40, retries=3, retry_callback=None):
        headers = {'User-Agent': USER_AGENT, 'Referer': BASE_URL + '/',
                   'Accept': '*/*' if binary else 'application/json,text/html;q=0.9'}
        last = None
        for attempt in range(retries):
            self._cancel_check()
            try:
                transport = self._binary_transport if binary else self._text_transport
                if transport:
                    result = transport(url, headers=headers, timeout=timeout)
                else:
                    request = urllib.request.Request(url, headers=headers)
                    with urllib.request.urlopen(request, timeout=timeout) as response:
                        result = read_response(response, IMAGE_LIMIT if binary else TEXT_LIMIT, self._cancel_check)
                    if not binary:
                        result = result.decode('utf-8')
                self._cancel_check()
                return result
            except InterruptedError:
                raise
            except urllib.error.HTTPError as exc:
                if exc.code == 403:
                    raise RuntimeError('Atsu access blocked by site protection (HTTP 403).') from exc
                if exc.code < 500 and exc.code != 429:
                    raise
                last = exc
            except (OSError, TimeoutError) as exc:
                last = exc
            if attempt + 1 < retries:
                if retry_callback:
                    retry_callback(f'Atsu request retry {attempt + 1}/{retries}')
                remaining = min(4, 0.75 * 2 ** attempt)
                while remaining > 0:
                    self._cancel_check()
                    interval = min(0.1, remaining)
                    self._sleep(interval)
                    remaining -= interval
        raise RuntimeError(f'Atsu request failed after {retries} attempts: {last}')

    def _json(self, url):
        try:
            result = json.loads(self._request(url))
        except (ValueError, TypeError) as exc:
            raise RuntimeError('Atsu returned malformed JSON.') from exc
        if not isinstance(result, dict) or result.get('success') is False:
            raise RuntimeError('Atsu returned an unsuccessful response.')
        return result

    def parse_manga_ref(self, value):
        text = str(value or '').strip()
        parsed = urllib.parse.urlparse(text if '://' in text else 'https://' + text)
        if (parsed.scheme not in ('http', 'https') or parsed.hostname not in self.domains
                or parsed.username or parsed.password):
            return None
        match = TITLE_PATH.fullmatch(parsed.path) or READER_PATH.fullmatch(parsed.path)
        return match.group(1) if match else None

    def _require_id(self, value):
        manga_id = self.parse_manga_ref(value)
        if not manga_id:
            raise ValueError('Enter a valid Atsu manga or chapter URL.')
        return manga_id

    def resolve_manga_ref(self, value):
        return self._require_id(value)

    def _api(self, path, **params):
        return self._json(BASE_URL + path + '?' + urllib.parse.urlencode(params))

    @staticmethod
    def _image_url(value):
        text = str(value or '')
        if not text:
            return ''
        if text.startswith('posters/'):
            text = '/static/' + text
        url = urllib.parse.urljoin(CDN_URL + '/', text)
        if urllib.parse.urlparse(url).scheme not in ('http', 'https'):
            raise RuntimeError('Atsu returned an invalid image URL.')
        return url

    def get_manga(self, value, preferred='en'):
        manga_id = self._require_id(value)
        manga = self._api('/api/manga/page', id=manga_id).get('mangaPage')
        if not isinstance(manga, dict) or str(manga.get('id')) != manga_id or not manga.get('title'):
            raise RuntimeError('Atsu title response did not contain matching metadata.')
        if not supported_media(manga):
            raise RuntimeError('Atsu entry is a Novel; MangaAnkā currently supports manga/comic media.')
        title = manga['title']
        aliases = list(manga.get('otherNames') or [])
        if manga.get('englishTitle') and manga['englishTitle'] != title:
            aliases.append(manga['englishTitle'])
        poster = manga.get('poster') or {}
        year = None
        if manga.get('released') is not None:
            try:
                year = datetime.fromtimestamp(float(manga['released']) / 1000, timezone.utc).year
            except (ValueError, TypeError, OverflowError, OSError):
                pass
        return {'uuid': manga_id, 'title': title,
                'author': ', '.join(dict.fromkeys(a['name'] for a in manga.get('authors') or [] if a.get('name'))),
                'titles': [{'language': 'en', 'title': title, 'primary': True}] +
                          [{'language': '', 'title': alias, 'primary': False} for alias in aliases],
                'alternate_titles': aliases, 'year': year, 'available_languages': ['en'],
                'original_language': '', 'main_cover_url': self._image_url(poster.get('image')),
                'source_url': BASE_URL + '/manga/' + manga_id,
                'description': manga.get('synopsis') or '', 'adult': manga.get('isAdult'),
                'type': manga.get('type') or '', 'medium': manga.get('medium') or ''}

    def search(self, query, offset=0, limit=12, include_adult=False, preferred='en', availability_cache=None):
        limit = max(1, int(limit)); offset = max(0, int(offset))
        params = {
            'q': query, 'query_by': 'title,englishTitle,otherNames,authors,acronyms',
            'query_by_weights': '4,3,2,2,1', 'num_typos': '4,3,2,1,0',
            'prefix': 'true,true,true,true,false',
            'include_fields': 'id,title,englishTitle,otherNames,authors,poster,posterSmall,posterMedium,type,medium,isAdult,status,year,mbRating,popularity,dateAdded',
            'filter_by': ('' if include_adult else 'isAdult:=false && ') + 'views:>0 && hidden:!=true',
            'page': offset // limit + 1, 'per_page': limit,
            'infix': 'off,off,fallback,off,off',
        }
        data = self._api('/collections/manga/documents/search', **params)
        if not isinstance(data.get('hits'), list) or not isinstance(data.get('found'), int):
            raise RuntimeError('Atsu search response is incomplete.')
        rows = []; filtered_media = 0
        for hit in data['hits']:
            item = hit.get('document') or {}
            if not supported_media(item):
                filtered_media += 1; continue
            if not include_adult and item.get('isAdult') is True:
                continue
            if not item.get('id') or not item.get('title') or not re.fullmatch(r'[A-Za-z0-9_-]+', str(item['id'])):
                continue
            title = item['title']
            rows.append({'id': str(item['id']), 'url': BASE_URL + '/manga/' + str(item['id']),
                         'title': title, 'full_title': title, 'author': ', '.join(item.get('authors') or []),
                         'alternate_titles': list(dict.fromkeys([*(item.get('otherNames') or ()), *([item['englishTitle']] if item.get('englishTitle') else [])])),
                         'year': item.get('year'), 'available_languages': ['en'], 'adult': item.get('isAdult'),
                         'cover_url': self._image_url(item.get('poster') or item.get('posterMedium')),
                         'type': item.get('type') or '', 'medium': item.get('medium') or '', 'badge': '',
                         'score': 1000 if normalize_identity_text(title) == normalize_identity_text(query) else 250})
        return {'query': query, 'offset': offset, 'next_offset': offset + limit, 'limit': limit,
                'total': data['found'], 'rows': rows, 'fetched_count': len(data['hits']),
                'has_more': offset + limit < data['found'], 'filtered_unsupported_media': filtered_media, 'filtered_doujinshi': 0, 'filtered_empty': 0}

    @SourceAdapter.capture_chapter_inventory
    def get_chapters(self, value, language, start_volume=None, end_volume=None):
        if language and language != 'en':
            return []
        manga_id = self._require_id(value)
        chapters = self._api('/api/manga/allChapters', mangaId=manga_id).get('chapters')
        if not isinstance(chapters, list):
            raise RuntimeError('Atsu chapter inventory is incomplete.')
        rows = []; seen = set()
        for item in chapters:
            chapter_id = str(item.get('id') or '')
            if not re.fullmatch(r'[A-Za-z0-9_-]+', chapter_id):
                raise RuntimeError('Atsu returned an invalid chapter ID.')
            if chapter_id in seen:
                continue
            seen.add(chapter_id)
            number = item.get('number')
            label = str(item.get('title') or '')
            if number is None:
                number = re.sub(r'^(Chapter|Episode)\s+', '', label, flags=re.I)
            if str(number) == '':
                raise RuntimeError('Atsu chapter has no display identity.')
            pages = item.get('pageCount')
            if pages is not None and (not isinstance(pages, int) or pages <= 0):
                raise RuntimeError('Atsu chapter has an invalid page count.')
            volume = packaged_volume(item)
            # Carry both IDs in an opaque reader URL so fresh workers need no mutable lookup cache.
            rows.append({'id': f'{BASE_URL}/read/{manga_id}/{chapter_id}', 'volume': volume, '_unit_kind': 'volume' if volume is not None else 'chapter',
                         'chapter': str(number), 'title': '' if re.fullmatch(r'(Chapter|Episode)\s+[\d.]+', label, re.I) else label,
                         'pages': pages, '_scanlation_id': str(item.get('scanlationMangaId') or ''),
                         '_atsu_provider_title':label,'_atsu_index':item.get('index'),
                         '_atsu_created_at':item.get('createdAt')})
        rows=sorted(rows, key=chapter_sort_key)
        groups={r['_scanlation_id'] for r in rows}
        if len(groups)>1 and '' not in groups:
            try:page=self._api('/api/manga/page',id=manga_id).get('mangaPage')
            except InterruptedError:raise
            except Exception:page=None  # Unavailable recommendation cannot discard an incomplete union.
            rows=recommended_inventory(rows,page,manga_id)
        if start_volume is not None or end_volume is not None:
            envelope=next((r.get('_atsu_group_inventory') for r in rows if r.get('_atsu_group_inventory')),None)
            def in_range(row):
                volume=row.get('volume')
                return volume is not None and (start_volume is None or volume>=float(start_volume)) and (end_volume is None or volume<=float(end_volume))
            rows=[r for r in rows if in_range(r)]
            if rows and envelope:
                for r in rows:r.pop('_atsu_group_inventory',None)
                rows[0]['_atsu_group_inventory']=dict(envelope,alternatives=[r for r in envelope['alternatives'] if in_range(r)])
        return rows

    def get_download_plan(self, value, language, start_volume=None, end_volume=None):
        chapters = self.get_chapters(value, language, start_volume, end_volume)
        counts = {}; pages = {}; standalone = []
        for row in chapters:
            volume=row['volume']
            if volume is None:
                standalone.append(row); continue
            counts[volume]=counts.get(volume,0)+1  # reader acquisition members, not story chapters
            pages[volume]=pages.get(volume,0)+(row['pages'] or 0)
        return {'volumes': sorted(counts), 'pages_by_volume': pages, 'chapters_by_volume': counts,
                'bonus_pages': sum(c['pages'] or 0 for c in standalone),
                'bonus_chapters': len(standalone), 'aggregate_error': '', 'feed_error': ''}


    def get_volume_covers(self, value):
        cover = self.get_manga(value)['main_cover_url']
        return {None: cover} if cover else {}

    def get_page_manifest(self, chapter_id, retry_callback=None):
        parsed = urllib.parse.urlparse(str(chapter_id or ''))
        match = READER_PATH.fullmatch(parsed.path)
        if not self.parse_manga_ref(chapter_id) or not match:
            raise ValueError('Enter a valid Atsu chapter URL.')
        manga_id, reference = match.groups()
        chapter = self._api('/api/read/chapter', mangaId=manga_id, chapterId=reference).get('readChapter')
        if not isinstance(chapter, dict) or str(chapter.get('id')) != reference:
            raise RuntimeError('Atsu reader did not identify the requested chapter.')
        pages = chapter.get('pages')
        if not isinstance(pages, list) or not pages:
            raise RuntimeError('Atsu reader did not contain readable pages.')
        if any(not isinstance(p, dict) or not isinstance(p.get('number'), int) for p in pages):
            raise RuntimeError('Atsu reader has invalid page numbering.')
        pages = sorted(pages, key=lambda p: p['number'])
        if [p['number'] for p in pages] != list(range(len(pages))):
            raise RuntimeError('Atsu reader has missing or duplicate pages.')
        if any(not p.get('image') for p in pages):
            raise RuntimeError('Atsu reader has missing page images.')
        return {'full': [self._image_url(p['image']) for p in pages], 'data_saver': []}

    def fetch_binary(self, url, timeout=45, retries=4, retry_callback=None, **kwargs):
        if urllib.parse.urlparse(url).scheme not in ('http', 'https'):
            raise ValueError('Atsu binary URL must use HTTP or HTTPS.')
        return self._request(url, binary=True, timeout=timeout, retries=retries, retry_callback=retry_callback)

    def fetch_preview_page(self, saver_url, full_url, page_number, log=None, check_cancel=None):
        if check_cancel:
            check_cancel()
        blob = self.fetch_binary(full_url or saver_url)
        if check_cancel:
            check_cancel()
        return blob, True

