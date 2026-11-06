"""Normalized publication snapshot and pure acquisition-inventory projection.

External sources contribute evidence to this Calibre/Qt-independent model.
Acquisition records remain separate and are projected through a manifest only
when a workflow needs publication titles, volume membership, or artwork.
"""

from dataclasses import asdict, dataclass, field, replace
from copy import deepcopy
from functools import wraps
from decimal import Decimal, InvalidOperation, ROUND_FLOOR
import re

from calibre_plugins.manganana.discovery.canonical_identity import normalize_identity_text, edition_identity
from calibre_plugins.manganana.providers.cross_source_fallback import normalize_chapter_number
from calibre_plugins.manganana.providers.atsu_acquisition import resolve_atsu_acquisition
from calibre_plugins.manganana.publication.publication_specials import (
    canonical_special_records,
    canonical_publication_records,
    match_special,
)
from calibre_plugins.manganana.publication.publication_freshness import (
    SPECIAL_KINDS,
    publication_date,
    volume_release_state,
    derive_publication_states,
    source_fingerprints,
    catalog_freshness,
)
from calibre_plugins.manganana.publication.publication_freshness import trusted_wikipedia_records
from calibre_plugins.manganana.publication.publication_identity import (
    AcquisitionIdentity,
    compile_bridge,
    qualify_structural_claims,
)


MANIFEST_SCHEMA_VERSION = 'publication-manifest-v2'


def structural_edition_family(value):
    """Approved same-work standard/color numbering policy used by references."""
    edition = str(value or '').casefold().replace('-', '_').replace(' ', '_')
    return 'standard' if edition in (
        'original', 'standard', 'b&w', 'bw', 'color', 'colored',
        'official_color', 'fan_color', 'fan_colored') else ''


def trusted_volume_numbers(manifest):
    """Artwork targets come from explicit structure, never catalog/art counts."""
    if manifest is None:
        return ()
    values = set()
    unreleased = set((manifest.runtime_publication.get('release_boundary') or {}).get('future_volumes') or ())
    forbidden = {'bookwalker', 'google_books', 'madb', 'anilist', 'kitsu', 'mangadex_artwork'}
    for chapter in manifest.chapters:
        evidence = chapter.volume
        if chapter.key in manifest.ambiguous_chapter_keys and evidence.source == 'wikipedia':
            continue
        if evidence.present and evidence.source not in forbidden and evidence.confidence in ('explicit','validated'):
            number = normalize_publication_number(evidence.value)
            if number is not None and number not in unreleased: values.add(number)
    for volume in manifest.volumes:
        if volume.provenance.source == 'wikipedia' and volume.provenance.present and volume.key not in unreleased:
            values.add(volume.key)
    return tuple(sorted(values, key=Decimal))


_PLACEHOLDER_TITLES = frozenset({'', 'fallback', 'unknown', 'none', 'null', 'n/a', 'untitled'})
_EXPLICIT_CHAPTER_RANGE = re.compile(r'^\s*(\d+)\s*[-\u2013\u2014]\s*(\d+)\s*$')
_MAX_EXPLICIT_CHAPTER_RANGE_SPAN = 200
_BOOKWALKER_RIMG_COVER = re.compile(r'^https://rimg\.bookwalker\.jp/([^/?#]+)/[^/?#]+(?:\?[^#]*)?$', re.I)


def _bookwalker_metadata_cover_url(value):
    """Choose the public metadata rendition of a known rimg thumbnail URL.

    Normalize cached references at manifest construction, without refetching the
    catalog or changing its cache contract. Unknown URL forms remain unchanged.
    """
    url=str(value or '').strip()
    match=_BOOKWALKER_RIMG_COVER.fullmatch(url)
    return f'https://c.bookwalker.jp/{match.group(1)}/t_700x780.jpg' if match else url


def normalize_publication_number(value):
    """Normalize only a finite non-negative explicit numeric volume label."""
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not number.is_finite() or number < 0:
        return None
    return format(number.normalize(), 'f')


def _explicit_chapter_range(value):
    """Expand only bounded, inclusive integer ranges from explicit records."""
    matched = _EXPLICIT_CHAPTER_RANGE.fullmatch(str(value or ''))
    if not matched:
        return ()
    start, end = (int(part) for part in matched.groups())
    if end < start or end - start > _MAX_EXPLICIT_CHAPTER_RANGE_SPAN:
        return ()
    return tuple(str(number) for number in range(start, end + 1))


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
    publication_context: dict = field(default_factory=dict)


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
    kind_evidence: FieldEvidence = field(default_factory=FieldEvidence)


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
    artwork_candidates: tuple = ()


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
    runtime_publication: dict = field(default_factory=dict)

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
    publication_state: str = ''
    resolved_kind: FieldEvidence = field(default_factory=FieldEvidence)
    publication_identity: object = None
    publication_reading_order: object = None

    @property
    def acquisition_identity(self):
        """Source namespace is separate from a reference's numeric chapter key."""
        return (self.acquisition_provider, str(self.acquisition.get('numbering_group') or ''),
                str(self.acquisition.get('numbering_ordinal') or self.acquisition.get('chapter') or ''),
                str(self.acquisition.get('id') or ''))

    def as_row(self):
        row=dict(self.acquisition)
        if self.publication_identity is not None:
            row['_publication_identity']=asdict(self.publication_identity)
            if self.effective_volume.present and self.publication_reading_order is not None:
                row['_publication_reading_order']=self.publication_reading_order
        if self.resolved_kind.present:
            row['type']=self.resolved_kind.value
            row['_type_source']=self.resolved_kind.source
            row['_type_confidence']=self.resolved_kind.confidence
            row['_type_source_identity']=self.resolved_kind.source_identity
            if self.canonical_key and normalize_chapter_number(row.get('chapter')) != self.canonical_key:
                row['_acquisition_chapter']=row.get('chapter')
                row['chapter']=self.canonical_key
        row['_selected_provider']=self.selected_provider
        row['_acquisition_provider']=self.acquisition_provider
        row['_projection_state']=self.mapping_state
        if self.publication_state:
            row['_publication_state']=self.publication_state
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
        resolved=sum(chapter.effective_volume.present for chapter in self.chapters)
        return {
            'provider_chapters':len(self.chapters),
            'chapters_matched':resolved,
            'resolved_chapters':resolved,
            'provider_explicit':states.count('provider_explicit'),
            'reference_explicit':states.count('reference_explicit'),
            'derived_fractional':states.count('derived_fractional'),
            'derived_pre_chapter_one':states.count('derived_pre_chapter_one'),
            'unmapped_provider_chapters':len(self.chapters)-resolved,
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


def _structural_evidence_change(method):
    @wraps(method)
    def changed(self, *args, **kwargs):
        self._validated_snapshot = None
        return method(self, *args, **kwargs)
    return changed


class PublicationManifestBuilder:
    """Build a candidate snapshot while retaining stronger last-known-good data."""

    def __init__(self, work, edition='unknown', existing=None, as_of=None):
        # One builder is owned by one resolution. Never a title/global cache.
        self._validated_snapshot = None
        self.as_of = publication_date(as_of).isoformat()
        self._references = {}
        self._curated_patch = {'status':'absent','fields':[]}
        self._curated_conflicts = []
        self._runtime = {}
        row = dict(work or {})
        canonical = str(row.get('canonical_identity') or '').strip()
        title = str(row.get('title') or '').strip()
        if not canonical:
            canonical = normalize_identity_text(title)
        same = bool(existing and existing.schema_version == MANIFEST_SCHEMA_VERSION and
                    existing.work.canonical_identity == canonical and
                    existing.edition.identity == str(edition or 'unknown'))
        if same:
            self._runtime = dict(existing.runtime_publication)
            self.work = replace(existing.work,publication_context=dict(
                row.get('publication_context') or existing.work.publication_context))
            self.edition = existing.edition
            self.chapters = {item.key: item for item in existing.chapters}
            self.volumes = {item.key: item for item in existing.volumes}
            self.descriptions = list(existing.display.descriptions)
            self.edition_artwork = existing.display.edition_artwork
            self.rating = existing.display.rating
            self.tags = list(existing.display.tags)
            self.source_states = {item.source: item for item in existing.source_states}
            self.ambiguous_chapter_keys = set(existing.ambiguous_chapter_keys) - set(
                existing.runtime_publication.get('unresolved_reference_chapters') or ())
            self._curated_patch = dict(status='matched', fields=[
                dict(entity='chapter',record_key=c.key,field=name,value=e.value,verification='VERIFIED')
                for c in existing.chapters for name,e in (('title',c.title),('volume',c.volume))
                if e.source=='curated_database' and e.confidence in ('verified','reviewed')])
            self._curated_patch['source_fingerprints']=existing.runtime_publication.get('source_fingerprints') or {}
        else:
            aliases = tuple(dict.fromkeys(str(value).strip() for value in row.get('aliases') or () if str(value or '').strip()))
            creator = str(row.get('creator') or '').strip()
            self.work = ManifestWork(canonical, title, aliases,
                                     FieldEvidence(creator, row.get('creator_source') or 'provider',
                                                   'explicit' if creator else 'unknown'),
                                     str(row.get('language') or ''), dict(row.get('publication_context') or {}))
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
        for name, old, incoming in (('title',current.title,title),('volume',current.volume,volume)):
            if (old.source=='curated_database' and incoming and incoming.present and
                    str(old.value)!=str(incoming.value)):
                conflict=dict(chapter=key,field=name,curated=old.value,live=incoming.value,source=incoming.source)
                if conflict not in self._curated_conflicts:
                    self._curated_conflicts.append(conflict)
        # Reviewed fields are anchors even when provider/reference refreshes run.
        if current.title.source == 'curated_database':
            title = None
        if current.volume.source == 'curated_database':
            volume = None
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

    @_structural_evidence_change
    def apply_curated(self, patch):
        """Overlay an already identity-validated runtime patch, never bound its range."""
        if patch.get('status')!='matched':
            return self
        identity=patch.get('identity') or {}
        if (not identity.get('trusted') or identity.get('canonical_work_id')!=self.work.canonical_identity or
                {'original':'standard'}.get(identity.get('edition'),identity.get('edition'))!=
                {'original':'standard'}.get(self.edition.identity,self.edition.identity) or
                identity.get('language')!=self.work.language):
            return self
        self._curated_patch=patch
        for entry in patch.get('fields') or ():
            if (entry.get('entity')!='chapter' or entry.get('field') not in ('volume','title') or
                    entry.get('verification') not in ('REVIEWED','VERIFIED')):
                continue
            key=normalize_chapter_number(entry.get('record_key'))
            if key is None:
                continue
            current=self.chapters.get(key) or ManifestChapter(key,key)
            name=entry['field']; old=getattr(current,name)
            if old.present and str(old.value)!=str(entry['value']):
                self._curated_conflicts.append(dict(chapter=key,field=name,curated=entry['value'],live=old.value,source=old.source))
            self.chapters[key]=replace(current,**{name:FieldEvidence(entry['value'],'curated_database',
                entry['verification'].lower(),str(patch.get('work_id') or ''))})
        self._rebuild_volume_membership()
        return self

    def add_description(self, value, source, confidence='trusted', language='', source_identity='', status='valid'):
        text = str(value or '').strip()
        if not text:
            return
        candidate = DescriptionCandidate(text, str(source or ''), confidence,
                                         str(language or ''), str(source_identity or ''), status)
        identity = (candidate.source, candidate.source_identity, candidate.language, candidate.value)
        if identity not in {(row.source, row.source_identity, row.language, row.value) for row in self.descriptions}:
            self.descriptions.append(candidate)

    @_structural_evidence_change
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

    @_structural_evidence_change
    def apply_mangadex_structure(self, value):
        row = dict(value or {})
        self._references['mangadex_structure'] = row
        self._set_state(ManifestSourceState('mangadex_structure', str(row.get('status') or 'unavailable'),
                                          str(row.get('manga_id') or ''), cache_state=str(row.get('cache_state') or '')))
        if (row.get('status') in ('invalid_structure', 'no_structure') and
                row.get('canonical_work_id') == self.work.canonical_identity and
                structural_edition_family(self.edition.identity) and
                structural_edition_family(row.get('edition_profile')) == structural_edition_family(self.edition.identity)):
            for key, chapter in tuple(self.chapters.items()):
                if chapter.volume.source == 'mangadex_structure':
                    self.chapters[key] = replace(chapter, volume=FieldEvidence())
            self._rebuild_volume_membership()
        if (row.get('status') != 'valid' or row.get('cache_contract') != 'mangadex-structure-v1' or
                row.get('canonical_work_id') != self.work.canonical_identity or
                not structural_edition_family(self.edition.identity) or
                structural_edition_family(row.get('edition_profile')) != structural_edition_family(self.edition.identity)):
            if row.get('status') == 'valid':
                self._set_state(ManifestSourceState('mangadex_structure', 'incompatible'))
            return self
        ambiguous = {normalize_chapter_number(k) for k in row.get('ambiguous_chapters') or ()}
        # A refreshed conflict must invalidate an accepted assignment.
        # Wikipedia is applied afterwards and can fill these gaps independently.
        for key, chapter in tuple(self.chapters.items()):
            if chapter.volume.source == 'mangadex_structure':
                self.chapters[key] = replace(chapter, volume=FieldEvidence())
        for number, value in dict(row.get('mappings') or {}).items():
            key = normalize_chapter_number(number)
            volume = normalize_publication_number(value)
            if key is None or volume is None or key in ambiguous:
                continue
            current = self.chapters.get(key)
            if current and current.volume.present and current.volume.source not in ('wikipedia','mangadex_structure','curated_database'):
                continue
            self._set_chapter(key, key, volume=FieldEvidence(volume, 'mangadex_structure', 'explicit', str(row.get('manga_id') or '')))
        self._rebuild_volume_membership()
        return self

    @_structural_evidence_change
    def apply_wikipedia(self, value):
        row = dict(value or {})
        self._runtime['unnumbered_publication_evidence']=deepcopy(row.get('unnumbered_evidence') or ())
        self._references['wikipedia'] = row
        future = {normalize_publication_number(v.get('number')) for v in row.get('volumes') or ()
                  if volume_release_state(v,self.as_of) in ('FUTURE','UPCOMING','PREORDER','ANNOUNCED')}
        # Future listings may carry planned contents; they cannot assign current chapters.
        row = dict(row,chapters=[dict(c,volume='') if normalize_publication_number(c.get('volume')) in future
                                else c for c in row.get('chapters') or ()])
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
        reference_memberships = {}
        expanded_ranges = []
        for original in rows:
            chapter = dict(original)
            kind = str(chapter.get('kind') or 'chapter')
            volume_key = normalize_publication_number(chapter.get('volume'))
            if volume_key is None:
                continue
            if kind == 'range':
                keys = _explicit_chapter_range(
                    chapter.get('number') or chapter.get('chapter')
                )
                if keys:
                    expanded_ranges.append((chapter, keys, volume_key))
            elif kind in ({'chapter', 'uncollected'} | SPECIAL_KINDS):
                key = normalize_chapter_number(
                    chapter.get('number') or chapter.get('chapter')
                )
                keys = (key,) if key is not None else ()
            else:
                keys = ()
            for key in keys:
                reference_memberships.setdefault(key, set()).add(volume_key)
        conflicting_memberships = {
            key for key, volumes in reference_memberships.items() if len(volumes) != 1
        }
        self.ambiguous_chapter_keys.update(conflicting_memberships)
        for original in rows:
            chapter = dict(original)
            key = normalize_chapter_number(chapter.get('number') or chapter.get('chapter'))
            if key is None or chapter.get('kind', 'chapter') not in ({'chapter', 'uncollected'} | SPECIAL_KINDS):
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
            if (key not in conflicting_memberships and volume_key is not None and
                    (current is None or not current.volume.present or
                     current.volume.source in ('wikipedia','curated_database'))):
                volume = FieldEvidence(volume_key, 'wikipedia',
                                       str(chapter.get('confidence') or 'explicit'),
                                       str(chapter.get('source_page') or ''))
            self._set_chapter(key, str(chapter.get('number') or key),
                              str(chapter.get('kind') or 'chapter'), title, volume)
        for chapter, keys, volume_key in expanded_ranges:
            evidence = FieldEvidence(
                volume_key, 'wikipedia', str(chapter.get('confidence') or 'explicit'),
                str(chapter.get('source_page') or ''),
            )
            for key in keys:
                if key in conflicting_memberships:
                    continue
                current = self.chapters.get(key)
                volume = (evidence if current is None or not current.volume.present or
                          current.volume.source == 'wikipedia' else None)
                self._set_chapter(key, key, 'chapter', volume=volume)
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

    def _apply_exact_artwork(self, artwork):
        if artwork.volume not in self._validated_volume_numbers():
            return
        ranks={'provider':0,'mangadex_artwork':1,'bookwalker':2,'google_books':3}
        current=self.volumes.get(artwork.volume)
        if current is None:
            return
        rank=lambda source:ranks.get(source,0)
        candidates=list(current.artwork_candidates or ((current.cover,) if current.cover else ()))
        candidates=[item for item in candidates if item.source != artwork.source]
        candidates.append(artwork)
        candidates.sort(key=lambda item:rank(item.source))
        self.volumes[artwork.volume]=replace(current,cover=candidates[0],artwork_candidates=tuple(candidates))

    def apply_provider_covers(self, covers, source='provider'):
        for number,url in dict(covers or {}).items():
            key=normalize_publication_number(number)
            if key is not None and url:
                self._apply_exact_artwork(ManifestArtwork(str(url),source,'exact_volume','exact',volume=key))
        return self

    def apply_mangadex_artwork(self, value):
        row=dict(value or {})
        if (row.get('cache_contract') != 'mangadex-artwork-v1' or row.get('status') != 'valid' or
                row.get('canonical_work_id') != self.work.canonical_identity or
                not structural_edition_family(self.edition.identity) or
                row.get('edition') != edition_identity({'edition':self.edition.identity})):
            return self
        for cover in row.get('covers') or ():
            key=normalize_publication_number(cover.get('volume'))
            if key is not None and cover.get('url') and cover.get('confidence') == 'exact':
                self._apply_exact_artwork(ManifestArtwork(
                    cover['url'],'mangadex_artwork','exact_volume','exact',row.get('manga_id',''),
                    row.get('edition',''),cover.get('cover_id',''),key,
                    preview_url=cover.get('preview_url',''),source_url=cover['url']))
        return self

    @_structural_evidence_change
    def apply_bookwalker(self, value):
        row = dict(value or {})
        self._references['bookwalker'] = row
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
            raw_cover_url=str(cover['url'])
            metadata_cover_url=_bookwalker_metadata_cover_url(raw_cover_url)
            artwork = ManifestArtwork(
                metadata_cover_url, 'bookwalker', 'exact_volume', 'exact', publication_id,
                edition_id, str(cover.get('volume_id') or ''), volume_key,
                preview_url=raw_cover_url, source_url=metadata_cover_url,
            )
            self._apply_exact_artwork(artwork)
            if volume_key in self._validated_volume_numbers():
                # Preserve compatible catalog identity on an existing structural
                # volume even when higher-priority artwork remains selected.
                self.volumes[volume_key]=replace(self.volumes[volume_key],publication_identity=publication_id)
        edition_art = next((dict(item) for item in row.get('edition_artwork') or ()
                            if item.get('artwork_type') == 'edition' and item.get('url') and
                            str(item.get('edition_id') or '') == edition_id), None)
        if edition_art:
            raw_cover_url=str(edition_art['url'])
            metadata_cover_url=_bookwalker_metadata_cover_url(raw_cover_url)
            self.edition_artwork = ManifestArtwork(
                metadata_cover_url, 'bookwalker', 'edition',
                str(edition_art.get('confidence') or 'exact'), publication_id, edition_id,
                str(edition_art.get('volume_id') or ''),
                preview_url=raw_cover_url, source_url=metadata_cover_url,
            )
        self.add_description(row.get('description'), 'bookwalker', 'trusted',
                             str(row.get('description_language') or ''), publication_id)
        return self

    @_structural_evidence_change
    def apply_madb(self, value):
        """Record publication-reference provenance without asserting edition equivalence.

        The detailed Japanese book inventory lives in the reference bundle/cache.
        A canonical work and 'standard' profile alone do not prove that provider
        volume N is this Japanese ISBN. Never modify chapter membership, existing
        volume identities, artwork, canonical metadata, or acquisition provenance.
        """
        row = dict(value or {})
        match = dict(row.get('match') or {})
        status = str(row.get('status') or 'unresolved')
        valid = status == 'valid' and match.get('confidence') == 'confident'
        self._set_state(ManifestSourceState(
            'madb', 'valid_stale' if valid and row.get('cache_state') == 'last_known_good' else status,
            str(match.get('series_id') or '') if valid else '',
            contract=str(row.get('cache_contract') or ''), cache_state=str(row.get('cache_state') or '')))
        return self

    @_structural_evidence_change
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
            if (current is None or
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
            self._apply_exact_artwork(artwork)
        return self

    @_structural_evidence_change
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

    def _reference_memberships(self):
        """Compare current independently eligible claims, never source rank."""
        claims = {key: [dict(r) for r in rows if r['source'] not in self._references]
                  for key, rows in (self._runtime.get('reference_claims') or {}).items()}
        claims = {key: rows for key, rows in claims.items() if rows}
        md = self._references.get('mangadex_structure') or {}
        if (md.get('status') == 'valid' and md.get('cache_contract') == 'mangadex-structure-v1'
                and md.get('canonical_work_id') == self.work.canonical_identity
                and structural_edition_family(self.edition.identity)
                and structural_edition_family(md.get('edition_profile')) == structural_edition_family(self.edition.identity)
                and md.get('cache_state') != 'last_known_good' and not md.get('refresh_status')):
            ambiguous = {normalize_chapter_number(k) for k in md.get('ambiguous_chapters') or ()}
            for key, volume in (md.get('mappings') or {}).items():
                key = normalize_chapter_number(key)
                volume = normalize_publication_number(volume)
                if key is not None and volume is not None and key not in ambiguous:
                    claims.setdefault(key, []).append(dict(source='mangadex_structure', volume=volume,
                        confidence='explicit', source_record_id=md.get('manga_id') or '',
                        source_page='https://mangadex.org/title/'+str(md.get('manga_id') or '')))
        identity = dict(trusted=bool(self.work.publication_context.get('shareable') and
            self.work.publication_context.get('canonical_work_id') == self.work.canonical_identity),
            canonical_work_id=self.work.canonical_identity, edition=self.edition.identity, language=self.work.language)
        wiki = self._references.get('wikipedia') or {}
        # Apply the same future-content filtering as ordinary manifest fills.
        future = {normalize_publication_number(v.get('number')) for v in wiki.get('volumes') or ()
                  if volume_release_state(v, self.as_of) in ('FUTURE','UPCOMING','PREORDER','ANNOUNCED')}
        memberships = {}
        expanded = []
        for row in wiki.get('chapters') or ():
            if row.get('kind') == 'range':
                expanded.extend(dict(row, number=k, kind='chapter') for k in
                                _explicit_chapter_range(row.get('number') or row.get('chapter')))
            else:
                expanded.append(row)
        eligible = trusted_wikipedia_records(dict(wikipedia=dict(wiki, chapters=expanded)),
                                            identity, self.work.publication_context)
        for row in eligible:
            volume = normalize_publication_number(row.get('volume'))
            if volume is None or volume in future or row.get('kind') not in ({'chapter','uncollected'} | SPECIAL_KINDS):
                continue
            memberships.setdefault(row['key'], []).append(dict(row, source='wikipedia', volume=volume))
        for key, rows in memberships.items():
            if len({r['volume'] for r in rows}) == 1:
                claims.setdefault(key, []).extend(rows)
        conflicts = [dict(chapter=key, claims=rows) for key, rows in sorted(claims.items(), key=lambda v:Decimal(v[0]))
                     if len({r['volume'] for r in rows}) > 1]
        # Legacy conflict snapshots without stored claims remain fail-closed
        # until both sources are reevaluated. Updated sources replace their old
        # claims; an independent eligible remaining source can fill a rejection.
        if not {'mangadex_structure','wikipedia'} <= self._references.keys():
            present = {r['chapter'] for r in conflicts}
            conflicts.extend(dict(r) for r in self._runtime.get('reference_conflicts') or ()
                             if r['chapter'] not in present and r['chapter'] not in claims)
        return claims, conflicts

    def _validated_manifest(self):
        if self._validated_snapshot is None:
            self._validated_snapshot = self._build_structure()
            self._validated_targets = frozenset(trusted_volume_numbers(self._validated_snapshot))
        return self._validated_snapshot

    def _validated_volume_numbers(self):
        self._validated_manifest()
        return self._validated_targets

    def build(self, preferred_language=''):
        structure = self._validated_manifest()
        # Artwork never changes the validated membership universe. Preserve its
        # reconciled chapter_keys while attaching the current ordered candidates.
        volumes = tuple(replace(v, cover=self.volumes[v.key].cover,
            artwork_candidates=self.volumes[v.key].artwork_candidates,
            publication_identity=self.volumes[v.key].publication_identity)
            for v in structure.volumes)
        return replace(structure, volumes=volumes,
            display=ManifestDisplay(tuple(self.descriptions),
                resolve_description(self.descriptions,preferred_language),
                self.edition_artwork,self.rating,tuple(self.tags)),
            source_states=tuple(self.source_states.values()),
            runtime_publication=deepcopy(structure.runtime_publication))

    def _build_structure(self, preferred_language=''):
        special_records=canonical_special_records(self._references,self.work.canonical_identity,
            self.edition.identity,self.work.language,self.work.publication_context)
        for proof in special_records:
            current=self.chapters.get(proof['key']) or ManifestChapter(proof['key'],proof['key'])
            title=current.title
            if proof.get('title') and not title.present:
                title=FieldEvidence(proof['title'],proof['source'],proof['confidence'],proof['source_record_id'])
            self.chapters[proof['key']]=replace(current,title=title,kind=proof['kind'],kind_evidence=FieldEvidence(
                proof['kind'],proof['source'],proof['confidence'],proof['source_record_id']))
        display = ManifestDisplay(
            tuple(self.descriptions), resolve_description(self.descriptions, preferred_language),
            self.edition_artwork, self.rating, tuple(self.tags),
        )
        claims, conflicts = self._reference_memberships()
        chapters = dict(self.chapters)
        for key, rows in claims.items():
            chapter = chapters.get(key)
            if (chapter and chapter.volume.source in ('mangadex_structure','wikipedia') and
                    chapter.volume.source not in {r['source'] for r in rows} and
                    len({r['volume'] for r in rows}) == 1):
                claim = rows[0]
                chapters[key] = replace(chapter, volume=FieldEvidence(claim['volume'], claim['source'],
                    claim['confidence'], claim.get('source_record_id') or ''))
        ambiguous = set(self.ambiguous_chapter_keys)
        md = self._references.get('mangadex_structure') or {}
        if (md.get('canonical_work_id') == self.work.canonical_identity and
                structural_edition_family(md.get('edition_profile')) == structural_edition_family(self.edition.identity)):
            for key in md.get('ambiguous_chapters') or ():
                key = normalize_chapter_number(key)
                if key is not None and not (chapters.get(key) and chapters[key].volume.present):
                    ambiguous.add(key)
        unresolved = []
        for conflict in conflicts:
            key = conflict['chapter']
            chapter = chapters.get(key)
            evidence = chapter.volume if chapter else FieldEvidence()
            curated = evidence.source == 'curated_database' and evidence.confidence in ('reviewed','verified')
            provider = evidence.present and evidence.source not in ('','mangadex_structure','wikipedia','curated_database')
            conflict['resolved_by'] = evidence.source if curated or provider else ''
            if not (curated or provider):
                unresolved.append(key)
                ambiguous.add(key)
                if chapter: chapters[key] = replace(chapter, volume=FieldEvidence())
        # Membership groups reflect the reconciled copy; builder/source snapshots
        # stay intact, so repeated build and later curation are deterministic.
        # Index the reconciled copy once. Preserve insertion order and the exact
        # normalized-volume comparison used by the former per-volume scan.
        # No claims, conflict resolution, or publication identities change here.
        chapter_keys_by_volume = {}
        for chapter in chapters.values():
            if chapter.volume.present:
                key = normalize_publication_number(chapter.volume.value)
                chapter_keys_by_volume.setdefault(key, []).append(chapter.key)
        volumes = tuple(replace(v, chapter_keys=tuple(chapter_keys_by_volume.get(v.key, ())))
                        for v in sorted(self.volumes.values(), key=lambda row:Decimal(row.key)))
        manifest = PublicationManifest(
            MANIFEST_SCHEMA_VERSION, self.work, self.edition,
            tuple(sorted(chapters.values(), key=lambda row: Decimal(row.key))),
            volumes,
            display, tuple(self.source_states.values()),
            tuple(sorted(ambiguous, key=Decimal)),
        )
        if not self._references:
            return replace(manifest,runtime_publication=dict(self._runtime,
                reference_conflicts=conflicts, unresolved_reference_chapters=sorted(unresolved,key=Decimal)))
        rows = [dict(chapter=c.key,_effective_volume=c.volume.value if c.volume.present else '',
                     _volume_source=c.volume.source,title=c.title.value,_title_source=c.title.source)
                for c in manifest.chapters]
        explicit_main = {str(c.get('number')) for c in (self._references.get('wikipedia') or {}).get('chapters') or ()
                         if c.get('kind') in ('chapter','uncollected')}
        labels = ['main' if Decimal(c.key)==Decimal(c.key).to_integral_value() or c.key in explicit_main
                  else 'excluded' for c in manifest.chapters]
        context = self.work.publication_context
        trusted = bool(context.get('shareable') and context.get('canonical_work_id')==self.work.canonical_identity)
        publication = dict(projection=rows,normalization=dict(labels=labels),manifest=asdict(manifest),
            references=self._references,as_of=self.as_of,
            catalog_identity=dict(trusted=trusted,canonical_work_id=self.work.canonical_identity,
                                  edition=self.edition.identity,language=self.work.language),
            context=dict(context,shareable=trusted))
        derive_publication_states(publication)
        publication['source_fingerprints']=source_fingerprints(self._references)
        runtime = {key:publication[key] for key in ('as_of','release_boundary','uncompiled_evidence',
                    'uncompiled_identifiers','source_fingerprints')}
        if self._runtime.get('unnumbered_publication_evidence'):
            runtime['unnumbered_publication_evidence']=deepcopy(self._runtime['unnumbered_publication_evidence'])
        runtime['catalog_freshness']=catalog_freshness(self._curated_patch,publication)
        runtime['special_records']=special_records
        runtime['publication_records']=canonical_publication_records(self._references,
            self.work.canonical_identity,self.edition.identity,self.work.language,self.work.publication_context)
        runtime.update(reference_claims=claims, reference_conflicts=conflicts,
                       unresolved_reference_chapters=sorted(unresolved,key=Decimal))
        if self._curated_conflicts:
            runtime['catalog_freshness'].update(state='CONFLICT_REVIEW',blocking=True,
                                               conflicts=list(self._curated_conflicts))
        return replace(manifest,runtime_publication=runtime)


def build_publication_projection(provider_inventory, manifest, selected_provider='', default_acquisition_provider='',
                                 identity_bridge=None, acquisition_context=None):
    """Resolve publication evidence onto downloadable rows without mutating either."""
    rows=tuple(resolve_atsu_acquisition(provider_inventory,manifest)['rows'])
    runtime=manifest.runtime_publication if manifest else {}
    artifact=identity_bridge if identity_bridge is not None else runtime.get('identity_bridge')
    context=acquisition_context or runtime.get('identity_acquisition_context') or {}
    index=compile_bridge(artifact) if artifact else None
    if index and (not manifest or not index.compatible(manifest.work.canonical_identity,manifest.edition.identity,
                                     context.get('language',''))):
        index=None
    associations=[]; publication_multiplicity={}
    for row in rows:
        aid=AcquisitionIdentity.from_row(row,default_acquisition_provider,
                                        context.get('source_work',''),context.get('language',''))
        target=index.resolve(aid) if index else None
        associations.append(target)
        if target:
            publication_multiplicity[target.identity]=publication_multiplicity.get(target.identity,0)+1
    _,typed_conflicts=qualify_structural_claims(runtime.get('identity_reference_claims') or (),index)
    acquisition_multiplicity={}
    for row in rows:
        key=normalize_chapter_number(row.get('chapter'))
        if key is not None:
            acquisition_multiplicity[key]=acquisition_multiplicity.get(key,0)+1
    base=[]
    for row,target in zip(rows,associations):
        key=normalize_chapter_number(row.get('chapter'))
        acquisition_provider=str(row.get('_source_id') or row.get('source_id') or
                                 default_acquisition_provider or '')
        proof=match_special(row,manifest.runtime_publication.get('special_records',()) if manifest else (),
                            acquisition_provider)
        if proof:key=proof['key']
        trusted_chapter = manifest.chapter(key) if manifest and key is not None else None
        authority = bool(normalize_publication_number(row.get('volume')) is not None or (
            trusted_chapter and trusted_chapter.volume.source == 'curated_database'
            and trusted_chapter.volume.confidence in ('reviewed','verified')))
        reference_conflict = bool(manifest and key in (
            manifest.runtime_publication.get('unresolved_reference_chapters') or ()) and not authority)
        ambiguous=bool(
            reference_conflict or
            (manifest and key in manifest.ambiguous_chapter_keys and not (
                trusted_chapter and trusted_chapter.volume.source == 'mangadex_structure')) or
            (key is not None and acquisition_multiplicity.get(key,0) > 1)
        )
        if target:
            # Association precedes multiplicity. A verified identity never shares
            # the legacy numeric bucket; two releases of that identity still do.
            ambiguous=(publication_multiplicity[target.identity]>1 or target.identity in typed_conflicts)
        acquisition_provider=str(row.get('_source_id') or row.get('source_id') or
                                 default_acquisition_provider or '')
        chapter=(manifest.chapter(key) if manifest and key is not None and not ambiguous and not target
                 else None)

        provider_title=str(row.get('title') or '').strip()
        if chapter and chapter.title.source=='curated_database' and chapter.title.confidence in ('verified','reviewed'):
            title=chapter.title
        elif provider_title and not _placeholder_title(provider_title,key or ''):
            title=FieldEvidence(provider_title,acquisition_provider or 'provider','explicit',
                                str(row.get('id') or ''))
        elif chapter and chapter.title.present and not ambiguous:
            title=chapter.title
        else:
            title=FieldEvidence()

        provider_volume=normalize_publication_number(row.get('volume'))
        if chapter and chapter.volume.source=='curated_database' and chapter.volume.confidence in ('verified','reviewed'):
            volume=chapter.volume
            state='curated' if volume.present else 'unmapped'
        elif provider_volume is not None:
            volume=FieldEvidence(provider_volume,acquisition_provider or 'provider','explicit',
                                 str(row.get('id') or ''))
            state='provider_explicit'
        elif chapter and chapter.volume.present and not ambiguous:
            volume=chapter.volume
            state=('reference_explicit' if chapter.volume.source in ('wikipedia','mangadex_structure')
                   else 'provider_explicit')
        else:
            volume=FieldEvidence()
            state='unmapped'
        if target and provider_volume is None:
            volume=(FieldEvidence(target.volume,'publication_identity_bridge','reviewed',index.digest)
                    if not ambiguous else FieldEvidence())
            state='identity_bridge' if volume.present else 'identity_bridge_conflict'
            if volume.present and target.title:
                title=FieldEvidence(target.title,'publication_identity_bridge','reviewed',index.digest)
        if target:
            # Never derive a fractional/legacy membership for a failed bridge.
            key=None
        base.append({
            'row':row,'key':key,'title':title,'volume':volume,'state':state,
            'kind':(FieldEvidence(proof['kind'],proof['source'],proof['confidence'],proof['source_record_id'])
                    if proof else FieldEvidence()),
            'selected_provider':str(selected_provider or ''),
            'acquisition_provider':acquisition_provider,'ambiguous':ambiguous,
            'publication_identity':target.identity if target else None,
            'publication_reading_order':(target.reading_order if target and volume.present
                and normalize_publication_number(volume.value)==target.volume else None),
        })

    volume_one_meaningful=bool(
        manifest and manifest.volume('1') or
        any(item['volume'].present and normalize_publication_number(item['volume'].value) == '1'
            for item in base)
    )
    for item in base:
        if (item['volume'].present or item['key'] is None or item['ambiguous'] or
                not volume_one_meaningful or item['kind'].present):
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
        if item['volume'].present or item['key'] is None or item['ambiguous'] or item['kind'].present:
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
            ('MAPPED' if item['volume'].present else 'UNCOMPILED' if manifest and
             item['key'] in manifest.runtime_publication.get('uncompiled_identifiers',()) and
             not item['ambiguous'] else 'UNMAPPED'),
            item['kind'],
            item['publication_identity'],
            item['publication_reading_order'],
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
