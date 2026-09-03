"""Pure native-plus-projected volume inventory normalization.

The publication projection supplies evidence only.  Acquisition chapter rows
remain authoritative for what can actually be downloaded.
"""

import math


def _volume_number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def build_unified_volume_plan(native_plan, acquisition_rows, projection,
                              source_id='', source_name=''):
    """Return one conservative Volume-mode plan.

    Provider-native membership is established first.  Publication evidence may
    assign only acquisition rows whose provider volume is absent.  It never
    creates chapters, guesses boundaries, or replaces native membership.
    """
    plan = dict(native_plan or {})
    projected = tuple(projection.rows) if projection is not None else ()
    acquisitions = tuple(dict(row) for row in acquisition_rows or ())
    if len(projected) != len(acquisitions):
        projected = acquisitions

    native_groups = {}
    ungrouped = []
    for original, enriched in zip(acquisitions, projected):
        row = dict(enriched)
        row.setdefault('_source_id', str(original.get('_source_id') or source_id or ''))
        row.setdefault('_source_name', str(original.get('_source_name') or source_name or ''))
        provider_volume = _volume_number(original.get('volume'))
        if provider_volume is None:
            ungrouped.append((original, row))
        else:
            native_groups.setdefault(provider_volume, []).append(row)

    groups = {volume: list(rows) for volume, rows in native_groups.items()}
    derived_volumes = set()
    projected_assignments = 0
    unresolved = []
    for original, row in ungrouped:
        volume = _volume_number(row.get('_effective_volume'))
        if volume is None:
            unresolved.append(row)
            continue
        groups.setdefault(volume, []).append(row)
        projected_assignments += 1
        if volume not in native_groups:
            derived_volumes.add(volume)

    output_groups = []
    for volume in sorted(groups):
        provenance = 'native' if volume in native_groups else 'derived'
        output_groups.append({
            'kind': 'volume', 'identifier': f'{volume:g}', 'volume': volume,
            'mode': 'unified_volume', 'provenance': provenance,
            'chapters': tuple(groups[volume]),
        })
    if unresolved:
        output_groups.append({
            'kind': 'standalone', 'identifier': 'standalone', 'volume': None,
            'mode': 'unified_volume', 'provenance': 'unmapped',
            'chapters': tuple(unresolved),
        })

    plan.update({
        'volumes': sorted(groups),
        'chapters_by_volume': {volume: len(rows) for volume, rows in groups.items()},
        'bonus_chapters': len(unresolved),
        'volume_groups': tuple(output_groups),
        'native_volume_count': len(native_groups),
        'derived_volume_count': len(derived_volumes),
        'projected_assignment_count': projected_assignments,
        'unmapped_chapter_count': len(unresolved),
        'requires_grouped_output': bool(projected_assignments),
    })
    return plan


def selected_unified_volume_groups(plan, selected_volumes=(), include_standalone=False):
    """Select exact output groups from a normalized plan without regrouping."""
    selected = set(float(value) for value in selected_volumes or ())
    result = []
    for original in (plan or {}).get('volume_groups') or ():
        group = dict(original)
        if group.get('kind') == 'volume':
            if float(group.get('volume')) not in selected:
                continue
        elif not include_standalone:
            continue
        result.append(group)
    return tuple(result)
