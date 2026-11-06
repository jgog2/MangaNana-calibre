"""Bounded MangaDex metadata reference. No acquisition adapter or page access."""
from concurrent.futures import CancelledError
from decimal import Decimal
import hashlib
import json
import re
import urllib.parse
import urllib.request

from calibre_plugins.manganana.discovery.canonical_identity import normalize_identity_text, edition_identity
from calibre_plugins.manganana.providers.cross_source_fallback import normalize_chapter_number
from calibre_plugins.manganana.publication.publication_manifest import normalize_publication_number, structural_edition_family
from calibre_plugins.manganana.metadata.references.madb_reference import creator_relationship
from calibre_plugins.manganana.providers.source_policy import supported_media
from calibre_plugins.manganana.publication.publication_specials import explicit_special_title, SPECIAL_METADATA_CONTRACT
from calibre_plugins.manganana.publication.publication_identity import structural_claim_inventory, canonical_work_identifiers

CACHE_CONTRACT = 'mangadex-structure-v1'
MAX_SEARCH_TERMS = 3
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
AGGREGATE_INTEGRITY_CONTRACT = 'mangadex-aggregate-integrity-v1'
_UUID = re.compile(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', re.I)


class AggregateIntegrityError(ValueError):
    def __init__(self, message, diagnostics):
        super().__init__(message)
        self.diagnostics = diagnostics


def aggregate_mappings(payload, with_diagnostics=False):
    """Aggregate groups by BOTH explicit volume and chapter, across languages."""
    diagnostics = []
    def malformed(reason, record):
        raise AggregateIntegrityError('Invalid MangaDex aggregate metadata',
                                      diagnostics + [dict(reason=reason, record=record)])
    if not isinstance(payload, dict):
        malformed('invalid_aggregate', payload)
    volumes = payload.get('volumes')
    if payload.get('result') != 'ok' or not isinstance(volumes, (dict, list)):
        malformed('invalid_aggregate', payload)
    assignments = {}
    records = {}
    release_claims = {}
    for volume in (volumes.values() if isinstance(volumes, dict) else volumes):
        if not isinstance(volume, dict):
            malformed('invalid_volume_record', volume)
        if isinstance(volume.get('volume'), (dict, list, tuple)):
            malformed('invalid_volume_label', volume)
        number = normalize_publication_number(volume.get('volume'))
        chapters = volume.get('chapters')
        if not isinstance(chapters, (dict, list)):
            malformed('invalid_chapter_collection', volume)
        for chapter in (chapters.values() if isinstance(chapters, dict) else chapters):
            if not isinstance(chapter, dict):
                malformed('invalid_chapter_record', chapter)
            if isinstance(chapter.get('chapter'), (dict, list, tuple)):
                malformed('invalid_chapter_label', chapter)
            key = normalize_chapter_number(chapter.get('chapter'))
            record = dict(chapter=key, volume=number, original_chapter=chapter.get('chapter'),
                          original_volume=volume.get('volume'), record=dict(chapter))
            others = chapter.get('others') or ()
            if not isinstance(others, (list, tuple)):
                malformed('invalid_release_identifiers', record)
            identifiers = (chapter.get('id'), *others)
            for identifier in identifiers:
                if identifier in (None, ''):
                    continue
                if not isinstance(identifier, str) or not _UUID.fullmatch(identifier):
                    malformed('invalid_release_identifier', record)
                release_claims.setdefault(identifier.casefold(), []).append(record)
            if key is not None:
                records.setdefault(key, []).append(record)
            if key is not None and number is not None:
                assignments.setdefault(key, set()).add(number)
            elif key is None or number is None:
                diagnostics.append(dict(reason='no_explicit_numeric_membership', **record))
    rejected = set()
    for identifier, claims in release_claims.items():
        keys = {r['chapter'] for r in claims if r['chapter'] is not None}
        values = {r['volume'] for r in claims if r['volume'] is not None}
        if len(keys) > 1 or len(values) > 1:
            rejected.update(keys)
            diagnostics.append(dict(reason='conflicting_release_identifier', release_id=identifier,
                                    chapters=sorted(keys, key=Decimal), records=claims))
    for key, values in assignments.items():
        if len(values) > 1:
            diagnostics.append(dict(reason='contradictory_volume_assignments', chapter=key,
                                    volumes=sorted(values, key=Decimal), records=records[key]))
    mappings = {key: next(iter(values)) for key, values in sorted(assignments.items(), key=lambda x:Decimal(x[0]))
                if len(values) == 1 and key not in rejected}
    ambiguous = sorted(rejected | {key for key, values in assignments.items() if len(values) != 1}, key=Decimal)
    return (mappings, ambiguous, diagnostics) if with_diagnostics else (mappings, ambiguous)


def fractional_metadata_ids(aggregate, mappings):
    """Only explicit aggregate chapter IDs; one bounded metadata request."""
    ids={}
    volumes=aggregate.get('volumes') or {}
    for volume in volumes.values() if isinstance(volumes,dict) else volumes:
        chapters=volume.get('chapters') or {}
        for chapter in chapters.values() if isinstance(chapters,dict) else chapters:
            key=normalize_chapter_number(chapter.get('chapter'))
            if key not in mappings or Decimal(key)==Decimal(key).to_integral_value(): continue
            for value in (chapter.get('id'), *(chapter.get('others') or ())):
                if _UUID.fullmatch(str(value or '')): ids[str(value)]=key
    return ids


def special_metadata_records(payload, ids, mappings, manga_id):
    """A title is taxonomy only when every fetched release agrees explicitly."""
    if payload.get('result')!='ok' or not isinstance(payload.get('data'),list):
        raise ValueError('Invalid MangaDex chapter metadata')
    groups={};seen=set()
    for row in payload['data']:
        rid=row.get('id');attrs=row.get('attributes') or {}
        key=normalize_chapter_number(attrs.get('chapter'))
        parents={r.get('id') for r in row.get('relationships') or () if r.get('type')=='manga'}
        if (rid not in ids or key!=ids[rid] or parents!={manga_id}
                or normalize_publication_number(attrs.get('volume'))!=mappings.get(key)):
            continue
        seen.add(rid)
        groups.setdefault(key,[]).append(dict(key=key,kind=explicit_special_title(attrs.get('title')),
            title=attrs.get('title') or '',volume=mappings[key],source='mangadex_structure',
            confidence='explicit',source_record_id=rid,source_page='https://mangadex.org/chapter/'+rid,
            language=attrs.get('translatedLanguage') or '',manga_id=manga_id))
    records=[]
    for key,rows in groups.items():
        expected={rid for rid,k in ids.items() if k==key}
        if not expected<=seen or not all(r['kind'] for r in rows): continue
        kinds={r['kind'] for r in rows}
        chosen=dict(rows[0],kind=next(iter(kinds)) if len(kinds)==1 else 'special',evidence=rows)
        records.append(chosen)
    return sorted(records,key=lambda r:Decimal(r['key']))


def _terms(evidence):
    title = str(evidence.get('canonical_title') or evidence.get('title') or '')
    aliases = sorted(set(evidence.get('canonical_aliases') or ()), key=lambda v:(normalize_identity_text(v),v))
    ordered = [title]
    for native in (True, False):
        ordered.extend(v for v in aliases if bool(re.search(r'[\u3040-\u30ff\u3400-\u9fff]',v)) == native)
    result=[]; seen=set()
    for value in ordered:
        key=normalize_identity_text(value)
        if key and key not in seen:
            result.append(value); seen.add(key)
    return tuple(result[:MAX_SEARCH_TERMS])


class MangaDexStructureResolver:
    def __init__(self, cache=None, request_json=None):
        self.cache = cache
        self.request_json = request_json or self._http_json

    @staticmethod
    def _http_json(url):
        request = urllib.request.Request(url, headers={'User-Agent':'MangaNana publication structure/1', 'Accept':'application/json'})
        with urllib.request.urlopen(request, timeout=12) as response:
            data = response.read(MAX_RESPONSE_BYTES + 1)
        if len(data) > MAX_RESPONSE_BYTES:
            raise ValueError('MangaDex metadata response exceeds bound')
        return json.loads(data)

    def lookup(self, evidence, should_cancel=None):
        row = dict(evidence or {}); cancel = should_cancel or (lambda:False)
        work = str(row.get('canonical_work_id') or '')
        family = structural_edition_family(row.get('edition_profile') or row.get('edition'))
        result = {'source':'mangadex_structure','cache_contract':CACHE_CONTRACT,
                  'canonical_work_id':work,'edition_profile':family,'title':row.get('canonical_title') or row.get('title') or '',
                  'manga_id':'','mappings':{},'ambiguous_chapters':[], 'volume_count':0,
                  'special_metadata_contract':SPECIAL_METADATA_CONTRACT,'special_records':[],
                  'special_metadata_status':'not_run','mapped_chapter_count':0,'status':'unavailable_identity','network':{'requests':0}}
        result.update(integrity_contract=AGGREGATE_INTEGRITY_CONTRACT, integrity_diagnostics=[])
        def check():
            if cancel(): raise CancelledError()
        def get(path, params=()):
            check()
            if path not in ('/manga','/chapter') and not re.fullmatch(r'/manga/'+_UUID.pattern+r'/aggregate', path, re.I):
                raise ValueError('Only title discovery, aggregate and bounded chapter metadata are permitted')
            if result['network']['requests'] >= MAX_SEARCH_TERMS + 2:
                raise ValueError('MangaDex structural request budget exceeded')
            url = 'https://api.mangadex.org'+path
            if params: url += '?' + urllib.parse.urlencode(params)
            result['network']['requests'] += 1
            data = self.request_json(url)
            check()
            return data
        check()
        if not work or row.get('identity_confidence') != 'high' or not family or not supported_media(row):
            result['reason']='Canonical work, comic format, confidence or compatible edition evidence unavailable.'
            return result
        # Language is intentionally absent. Approved color variants share standard numbering.
        key = CACHE_CONTRACT+':'+hashlib.sha256((work+'|'+family).encode()).hexdigest()
        def usable(value):
            return bool(isinstance(value, dict) and value.get('cache_contract') == CACHE_CONTRACT and
                        value.get('canonical_work_id') == work and value.get('edition_profile') == family and
                        value.get('integrity_contract') == AGGREGATE_INTEGRITY_CONTRACT and
                        value.get('status') == 'valid' and _UUID.fullmatch(str(value.get('manga_id') or '')) and
                        value.get('mappings'))
        hit = self.cache.get_reference_structure(key) if self.cache else None
        hints = tuple(sorted(set(str(v) for v in row.get('mangadex_title_ids') or () if _UUID.fullmatch(str(v)))))
        if len(hints) > 1:
            result.update(status='ambiguous',reason='Multiple canonical MangaDex title hints remain.'); return result
        # bounded_out is a successful bounded aggregate evaluation, not a failed
        # metadata fetch. Reuse the fresh partial facts without upgrading their
        # completeness or issuing the prohibited >100-ID chapter request.
        if hit and usable(hit.value) and hit.value.get('special_metadata_contract') == SPECIAL_METADATA_CONTRACT and hit.value.get('special_metadata_status') in ('complete','no_ids','bounded_out') and not hit.value.get('refresh_status') and not hit.value.get('refresh_error') and (not hints or hints[0] == hit.value['manga_id']):
            return dict(hit.value, cache_state='hit', network={'requests':0})
        stale = self.cache.get('reference_structure', key, allow_stale=True) if self.cache else None
        old = dict(stale.value) if stale and usable(stale.value) else None
        if old and hints and old['manga_id'] != hints[0]: old=None
        manga_id = hints[0] if hints else (old['manga_id'] if old else '')
        identity_edition = (edition_identity({'edition':row.get('edition') or row.get('edition_profile')})
                            if hints else (old.get('identity_edition') if old else None))
        try:
            if not manga_id:
                identities = {normalize_identity_text(t) for t in (row.get('canonical_title') or row.get('title'), *(row.get('canonical_aliases') or ())) if t}
                for term in _terms(row):
                    data = get('/manga', [('title',term),('limit',20),('order[relevance]','desc'),('includes[]','author'),('includes[]','artist')])
                    if data.get('result') != 'ok' or not isinstance(data.get('data'),list):
                        raise ValueError('Invalid MangaDex title metadata')
                    candidates = set()
                    for candidate in data['data']:
                        attrs = candidate.get('attributes') or {}
                        titles = tuple((attrs.get('title') or {}).values()) + tuple(t for a in attrs.get('altTitles') or () for t in a.values())
                        if not identities.intersection(normalize_identity_text(t) for t in titles): continue
                        # MangaDex manga metadata is comic media. Reject explicit non-comic formats/adaptations.
                        tags = {str(t).casefold() for tag in attrs.get('tags') or () for t in (tag.get('attributes',{}).get('name') or {}).values()}
                        if tags.intersection({'novel','light novel','doujinshi'}): continue
                        candidate_edition = edition_identity({'title':' '.join(titles)})
                        if structural_edition_family(candidate_edition) != family: continue
                        creators = tuple(rel.get('attributes',{}).get('name') for rel in candidate.get('relationships') or ()
                                         if rel.get('type') in ('author','artist') and rel.get('attributes',{}).get('name'))
                        relationship=creator_relationship(row.get('creators') or (), creators)
                        # Provider consensus may be one combined historical
                        # credit, not a canonical creator list. An explicit
                        # same-service work ID can corroborate that work; a
                        # conflicting ID or trusted creator contradiction cannot.
                        ids=canonical_work_identifiers(work)
                        links=attrs.get('links') or {}
                        known={service:str(links[key]) for service,key in (('anilist','al'),('kitsu','kt'))
                               if links.get(key)}
                        shared=bool(ids and any(known.get(k)==v for k,v in ids.items()))
                        conflict=any(k in known and known[k]!=v for k,v in ids.items())
                        if conflict:continue
                        if relationship=='CONTRADICTION' and not (
                                row.get('creator_provenance')=='provider_consensus' and shared):continue
                        value = str(candidate.get('id') or '')
                        if _UUID.fullmatch(value): candidates.add(value)
                    if len(candidates) > 1:
                        result.update(status='ambiguous',reason='Multiple exact compatible work candidates remain.',candidate_count=len(candidates)); return result
                    if len(candidates) == 1:
                        manga_id = next(iter(candidates))
                        chosen=next(c for c in data['data'] if c.get('id')==manga_id)
                        attributes=chosen.get('attributes') or {}
                        known_titles=tuple((attributes.get('title') or {}).values())+tuple(
                            t for alias in attributes.get('altTitles') or () for t in alias.values())
                        identity_edition=edition_identity({'title':' '.join(known_titles)})
                        break
                if not manga_id:
                    result.update(status='no_match',reason='No exact title, creator and edition compatible candidate found within bounded discovery.'); return result
            result['manga_id']=manga_id
            result['identity_edition']=identity_edition
            aggregate = get('/manga/'+manga_id+'/aggregate')
            mappings, ambiguous, diagnostics = aggregate_mappings(aggregate, with_diagnostics=True)
            result.update(mappings=mappings, ambiguous_chapters=ambiguous,
                          integrity_diagnostics=diagnostics,
                          volume_count=len(set(mappings.values())),mapped_chapter_count=len(mappings),
                          status='valid' if mappings else 'no_structure',cache_state='refreshed')
            ids=fractional_metadata_ids(aggregate,mappings)
            result['release_claims']=structural_claim_inventory(aggregate,manga_id=manga_id)
            result['special_metadata_status']='no_ids' if not ids else 'bounded_out'
            if ids and len(ids)<=100:
                try:
                    payload=get('/chapter',[('ids[]',rid) for rid in sorted(ids)]+[('limit',100)])
                    result['release_claims']=structural_claim_inventory(aggregate,payload,manga_id)
                    result['special_records']=special_metadata_records(payload,ids,mappings,manga_id)
                    result['special_metadata_status']='complete'
                except CancelledError:
                    raise
                except Exception:
                    result['special_metadata_status']='transient_failure'
            if (mappings or ambiguous) and self.cache:
                check(); self.cache.put_reference_structure(key, result)
            return result
        except CancelledError:
            raise
        except AggregateIntegrityError as exc:
            # A demonstrated bad refresh is not a transport failure. Never
            # resurrect previously accepted structure to conceal corruption.
            result.update(status='invalid_structure', integrity_diagnostics=exc.diagnostics)
            if self.cache:
                self.cache.put_reference_structure(key, result)
            return result
        except Exception:
            if old:
                return dict(old, cache_state='last_known_good', network=result['network'], refresh_status='transient_failure')
            result['status']='transient_failure'; return result
