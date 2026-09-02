"""Bounded Wikipedia publication-structure adapter with explicit collections."""

from dataclasses import asdict, dataclass
import json
import re
import threading
import time
import urllib.parse
import urllib.error
import urllib.request

try:
    from .canonical_identity import creator_query_variants, normalize_identity_text
    from .cross_source_fallback import normalize_chapter_number
    from .reference_metadata import PublicationChapter, PublicationMatch, PublicationVolume
except ImportError:
    from canonical_identity import creator_query_variants, normalize_identity_text
    from cross_source_fallback import normalize_chapter_number
    from reference_metadata import PublicationChapter, PublicationMatch, PublicationVolume


API = 'https://en.wikipedia.org/w/api.php'
_GRAPHIC_LIST = re.compile(r'\{\{\s*Graphic novel list(?:\s*[|}])', re.I)
_NUMBERED_LIST = re.compile(r'\{\{\s*Numbered list(?:\s*[|}])', re.I)
_VOLUME = re.compile(r'^\s*(\d+(?:\.\d+)?)\b')
_BULLET = re.compile(r'^\s*\*\s*((?:\d+(?:\.\d+)?)(?:[–-]\d+(?:\.\d+)?)?|Special\s+\d+)\.\s*(.+)$', re.I)
_LABELED_BULLET = re.compile(
    r'^\s*\*\s*(?:Chapter|Episode|Round)\s+(-?\d+(?:\.\d+)?)\s*[:.]\s*(.+)$', re.I
)
_ORDERED_ITEM = re.compile(r'^\s*#\s*(.+)$')
_ORDERED_VALUE = re.compile(
    r'^\s*<li\s+value\s*=\s*["\']?(-?\d+)["\']?[^>]*>(.*?)</li>\s*$', re.I | re.S
)
_HEADING = re.compile(r'^(={2,})\s*(.*?)\s*(={2,})\s*$', re.M)
_NAVIGATION = re.compile(r'\{\{\s*(?:Main(?:\s+article)?|Further|See also)(?:\s*[|}])', re.I)
_WIKILINK = re.compile(r'\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]')
_TEMPLATE_PIPE = re.compile(r'\{\{\s*!\s*\}\}', re.I)
_HTML_COMMENT = re.compile(r'<!--.*?-->', re.S)
_PUBLICATION_INDEX_FIELD = re.compile(
    r'^\s*\|\s*(?:volume|publication)_list\s*=\s*([^\r\n]+)', re.I | re.M
)
_EDITION_MARKERS = frozenset({'color', 'colored', 'colour', 'coloured', 'omnibus'})
_HTTP_REQUEST_LOCK = threading.Lock()
_LAST_HTTP_REQUEST = 0.0
_MINIMUM_HTTP_INTERVAL = 1.5


@dataclass(frozen=True)
class _WikipediaPage:
    title: str
    page_id: str
    revision_id: str
    wikitext: str


@dataclass(frozen=True)
class WikipediaPublicationSegment:
    """One explicitly linked page containing validated publication rows."""

    order: int
    title: str
    page_id: str
    revision_id: str
    relationship: str
    parser_pattern: str
    parser_version: str
    chapters: tuple = ()
    volumes: tuple = ()

    def cache_record(self):
        return {
            'cache_contract': 'wikipedia-segment-v1',
            'title': self.title,
            'page_id': self.page_id,
            'revision_id': self.revision_id,
            'parser_pattern': self.parser_pattern,
            'parser_version': self.parser_version,
            'chapters': [asdict(row) for row in self.chapters],
            'volumes': [asdict(row) for row in self.volumes],
        }


@dataclass(frozen=True)
class WikipediaPublicationCollection:
    """Atomic normalized snapshot assembled only from explicit page relations."""

    root_title: str
    root_page_id: str
    root_revision_id: str
    index_pages: tuple
    segments: tuple
    chapters: tuple
    volumes: tuple
    status: str
    discovered_candidates: int = 0
    rejected_segments: int = 0
    unsupported_segments: int = 0
    failed_segments: int = 0
    duplicate_identical: int = 0
    duplicate_complementary: int = 0
    conflicts: tuple = ()
    quarantined_groups: tuple = ()
    traversal_bound: int = 0
    segment_cache_hits: int = 0

    def metadata(self):
        return {
            'root': {
                'title': self.root_title,
                'page_id': self.root_page_id,
                'revision_id': self.root_revision_id,
            },
            'index_pages': [dict(row) for row in self.index_pages],
            'segments': [{
                'order': row.order,
                'title': row.title,
                'page_id': row.page_id,
                'revision_id': row.revision_id,
                'relationship': row.relationship,
                'parser_pattern': row.parser_pattern,
                'parser_version': row.parser_version,
                'explicit_rows': len(row.chapters),
                'explicit_volumes': len(row.volumes),
            } for row in self.segments],
            'status': self.status,
            'discovered_candidates': self.discovered_candidates,
            'accepted_segments': len(self.segments),
            'rejected_segments': self.rejected_segments,
            'unsupported_segments': self.unsupported_segments,
            'failed_segments': self.failed_segments,
            'duplicate_identical': self.duplicate_identical,
            'duplicate_complementary': self.duplicate_complementary,
            'conflicts': list(self.conflicts),
            'raw_publication_records': sum(len(row.chapters) for row in self.segments),
            'safe_aggregated_records': len(self.chapters),
            'reused_label_records': sum(
                group.get('row_count', 0) for group in self.quarantined_groups
                if group.get('classification') == 'explicit_reused_label'
            ),
            'quarantined_records': sum(
                group.get('row_count', 0) for group in self.quarantined_groups
            ),
            'quarantined_groups': [dict(row) for row in self.quarantined_groups],
            'traversal_bound': self.traversal_bound,
            'segment_cache_hits': self.segment_cache_hits,
        }


def _template_at(text, start):
    """Return one balanced ``{{...}}`` template, or ``''`` when malformed."""
    depth = 0; index = start
    while index < len(text) - 1:
        token = text[index:index + 2]
        if token == '{{':
            depth += 1; index += 2; continue
        if token == '}}':
            depth -= 1; index += 2
            if depth == 0:
                return text[start:index]
            continue
        index += 1
    return ''


def _templates(text, pattern):
    found = []; offset = 0
    while True:
        match = pattern.search(text, offset)
        if not match:
            return tuple(found)
        block = _template_at(text, match.start())
        if not block:
            return tuple(found)
        found.append(block); offset = match.start() + len(block)


def _top_level_parts(template):
    """Split a template body on top-level pipes, preserving nested templates."""
    body = template[2:-2]
    parts = []; current = []; depth = 0; index = 0
    while index < len(body):
        token = body[index:index + 2]
        if token == '{{':
            depth += 1; current.append(token); index += 2; continue
        if token == '}}':
            depth = max(0, depth - 1); current.append(token); index += 2; continue
        if body[index] == '|' and depth == 0:
            parts.append(''.join(current)); current = []; index += 1; continue
        current.append(body[index]); index += 1
    parts.append(''.join(current))
    return tuple(parts)


def _clean_title(value):
    text = str(value or '').strip()
    nihongo = re.search(r'\{\{\s*nihongo2?\s*\|\s*["\']?([^|]+)', text, re.I)
    if nihongo:
        text = nihongo.group(1)
    text = re.sub(r'\[\[([^\]|]+)\|([^\]]+)\]\]', r'\2', text)
    text = re.sub(r'\[\[([^\]]+)\]\]', r'\1', text)
    text = re.sub(r"'{2,}", '', text)
    return ' '.join(text.strip(' "\'').split())


def _field_values(template, prefix):
    values = []
    for part in _top_level_parts(template)[1:]:
        if '=' not in part:
            continue
        key, value = part.split('=', 1)
        if key.strip().casefold().startswith(prefix.casefold()):
            values.append(value)
    return tuple(values)


def _numbered_list_rows(template):
    """Return explicit sequential identifiers from one Numbered list template."""
    parts = _top_level_parts(template); start = 1; values = []
    for part in parts[1:]:
        if '=' in part:
            key, value = part.split('=', 1)
            if key.strip().casefold() == 'start':
                explicit = re.match(r'-?\d+', value.strip())
                if not explicit:
                    return ()
                start = int(explicit.group(0))
        else:
            values.append(part)
    return tuple(
        (str(start + index), _clean_title(value), 'chapter')
        for index, value in enumerate(values) if _clean_title(value)
    )


def _clean_link_target(value):
    text = _TEMPLATE_PIPE.split(str(value or ''), maxsplit=1)[0]
    text = text.split('#', 1)[0].replace('_', ' ')
    # A leading colon is MediaWiki's explicit article-link escape. Remove
    # only that marker; a remaining namespace colon is rejected later.
    return ' '.join(text.strip().lstrip(':').split())


def _navigation_targets(text):
    targets = []
    for template in _templates(text, _NAVIGATION):
        for part in _top_level_parts(template)[1:]:
            if '=' in part:
                continue
            target = _clean_link_target(part)
            if target:
                targets.append(target)
    return tuple(dict.fromkeys(targets))


def _wikilink_targets(text):
    return tuple(dict.fromkeys(
        target for target in (_clean_link_target(value) for value in _WIKILINK.findall(text))
        if target
    ))


def _publication_index_targets(text):
    """Return explicit infobox publication-index relations, never guessed names."""
    targets = []
    for value in _PUBLICATION_INDEX_FIELD.findall(text):
        links = _wikilink_targets(value)
        if links:
            targets.extend(links)
            continue
        target = _clean_link_target(value)
        if target:
            targets.append(target)
    return tuple(dict.fromkeys(targets))


def _chapter_identity(chapter):
    numeric = normalize_chapter_number(chapter.number)
    if numeric is not None:
        return ('numeric', numeric)
    normalized = normalize_identity_text(chapter.number)
    return (str(chapter.kind or 'chapter').casefold(), normalized) if normalized else None


def _aggregate_segments(segments):
    """Merge safe rows while retaining duplicate-label groups as diagnostics."""
    grouped = {}
    duplicate_identical = duplicate_complementary = 0
    conflicts = []
    quarantined = []
    ordered_segments = tuple(sorted(
        segments, key=lambda row: (str(row.page_id), str(row.revision_id), row.title)
    ))
    for segment in ordered_segments:
        for chapter in segment.chapters:
            identity = _chapter_identity(chapter)
            if identity is None:
                continue
            grouped.setdefault(identity, []).append(chapter)

    indexed = {}
    for identity in sorted(grouped, key=lambda value: (value[0], value[1])):
        rows = sorted(grouped[identity], key=lambda row: (
            row.source_page_id, row.source_revision_id, row.source_record_id,
            normalize_identity_text(row.title), normalize_chapter_number(row.volume) or '',
        ))
        volumes = {normalize_chapter_number(row.volume) for row in rows}
        titles = {normalize_identity_text(row.title) for row in rows if normalize_identity_text(row.title)}
        classification = ''
        if len(volumes) > 1:
            classification = 'true_structural_conflict'
            conflicts.append(
                f'{identity[1]}: incompatible explicit volumes '
                + ', '.join(sorted(str(value) for value in volumes))
            )
        elif len(titles) > 1:
            structures = {
                (row.source_page_id, row.source_revision_id, row.parser_pattern)
                for row in rows
            }
            record_ids = {row.source_record_id for row in rows if row.source_record_id}
            classification = (
                'explicit_reused_label'
                if len(structures) == 1 and len(record_ids) == len(rows)
                else 'local_ambiguous_label_group'
            )
        if classification:
            quarantined.append({
                'display_key': identity[1],
                'classification': classification,
                'row_count': len(rows),
                'provenance_pages': list(sorted(set(
                    row.source_page for row in rows if row.source_page
                ))),
                'acquisition_projection': 'ambiguous_unprojected',
                'records': [{
                    'source_record_id': row.source_record_id,
                    'display_number': row.number,
                    'title': row.title,
                    'volume': row.volume,
                    'source_page': row.source_page,
                    'source_page_id': row.source_page_id,
                    'source_revision_id': row.source_revision_id,
                    'parser_pattern': row.parser_pattern,
                } for row in rows],
            })
            continue

        chosen = rows[0]
        for candidate in rows[1:]:
            current_title = normalize_identity_text(chosen.title)
            candidate_title = normalize_identity_text(candidate.title)
            if bool(current_title) != bool(candidate_title):
                duplicate_complementary += 1
                if candidate_title:
                    chosen = candidate
            else:
                duplicate_identical += 1
        pages = tuple(sorted(set(
            tuple(value for row in rows for value in row.source_pages or ()) +
            tuple(row.source_page for row in rows if row.source_page)
        ), key=lambda value: (normalize_identity_text(value), value)))
        indexed[identity] = PublicationChapter(
            identity[1] if identity[0] == 'numeric' else chosen.number,
            chosen.title, chosen.volume, chosen.kind, chosen.source,
            pages[0] if pages else chosen.source_page, chosen.parser_pattern,
            chosen.confidence, chosen.source_page_id, chosen.source_revision_id, pages,
            chosen.source_record_id,
        )

    def chapter_order(row):
        key = _chapter_identity(row)
        if key and key[0] == 'numeric':
            parts = key[1].split('.', 1)
            return (0, int(parts[0]), parts[1] if len(parts) > 1 else '', row.title)
        return (1, 0, key[1] if key else row.number, row.title)

    chapters = tuple(sorted(indexed.values(), key=chapter_order))
    volumes = {}
    for segment in ordered_segments:
        for volume in segment.volumes:
            key = normalize_chapter_number(volume.number)
            if key is not None:
                volumes.setdefault(key, volume)
    volume_rows = tuple(sorted(
        volumes.values(), key=lambda row: tuple(int(part) for part in row.number.split('.'))
    ))
    return (chapters, volume_rows, duplicate_identical, duplicate_complementary,
            tuple(sorted(set(conflicts))), tuple(quarantined))


class WikipediaPublicationAdapter:
    source_id = 'wikipedia'
    pattern_id = 'graphic-novel-list-explicit-chapter-list-v1'
    collection_pattern_id = 'segmented-publication-collection-v1'
    parser_version = '5'
    max_collection_pages = 18
    max_collection_segments = 16

    def __init__(self, request_json=None):
        self.request_count = 0
        self.retry_count = 0
        self.rate_limit_count = 0
        self.segment_cache_hits = 0
        self._request_json = request_json or self._http_json
        self._wikitext_cache = {}
        self._page_cache = {}
        self._structure_pages = {}

    def _http_json(self, params):
        global _LAST_HTTP_REQUEST
        url = API + '?' + urllib.parse.urlencode(params)
        request = urllib.request.Request(url, headers={
            'User-Agent': 'MangaNana/0.11 Wikipedia publication resolver (Calibre GUI plugin)',
        })
        for attempt in range(3):
            try:
                with _HTTP_REQUEST_LOCK:
                    elapsed = time.monotonic() - _LAST_HTTP_REQUEST
                    if elapsed < _MINIMUM_HTTP_INTERVAL:
                        time.sleep(_MINIMUM_HTTP_INTERVAL - elapsed)
                    _LAST_HTTP_REQUEST = time.monotonic()
                    with urllib.request.urlopen(request, timeout=12) as response:
                        return json.loads(response.read().decode('utf-8'))
            except urllib.error.HTTPError as exc:
                if exc.code == 429:
                    self.rate_limit_count += 1
                if exc.code not in (429, 500, 502, 503, 504) or attempt >= 2:
                    raise
                retry_after = str((exc.headers or {}).get('Retry-After') or '').strip()
                try:
                    delay = max(1.5, min(12.0, float(retry_after)))
                except ValueError:
                    delay = min(12.0, 3.0 * (2 ** attempt))
                self.retry_count += 1
                time.sleep(delay)

    @staticmethod
    def _titles(evidence):
        row = dict(evidence or {})
        values = [row.get('title'), *(row.get('aliases') or ()), *(row.get('alternate_titles') or ())]
        return {normalize_identity_text(value) for value in values if normalize_identity_text(value)}

    @staticmethod
    def _creator_corroboration_forms(value):
        """Return bounded shared comparison/query forms.

        This is comparison-only: it neither reconstructs display strings nor
        persists a derived creator alias.
        """
        return tuple(dict.fromkeys(normalize_identity_text(form)
                                   for form in creator_query_variants(value)
                                   if normalize_identity_text(form)))

    def _query(self, **params):
        self.request_count += 1
        return self._request_json({'format': 'json', **params})

    def match_publication(self, evidence):
        titles = self._titles(evidence)
        if not titles:
            return PublicationMatch(self.source_id, '', '', 'no_match', 'No title evidence.')
        query = str(dict(evidence or {}).get('title') or '')
        data = self._query(action='query', list='search', srsearch=query, srlimit=8)
        rows = ((data.get('query') or {}).get('search') or ())
        exact = [row for row in rows if normalize_identity_text(row.get('title')) in titles]
        evidence_row = dict(evidence or {})
        creator = normalize_identity_text(
            evidence_row.get('author') or evidence_row.get('creator') or ''
        )
        corroborating_creators = [creator] if creator else []
        if str(evidence_row.get('identity_confidence') or '').casefold() == 'high':
            corroborating_creators.extend(
                form
                for value in (
                    evidence_row.get('author') or evidence_row.get('creator') or '',
                    *(evidence_row.get('creators') or ()),
                    *(evidence_row.get('creator_aliases') or ()),
                )
                for form in self._creator_corroboration_forms(value)
            )
        manga_title_rows = [
            row for row in rows
            if any(normalize_identity_text(row.get('title')) == f'{value} manga'
                   for value in titles if not value.endswith(' manga'))
        ]
        manga_matches = [
            row for row in manga_title_rows
            if any(value in normalize_identity_text(row.get('snippet'))
                   for value in corroborating_creators)
        ]
        # A base title may resolve to an unrelated subject (for example, a
        # chemical article) while Wikipedia also has ``Title (manga)``.  The
        # manga disambiguator is only selected when the supplied canonical
        # creator evidence corroborates its search result; otherwise fail
        # closed instead of silently using the unrelated exact title.
        if len(manga_matches) == 1:
            row = manga_matches[0]; title = row['title']
            return PublicationMatch(
                self.source_id, str(row.get('pageid') or title), title, 'confident',
                'Unique manga-disambiguated title corroborated by creator evidence.',
                edition=str(dict(evidence or {}).get('edition') or 'unknown'),
                url='https://en.wikipedia.org/wiki/' + urllib.parse.quote(title.replace(' ', '_')),
            )
        if manga_title_rows and not any(
                normalize_identity_text(row.get('title')).endswith(' manga') for row in exact):
            return PublicationMatch(self.source_id, '', '', 'ambiguous',
                                    'Manga disambiguation lacks unique creator corroboration.')
        if len(exact) != 1:
            return PublicationMatch(self.source_id, '', '', 'ambiguous' if rows else 'no_match',
                                    'No unique exact title/alias match.')
        row = exact[0]; title = row['title']
        return PublicationMatch(self.source_id, str(row.get('pageid') or title), title,
                                'confident', 'Unique exact Wikipedia title/alias match.',
                                edition=str(dict(evidence or {}).get('edition') or 'unknown'),
                                url='https://en.wikipedia.org/wiki/' + urllib.parse.quote(title.replace(' ', '_')))

    def _wikitext(self, title):
        if title not in self._wikitext_cache:
            data = self._query(action='parse', page=title, prop='wikitext', redirects=1)
            text = str(((data.get('parse') or {}).get('wikitext') or {}).get('*') or '')
            if text:
                self._wikitext_cache[title] = text
        return self._wikitext_cache.get(title, '')

    def _page(self, title):
        key = normalize_identity_text(title)
        if key in self._page_cache:
            return self._page_cache[key]
        data = self._query(action='parse', page=title, prop='wikitext|revid', redirects=1)
        row = data.get('parse') or {}
        text = str((row.get('wikitext') or {}).get('*') or '')
        if not text:
            raise RuntimeError(f'Wikipedia returned no wikitext for {title!r}')
        page = _WikipediaPage(
            str(row.get('title') or title), str(row.get('pageid') or title),
            str(row.get('revid') or ''), text,
        )
        self._page_cache[key] = page
        self._page_cache[normalize_identity_text(page.title)] = page
        self._wikitext_cache[page.title] = text
        self._wikitext_cache[title] = text
        return page

    def _is_related_chapter_page(self, work_title, candidate):
        title = normalize_identity_text(candidate)
        works = self._work_title_variants(work_title)
        # Collection members must be article-namespace publication pages;
        # Category:/Template:/File: links are evidence around a page, not segments.
        prefixes = tuple(prefix for work in works for prefix in (
            f'list of {work} chapter', f'lists of {work} chapter', f'{work} chapter',
        ))
        return bool(':' not in str(candidate or '') and
                    any(title.startswith(prefix) for prefix in prefixes))

    @staticmethod
    def _work_title_variants(work_title):
        """Keep an explicit ``(manga)`` root compatible with its base lists."""
        work = normalize_identity_text(work_title)
        values = [work] if work else []
        if work.endswith(' manga'):
            values.append(work[:-len(' manga')].strip())
        return tuple(dict.fromkeys(value for value in values if value))

    def _is_publication_index_page(self, work_title, candidate):
        """Recognize same-work publication indexes, not arbitrary related pages."""
        title = normalize_identity_text(candidate)
        prefixes = tuple(prefix for work in self._work_title_variants(work_title) for prefix in (
            f'list of {work} volume', f'lists of {work} volume', f'{work} volume',
            f'list of {work} manga volume', f'lists of {work} manga volume',
            f'{work} manga volume',
            f'list of {work} publication', f'lists of {work} publication',
            f'{work} publication',
        ))
        return bool(':' not in str(candidate or '') and
                    any(title.startswith(prefix) for prefix in prefixes))

    def _is_collection_node(self, work_title, candidate):
        return (self._is_related_chapter_page(work_title, candidate) or
                self._is_publication_index_page(work_title, candidate))

    @staticmethod
    def _edition_compatible(edition, candidate):
        profile = str(edition or 'unknown').casefold().replace('-', '_')
        words = set(normalize_identity_text(candidate).split())
        if profile in ('original', 'standard', 'unknown'):
            return not bool(words & _EDITION_MARKERS)
        return False

    def get_structure_page(self, match):
        """Return a verified explicit-template page, never a guessed page name."""
        cached = self._structure_pages.get(match.publication_id)
        if cached is not None:
            return cached
        main = self._wikitext(match.title)
        if _GRAPHIC_LIST.search(main):
            self._structure_pages[match.publication_id] = match.title
            return match.title
        data = self._query(action='query', list='search', srsearch=match.title + ' chapters', srlimit=8)
        candidates = [row.get('title') for row in ((data.get('query') or {}).get('search') or ())
                      if self._is_related_chapter_page(match.title, row.get('title'))]
        candidates = list(dict.fromkeys(value for value in candidates if value))
        if len(candidates) != 1:
            self._structure_pages[match.publication_id] = ''
            return ''
        page = candidates[0]
        if not _GRAPHIC_LIST.search(self._wikitext(page)):
            self._structure_pages[match.publication_id] = ''
            return ''
        self._structure_pages[match.publication_id] = page
        return page

    def _parse_graphic_lists(self, page, work_title=''):
        records = []
        text = self._main_series_section(self._wikitext(page), work_title)
        for template in _templates(text, _GRAPHIC_LIST):
            volume_value = next(iter(_field_values(template, 'VolumeNumber')), '')
            volume_match = _VOLUME.match(_clean_title(volume_value))
            if not volume_match:
                continue
            volume = volume_match.group(1)
            title = _clean_title(next(iter(_field_values(template, 'LicensedTitle')), ''))
            chapters = []
            # Both forms are explicit fields of the validated Graphic novel
            # list template. ChapterList is the live Attack on Titan spelling;
            # ChapterListCol* remains supported for columnar layouts.
            for field in _field_values(template, 'ChapterList'):
                field = _HTML_COMMENT.sub('', field)
                numbered = _templates(field, _NUMBERED_LIST)
                if numbered:
                    for block in numbered:
                        chapters.extend(_numbered_list_rows(block))
                    continue
                ordered = [match.group(1) for line in field.splitlines()
                           for match in (_ORDERED_ITEM.match(line),) if match]
                if ordered:
                    next_number = 1
                    for value in ordered:
                        explicit = _ORDERED_VALUE.match(value)
                        if explicit:
                            next_number = int(explicit.group(1))
                            value = explicit.group(2)
                        chapter_title = _clean_title(value)
                        if chapter_title:
                            chapters.append((str(next_number), chapter_title, 'chapter'))
                        next_number += 1
                    continue
                for line in field.splitlines():
                    bullet = _BULLET.match(line)
                    if bullet:
                        number, chapter_title = bullet.groups()
                        kind = ('special' if number.casefold().startswith('special') else
                                'range' if '–' in number or '-' in number else 'chapter')
                        chapters.append((number, _clean_title(chapter_title), kind))
                        continue
                    labeled = _LABELED_BULLET.match(line)
                    if labeled:
                        number, chapter_title = labeled.groups()
                        chapters.append((number, _clean_title(chapter_title), 'chapter'))
            records.append((PublicationVolume(volume, title, self.source_id), tuple(chapters)))
        return tuple(records)

    def _parse_uncollected_chapters(self, page, work_title=''):
        """Read only explicitly labelled uncollected chapter sections."""
        text = self._main_series_section(self._wikitext(page), work_title)
        headings = [match for match in _HEADING.finditer(text)
                    if len(match.group(1)) == len(match.group(3))]
        rows = []
        for index, heading in enumerate(headings):
            label = normalize_identity_text(_clean_title(heading.group(2)))
            explicitly_uncollected = bool(
                label == 'uncollected chapters' or
                ('chapter' in label and 'not released in collected volume' in label) or
                ('chapter' in label and 'not yet' in label and
                 ('volume format' in label or 'tankobon format' in label or
                  'tankōbon format' in label))
            )
            if not explicitly_uncollected:
                continue
            level = len(heading.group(1)); end = len(text)
            for next_heading in headings[index + 1:]:
                if len(next_heading.group(1)) <= level:
                    end = next_heading.start(); break
            section = text[heading.end():end]
            for block in _templates(_HTML_COMMENT.sub('', section), _NUMBERED_LIST):
                rows.extend((number, title, 'uncollected')
                            for number, title, _kind in _numbered_list_rows(block))
            for line in section.splitlines():
                bullet = _BULLET.match(line)
                if bullet:
                    number, title = bullet.groups()
                    rows.append((number, _clean_title(title), 'uncollected'))
                    continue
                labeled = _LABELED_BULLET.match(line)
                if labeled:
                    number, title = labeled.groups()
                    rows.append((number, _clean_title(title), 'uncollected'))
        return tuple(rows)

    def _segment_from_page(self, page, work_title, order, relationship,
                           segment_cache_get=None, segment_cache_put=None):
        cache_key = ':'.join((
            'wikipedia-segment', page.page_id, page.revision_id,
            self.pattern_id, self.parser_version,
        ))
        cached = segment_cache_get(cache_key) if segment_cache_get else None
        cached = dict(cached or {})
        if (
            cached.get('cache_contract') == 'wikipedia-segment-v1' and
            str(cached.get('page_id') or '') == page.page_id and
            str(cached.get('revision_id') or '') == page.revision_id and
            cached.get('parser_pattern') == self.pattern_id and
            cached.get('parser_version') == self.parser_version and
            cached.get('chapters')
        ):
            chapters = []
            for value in cached.get('chapters') or ():
                row = dict(value)
                row['source_pages'] = tuple(row.get('source_pages') or ())
                chapters.append(PublicationChapter(**row))
            volumes = tuple(PublicationVolume(**dict(value)) for value in cached.get('volumes') or ())
            self.segment_cache_hits += 1
            return WikipediaPublicationSegment(
                order, page.title, page.page_id, page.revision_id, relationship,
                self.pattern_id, self.parser_version, tuple(chapters), volumes,
            )

        records = self._parse_graphic_lists(page.title, work_title)
        uncollected = self._parse_uncollected_chapters(page.title, work_title)
        uncollected_keys = {
            normalize_chapter_number(number) for number, _title, _kind in uncollected
        }
        volumes = tuple(volume for volume, _rows in records)
        chapters = []
        for volume_index, (volume, rows) in enumerate(records):
            for row_index, (number, title, kind) in enumerate(rows):
                if normalize_chapter_number(number) in uncollected_keys:
                    continue
                source_record_id = ':'.join((
                    page.page_id, page.revision_id, self.pattern_id,
                    str(volume_index), str(row_index),
                ))
                chapters.append(PublicationChapter(
                    number, title, volume.number, kind, self.source_id,
                    source_page=page.title, parser_pattern=self.pattern_id,
                    confidence='explicit', source_page_id=page.page_id,
                    source_revision_id=page.revision_id, source_pages=(page.title,),
                    source_record_id=source_record_id,
                ))
        for row_index, (number, title, kind) in enumerate(uncollected):
            chapters.append(PublicationChapter(
                number, title, '', kind, self.source_id,
                source_page=page.title, parser_pattern=self.pattern_id,
                confidence='explicit', source_page_id=page.page_id,
                source_revision_id=page.revision_id, source_pages=(page.title,),
                source_record_id=':'.join((
                    page.page_id, page.revision_id, self.pattern_id,
                    'uncollected', str(row_index),
                )),
            ))
        segment = WikipediaPublicationSegment(
            order, page.title, page.page_id, page.revision_id, relationship,
            self.pattern_id, self.parser_version, tuple(chapters), volumes,
        )
        if segment.chapters and segment_cache_put:
            segment_cache_put(cache_key, segment.cache_record())
        return segment

    def resolve_publication(self, match, segment_cache_get=None, segment_cache_put=None):
        """Resolve one page or an explicitly linked, bounded page collection."""
        root = self._page(match.title)
        if _GRAPHIC_LIST.search(root.wikitext):
            segment = self._segment_from_page(
                root, match.title, 0, 'canonical root', segment_cache_get, segment_cache_put
            )
            return {
                'status': 'valid_with_data' if segment.chapters else 'supported_empty',
                'structure_page': root.title, 'chapters': segment.chapters,
                'volumes': segment.volumes, 'root_page_id': root.page_id,
                'root_revision_id': root.revision_id,
            }

        explicit_root_targets = tuple(dict.fromkeys(
            target for target in (
                _navigation_targets(root.wikitext) + _wikilink_targets(root.wikitext) +
                _publication_index_targets(root.wikitext)
            ) if self._is_collection_node(match.title, target)
        ))
        if not explicit_root_targets:
            # Preserve the validated single-page fallback. Search may locate
            # one explicit list page, but it is never used to assemble a collection.
            page_title = self.get_structure_page(match)
            if not page_title:
                return {
                    'status': 'unsupported_layout', 'structure_page': '',
                    'chapters': (), 'volumes': (), 'root_page_id': root.page_id,
                    'root_revision_id': root.revision_id,
                }
            page = self._page(page_title)
            segment = self._segment_from_page(
                page, match.title, 0, 'single validated search result',
                segment_cache_get, segment_cache_put,
            )
            return {
                'status': 'valid_with_data' if segment.chapters else 'supported_empty',
                'structure_page': page.title, 'chapters': segment.chapters,
                'volumes': segment.volumes, 'root_page_id': root.page_id,
                'root_revision_id': root.revision_id,
            }

        queue = [(target, f'explicit link from {root.title}') for target in explicit_root_targets]
        seen_titles = {normalize_identity_text(root.title)}
        seen_page_ids = {root.page_id}
        index_pages = []
        segments = []
        unsupported = rejected = failed = 0
        processed_pages = 0
        candidate_titles = set()
        bound_exceeded = False

        while queue:
            if processed_pages >= self.max_collection_pages:
                bound_exceeded = True
                break
            target, relationship = queue.pop(0)
            title_key = normalize_identity_text(target)
            if not title_key or title_key in seen_titles:
                continue
            seen_titles.add(title_key)
            if (not self._is_collection_node(match.title, target) or
                    not self._edition_compatible(match.edition, target)):
                rejected += 1
                continue
            try:
                page = self._page(target)
            except Exception as exc:
                failed += 1
                raise RuntimeError(
                    f'Wikipedia collection segment failed ({target}): {exc}'
                ) from exc
            processed_pages += 1
            if page.page_id in seen_page_ids:
                continue
            seen_page_ids.add(page.page_id)
            related_targets = tuple(dict.fromkeys(
                value for value in _navigation_targets(page.wikitext) + _wikilink_targets(page.wikitext)
                if self._is_collection_node(match.title, value)
            ))
            if _GRAPHIC_LIST.search(page.wikitext):
                if len(segments) >= self.max_collection_segments:
                    bound_exceeded = True
                    break
                candidate_titles.add(normalize_identity_text(page.title))
                segment = self._segment_from_page(
                    page, match.title, len(segments), relationship,
                    segment_cache_get, segment_cache_put,
                )
                if segment.chapters:
                    segments.append(segment)
                else:
                    unsupported += 1
                for value in related_targets:
                    queue.append((value, f'explicit link from {page.title}'))
                continue

            raw_targets = _navigation_targets(page.wikitext) + _wikilink_targets(page.wikitext)
            if related_targets:
                index_pages.append({
                    'title': page.title, 'page_id': page.page_id,
                    'revision_id': page.revision_id, 'relationship': relationship,
                    'kind': ('publication_index' if self._is_publication_index_page(
                        match.title, page.title
                    ) else 'chapter_list_index'),
                })
                for value in raw_targets:
                    normalized = normalize_identity_text(value)
                    if self._is_collection_node(match.title, value):
                        candidate_titles.add(normalized)
                        queue.append((value, f'explicit link from {page.title}'))
                    elif (':' not in str(value or '') and 'chapter' in normalized and
                          ('list' in normalized or 'chapters' in normalized)):
                        rejected += 1
                continue
            candidate_titles.add(normalize_identity_text(page.title))
            unsupported += 1

        chapters, volumes, identical, complementary, conflicts, quarantined = _aggregate_segments(segments)
        if bound_exceeded:
            status = 'ambiguous_collection'
            chapters = volumes = ()
        elif not segments:
            status = 'unsupported_segment' if unsupported else 'ambiguous_collection'
        elif unsupported or quarantined:
            status = 'valid_partial'
        else:
            status = 'valid_complete'
        collection = WikipediaPublicationCollection(
            root.title, root.page_id, root.revision_id, tuple(index_pages),
            tuple(segments), tuple(chapters), tuple(volumes), status,
            len(candidate_titles), rejected, unsupported, failed,
            identical, complementary, conflicts, quarantined, self.max_collection_pages,
            self.segment_cache_hits,
        )
        if not index_pages and len(segments) == 1 and status == 'valid_complete':
            segment = segments[0]
            return {
                'status': 'valid_with_data', 'structure_page': segment.title,
                'chapters': segment.chapters, 'volumes': segment.volumes,
                'root_page_id': root.page_id, 'root_revision_id': root.revision_id,
            }
        return {
            'status': status,
            'structure_page': index_pages[0]['title'] if index_pages else root.title,
            'chapters': collection.chapters, 'volumes': collection.volumes,
            'root_page_id': root.page_id, 'root_revision_id': root.revision_id,
            'collection': collection,
        }

    @staticmethod
    def _main_series_section(text, work_title):
        """Restrict to an explicitly labelled main-series subsection when present."""
        headings = []
        for heading in _HEADING.finditer(text):
            if len(heading.group(1)) == len(heading.group(3)):
                headings.append(heading)
        work = normalize_identity_text(work_title)
        for index, heading in enumerate(headings):
            if normalize_identity_text(_clean_title(heading.group(2))) != work:
                continue
            level = len(heading.group(1)); end = len(text)
            for next_heading in headings[index + 1:]:
                if len(next_heading.group(1)) <= level:
                    end = next_heading.start(); break
            return text[heading.end():end]
        return text

    def get_chapter_list(self, match):
        page = self.get_structure_page(match)
        if not page:
            return ()
        chapters = []; seen = set()
        for volume, rows in self._parse_graphic_lists(page, match.title):
            for number, title, kind in rows:
                if number in seen:
                    continue
                seen.add(number)
                chapters.append(PublicationChapter(number, title, volume.number, kind, self.source_id,
                                                    source_page=page, parser_pattern=self.pattern_id,
                                                    confidence='explicit'))
        return tuple(chapters)

    def get_chapter_volume_map(self, match):
        return {chapter.number: chapter.volume for chapter in self.get_chapter_list(match)
                if chapter.kind == 'chapter' and re.fullmatch(r'\d+(?:\.\d+)?', chapter.number)}

    def get_volume_list(self, match):
        page = self.get_structure_page(match)
        return tuple(volume for volume, _rows in self._parse_graphic_lists(page, match.title)) if page else ()
