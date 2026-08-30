"""Provider-neutral search intent, relevance tiers, and canonical ordering."""

from dataclasses import dataclass
from enum import IntEnum
import math

try:
    from .canonical_identity import edition_identity, group_canonical_results, normalize_identity_text
except ImportError:
    from canonical_identity import edition_identity, group_canonical_results, normalize_identity_text


class MatchTier(IntEnum):
    RELATED_EDITION = 2
    ALL_TOKENS = 3
    LEADING_PHRASE = 4
    EXACT_ALIAS = 5
    EXACT_PRIMARY = 6


_COLOR_TOKENS = frozenset({'color', 'colored', 'colour', 'coloured', 'colouring', 'coloring'})
_FAN_TOKENS = frozenset({'fan', 'fanmade'})


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

    @property
    def known(self):
        return any(value is not None for value in (
            self.rating, self.rating_count, self.follows,
            self.saves, self.comments, self.views,
        ))

    @property
    def bounded_score(self):
        """Return a bounded tie-break signal; unknown popularity stays unknown."""
        if not self.known:
            return None
        score = 0.0
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


def _edition_preference(intent, result):
    edition = edition_identity(result)
    if intent.edition_intent == 'fan_color':
        return 3 if edition == 'fan_color' else 0
    if intent.edition_intent == 'color':
        return 3 if edition == 'official_color' else (2 if edition == 'fan_color' else 0)
    return 3 if edition == 'original' else (1 if edition == 'official_color' else 0)


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


def match_result(query, result):
    intent = query if isinstance(query, QueryIntent) else query_intent(query)
    if not intent.tokens:
        return None
    best = None
    edition_preference = _edition_preference(intent, result)
    for kind, original, normalized in _titles(result or {}):
        title_tokens = tuple(normalized.split())
        if normalized == intent.normalized:
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
        key = (int(tier), edition_preference, precision, -extra, kind == 'primary')
        if best is None or key > best[0]:
            best = (key, candidate)
    return best[1] if best else None


def popularity_signals(result):
    row = dict((result or {}).get('popularity') or {})
    for key in ('rating', 'rating_count', 'follows', 'saves', 'comments', 'views', 'provider'):
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


def rank_canonical_results(query, results):
    """Gate weak groups, then rank plausible canonical identities by clear tiers."""
    intent = query_intent(query)
    ranked = []
    for group in group_canonical_results(results):
        matches = [match_result(intent, result) for result in group.results]
        matches = [match for match in matches if match is not None]
        if not matches:
            continue
        best = max(matches, key=lambda match: (
            int(match.tier), match.edition_preference, match.precision,
            -match.extra_words, match.title_kind == 'primary',
        ))
        popularity = _group_popularity(group)
        popularity_known = 1 if popularity.known else 0
        popularity_score = popularity.bounded_score or 0.0
        sort_key = (
            -int(best.tier), -best.edition_preference, best.extra_words,
            -best.precision, 0 if best.title_kind == 'primary' else 1,
            -popularity_known, -popularity_score,
            normalize_identity_text(group.display_title),
        )
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
