"""Comparison-only Wikipedia title roles; never changes canonical/display data."""
import re
import unicodedata

from calibre_plugins.manganana.discovery.canonical_identity import normalize_identity_text


def wikipedia_title_key(value):
    text = unicodedata.normalize('NFKC', str(value or ''))
    # A literal typographic cross between words is the same title separator as
    # a spaced x. Do not remove other symbols or collapse arbitrary word gaps.
    text = re.sub(r'(?<=\w)\s*×\s*(?=\w)', ' x ', text)
    return normalize_identity_text(text)


def chapter_list_work_key(value):
    match = re.fullmatch(r'list of (.+) chapters', wikipedia_title_key(value))
    return match[1] if match else ''


def wikipedia_work_title_key(value):
    key = chapter_list_work_key(value) or wikipedia_title_key(value)
    return key[:-6].strip() if key.endswith(' manga') else key
