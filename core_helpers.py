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
