"""Conservative, provider-neutral canonical manga identity helpers."""

from dataclasses import dataclass
import re
import unicodedata

try:
    from .enrichment_model import EditionClass
except ImportError:
    from enrichment_model import EditionClass


_COLOR_MARKERS = (
    ('fan_color', re.compile(r'\bfan\s+colou?red\b', re.I)),
    ('official_color', re.compile(
        r'\b(?:official(?:ly)?\s+colou?red|digital\s+colou?red|full\s+colou?r|colou?red\s+edition|official\s+color|colou?r(?:ed)?)\b',
        re.I,
    )),
)


def normalize_identity_text(value):
    """Normalize Unicode, case, punctuation, and whitespace conservatively."""
    text = unicodedata.normalize('NFKC', str(value or '')).casefold()
    text = ''.join(' ' if unicodedata.category(ch).startswith('P') else ch for ch in text)
    return ' '.join(text.split())


def edition_classification(result):
    """Classify only explicit provider/title evidence; absence stays UNKNOWN."""
    explicit = str((result or {}).get('edition_class') or (result or {}).get('edition') or '').casefold().strip()
    aliases = {
        'standard': EditionClass.STANDARD, 'original': EditionClass.STANDARD,
        'b&w': EditionClass.STANDARD, 'bw': EditionClass.STANDARD,
        'official_color': EditionClass.OFFICIAL_COLOR, 'official color': EditionClass.OFFICIAL_COLOR,
        'color': EditionClass.OFFICIAL_COLOR, 'colored': EditionClass.OFFICIAL_COLOR,
        'fan_color': EditionClass.FAN_COLOR, 'fan color': EditionClass.FAN_COLOR,
        'unknown': EditionClass.UNKNOWN,
    }
    if explicit in aliases:
        return aliases[explicit]
    text = ' '.join(str(result.get(key) or '') for key in ('title', 'full_title', 'badge'))
    for name, pattern in _COLOR_MARKERS:
        if pattern.search(text):
            return EditionClass.FAN_COLOR if name == 'fan_color' else EditionClass.OFFICIAL_COLOR
    badge = str((result or {}).get('badge') or '').casefold().strip()
    if badge in ('b&w', 'bw', 'standard') or (result or {}).get('is_colored') is False:
        return EditionClass.STANDARD
    return EditionClass.UNKNOWN


def edition_identity(result):
    """Compatibility identity used to keep color siblings separate."""
    classification = edition_classification(result or {})
    if classification is EditionClass.OFFICIAL_COLOR:
        return 'official_color'
    if classification is EditionClass.FAN_COLOR:
        return 'fan_color'
    # Existing unmarked catalogue records historically represented the normal
    # edition for grouping, but display code must still omit an unproven B&W tag.
    return 'original'


def edition_display_label(result):
    classification = edition_classification(result or {})
    return {
        EditionClass.STANDARD: 'B&W',
        EditionClass.OFFICIAL_COLOR: 'COLOR',
        EditionClass.FAN_COLOR: 'FAN COLOR',
        EditionClass.UNKNOWN: '',
    }[classification]


def _values(result, key):
    value = result.get(key)
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value or '').strip() else []


def identity_titles(result):
    values = _values(result, 'title') + _values(result, 'alternate_titles')
    normalized = {normalize_identity_text(value) for value in values}
    return {value for value in normalized if value}


def identity_authors(result):
    values = _values(result, 'authors') or _values(result, 'author')
    return {normalize_identity_text(value) for value in values if normalize_identity_text(value)}


def relevance_score(query, result):
    """Compatibility wrapper for the provider-neutral tiered ranker."""
    try:
        from .search_ranking import relevance_score as rank_score
    except ImportError:
        from search_ranking import relevance_score as rank_score
    return rank_score(query, result)


def filter_relevant_results(query, results):
    """Compatibility wrapper returning rows from accepted canonical groups."""
    try:
        from .search_ranking import filter_relevant_results as rank_filter
    except ImportError:
        from search_ranking import filter_relevant_results as rank_filter
    return rank_filter(query, results)


@dataclass(frozen=True)
class CanonicalGroup:
    display_title: str
    aliases: tuple
    results: tuple
    source_ids: tuple
    source_names: tuple
    confidence: str
    reason: str


def _can_join(group_results, candidate):
    if candidate.get('source_id') in {row.get('source_id') for row in group_results}:
        return False, ''
    if any(edition_identity(row) != edition_identity(candidate) for row in group_results):
        return False, ''
    candidate_titles = identity_titles(candidate)
    group_titles = set().union(*(identity_titles(row) for row in group_results))
    overlap = candidate_titles & group_titles
    if not overlap:
        return False, ''
    candidate_authors = identity_authors(candidate)
    group_authors = set().union(*(identity_authors(row) for row in group_results))
    if candidate_authors and group_authors and not (candidate_authors & group_authors):
        return False, ''
    candidate_year = candidate.get('year')
    group_years = {row.get('year') for row in group_results if row.get('year') is not None}
    if candidate_year is not None and group_years and candidate_year not in group_years:
        return False, ''
    primary = normalize_identity_text(candidate.get('title'))
    group_primaries = {normalize_identity_text(row.get('title')) for row in group_results}
    reason = 'exact normalized primary title' if primary in group_primaries else 'alternate-title overlap'
    if candidate_authors and group_authors:
        reason += ' with matching author'
    if candidate_year is not None and group_years:
        reason += ' and year'
    return True, reason


def group_canonical_results(results):
    """Group only high-confidence identities while preserving input order."""
    groups = []
    reasons = []
    for original in results or ():
        candidate = dict(original)
        joined = False
        for index, rows in enumerate(groups):
            match, reason = _can_join(rows, candidate)
            if match:
                rows.append(candidate)
                reasons[index] = reason
                joined = True
                break
        if not joined:
            groups.append([candidate])
            reasons.append('single provider result')

    output = []
    for rows, reason in zip(groups, reasons):
        aliases = []
        seen_aliases = set()
        for row in rows:
            for alias in _values(row, 'title') + _values(row, 'alternate_titles'):
                key = normalize_identity_text(alias)
                if key and key not in seen_aliases:
                    seen_aliases.add(key); aliases.append(alias)
        source_ids = tuple(dict.fromkeys(row.get('source_id') for row in rows if row.get('source_id')))
        source_names = tuple(dict.fromkeys(row.get('source_name') for row in rows if row.get('source_name')))
        display_title = str(rows[0].get('title') or (aliases[0] if aliases else 'Untitled'))
        output.append(CanonicalGroup(
            display_title=display_title,
            aliases=tuple(aliases), results=tuple(rows), source_ids=source_ids,
            source_names=source_names, confidence='high' if len(rows) > 1 else 'single',
            reason=reason,
        ))
    return tuple(output)
