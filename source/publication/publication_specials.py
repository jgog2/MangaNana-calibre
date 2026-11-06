"""Exact, scoped publication taxonomy; numbering alone never proves a special."""
from collections import defaultdict
from decimal import Decimal
import re

from calibre_plugins.manganana.providers.cross_source_fallback import normalize_chapter_number
from calibre_plugins.manganana.publication.publication_freshness import SPECIAL_KINDS, trusted_wikipedia_records

SPECIAL_METADATA_CONTRACT = 'mangadex-specials-v1'


def explicit_special_title(title):
    """Read explicit category headings, not incidental words in story titles."""
    text = str(title or '').strip().casefold()
    words = re.fullmatch(r'(bonus(?: chapter)?|extras?(?: chapter)?|omakes?|special(?: chapter)?|prologue|epilogue)'
        r'(?:\s*(?:&|,|and)\s*(extras?|omakes?|bonus(?: chapter)?))*', text)
    if words:
        kinds = {('extra' if w.startswith('extra') else 'omake' if w.startswith('omake') else w.split()[0])
                 for w in re.split(r'\s*(?:&|,|\band\b)\s*', text)}
        return next(iter(kinds)) if len(kinds) == 1 else 'special'
    if re.fullmatch(r'one[- ]shot,?\s+(?:omakes?\s*&\s*)?extras?', text):
        return 'special'  # A bundled supplement; do not claim it is one omake.
    return None


def canonical_special_records(bundle, work_id, edition, language, context):
    """Reuse validated Wikipedia evidence and scoped typed MangaDex records."""
    identity = dict(trusted=bool(context.get('shareable')), canonical_work_id=work_id,
                    edition=edition, language=language)
    rows = trusted_wikipedia_records(bundle, identity, context)
    md = (bundle or {}).get('mangadex_structure') or {}
    standard = {'standard', 'original', 'official_color', 'fan_color'}
    if (md.get('status') == 'valid' and md.get('cache_contract') == 'mangadex-structure-v1'
            and md.get('special_metadata_contract') == SPECIAL_METADATA_CONTRACT
            and md.get('canonical_work_id') == work_id and edition in standard
            and md.get('edition_profile') in ('standard', 'original')
            and md.get('cache_state') != 'last_known_good' and not md.get('refresh_status')):
        rows += [dict(r) for r in md.get('special_records') or () if
                 r.get('source') == 'mangadex_structure' and r.get('confidence') == 'explicit'
                 and r.get('source_record_id') and r.get('source_page')
                 and r.get('key') not in (md.get('ambiguous_chapters') or ())]
    groups = defaultdict(list)
    for row in rows:
        key = normalize_chapter_number(row.get('key') or row.get('number'))
        if key is not None: groups[key].append(dict(row, key=key))
    result = []
    for key, members in groups.items():
        # Explicit main evidence is a contradiction, not another alias.
        if not all(r.get('kind') in SPECIAL_KINDS for r in members): continue
        volumes = {str(r['volume']) for r in members if r.get('volume') not in (None, '')}
        if len(volumes) > 1: continue
        chosen = dict(members[0])
        kinds = {r['kind'] for r in members}
        chosen['kind'] = next(iter(kinds)) if len(kinds) == 1 else 'special'
        chosen['volume'] = next(iter(volumes)) if volumes else ''
        chosen['evidence'] = members
        aliases = {}
        for member in members:
            for alias in member.get('aliases') or ():
                identity = tuple(alias.get(k) for k in ('source','record_id','identifier'))
                if all(identity): aliases[identity] = dict(alias)
        if aliases: chosen['aliases'] = list(aliases.values())
        result.append(chosen)
    return sorted(result, key=lambda r: Decimal(r['key']))


def canonical_publication_records(bundle, work_id, edition, language, context):
    """Exact current identities, independent of whether volume membership exists.

    Structure may disagree while the chapter identity agrees. Internal source
    ambiguity and contradictory main/special taxonomy cannot establish identity.
    This does not derive new identifiers from ranges or adjacent chapters.
    """
    # Import locally: the manifest already consumes this taxonomy module.
    from calibre_plugins.manganana.publication.publication_manifest import normalize_publication_number, structural_edition_family
    identity = dict(trusted=bool(context.get('shareable') and
        context.get('canonical_work_id') == work_id), canonical_work_id=work_id,
        edition=edition, language=language)
    if context.get('canonical_work_id') and context['canonical_work_id'] != work_id:
        return []
    wiki = trusted_wikipedia_records(bundle, identity, context)
    by_key = defaultdict(list)
    for row in wiki:
        by_key[row['key']].append(row)
    records = []
    taxonomy = defaultdict(set)
    for key, rows in by_key.items():
        taxonomy[key].update('special' if r.get('kind') in SPECIAL_KINDS else
                             'main' if r.get('kind') in ('chapter','uncollected') else 'unknown' for r in rows)
        volumes = {normalize_publication_number(r.get('volume')) for r in rows} - {None}
        if taxonomy[key] == {'main'} and len(volumes) <= 1:
            records.extend(dict(r) for r in rows)
    md = (bundle or {}).get('mangadex_structure') or {}
    if (md.get('status') == 'valid' and md.get('cache_contract') == 'mangadex-structure-v1'
            and md.get('canonical_work_id') == work_id and structural_edition_family(edition)
            and structural_edition_family(md.get('edition_profile')) == structural_edition_family(edition)
            and md.get('manga_id') and md.get('cache_state') != 'last_known_good'
            and not md.get('refresh_status') and not md.get('refresh_error')):
        ambiguous = {normalize_chapter_number(k) for k in md.get('ambiguous_chapters') or ()}
        typed = defaultdict(set)
        for row in md.get('special_records') or ():
            key = normalize_chapter_number(row.get('key'))
            if key is not None:
                typed[key].add('special' if row.get('kind') in SPECIAL_KINDS else 'unknown')
        for number, volume in (md.get('mappings') or {}).items():
            key = normalize_chapter_number(number)
            volume = normalize_publication_number(volume)
            if key is None or volume is None or key in ambiguous: continue
            if typed[key] or 'special' in taxonomy[key]:
                taxonomy[key].update(typed[key]); continue
            taxonomy[key].add('main')
            records.append(dict(key=key, kind='chapter', volume=volume, source='mangadex_structure',
                confidence='explicit', source_record_id=md['manga_id'],
                source_page='https://mangadex.org/title/'+str(md['manga_id']),
                language_basis='shared structural numbering', canonical_work_id=work_id))
    special_bundle = dict(bundle or {})
    if not identity['trusted']:
        special_bundle.pop('wikipedia', None)
    specials = canonical_special_records(special_bundle, work_id, edition, language, context)
    for row in specials:
        taxonomy[row['key']].add('special')
    records = [r for r in records if taxonomy[r['key']] == {'main'}]
    records.extend(r for r in specials if taxonomy[r['key']] == {'special'})
    return sorted(records, key=lambda r: Decimal(r['key']))


def match_special(row, records, provider=''):
    """Different labels require an explicit link to this exact acquisition ID."""
    key = normalize_chapter_number(row.get('chapter'))
    source = row.get('_source_id') or row.get('source_id') or provider
    matches = []
    for record in records or ():
        exact = key is not None and key == record['key']
        linked = any(a.get('source') == source and a.get('record_id') == row.get('id')
                     and row.get('id') and str(a.get('identifier')) == str(row.get('chapter'))
                     for a in record.get('aliases') or ())
        if exact or linked: matches.append(record)
    return matches[0] if len(matches) == 1 else None


def inventory_coverage(inventory, specials=()):
    """Compare unique confirmed units; unknown fractions cannot buy coverage."""
    rows = inventory.chapter_records or ()
    if not rows:
        # Legacy count-only inventories have no finer evidence to inspect.
        return dict(main=inventory.chapter_count, specials=0, unresolved=0, raw=inventory.chapter_count)
    main, special, unknown = defaultdict(set), set(), set()
    for index, row in enumerate(rows):
        if row.get('_unit_kind') == 'volume': continue
        key = normalize_chapter_number(row.get('chapter'))
        proof = match_special(row, specials, inventory.source_id)
        if proof:
            special.add(proof['key'])
        elif (key is not None and Decimal(key) == Decimal(key).to_integral_value()
              and str(row.get('type') or row.get('chapter_type') or '').casefold() not in SPECIAL_KINDS):
            # Explicit native volumes may restart chapter numbering.
            main[key].add(normalize_chapter_number(row.get('volume')) or '')
        else: unknown.add(key or str(row.get('id') or index))
    return dict(main=sum(max(1,len(volumes-{''})) for volumes in main.values()), specials=len(special), unresolved=len(unknown), raw=len(rows))
