"""Conservative, provider-neutral canonical manga identity helpers."""

from dataclasses import dataclass
import re
import unicodedata


_COLOR_MARKERS = (
    ('fan_color', re.compile(r'\bfan\s+colou?red\b', re.I)),
    ('official_color', re.compile(
        r'\b(?:official(?:ly)?\s+colou?red|digital\s+colou?red|full\s+colou?r|colou?red\s+edition|official\s+color)\b',
        re.I,
    )),
)


def normalize_identity_text(value):
    """Normalize Unicode, case, punctuation, and whitespace conservatively."""
    text = unicodedata.normalize('NFKC', str(value or '')).casefold()
    text = ''.join(' ' if unicodedata.category(ch).startswith('P') else ch for ch in text)
    return ' '.join(text.split())


def edition_identity(result):
    """Return the explicit edition class advertised by a result."""
    text = ' '.join(str(result.get(key) or '') for key in ('title', 'full_title', 'badge'))
    for name, pattern in _COLOR_MARKERS:
        if pattern.search(text):
            return name
    return 'original'


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


def source_badge_specs(source_names):
    """Return deterministic metadata for compact provider chips."""
    return tuple({'text': name, 'kind': 'source'} for name in dict.fromkeys(source_names or ()) if name)


def relevance_score(query, result):
    """Score exact and strong all-token matches; return None for weak matches."""
    normalized_query = normalize_identity_text(query)
    if not normalized_query:
        return None
    primary = normalize_identity_text(result.get('title'))
    aliases = {normalize_identity_text(value) for value in _values(result, 'alternate_titles')}
    if primary == normalized_query:
        return 1000
    if normalized_query in aliases:
        return 950
    query_tokens = tuple(normalized_query.split())
    if len(query_tokens) < 2:
        return None
    candidate_titles = [primary] + sorted(aliases)
    matches = []
    wanted = set(query_tokens)
    for title in candidate_titles:
        tokens = set(title.split())
        if wanted <= tokens:
            matches.append(700 - max(0, len(tokens) - len(wanted)) * 10)
    return max(matches) if matches else None


def filter_relevant_results(query, results):
    """Filter weak incidental matches while retaining canonical companions."""
    rows = [dict(row) for row in (results or ())]
    scores = [relevance_score(query, row) for row in rows]
    grouped = group_canonical_results(rows)
    retained_ids = set()
    for group in grouped:
        indexes = [index for index, row in enumerate(rows) if row in group.results]
        if any(scores[index] is not None for index in indexes):
            retained_ids.update(indexes)
    ranked = [(scores[index] if scores[index] is not None else 0, index, row)
              for index, row in enumerate(rows) if index in retained_ids]
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return tuple(row for _score, _index, row in ranked)


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
