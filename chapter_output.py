"""Pure Chapter-mode output planning with conservative volume evidence."""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum

try:
    from .chapter_workflow import chapter_sort_key
    from .cross_source_fallback import chapter_identity, normalize_chapter_number
except ImportError:
    from chapter_workflow import chapter_sort_key
    from cross_source_fallback import chapter_identity, normalize_chapter_number


class ChapterOutputMode(str, Enum):
    DETECTED_VOLUMES = 'detected_volumes'
    MANUAL_VOLUMES = 'manual_volumes'
    INDIVIDUAL_CHAPTERS = 'individual_chapters'


@dataclass(frozen=True)
class VolumeEvidenceSource:
    source_id: str
    work_id: str
    edition: str
    chapters: tuple


@dataclass(frozen=True)
class VolumeEvidenceResolution:
    available: bool
    assignments: tuple = ()
    provenance: tuple = ()
    reason: str = ''

    @property
    def assignment_map(self):
        return dict(self.assignments)


@dataclass(frozen=True)
class ChapterOutputGroup:
    kind: str
    identifier: str
    chapters: tuple
    mode: ChapterOutputMode

    @property
    def volume(self):
        if self.kind != 'volume':
            return None
        try:
            return float(Decimal(self.identifier))
        except (InvalidOperation, ValueError, TypeError):
            return None

    @property
    def page_sources(self):
        return tuple(dict.fromkeys(
            str(chapter.get('_source_id') or '') for chapter in self.chapters
            if str(chapter.get('_source_id') or '')
        ))

    def to_record(self):
        return {
            'kind': self.kind,
            'identifier': self.identifier,
            'volume': self.volume,
            'mode': self.mode.value,
            'chapters': [dict(chapter) for chapter in self.chapters],
            'page_sources': list(self.page_sources),
        }


def normalize_volume_identifier(value):
    """Normalize the numeric volume conventions already used by MangaNana."""
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError):
        return None
    if not number.is_finite() or number < 0:
        return None
    return format(number.normalize(), 'f')


def _chapter_match(selected, evidence):
    wanted = chapter_identity(selected)
    offered = chapter_identity(evidence)
    if not wanted.number or not offered.number or wanted.number != offered.number:
        return False
    # A conflicting explicit title makes a same-number match ambiguous. Missing
    # titles remain compatible because many provider inventories omit them.
    return not (wanted.title and offered.title and wanted.title != offered.title)


def resolve_volume_evidence(selected_chapters, evidence_sources=(), *,
                            page_source_id='', page_work_id='', page_edition='original'):
    """Resolve all-or-nothing explicit chapter-to-volume evidence.

    Totals, averages, neighbouring chapters, and title-number heuristics are
    intentionally absent. A secondary provider is considered only when the
    caller supplies the same trusted canonical-work token and edition.
    """
    selected = tuple(sorted((dict(row) for row in selected_chapters or ()), key=chapter_sort_key))
    if not selected:
        return VolumeEvidenceResolution(False, reason='No chapters are selected.')

    sources = tuple(
        value if isinstance(value, VolumeEvidenceSource) else VolumeEvidenceSource(
            str((value or {}).get('source_id') or ''),
            str((value or {}).get('work_id') or ''),
            str((value or {}).get('edition') or 'original'),
            tuple(dict(row) for row in (value or {}).get('chapters') or ()),
        )
        for value in evidence_sources or ()
    )
    assignments = []
    provenance = []
    for chapter in selected:
        chapter_id = str(chapter.get('id') or '')
        number = normalize_chapter_number(chapter.get('chapter'))
        if not chapter_id or number is None:
            return VolumeEvidenceResolution(False, reason='A selected chapter has ambiguous identity.')

        candidates = []
        own_volume = normalize_volume_identifier(chapter.get('volume'))
        if own_volume is not None:
            candidates.append((own_volume, str(chapter.get('_source_id') or page_source_id or 'selected-provider')))

        for source in sources:
            same_provider = bool(source.source_id and source.source_id == str(chapter.get('_source_id') or page_source_id))
            if source.edition != page_edition:
                continue
            if not same_provider:
                if not page_work_id or source.work_id != page_work_id:
                    continue
            matches = [row for row in source.chapters if _chapter_match(chapter, row)]
            # Multiple explicit rows for a number are safe only when they agree.
            for row in matches:
                volume = normalize_volume_identifier(row.get('volume'))
                if volume is not None:
                    candidates.append((volume, source.source_id or 'provider'))

        volumes = {volume for volume, _source_id in candidates}
        if not volumes:
            return VolumeEvidenceResolution(False, reason=f'Chapter {number} has no explicit volume assignment.')
        if len(volumes) != 1:
            return VolumeEvidenceResolution(False, reason=f'Chapter {number} has conflicting explicit volume assignments.')
        volume = next(iter(volumes))
        assignments.append((chapter_id, volume))
        provenance.extend(source_id for candidate_volume, source_id in candidates if candidate_volume == volume)

    return VolumeEvidenceResolution(
        True, tuple(assignments), tuple(dict.fromkeys(provenance)),
        'Every selected chapter has one compatible explicit volume assignment.',
    )


def validate_manual_assignments(selected_chapters, assignments):
    selected_ids = tuple(str(row.get('id') or '') for row in selected_chapters or ())
    if not selected_ids or any(not value for value in selected_ids):
        return False
    normalized = {
        str(chapter_id): normalize_volume_identifier(volume)
        for chapter_id, volume in dict(assignments or {}).items()
    }
    return all(normalized.get(chapter_id) is not None for chapter_id in selected_ids)


def plan_chapter_outputs(selected_chapters, mode, *, evidence=None, manual_assignments=None):
    """Transform selected chapters into explicit downloader-ready groups."""
    mode = mode if isinstance(mode, ChapterOutputMode) else ChapterOutputMode(str(mode))
    selected = tuple(sorted((dict(row) for row in selected_chapters or ()), key=chapter_sort_key))
    if mode is ChapterOutputMode.INDIVIDUAL_CHAPTERS:
        return tuple(
            ChapterOutputGroup('chapter', str(row.get('chapter') or ''), (row,), mode)
            for row in selected
        )

    if mode is ChapterOutputMode.DETECTED_VOLUMES:
        if not evidence or not evidence.available:
            raise ValueError('Complete trustworthy volume data is unavailable for this selection.')
        assignments = evidence.assignment_map
    else:
        if not validate_manual_assignments(selected, manual_assignments):
            raise ValueError('Assign every selected chapter to a valid volume before continuing.')
        assignments = {
            str(key): normalize_volume_identifier(value)
            for key, value in dict(manual_assignments or {}).items()
        }

    grouped = {}
    for chapter in selected:
        chapter_id = str(chapter.get('id') or '')
        volume = assignments.get(chapter_id)
        if volume is None:
            raise ValueError('The output plan would discard an unassigned chapter.')
        grouped.setdefault(volume, []).append(chapter)
    return tuple(
        ChapterOutputGroup('volume', volume, tuple(sorted(rows, key=chapter_sort_key)), mode)
        for volume, rows in sorted(grouped.items(), key=lambda item: Decimal(item[0]))
    )

