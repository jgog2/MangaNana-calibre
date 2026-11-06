"""Production-facing reference lookup and conservative field merge helpers."""

from dataclasses import asdict, dataclass
from concurrent.futures import CancelledError
import hashlib
import json
import re

from calibre_plugins.manganana.metadata.references.madb_reference import (
    MadbPublicationAdapter,
    CACHE_CONTRACT as MADB_CACHE_CONTRACT,
    MATCHER_CONTRACT,
    trusted_titles,
)
from calibre_plugins.manganana.metadata.references.bookwalker_reference import BookwalkerPublicationAdapter
from calibre_plugins.manganana.metadata.references.google_books_reference import (
    CACHE_CONTRACT as GOOGLE_BOOKS_CACHE_CONTRACT,
    DETAIL_CACHE_CONTRACT as GOOGLE_BOOKS_DETAIL_CACHE_CONTRACT,
    GoogleBooksArtworkResolver,
    GoogleBooksCredentialsChanged,
)
from calibre_plugins.manganana.discovery.canonical_identity import creator_comparison_identity, normalize_identity_text
from calibre_plugins.manganana.publication.chapter_workflow import chapter_label
from calibre_plugins.manganana.providers.cross_source_fallback import normalize_chapter_number
from calibre_plugins.manganana.metadata.references.wikipedia_reference import WikipediaPublicationAdapter


PLACEHOLDER_TITLES = frozenset({'', 'fallback', 'unknown', 'none', 'null', 'n/a', 'untitled'})
WIKIPEDIA_CACHE_CONTRACT = 'wikipedia-structure-v3-collection'
BOOKWALKER_CACHE_CONTRACT = 'bookwalker-publication-v5-canonical-evidence'


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
    canonical_aliases: tuple = ()
    creator_provenance: str = ""
    mangadex_title_ids: tuple = ()

    def lookup_evidence(self):
        return {
            'canonical_work_id': self.canonical_work_id,
            'canonical_title': self.canonical_title,
            'title': self.canonical_title,
            'aliases': self.trusted_aliases,
            'canonical_aliases': self.canonical_aliases,
            'creator_provenance': self.creator_provenance,
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
            'mangadex_title_ids': self.mangadex_title_ids,
        }


def _stable_values(values, identity=normalize_identity_text):
    """One stable spelling per normalized identity, independent of input order."""
    indexed = {}
    for value in values:
        text = str(value or '').strip()
        key = identity(text)
        if key:
            indexed[key] = min(text, indexed.get(key, text))
    return tuple(indexed[key] for key in sorted(indexed))


def _native_creator_relationship(creators, native, relationship):
    """Recognize known creator components without guessing new name aliases."""
    known = {_creator_identity(value) for value in creators if _creator_identity(value)}
    components = tuple(part.strip() for part in re.split(r'[,/]', str(native)) if part.strip())
    if components and all(_creator_identity(value) in known for value in components):
        return 'MATCH'
    # Preserve comma surname/given spelling and existing script comparison.
    return relationship(creators, (native,))


def canonical_family_publication_context(selected, records=(), edition=None):
    """Freeze trusted family evidence; raw acquisition aliases never enter it."""
    from calibre_plugins.manganana.discovery.canonical_identity import edition_identity
    from calibre_plugins.manganana.providers.source_policy import compatible_media, supported_media
    from calibre_plugins.manganana.metadata.references.madb_reference import creator_relationship
    selected = dict(selected or {})
    work = str(selected.get('canonical_work_id') or '')
    profile = _edition_profile(edition or edition_identity(selected))
    confidence = (selected.get('_canonical_identity_confidence') or '') if supported_media(selected) else ''
    family = []
    for original in (selected, *records):
        row = dict(original or {})
        if (not work or confidence != 'high' or
                row.get('canonical_work_id') != work or
                row.get('_canonical_identity_confidence') != 'high' or
                _edition_profile(edition_identity(row)) != profile or
                not supported_media(row) or not compatible_media(selected, row)):
            continue
        creators = tuple(row.get('canonical_creators') or ()) or (
            (row['canonical_author'],) if row.get('canonical_author') else ())
        native = row.get('_provider_native_author') or row.get('author')
        if (native and _creator_identity(native) != _creator_identity(', '.join(creators)) and
                _native_creator_relationship(creators, native, creator_relationship) == 'CONTRADICTION'):
            if row == selected:
                return canonical_publication_context(work, {'identity_confidence':'ambiguous'})
            continue
        family.append(row)
    titles = _stable_values(row.get('canonical_title') for row in family)
    creators = _stable_values((c for row in family for c in (
        row.get('canonical_creators') or ((row['canonical_author'],) if row.get('canonical_author') else ()))), _creator_identity)
    # Conflicting trusted creators are not resolved by provider response order.
    for first in family:
        for second in family:
            a = first.get('canonical_creators') or ((first['canonical_author'],) if first.get('canonical_author') else ())
            b = second.get('canonical_creators') or ((second['canonical_author'],) if second.get('canonical_author') else ())
            if creator_relationship(a, b) == 'CONTRADICTION':
                return canonical_publication_context(work, {'identity_confidence':'ambiguous'})
    aliases = _stable_values((*titles, *(a for row in family for a in row.get('canonical_aliases') or ())))
    context = canonical_publication_context(work, {
        'canonical_title': titles[0] if titles else '', 'trusted_aliases': aliases,
        'canonical_aliases': aliases, 'canonical_creators': creators,
        'canonical_creator_aliases': _stable_values(a for row in family for a in row.get('canonical_creator_aliases') or ()),
        'identity_confidence': confidence, 'edition_profile': profile,
        'canonical_creator_provenance': (family[0].get('canonical_creator_provenance') or 'canonical')
            if family and len({row.get('canonical_creator_provenance') or 'canonical' for row in family})==1 else 'canonical',
    })
    from dataclasses import replace
    return replace(context, canonical_creator_aliases=_stable_values(
        a for row in family for a in row.get('canonical_creator_aliases') or ()),
        mangadex_title_ids=tuple(sorted({
        str(row.get('id') or '') for row in family
        if row.get('source_id') == 'mangadex' and row.get('id')
    })))


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
        tuple(row.get("canonical_aliases", row.get("trusted_aliases", ())) or ()),
        str(row.get("canonical_creator_provenance") or "canonical"),
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
    if row.get('_unit_kind') == 'volume':
        return str(row.get('title') or ('Volume '+str(row.get('volume'))))
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
    builder = reference_artwork_builder(result)
    builder.apply_bookwalker(result.get('bookwalker'))
    return artwork_gaps(builder.build())


def artwork_gaps(manifest):
    from calibre_plugins.manganana.publication.publication_manifest import trusted_volume_numbers
    return tuple(number for number in trusted_volume_numbers(manifest)
                 if not manifest.volume(number).cover)


def reference_artwork_builder(result):
    """One structural universe for every reference artwork stage."""
    from calibre_plugins.manganana.publication.publication_manifest import PublicationManifestBuilder
    evidence=dict(result.get('publication_evidence') or {})
    identity=dict(result.get('mangadex_structure') or {})
    work=evidence.get('canonical_work_id') or identity.get('canonical_work_id') or 'reference'
    builder=PublicationManifestBuilder({'canonical_identity':work,'title':evidence.get('title') or ''},
                                      evidence.get('edition') or 'original')
    acquisition=dict(result.get('acquisition') or {})
    builder.apply_provider_inventory(acquisition.get('chapters') or (),acquisition.get('source_id') or 'provider')
    builder.apply_mangadex_structure(identity).apply_wikipedia(result.get('wikipedia'))
    builder.apply_provider_covers(acquisition.get('covers'),acquisition.get('source_id') or 'provider')
    builder.apply_mangadex_artwork(result.get('mangadex_artwork'))
    return builder


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

    def __init__(self, cache, wikipedia=None, bookwalker=None, google_books=None, madb=None, madb_enabled=False,
                 mangadex_structure=None, mangadex_structure_enabled=False, mangadex_artwork=None,
                 mangadex_artwork_enabled=False):
        self.cache = cache
        self.madb = madb or MadbPublicationAdapter()
        self.madb_enabled = bool(madb_enabled)
        self.wikipedia = wikipedia or WikipediaPublicationAdapter()
        self.bookwalker = bookwalker or BookwalkerPublicationAdapter()
        self.google_books = google_books or GoogleBooksArtworkResolver()
        self.mangadex_structure = mangadex_structure
        self.mangadex_structure_enabled = bool(mangadex_structure_enabled or mangadex_structure is not None)
        self.mangadex_artwork = mangadex_artwork
        self.mangadex_artwork_enabled=bool(mangadex_artwork_enabled or mangadex_artwork is not None)

    def lookup(self, selected_work_id, evidence, should_cancel=None, acquisition=None):
        should_cancel = should_cancel or (lambda: False)

        def check_cancel():
            if should_cancel():
                raise CancelledError()

        for adapter in (self.wikipedia, self.bookwalker, self.google_books):
            if hasattr(adapter, 'set_cancel_check'):
                adapter.set_cancel_check(should_cancel)
        check_cancel()
        row = dict(evidence or {})
        key = str(row.get('reference_key') or '').strip() or reference_work_key(selected_work_id, row)
        edition = str(row.get('edition') or 'original')
        result = {'work_key': key, 'edition': edition, 'wikipedia': {}, 'bookwalker': {},
                  'google_books': {}, 'errors': {}}
        result['publication_evidence']=row
        result['acquisition']=dict(acquisition or {})
        if self.mangadex_structure_enabled:
            if self.mangadex_structure is None:
                from calibre_plugins.manganana.metadata.references.mangadex_structure_reference import MangaDexStructureResolver
                self.mangadex_structure = MangaDexStructureResolver(self.cache)
            result['mangadex_structure'] = self.mangadex_structure.lookup(row, should_cancel)
            check_cancel()
        compatibility,compatibility_key=_compatibility_metadata(row,edition)
        # Chapter-to-volume structure is edition-agnostic when the canonical work
        # is the same. Official/fan color releases normally preserve chapter
        # numbering even when their artwork/catalog identity is edition-specific.
        # Normalize only the Wikipedia structural lookup to the standard edition;
        # BOOK☆WALKER/Google Books remain edition-sensitive below.
        wiki_edition = ('original' if _edition_profile(edition) in ('standard','color','fan_color')
                        else edition)
        wiki_row = dict(row); wiki_row['edition'] = wiki_edition
        wiki_compatibility,wiki_compatibility_key=_compatibility_metadata(row,wiki_edition)

        wiki_pointer = 'work:' + key
        pointer = self.cache.get_reference_structure(wiki_pointer) if self.cache else None
        if pointer is None and self.cache:
            pointer = self.cache.get('reference_structure', wiki_pointer, allow_stale=True)
        compatible_reuse=False
        if pointer is None and self.cache and wiki_compatibility_key:
            secondary=self.cache.get_reference_structure('compatible-wiki:'+wiki_compatibility_key)
            if secondary is None:
                secondary=self.cache.get('reference_structure','compatible-wiki:'+wiki_compatibility_key,allow_stale=True)
            if secondary is not None and _compatible_pointer(secondary.value,wiki_compatibility):
                pointer=secondary; compatible_reuse=True
        resolved_key = str(((pointer.value if pointer else {}) or {}).get('resolved_key') or '')
        hit = self.cache.get_reference_structure(resolved_key) if self.cache and resolved_key else None
        stale = (self.cache.get('reference_structure', resolved_key, allow_stale=True)
                 if self.cache and resolved_key and hit is None else None)
        stale_invalidated = bool(hit is not None and not _usable_wikipedia_cache(hit.value, self.wikipedia))
        if stale_invalidated:
            check_cancel()
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
                check_cancel()
                if hasattr(self.wikipedia,'begin_refresh'):
                    self.wikipedia.begin_refresh()
                match = self.wikipedia.match_publication(wiki_row)
                check_cancel()
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
                            check_cancel()
                            if self.cache:
                                self.cache.put_reference_structure(segment_key, value)

                        check_cancel()
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
                        parsed['unnumbered_evidence']=list(resolved.get('unnumbered_evidence') or ())
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
                            check_cancel()
                            resolved_key = str(parsed.get('cache_identity') or '')
                            self.cache.put_reference_structure(resolved_key, result['wikipedia'])
                            check_cancel()
                            pointer_value={'resolved_key':resolved_key,'compatibility':wiki_compatibility}
                            self.cache.put_reference_structure(wiki_pointer,pointer_value)
                            if wiki_compatibility_key:
                                check_cancel()
                                self.cache.put_reference_structure('compatible-wiki:'+wiki_compatibility_key,pointer_value)
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
            except CancelledError:
                raise
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

        check_cancel()
        if self.mangadex_artwork_enabled:
            if self.mangadex_artwork is None:
                from calibre_plugins.manganana.metadata.references.mangadex_artwork_reference import MangaDexArtworkResolver
                self.mangadex_artwork=MangaDexArtworkResolver(self.cache)
            catalog=dict(acquisition or {}).get('artwork_catalog')
            options={'catalog':catalog} if catalog else {}
            result['mangadex_artwork']=self.mangadex_artwork.lookup(row,result.get('mangadex_structure'),should_cancel,**options)
            check_cancel()
        builder=reference_artwork_builder(result)
        from calibre_plugins.manganana.publication.publication_manifest import trusted_volume_numbers
        structural_snapshot=builder.build()
        result['trusted_volumes']=trusted_volume_numbers(structural_snapshot)
        result['bookwalker_targets']=artwork_gaps(structural_snapshot)
        # Keep BOOKWALKER's publication description/edition metadata even when its
        # artwork gaps are empty. Only exact trusted gaps can be decorated later.
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
                check_cancel()
                if hasattr(self.bookwalker,'begin_refresh'):
                    self.bookwalker.begin_refresh()
                match = self.bookwalker.match_publication(row)
                check_cancel()
                if match.confidence == 'confident':
                    volumes = self.bookwalker.get_volume_list(match)
                    check_cancel()
                    covers = self.bookwalker.get_volume_covers(match)
                    check_cancel()
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
                        check_cancel()
                        resolved_key=str(match.publication_id) + ':' + str(match.edition_id or edition)
                        self.cache.put_reference_catalog(resolved_key, result['bookwalker'])
                        check_cancel()
                        pointer_value={'resolved_key':resolved_key,'compatibility':compatibility}
                        self.cache.put_reference_catalog(book_pointer,pointer_value)
                        if compatibility_key:
                            check_cancel()
                            self.cache.put_reference_catalog('compatible-book:'+compatibility_key,pointer_value)
            except CancelledError:
                raise
            except Exception as exc:
                if last_known_good:
                    result['bookwalker'] = last_known_good
                    result['bookwalker']['cache_state'] = 'last_known_good'
                    result['bookwalker']['refresh_error'] = str(exc)
                else:
                    result['errors']['bookwalker'] = str(exc)
        check_cancel()
        result['madb'] = self._lookup_madb(key, row, should_cancel)
        requested_language=str(row.get('requested_language') or '').casefold()
        edition_profile=str(row.get('edition_profile') or '').casefold()
        builder.apply_bookwalker(result.get('bookwalker'))
        targets=artwork_gaps(builder.build())
        google_key=f'google:{GOOGLE_BOOKS_CACHE_CONTRACT}:{key}:{requested_language}:{edition_profile}'
        hit=self.cache.get_reference_catalog(google_key) if self.cache else None
        stale=(self.cache.get('reference_catalog',google_key,allow_stale=True)
               if self.cache and hit is None else None)
        cached_google=dict(hit.value or {}) if hit is not None else {}
        cached_targets=tuple(sorted({normalize_chapter_number(value) for value in
            cached_google.get('target_volumes') or () if normalize_chapter_number(value) is not None},key=float))
        current_google_keyed=bool(str(getattr(self.google_books,'api_key','') or '').strip())
        cached_google_keyed=str(cached_google.get('configuration_status') or '').startswith('configured')
        if isinstance(self.google_books, GoogleBooksArtworkResolver) and not self.google_books.enabled:
            result['google_books'] = self.google_books.resolve({}, targets)
            return result
        if (hit is not None and cached_google.get('cache_contract') == GOOGLE_BOOKS_CACHE_CONTRACT and
                cached_google.get('detail_cache_contract') == GOOGLE_BOOKS_DETAIL_CACHE_CONTRACT and
                cached_targets == targets and
                (not current_google_keyed or cached_google_keyed)):
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
                        check_cancel()
                        self.cache.put_reference_catalog(
                            'google-detail:'+GOOGLE_BOOKS_DETAIL_CACHE_CONTRACT+':'+str(volume_id),value
                        )
                    check_cancel()
                    google=self.google_books.resolve(context,targets,detail_cache_get,detail_cache_put)
                else:
                    check_cancel()
                    google=self.google_books.resolve(context,targets)
                check_cancel()
                google['cache_state']='refreshed'
                result['google_books']=google
                if self.cache and google.get('status') == 'valid':
                    check_cancel()
                    self.cache.put_reference_catalog(google_key,google)
            except GoogleBooksCredentialsChanged:
                result['google_books'] = {
                    'status': 'credentials_changed' if self.google_books.enabled else 'unavailable_no_api_key',
                    'covers': [], 'candidates': [], 'network': {'requests': 0},
                }
            except CancelledError:
                raise
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

    def _lookup_madb(self, key, evidence, should_cancel):
        if not self.madb_enabled:
            return {'status':'disabled','source':'madb','network':{'requests':0}}
        self.madb.set_cancel_check(should_cancel)
        if should_cancel(): raise CancelledError()
        if evidence.get('identity_confidence') != 'high' or not evidence.get('reference_key'):
            return self.madb.resolve(evidence)
        cache_key = MADB_CACHE_CONTRACT + ':' + MATCHER_CONTRACT + ':work:' + str(evidence.get('reference_key') or key) + ':' + _edition_profile(evidence.get('edition_profile') or evidence.get('edition'))
        identity = json.dumps([sorted(normalize_identity_text(t) for t in trusted_titles(evidence)),
                               sorted(creator_comparison_identity(c) for c in evidence.get('creators') or ())], ensure_ascii=False, sort_keys=True)
        cache_key += ':' + hashlib.sha256(identity.encode('utf-8')).hexdigest()[:16]
        def usable(hit):
            return bool(hit and hit.value.get('cache_contract') == MADB_CACHE_CONTRACT and
                        hit.value.get('status') == 'valid' and
                        hit.value.get('match',{}).get('confidence') == 'confident')
        hit = self.cache.get_reference_catalog(cache_key) if self.cache else None
        if usable(hit):
            return dict(hit.value,cache_state='hit',network={'requests':0})
        stale = self.cache.get('reference_catalog',cache_key,allow_stale=True) if self.cache else None
        try:
            value = self.madb.resolve(evidence)
            if should_cancel(): raise CancelledError()
            if value.get('status') == 'valid' and self.cache:
                ident = value['match']['series_id']
                self.cache.put_reference_catalog(MADB_CACHE_CONTRACT + ':series:' + ident + ':standard',value)
                self.cache.put_reference_catalog(cache_key,value)
            return value
        except CancelledError:
            raise
        except Exception as exc:
            if usable(stale):
                return dict(stale.value,cache_state='last_known_good',refresh_error=str(exc))
            return {'source':'madb','status':'transient_failure','error':str(exc),
                    'network':{'requests':self.madb.request_count}}
