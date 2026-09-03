"""Bounded BOOK☆WALKER identity/catalog prototype; not UI-integrated."""

from concurrent.futures import CancelledError
from dataclasses import dataclass
import html
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

try:
    from .canonical_identity import edition_identity, normalize_identity_text
    from .reference_metadata import PublicationArtwork, PublicationMatch, PublicationVolume
except ImportError:
    from canonical_identity import edition_identity, normalize_identity_text
    from reference_metadata import PublicationArtwork, PublicationMatch, PublicationVolume


BASE = 'https://bookwalker.jp'
_CARD = re.compile(r'<div class="m-book-item\b.*?(?=<div class="m-book-item\b|</ul>\s*</div>\s*</section>|\Z)', re.I | re.S)
_PRODUCT = re.compile(r'https://bookwalker\.jp/de([0-9a-f-]{36})/', re.I)
_SERIES = re.compile(r'(?:https://bookwalker\.jp)?/series/(\d+)/list/', re.I)
_NEXT = re.compile(r'<link\b(?=[^>]*\brel=["\']next["\'])(?=[^>]*\bhref=["\']([^"\']+)["\'])[^>]*>', re.I)
_TOTAL = re.compile(r'(?:全|/\s*)([0-9,]+)\s*件')
_TITLE_ATTR = re.compile(r'class="m-book-item__title".*?title="([^"]+)"', re.I | re.S)
_TITLE_LINK = re.compile(r'<a\b(?=[^>]*\bm-book-item__title\b)[^>]*>', re.I | re.S)
_LINK_TITLE_ATTR = re.compile(r'\btitle=["\']([^"\']+)["\']', re.I | re.S)
_TITLE = re.compile(r'<title>\s*(.*?)\s*</title>', re.I | re.S)
_DESCRIPTION = re.compile(r'<meta\s+(?:name|property)="(?:description|og:description)"\s+content="([^"]+)"', re.I)
_IMAGE = re.compile(r'data-original="([^"]+)"', re.I)
_TAGS = re.compile(r'<span class="a-tag-[^"]+">\s*(.*?)\s*</span>', re.I | re.S)
_AUTHOR = re.compile(r'<p class="m-book-item__author">\s*(.*?)</p>', re.I | re.S)
_VOLUME = re.compile(r'(?:第\s*)?(\d+(?:\.\d+)?)\s*(?:巻|卷|巻[）)])|[（(](\d+(?:\.\d+)?)[）)]|\s(\d+(?:\.\d+)?)\s*(?:[-–]|$)')
_COLOR = re.compile(r'(?:カラー版|full\s+color|colou?red\s+edition)', re.I)
_MONO = re.compile(r'(?:モノクロ版|\bb[& ]?w\b|\bblack\s*(?:and|&)\s*white\b)', re.I)
_PROMOTION = re.compile(r'(?:無料|お試し|sample|trial)', re.I)
_SUPPLEMENTARY_SUFFIX = re.compile(
    r'\s*(?:特装版|限定版)(?:\s+(?:Ending|Beginning))?\s*$', re.I,
)
_CATALOG_QUALIFIER = re.compile(r'\s*[（(][^（）()]+[）)]\s*$')
_CATALOG_VOLUME_SUFFIX = re.compile(r'\s+(?:第\s*)?\d+(?:\.\d+)?\s*(?:巻|卷)?\s*$')
_CATALOG_EDITION_SUFFIX = re.compile(
    r'\s*(?:カラー版|モノクロ版|full\s+color|colou?red\s+edition|'
    r'b[& ]?w|black\s*(?:and|&)\s*white)\s*$', re.I
)
_LATIN_PART = re.compile(r'\bpart\s*(\d+)\b', re.I)
_JAPANESE_PART = re.compile(r'第\s*(\d+)\s*部')
_JAPANESE = re.compile(r'[\u3040-\u30ff\u3400-\u9fff]')
MAX_SEARCH_TERMS = 8
MAX_CATALOG_PAGES = 10


def _text(value):
    return ' '.join(html.unescape(re.sub(r'<[^>]+>', ' ', str(value or ''))).split())


def _number(value):
    try:
        number=float(value)
    except (TypeError,ValueError):
        return ''
    return str(int(number)) if number.is_integer() else str(number)


def _volume_number(title):
    match = _VOLUME.search(_text(title))
    return _number(next((group for group in match.groups() if group), '')) if match else ''


def _product_uuid(value):
    """Accept a bare UUID or canonical de<UUID> URL and return one bare UUID."""
    text = str(value or '').strip()
    match = _PRODUCT.search(text)
    if match:
        return match.group(1).lower()
    if text.casefold().startswith('de'):
        text = text[2:]
    return text.lower() if re.fullmatch(r'[0-9a-fA-F-]{36}', text) else ''


def _product_url(value):
    product_id = _product_uuid(value)
    return BASE + '/de' + product_id + '/' if product_id else ''


@dataclass(frozen=True)
class _CatalogCard:
    product_id: str
    title: str
    url: str
    tags: tuple = ()
    creator: str = ''
    image: str = ''


def _cards(page):
    rows = []
    for block in _CARD.findall(page):
        product = _PRODUCT.search(block)
        title = _TITLE_ATTR.search(block)
        if not product or not title:
            continue
        product_id = _product_uuid(product.group(1))
        rows.append(_CatalogCard(
            product_id, _text(title.group(1)), _product_url(product_id),
            tuple(_text(tag) for tag in _TAGS.findall(block) if _text(tag)),
            _text((_AUTHOR.search(block) or ['', ''])[1]),
            html.unescape((_IMAGE.search(block) or ['', ''])[1]),
        ))
    # Campaign products can use a different outer wrapper while retaining the
    # same stable product URL and m-book-item__title anchor. Count those as raw
    # store products so advertised totals remain independently verifiable.
    seen = {row.product_id for row in rows}
    for link in _TITLE_LINK.findall(page):
        product = _PRODUCT.search(link)
        title = _LINK_TITLE_ATTR.search(link)
        if not product or not title:
            continue
        product_id = _product_uuid(product.group(1))
        if product_id in seen:
            continue
        seen.add(product_id)
        rows.append(_CatalogCard(
            product_id, _text(title.group(1)), _product_url(product_id),
        ))
    return tuple(rows)


def _trusted_part_numbers(evidence):
    row = dict(evidence or {})
    values = (row.get('title'), *(row.get('aliases') or ()),
              *(row.get('alternate_titles') or ()))
    return frozenset(
        int(number)
        for value in values
        for pattern in (_LATIN_PART, _JAPANESE_PART)
        for number in pattern.findall(str(value or ''))
    )


def _catalog_base_identity(title, identities, trusted_parts=()):
    """Return one exact comparison-only catalog identity, or fail closed."""
    value = _text(title)
    value = _CATALOG_VOLUME_SUFFIX.sub('', value)
    value = _CATALOG_EDITION_SUFFIX.sub('', value)
    value = _CATALOG_QUALIFIER.sub('', value)
    candidate_parts = {int(number) for number in _JAPANESE_PART.findall(value)}
    trusted_parts = frozenset(int(number) for number in trusted_parts)
    if len(candidate_parts) > 1:
        return ''
    if candidate_parts and trusted_parts and candidate_parts != trusted_parts:
        return ''
    normalized = normalize_identity_text(value)
    if normalized in identities:
        return normalized
    if len(candidate_parts) == 1 and candidate_parts == trusted_parts:
        normalized = normalize_identity_text(_JAPANESE_PART.sub('', value))
        if normalized in identities:
            return normalized
    return ''


def _edition_from_title(title, identities, trusted_parts=()):
    """Classify only explicit catalog variant markers or an exact base title."""
    value = _text(title)
    if _COLOR.search(value):
        return 'official_color'
    if _MONO.search(value):
        return 'original'
    if _catalog_base_identity(value, identities, trusted_parts):
        return 'original'
    return 'unknown'


def _compatible_catalog_kind(card):
    """Use BOOK☆WALKER's explicit category when the card supplies one."""
    return not card.tags or any(tag == 'マンガ' for tag in card.tags)


def _search_terms(evidence):
    """Bound and prioritize supplied identities without fuzzy title guessing."""
    row = dict(evidence or {})
    title = str(row.get('title') or '').strip()
    aliases = tuple(dict.fromkeys(str(value).strip() for value in (
        *(row.get('aliases') or ()), *(row.get('alternate_titles') or ())
    ) if str(value or '').strip() and str(value).strip() != title))
    ordered = (title, *(value for value in aliases if _JAPANESE.search(value)),
               *(value for value in aliases if not _JAPANESE.search(value)))
    return tuple(dict.fromkeys(value for value in ordered if value))[:MAX_SEARCH_TERMS]


class BookwalkerPublicationAdapter:
    source_id = 'bookwalker'

    def __init__(self, request_text=None, should_cancel=None):
        self.request_count = 0
        self._request_text = request_text or self._http_text
        self._page_cache = {}
        self._matched_cards = {}
        self._catalogs = {}
        self._catalog_contexts = {}
        self._last_rejection_reason = ''
        self._should_cancel = should_cancel or (lambda: False)

    def set_cancel_check(self, should_cancel=None):
        self._should_cancel = should_cancel or (lambda: False)

    def _check_cancel(self):
        if self._should_cancel():
            raise CancelledError()

    def _http_text(self, url):
        request = urllib.request.Request(url, headers={
            'User-Agent': 'MangaNana reference prototype/0.11',
            'Accept-Language': 'ja,en;q=0.8',
        })
        with urllib.request.urlopen(request, timeout=12) as response:
            return response.read().decode('utf-8', 'replace')

    def _fetch(self, url):
        if url not in self._page_cache:
            self._check_cancel()
            self.request_count += 1
            text = self._request_text(url)
            if text:
                self._page_cache[url] = text
        return self._page_cache.get(url, '')

    @staticmethod
    def _identities(evidence):
        row = dict(evidence or {})
        values = (row.get('title'), *(row.get('aliases') or ()), *(row.get('alternate_titles') or ()))
        return {normalize_identity_text(value) for value in values if normalize_identity_text(value)}

    def _confirm_product(self, candidate, expected):
        """Confirm one stable product, one series relation, and one volume."""
        self._check_cancel()
        page = self._fetch(candidate.url)
        series_ids = tuple(dict.fromkeys(_SERIES.findall(page)))
        page_title = _text((_TITLE.search(page) or ['', ''])[1])
        canonical = re.search(r'<link rel="canonical" href="([^"]+)"', page, re.I)
        canonical_url = canonical.group(1) if canonical else candidate.url
        canonical_product = _PRODUCT.search(canonical_url)
        volume = _volume_number(page_title)
        if (len(series_ids) != 1 or not volume or not canonical_product or
                canonical_product.group(1) != candidate.product_id):
            return None
        series_id = series_ids[0]
        return PublicationMatch(
            self.source_id, 'series/' + series_id, candidate.title, 'confident',
            'Unique compatible result confirmed by canonical product URL and series list.',
            edition=expected, url=BASE + '/series/' + series_id + '/list/',
            edition_id='series/' + series_id, volume_id=candidate.product_id,
            volume_number=volume,
        )

    @staticmethod
    def _seed_card(candidates):
        def key(card):
            number = _volume_number(card.title)
            return (0, float(number), card.product_id) if number else (1, 0, card.product_id)
        return min(candidates, key=key)

    def _confirm_candidate_series(self, candidates, expected, identities, trusted_parts):
        """Resolve one product or prove several products share one complete series."""
        self._check_cancel()
        if not candidates:
            return None
        seed = candidates[0] if len(candidates) == 1 else self._seed_card(candidates)
        match = self._confirm_product(seed, expected)
        if not match:
            self._last_rejection_reason = 'product confirmation failed'
            return None
        self._catalog_contexts[match.publication_id] = {
            'expected_edition': expected,
            'identities': frozenset(identities),
            'trusted_parts': frozenset(trusted_parts),
        }
        if len(candidates) > 1:
            catalog = self._series_cards(match)
            metadata = self.catalog_metadata(match)
            catalog_ids = {card.product_id for card in catalog}
            candidate_ids = {card.product_id for card in candidates}
            if not metadata.get('complete'):
                self._last_rejection_reason = 'raw series traversal incomplete'
                return None
            if metadata.get('record_count_delta'):
                self._last_rejection_reason = 'raw catalog record-count deficit'
                return None
            if not candidate_ids <= catalog_ids:
                self._last_rejection_reason = 'search candidate absent from confirmed raw series'
                return None
            if not metadata.get('canonical_complete'):
                self._last_rejection_reason = str(
                    metadata.get('canonical_rejection_reason') or
                    'canonical publication catalog invalid'
                )
                return None
        self._matched_cards[match.publication_id] = seed
        self._last_rejection_reason = ''
        return match

    def match_publication(self, evidence):
        row = dict(evidence or {})
        identities = self._identities(row)
        terms = _search_terms(row)
        if not identities or not terms:
            return PublicationMatch(self.source_id, '', '', 'no_match', 'No title evidence.')
        expected = edition_identity(row)
        trusted_parts = _trusted_part_numbers(row)
        saw_cards = False
        for term in terms:
            self._check_cancel()
            search_url = BASE + '/search/?word=' + urllib.parse.quote(term) + '&order=score'
            try:
                search = self._fetch(search_url)
            except urllib.error.HTTPError as exc:
                # BOOK☆WALKER reports an ordinary no-result search as 404.
                # That alias is empty evidence, not a failure of the next
                # supplied canonical alias or of a confirmed product URL.
                if exc.code == 404:
                    continue
                raise
            cards = _cards(search); saw_cards = saw_cards or bool(cards)
            candidates = tuple({card.product_id: card for card in cards
                                if _compatible_catalog_kind(card)
                                and not _PROMOTION.search(card.title)
                                and _edition_from_title(
                                    card.title, identities, trusted_parts
                                ) == expected
                                and _catalog_base_identity(
                                    card.title, identities, trusted_parts
                                )}.values())
            match = self._confirm_candidate_series(
                candidates, expected, identities, trusted_parts,
            )
            if match:
                return match
        return PublicationMatch(
            self.source_id, '', '', 'ambiguous' if saw_cards else 'no_match',
            'No unique compatible BOOK☆WALKER edition result.' + (
                ' Last rejection: ' + self._last_rejection_reason + '.'
                if self._last_rejection_reason else ''
            ),
        )

    def _series_cards(self, match):
        self._check_cancel()
        cache_key = str(match.publication_id or match.url)
        if cache_key in self._catalogs:
            return self._catalogs[cache_key][0]
        series = str(match.publication_id or '')
        series_id = series.split('/', 1)[1] if series.startswith('series/') else ''
        expected_path = f'/series/{series_id}/list/'
        url = str(match.url or '')
        seen = set(); rows = []; pages = 0; expected_total = 0
        complete = False; error = ''
        while url and pages < MAX_CATALOG_PAGES:
            self._check_cancel()
            parsed = urllib.parse.urlparse(url)
            if (parsed.scheme != 'https' or parsed.netloc.casefold() != 'bookwalker.jp' or
                    parsed.path != expected_path or url in seen):
                error = 'unsafe or repeated next-page URL'
                break
            seen.add(url)
            try:
                page = self._fetch(url)
            except Exception as exc:
                if not pages:
                    raise
                error = str(exc)
                break
            pages += 1
            rows.extend(_cards(page))
            totals = [int(value.replace(',', '')) for value in _TOTAL.findall(page)]
            if totals:
                expected_total = max(expected_total, max(totals))
            next_match = _NEXT.search(page)
            if not next_match:
                complete = True
                break
            candidate = urllib.parse.urljoin(url, html.unescape(next_match.group(1)))
            next_parsed = urllib.parse.urlparse(candidate)
            query = urllib.parse.parse_qs(next_parsed.query, keep_blank_values=True)
            if set(query) != {'page'} or len(query['page']) != 1 or not query['page'][0].isdigit():
                error = 'unsafe next-page query'
                break
            url = candidate
        else:
            if url:
                error = f'catalog page limit {MAX_CATALOG_PAGES} reached'
        unique = tuple({row.product_id: row for row in rows}.values())
        self._catalogs[cache_key] = (unique, {
            'pages_fetched': pages, 'page_limit': MAX_CATALOG_PAGES,
            'expected_total': expected_total, 'records_fetched': len(unique),
            'record_count_delta': max(0,expected_total-len(unique)),
            'complete': complete, 'partial': not complete, 'error': error,
        })
        return unique

    def catalog_metadata(self, match):
        cards, canonical = self._canonical_catalog(match)
        metadata = dict(self._catalogs.get(str(match.publication_id or match.url), ((), {}))[1])
        numbers = sorted({_volume_number(card.title) for card in cards}, key=float)
        integers = {int(float(value)) for value in numbers if float(value).is_integer()}
        gaps = []
        if integers:
            gaps = sorted(set(range(min(integers), max(integers) + 1)) - integers)
        metadata.update({
            **canonical,
            'exact_volume_numbers': numbers,
            'minimum_volume': numbers[0] if numbers else '',
            'maximum_volume': numbers[-1] if numbers else '',
            'gap_count': len(gaps), 'gaps': gaps,
        })
        return metadata

    def _canonical_catalog(self, match):
        """Return validated publication products separately from raw traversal."""
        raw = self._series_cards(match)
        raw_metadata = dict(
            self._catalogs.get(str(match.publication_id or match.url), ((), {}))[1]
        )
        context = dict(self._catalog_contexts.get(match.publication_id) or {})
        identities = frozenset(context.get('identities') or ())
        trusted_parts = frozenset(context.get('trusted_parts') or ())
        if not identities:
            seed = _text(match.title)
            base = _CATALOG_QUALIFIER.sub('', _CATALOG_EDITION_SUFFIX.sub(
                '', _CATALOG_VOLUME_SUFFIX.sub('', seed)
            ))
            identities = frozenset(filter(None, (
                normalize_identity_text(seed), normalize_identity_text(base),
            )))
            trusted_parts = _trusted_part_numbers({'title': seed})
        expected = str(context.get('expected_edition') or match.edition or 'unknown')
        if expected == 'unknown':
            expected = _edition_from_title(match.title, identities, trusted_parts)
        eligible = []
        excluded_promotions = 0
        supplementary = []
        rejection = ''
        grouped = {}
        for card in raw:
            if _PROMOTION.search(card.title):
                excluded_promotions += 1
                continue
            number = _volume_number(card.title)
            if not _compatible_catalog_kind(card):
                rejection = 'non-promotional catalog-kind mismatch'
                break
            if not number:
                rejection = 'non-promotional product lacks explicit volume number'
                break
            # NFKC is comparison-only: never change the stored card or identity.
            comparison_title = unicodedata.normalize('NFKC', _text(card.title))
            supplementary_base = _SUPPLEMENTARY_SUFFIX.sub('', comparison_title)
            is_supplementary = supplementary_base != comparison_title
            if is_supplementary:
                if _COLOR.search(comparison_title) or _MONO.search(comparison_title):
                    rejection = 'supplementary product contains publication-edition marker'
                    break
                if not _catalog_base_identity(
                        supplementary_base, identities, trusted_parts):
                    rejection = 'supplementary product title mismatch'
                    break
                supplementary.append((number, card))
                continue
            if (not identities or
                    not _catalog_base_identity(card.title, identities, trusted_parts)):
                rejection = 'non-promotional product title mismatch'
                break
            if _edition_from_title(card.title, identities, trusted_parts) != expected:
                rejection = 'non-promotional edition mismatch'
                break
            grouped.setdefault(number, []).append(card)
        if not rejection:
            duplicates = sorted(number for number, rows in grouped.items() if len(rows) != 1)
            if duplicates:
                rejection = 'duplicate non-promotional volume number: ' + ', '.join(duplicates)
            else:
                eligible = [rows[0] for rows in grouped.values()]
        if not rejection:
            missing_counterparts = sorted({
                number for number, _card in supplementary
                if len(grouped.get(number, ())) != 1
            }, key=float)
            if missing_counterparts:
                rejection = ('supplementary variant lacks one ordinary counterpart: ' +
                             ', '.join(missing_counterparts))
                eligible = []
        numbers = sorted((_volume_number(card.title) for card in eligible), key=float)
        integer_numbers = [int(float(value)) for value in numbers if float(value).is_integer()]
        gaps = []
        if not rejection and numbers and len(integer_numbers) == len(numbers):
            gaps = sorted(set(range(min(integer_numbers), max(integer_numbers) + 1)) -
                          set(integer_numbers))
            if gaps:
                rejection = 'canonical integer volume gap: ' + ', '.join(map(str, gaps))
                eligible = []
                numbers = []
        raw_complete = bool(
            raw_metadata.get('complete') and not raw_metadata.get('record_count_delta')
        )
        if not raw_complete and not rejection:
            rejection = ('raw catalog record-count deficit' if
                         raw_metadata.get('record_count_delta') else
                         'raw series traversal incomplete')
            eligible = []
            numbers = []
        diagnostics = {
            'raw_records_fetched': len(raw),
            'promotional_products_excluded': excluded_promotions,
            'supplementary_variants_excluded': len(supplementary),
            'canonical_volume_count': len(eligible),
            'canonical_complete': bool(raw_complete and eligible and not rejection),
            'canonical_rejection_reason': rejection,
        }
        return tuple(eligible), diagnostics

    @staticmethod
    def _usable_volume(card):
        return _volume_number(card.title) if not _PROMOTION.search(card.title) else ''

    def get_volume_list(self, match):
        cards, diagnostics = self._canonical_catalog(match)
        if not diagnostics.get('canonical_complete'):
            return ()
        return tuple(PublicationVolume(
            _volume_number(card.title), card.title, self.source_id, card.product_id,
            card.url, match.edition_id, 'explicit',
        ) for card in cards)

    def get_volume_covers(self, match):
        volumes = {row.volume_id: row for row in self.get_volume_list(match)}
        values = []
        for card in self._canonical_catalog(match)[0]:
            volume = volumes.get(card.product_id)
            if volume and card.image:
                values.append(PublicationArtwork(card.image, 'volume', volume.number, self.source_id, 'exact',
                                                 match.publication_id, match.edition_id, card.product_id))
        return tuple(values)

    def get_edition_artwork(self, match):
        if (str(match.publication_id or match.url) in self._catalogs and
                not self._canonical_catalog(match)[1].get('canonical_complete')):
            return ()
        card = self._matched_cards.get(match.publication_id)
        if not card or not card.image:
            return ()
        return (PublicationArtwork(card.image, 'edition', '', self.source_id, 'exact',
                                   match.publication_id, match.edition_id, card.product_id),)

    def get_chapter_artwork(self, match):
        return ()

    def get_description(self, match):
        if (str(match.publication_id or match.url) in self._catalogs and
                not self._canonical_catalog(match)[1].get('canonical_complete')):
            return ''
        page = self._fetch(_product_url(match.volume_id)) if _product_uuid(match.volume_id) else ''
        description = _DESCRIPTION.search(page)
        return _text(description.group(1) if description else '')

    def get_tags(self, match):
        page = self._fetch(_product_url(match.volume_id)) if _product_uuid(match.volume_id) else ''
        return tuple(dict.fromkeys(_text(value) for value in _TAGS.findall(page) if _text(value)))

    def get_creators(self, match):
        page = self._fetch(_product_url(match.volume_id)) if _product_uuid(match.volume_id) else ''
        values = re.findall(r'(?:著|原作|作画)\s*[:：]\s*</?[^>]*>?\s*([^<\n]+)', page, re.I)
        return tuple(dict.fromkeys(_text(value) for value in values if _text(value)))
