"""Local catalog contract v1. Pure Python; no Qt, Calibre or network imports.

An explicit local catalog offers a mapping; it never grants implicit consent.
Coverage is checked against exact selected acquisition IDs, not number ranges.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

CATALOG_SCHEMA_VERSION = 1
MAX_BYTES = 2 * 1024 * 1024


def _text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('Missing/invalid '+name)
    return value


def validate_catalog(data):
    if not isinstance(data, dict) or type(data.get('catalog_schema_version')) is not int or data['catalog_schema_version'] != 1:
        raise ValueError('Unsupported catalog schema')
    for name in ('catalog_revision', 'generated_at', 'producer'):
        _text(data.get(name), name)
    record = data['record']; work = record['work']; layout = record['layout']
    for name in ('canonical_work_id', 'title', 'edition', 'acquisition_language'):
        _text(work.get(name), name)
    if not isinstance(work.get('external_ids'), dict):
        raise ValueError('Missing external identifier dictionary')
    for name in ('layout_id', 'label', 'publisher', 'market_relation', 'publication_language', 'format', 'evidence_status'):
        _text(layout.get(name), name)
    if record.get('qualification') not in ('verified', 'provisional'):
        raise ValueError('Invalid catalog qualification')
    _text(record.get('qualification_rationale'), 'qualification rationale')
    _text(record.get('record_revision'), 'record revision')
    if record.get('coverage') not in ('partial', 'complete'):
        raise ValueError('Missing explicit coverage')
    for name in ('limitations', 'unresolved_publication_questions', 'unresolved_acquisitions'):
        if not isinstance(record.get(name), list):
            raise ValueError('Missing '+name)
    if record.get('supplementary_identity_status') not in ('none_claimed', 'resolved', 'unresolved'):
        raise ValueError('Missing supplementary identity status')
    evidence = record['evidence']
    if not isinstance(evidence, list) or not evidence:
        raise ValueError('Missing evidence')
    evidence_ids = set()
    for item in evidence:
        key = _text(item.get('evidence_id'), 'evidence ID')
        if key in evidence_ids:
            raise ValueError('Duplicate evidence ID')
        evidence_ids.add(key)
        for name in ('source_url', 'inspected_at', 'locator', 'evidence_type'):
            _text(item.get(name), name)

    def references(item):
        refs = item.get('evidence_refs')
        if not isinstance(refs, list) or not refs or any(ref not in evidence_ids for ref in refs):
            raise ValueError('Missing/unknown supporting evidence')
    references(layout); references(record)
    volumes = {}
    for volume in record['volumes']:
        key = _text(volume.get('volume_id'), 'volume ID')
        number = _text(volume.get('number'), 'volume number')
        if not number.isascii() or not number.isdigit() or str(int(number)) != number:
            raise ValueError('Unsupported volume number')
        if key in volumes or number in [v['number'] for v in volumes.values()]:
            raise ValueError('Ambiguous volume identity')
        _text(volume.get('publication_id'), 'publication volume identity')
        references(volume); volumes[key] = volume
    chapters = {}
    for item in record['memberships']:
        key = _text(item.get('chapter_id'), 'canonical chapter ID')
        if key in chapters or item.get('volume_id') not in volumes:
            raise ValueError('Conflicting/missing chapter membership')
        if item.get('kind') != 'main' or not key.isascii() or not key.isdigit() or str(int(key)) != key:
            raise ValueError('This bridge requires explicit canonical main chapter identities')
        references(item); chapters[key] = item['volume_id']
    for item in record['uncollected']:
        key = _text(item.get('chapter_id'), 'uncollected chapter ID')
        if key in chapters or item.get('volume_id') is not None or item.get('kind') != 'main':
            raise ValueError('Conflicting uncollected membership')
        if not key.isascii() or not key.isdigit() or str(int(key)) != key:
            raise ValueError('Unsupported uncollected identity')
        references(item); chapters[key] = None
    if not chapters:
        raise ValueError('Empty catalog mapping')
    bindings = set()
    for item in record['acquisitions']:
        key = (_text(item.get('provider'), 'provider'), _text(item.get('acquisition_id'), 'acquisition ID'))
        if key in bindings or item.get('chapter_id') not in chapters:
            raise ValueError('Ambiguous/missing provider acquisition identity')
        _text(item.get('provider_chapter'), 'captured provider chapter label')
        if 'provider_record_id' in item:
            _text(item['provider_record_id'], 'captured provider record ID')
        references(item); bindings.add(key)
    for item in record['unresolved_acquisitions']:
        key = (_text(item.get('provider'), 'unresolved provider'), _text(item.get('acquisition_id'), 'unresolved ID'))
        if key in bindings:
            raise ValueError('Acquisition is both resolved and unresolved')
        bindings.add(key); _text(item.get('reason'), 'unresolved identity reason')
    # A qualification flag alone is never proof of verified scope.
    if record['qualification'] == 'verified':
        verification = record.get('verification') or {}
        if (verification.get('scope_approved') is not True or
                verification.get('publication_relationships_verified') is not True or
                verification.get('acquisition_relationships_verified') is not True or
                verification.get('canonical_work_id') != work['canonical_work_id'] or
                verification.get('layout_id') != layout['layout_id']):
            raise ValueError('Verified catalog requires explicit publication/acquisition scope verification')
        references(verification)
        kinds = {e['evidence_type'] for e in evidence if e['evidence_id'] in verification['evidence_refs']}
        if not {'publication_scope_review', 'acquisition_scope_review'} <= kinds:
            raise ValueError('Verified scope lacks separate publication and acquisition review evidence')
    return data


def load_catalog(path):
    path = Path(path)
    with path.open('rb') as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('Catalog exceeds local bridge size limit')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate JSON field')
            result[key] = value
        return result
    data = json.loads(raw.decode('utf-8'), object_pairs_hook=unique)
    validate_catalog(data)
    return data


def acquisition_key(row):
    return (str(row.get('_source_id') or row.get('_acquisition_provider') or ''), str(row.get('id') or ''))


def decide(data, context, rows, live_groups=()):
    """Evaluate exact requested output, retaining every selected acquisition."""
    result = {'decision': 'ineligible', 'reason': '', 'canonical_work_id': None,
        'mapping_source': 'local_catalog', 'qualification': None, 'layout': None,
        'catalog_revision': None, 'supported_relationships': [], 'unresolved_identities': [],
        'missing_required_relationships': [], 'uncertainties': [], 'groups': (),
        'explicit_selection_required': True, 'differences': []}
    try:
        validate_catalog(data)
        record = data['record']; work = record['work']; layout = record['layout']
        result.update(canonical_work_id=work['canonical_work_id'], qualification=record['qualification'],
            layout=deepcopy(layout), catalog_revision=data['catalog_revision'],
            unresolved_identities=deepcopy(record['unresolved_acquisitions']),
            uncertainties=list(record['limitations'])+list(record['unresolved_publication_questions']))
        if context.get('identity_trusted') is not True:
            raise ValueError('Current canonical work identity is not trusted')
        for field in ('canonical_work_id', 'edition', 'acquisition_language'):
            if context.get(field) in (None, '', 'unknown') or context.get(field) != work[field]:
                raise ValueError('Incompatible '+field)
        # Conflicting external identifiers also fail closed; no alias/fuzzy linking.
        for key, value in (context.get('external_ids') or {}).items():
            if key in work['external_ids'] and str(value) != str(work['external_ids'][key]):
                raise ValueError('Conflicting external work identifier')
        unknown = ('', 'unknown', 'unspecified')
        if (str(context.get('layout_id') or '').strip().casefold() in unknown or
                any(layout[field].strip().casefold() in unknown for field in
                    ('layout_id', 'publisher', 'market_relation', 'publication_language', 'format'))):
            raise ValueError('Publication layout is unknown; explicit known layout required')
        if context['layout_id'] != layout['layout_id'] or layout['evidence_status'] not in ('supported', 'owner_approved_secondary_source_fixture', 'verified'):
            raise ValueError('Incompatible/unsupported publication layout')
        bindings = {(r['provider'], r['acquisition_id']): r for r in record['acquisitions']}
        membership = {r['chapter_id']: r['volume_id'] for r in record['memberships']}
        membership.update({r['chapter_id']: None for r in record['uncollected']})
        volumes = {v['volume_id']: v for v in record['volumes']}
        groups = {}; seen = set(); canonical_seen = set(); supported = []
        live = {acquisition_key(r): str(g.get('identifier')) for g in live_groups for r in g.get('chapters') or ()}
        required = tuple(rows)
        if not required:
            raise ValueError('No explicit selected acquisition scope')
        for row in required:
            key = acquisition_key(row)
            if not all(key) or key in seen:
                raise ValueError('Ambiguous provider acquisition identity in selected output')
            seen.add(key); binding = bindings.get(key)
            if not binding:
                result['missing_required_relationships'].append({'provider': key[0], 'acquisition_id': key[1], 'chapter': row.get('chapter')})
                continue
            chapter = binding['chapter_id']
            if chapter in canonical_seen or str(row.get('chapter')) != binding['provider_chapter']:
                raise ValueError('Ambiguous/changed provider-to-canonical identity')
            canonical_seen.add(chapter)
            record_id = binding.get('provider_record_id')
            if record_id is not None and row.get('_provider_record_id') != record_id:
                raise ValueError('Missing/changed provider record ID')
            changed_identity = binding['provider_chapter'] != chapter
            # MangaK uses the reader URL as the adapter ID. A relabeling also
            # requires the captured opaque API ID; a reused URL is insufficient.
            if changed_identity and key[0] == 'mangak' and not record_id:
                raise ValueError('MangaK identity correction requires the captured provider record ID')
            volume_id = membership[chapter]; volume = volumes.get(volume_id)
            number = volume['number'] if volume else 'standalone'
            copied = dict(row); copied['_source_id'] = key[0]
            if changed_identity:
                copied['_provider_chapter'] = binding['provider_chapter']
                copied['_catalog_identity'] = {
                    'provider': key[0], 'acquisition_id': key[1],
                    'provider_record_id': record_id,
                    'provider_chapter': binding['provider_chapter'],
                    'provider_label': row.get('_provider_label', binding['provider_chapter']),
                    'chapter_id': chapter, 'evidence_refs': list(binding['evidence_refs']),
                    'catalog_revision': data['catalog_revision'], 'layout_id': layout['layout_id']}
                copied['chapter'] = chapter
            groups.setdefault(number, []).append(copied)
            supported.append({'provider': key[0], 'acquisition_id': key[1], 'chapter_id': chapter, 'volume_id': volume_id})
            if live.get(key) != number or changed_identity:
                difference = {'chapter_id': chapter, 'live': live.get(key), 'catalog': number}
                if changed_identity:
                    difference['provider_chapter'] = binding['provider_chapter']
                result['differences'].append(difference)
        selected_volumes = {membership[ch] for ch in canonical_seen if membership[ch] is not None}
        for chapter, volume_id in membership.items():
            if volume_id in selected_volumes and chapter not in canonical_seen:
                result['missing_required_relationships'].append({'provider': '', 'acquisition_id': chapter,
                    'chapter': chapter, 'reason': 'Known catalog volume member is outside selected acquisition scope'})
        if result['missing_required_relationships']:
            raise ValueError('Selected output has missing/unresolved canonical relationships; no chapters were dropped')
        provenance = {'mapping_source': 'local_catalog', 'qualification': record['qualification'],
                      'layout_id': layout['layout_id'], 'catalog_revision': data['catalog_revision']}
        output = []
        for number in sorted(groups, key=lambda n: (n == 'standalone', int(n) if n != 'standalone' else 0)):
            output.append({'kind': 'standalone' if number == 'standalone' else 'volume',
                'identifier': number, 'volume': None if number == 'standalone' else float(number),
                'mode': 'unified_volume', 'provenance': 'catalog', 'catalog': dict(provenance),
                'chapters': tuple(sorted(groups[number], key=lambda r: int(str(r['chapter']))))})
        result.update(decision='needs_consent' if record['qualification'] == 'provisional' else 'eligible',
            reason='Supported exact selected subset; explicit Review selection required',
            supported_relationships=supported, groups=tuple(output),
            selection_token=hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest())
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        result.update(decision='ineligible', reason=str(exc), groups=())
    return result


def selected_groups(decision, live_groups, explicit_selection=False):
    """Declining is an exact no-op, including the original object identity."""
    if explicit_selection and decision.get('decision') in ('eligible', 'needs_consent'):
        return deepcopy(decision['groups'])
    return live_groups
