"""High-confidence external identity reconciliation and work-level signals."""

from dataclasses import dataclass
import hashlib
import math
import re

try:
    from .canonical_identity import creator_comparison_identity, normalize_identity_text
    from .enrichment_model import ExternalMangaCandidate, IdentityConfidence
    from .title_metadata import external_candidate_title_rows, normalize_title_rows
except ImportError:
    from canonical_identity import creator_comparison_identity, normalize_identity_text
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


@dataclass(frozen=True)
class CanonicalWorkFacts:
    """Resolved display facts for an already-confident provider work group."""
    canonical_work_id: str = ''
    canonical_title: str = ''
    creator: str = ''
    creator_provenance: str = ''
    creator_conflicted: bool = False
    creator_aliases: tuple = ()
    creators: tuple = ()


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


def content_core_titles(result):
    """Provider titles that identify the card itself, excluding aliases."""
    values = _values((result or {}).get('title')) + _values((result or {}).get('full_title'))
    return {work_title(value) for value in values if work_title(value)}


def external_work_titles(candidate):
    return {work_title(value) for value in candidate.titles if work_title(value)}


def external_core_titles(candidate):
    values=(candidate.primary_title,candidate.english_title,
            candidate.romanized_title,candidate.native_title)
    return {work_title(value) for value in values if work_title(value)}


def _authors(result):
    values = _values((result or {}).get('authors')) or _values((result or {}).get('author'))
    keys = set()
    for value in values:
        identity = creator_comparison_identity(value)
        if identity:
            keys.add(identity)
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

    content_titles=content_work_titles(result)
    external_titles=external_work_titles(candidate)
    overlaps = tuple(sorted(content_titles & external_titles))
    if not overlaps:
        return IdentityMatch(IdentityConfidence.REJECT, 'no exact normalized title or alias overlap')
    core_overlaps=content_core_titles(result) & external_core_titles(candidate)

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
        kind='core title' if core_overlaps else 'alias-only title'
        return IdentityMatch(IdentityConfidence.HIGH, f'exact {kind} with matching author', overlaps)
    if core_overlaps and year is not None and candidate.start_year is not None:
        return IdentityMatch(IdentityConfidence.HIGH, 'exact core title with compatible year', overlaps)
    if core_overlaps and len(overlaps) >= 2:
        return IdentityMatch(IdentityConfidence.HIGH, 'multiple exact titles including a core title', overlaps)
    if not core_overlaps:
        return IdentityMatch(
            IdentityConfidence.MEDIUM,
            'alias-only title overlap lacks strong independent corroboration', overlaps,
        )

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


def _work_description(candidates):
    return next((str(candidate.description or '').strip() for candidate in candidates if str(candidate.description or '').strip()), '')


def _work_tags(candidates):
    tags = []
    seen = set()
    for candidate in candidates:
        for value in candidate.tags:
            text = ' '.join(str(value or '').split())
            key = normalize_identity_text(text)
            if text and key and key not in seen:
                seen.add(key)
                tags.append(text)
    return tags


def canonical_creator_value(candidates, fallback=''):
    """Use trusted source spelling verbatim; never guess at creator casing."""
    names=canonical_creator_values(candidates)
    return ', '.join(names) if names else str(fallback or '').strip()


def canonical_creator_values(candidates):
    """Return independently trusted creator components in stable order."""
    names = []
    by_key = {}
    for candidate in candidates or ():
        for value in candidate.authors:
            text = ' '.join(str(value or '').split())
            key = normalize_identity_text(text)
            if text and key:
                by_key.setdefault(key,[]).append((str(candidate.service or ''),
                                                  str(candidate.external_id or ''),text))
    for key in sorted(by_key):
        names.append(sorted(by_key[key],key=lambda row:(row[0],row[1],row[2].casefold()))[0][2])
    return tuple(names)


def resolve_canonical_title(candidates, provider_title=''):
    """Choose a canonical title from stable roles and independent-source consensus.

    Provider-title agreement is strongest, followed by primary-title consensus,
    general trusted-service consensus, then the explicit external title role.
    Lexical ordering is used only as a final stability tie-breaker.
    """
    roles=(('primary_title',4),('english_title',3),
           ('romanized_title',2),('native_title',1))
    evidence={}
    for candidate in candidates or ():
        service=str(candidate.service or '')
        for field,role_rank in roles:
            text=' '.join(str(getattr(candidate,field,'') or '').split())
            key=work_title(text)
            if not key:
                continue
            row=evidence.setdefault(key,{'services':set(),'primary':set(),'rows':[]})
            row['services'].add(service)
            if field == 'primary_title':
                row['primary'].add(service)
            row['rows'].append((role_rank,service,str(candidate.external_id or ''),text))
    if not evidence:
        return str(provider_title or '').strip()
    provider_key=work_title(provider_title)
    def score(item):
        key,row=item
        return (int(key == provider_key),len(row['primary']),len(row['services']),
                max(value[0] for value in row['rows']))
    best=max(score(item) for item in evidence.items())
    selected_key=min(key for key,row in evidence.items() if score((key,row)) == best)
    selected=evidence[selected_key]
    representatives=sorted(selected['rows'],key=lambda row:(-row[0],row[1],row[2],row[3].casefold()))
    return representatives[0][3]


def resolve_group_canonical_title(rows, fallback=''):
    """Resolve one final work title without consulting provider order.

    Equivalent-provider canonical presentations vote by normalized title.
    Provider-native agreement breaks equal votes, then existing structured
    external title roles (primary, English, romanized, native). A normalized
    lexical key is the final explicit tie-break. Provider titles are considered
    directly only when no canonical presentation title exists.
    """
    values=[]
    for index,row in enumerate(rows or ()):
        title=' '.join(str(row.get('canonical_title') or '').split())
        if title:
            source=(str(row.get('source_id') or ''),
                    str(row.get('id') or row.get('url') or index))
            values.append((title,source))
    if not values:
        for index,row in enumerate(rows or ()):
            title=' '.join(str(row.get('_provider_native_title') or
                               row.get('title') or '').split())
            if title:
                source=(str(row.get('source_id') or ''),
                        str(row.get('id') or row.get('url') or index))
                values.append((title,source))
    if not values:
        return str(fallback or '').strip()

    evidence={}
    for title,source in values:
        key=work_title(title)
        if not key:
            continue
        bucket=evidence.setdefault(key,{'sources':set(),'texts':set()})
        bucket['sources'].add(source); bucket['texts'].add(title)
    native_support={}
    role_support={}
    role_rank={'primary':4,'english':3,'romanized':2,'romaji':2,'native':1}
    for row in rows or ():
        native=work_title(row.get('_provider_native_title') or row.get('title'))
        if native:
            native_support[native]=native_support.get(native,0)+1
        for original in row.get('structured_titles') or row.get('titles') or ():
            title_row=dict(original) if isinstance(original,dict) else {'title':original}
            key=work_title(title_row.get('title') or title_row.get('text'))
            if not key:
                continue
            classification=str(title_row.get('classification') or '').casefold().strip()
            rank=4 if title_row.get('primary') else role_rank.get(classification,0)
            role_support[key]=max(role_support.get(key,0),rank)

    def score(key):
        bucket=evidence[key]
        return (len(bucket['sources']),native_support.get(key,0),role_support.get(key,0))

    best=max(score(key) for key in evidence)
    selected_key=min(key for key in evidence if score(key) == best)
    # Punctuation-equivalent spellings share a normalized key. Prefer the
    # least-decorated stable spelling, never the first observed spelling.
    return min(evidence[selected_key]['texts'],key=lambda value:(len(value),value.casefold(),value))


def _creator_key(value):
    return creator_comparison_identity(value)


def resolve_canonical_work_facts(groups, overlays=None):
    """Consolidate creator facts only after canonical grouping is confident.

    ``groups`` must have already been created by the conservative identity and
    edition checks. Creator evidence is deliberately not used to make groups.
    """
    overlays=dict(overlays or {})
    facts={}
    for group in groups or ():
        if getattr(group,'confidence','') != 'high':
            continue
        rows=[]
        for candidate in group.results:
            key=(str(candidate.get('source_id') or ''),
                 str(candidate.get('id') or candidate.get('url') or ''))
            row=dict(candidate); row.update(dict(overlays.get(key) or {})); rows.append(row)
        work_ids=tuple(dict.fromkeys(str(row.get('canonical_work_id') or '').strip()
                                     for row in rows if str(row.get('canonical_work_id') or '').strip()))
        external=[]; cached=[]; provider=[]
        for row, candidate in zip(rows,group.results):
            creator=str(row.get('canonical_author') or '').strip()
            creators=tuple(_values(row.get('canonical_creators'))) or ((creator,) if creator else ())
            provenance=str(row.get('canonical_creator_provenance') or '').strip()
            if creators:
                if provenance == 'trusted_external':
                    external.append((creators,'trusted_external'))
                elif provenance != 'provider':
                    cached.append((creators,'cached_canonical'))
            native=str(candidate.get('author') or '').strip()
            if native:
                provider.append(((native,),'provider_consensus'))

        def resolved(values):
            keyed={tuple(sorted(_creator_key(value) for value in creators if _creator_key(value))):
                   (creators,source) for creators,source in values if creators}
            if len(keyed) == 1:
                return next(iter(keyed.values())),False
            return (((),'')),bool(keyed)

        value,conflict=resolved(external)
        if not value[0] and not conflict:
            value,conflict=resolved(cached)
        if not value[0] and not conflict:
            value,conflict=resolved(provider)
        creators,provenance=value
        creator=', '.join(creators)
        creator_keys={_creator_key(value) for value in creators if _creator_key(value)}
        display_key=_creator_key(creator)
        creator_aliases=tuple(dict.fromkeys(
            name for row in rows for name in (
                *(_values(row.get('canonical_creator_aliases'))),
                str(row.get('canonical_author') or '').strip(),
                str(row.get('author') or '').strip(),
            ) if name and (_creator_key(name) in creator_keys or _creator_key(name) == display_key)
        ))
        group_key=tuple(sorted(
            (str(row.get('source_id') or ''),str(row.get('id') or row.get('url') or ''))
            for row in group.results
        ))
        facts[group_key]=CanonicalWorkFacts(
            work_ids[0] if len(work_ids) == 1 else '',
            resolve_group_canonical_title(rows,str(group.display_title or '')),
            creator,provenance,conflict or len(work_ids) > 1,creator_aliases,creators,
        )
    return facts


def propagate_trusted_family_work_facts(rows):
    """Share only agreed high-confidence work facts across exact edition siblings."""
    output=[dict(row or {}) for row in rows or ()]
    families={}
    for row in output:
        family=work_title(row.get('_provider_native_title') or row.get('title'))
        if family:
            families.setdefault(family,[]).append(row)
    for members in families.values():
        trusted=[]
        for row in members:
            work_id=str(row.get('canonical_work_id') or '').strip()
            confidence=str(row.get('_canonical_identity_confidence') or '').casefold()
            if not confidence and (row.get('work_family_id') or row.get('external_ids')):
                confidence='high'
            if work_id and confidence == 'high':
                trusted.append(row)
        work_ids={str(row.get('canonical_work_id') or '').strip() for row in trusted}
        if len(work_ids) != 1:
            continue
        creator_sets=[]
        for row in trusted:
            creators=tuple(_values(row.get('canonical_creators'))) or _values(
                row.get('canonical_author')
            )
            keys=frozenset(_creator_key(value) for value in creators if _creator_key(value))
            if keys:
                creator_sets.append(keys)
        if len(set(creator_sets)) > 1:
            continue
        creator_keys=creator_sets[0] if creator_sets else frozenset()
        contradicted=False
        if creator_keys:
            for row in members:
                offered=tuple(_values(row.get('canonical_creators'))) or _values(
                    row.get('canonical_author') or row.get('author')
                )
                offered_keys={_creator_key(value) for value in offered if _creator_key(value)}
                if offered_keys and not offered_keys & creator_keys:
                    contradicted=True
                    break
        if contradicted:
            continue
        donor=sorted(trusted,key=lambda row:(
            str(row.get('source_id') or ''),str(row.get('id') or row.get('url') or '')
        ))[0]
        aliases=tuple(dict.fromkeys(
            value for row in trusted for value in row.get('canonical_aliases') or () if value
        ))
        creator_aliases=tuple(dict.fromkeys(
            value for row in trusted
            for value in row.get('canonical_creator_aliases') or () if value
        ))
        external_ids={
            key:value for row in trusted for key,value in dict(row.get('external_ids') or {}).items()
        }
        for row in members:
            row.update({
                'canonical_work_id':donor.get('canonical_work_id') or '',
                'canonical_title':donor.get('canonical_title') or '',
                'canonical_author':donor.get('canonical_author') or '',
                'canonical_creators':list(donor.get('canonical_creators') or ()),
                'canonical_creator_provenance':donor.get('canonical_creator_provenance') or '',
                'canonical_creator_aliases':list(creator_aliases),
                'canonical_aliases':list(aliases),
                'external_ids':dict(external_ids),
                '_canonical_identity_confidence':'high',
            })
            for field in ('work_description','work_description_candidates','work_tags'):
                if donor.get(field) not in (None,'',(),[],{}):
                    row[field]=donor[field]
    return tuple(output)


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
        # An overlay can cross explicit edition siblings only after at least
        # one member of their normalized work family has a high-confidence
        # external match. The provider records themselves remain distinct.
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
            row['canonical_work_id'] = '|'.join(sorted(dict.fromkeys(
                f'{candidate.service}:{candidate.external_id}'
                for candidate in inherited if candidate.service and candidate.external_id
            )))
            row['external_authors'] = list(dict.fromkeys(author for candidate in inherited for author in candidate.authors))
            external_creators=canonical_creator_values(inherited)
            external_creator=', '.join(external_creators)
            row['canonical_creators'] = list(external_creators)
            row['canonical_author'] = external_creator or str(row.get('author') or '').strip()
            row['canonical_creator_provenance'] = (
                'trusted_external' if external_creator else ('provider' if row.get('author') else '')
            )
            row['canonical_creator_aliases'] = list(dict.fromkeys(
                value for value in (
                    *(author for candidate in inherited for author in candidate.authors),
                    str(row.get('author') or '').strip(),
                ) if value and (
                    _creator_key(value) in {_creator_key(name) for name in external_creators} or
                    _creator_key(value) == _creator_key(row['canonical_author'])
                )
            ))
            row['canonical_title'] = resolve_canonical_title(
                inherited,str(row.get('title') or '').strip()
            )
            row['canonical_aliases'] = list(dict.fromkeys(
                title for candidate in inherited for title in candidate.titles if title
            ))
            row['work_description'] = _work_description(inherited)
            row['work_description_candidates'] = [
                {
                    'value': str(candidate.description or '').strip(),
                    'source': candidate.service,
                    'source_identity': candidate.external_id,
                    # AniList/Kitsu candidates currently do not carry an
                    # explicit Description-language field. Preserve unknown
                    # rather than guessing from free text.
                    'language': '',
                    'confidence': 'trusted',
                }
                for candidate in inherited if str(candidate.description or '').strip()
            ]
            row['work_tags'] = _work_tags(inherited)
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
