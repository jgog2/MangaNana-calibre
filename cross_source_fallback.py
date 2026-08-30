"""Conservative chapter-level planning across compatible manga providers.

This module deliberately knows nothing about Qt, Calibre, or page downloads.
It creates a provenance-preserving plan which callers can either execute (for
chapter jobs) or present as an incomplete/blocked volume plan.  Matching is
intentionally exact and never attempts fuzzy title matching.
"""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re

try:
    from .canonical_identity import normalize_identity_text
except ImportError:
    from canonical_identity import normalize_identity_text


_NUMBER_RE = re.compile(r"^\s*(?:(?:chapter|ch\.?)\s*)?(\d+(?:\.\d+)?)\s*$", re.I)


def _decimal(value):
    """Return a normalized decimal string, or ``None`` for non-numeric input."""
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError):
        return None
    if not number.is_finite() or number < 0:
        return None
    return format(number.normalize(), 'f')


def normalize_chapter_number(value):
    """Normalize only explicit numeric chapter labels (including decimals)."""
    if isinstance(value, (int, float, Decimal)):
        return _decimal(value)
    match = _NUMBER_RE.match(str(value or ''))
    return _decimal(match.group(1)) if match else None


@dataclass(frozen=True)
class CanonicalChapterIdentity:
    """Exact, conservative identity for a provider chapter record."""

    number: str
    volume: str = None
    title: str = ''

    @property
    def label(self):
        return f'Chapter {self.number}' if self.number is not None else 'Ambiguous chapter'


def chapter_identity(chapter):
    """Build an identity, leaving specials/bonuses deliberately ambiguous."""
    row = chapter or {}
    return CanonicalChapterIdentity(
        number=normalize_chapter_number(row.get('chapter')),
        volume=_decimal(row.get('volume')),
        title=normalize_identity_text(row.get('title')),
    )


def chapter_identities_match(first, second):
    """Return whether two identities are safe to treat as the same chapter.

    A chapter number is mandatory.  When both sources provide a volume or
    title, they must agree exactly after normalization.  Missing metadata does
    not manufacture a match, but also does not reject an otherwise exact
    numeric chapter identity.
    """
    if not first.number or not second.number or first.number != second.number:
        return False
    if first.volume and second.volume and first.volume != second.volume:
        return False
    if first.title and second.title and first.title != second.title:
        return False
    return True


@dataclass(frozen=True)
class PlannedChapter:
    """A selected provider chapter plus the reason for its provider choice."""

    source_id: str
    source_name: str
    reference: dict
    canonical_identity: CanonicalChapterIdentity
    reason: str = 'primary'
    output_eligible: bool = True


@dataclass(frozen=True)
class InventoryGap:
    """A primary-inventory absence and its safe fallback status."""

    canonical_identity: CanonicalChapterIdentity
    primary_source_id: str
    fallback_source_id: str = ''
    fallback_source_name: str = ''
    status: str = 'unresolved'
    reason: str = ''


@dataclass(frozen=True)
class CrossSourcePlan:
    """A deterministic per-chapter plan; it does not imply all items are runnable."""

    primary_source_id: str
    primary_source_name: str
    language: str
    edition: str
    items: tuple
    gaps: tuple
    workflow: str = 'chapter'
    primary_failure: str = ''

    @property
    def fallback_items(self):
        return tuple(item for item in self.items if item.reason != 'primary')

    @property
    def unresolved_gaps(self):
        return tuple(gap for gap in self.gaps if gap.status != 'filled')

    @property
    def can_execute(self):
        return bool(self.items) and not self.unresolved_gaps and all(
            item.output_eligible for item in self.items
        )

    @property
    def notice(self):
        count = len(self.fallback_items)
        if not count:
            return ''
        names = tuple(dict.fromkeys(item.source_name for item in self.fallback_items))
        suffix = ', '.join(names)
        return f'{count} missing chapter' + ('' if count == 1 else 's') + f' will be filled from {suffix}.'


def _result_reference(inventory):
    result = inventory.result or {}
    return result.get('url') or result.get('source_url') or result.get('id')


def _provider_chapters(inventory, registry):
    """Fetch one provider's normalized chapter records with safe provenance."""
    cached = tuple(getattr(inventory, 'chapter_records', ()) or ())
    if cached:
        return [(chapter_identity(row), dict(row)) for row in cached]
    source = registry.get(inventory.source_id)
    if source is None:
        raise RuntimeError(f'Unknown source: {inventory.source_id}')
    value = _result_reference(inventory)
    if not value:
        raise RuntimeError(f'{source.display_name} has no manga reference.')
    records = []
    for chapter in source.get_chapters(value, inventory.language) or ():
        row = dict(chapter)
        identity = chapter_identity(row)
        records.append((identity, row))
    return records


def _compatible(primary, candidate):
    return (candidate.source_id != primary.source_id and candidate.usable and
            candidate.language == primary.language and
            candidate.edition == primary.edition)


def build_cross_source_plan(inventories, registry, primary=None, workflow='chapter'):
    """Create a safe gap-fill plan for one already-canonical series.

    ``inventories`` must come from the same high-confidence canonical group.
    A secondary contributes only numeric chapters which are absent from the
    primary inventory.  Ambiguous specials are recorded as unresolved and are
    never used as fallbacks.  Mixed volume output remains disabled until the
    CBZ builder gains native per-chapter provider support.
    """
    rows = tuple(inventories or ())
    selected = primary or next((row for row in rows if row.usable), None)
    if selected is None:
        return CrossSourcePlan('', '', '', '', (), (), workflow)

    primary_error = selected.error if not selected.usable else ''
    try:
        primary_records = _provider_chapters(selected, registry) if selected.usable else []
    except Exception as exc:
        primary_records = []
        primary_error = str(exc)

    compatible = [row for row in rows if _compatible(selected, row)]
    secondaries = []
    for candidate in compatible:
        try:
            secondaries.append((candidate, _provider_chapters(candidate, registry)))
        except Exception:
            # The inventory result already retains the planning failure.  Do
            # not broaden matching or hide the primary plan because a helper
            # source is temporarily unavailable.
            continue

    items = []
    gaps = []
    primary_identities = [identity for identity, _row in primary_records]
    for identity, chapter in primary_records:
        items.append(PlannedChapter(selected.source_id, selected.source_name, chapter,
                                    identity, 'primary', True))

    # A primary planning failure may safely switch to an already compatible
    # source, but never to a different edition or language.
    if primary_error:
        for candidate, records in secondaries:
            if not records:
                continue
            for identity, chapter in records:
                if not identity.number:
                    gaps.append(InventoryGap(identity, selected.source_id, candidate.source_id,
                                              candidate.source_name, 'unresolved',
                                              'Ambiguous special/bonus chapters are never inferred.'))
                    continue
                eligible = workflow != 'volume'
                items.append(PlannedChapter(candidate.source_id, candidate.source_name, chapter,
                                            identity, 'primary-failure-fallback', eligible))
                if not eligible:
                    gaps.append(InventoryGap(identity, selected.source_id, candidate.source_id,
                                              candidate.source_name, 'unresolved',
                                              'Mixed-provider volume output is not supported yet.'))
            break
    else:
        for candidate, records in secondaries:
            for identity, chapter in records:
                if not identity.number:
                    continue
                if any(chapter_identities_match(identity, existing) for existing in primary_identities):
                    continue
                if any(identity.number == existing.number for existing in primary_identities):
                    gaps.append(InventoryGap(identity, selected.source_id, candidate.source_id,
                                              candidate.source_name, 'unresolved',
                                              'Conflicting chapter title or volume metadata.'))
                    continue
                # A numeric chapter only becomes a genuine gap if no earlier
                # compatible fallback already supplied that exact identity.
                if any(chapter_identities_match(identity, item.canonical_identity) for item in items):
                    continue
                eligible = workflow != 'volume'
                items.append(PlannedChapter(candidate.source_id, candidate.source_name, chapter,
                                            identity, 'missing-from-primary', eligible))
                gaps.append(InventoryGap(identity, selected.source_id, candidate.source_id,
                                          candidate.source_name,
                                          'filled' if eligible else 'unresolved',
                                          'Missing from primary inventory.' if eligible else
                                          'Mixed-provider volume output is not supported yet.'))

    # Numeric ordering makes the plan stable across provider feed order while
    # preserving primary precedence for equal identities.
    items.sort(key=lambda item: (
        Decimal(item.canonical_identity.number) if item.canonical_identity.number else Decimal('Infinity'),
        item.canonical_identity.volume or '', item.source_id, str(item.reference.get('id') or '')
    ))
    return CrossSourcePlan(selected.source_id, selected.source_name, selected.language,
                           selected.edition, tuple(items), tuple(gaps), workflow,
                           primary_error)
