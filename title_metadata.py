"""Structured alternate-title normalization without network activity."""

import unicodedata


LANGUAGE_LABELS = {
    'en': 'English',
    'ja-ro': 'Japanese (Romanized)',
    'ja_romaji': 'Japanese (Romanized)',
    'en_jp': 'Japanese (Romanized)',
    'ja': 'Japanese',
    'ja-jp': 'Japanese',
    'ja_jp': 'Japanese',
}


def title_language_label(row):
    value = dict(row or {})
    classification = str(value.get('classification') or '').casefold().strip()
    if classification in ('romanized', 'romaji', 'japanese_romanized'):
        return 'Japanese (Romanized)'
    if classification in ('native', 'japanese_native'):
        return 'Japanese'
    code = str(value.get('language') or '').casefold().strip()
    return LANGUAGE_LABELS.get(code, str(value.get('language_label') or '').strip() or 'Unknown')


def _key(text):
    normalized = unicodedata.normalize('NFKC', str(text or '')).casefold()
    return ''.join(ch for ch in normalized if ch.isalnum())


def normalize_title_rows(rows, selected_title=''):
    """Deduplicate title rows while preserving trustworthy structured roles."""
    output = []
    positions = {}
    for original in rows or ():
        if isinstance(original, str):
            row = {'title': original, 'language': '', 'primary': False, 'provenance': ''}
        else:
            row = dict(original or {})
        text = str(row.get('title') or row.get('text') or '').strip()
        key = _key(text)
        if not text or not key:
            continue
        row['title'] = text
        row['primary'] = bool(row.get('primary'))
        row['language_label'] = title_language_label(row)
        existing = positions.get(key)
        if existing is None:
            positions[key] = len(output)
            output.append(row)
            continue
        current = output[existing]
        # Prefer structured classification/provenance over an earlier bare alias.
        if current.get('language_label') == 'Unknown' and row.get('language_label') != 'Unknown':
            row['primary'] = bool(row.get('primary') or current.get('primary'))
            output[existing] = row
        elif row.get('primary') and not current.get('primary'):
            current['primary'] = True
    return tuple(output)


def meaningful_alternate_titles(rows, selected_title=''):
    normalized = normalize_title_rows(rows, selected_title)
    return normalized if len({_key(row.get('title')) for row in normalized}) >= 2 else ()


def external_candidate_title_rows(candidate):
    """Convert already-fetched AniList/Kitsu title fields into typed rows."""
    rows = []
    values = (
        ('english_title', 'en', 'english'),
        ('romanized_title', 'ja-ro', 'romanized'),
        ('native_title', 'ja', 'native'),
        ('primary_title', '', 'primary'),
    )
    for field, language, classification in values:
        text = str(getattr(candidate, field, '') or '').strip()
        if text:
            rows.append({
                'title': text, 'language': language,
                'classification': classification,
                'primary': field == 'primary_title',
                'provenance': getattr(candidate, 'service', ''),
            })
    for alias in getattr(candidate, 'aliases', ()) or ():
        rows.append({
            'title': str(alias), 'language': '', 'classification': '',
            'primary': False, 'provenance': getattr(candidate, 'service', ''),
        })
    return normalize_title_rows(rows)

