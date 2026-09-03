"""Provider-neutral search intent, relevance tiers, and canonical ordering."""

from dataclasses import dataclass
from enum import Enum, IntEnum
import math

try:
    from .canonical_identity import edition_classification, edition_identity, group_canonical_results, normalize_identity_text
    from .enrichment_model import EditionClass
except ImportError:
    from canonical_identity import edition_classification, edition_identity, group_canonical_results, normalize_identity_text
    from enrichment_model import EditionClass


class MatchTier(IntEnum):
    PROVIDER_WEAK = 1
    RELATED_EDITION = 2
    ALL_TOKENS = 3
    LEADING_PHRASE = 4
    EXACT_ALIAS = 5
    EXACT_PRIMARY = 6


class AcquisitionFitness(str, Enum):
    DIRECT = 'direct'
    PARTIAL = 'partial'
    FALLBACK_ONLY = 'fallback_only'
    UNKNOWN = 'unknown'
    UNAVAILABLE = 'unavailable'


FITNESS_PRIORITY = {
    AcquisitionFitness.DIRECT: 5,
    AcquisitionFitness.PARTIAL: 4,
    AcquisitionFitness.FALLBACK_ONLY: 3,
    AcquisitionFitness.UNKNOWN: 2,
    AcquisitionFitness.UNAVAILABLE: 1,
}
_PROVIDER_PREFERENCE = {'mangadex': 0, 'mangapill': 1, 'weebcentral': 2}


@dataclass(frozen=True)
class SearchCandidatePresentation:
    raw_result: object
    provider_key: tuple
    provider_name: str
    provider_title: str
    display_title: str
    display_creator: str
    display_rating: str
    canonical_identity: str = ''
    canonical_confidence: str = ''
    canonical_work_id: str = ''
    canonical_title: str = ''
    canonical_creator: str = ''
    canonical_creator_provenance: str = ''
    canonical_creator_conflicted: bool = False
    canonical_creator_aliases: tuple = ()
    canonical_creators: tuple = ()
    trusted_aliases: tuple = ()
    edition: str = 'original'
    fitness: AcquisitionFitness = AcquisitionFitness.UNKNOWN
    qualification_status: str = 'unqualified'
    qualification_chapters: int = 0

    def as_record(self):
        row=dict(self.raw_result or {})
        row['title']=self.display_title
        row['author']=self.display_creator
        row['rating_display']=self.display_rating
        row['_provider_native_title']=self.provider_title
        row['_provider_native_author']=str((self.raw_result or {}).get('author') or '').strip()
        row['_canonical_identity']=self.canonical_identity
        row['_canonical_identity_confidence']=self.canonical_confidence
        row['canonical_work_id']=self.canonical_work_id
        row['work_family_id']=self.canonical_identity
        row['canonical_title']=self.canonical_title
        row['canonical_author']=self.canonical_creator
        row['canonical_creator_provenance']=self.canonical_creator_provenance
        row['canonical_creator_conflicted']=self.canonical_creator_conflicted
        row['canonical_creator_aliases']=list(self.canonical_creator_aliases)
        row['canonical_creators']=list(self.canonical_creators)
        row['canonical_aliases']=list(self.trusted_aliases)
        row['_acquisition_fitness']=self.fitness.value
        row['_qualification_status']=self.qualification_status
        row['_qualification_chapter_count']=self.qualification_chapters
        return row


def _same_creator_identity(first, second):
    left=normalize_identity_text(first)
    right=normalize_identity_text(second)
    return bool(left and right and tuple(sorted(left.split())) == tuple(sorted(right.split())))


def present_search_candidate(raw_result, canonical_overlay=None,
                             fitness=AcquisitionFitness.UNKNOWN,
                             qualification_status='unqualified',
                             qualification_chapters=0):
    """Create display metadata without mutating the provider-native record."""
    raw=raw_result or {}
    overlay=dict(canonical_overlay or {})
    key=provider_record_key(raw) or ('','')
    provider_title=str(raw.get('title') or '').strip()
    canonical_title=str(overlay.get('canonical_title') or raw.get('canonical_title') or '').strip()
    display_title=provider_title or canonical_title or 'Untitled'
    provider_creator=str(raw.get('author') or '').strip()
    creator_conflicted=bool(overlay.get('canonical_creator_conflicted') or raw.get('canonical_creator_conflicted'))
    canonical_creator='' if creator_conflicted else str(
        overlay.get('canonical_author') or raw.get('canonical_author') or ''
    ).strip()
    display_creator=provider_creator
    if canonical_creator and (not provider_creator or _same_creator_identity(provider_creator,canonical_creator)):
        display_creator=canonical_creator
    try:
        fitness=fitness if isinstance(fitness,AcquisitionFitness) else AcquisitionFitness(str(fitness))
    except ValueError:
        fitness=AcquisitionFitness.UNKNOWN
    return SearchCandidatePresentation(
        raw,key,str(raw.get('source_name') or raw.get('source_id') or ''),provider_title,
        display_title,display_creator,
        str(overlay.get('rating_display') or raw.get('rating_display') or ''),
        str(overlay.get('work_family_id') or raw.get('work_family_id') or overlay.get('_canonical_identity') or raw.get('_canonical_identity') or ''),
        'high' if (overlay.get('work_family_id') or raw.get('work_family_id') or
                   overlay.get('external_ids') or raw.get('external_ids')) else '',
        str(overlay.get('canonical_work_id') or raw.get('canonical_work_id') or ''),
        canonical_title,canonical_creator,
        str(overlay.get('canonical_creator_provenance') or raw.get('canonical_creator_provenance') or ''),
        creator_conflicted,
        tuple(overlay.get('canonical_creator_aliases') or raw.get('canonical_creator_aliases') or ()),
        tuple(overlay.get('canonical_creators') or raw.get('canonical_creators') or ()),
        tuple(overlay.get('canonical_aliases') or raw.get('canonical_aliases') or ()),
        edition_identity(raw),fitness,str(qualification_status or 'unqualified'),
        max(0,int(qualification_chapters or 0)),
    )


_COLOR_TOKENS = frozenset({'color', 'colored', 'colour', 'coloured', 'colouring', 'coloring'})
_FAN_TOKENS = frozenset({'fan', 'fanmade'})
_EDITION_DECORATION_TOKENS = _COLOR_TOKENS | _FAN_TOKENS | frozenset({
    'official', 'officially', 'digital', 'full', 'edition', 'comic', 'comics', 'ban',
})


@dataclass(frozen=True)
class QueryIntent:
    normalized: str
    tokens: tuple
    edition_intent: str = ''
    base_tokens: tuple = ()


@dataclass(frozen=True)
class PopularitySignals:
    rating: float = None
    rating_count: int = None
    follows: int = None
    saves: int = None
    comments: int = None
    views: int = None
    provider: str = ''
    normalized: float = None

    @property
    def known(self):
        return any(value is not None for value in (
            self.rating, self.rating_count, self.follows,
            self.saves, self.comments, self.views, self.normalized,
        ))

    @property
    def bounded_score(self):
        """Return a bounded tie-break signal; unknown popularity stays unknown."""
        if not self.known:
            return None
        score = 0.0
        if self.normalized is not None:
            return max(0.0, min(1.0, float(self.normalized)))
        if self.rating is not None:
            count = max(0, int(self.rating_count or 0))
            # Bayesian shrinkage toward a neutral 7/10 with a 250-vote prior.
            weighted = (float(self.rating) * count + 7.0 * 250) / (count + 250)
            score += max(0.0, min(1.0, weighted / 10.0)) * 0.65
        engagement = sum(max(0, int(value or 0)) for value in (
            self.follows, self.saves, self.comments, self.views,
        ))
        if engagement:
            score += min(1.0, math.log1p(engagement) / math.log(1_000_001)) * 0.35
        return min(1.0, score)


@dataclass(frozen=True)
class TitleMatch:
    tier: MatchTier
    matched_title: str
    title_kind: str
    precision: float
    extra_words: int
    edition_preference: int


@dataclass(frozen=True)
class RankedCanonicalResult:
    group: object
    match: TitleMatch
    popularity: PopularitySignals
    sort_key: tuple


@dataclass(frozen=True)
class RankedProviderResult:
    """One visible, independently selectable provider-local record."""
    result: object
    match: TitleMatch
    provider_key: tuple
    sort_key: tuple


def query_intent(query):
    normalized = normalize_identity_text(query)
    tokens = tuple(normalized.split())
    token_set = set(tokens)
    has_color = bool(token_set & _COLOR_TOKENS)
    has_fan = has_color and bool(token_set & _FAN_TOKENS)
    edition = 'fan_color' if has_fan else ('color' if has_color else '')
    base = tuple(token for token in tokens if token not in _COLOR_TOKENS and token not in _FAN_TOKENS)
    return QueryIntent(normalized, tokens, edition, base or tokens)


def _ordered_span(wanted, available):
    positions = []
    start = 0
    for token in wanted:
        try:
            position = available.index(token, start)
        except ValueError:
            return None
        positions.append(position)
        start = position + 1
    return positions[-1] - positions[0] + 1 if positions else 0


def _token_match(query_tokens, title_tokens):
    if not query_tokens or not title_tokens:
        return None
    extra = max(0, len(title_tokens) - len(query_tokens))
    if tuple(title_tokens[:len(query_tokens)]) == tuple(query_tokens):
        if len(query_tokens) > 1 or len(query_tokens[0]) >= 4:
            return MatchTier.LEADING_PHRASE, extra
    wanted = set(query_tokens)
    if not wanted <= set(title_tokens):
        return None
    if len(query_tokens) == 1:
        token = query_tokens[0]
        position = title_tokens.index(token)
        if len(token) < 4 or position > 1 or extra > 9:
            return None
    else:
        span = _ordered_span(query_tokens, title_tokens)
        if span is None or span > len(query_tokens) + 2 or extra > max(3, len(query_tokens) * 2):
            return None
    return MatchTier.ALL_TOKENS, extra


def _edition_preference(intent, result, prefer_colored=False):
    edition = edition_classification(result)
    if intent.edition_intent == 'fan_color':
        return 4 if edition is EditionClass.FAN_COLOR else (2 if edition is EditionClass.OFFICIAL_COLOR else 0)
    if intent.edition_intent == 'color':
        return 4 if edition is EditionClass.OFFICIAL_COLOR else (3 if edition is EditionClass.FAN_COLOR else 0)
    if prefer_colored:
        return 4 if edition is EditionClass.OFFICIAL_COLOR else (3 if edition is EditionClass.FAN_COLOR else (1 if edition is EditionClass.STANDARD else 0))
    return 4 if edition is EditionClass.STANDARD else (3 if edition is EditionClass.UNKNOWN else (2 if edition is EditionClass.OFFICIAL_COLOR else 1))


def _titles(result):
    seen = set()
    rows = []
    for kind, values in (
        ('primary', (result.get('title'),)),
        ('alias', result.get('alternate_titles') or ()),
        ('full', (result.get('full_title'),)),
    ):
        if isinstance(values, str):
            values = (values,)
        for value in values:
            normalized = normalize_identity_text(value)
            if normalized and normalized not in seen:
                seen.add(normalized)
                rows.append((kind, str(value), normalized))
    return rows


def match_result(query, result, prefer_colored=False):
    intent = query if isinstance(query, QueryIntent) else query_intent(query)
    if not intent.tokens:
        return None
    best = None
    edition_preference = _edition_preference(intent, result, prefer_colored)
    for kind, original, normalized in _titles(result or {}):
        title_tokens = tuple(normalized.split())
        work_tokens = tuple(token for token in title_tokens if token not in _EDITION_DECORATION_TOKENS)
        same_work_title = bool(work_tokens and work_tokens == intent.base_tokens)
        if normalized == intent.normalized or (not intent.edition_intent and same_work_title):
            tier = MatchTier.EXACT_PRIMARY if kind == 'primary' else MatchTier.EXACT_ALIAS
            extra = 0
        else:
            token_match = _token_match(intent.tokens, title_tokens)
            if token_match:
                tier, extra = token_match
            elif intent.edition_intent and intent.base_tokens:
                base_normalized = ' '.join(intent.base_tokens)
                if normalized == base_normalized:
                    tier, extra = MatchTier.RELATED_EDITION, 0
                else:
                    base_match = _token_match(intent.base_tokens, title_tokens)
                    if not base_match:
                        continue
                    tier, extra = MatchTier.RELATED_EDITION, base_match[1]
            else:
                continue
        precision = len(intent.tokens) / max(1, len(title_tokens))
        candidate = TitleMatch(tier, original, kind, precision, extra, edition_preference)
        if intent.edition_intent or prefer_colored:
            key = (int(tier), edition_preference, -extra, precision, kind == 'primary')
        else:
            key = (int(tier), -extra, precision, edition_preference, kind == 'primary')
        if best is None or key > best[0]:
            best = (key, candidate)
    return best[1] if best else None


def provider_record_key(result):
    """Return the only identity permitted for visible-result deduplication."""
    row = dict(result or {})
    source_id = str(row.get('source_id') or '').strip()
    provider_id = str(row.get('id') or row.get('url') or '').strip()
    if not source_id or not provider_id:
        return None
    return source_id, provider_id


def _provider_match(query, result, prefer_colored=False):
    """Classify every loadable provider row, including weak local matches."""
    intent = query if isinstance(query, QueryIntent) else query_intent(query)
    matched = match_result(intent, result, prefer_colored)
    if matched is not None:
        return matched
    titles = _titles(result or {})
    if not titles:
        return None
    query_tokens = set(intent.tokens)
    best = None
    for kind, original, normalized in titles:
        title_tokens = tuple(normalized.split())
        overlap = len(query_tokens & set(title_tokens))
        # Tier 2 is a plausible partial relationship. Tier 1 means the
        # provider returned the record but MangaNana sees only weak local text.
        tier = MatchTier.RELATED_EDITION if overlap else MatchTier(1)
        precision = overlap / max(1, len(query_tokens))
        candidate = TitleMatch(
            tier, original, kind, precision,
            max(0, len(title_tokens) - overlap),
            _edition_preference(intent, result, prefer_colored),
        )
        key = (int(tier), precision, candidate.edition_preference, kind == 'primary')
        if best is None or key > best[0]:
            best = (key, candidate)
    return best[1] if best else None


def rank_provider_results(query, results, prefer_colored=False):
    """Rank provider facts permissively without cross-provider collapsing.

    Only malformed identities and exact same-provider duplicates are removed.
    Provider response timing is absent from the sort key.
    """
    unique = {}
    for input_index, value in enumerate(results or ()):
        row = dict(value or {})
        key = provider_record_key(row)
        match = _provider_match(query, row, prefer_colored)
        if key is None or match is None:
            continue
        try:
            provider_order = int(row.get('provider_result_order', row.get('_provider_result_order', input_index)))
        except (TypeError, ValueError):
            provider_order = input_index
        row['_provider_result_order'] = provider_order
        current = unique.get(key)
        if current is None or provider_order < current[0]:
            unique[key] = (provider_order, row, match)

    ranked = []
    for key, (provider_order, row, match) in unique.items():
        try:
            fitness = AcquisitionFitness(str(row.get('_acquisition_fitness') or 'unknown'))
        except ValueError:
            fitness = AcquisitionFitness.UNKNOWN
        canonical_confidence = 1 if row.get('_canonical_identity_confidence') == 'high' else 0
        try:
            known_chapters = max(0, int(row.get('_qualification_chapter_count') or 0))
        except (TypeError, ValueError):
            known_chapters = 0
        provider_preference = _PROVIDER_PREFERENCE.get(key[0].casefold(), len(_PROVIDER_PREFERENCE))
        sort_key = (
            -int(match.tier),
            -int(match.edition_preference),
            -float(match.precision),
            int(match.extra_words),
            -canonical_confidence,
            -FITNESS_PRIORITY[fitness],
            -known_chapters,
            provider_preference,
            provider_order,
            key[0].casefold(),
            key[1].casefold(),
        )
        ranked.append(RankedProviderResult(row, match, key, sort_key))
    return tuple(sorted(ranked, key=lambda value: value.sort_key))


def popularity_signals(result):
    row = dict((result or {}).get('popularity') or {})
    for key in ('rating', 'rating_count', 'follows', 'saves', 'comments', 'views', 'provider', 'normalized'):
        if key not in row and key in (result or {}):
            row[key] = result.get(key)
    allowed = {key: row.get(key) for key in PopularitySignals.__dataclass_fields__}
    return PopularitySignals(**allowed)


def _group_popularity(group):
    known = [popularity_signals(result) for result in group.results]
    known = [signals for signals in known if signals.known]
    if not known:
        return PopularitySignals()
    return max(known, key=lambda signals: signals.bounded_score or 0.0)


def rank_canonical_results(query, results, prefer_colored=False):
    """Gate weak groups, then rank plausible canonical identities by clear tiers."""
    intent = query_intent(query)
    ranked = []
    for group in group_canonical_results(results):
        matches = [match_result(intent, result, prefer_colored) for result in group.results]
        matches = [match for match in matches if match is not None]
        if not matches:
            continue
        if intent.edition_intent or prefer_colored:
            best = max(matches, key=lambda match: (
                int(match.tier), match.edition_preference, -match.extra_words,
                match.precision, match.title_kind == 'primary',
            ))
        else:
            best = max(matches, key=lambda match: (
                int(match.tier), -match.extra_words, match.precision,
                match.edition_preference, match.title_kind == 'primary',
            ))
        popularity = _group_popularity(group)
        popularity_known = 1 if popularity.known else 0
        popularity_score = popularity.bounded_score or 0.0
        structural = (best.extra_words,-best.precision,-best.edition_preference)
        if intent.edition_intent or prefer_colored:
            structural = (-best.edition_preference,best.extra_words,-best.precision)
        sort_key = (-int(best.tier),*structural,
                    0 if best.title_kind == 'primary' else 1,
                    -popularity_known,-popularity_score,
                    normalize_identity_text(group.display_title))
        ranked.append(RankedCanonicalResult(group, best, popularity, sort_key))
    return tuple(sorted(ranked, key=lambda row: row.sort_key))


def filter_relevant_results(query, results):
    """Compatibility helper returning rows from accepted groups in ranked order."""
    return tuple(
        result
        for ranked in rank_canonical_results(query, results)
        for result in ranked.group.results
    )


def relevance_score(query, result):
    """Compatibility score whose tier always dominates lower-level tie-breaks."""
    match = match_result(query, result)
    if match is None:
        return None
    return int(match.tier) * 1000 + match.edition_preference * 100 - match.extra_words
