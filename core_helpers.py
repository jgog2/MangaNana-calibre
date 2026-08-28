"""Pure helpers shared by MangaNana without Calibre or Qt dependencies."""

import re


VOL_RE = re.compile(r'(?i)(?:vol(?:ume)?\.?\s*)(\d+(?:\.\d+)?)')


def first_localized(obj, preferred='en'):
    if not isinstance(obj, dict):
        return ''
    return obj.get(preferred) or obj.get('en') or next(iter(obj.values()), '')


def choose_preferred_title(title_rows, preferred='en'):
    for row in title_rows:
        if row['language'] == preferred:
            return row['title']
    for row in title_rows:
        if row['language'] == 'en':
            return row['title']
    return title_rows[0]['title'] if title_rows else ''


def collect_titles(attrs):
    """Return MangaDex primary and alternate titles as ordered language/title rows."""
    rows = []
    seen = set()
    primary = attrs.get('title') or {}
    for code, text in primary.items():
        text = str(text or '').strip()
        key = (code, text.casefold())
        if text and key not in seen:
            seen.add(key); rows.append({'language': code, 'title': text, 'primary': True})
    for alt in attrs.get('altTitles') or []:
        if not isinstance(alt, dict):
            continue
        for code, text in alt.items():
            text = str(text or '').strip()
            key = (code, text.casefold())
            if text and key not in seen:
                seen.add(key); rows.append({'language': code, 'title': text, 'primary': False})
    return rows


def is_doujinshi_entry(attrs):
    """Return True when MangaDex metadata identifies a result as doujinshi."""
    for tag in (attrs or {}).get('tags') or []:
        names = ((tag or {}).get('attributes') or {}).get('name') or {}
        if isinstance(names, dict):
            texts = names.values()
        else:
            texts = [names]
        for text in texts:
            folded = str(text or '').casefold()
            if 'doujinshi' in folded or 'doujin' in folded:
                return True
    title_text = ' '.join(r.get('title', '') for r in collect_titles(attrs or {})).casefold()
    return 'doujinshi' in title_text or 'doujin' in title_text


def _iter_aggregate_nodes(value):
    """Yield MangaDex aggregate objects whether the API returns a map or list."""
    if isinstance(value, dict):
        for key, row in value.items():
            yield key, row or {}
    elif isinstance(value, list):
        for index, row in enumerate(value):
            row = row or {}
            key = row.get('volume') if isinstance(row, dict) else index
            yield key, row if isinstance(row, dict) else {}


def volume_from_name(name):
    m = VOL_RE.search(name)
    if not m:
        return None
    try:
        return float(m.group(1))
    except Exception:
        return None


def fmt_volume(v, zero_pad=True):
    if float(v).is_integer():
        n = int(v)
        return f'{n:02d}' if zero_pad else str(n)
    return f'{v:g}'
