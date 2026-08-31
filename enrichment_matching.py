"""High-confidence external identity reconciliation and work-level signals."""

from dataclasses import dataclass
import hashlib
import math
import re

try:
    from .canonical_identity import normalize_identity_text
    from .enrichment_model import ExternalMangaCandidate, IdentityConfidence
    from .title_metadata import external_candidate_title_rows, normalize_title_rows
except ImportError:
    from canonical_identity import normalize_identity_text
    from enrichment_model import ExternalMangaCandidate, IdentityConfidence
    from title_metadata import external_candidate_title_rows, normalize_title_rows


_EDITION_WORDS = re.compile(
    r'\b(?:official(?:ly)?|digital|fan(?:made)?|full)?\s*colou?r(?:ed|ing)?(?:\s+(?:comics?|edition))?\b',
    re.I,
)


@dataclass(frozen=True)
class IdentityMatch:
    confidence: IdentityConfidence
    reason: str
    title_overlaps: tuple = ()


def _values(value):
    if isinstance(value, (list, tuple, set)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return (str(value).strip(),) if str(value or '').strip() else ()


def work_title(value):
    """Strip explicit edition markers without collapsing downloadable records."""
    return normalize_identity_text(_EDITION_WORDS.sub(' ', str(value or '')))


def content_work_titles(result):
    values = _values((result or {}).get('title')) + _values((result or {}).get('full_title'))
    values += _values((result or {}).get('alternate_titles'))
    return {work_title(value) for value in values if work_title(value)}


def external_work_titles(candidate):
    return {work_title(value) for value in candidate.titles if work_title(value)}


def _authors(result):
    values = _values((result or {}).get('authors')) or _values((result or {}).get('author'))
    keys = set()
    for value in values:
        normalized = normalize_identity_text(value)
        if normalized:
            keys.add(normalized)
            keys.add(' '.join(sorted(normalized.split())))
    return keys


def _external_ids(result):
    ids = dict((result or {}).get('external_ids') or {})
    for key in ('anilist_id', 'mal_id', 'kitsu_id'):
        if (result or {}).get(key) is not None:
            ids[key] = str((result or {}).get(key))
    return {str(key): str(value) for key, value in ids.items() if value not in (None, '')}


def match_external_identity(result, candidate):
    direct = set(_external_ids(result).items()) & set(dict(candidate.cross_ids or {}).items())
    if direct:
        return IdentityMatch(IdentityConfidence.HIGH, 'direct external-ID mapping')

    overlaps = tuple(sorted(content_work_titles(result) & external_work_titles(candidate)))
    if not overlaps:
        return IdentityMatch(IdentityConfidence.REJECT, 'no exact normalized title or alias overlap')

    content_authors = _authors(result)
    external_authors = _authors({'authors': candidate.authors})
    if content_authors and external_authors and not (content_authors & external_authors):
        return IdentityMatch(IdentityConfidence.REJECT, 'conflicting author metadata', overlaps)

    year = (result or {}).get('year')
    try:
        year = int(year) if year is not None else None
    except (TypeError, ValueError):
        year = None
    if year is not None and candidate.start_year is not None and abs(year - candidate.start_year) > 2:
        return IdentityMatch(IdentityConfidence.REJECT, 'incompatible publication era', overlaps)

    if content_authors and external_authors:
        return IdentityMatch(IdentityConfidence.HIGH, 'exact title/alias with matching author', overlaps)
    if year is not None and candidate.start_year is not None:
        return IdentityMatch(IdentityConfidence.HIGH, 'exact title/alias with compatible year', overlaps)
    if len(overlaps) >= 2:
        return IdentityMatch(IdentityConfidence.HIGH, 'multiple exact title/alias overlaps', overlaps)

    return IdentityMatch(IdentityConfidence.MEDIUM, 'single exact title/alias overlap without corroborating metadata', overlaps)


def consensus_rating(candidates):
    weighted = []
    for candidate in candidates:
        score = candidate.rating.score_10
        if score is None:
            continue
        weight = 1.0
        if candidate.service == 'kitsu':
            count = candidate.rating.sample_count
            if count is not None and count < 50:
                weight = max(0.2, float(count) / 50.0)
        weighted.append((float(score), weight))
    if not weighted:
        return None
    return sum(score * weight for score, weight in weighted) / sum(weight for _score, weight in weighted)


def _service_engagement(candidate):
    readers = max(0, int(candidate.popularity.readers or 0))
    favourites = max(0, int(candidate.popularity.favourites or 0))
    if not readers and not favourites:
        return None
    return 0.85 * math.log1p(readers) + 0.15 * math.log1p(favourites)


def normalized_popularity(work_candidates):
    """Return query-relative 0..1 signals; raw cross-site counts are never compared."""
    by_service = {}
    for work_key, candidates in work_candidates.items():
        for candidate in candidates:
            signal = _service_engagement(candidate)
            if signal is not None:
                by_service.setdefault(candidate.service, {})[work_key] = max(
                    signal, by_service.setdefault(candidate.service, {}).get(work_key, 0.0)
                )
    normalized = {work_key: [] for work_key in work_candidates}
    for rows in by_service.values():
        values = tuple(rows.values())
        low = min(values); high = max(values)
        for work_key, value in rows.items():
            score = 1.0 if high == low and high > 0 else ((value - low) / (high - low) if high > low else 0.0)
            normalized[work_key].append(score)
    return {
        work_key: (sum(values) / len(values) if values else None)
        for work_key, values in normalized.items()
    }


def _family_key(result):
    titles = sorted(content_work_titles(result))
    primary = work_title((result or {}).get('title'))
    basis = primary or (titles[0] if titles else str((result or {}).get('id') or 'unknown'))
    return hashlib.sha1(basis.encode('utf-8')).hexdigest()[:16]


def enrich_content_results(results, external_candidates):
    """Attach trusted work metadata while preserving every downloadable edition."""
    rows = [dict(result) for result in results or ()]
    candidates = tuple(
        value if isinstance(value, ExternalMangaCandidate) else ExternalMangaCandidate.from_record(value)
        for value in external_candidates or ()
    )
    family_candidates = {}
    row_candidates = []
    for row in rows:
        trusted = tuple(
            candidate for candidate in candidates
            if match_external_identity(row, candidate).confidence is IdentityConfidence.HIGH
        )
        key = _family_key(row)
        row['work_family_id'] = key
        if trusted:
            family_candidates.setdefault(key, {})
            for candidate in trusted:
                family_candidates[key][(candidate.service, candidate.external_id)] = candidate
        row_candidates.append((row, key, trusted))

    family_candidates = {key: tuple(values.values()) for key, values in family_candidates.items()}
    popularity = normalized_popularity(family_candidates)
    output = []
    for row, key, trusted in row_candidates:
        inherited = family_candidates.get(key, trusted)
        if inherited:
            aliases = list(row.get('alternate_titles') or ())
            structured = list(row.get('structured_titles') or row.get('titles') or ())
            for candidate in inherited:
                aliases.extend(candidate.titles)
                structured.extend(external_candidate_title_rows(candidate))
            row['alternate_titles'] = list(dict.fromkeys(value for value in aliases if value))
            row['structured_titles'] = list(normalize_title_rows(structured))
            rating = consensus_rating(inherited)
            row['consensus_rating'] = rating
            row['rating_display'] = f'{rating:.1f}/10' if rating is not None else ''
            row['external_ids'] = {
                key: value for candidate in inherited for key, value in candidate.cross_ids.items()
            }
            row['external_authors'] = list(dict.fromkeys(author for candidate in inherited for author in candidate.authors))
            row['volume_context'] = [
                candidate.volume_context.__dict__ for candidate in inherited if candidate.volume_context
            ]
            row['popularity_normalized'] = popularity.get(key)
            # Compatibility surface for the local tiered ranker.
            row['popularity'] = {
                **dict(row.get('popularity') or {}),
                'normalized': popularity.get(key), 'provider': 'external-consensus',
            }
        output.append(row)
    return tuple(output)


def trusted_alias_for_query(query, candidates):
    """Return one alias only when independent services corroborate the work."""
    query_key = work_title(query)
    grouped = {}
    for candidate in candidates or ():
        candidate = candidate if isinstance(candidate, ExternalMangaCandidate) else ExternalMangaCandidate.from_record(candidate)
        titles = tuple(value for value in candidate.titles if work_title(value))
        if query_key not in {work_title(value) for value in titles}:
            continue
        grouped.setdefault(work_title(candidate.primary_title), []).append((candidate,titles))
    for _work_key, rows in grouped.items():
        if len({candidate.service for candidate,_titles in rows}) < 2:
            continue
        primary = rows[0][0].primary_title
        if primary and work_title(primary) != query_key:
            return primary
        alternates = [value for _candidate,titles in rows for value in titles if work_title(value) != query_key]
        if alternates:
            return sorted(set(alternates), key=lambda value: (len(value), value.casefold()))[0]
    return ''
