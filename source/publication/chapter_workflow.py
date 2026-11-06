"""Pure helpers shared by the explicit Chapter-mode UI and workers."""

from decimal import Decimal, InvalidOperation

from calibre_plugins.manganana.providers.cross_source_fallback import normalize_chapter_number


def chapter_sort_key(chapter):
    """Sort numeric chapters before ambiguous specials without inventing order."""
    # An approved export can supply an independently reviewed sequence ordinal.
    # The opaque episode token and original acquisition label are never parsed
    # to manufacture this order. Absent proof retains the legacy ordering.
    order = (chapter or {}).get('_publication_reading_order')
    if (chapter or {}).get('_publication_identity') and type(order) is int:
        return (0, Decimal(order), '', str(chapter.get('id') or ''))
    if (chapter or {}).get('numbering_group') == 'prologue':
        ordinal=normalize_chapter_number(chapter.get('numbering_ordinal'))
        if ordinal is not None:
            return (-1,Decimal(ordinal),'',str(chapter.get('id') or ''))
    number = normalize_chapter_number((chapter or {}).get('chapter'))
    if number is not None:
        return (0, Decimal(number), str((chapter or {}).get('title') or '').casefold(), str((chapter or {}).get('id') or ''))
    return (1, Decimal('Infinity'), str((chapter or {}).get('chapter') or '').casefold(), str((chapter or {}).get('id') or ''))


def chapter_label(chapter, zero_pad=False):
    """Return a stable human/output label without treating specials as numbers."""
    raw = str((chapter or {}).get('chapter') or '').strip()
    normalized = normalize_chapter_number(raw)
    if normalized is None:
        return raw or 'Special'
    if zero_pad:
        whole, dot, fraction = normalized.partition('.')
        normalized = whole.zfill(2) + (dot + fraction if dot else '')
    return normalized


def chapter_output_title(series_title, chapter, zero_pad=False):
    base = f'{series_title} (Ch. {chapter_label(chapter, zero_pad)})'
    title = str((chapter or {}).get('title') or '').strip()
    return f'{base} - {title}' if title else base


def chapter_series_index(chapter):
    """Return a Calibre-sortable numeric index only when the label is exact."""
    number = normalize_chapter_number((chapter or {}).get('chapter'))
    if number is None:
        return None
    try:
        return float(Decimal(number))
    except (InvalidOperation, ValueError):
        return None


def chapter_selection_ids(chapters):
    return {str(row.get('id') or '') for row in chapters or () if str(row.get('id') or '')}
