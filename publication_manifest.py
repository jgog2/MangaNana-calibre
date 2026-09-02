"""Normalized publication snapshot and pure acquisition-inventory projection.

External sources contribute evidence to this Calibre/Qt-independent model.
Acquisition records remain separate and are projected through a manifest only
when a workflow needs publication titles, volume membership, or artwork.
"""

from dataclasses import dataclass, field, replace
from decimal import Decimal, InvalidOperation, ROUND_FLOOR
import re

try:
    from .canonical_identity import normalize_identity_text
    from .cross_source_fallback import normalize_chapter_number
except ImportError:
    from canonical_identity import normalize_identity_text
    from cross_source_fallback import normalize_chapter_number


MANIFEST_SCHEMA_VERSION = 'publication-manifest-v2'
_PLACEHOLDER_TITLES = frozenset({'', 'fallback', 'unknown', 'none', 'null', 'n/a', 'untitled'})


def normalize_publication_number(value):
    """Normalize only a finite non-negative explicit numeric volume label."""
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not number.is_finite() or number < 0:
        return None
    return format(number.normalize(), 'f')


def _placeholder_title(value, chapter_key=''):
    text = ' '.join(str(value or '').split())
    if text.casefold() in _PLACEHOLDER_TITLES:
        return True
    match = re.fullmatch(r'(?:(?:chapter|ch\.?)\s*)?([0-9]+(?:\.[0-9]+)?)', text, re.I)
    return bool(chapter_key and match and normalize_chapter_number(match.group(1)) == chapter_key)


@dataclass(frozen=True)
class FieldEvidence:
    value: object = None
    source: str = ''
    confidence: str = 'unknown'
    source_identity: str = ''
    status: str = 'valid'
    language: str = ''

    @property
    def present(self):
        return self.value not in (None, '', (), [], {})


@dataclass(frozen=True)
class ManifestWork:
    canonical_identity: str
    title: str
    aliases: tuple = ()
    creator: FieldEvidence = field(default_factory=FieldEvidence)
    language: str = ''


@dataclass(frozen=True)
class ManifestEdition:
    identity: str = 'unknown'
    language: str = ''
    market: str = ''
    provenance: FieldEvidence = field(default_factory=FieldEvidence)


@dataclass(frozen=True)
class ManifestChapter:
    key: str
    display_number: str
    kind: str = 'chapter'
    title: FieldEvidence = field(default_factory=FieldEvidence)
    volume: FieldEvidence = field(default_factory=FieldEvidence)


@dataclass(frozen=True)
class ManifestArtwork:
    url: str
    source: str
    artwork_type: str
    confidence: str
    publication_id: str = ''
    edition_id: str = ''
    volume_id: str = ''
    volume: str = ''
    preview_url: str = ''
    source_url: str = ''
    source_field: str = ''
    retrieval: str = ''

    @property
    def identity(self):
        """Stable presentation identity; never use a row position for artwork."""
        if self.source == 'google_books':
            return '|'.join(('google-books',str(self.publication_id or ''),'standard',
                             str(self.volume or ''),str(self.volume_id or '')))
        return '|'.join((
            str(self.artwork_type or ''), str(self.source or ''),
            str(self.publication_id or ''), str(self.edition_id or ''),
            str(self.volume_id or ''), str(self.volume or ''), str(self.url or ''),
        ))


@dataclass(frozen=True)
class ManifestVolume:
    key: str
    display_number: str
    chapter_keys: tuple = ()
    cover: object = None
    publication_identity: str = ''
    provenance: FieldEvidence = field(default_factory=FieldEvidence)


@dataclass(frozen=True)
class DescriptionCandidate:
    value: str
    source: str
    confidence: str = 'trusted'
    language: str = ''
    source_identity: str = ''
    status: str = 'valid'


@dataclass(frozen=True)
class ManifestDisplay:
    descriptions: tuple = ()
    description: FieldEvidence = field(default_factory=FieldEvidence)
    edition_artwork: object = None
    rating: FieldEvidence = field(default_factory=FieldEvidence)
    tags: tuple = ()


@dataclass(frozen=True)
class ManifestSourceState:
    source: str
    status: str = 'unresolved'
    source_identity: str = ''
    contract: str = ''
    parser_version: str = ''
    cache_state: str = ''
    last_validated: object = None


@dataclass(frozen=True)
class PublicationManifest:
    schema_version: str
    work: ManifestWork
    edition: ManifestEdition
    chapters: tuple = ()
    volumes: tuple = ()
    display: ManifestDisplay = field(default_factory=ManifestDisplay)
    source_states: tuple = ()
    ambiguous_chapter_keys: tuple = ()

    def chapter(self, value):
        key = normalize_chapter_number(value)
        return next((row for row in self.chapters if row.key == key), None) if key is not None else None

    def volume(self, value):
        key = normalize_publication_number(value)
        return next((row for row in self.volumes if row.key == key), None) if key is not None else None


@dataclass(frozen=True)
class ProjectedChapter:
    acquisition: dict
    canonical_key: str
    resolved_title: FieldEvidence
    effective_volume: FieldEvidence
    resolved_cover: object
    selected_provider: str
    acquisition_provider: str
    mapping_state: str

    def as_row(self):
        row=dict(self.acquisition)
        row['_selected_provider']=self.selected_provider
        row['_acquisition_provider']=self.acquisition_provider
        row['_projection_state']=self.mapping_state
        if self.resolved_title.present:
            row['title']=self.resolved_title.value
            row['_title_source']=self.resolved_title.source
            row['_title_confidence']=self.resolved_title.confidence
        if self.effective_volume.present:
            row['_effective_volume']=self.effective_volume.value
            if row.get('volume') in (None,''):
                row['volume']=self.effective_volume.value
            row['_volume_source']=self.effective_volume.source
            row['_volume_confidence']=self.effective_volume.confidence
        if self.resolved_cover:
            row['_publication_cover_url']=self.resolved_cover.preview_url or self.resolved_cover.url
            row['_publication_source_cover_url']=self.resolved_cover.source_url or self.resolved_cover.url
            row['_publication_cover_source']=self.resolved_cover.source
            row['_publication_cover_identity']=self.resolved_cover.identity
        return row


@dataclass(frozen=True)
class PublicationProjection:
    chapters: tuple
    selected_provider: str = ''

    @property
    def rows(self):
        return tuple(chapter.as_row() for chapter in self.chapters)

    @property
    def acquisition_providers(self):
        return tuple(dict.fromkeys(chapter.acquisition_provider for chapter in self.chapters
                                   if chapter.acquisition_provider))

    def chapters_for_volume(self, volume):
        key=normalize_publication_number(volume)
        return tuple(chapter for chapter in self.chapters
                     if chapter.effective_volume.present and
                     normalize_publication_number(chapter.effective_volume.value) == key)

    @property
    def unmapped(self):
        return tuple(chapter for chapter in self.chapters if not chapter.effective_volume.present)

    @property
    def coverage(self):
        states=[chapter.mapping_state for chapter in self.chapters]
        resolved=sum(state != 'unmapped' for state in states)
        return {
            'provider_chapters':len(self.chapters),
            'chapters_matched':resolved,
            'resolved_chapters':resolved,
            'provider_explicit':states.count('provider_explicit'),
            'reference_explicit':states.count('reference_explicit'),
            'derived_fractional':states.count('derived_fractional'),
            'derived_pre_chapter_one':states.count('derived_pre_chapter_one'),
            'unmapped_provider_chapters':states.count('unmapped'),
            'acquisition_providers':self.acquisition_providers,
            'selected_provider':self.selected_provider,
        }


def _source_priority(source):
    return {'bookwalker': 50, 'anilist': 40, 'kitsu': 30,
            'wikipedia': 20, 'provider': 10}.get(str(source or '').casefold(), 0)


def resolve_description(candidates, preferred_language=''):
    """Choose deterministically using explicit language evidence before source rank."""
    preferred = str(preferred_language or '').casefold().split('-', 1)[0]
    usable = [row for row in candidates or ()
              if row.value and row.status in ('valid', 'valid_stale') and
              str(row.source or '').casefold() != 'bookwalker']
    if not usable:
        return FieldEvidence()

    def score(row):
        language = str(row.language or '').casefold().split('-', 1)[0]
        language_rank = 3 if preferred and language == preferred else (1 if not language else 0)
        return (language_rank, _source_priority(row.source))

    selected = max(usable, key=score)
    return FieldEvidence(selected.value, selected.source, selected.confidence,
                         selected.source_identity, selected.status, selected.language)


class PublicationManifestBuilder:
    """Build a candidate snapshot while retaining stronger last-known-good data."""

    def __init__(self, work, edition='unknown', existing=None):
        row = dict(work or {})
        canonical = str(row.get('canonical_identity') or '').strip()
        title = str(row.get('title') or '').strip()
        if not canonical:
            canonical = normalize_identity_text(title)
        same = bool(existing and existing.schema_version == MANIFEST_SCHEMA_VERSION and
                    existing.work.canonical_identity == canonical and
                    existing.edition.identity == str(edition or 'unknown'))
        if same:
            self.work = existing.work
            self.edition = existing.edition
            self.chapters = {item.key: item for item in existing.chapters}
            self.volumes = {item.key: item for item in existing.volumes}
            self.descriptions = list(existing.display.descriptions)
            self.edition_artwork = existing.display.edition_artwork
            self.rating = existing.display.rating
            self.tags = list(existing.display.tags)
            self.source_states = {item.source: item for item in existing.source_states}
            self.ambiguous_chapter_keys = set(existing.ambiguous_chapter_keys)
        else:
            aliases = tuple(dict.fromkeys(str(value).strip() for value in row.get('aliases') or () if str(value or '').strip()))
            creator = str(row.get('creator') or '').strip()
            self.work = ManifestWork(canonical, title, aliases,
                                     FieldEvidence(creator, row.get('creator_source') or 'provider',
                                                   'explicit' if creator else 'unknown'),
                                     str(row.get('language') or ''))
            self.edition = ManifestEdition(str(edition or 'unknown'))
            self.chapters = {}
            self.volumes = {}
            self.descriptions = []
            self.edition_artwork = None
            self.rating = FieldEvidence()
            self.tags = []
            self.source_states = {}
            self.ambiguous_chapter_keys = set()

    def _set_state(self, state):
        self.source_states[state.source] = state

    def _set_chapter(self, key, display, kind='chapter', title=None, volume=None):
        current = self.chapters.get(key) or ManifestChapter(key, display or key, kind)
        self.chapters[key] = replace(
            current,
            display_number=current.display_number or display or key,
            kind=current.kind or kind,
            title=title if title is not None else current.title,
            volume=volume if volume is not None else current.volume,
        )

    def _rebuild_volume_membership(self):
        memberships = {}
        for chapter in self.chapters.values():
            key = normalize_publication_number(chapter.volume.value) if chapter.volume.present else None
            if key is not None:
                memberships.setdefault(key, []).append(chapter.key)
        for key, current in tuple(self.volumes.items()):
            chapter_keys=tuple(memberships.get(key, ()))
            evidence=[chapter.volume for chapter in self.chapters.values()
                      if chapter.key in chapter_keys and chapter.volume.present]
            preferred=next((item for item in evidence if item.source != 'wikipedia'),None)
            self.volumes[key] = replace(current,chapter_keys=chapter_keys,
                                        provenance=preferred or (evidence[0] if evidence else current.provenance))
        for key, chapter_keys in memberships.items():
            if key not in self.volumes:
                evidence=next(chapter.volume for chapter in self.chapters.values()
                              if chapter.key in chapter_keys and chapter.volume.present)
                self.volumes[key] = ManifestVolume(key, key, tuple(chapter_keys),provenance=evidence)

    def add_description(self, value, source, confidence='trusted', language='', source_identity='', status='valid'):
        text = str(value or '').strip()
        if not text:
            return
        candidate = DescriptionCandidate(text, str(source or ''), confidence,
                                         str(language or ''), str(source_identity or ''), status)
        identity = (candidate.source, candidate.source_identity, candidate.language, candidate.value)
        if identity not in {(row.source, row.source_identity, row.language, row.value) for row in self.descriptions}:
            self.descriptions.append(candidate)

    def apply_provider_inventory(self, chapters, source='provider'):
        source = str(source or 'provider')
        rows = tuple(chapters or ())
        for original in rows:
            row = dict(original)
            key = normalize_chapter_number(row.get('chapter'))
            if key is None:
                continue
            current = self.chapters.get(key)
            title_text = str(row.get('title') or '').strip()
            title = None
            if title_text and not _placeholder_title(title_text, key):
                title = FieldEvidence(title_text, source, 'explicit', str(row.get('id') or ''))
            elif current is None:
                title = FieldEvidence()
            volume_key = normalize_publication_number(row.get('volume'))
            volume = (FieldEvidence(volume_key, source, 'explicit', str(row.get('id') or ''))
                      if volume_key is not None else (FieldEvidence() if current is None else None))
            # Provider-explicit fields outrank reference fills; absent provider
            # fields leave an existing validated manifest value intact.
            self._set_chapter(key, str(row.get('chapter') or key), 'chapter', title, volume)
        self._rebuild_volume_membership()
        self._set_state(ManifestSourceState(source, 'valid' if rows else 'unsupported'))
        return self

    def apply_wikipedia(self, value):
        row = dict(value or {})
        match = dict(row.get('match') or {})
        cache_state=str(row.get('cache_state') or '')
        status = ('valid_stale' if cache_state == 'last_known_good' else
                  str(row.get('status') or ('transient_failure' if row.get('error') else 'unresolved')))
        self._set_state(ManifestSourceState(
            'wikipedia', status, str(row.get('structure_page') or match.get('publication_id') or ''),
            str(row.get('cache_contract') or ''), str(row.get('parser_version') or ''),
            cache_state, row.get('last_validated'),
        ))
        rows = tuple(row.get('chapters') or ())
        collection = dict(row.get('collection') or {})
        for group in collection.get('quarantined_groups') or ():
            key = normalize_chapter_number(dict(group or {}).get('display_key'))
            if key is not None:
                self.ambiguous_chapter_keys.add(key)
        if not rows:
            return self
        for original in rows:
            chapter = dict(original)
            key = normalize_chapter_number(chapter.get('number') or chapter.get('chapter'))
            if key is None or chapter.get('kind', 'chapter') not in (
                    'chapter', 'special', 'uncollected'):
                continue
            current = self.chapters.get(key)
            title_text = str(chapter.get('title') or '').strip()
            title = None
            if title_text and (current is None or not current.title.present or
                               current.title.source == 'wikipedia' or
                               _placeholder_title(current.title.value, key)):
                title = FieldEvidence(title_text, 'wikipedia',
                                      str(chapter.get('confidence') or 'explicit'),
                                      str(chapter.get('source_page') or ''))
            volume_key = normalize_publication_number(chapter.get('volume'))
            volume = None
            if volume_key is not None and (current is None or not current.volume.present or
                                           current.volume.source == 'wikipedia'):
                volume = FieldEvidence(volume_key, 'wikipedia',
                                       str(chapter.get('confidence') or 'explicit'),
                                       str(chapter.get('source_page') or ''))
            self._set_chapter(key, str(chapter.get('number') or key),
                              str(chapter.get('kind') or 'chapter'), title, volume)
        for original in row.get('volumes') or ():
            volume=dict(original)
            key=normalize_publication_number(volume.get('number') or volume.get('volume'))
            if key is None:
                continue
            current=self.volumes.get(key) or ManifestVolume(key,str(volume.get('number') or key))
            evidence=FieldEvidence(key,'wikipedia',str(volume.get('confidence') or 'explicit'),
                                   str(volume.get('source_page') or row.get('structure_page') or ''))
            self.volumes[key]=replace(current,provenance=evidence)
        self._rebuild_volume_membership()
        return self

    def apply_bookwalker(self, value):
        row = dict(value or {})
        match = dict(row.get('match') or {})
        publication_id = str(match.get('publication_id') or '')
        if not publication_id:
            self._set_state(ManifestSourceState('bookwalker',
                                                str(row.get('status') or 'transient_failure')))
            return self
        edition_id = str(match.get('edition_id') or '')
        cache_state=str(row.get('cache_state') or '')
        self._set_state(ManifestSourceState('bookwalker',
                                            'valid_stale' if cache_state == 'last_known_good' else 'valid',
                                            publication_id,cache_state=cache_state))
        self.edition = ManifestEdition(
            str(match.get('edition') or self.edition.identity),
            str(match.get('language') or self.edition.language),
            str(match.get('market') or self.edition.market),
            FieldEvidence(edition_id or publication_id, 'bookwalker', 'exact', publication_id),
        )
        for original in row.get('covers') or ():
            cover = dict(original)
            volume_key = normalize_publication_number(cover.get('volume'))
            if (volume_key is None or cover.get('artwork_type') != 'volume' or
                    cover.get('confidence') != 'exact' or
                    str(cover.get('edition_id') or '') != edition_id or not cover.get('url')):
                continue
            artwork = ManifestArtwork(
                str(cover['url']), 'bookwalker', 'exact_volume', 'exact', publication_id,
                edition_id, str(cover.get('volume_id') or ''), volume_key,
            )
            current = self.volumes.get(volume_key) or ManifestVolume(volume_key, volume_key)
            self.volumes[volume_key] = replace(current, cover=artwork,
                                               publication_identity=publication_id,
                                               provenance=(current.provenance if current.provenance.present else
                                                           FieldEvidence(volume_key,'bookwalker','exact',
                                                                         str(cover.get('volume_id') or ''))))
        edition_art = next((dict(item) for item in row.get('edition_artwork') or ()
                            if item.get('artwork_type') == 'edition' and item.get('url') and
                            str(item.get('edition_id') or '') == edition_id), None)
        if edition_art:
            self.edition_artwork = ManifestArtwork(
                str(edition_art['url']), 'bookwalker', 'edition',
                str(edition_art.get('confidence') or 'exact'), publication_id, edition_id,
                str(edition_art.get('volume_id') or ''),
            )
        self.add_description(row.get('description'), 'bookwalker', 'trusted',
                             str(row.get('description_language') or ''), publication_id)
        return self

    def apply_google_books(self, value):
        """Fill exact-art gaps only; Google never creates publication structure."""
        row=dict(value or {}); cache_state=str(row.get('cache_state') or '')
        status=str(row.get('status') or 'unresolved')
        self._set_state(ManifestSourceState(
            'google_books','valid_stale' if cache_state == 'last_known_good' else status,
            ','.join(str(value) for value in row.get('trusted_series_ids') or ()),
            contract=str(row.get('cache_contract') or ''),cache_state=cache_state,
        ))
        for original in row.get('covers') or ():
            cover=dict(original); volume_key=normalize_publication_number(cover.get('volume'))
            current=self.volumes.get(volume_key) if volume_key is not None else None
            if (current is None or current.cover is not None or
                    cover.get('artwork_type') != 'volume' or cover.get('confidence') != 'exact' or
                    cover.get('source') != 'google_books' or not cover.get('url')):
                continue
            artwork=ManifestArtwork(
                str(cover.get('source_url') or cover['url']),'google_books','exact_volume','exact',
                str(cover.get('publication_id') or ''),str(cover.get('edition_id') or 'standard:en'),
                str(cover.get('volume_id') or ''),volume_key,str(cover.get('preview_url') or ''),
                str(cover.get('source_url') or cover['url']),str(cover.get('source_field') or ''),
                str(cover.get('retrieval') or ''),
            )
            self.volumes[volume_key]=replace(current,cover=artwork)
        return self

    def apply_enrichment(self, value):
        row = dict(value or {})
        aliases = list(self.work.aliases)
        aliases.extend(row.get('alternate_titles') or ())
        creator = str(row.get('canonical_author') or '').strip()
        if creator:
            creator_evidence = FieldEvidence(creator, 'enrichment', 'trusted')
        else:
            creator_evidence = self.work.creator
        self.work = replace(self.work, aliases=tuple(dict.fromkeys(
            str(item).strip() for item in aliases if str(item or '').strip()
        )), creator=creator_evidence)
        candidates = tuple(row.get('work_description_candidates') or ())
        if candidates:
            for item in candidates:
                candidate = dict(item or {})
                self.add_description(candidate.get('value'), candidate.get('source') or 'enrichment',
                                     candidate.get('confidence') or 'trusted', candidate.get('language') or '',
                                     candidate.get('source_identity') or '')
        else:
            self.add_description(row.get('work_description'), 'enrichment')
        external_ids=dict(row.get('external_ids') or {})
        for source in ('anilist','kitsu'):
            source_identity=str(external_ids.get(source + '_id') or '')
            if source_identity or any(str(item.get('source') or '').casefold() == source for item in candidates):
                self._set_state(ManifestSourceState(source,'valid',source_identity))
        rating = row.get('consensus_rating')
        if rating is not None:
            self.rating = FieldEvidence(rating, 'anilist/kitsu', 'consensus')
        tags = tuple(row.get('work_tags') or ())
        if tags:
            self.tags = [FieldEvidence(tag, 'anilist/kitsu', 'trusted') for tag in tags]
        return self

    def build(self, preferred_language=''):
        display = ManifestDisplay(
            tuple(self.descriptions), resolve_description(self.descriptions, preferred_language),
            self.edition_artwork, self.rating, tuple(self.tags),
        )
        return PublicationManifest(
            MANIFEST_SCHEMA_VERSION, self.work, self.edition,
            tuple(sorted(self.chapters.values(), key=lambda row: Decimal(row.key))),
            tuple(sorted(self.volumes.values(), key=lambda row: Decimal(row.key))),
            display, tuple(self.source_states.values()),
            tuple(sorted(self.ambiguous_chapter_keys, key=Decimal)),
        )


def build_publication_projection(provider_inventory, manifest, selected_provider='', default_acquisition_provider=''):
    """Resolve publication evidence onto downloadable rows without mutating either."""
    rows=tuple(dict(row) for row in provider_inventory or ())
    acquisition_multiplicity={}
    for row in rows:
        key=normalize_chapter_number(row.get('chapter'))
        if key is not None:
            acquisition_multiplicity[key]=acquisition_multiplicity.get(key,0)+1
    base=[]
    for row in rows:
        key=normalize_chapter_number(row.get('chapter'))
        ambiguous=bool(
            (manifest and key in manifest.ambiguous_chapter_keys) or
            (key is not None and acquisition_multiplicity.get(key,0) > 1)
        )
        acquisition_provider=str(row.get('_source_id') or row.get('source_id') or
                                 default_acquisition_provider or '')
        chapter=(manifest.chapter(key) if manifest and key is not None and not ambiguous
                 else None)

        provider_title=str(row.get('title') or '').strip()
        if provider_title and not _placeholder_title(provider_title,key or ''):
            title=FieldEvidence(provider_title,acquisition_provider or 'provider','explicit',
                                str(row.get('id') or ''))
        elif chapter and chapter.title.present and not ambiguous:
            title=chapter.title
        else:
            title=FieldEvidence()

        provider_volume=normalize_publication_number(row.get('volume'))
        if provider_volume is not None:
            volume=FieldEvidence(provider_volume,acquisition_provider or 'provider','explicit',
                                 str(row.get('id') or ''))
            state='provider_explicit'
        elif chapter and chapter.volume.present and not ambiguous:
            volume=chapter.volume
            state=('reference_explicit' if chapter.volume.source == 'wikipedia'
                   else 'provider_explicit')
        else:
            volume=FieldEvidence()
            state='unmapped'
        base.append({
            'row':row,'key':key,'title':title,'volume':volume,'state':state,
            'selected_provider':str(selected_provider or ''),
            'acquisition_provider':acquisition_provider,'ambiguous':ambiguous,
        })

    volume_one_meaningful=bool(
        manifest and manifest.volume('1') or
        any(item['volume'].present and normalize_publication_number(item['volume'].value) == '1'
            for item in base)
    )
    for item in base:
        if (item['volume'].present or item['key'] is None or item['ambiguous'] or
                not volume_one_meaningful):
            continue
        try:
            number=Decimal(item['key'])
        except InvalidOperation:
            continue
        if Decimal('0') <= number < Decimal('1'):
            item['volume']=FieldEvidence('1','pre_chapter_one','derived','volume:1','derived')
            item['state']='derived_pre_chapter_one'

    by_key={item['key']:item for item in base
            if item['key'] is not None and not item['ambiguous']}
    for item in base:
        if item['volume'].present or item['key'] is None or item['ambiguous']:
            continue
        try:
            number=Decimal(item['key'])
        except InvalidOperation:
            continue
        parent_number=number.to_integral_value(rounding=ROUND_FLOOR)
        if number == parent_number:
            continue
        parent=by_key.get(format(parent_number,'f'))
        if not parent or not parent['volume'].present or parent['volume'].confidence == 'unknown':
            continue
        item['volume']=FieldEvidence(
            parent['volume'].value,'fractional_parent','derived',parent['key'],'derived'
        )
        item['state']='derived_fractional'

    chapters=[]
    for item in base:
        cover=None
        if manifest and item['volume'].present and not item['ambiguous']:
            manifest_volume=manifest.volume(item['volume'].value)
            cover=manifest_volume.cover if manifest_volume else None
        chapters.append(ProjectedChapter(
            item['row'],item['key'] or '',item['title'],item['volume'],cover,
            item['selected_provider'],item['acquisition_provider'],item['state'],
        ))
    return PublicationProjection(tuple(chapters),str(selected_provider or ''))


def project_inventory_through_manifest(provider_inventory, manifest, selected_provider='', default_acquisition_provider=''):
    """Compatibility boundary returning projected rows plus composition metrics."""
    projection=build_publication_projection(
        provider_inventory,manifest,selected_provider,default_acquisition_provider,
    )
    coverage=dict(projection.coverage)
    coverage['manifest_chapters']=len(manifest.chapters) if manifest else 0
    coverage['titles_applied']=sum(
        chapter.resolved_title.present and
        _placeholder_title(chapter.acquisition.get('title'),chapter.canonical_key)
        for chapter in projection.chapters
    )
    coverage['volume_assignments_applied']=sum(
        chapter.effective_volume.present and chapter.acquisition.get('volume') in (None,'')
        for chapter in projection.chapters
    )
    return projection.rows,coverage
