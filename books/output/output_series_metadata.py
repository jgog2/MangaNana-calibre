"""Effective output metadata; source/acquisition identity remains separate."""
import math
import re
import hashlib
import json
from decimal import Decimal

from calibre_plugins.manganana.publication.chapter_workflow import chapter_series_index


def parse_series_index(text):
    text = str(text).strip()
    if len(text) > 64 or not re.fullmatch(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)', text):
        raise ValueError('Series # must be an integer or decimal, such as 5 or 5.5.')
    value = float(text)
    if not math.isfinite(value):
        raise ValueError('Series # must be a finite number.')
    return value


def planned_series_index(row):
    if 'series_index_override' in row:
        return parse_series_index(row['series_index_override'])
    value = row.get('volume')
    if row.get('kind') == 'chapter' and row.get('chapter'):
        value = chapter_series_index(row['chapter'])
    # Calibre Metadata's default when no source/import index is available.
    try:
        return parse_series_index(value) if value is not None else 1.0
    except ValueError:
        return 1.0


def format_series_index(value):
    text = format(Decimal(str(value)), 'f')
    return text.rstrip('0').rstrip('.') if '.' in text else text


def legacy_output_identity(row):
    if row.get('kind') == 'import':
        return ('import', row['import_id'])
    kind = row.get('kind') or ('volume' if row.get('volume') is not None else 'standalone')
    value = row.get('volume')
    if kind == 'chapter' and row.get('chapter'):
        value = chapter_series_index(row['chapter'])
    if kind == 'chapter' and value is None:
        value = row.get('chapter_number')
    try:
        value = parse_series_index(value) if value is not None else None
    except ValueError:
        value = None
    return (kind, value)


def bind_output_identity(row, *, source_id='', series_ref='', edition='original', language='', chapters=None):
    """Bind finalization ownership once; bibliography never participates."""
    if row.get('output_identity'):
        return row
    kind = row.get('kind') or ('volume' if row.get('volume') is not None else 'standalone')
    if kind == 'import':
        book = row.get('book') or {}
        # File identity is already validated by local acquisition. A reinspection
        # of the same file must not acquire a new UUID-based metadata key.
        payload = dict(kind=kind, file=list(book.get('identity') or (row['import_id'],)))
    else:
        group = row.get('group') or {}
        records = chapters if chapters is not None else group.get('chapters')
        if records is None:
            records = [row['chapter']] if row.get('chapter') else []
        members = []
        for chapter in records:
            exact_id = str(chapter.get('id') or '')
            if not exact_id:
                raise ValueError('An output chapter is missing its exact acquisition identity.')
            members.append((str(chapter.get('_source_id') or source_id), exact_id))
        if not source_id or not series_ref or not members:
            raise ValueError('Cannot prepare an output without its source series and acquisition records.')
        payload = dict(kind=kind, source_id=str(source_id), series_ref=str(series_ref),
                       edition=str(edition or 'original'), language=str(language or ''),
                       members=[list(value) for value in sorted(set(members))])
        if kind == 'volume':
            payload['volume'] = format_series_index(row['volume'])
    encoded = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    row['output_acquisition'] = payload
    row['output_identity'] = 'v2:' + hashlib.sha256(encoded.encode('utf8')).hexdigest()
    return row


def output_identity(row):
    if row.get('output_identity'):
        return ('output-v2', str(row['output_identity']))
    # Compatibility for old callers/snapshots only. Runtime plans bind a source
    # identity before editing; never promote a legacy key to an acquisition ID.
    return legacy_output_identity(row)


def migrate_legacy_overrides(rows, overrides, *, eligible=True):
    """Migrate only one-to-one legacy keys. Ambiguous originals remain intact."""
    unresolved = {}
    for key, value in list(overrides.items()):
        if key and key[0] == 'output-v2':
            continue
        matches = {output_identity(row) for row in rows if legacy_output_identity(row) == key} if eligible else set()
        if len(matches) == 1:
            target = next(iter(matches))
            overrides[target] = dict(value, **overrides.get(target, {}))
            del overrides[key]
        else:
            unresolved[key] = dict(value)
    return unresolved


def effective_output_metadata(row, *, output_format=None, cover_mode=None):
    """One output-facing snapshot, without overwriting source volume/group/book.

    Explicit overrides win across table rebuilds. Consumers snapshot this before
    starting workers so later GUI edits cannot alter an in-flight output job.
    """
    overrides = row.get('output_overrides') or {}
    result = {field: overrides.get(field, row.get(field, ''))
              for field in ('title', 'series', 'author', 'language')}
    result['series_index'] = overrides.get('series_index', planned_series_index(row))
    result['series_index_override'] = result['series_index']
    # A user-numbered standalone/import must show that number on stamped and
    # generated covers too. Keep the acquisition kind/volume untouched. Carry
    # this presentation decision across worker snapshots (whose overrides may
    # already have been flattened).
    result['cover_number_kind'] = (
        'chapter' if row.get('kind') == 'chapter' else
        'volume' if row.get('volume') is not None or 'series_index' in overrides else
        row.get('cover_number_kind', 'standalone'))
    result['format'] = output_format or row.get('format') or 'cbz'
    result['cover_mode'] = cover_mode or row.get('cover_mode') or 'keep'
    result['cover_url'] = row.get('cover_url', '')
    for field in ('output_identity', 'output_acquisition'):
        if field in row:
            result[field] = row[field]
    return result


def renumber_values(count, start, step):
    start, step = Decimal(str(parse_series_index(start))), Decimal(str(parse_series_index(step)))
    return [parse_series_index(str(start + index*step)) for index in range(count)]


def snapshot_overrides(rows):
    return {output_identity(row): row['series_index_override'] for row in rows
            if row.get('selected') and 'series_index_override' in row}


def with_series_override(item, overrides):
    """Attach a finalized override to a result copy at the Calibre boundary."""
    key = output_identity(item)
    return dict(item, series_index_override=overrides[key]) if key in overrides else item


def append_output_provenance(root, metadata):
    """Preserve exact acquisition evidence separately from numeric Number."""
    import xml.etree.ElementTree as ET
    for tag, value in (('MangaAnkaOutputIdentity', metadata.get('output_identity')),
                       ('MangaAnkaAcquisition', json.dumps(metadata['output_acquisition'], ensure_ascii=False) if metadata.get('output_acquisition') else ''),
                       ('MangaAnkaChapterLabel', metadata.get('chapter_number') or
                        (metadata.get('chapter') or {}).get('chapter'))):
        if value:
            for old in list(root.findall(tag)):
                root.remove(old)
            ET.SubElement(root, tag).text = str(value)
