"""Production-facing reference lookup and conservative field merge helpers."""

from dataclasses import asdict, dataclass
import hashlib
import json
import re

try:
    from .bookwalker_reference import BookwalkerPublicationAdapter
    from .google_books_reference import (
        CACHE_CONTRACT as GOOGLE_BOOKS_CACHE_CONTRACT,
        DETAIL_CACHE_CONTRACT as GOOGLE_BOOKS_DETAIL_CACHE_CONTRACT,
        GoogleBooksArtworkResolver,
    )
    from .canonical_identity import creator_comparison_identity, normalize_identity_text
    from .chapter_workflow import chapter_label
    from .cross_source_fallback import normalize_chapter_number
    from .wikipedia_reference import WikipediaPublicationAdapter
except ImportError:
    from bookwalker_reference import BookwalkerPublicationAdapter
    from google_books_reference import (
        CACHE_CONTRACT as GOOGLE_BOOKS_CACHE_CONTRACT,
        DETAIL_CACHE_CONTRACT as GOOGLE_BOOKS_DETAIL_CACHE_CONTRACT,
        GoogleBooksArtworkResolver,
    )
    from canonical_identity import creator_comparison_identity, normalize_identity_text
    from chapter_workflow import chapter_label
    from cross_source_fallback import normalize_chapter_number
    from wikipedia_reference import WikipediaPublicationAdapter


PLACEHOLDER_TITLES = frozenset({'', 'fallback', 'unknown', 'none', 'null', 'n/a', 'untitled'})
WIKIPEDIA_CACHE_CONTRACT = 'wikipedia-structure-v3-collection'
BOOKWALKER_CACHE_CONTRACT = 'bookwalker-publication-v4'


def _creator_identity(value):
    return creator_comparison_identity(value)


def _edition_profile(value):
    edition = str(value or '').casefold().strip().replace('-', '_').replace(' ', '_')
    return {
        'original': 'standard', 'standard': 'standard', 'b&w': 'standard', 'bw': 'standard',
        'color': 'color', 'colored': 'color', 'official_color': 'color',
        'fan_color': 'fan_color', 'fan_colored': 'fan_color',
    }.get(edition, 'unknown')


@dataclass(frozen=True)
class CanonicalPublicationContext:
    """Provider-independent identity used only for publication references."""
    canonical_work_id: str
    canonical_title: str
    trusted_aliases: tuple = ()
    canonical_creators: tuple = ()
    edition_profile: str = 'unknown'
    identity_confidence: str = ''
    reference_key: str = ''
    shareable: bool = False
    shareability_reason: str = ''
    canonical_creator_aliases: tuple = ()

    def lookup_evidence(self):
        return {
            'canonical_work_id': self.canonical_work_id,
            'canonical_title': self.canonical_title,
            'title': self.canonical_title,
            'aliases': self.trusted_aliases,
            'author': ', '.join(self.canonical_creators),
            'creators': self.canonical_creators,
            'creator_aliases': self.canonical_creator_aliases,
            'edition': {
                'standard': 'original', 'color': 'official_color',
                'fan_color': 'fan_color',
            }.get(self.edition_profile, 'unknown'),
            'edition_profile': self.edition_profile,
            'reference_key': self.reference_key,
            'identity_confidence': self.identity_confidence,
        }


def canonical_publication_context(canonical_work_id, evidence):
    """Build a shareable context only from trusted canonical work evidence."""
    row = dict(evidence or {})
    title = str(row.get('canonical_title') or row.get('title') or '').strip()
    work_id = str(canonical_work_id or row.get('work_family_id') or '').strip()
    confidence = str(row.get('identity_confidence') or '').casefold().strip()
    edition = _edition_profile(row.get('edition_profile') or row.get('edition'))
    creator = str(row.get('canonical_author') or '').strip()
    creators=tuple(dict.fromkeys(
        str(value).strip() for value in row.get('canonical_creators') or ()
        if str(value or '').strip()
    )) or ((creator,) if creator else ())
    creator_display=creator or ', '.join(creators)
    creator_identities={_creator_identity(value) for value in creators if _creator_identity(value)}
    display_identity=_creator_identity(creator_display)
    creator_aliases = tuple(dict.fromkeys(
        str(value).strip() for value in row.get('canonical_creator_aliases') or ()
        if str(value or '').strip() and (
            _creator_identity(value) in creator_identities or
            _creator_identity(value) == display_identity
        )
    ))
    provider_creator = str(row.get('provider_author') or '').strip()
    provider_identity=_creator_identity(provider_creator)
    conflict = bool(creators and provider_creator and
                    provider_identity not in creator_identities and
                    provider_identity != display_identity)
    aliases = tuple(dict.fromkeys(
        str(value).strip() for value in row.get('trusted_aliases') or ()
        if str(value or '').strip() and normalize_identity_text(value) != normalize_identity_text(title)
    ))
    shareable = bool(work_id and title and confidence == 'high' and
                     edition in ('standard', 'color', 'fan_color') and not conflict)
    if conflict:
        reason = 'material creator contradiction'
    elif edition == 'unknown':
        reason = 'ambiguous edition'
    elif confidence != 'high' or not work_id:
        reason = 'canonical identity is not high confidence'
    elif not title:
        reason = 'canonical title is missing'
    else:
        reason = 'same canonical work, compatible edition, no creator contradiction'
    work_component = '-'.join(normalize_identity_text(work_id).split())
    slug = '-'.join(normalize_identity_text(title).split())
    key = f'{work_component}|{slug}|{edition}' if shareable else ''
    return CanonicalPublicationContext(
        work_id, title, aliases, creators, edition,
        confidence, key, shareable, reason, creator_aliases,
    )


def is_placeholder_chapter_title(value, chapter_number=''):
    text = ' '.join(str(value or '').split())
    if text.casefold() in PLACEHOLDER_TITLES:
        return True
    number = normalize_chapter_number(chapter_number)
    if number is None:
        return False
    normalized = re.sub(r'[^0-9.]+', ' ', text.casefold()).strip()
    return normalized == number and bool(re.fullmatch(r'(?:(?:chapter|ch\.?)\s*)?[0-9.]+', text.casefold()))


def chapter_metadata_label(chapter, zero_pad=False):
    """Render chapter facts only; acquisition provenance belongs to its pill."""
    row = dict(chapter or {})
    label = f'Chapter {chapter_label(row, zero_pad)}'
    title = str(row.get('title') or '').strip()
    if title and not is_placeholder_chapter_title(title, row.get('chapter')):
        label += f'  ·  {title}'
    try:
        volume = float(row.get('volume'))
    except (TypeError, ValueError):
        volume = None
    if volume is not None:
        label += f'  ·  Vol. {volume:g}'
    return label


def fallback_source_label(source_name, fallback_reason=''):
    name = str(source_name or '').strip()
    reason = str(fallback_reason or '').strip()
    return f'{name} · fallback' if name and reason and reason != 'primary' else name


def canonical_reference_alias(selected_title, candidates=()):
    """Return one exact externally-established alias, or fail closed."""
    selected = normalize_identity_text(selected_title)
    if not selected:
        return ''
    matched = {}
    for candidate in candidates or ():
        row = candidate if isinstance(candidate, dict) else getattr(candidate, '__dict__', {})
        service = str(row.get('service') or '').casefold()
        if service not in ('anilist', 'kitsu'):
            continue
        values = row.get('titles') if isinstance(candidate, dict) else getattr(candidate, 'titles', ())
        if values is None:
            values = (row.get('primary_title'), row.get('english_title'), row.get('romanized_title'),
                      row.get('native_title'), *(row.get('aliases') or ()))
        if selected not in {normalize_identity_text(value) for value in values if value}:
            continue
        primary = str(row.get('primary_title') or '').strip()
        primary_key = normalize_identity_text(primary)
        if primary and primary_key and primary_key != selected:
            matched[primary_key] = primary
    return next(iter(matched.values())) if len(matched) == 1 else ''


def merge_wikipedia_chapters(provider_chapters, reference_chapters, with_coverage=False):
    """Fill title/volume gaps without replacing provider records or provenance."""
    indexed = {}
    ambiguous = set()
    for original in reference_chapters or ():
        row = asdict(original) if hasattr(original, '__dataclass_fields__') else dict(original)
        number = normalize_chapter_number(row.get('number') or row.get('chapter'))
        if number is None or row.get('kind', 'chapter') not in (
                'chapter', 'special', 'uncollected'):
            continue
        if number in indexed and indexed[number] != row:
            ambiguous.add(number)
        else:
            indexed[number] = row
    output = []; matched = titles_applied = volumes_applied = 0
    provider_rows = tuple(provider_chapters or ())
    acquisition_multiplicity={}
    for row in provider_rows:
        key=normalize_chapter_number(dict(row).get('chapter'))
        if key is not None:
            acquisition_multiplicity[key]=acquisition_multiplicity.get(key,0)+1
    for original in provider_rows:
        row = dict(original)
        number = normalize_chapter_number(row.get('chapter'))
        reference=(indexed.get(number) if number not in ambiguous and
                   acquisition_multiplicity.get(number,0) == 1 else None)
        if reference:
            matched += 1
            current_title = str(row.get('title') or '').strip()
            reference_title = str(reference.get('title') or '').strip()
            if reference_title and is_placeholder_chapter_title(current_title, number):
                row['title'] = reference_title
                row['_title_source'] = 'wikipedia'
                titles_applied += 1
            elif current_title:
                row.setdefault('_title_source', str(row.get('_source_id') or 'provider'))
            if row.get('volume') in (None, '') and reference.get('volume') not in (None, ''):
                row['volume'] = str(reference.get('volume'))
                row['_volume_source'] = 'wikipedia'
                row['_volume_confidence'] = 'explicit'
                volumes_applied += 1
        output.append(row)
    merged = tuple(output)
    if not with_coverage:
        return merged
    usable = tuple(row for key,row in indexed.items() if key not in ambiguous)
    return merged, {
        'provider_chapters': len(provider_rows),
        'reference_chapters': len(usable),
        'titles_available': sum(bool(str(row.get('title') or '').strip()) for row in usable),
        'volume_mappings_available': sum(row.get('volume') not in (None, '') for row in usable),
        'chapters_matched': matched,
        'titles_applied': titles_applied,
        'volume_assignments_applied': volumes_applied,
        'unmapped_provider_chapters': len(provider_rows) - matched,
    }


def preferred_description(bookwalker='', anilist='', kitsu='', wikipedia='', provider=''):
    # BOOK☆WALKER text remains reference evidence only; it is not approved as
    # display Description authority because its language is not declared.
    return next((str(value).strip() for value in
                 (anilist, kitsu, wikipedia, provider) if str(value or '').strip()), '')


def reference_work_key(selected_work_id, evidence):
    row = dict(evidence or {})
    stable = str(selected_work_id or '').strip()
    if stable:
        return stable
    return '|'.join((str(row.get('title') or '').casefold().strip(), str(row.get('author') or '').casefold().strip()))


def _strong_external_ids(value):
    values={}
    for part in str(value or '').split('|'):
        if ':' in part:
            source,identifier=part.split(':',1)
            if source.strip() and identifier.strip():
                values[source.casefold().strip()]=identifier.strip()
    return values


def _compatibility_metadata(row, edition):
    title=normalize_identity_text(row.get('canonical_title') or row.get('title'))
    creators=tuple(sorted({creator_comparison_identity(value) for value in
        (row.get('canonical_creators') or row.get('creators') or ())
        if creator_comparison_identity(value)}))
    work_id=str(row.get('canonical_work_id') or '').strip()
    payload={'title':title,'creators':creators,'edition':_edition_profile(edition),'work_id':work_id}
    digest=hashlib.sha256(json.dumps(
        {'title':title,'creators':creators,'edition':payload['edition']},
        sort_keys=True,separators=(',',':'),ensure_ascii=False,
    ).encode('utf-8')).hexdigest()[:24] if title and creators else ''
    return payload,digest


def _compatible_pointer(pointer, metadata):
    row=dict(pointer or {}); stored=dict(row.get('compatibility') or {})
    if not row.get('resolved_key') or not stored:
        return False
    stored_creators=tuple(tuple(value) for value in stored.get('creators') or ())
    if (stored.get('title') != metadata.get('title') or stored_creators != metadata.get('creators') or
            stored.get('edition') != metadata.get('edition')):
        return False
    left=_strong_external_ids(stored.get('work_id')); right=_strong_external_ids(metadata.get('work_id'))
    return not any(source in right and right[source] != identifier for source,identifier in left.items())


def _google_targets(result):
    canonical_volumes=set()
    for volume in result.get('wikipedia',{}).get('volumes') or ():
        number=normalize_chapter_number(dict(volume or {}).get('number') or dict(volume or {}).get('volume'))
        if number is not None: canonical_volumes.add(number)
    for chapter in result.get('wikipedia',{}).get('chapters') or ():
        number=normalize_chapter_number(dict(chapter or {}).get('volume'))
        if number is not None: canonical_volumes.add(number)
    covered={normalize_chapter_number(dict(cover or {}).get('volume'))
             for cover in result.get('bookwalker',{}).get('covers') or ()}
    return tuple(sorted(canonical_volumes-{value for value in covered if value is not None},key=float))


def _usable_wikipedia_cache(value, adapter):
    row = dict(value or {})
    patterns = {
        getattr(adapter, 'pattern_id', ''),
        getattr(adapter, 'collection_pattern_id', ''),
    }
    return bool(
        row.get('cache_contract') == WIKIPEDIA_CACHE_CONTRACT and
        row.get('parser_pattern') in patterns and
        row.get('parser_version') == getattr(adapter, 'parser_version', '') and
        row.get('status') in ('valid_with_data', 'valid_complete', 'valid_partial') and
        row.get('chapters')
    )


def _wikipedia_result(match, structure_page, chapters, volumes, adapter,
                      status='', collection=None):
    chapter_rows = [asdict(value) for value in chapters]
    collection_metadata = collection.metadata() if collection is not None else {}
    result = {
        'cache_contract': WIKIPEDIA_CACHE_CONTRACT,
        'parser_pattern': (
            getattr(adapter, 'collection_pattern_id', '') if collection is not None
            else getattr(adapter, 'pattern_id', '')
        ),
        'parser_version': getattr(adapter, 'parser_version', ''),
        'match': asdict(match), 'structure_page': structure_page,
        'status': status or ('valid_with_data' if chapter_rows else (
            'unsupported_layout' if not structure_page else 'supported_empty'
        )),
        'chapters': chapter_rows,
        'volumes': [asdict(value) for value in volumes],
        'collection': collection_metadata,
    }
    identity = {
        'contract': WIKIPEDIA_CACHE_CONTRACT,
        'parser_pattern': result['parser_pattern'],
        'parser_version': result['parser_version'],
        'publication_id': match.publication_id,
        'structure_page': structure_page,
        'collection_root': collection_metadata.get('root') or {},
        'collection_indexes': collection_metadata.get('index_pages') or (),
        'collection_segments': [
            {key: row.get(key) for key in ('page_id', 'revision_id', 'parser_pattern', 'parser_version')}
            for row in collection_metadata.get('segments') or ()
        ],
    }
    digest = hashlib.sha256(json.dumps(
        identity, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
    ).encode('utf-8')).hexdigest()[:24]
    result['cache_identity'] = f'wikipedia:{match.publication_id}:{digest}'
    return result


def _usable_bookwalker_cache(value):
    row = dict(value or {})
    match = dict(row.get('match') or {})
    return bool(
        row.get('cache_contract') == BOOKWALKER_CACHE_CONTRACT and
        match.get('confidence') == 'confident' and match.get('publication_id') and
        (row.get('covers') or row.get('edition_artwork') or row.get('description'))
    )


class ReferenceMetadataService:
    """Bounded post-selection lookup with persistent success-only caching."""

    def __init__(self, cache, wikipedia=None, bookwalker=None, google_books=None):
        self.cache = cache
        self.wikipedia = wikipedia or WikipediaPublicationAdapter()
        self.bookwalker = bookwalker or BookwalkerPublicationAdapter()
        self.google_books = google_books or GoogleBooksArtworkResolver()

    def lookup(self, selected_work_id, evidence):
        row = dict(evidence or {})
        key = str(row.get('reference_key') or '').strip() or reference_work_key(selected_work_id, row)
        edition = str(row.get('edition') or 'original')
        result = {'work_key': key, 'edition': edition, 'wikipedia': {}, 'bookwalker': {},
                  'google_books': {}, 'errors': {}}
        compatibility,compatibility_key=_compatibility_metadata(row,edition)

        wiki_pointer = 'work:' + key
        pointer = self.cache.get_reference_structure(wiki_pointer) if self.cache else None
        if pointer is None and self.cache:
            pointer = self.cache.get('reference_structure', wiki_pointer, allow_stale=True)
        compatible_reuse=False
        if pointer is None and self.cache and compatibility_key:
            secondary=self.cache.get_reference_structure('compatible-wiki:'+compatibility_key)
            if secondary is None:
                secondary=self.cache.get('reference_structure','compatible-wiki:'+compatibility_key,allow_stale=True)
            if secondary is not None and _compatible_pointer(secondary.value,compatibility):
                pointer=secondary; compatible_reuse=True
        resolved_key = str(((pointer.value if pointer else {}) or {}).get('resolved_key') or '')
        hit = self.cache.get_reference_structure(resolved_key) if self.cache and resolved_key else None
        stale = (self.cache.get('reference_structure', resolved_key, allow_stale=True)
                 if self.cache and resolved_key and hit is None else None)
        stale_invalidated = bool(hit is not None and not _usable_wikipedia_cache(hit.value, self.wikipedia))
        if stale_invalidated:
            self.cache.delete('reference_structure', resolved_key)
            self.cache.delete('reference_structure', wiki_pointer)
            hit = None
        if hit is not None and _usable_wikipedia_cache(hit.value, self.wikipedia):
            result['wikipedia'] = dict(hit.value or {})
            result['wikipedia']['cache_state'] = 'compatible_hit' if compatible_reuse else 'hit'
            if compatible_reuse:
                result['wikipedia']['cache_note'] = 'reused from compatible validated publication identity'
            result['wikipedia']['network'] = {
                'requests': 0, 'retries': 0, 'rate_limits': 0,
                'segment_cache_hits': 0, 'collection_cache_hits': 1,
            }
        else:
            last_known_good = (dict(stale.value or {})
                               if stale is not None and _usable_wikipedia_cache(stale.value, self.wikipedia)
                               else {})
            try:
                match = self.wikipedia.match_publication(row)
                if match.confidence == 'confident':
                    if hasattr(self.wikipedia, 'resolve_publication'):
                        def segment_cache_get(segment_key):
                            if not self.cache:
                                return None
                            segment_hit = self.cache.get_reference_structure(segment_key)
                            if segment_hit is None:
                                segment_hit = self.cache.get(
                                    'reference_structure', segment_key, allow_stale=True
                                )
                            return dict(segment_hit.value or {}) if segment_hit else None

                        def segment_cache_put(segment_key, value):
                            if self.cache:
                                self.cache.put_reference_structure(segment_key, value)

                        resolved = self.wikipedia.resolve_publication(
                            match, segment_cache_get, segment_cache_put,
                        )
                        collection = resolved.get('collection')
                        parsed = _wikipedia_result(
                            match, str(resolved.get('structure_page') or ''),
                            tuple(resolved.get('chapters') or ()),
                            tuple(resolved.get('volumes') or ()), self.wikipedia,
                            str(resolved.get('status') or ''), collection,
                        )
                    else:
                        structure_page = self.wikipedia.get_structure_page(match)
                        chapters = self.wikipedia.get_chapter_list(match)
                        volumes = self.wikipedia.get_volume_list(match)
                        parsed = _wikipedia_result(
                            match, structure_page, chapters, volumes, self.wikipedia,
                        )
                    parsed['network'] = {
                        'requests': int(getattr(self.wikipedia, 'request_count', 0) or 0),
                        'retries': int(getattr(self.wikipedia, 'retry_count', 0) or 0),
                        'rate_limits': int(getattr(self.wikipedia, 'rate_limit_count', 0) or 0),
                        'segment_cache_hits': int(getattr(self.wikipedia, 'segment_cache_hits', 0) or 0),
                        'collection_cache_hits': 0,
                    }
                    if parsed['status'] in ('valid_with_data', 'valid_complete', 'valid_partial'):
                        result['wikipedia'] = parsed
                        result['wikipedia']['cache_state'] = (
                            'refreshed_after_invalidation' if stale_invalidated else 'refreshed'
                        )
                        if self.cache:
                            resolved_key = str(parsed.get('cache_identity') or '')
                            self.cache.put_reference_structure(resolved_key, result['wikipedia'])
                            pointer_value={'resolved_key':resolved_key,'compatibility':compatibility}
                            self.cache.put_reference_structure(wiki_pointer,pointer_value)
                            if compatibility_key:
                                self.cache.put_reference_structure('compatible-wiki:'+compatibility_key,pointer_value)
                    elif last_known_good:
                        result['wikipedia'] = last_known_good
                        result['wikipedia']['cache_state'] = 'last_known_good'
                        result['wikipedia']['refresh_status'] = parsed['status']
                        result['wikipedia']['refresh_network'] = parsed['network']
                    else:
                        result['wikipedia'] = parsed
                else:
                    status=('ambiguous' if match.confidence == 'ambiguous' else 'unmatched')
                    result['wikipedia'] = {'match': asdict(match), 'status': status,
                                           'chapters': [], 'volumes': []}
            except Exception as exc:
                if last_known_good:
                    result['wikipedia'] = last_known_good
                    result['wikipedia']['cache_state'] = 'last_known_good'
                    result['wikipedia']['refresh_error'] = str(exc)
                    result['wikipedia']['refresh_network'] = {
                        'requests': int(getattr(self.wikipedia, 'request_count', 0) or 0),
                        'retries': int(getattr(self.wikipedia, 'retry_count', 0) or 0),
                        'rate_limits': int(getattr(self.wikipedia, 'rate_limit_count', 0) or 0),
                        'segment_cache_hits': int(getattr(self.wikipedia, 'segment_cache_hits', 0) or 0),
                        'collection_cache_hits': 0,
                    }
                else:
                    message = str(exc)
                    status = 'rate_limited' if '429' in message else 'transient_failure'
                    result['wikipedia'] = {
                        'status': status, 'error': message, 'chapters': [], 'volumes': [],
                        'cache_contract': WIKIPEDIA_CACHE_CONTRACT,
                        'parser_pattern': getattr(self.wikipedia, 'collection_pattern_id',
                                                  getattr(self.wikipedia, 'pattern_id', '')),
                        'parser_version': getattr(self.wikipedia, 'parser_version', ''),
                    }
                    result['errors']['wikipedia'] = message

        book_pointer = 'work:' + key + ':' + edition
        pointer = self.cache.get_reference_catalog(book_pointer) if self.cache else None
        if pointer is None and self.cache:
            pointer = self.cache.get('reference_catalog', book_pointer, allow_stale=True)
        compatible_book_reuse=False
        if pointer is None and self.cache and compatibility_key:
            secondary=self.cache.get_reference_catalog('compatible-book:'+compatibility_key)
            if secondary is None:
                secondary=self.cache.get('reference_catalog','compatible-book:'+compatibility_key,allow_stale=True)
            if secondary is not None and _compatible_pointer(secondary.value,compatibility):
                pointer=secondary; compatible_book_reuse=True
        resolved_key = str(((pointer.value if pointer else {}) or {}).get('resolved_key') or '')
        hit = self.cache.get_reference_catalog(resolved_key) if self.cache and resolved_key else None
        stale = (self.cache.get('reference_catalog', resolved_key, allow_stale=True)
                 if self.cache and resolved_key and hit is None else None)
        if hit is not None and _usable_bookwalker_cache(hit.value):
            result['bookwalker'] = dict(hit.value or {})
            result['bookwalker']['cache_state'] = 'compatible_hit' if compatible_book_reuse else 'hit'
            if compatible_book_reuse:
                result['bookwalker']['cache_note'] = 'reused from compatible validated publication identity'
        else:
            last_known_good = (dict(stale.value or {})
                               if stale is not None and _usable_bookwalker_cache(stale.value)
                               else {})
            try:
                match = self.bookwalker.match_publication(row)
                if match.confidence == 'confident':
                    volumes = self.bookwalker.get_volume_list(match)
                    covers = self.bookwalker.get_volume_covers(match)
                    edition_art = self.bookwalker.get_edition_artwork(match)
                    result['bookwalker'] = {
                        'cache_contract': BOOKWALKER_CACHE_CONTRACT,
                        'match': asdict(match),
                        'volumes': [asdict(value) for value in volumes],
                        'covers': [asdict(value) for value in covers],
                        'edition_artwork': [asdict(value) for value in edition_art],
                        'description': self.bookwalker.get_description(match),
                        'catalog': (self.bookwalker.catalog_metadata(match)
                                    if hasattr(self.bookwalker,'catalog_metadata') else
                                    {'complete':True,'partial':False,'pages_fetched':1}),
                    }
                    if _usable_bookwalker_cache(result['bookwalker']):
                        new_count=len(result['bookwalker'].get('covers') or ())
                        old_count=len(last_known_good.get('covers') or ())
                        old_publication=str((last_known_good.get('match') or {}).get('publication_id') or '')
                        new_publication=str((result['bookwalker'].get('match') or {}).get('publication_id') or '')
                        new_partial=bool(result['bookwalker'].get('catalog',{}).get('partial'))
                        old_complete=bool(last_known_good.get('catalog',{}).get('complete',True))
                        if last_known_good and ((new_partial and old_complete) or new_count < old_count or
                                                 (old_publication and new_publication != old_publication)):
                            result['bookwalker'] = last_known_good
                            result['bookwalker']['cache_state'] = 'last_known_good'
                            result['bookwalker']['refresh_note'] = 'weaker or inconsistent artwork refresh ignored'
                        else:
                            result['bookwalker']['cache_state'] = 'partial' if new_partial else 'refreshed'
                    elif last_known_good:
                        result['bookwalker'] = last_known_good
                        result['bookwalker']['cache_state'] = 'last_known_good'
                    if self.cache and result['bookwalker'].get('cache_state') == 'refreshed':
                        resolved_key=str(match.publication_id) + ':' + str(match.edition_id or edition)
                        self.cache.put_reference_catalog(resolved_key, result['bookwalker'])
                        pointer_value={'resolved_key':resolved_key,'compatibility':compatibility}
                        self.cache.put_reference_catalog(book_pointer,pointer_value)
                        if compatibility_key:
                            self.cache.put_reference_catalog('compatible-book:'+compatibility_key,pointer_value)
            except Exception as exc:
                if last_known_good:
                    result['bookwalker'] = last_known_good
                    result['bookwalker']['cache_state'] = 'last_known_good'
                    result['bookwalker']['refresh_error'] = str(exc)
                else:
                    result['errors']['bookwalker'] = str(exc)
        requested_language=str(row.get('requested_language') or '').casefold()
        edition_profile=str(row.get('edition_profile') or '').casefold()
        targets=_google_targets(result)
        google_key=f'google:{GOOGLE_BOOKS_CACHE_CONTRACT}:{key}:{requested_language}:{edition_profile}'
        hit=self.cache.get_reference_catalog(google_key) if self.cache else None
        stale=(self.cache.get('reference_catalog',google_key,allow_stale=True)
               if self.cache and hit is None else None)
        cached_google=dict(hit.value or {}) if hit is not None else {}
        cached_targets=tuple(sorted({normalize_chapter_number(value) for value in
            cached_google.get('target_volumes') or () if normalize_chapter_number(value) is not None},key=float))
        if (hit is not None and cached_google.get('cache_contract') == GOOGLE_BOOKS_CACHE_CONTRACT and
                cached_google.get('detail_cache_contract') == GOOGLE_BOOKS_DETAIL_CACHE_CONTRACT and
                cached_targets == targets):
            result['google_books']=dict(hit.value or {}); result['google_books']['cache_state']='hit'
            result['google_books']['network']={'requests':0}
        else:
            context={
                'canonical_work_id':selected_work_id,'canonical_title':row.get('title') or '',
                'trusted_aliases':tuple(row.get('aliases') or ()),
                'canonical_creators':tuple(row.get('creators') or ()),
                'canonical_creator_aliases':tuple(row.get('creator_aliases') or ()),
                'requested_language':requested_language,'edition_profile':edition_profile,
                'reference_key':key,
            }
            try:
                if getattr(self.google_books,'supports_detail_cache',False) and self.cache:
                    def detail_cache_get(volume_id):
                        detail_hit=self.cache.get_reference_catalog(
                            'google-detail:'+GOOGLE_BOOKS_DETAIL_CACHE_CONTRACT+':'+str(volume_id)
                        )
                        return dict(detail_hit.value or {}) if detail_hit else None

                    def detail_cache_put(volume_id,value):
                        self.cache.put_reference_catalog(
                            'google-detail:'+GOOGLE_BOOKS_DETAIL_CACHE_CONTRACT+':'+str(volume_id),value
                        )
                    google=self.google_books.resolve(context,targets,detail_cache_get,detail_cache_put)
                else:
                    google=self.google_books.resolve(context,targets)
                google['cache_state']='refreshed'
                result['google_books']=google
                if self.cache and google.get('status') == 'valid':
                    self.cache.put_reference_catalog(google_key,google)
            except Exception as exc:
                stale_value=dict(stale.value or {}) if stale is not None else {}
                stale_targets=tuple(sorted({normalize_chapter_number(value) for value in
                    stale_value.get('target_volumes') or () if normalize_chapter_number(value) is not None},key=float))
                if (stale is not None and stale_value.get('cache_contract') == GOOGLE_BOOKS_CACHE_CONTRACT and
                        stale_targets == targets):
                    result['google_books']=dict(stale.value or {})
                    result['google_books']['cache_state']='last_known_good'
                    result['google_books']['refresh_error']=str(exc)
                else:
                    result['google_books']={'cache_contract':GOOGLE_BOOKS_CACHE_CONTRACT,
                                            'status':'transient_failure','error':str(exc),'covers':[]}
                    result['errors']['google_books']=str(exc)
        return result
