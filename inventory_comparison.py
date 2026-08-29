"""Provider-neutral inventory inspection and conservative source ranking."""

from dataclasses import dataclass

try:
    from .canonical_identity import edition_identity
except ImportError:
    from canonical_identity import edition_identity


@dataclass(frozen=True)
class SourceInventory:
    source_id: str
    source_name: str
    result: dict
    language: str
    edition: str
    language_match: bool = False
    native_volumes: int = 0
    native_volume_metadata: int = 0
    volume_ids: tuple = ()
    chapters_by_volume: tuple = ()
    standalone_chapters: int = 0
    chapter_count: int = 0
    usable: bool = False
    complete: bool = False
    error: str = ''
    capabilities: tuple = ()

    @property
    def summary(self):
        if self.error and not self.usable:
            return f'Unavailable ({self.error})'
        parts = []
        if self.native_volumes:
            parts.append(f'{self.native_volumes} volume' + ('' if self.native_volumes == 1 else 's'))
        if self.standalone_chapters:
            parts.append(f'{self.standalone_chapters} standalone chapter' + ('' if self.standalone_chapters == 1 else 's'))
        elif self.chapter_count:
            parts.append(f'{self.chapter_count} chapter' + ('' if self.chapter_count == 1 else 's'))
        if not parts:
            if self.native_volume_metadata:
                parts.append(f'{self.native_volume_metadata} native volume metadata entr' + ('y' if self.native_volume_metadata == 1 else 'ies') + ', no usable chapters')
            else:
                parts.append('No usable chapters')
        if self.error and self.usable:
            parts.append('partial: ' + self.error)
        return ', '.join(parts)


@dataclass(frozen=True)
class InventoryDecision:
    inventories: tuple
    selected: SourceInventory = None
    ambiguous: bool = False
    reason: str = ''
    error: str = ''
    fallback_plan: object = None


def inspect_source_inventory(source, result, language):
    """Inspect one adapter's normalized plan without page or image downloads."""
    value = result.get('url') or result.get('id')
    edition = edition_identity(result)
    try:
        plan = source.get_download_plan(value, language) or {}
        nominal_volumes = tuple(plan.get('volumes') or ())
        # Aggregate/provider metadata is advisory. Only a readable chapter
        # record proves a native volume can reach Review and Download.
        chapters = tuple(source.get_chapters(value, language) or ())
        by_volume = {}
        standalone = 0
        for chapter in chapters:
            volume = chapter.get('volume')
            if volume is None:
                standalone += 1
            else:
                try:
                    volume = float(volume)
                except (TypeError, ValueError):
                    continue
                by_volume[volume] = by_volume.get(volume, 0) + 1
        volumes = tuple(sorted(by_volume))
        chapter_count = len(chapters)
        errors = [str(plan.get(key)) for key in ('aggregate_error', 'feed_error') if plan.get(key)]
        error = '; '.join(errors)
        usable = chapter_count > 0
        return SourceInventory(
            source_id=source.source_id, source_name=source.display_name,
            result=dict(result), language=language, edition=edition,
            language_match=usable, native_volumes=len(volumes), native_volume_metadata=len(nominal_volumes), volume_ids=volumes,
            chapters_by_volume=tuple(sorted(by_volume.items(), key=lambda item: float(item[0]))),
            standalone_chapters=standalone,
            chapter_count=chapter_count, usable=usable,
            complete=usable and not error, error=error,
            capabilities=tuple(sorted(source.capabilities)),
        )
    except Exception as exc:
        return SourceInventory(
            source_id=source.source_id, source_name=source.display_name,
            result=dict(result), language=language, edition=edition,
            error=str(exc), capabilities=tuple(sorted(source.capabilities)),
        )


def compare_inventories(inventories, expected_edition='original', workflow=None):
    """Choose only when one provider is clearly superior; otherwise remain ambiguous."""
    rows = tuple(inventories or ())
    eligible = [row for row in rows if row.edition == expected_edition]
    # A volume job is only meaningful when a provider exposes native volume
    # structure.  Chapter-native providers remain eligible in Chapter mode.
    usable = [row for row in eligible if row.usable and
              (workflow != 'volume' or row.native_volumes > 0)]
    if not usable:
        if workflow == 'volume':
            details = '; '.join(f'{row.source_name}: {row.summary}' for row in rows)
            return InventoryDecision(rows, error=details or 'No usable native volumes are currently available.')
        details = '; '.join(f'{row.source_name}: {row.summary}' for row in rows)
        return InventoryDecision(rows, error=details or 'No providers could be inspected.')
    if len(usable) == 1:
        winner = usable[0]
        return InventoryDecision(rows, selected=winner,
                                 reason=f'{winner.source_name} is the only source with usable {winner.language} inventory.')

    complete = [row for row in usable if row.complete]
    if len(complete) == 1:
        winner = complete[0]
        return InventoryDecision(rows, selected=winner,
                                 reason=f'{winner.source_name} has complete inventory while alternatives are partial.')

    pool = complete or usable
    ordered = sorted(pool, key=lambda row: (-row.chapter_count, -row.native_volumes, row.source_id))
    first, second = ordered[0], ordered[1]
    chapter_advantage = first.chapter_count - second.chapter_count
    clearly_more_complete = chapter_advantage >= 5 and first.chapter_count >= second.chapter_count * 1.25
    if clearly_more_complete:
        return InventoryDecision(rows, selected=first,
                                 reason=f'{first.source_name} has the more complete {first.language} inventory.')

    if workflow == 'volume':
        volume_sources = [row for row in pool if row.native_volumes > 0]
        if len(volume_sources) == 1:
            winner = volume_sources[0]
            # Prefer native structure only when it does not sacrifice substantial coverage.
            if winner.chapter_count >= first.chapter_count * 0.9:
                return InventoryDecision(rows, selected=winner,
                                         reason=f'{winner.source_name} provides comparable coverage with native volumes.')

    return InventoryDecision(rows, ambiguous=True,
                             reason='Providers have similarly usable inventory; user choice is required.')
