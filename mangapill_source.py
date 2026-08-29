"""Synchronous, Calibre- and Qt-independent MangaPill HTML adapter."""

from html.parser import HTMLParser
import re
import time
import urllib.parse
import urllib.request

try:
    from .source_adapter import SourceAdapter
    from .version_info import USER_AGENT
except ImportError:
    from source_adapter import SourceAdapter
    from version_info import USER_AGENT


BASE_URL = 'https://mangapill.com'
MANGA_PATH_RE = re.compile(r'^/manga/(\d+)(?:/[^/?#]+)?/?$')
CHAPTER_PATH_RE = re.compile(r'^/chapters/[A-Za-z0-9-]+(?:/[^/?#]+)?/?$')
CHAPTER_NUMBER_RE = re.compile(r'(?i)chapter\s+([^\s]+)')


class _DocumentParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.anchors = []
        self.images = []
        self.h1 = []
        self.description = ''
        self._anchor = None
        self._anchor_depth = 0
        self._h1_depth = 0

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == 'meta' and values.get('name') == 'description':
            self.description = values.get('content', '').strip()
        if tag == 'a':
            self._anchor = {'href': values.get('href', ''), 'title': values.get('title', ''), 'text': []}
            self._anchor_depth = 1
        elif self._anchor is not None and tag not in ('img', 'meta', 'input', 'br', 'hr', 'link'):
            self._anchor_depth += 1
        if tag == 'h1':
            self._h1_depth = 1
        elif self._h1_depth and tag not in ('img', 'meta', 'input', 'br', 'hr', 'link'):
            self._h1_depth += 1
        if tag == 'img':
            image = {
                'url': values.get('data-src') or values.get('src') or '',
                'alt': values.get('alt', ''),
                'class': values.get('class', ''),
            }
            self.images.append(image)
            if self._anchor is not None and image['url']:
                self._anchor.setdefault('image', image['url'])

    def handle_endtag(self, tag):
        if self._anchor is not None:
            self._anchor_depth -= 1
            if self._anchor_depth == 0:
                self._anchor['primary_text'] = self._anchor['text'][0] if self._anchor['text'] else ''
                self._anchor['text'] = ' '.join(self._anchor['text']).strip()
                self.anchors.append(self._anchor)
                self._anchor = None
        if self._h1_depth:
            self._h1_depth -= 1

    def handle_data(self, data):
        text = ' '.join(data.split())
        if not text:
            return
        if self._anchor is not None:
            self._anchor['text'].append(text)
        if self._h1_depth:
            self.h1.append(text)


def _parse_html(text):
    parser = _DocumentParser()
    parser.feed(text)
    return parser


def _chapter_number(text):
    match = CHAPTER_NUMBER_RE.search(text or '')
    return match.group(1).strip() if match else ''


def _chapter_sort_key(chapter):
    value = chapter.get('chapter') or ''
    try:
        return (0, float(value), value)
    except Exception:
        return (1, value.casefold(), value)


class MangaPillSource(SourceAdapter):
    source_id = 'mangapill'
    key = source_id
    display_name = 'MangaPill'
    domains = ('mangapill.com', 'www.mangapill.com')
    enabled_by_default = True
    capabilities = frozenset({'search', 'metadata', 'chapters', 'covers', 'pages', 'binary'})

    def __init__(self, fetch_text=None, fetch_binary=None):
        self._fetch_text = fetch_text or self._default_fetch_text
        self._fetch_binary = fetch_binary or self._default_fetch_binary

    @staticmethod
    def _request(url, timeout=30):
        request = urllib.request.Request(url, headers={
            'User-Agent': USER_AGENT,
            'Accept': 'text/html,application/xhtml+xml,*/*;q=0.8',
        })
        return urllib.request.urlopen(request, timeout=timeout)

    @classmethod
    def _default_fetch_text(cls, url, timeout=30, retries=3):
        last = None
        for attempt in range(1, retries + 1):
            try:
                with cls._request(url, timeout=timeout) as response:
                    return response.read().decode('utf-8', errors='replace')
            except Exception as exc:
                last = exc
                if attempt < retries:
                    time.sleep(min(4, 0.75 * (2 ** (attempt - 1))))
        raise RuntimeError(f'MangaPill request failed after {retries} attempt(s): {last}')

    @staticmethod
    def _default_fetch_binary(url, timeout=45, retries=5, **_kwargs):
        last = None
        for attempt in range(1, retries + 1):
            try:
                request = urllib.request.Request(url, headers={
                    'User-Agent': USER_AGENT, 'Accept': '*/*',
                    'Referer': BASE_URL + '/',
                })
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    return response.read()
            except Exception as exc:
                last = exc
                if attempt < retries:
                    time.sleep(min(8, 0.75 * (2 ** (attempt - 1))))
        raise RuntimeError(f'MangaPill image download failed after {retries} attempt(s): {last}')

    def parse_manga_ref(self, value):
        text = value or ''
        parsed = urllib.parse.urlparse(text if '://' in text else f'https://{text}')
        if (parsed.hostname or '').casefold() not in self.domains:
            return None
        match = MANGA_PATH_RE.match(parsed.path or '')
        if match:
            return match.group(1)
        if CHAPTER_PATH_RE.match(parsed.path or ''):
            return urllib.parse.urlunparse(('https', 'mangapill.com', parsed.path, '', '', ''))
        return None

    def resolve_manga_ref(self, value):
        """Resolve a title or chapter URL to its parent MangaPill manga id."""
        reference = self.parse_manga_ref(value)
        if reference is None:
            raise ValueError('Enter a valid MangaPill manga or chapter URL.')
        if str(reference).isdigit():
            return str(reference)
        doc = _parse_html(self._fetch_text(reference, timeout=30, retries=3))
        candidates = []
        for anchor in doc.anchors:
            match = MANGA_PATH_RE.match(urllib.parse.urlparse(anchor['href']).path or '')
            if match:
                candidates.append((anchor.get('text', '').strip().casefold(), match.group(1)))
        for text, manga_id in candidates:
            if text == 'go to manga':
                return manga_id
        if candidates:
            return candidates[0][1]
        raise RuntimeError('MangaPill chapter page did not contain a parent manga link.')

    def _manga_url(self, value):
        manga_id = self.resolve_manga_ref(value)
        return manga_id, f'{BASE_URL}/manga/{manga_id}'

    def search(self, query, offset=0, limit=12, include_adult=False,
               preferred='en', availability_cache=None):
        del include_adult, preferred, availability_cache
        page = max(1, int(offset) // max(1, int(limit)) + 1)
        url = f'{BASE_URL}/search?' + urllib.parse.urlencode({'q': query, 'page': page})
        doc = _parse_html(self._fetch_text(url, timeout=30, retries=3))
        found = {}
        for anchor in doc.anchors:
            match = MANGA_PATH_RE.match(urllib.parse.urlparse(anchor['href']).path)
            if not match:
                continue
            manga_id = match.group(1)
            row = found.setdefault(manga_id, {'id': manga_id, 'url': urllib.parse.urljoin(BASE_URL, anchor['href']),
                                              'title': '', 'cover_url': ''})
            if anchor.get('image'):
                row['cover_url'] = urllib.parse.urljoin(BASE_URL, anchor['image'])
            if anchor['primary_text'] and not row['title']:
                row['title'] = anchor['primary_text']
        rows = []
        for row in found.values():
            if not row['title']:
                continue
            title = row['title']; folded = title.casefold(); needle = (query or '').casefold().strip()
            score = 1000 if folded == needle else 500 if folded.startswith(needle) else 250 if needle in folded else 0
            rows.append({'score': score, 'title': title, 'full_title': title, 'author': '',
                         'id': row['id'], 'url': row['url'], 'cover_url': row['cover_url'], 'badge': ''})
        rows.sort(key=lambda row: (-row['score'], row['title'].casefold()))
        rows = rows[:max(0, int(limit))]
        has_more = any('page=' in anchor['href'] and 'next' in anchor['text'].casefold() for anchor in doc.anchors)
        return {'query': query, 'offset': int(offset), 'next_offset': int(offset) + len(rows),
                'limit': int(limit), 'total': int(offset) + len(rows) + (1 if has_more else 0),
                'rows': rows, 'fetched_count': len(rows), 'filtered_doujinshi': 0,
                'filtered_empty': 0, 'has_more': has_more}

    def _title_document(self, value):
        manga_id, url = self._manga_url(value)
        return manga_id, url, _parse_html(self._fetch_text(url, timeout=30, retries=3))

    def get_manga(self, value, preferred='en'):
        del preferred
        manga_id, url, doc = self._title_document(value)
        title = ' '.join(doc.h1).strip()
        if not title:
            raise RuntimeError('MangaPill manga page did not contain a title.')
        cover = next((image['url'] for image in doc.images if '/mangapill/i/' in image['url']), '')
        return {'uuid': manga_id, 'title': title, 'author': '',
                'titles': [{'language': 'en', 'title': title, 'primary': True}],
                'available_languages': ['en'], 'original_language': '',
                'main_cover_url': urllib.parse.urljoin(url, cover) if cover else '',
                'description': doc.description, 'source_url': url}

    def get_chapters(self, value, language, start_volume=None, end_volume=None):
        if language and language != 'en':
            return []
        if start_volume is not None or end_volume is not None:
            return []
        _manga_id, _url, doc = self._title_document(value)
        chapters = []
        for anchor in doc.anchors:
            path = urllib.parse.urlparse(anchor['href']).path
            if not path.startswith('/chapters/'):
                continue
            number = _chapter_number(anchor['text'] or anchor['title'])
            if not number:
                continue
            chapters.append({'id': urllib.parse.urljoin(BASE_URL, anchor['href']), 'volume': None,
                             'chapter': number, 'title': '', 'pages': None})
        chapters.sort(key=_chapter_sort_key)
        return chapters

    def get_download_plan(self, value, language, start_volume=None, end_volume=None):
        chapters = self.get_chapters(value, language, start_volume, end_volume)
        return {'volumes': [], 'pages_by_volume': {}, 'chapters_by_volume': {},
                'bonus_pages': 0, 'bonus_chapters': len(chapters),
                'aggregate_error': '', 'feed_error': ''}

    def get_volume_covers(self, value):
        metadata = self.get_manga(value)
        return {None: metadata['main_cover_url']} if metadata['main_cover_url'] else {}

    def get_page_manifest(self, chapter_id, retry_callback=None):
        del retry_callback
        parsed = urllib.parse.urlparse(chapter_id or '')
        if (parsed.hostname or '').casefold() not in self.domains or not parsed.path.startswith('/chapters/'):
            raise ValueError('Enter a valid MangaPill chapter URL.')
        doc = _parse_html(self._fetch_text(chapter_id, timeout=30, retries=3))
        pages = [urllib.parse.urljoin(chapter_id, image['url']) for image in doc.images
                 if 'js-page' in image['class'].split() and image['url']]
        if not pages:
            raise RuntimeError('MangaPill chapter page did not contain readable images.')
        return {'full': pages, 'data_saver': []}

    def fetch_binary(self, url, **kwargs):
        return self._fetch_binary(url, **kwargs)

    def fetch_preview_page(self, saver_url, full_url, page_number, log=None, check_cancel=None):
        del saver_url, page_number, log
        if check_cancel:
            check_cancel()
        return self.fetch_binary(full_url, timeout=45, retries=4), True
