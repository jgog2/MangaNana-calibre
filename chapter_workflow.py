"""Pure helpers shared by the explicit Chapter-mode UI and workers."""

from decimal import Decimal, InvalidOperation

try:
    from .cross_source_fallback import normalize_chapter_number
except ImportError:
    from cross_source_fallback import normalize_chapter_number


def chapter_sort_key(chapter):
    """Sort numeric chapters before ambiguous specials without inventing order."""
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
    return f'{series_title} (Ch. {chapter_label(chapter, zero_pad)})'


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
