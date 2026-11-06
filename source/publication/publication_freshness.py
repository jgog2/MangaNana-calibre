"""Shared runtime release, curation freshness and publication-state evidence.

Absence of a volume is never release evidence. Only explicit uncollected
records from a complete, compatible reference can establish UNCOMPILED.
"""
from decimal import Decimal
from datetime import date, datetime, timezone
import hashlib
import json
import re
from types import MappingProxyType

from calibre_plugins.manganana.providers.cross_source_fallback import normalize_chapter_number
from calibre_plugins.manganana.metadata.references.wikipedia_identity import wikipedia_work_title_key

WIKIPEDIA_CACHE_CONTRACT = 'wikipedia-structure-v3-collection' 

SPECIAL_KINDS = {'special', 'extra', 'bonus', 'omake', 'prologue', 'epilogue'}


def publication_date(as_of=None):
    """One injectable date boundary; cached source facts are evaluated afresh."""
    if isinstance(as_of, datetime):
        return as_of.date()
    if isinstance(as_of, date):
        return as_of
    if as_of is not None:
        return date.fromisoformat(str(as_of))
    return datetime.now(timezone.utc).date()


def parse_release_date(value):
    """Read a full source date, never a citation access/archive date."""
    text = str(value or '').strip()
    for pattern in ('%Y-%m-%d', '%B %d, %Y', '%d %B %Y', '%Y/%m/%d', '%Y年%m月%d日'):
        try:
            return datetime.strptime(text, pattern).date().isoformat()
        except ValueError:
            pass
    match = re.fullmatch(r'\{\{(?:Start date|Date)\s*\|\s*(\d{4})\s*\|\s*(\d{1,2})\s*\|\s*(\d{1,2})\s*\}\}',text,re.I)
    if match:
        try:
            return date(*map(int,match.groups())).isoformat()
        except ValueError:
            pass
    return ''


def volume_release_state(volume, as_of=None):
    cutoff = publication_date(as_of)
    day = parse_release_date(volume.get('release_date'))
    status = str(volume.get('release_status') or '').casefold()
    if day and date.fromisoformat(day) > cutoff:
        return 'FUTURE'
    if status in ('preorder','pre_order','upcoming','announced','future'):
        # A future date crossing alone cannot override an explicit unavailable status.
        return status.upper()
    if day or status in ('released','available','published'):
        return 'RELEASED'
    return 'LISTED_BUT_NOT_RELEASED'


def source_fingerprints(bundle):
    """Real revisions and semantic source facts; no invented upstream revisions."""
    result = {}
    for source in ('wikipedia','bookwalker','mangadex_structure'):
        row = bundle.get(source) or {}
        if not row:
            continue
        facts = {key:row.get(key) for key in ('cache_contract','cache_identity','parser_version',
            'manga_id','canonical_work_id','edition_profile','match','chapters','volumes','mappings','catalog')}
        claims=row.get('release_claims') or {}
        if isinstance(claims,dict) and claims.get('digest'):
            facts['publication_identity_claim_digest']=claims['digest']
        result[source] = hashlib.sha256(json.dumps(facts,sort_keys=True,default=str).encode()).hexdigest()
    return result


def release_boundary(bundle, as_of=None):
    """Combine trusted bibliography facts without producing chapter membership."""
    cutoff = publication_date(as_of)
    expected_edition = _edition((bundle.get('publication_evidence') or {}).get('edition') or bundle.get('edition'))
    released, future, listed, claims = set(), set(), set(), []
    for source in ('wikipedia','bookwalker'):
        row = bundle.get(source) or {}
        match = row.get('match') or {}
        if source=='bookwalker' and expected_edition and _edition(match.get('edition'))!=expected_edition:
            continue
        if (match.get('confidence') != 'confident' or not match.get('publication_id') or
                row.get('cache_state') == 'last_known_good' or
                row.get('refresh_status') or row.get('refresh_error')):
            continue
        if source == 'wikipedia':
            if (row.get('cache_contract') != WIKIPEDIA_CACHE_CONTRACT or
                    row.get('status') not in ('valid_with_data','valid_complete')):
                continue
        elif (row.get('cache_contract') != 'bookwalker-publication-v5-canonical-evidence' or
              not (row.get('catalog') or {}).get('canonical_complete')):
            continue
        for original in row.get('volumes') or ():
            volume = dict(original)
            key = normalize_chapter_number(volume.get('number'))
            if key is None or Decimal(key) <= 0 or Decimal(key) != Decimal(key).to_integral_value():
                continue
            state = volume_release_state(volume,cutoff)
            claims.append(dict(volume=key,source=source,state=state,
                release_date=volume.get('release_date') or '',
                release_status=volume.get('release_status') or '',
                release_evidence=volume.get('release_evidence') or '',
                publication_id=match['publication_id']))
            (released if state=='RELEASED' else future if state in
                ('FUTURE','UPCOMING','PREORDER','PRE_ORDER','ANNOUNCED') else listed).add(key)
    # Conflicting explicit future/current claims require review; unknown listings
    # alone do not contradict another source's positive release evidence.
    conflicts = released & future
    released -= conflicts
    ordered = sorted(released,key=Decimal)
    complete = bool(ordered and ordered == [str(n) for n in range(1,int(ordered[-1])+1)] and not conflicts)
    return dict(as_of=cutoff.isoformat(),released_volumes=ordered,
        latest_released_volume=ordered[-1] if complete else None,complete=complete,
        future_volumes=sorted(future,key=Decimal),
        listed_unreleased_volumes=sorted(listed-released-future,key=Decimal),
        conflicts=sorted(conflicts,key=Decimal),claims=claims)


def catalog_freshness(patch, live):
    """Sparse fields control only themselves; explicit coverage controls a set."""
    fields = patch.get('fields') or []
    contract = patch.get('coverage_contract') or {}
    complete = bool(patch.get('status')=='matched' and contract.get('complete') is True and
                    contract.get('kind')=='complete_publication_snapshot' and
                    isinstance(contract.get('volumes'),list) and
                    isinstance(contract.get('chapter_identifiers'),list))
    controlled = {(str(r['record_key']),r['field']):r for r in fields if
        r.get('entity')=='chapter' and r.get('verification') in ('REVIEWED','VERIFIED')}
    conflicts = []
    for row in live.get('projection') or ():
        key = normalize_chapter_number(row.get('chapter'))
        for field in ('volume','title','type'):
            curated = controlled.get((key,field))
            source = row.get('_volume_source' if field=='volume' else '_title_source')
            value = row.get('_effective_volume') if field=='volume' else row.get(field)
            if curated and source and value not in (None,'') and str(value)!=str(curated['value']):
                conflicts.append(dict(chapter=key,field=field,curated=curated['value'],live=value,source=source))
    volumes = set((live.get('release_boundary') or {}).get('released_volumes') or ())
    chapters = {normalize_chapter_number(r.get('chapter')) for r in live.get('projection') or ()
        if r.get('_volume_source') in ('wikipedia','mangadex_structure') or
           r.get('_publication_state')=='UNCOMPILED'} - {None}
    extensions_v = sorted(volumes-set(contract.get('volumes') or ()),key=Decimal) if complete else []
    extensions_c = sorted(chapters-set(contract.get('chapter_identifiers') or ()),key=Decimal) if complete else []
    old = patch.get('source_fingerprints') or {}
    current = live.get('source_fingerprints') or {}
    changed = [key for key in old if key in current and old[key]!=current[key]]
    state = ('CONFLICT_REVIEW' if conflicts else 'EXTENSION_AVAILABLE' if extensions_v or extensions_c
             else 'SOURCE_CHANGED' if changed else 'CURRENT')
    return dict(state=state,coverage_kind='complete' if complete else 'sparse' if controlled else
        'identity_only' if patch.get('status')=='matched' else 'absent',
        curated_coverage=contract if complete else None,extension_volumes=extensions_v,
        extension_chapters=extensions_c,changed_sources=changed,conflicts=conflicts,
        source_fingerprints=current,blocking=bool(conflicts))


def _edition(value):
    return {'original': 'standard'}.get(value, value)


def trusted_wikipedia_records(bundle, identity, context):
    """Use the real service's validated work match; reject stale/partial data."""
    wiki = (bundle or {}).get('wikipedia') or {}
    match = wiki.get('match') or {}
    def title_key(value):
        return wikipedia_work_title_key(value)
    work_titles = {title_key(v) for v in (context.get('canonical_title'),
        *(context.get('trusted_aliases') or ()), *(context.get('canonical_aliases') or ())) if v}
    if not (identity.get('trusted') and identity.get('canonical_work_id') and
            identity.get('language') and context.get('shareable') and
            wiki.get('cache_contract') == WIKIPEDIA_CACHE_CONTRACT and
            wiki.get('status') in ('valid_complete', 'valid_with_data') and
            wiki.get('cache_state') != 'last_known_good' and
            not wiki.get('refresh_status') and not wiki.get('refresh_error') and
            match.get('confidence') == 'confident' and
            title_key(match.get('title')) in work_titles and
            _edition(match.get('edition')) == _edition(identity.get('edition'))):
        return []
    collection = wiki.get('collection') or {}
    if any(collection.get(k) for k in ('unsupported_segments', 'failed_segments',
                                      'quarantined_groups', 'conflicts')):
        return []
    result = []
    for row in wiki.get('chapters') or ():
        key = normalize_chapter_number(row.get('number') or row.get('chapter'))
        if (key is not None and row.get('confidence') in ('explicit', 'validated') and
                row.get('source') == 'wikipedia' and row.get('source_page') and
                row.get('source_record_id') and
                row.get('language', identity['language']) == identity['language']):
            result.append(dict(row, key=key))
    return result


def reference_specials(records):
    by_key = {}
    for row in records:
        by_key.setdefault(row['key'], []).append(row)
    return {key: rows[0] for key, rows in by_key.items()
            if all(r.get('kind') in SPECIAL_KINDS for r in rows) and
            len({str(r.get('volume') or '') for r in rows}) == 1}


def ambiguity_diagnostic_index(diagnostics):
    """Immutable, ordered multi-key index; a release conflict keeps every key.

    Each diagnostic occurs once per key, just as in the former OR predicate.
    Missing/invalid chapter fields also retain their None-key behavior.
    """
    def freeze(value):
        if isinstance(value, dict):
            return MappingProxyType({k:freeze(v) for k,v in value.items()})
        if isinstance(value, (list,tuple)):
            return tuple(freeze(v) for v in value)
        return value
    index = {}
    for diagnostic in diagnostics or ():
        keys = {normalize_chapter_number(diagnostic.get('chapter'))}
        keys.update(normalize_chapter_number(k) for k in diagnostic.get('chapters') or ())
        frozen = freeze(diagnostic)
        for key in keys:
            index.setdefault(key, []).append(frozen)
    return MappingProxyType({key:tuple(values) for key,values in index.items()})


def _tail_ambiguity_scope(md, records, special, canonical_keys, rows, labels, release):
    """Exclude only independently resolved, demonstrably irrelevant MD ambiguity.

    Rejected metadata stays rejected. Unknown diagnostics and release-ID identity
    conflicts cannot be treated as harmless volume-only disagreements. Even an
    early chapter blocks if one of its rejected claims reaches the final volume.
    """
    by_key, projected = {}, {}
    for row in records:
        by_key.setdefault(row['key'], []).append(row)
    for row, label in zip(rows, labels):
        projected.setdefault(normalize_chapter_number(row.get('chapter')), []).append((row, label))
    resolved, blocking = [], []
    diagnostics_by_key = ambiguity_diagnostic_index(md.get('integrity_diagnostics'))
    for original in md.get('ambiguous_chapters') or ():
        key = normalize_chapter_number(original)
        proof = by_key.get(key, [])
        diagnostics = diagnostics_by_key.get(key, ())
        volume_claims = [d for d in diagnostics if d.get('reason') == 'contradictory_volume_assignments']
        volume_only = bool(key is not None and
            md.get('integrity_contract') == 'mangadex-aggregate-integrity-v1' and volume_claims and
            all(d.get('reason') in ('contradictory_volume_assignments', 'no_explicit_numeric_membership')
                for d in diagnostics))
        safe = False
        if volume_only and release.get('complete'):
            # A typed, independently evidenced special does not participate in
            # main sequence continuity. Numeric/fractional syntax is not taxonomy.
            if (key in special and key not in canonical_keys and
                    str(special[key].get('volume') or '') in release['released_volumes'] and
                    all(label in ('special', 'recognized_special') for _, label in projected.get(key, []))):
                safe = True
            elif key in canonical_keys and len(projected.get(key, [])) == 1:
                row, label = projected[key][0]
                values = {str(r.get('volume') or '') for r in proof}
                claims = [normalize_chapter_number(v) for d in volume_claims for v in d.get('volumes') or ()]
                try:
                    safe = bool(proof and all(r.get('kind') == 'chapter' for r in proof) and
                        values == {str(row.get('_effective_volume') or '')} and
                        row.get('_volume_source') == 'wikipedia' and label == 'main' and
                        claims and all(v in release['released_volumes'] and
                            Decimal(v) < Decimal(release['latest_released_volume']) for v in claims) and
                        str(row.get('_effective_volume')) in release['released_volumes'] and
                        Decimal(str(row['_effective_volume'])) < Decimal(release['latest_released_volume']))
                except (ValueError, TypeError, ArithmeticError):
                    safe = False
        (resolved if safe else blocking).append(str(original))
    return dict(independently_resolved=resolved, blocking=blocking)


def derive_publication_states(publication):
    """Annotate an automatic projection without changing volume membership."""
    rows = publication.get('projection') or []
    labels = (publication.get('normalization') or {}).get('labels') or []
    records = trusted_wikipedia_records(publication.get('references'),
        publication.get('catalog_identity') or {}, publication.get('context') or {})
    special = reference_specials(records)
    publication['recognized_special_records'] = [dict(row) for row in special.values()]
    acquired = {normalize_chapter_number(row.get('chapter')) for row in rows}
    publication['missing_special_acquisition'] = sorted(set(special) - acquired, key=Decimal)
    reason = 'No complete explicit trailing-uncollected evidence.'
    eligible = set()
    canonical = [(r, label) for r, label in zip(rows, labels) if label == 'main']
    unmapped = [r for r, label in zip(rows, labels)
                if label in ('main', 'special', 'recognized_special', 'provisional') and
                r.get('_effective_volume') in (None, '')]
    wiki = (publication.get('references') or {}).get('wikipedia') or {}
    uncollected = {r['key'] for r in records if r.get('kind') == 'uncollected' and
                   r.get('volume') in (None, '')}
    compiled = [r for r, _ in canonical if r.get('_effective_volume') not in (None, '')]
    candidates = {normalize_chapter_number(r.get('chapter')) for r in unmapped}
    trusted_pairs = {}
    for r in records:
        if r.get('volume') not in (None, '') and r.get('kind') not in SPECIAL_KINDS:
            trusted_pairs.setdefault(r['key'], set()).add(str(r['volume']))
    md = (publication.get('references') or {}).get('mangadex_structure') or {}
    manifest = publication.get('manifest') or {}
    # The manifest has already rejected another work/edition or invalid contract.
    # Its raw diagnostic snapshot is not evidence about this publication.
    md_excluded = any(s.get('source') == 'mangadex_structure' and s.get('status') == 'incompatible'
                      for s in manifest.get('source_states') or ())
    if md_excluded:
        md = {}
    # A mapping claim prevents uncompiled classification even if projection failed.
    claimed = set(trusted_pairs) | {normalize_chapter_number(k) for k, v in
        (md.get('mappings') or {}).items() if v not in (None, '')}
    canonical_keys = {normalize_chapter_number(r.get('chapter')) for r, _ in canonical}
    for c in manifest.get('chapters') or ():
        v = c.get('volume') or {}
        if (c.get('kind') not in SPECIAL_KINDS and v.get('source') in ('wikipedia','mangadex_structure') and
                v.get('confidence') in ('explicit','validated') and v.get('value') not in (None,'') and
                # MangaDex supplies membership, not chapter/special taxonomy.
                # Missing untyped decimals stay acquisition diagnostics; they
                # cannot falsify completeness of the canonical main sequence.
                (v.get('source')!='mangadex_structure' or c['key'] in canonical_keys or
                 Decimal(c['key'])==Decimal(c['key']).to_integral_value())):
            trusted_pairs.setdefault(c['key'],set()).add(str(v['value']))
    claimed.update(c.get('key') for c in manifest.get('chapters') or ()
                   if (c.get('volume') or {}).get('present') or
                   (c.get('volume') or {}).get('value') not in (None, ''))
    release = release_boundary(publication.get('references') or {}, publication.get('as_of'))
    publication['release_boundary'] = release
    released = set(release['released_volumes'])
    if any(not v or v == 'None' for v in released): released = set()
    try:
        release_sequence = sorted(Decimal(v) for v in released)
    except ArithmeticError:
        release_sequence = []
    consecutive_volumes = bool(release_sequence and release_sequence[0] == 1 and
        all(v == v.to_integral_value() for v in release_sequence) and
        all(b-a == 1 for a,b in zip(release_sequence,release_sequence[1:])))
    mapped_volumes = {str(r.get('_effective_volume')) for r in compiled}
    reported = {p.get('reported_total_volumes') for p in publication.get('reported_count_provenance') or ()
                if isinstance(p.get('reported_total_volumes'), int) and p['reported_total_volumes'] > 0}
    # Bibliographic totals may include explicitly announced, unreleased volumes.
    # Account for every numbered volume through the total; an unknown/undated
    # listing or gap cannot excuse missing released structure. Bound the range
    # before constructing it, including for malformed upstream totals.
    known_volumes = released | set(release.get('future_volumes') or ())
    totals_accounted = all(v <= len(released) or
        (v <= len(known_volumes) and all(str(n) in known_volumes for n in range(1,v+1)))
        for v in reported)
    try:
        keys = [Decimal(str(r.get('chapter'))) for r, _ in canonical]
        boundary = max(Decimal(str(r['chapter'])) for r in compiled)
        tail = sorted(Decimal(k) for k in candidates)
        integers = sorted(k for k in keys if k == k.to_integral_value())
        contiguous = bool(integers and integers[0] in (0, 1) and
                          all(b - a == 1 for a, b in zip(integers, integers[1:])))
        suffix = bool(tail and all(k > boundary and k == k.to_integral_value() for k in tail)
                      and tail[0] == int(boundary) + 1 and
                      all(b - a == 1 for a, b in zip(tail, tail[1:])))
        compiled_sequence = [Decimal(str(r['_effective_volume'])) for r in
            sorted(compiled,key=lambda r:Decimal(str(r['chapter'])))]
        ordered = all(b >= a for a,b in zip(compiled_sequence,compiled_sequence[1:]))
    except (ValueError, TypeError, ArithmeticError):
        keys = []
        contiguous = suffix = ordered = False
    ambiguity_scope = _tail_ambiguity_scope(md, records, special, canonical_keys, rows, labels, release)
    ambiguity_scope['excluded_incompatible_reference'] = md_excluded
    no_conflicts = not (release.get('conflicts') or publication.get('conflicting_chapters') or
        manifest.get('ambiguous_chapter_keys') or ambiguity_scope['blocking'])
    # Require the entire known released structure, including missing acquisitions,
    # to reach the projection. Never use a parse success or chapter total alone.
    resolved_pairs = {}
    for r in rows:
        if r.get('_effective_volume') not in (None,''):
            resolved_pairs.setdefault(normalize_chapter_number(r.get('chapter')),set()).add(str(r['_effective_volume']))
    complete_release = bool(consecutive_volumes and released == mapped_volumes and
        trusted_pairs and all(len(v) == 1 for v in trusted_pairs.values()) and
        all(v == resolved_pairs.get(k) for k,v in trusted_pairs.items()) and
        totals_accounted and
        int(md.get('volume_count') or 0) <= len(released))
    if (candidates and None not in candidates and len(keys) == len(set(keys)) and
            candidates <= {normalize_chapter_number(r.get('chapter')) for r, _ in canonical} and
            candidates <= uncollected and not candidates & claimed and
            contiguous and suffix and ordered and no_conflicts and complete_release):
        eligible = candidates
        reason = 'Explicit uncollected suffix after the fully resolved released reference structure.'
    publication['uncompiled_evidence'] = {'status': 'established' if eligible else 'insufficient',
        'reason': reason, 'source': 'wikipedia', 'released_volumes': sorted(released),
        'records': [r for r in records if r['key'] in eligible],
        'candidate_records': [r for r in records if r['key'] in uncollected],
        'ambiguity_scope': ambiguity_scope,
        'checks': dict(contiguous=contiguous, suffix=suffix, ordered=ordered,
                       no_conflicts=no_conflicts, complete_release=complete_release,
                       explicit_uncollected=bool(candidates and candidates <= uncollected)),
        'release_boundary': release}
    for row in rows:
        key = normalize_chapter_number(row.get('chapter'))
        row['_publication_state'] = ('UNCOMPILED' if key in eligible else
            'MAPPED' if row.get('_effective_volume') not in (None, '') else 'UNMAPPED')
    publication['uncompiled_identifiers'] = sorted(eligible, key=Decimal)
    return publication


def state_summary(publication):
    """One derived state summary used by audit, review, and UI consumers."""
    rows = publication.get('projection') or []
    labels = (publication.get('normalization') or {}).get('labels') or []
    included = [r for r, label in zip(rows, labels)
                if label in ('main', 'special', 'recognized_special', 'provisional')]
    uncompiled = [r for r in included if r.get('_publication_state') == 'UNCOMPILED' and
                  r.get('_effective_volume') in (None, '')]
    mapped = [r for r in included if r.get('_effective_volume') not in (None, '')]
    return {'mapped_identifiers': [str(r['chapter']) for r in mapped],
            'uncompiled_identifiers': [str(r['chapter']) for r in uncompiled],
            'uncompiled_chapters': len(uncompiled),
            'unmapped_identifiers': [str(r.get('chapter') or r.get('id')) for r in publication.get('unmapped') or ()],
            'conflict_identifiers': publication.get('conflicting_chapters') or []}


def verified_uncompiled_identifiers(publication):
    """Recheck stored derived claims for central acceptance, not just counts."""
    from copy import deepcopy
    current = state_summary(publication)['uncompiled_identifiers']
    if not current: return []
    automatic = deepcopy(publication.get('automatic', publication))
    derive_publication_states(automatic)
    established = set(automatic['uncompiled_identifiers'])
    return [k for k in current if k in established]
