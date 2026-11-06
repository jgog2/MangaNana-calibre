"""Presentation facts about a loaded listing, never a claim of a complete work.

No requests, projection, identity inference or changes to acquisition records.
Reference chapter membership can identify volume groups to review; it cannot
establish an exhaustive edition catalog or prove a provider lacks a chapter.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


def volume_key(value):
    try:
        number = Decimal(str(value))
        if number.is_finite() and number >= 0:
            return format(number.normalize(), 'f')
    except (InvalidOperation, ValueError):
        pass
    return None


def entry_text(count, packaged=False):
    noun = 'volume file' if packaged else 'chapter entry'
    return f'{count:,} ' + (noun if count == 1 else 'volume files' if packaged else 'chapter entries')


def chapter_range_text(rows):
    """Summarize actual numeric bounds, retaining separate numbering namespaces."""
    import re
    labels = []
    for row in rows or ():
        if row.get('_unit_kind') == 'volume':
            return ''  # A packaged volume does not expose its chapter contents.
        token = (row.get('_publication_identity') or {}).get('episode_token')
        if token is None:
            token = next((row.get(key) for key in ('chapter', 'number', 'label')
                          if row.get(key) is not None), None)
        if token is None or not str(token).strip():
            return ''
        labels.append(str(token).strip())
    groups = {}
    extras = []
    for token in dict.fromkeys(labels):
        match = re.fullmatch(r'(.*?)([0-9]+(?:\.[0-9]+)?)', token)
        if not match:
            extras.append(token)
            continue
        prefix, digits = match.groups()
        groups.setdefault(prefix, {})[Decimal(digits)] = token
    parts = []
    # Named/pre-serial chapter sequences remain separate from regular numbers.
    for prefix in sorted(groups, key=lambda value: (not bool(value), value)):
        values = groups[prefix]
        numbers = sorted(values)
        start, end = values[numbers[0]], values[numbers[-1]]
        parts.append('Ch '+start+(' - Ch '+end if len(numbers)>1 else ''))
    parts.extend('Ch '+token for token in extras)
    return '('+'; '.join(parts)+')' if parts else ''


@dataclass(frozen=True)
class InventoryCoverage:
    state: str
    provider: str
    language: str
    source_entries: int = 0
    other_entries: int = 0
    packaged: bool = False
    mixed_units: bool = False
    groups: tuple = ()  # (volume label, actual entry count)
    ungrouped: tuple = ()  # actual retained rows, not inferred missing chapters
    reference_volumes: tuple = ()
    reference_gaps: tuple = ()
    warnings: tuple = ()

    @property
    def summary(self):
        if self.state == 'loading':
            return f'Checking the listing from {self.provider} · {self.language}'
        if self.state == 'error':
            return f'The listing from {self.provider} could not be loaded · {self.language}'
        count = f'{self.source_entries:,} source entries' if self.mixed_units else entry_text(self.source_entries, self.packaged)
        text = f'{count} from {self.provider} · {self.language}'
        if self.other_entries:
            text += f' · {self.other_entries:,} entries from other sources'
        return text

    @property
    def status(self):
        if self.state == 'loading':
            return 'Full-work coverage cannot be assessed while the listing is loading.'
        if self.state == 'error':
            return 'Coverage unknown. A loading failure does not mean the provider has no chapters.'
        if self.state == 'empty':
            return 'No downloadable entries found. Full-work coverage unverified.'
        groups = f'{len(self.groups):,} volume ' + ('group' if len(self.groups) == 1 else 'groups')
        outside = f' · {len(self.ungrouped):,} entries not grouped into volumes' if self.ungrouped else ''
        gaps = ' Reference gaps to review.' if self.reference_gaps else ''
        warning = ' Listing warnings to review.' if self.warnings else ''
        return groups + outside + '. Full-work coverage unverified.' + gaps + warning


def describe_inventory(*, state, provider_id, provider_name, language, rows=(), plan=None, manifest=None):
    """Use exact downloaded inventory inputs; never infer counts from numbering."""
    if state not in ('ready', 'empty'):
        return InventoryCoverage(state, provider_name, language)
    plan = plan or {}
    raw = tuple(rows or ()) if state == 'ready' else ()
    grouped = tuple(plan.get('volume_groups') or ()) if state == 'ready' else ()
    # A prepared plan can include explicitly approved alternate acquisitions.
    # Its actual rows are authoritative for the displayed volume groups.
    entries = tuple(row for group in grouped for row in group.get('chapters') or ()) if grouped else raw
    by_volume = {}
    ungrouped = []
    if grouped:
        for group in grouped:
            key = volume_key(group.get('volume')) if group.get('kind') == 'volume' else None
            if key is None:
                ungrouped.extend(group.get('chapters') or ())
            else:
                by_volume[key] = by_volume.get(key, 0) + len(group.get('chapters') or ())
    else:
        for row in entries:
            key = volume_key(row.get('_effective_volume', row.get('volume')))
            if key is None:
                ungrouped.append(row)
            else:
                by_volume[key] = by_volume.get(key, 0) + 1
    source_count = sum(str(row.get('_source_id') or row.get('source_id') or provider_id) == provider_id for row in entries)
    packaged = bool(entries) and all(row.get('_unit_kind') == 'volume' for row in entries)
    mixed_units = not packaged and any(row.get('_unit_kind') == 'volume' for row in entries)
    references = set()
    ambiguous = set(getattr(manifest, 'ambiguous_chapter_keys', ()) or ())
    for chapter in getattr(manifest, 'chapters', ()) or ():
        field = chapter.volume
        # Cover catalogs, publication status, numeric ranges and provider
        # aggregates are not an exhaustive chapter-membership reference.
        if (chapter.key not in ambiguous and field.present and field.status == 'valid'
                and field.source in ('wikipedia', 'mangadex_structure', 'curated_database')):
            key = volume_key(field.value)
            if key is not None:
                references.add(key)
    order = lambda key: Decimal(key)
    warnings = tuple(str(plan[key]) for key in ('feed_error', 'aggregate_error') if plan.get(key))
    return InventoryCoverage(state=state, provider=provider_name, language=language,
        source_entries=source_count, other_entries=len(entries)-source_count,
        packaged=packaged, mixed_units=mixed_units,
        groups=tuple((key, by_volume[key]) for key in sorted(by_volume, key=order)),
        ungrouped=tuple(ungrouped), reference_volumes=tuple(sorted(references, key=order)),
        reference_gaps=tuple(sorted(references-set(by_volume), key=order)), warnings=warnings)
