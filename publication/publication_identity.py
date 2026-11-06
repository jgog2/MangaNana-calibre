"""Exact publication identities and reviewed bridge artifact v1.

This contract is independent of catalog_schema_v1.json. No network, Qt, DDK
database, numeric chapter normalization, or implicit alias inference lives here.
"""
from calibre_plugins.manganana.common.plugin_paths import plugin_root
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
import hashlib
import json
import os
import re

CONTRACT = 'publication-identity-bridge-v1'
MAX_BYTES = 2 * 1024 * 1024
MAX_RECORDS = 10000


def canonical_work_identifiers(value):
    """Parse existing trusted work IDs; never infer an ID from a title/number."""
    result={}
    for component in str(value or '').split('|'):
        match=re.fullmatch(r'(anilist|kitsu):([1-9][0-9]*)',component)
        if not match or match[1] in result:return {}
        result[match[1]]=match[2]
    return result


def canonical_work_scope_matches(selected,reviewed):
    """A strict subset of reviewed external IDs identifies the same work.

    Missing another service's ID is not a different manga. Every supplied ID
    must be accounted for; conflicting or unknown IDs never acquire aliases.
    Exact acquisition, edition, layout and language validation still applies.
    """
    if selected==reviewed:return True
    actual=canonical_work_identifiers(selected);approved=canonical_work_identifiers(reviewed)
    return bool(actual and approved and all(approved.get(k)==v for k,v in actual.items()))


def _text(value, name, empty=False):
    if not isinstance(value, str) or (not empty and not value.strip()):
        raise ValueError('Invalid ' + name)
    if value != value.strip() or '*' in value:
        raise ValueError('Non-exact ' + name)
    return value


@dataclass(frozen=True, order=True)
class PublicationIdentity:
    canonical_work: str
    edition: str
    layout: str
    serialization_namespace: str
    episode_token: str

    def __post_init__(self):
        for name, value in asdict(self).items():
            _text(value, name)


@dataclass(frozen=True, order=True)
class AcquisitionIdentity:
    provider: str
    source_work: str
    record_id: str
    url: str
    raw_label: str
    numbering_namespace: str
    language: str

    @classmethod
    def from_row(cls, row, provider, source_work, language):
        # Metadata, source ordering and explicit volumes remain in the original
        # acquisition row. This key does not rewrite or deduplicate that row.
        return cls(str(row.get('_source_id') or row.get('source_id') or provider),
            str(row.get('_source_work') or source_work), str(row.get('id') or ''),
            str(row.get('source_url') or row.get('url') or (row.get('id') if str(row.get('id') or '').startswith('https://') else '') or ''),
            str(row.get('original_label') or (row.get('chapter') if row.get('chapter') is not None else '')),
            str(row.get('numbering_group') or ''),
            str(row.get('language') or row.get('translatedLanguage') or language))


@dataclass(frozen=True)
class BridgeTarget:
    identity: PublicationIdentity
    volume: str
    title: str
    evidence_refs: tuple
    reading_order: object = None


@dataclass(frozen=True)
class BridgeIndex:
    revision: str
    digest: str
    scope: tuple
    bindings: object
    targets: object
    diagnostics: tuple

    def compatible(self, work, edition, language):
        return (canonical_work_scope_matches(work,self.scope[0]) and
                self.scope[1] == edition and self.scope[3] == language)

    def resolve(self, acquisition):
        return self.bindings.get(acquisition)


def validate_bridge(data):
    """Fail closed for malformed or contradictory exports, including pending rows.

    Approval is a reviewed data assertion, never inferred from numbers, titles,
    language or scanlation groups. A producer must verify both relationships.
    """
    if not isinstance(data, dict) or data.get('contract') != CONTRACT:
        raise ValueError('Unsupported publication identity bridge')
    _text(data.get('revision'), 'revision'); _text(data.get('producer'), 'producer')
    scope = data.get('scope')
    if not isinstance(scope, dict): raise ValueError('Missing scope')
    scope_tuple = tuple(_text(scope.get(k), k) for k in ('canonical_work','edition','layout','language'))
    evidence = {}; targets = {}; bindings = {}; diagnostics = []
    for name in ('evidence', 'targets', 'bindings'):
        if (not isinstance(data.get(name), list) or len(data[name]) > MAX_RECORDS or
                any(not isinstance(item,dict) for item in data[name])):
            raise ValueError('Invalid/bounded ' + name)
    for item in data['evidence']:
        eid = _text(item.get('id'), 'evidence ID')
        if eid in evidence: raise ValueError('Duplicate evidence ID')
        for name in ('source_url','revision','locator','inspected_at'):
            _text(item.get(name), name)
        if item.get('authority') not in ('publisher','secondary_index','provider_metadata','reviewed_content'):
            raise ValueError('Unclassified evidence authority')
        evidence[eid] = item

    def review(item):
        state = item.get('status')
        if state not in ('approved','pending','rejected','conflict'):
            raise ValueError('Missing review state')
        refs = item.get('evidence_refs')
        if not isinstance(refs, list) or not refs or any(r not in evidence for r in refs):
            raise ValueError('Missing evidence provenance')
        _text(item.get('revision'), 'record revision')
        if state == 'approved':
            _text(item.get('reviewer'), 'reviewer'); _text(item.get('reviewed_at'), 'review date')
            if item.get('relationship_verified') is not True:
                raise ValueError('Unverified relationship approval')
        else: _text(item.get('reason'), 'pending/rejection/conflict reason')
        return state

    all_targets = {}
    for item in data['targets']:
        tid = _text(item.get('id'), 'target ID')
        if tid in all_targets: raise ValueError('Duplicate target ID')
        identity = PublicationIdentity(**item['identity'])
        if (identity.canonical_work,identity.edition,identity.layout) != scope_tuple[:3]:
            raise ValueError('Target outside work/edition/layout scope')
        volume = item.get('volume')
        if not isinstance(volume, str) or not re.fullmatch(r'(?:0|[1-9]\d*)(?:\.\d+)?',volume):
            raise ValueError('Unsupported explicit volume')
        state = review(item)
        order = item.get('reading_order')
        if order is not None and (type(order) is not int or abs(order) > 1000000):
            raise ValueError('Invalid reviewed reading order')
        target = BridgeTarget(identity, volume, _text(item.get('title',''), 'title',True),tuple(item['evidence_refs']),order)
        all_targets[tid] = (target,state)
        if state == 'approved':
            previous = targets.get(identity)
            if previous and (previous.volume != volume or previous.reading_order != order):
                raise ValueError('Conflicting verified identity membership/order')
            targets[identity] = target
    orders = {}
    for identity,target in targets.items():
        if target.reading_order is not None:
            key = (target.volume,target.reading_order)
            if key in orders and orders[key] != identity:
                raise ValueError('Conflicting reviewed reading order')
            orders[key] = identity
    seen = set()
    for item in data['bindings']:
        aid = AcquisitionIdentity(**item['acquisition'])
        for name,value in asdict(aid).items(): _text(value,name, name in ('numbering_namespace','raw_label','url'))
        if aid.language != scope_tuple[3]: raise ValueError('Binding language outside scope')
        if aid in seen: raise ValueError('Duplicate/conflicting exact acquisition binding')
        seen.add(aid)
        target_id = item.get('target_id')
        if target_id not in all_targets: raise ValueError('Unknown publication target')
        state = review(item)
        if item.get('content_relation') != 'one_to_one':
            if state == 'approved': raise ValueError('Split/merged relationship requires a future contract')
        target,target_state = all_targets[target_id]
        if state == 'approved':
            if target_state != 'approved': raise ValueError('Binding targets an unapproved membership')
            bindings[aid] = target
        else: diagnostics.append((aid.record_id,state,item['reason']))
    encoded = json.dumps(data,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode('utf-8')
    if len(encoded) > MAX_BYTES: raise ValueError('Bridge exceeds size bound')
    return BridgeIndex(data['revision'],hashlib.sha256(encoded).hexdigest(),scope_tuple,
        MappingProxyType(bindings),MappingProxyType(targets),tuple(diagnostics))


@lru_cache(maxsize=8)
def _compiled(encoded):
    return validate_bridge(json.loads(encoded))


def compile_bridge(data):
    return _compiled(json.dumps(data,sort_keys=True,ensure_ascii=False,separators=(',',':')))


PACKAGED_REGISTRY = 'assets/publication_identity/reviewed-registry-v1.json'


def _resource_bytes(name, limit=MAX_BYTES):
    loader=globals().get('get_resources')
    if loader is not None:
        raw=loader(name)
        if not isinstance(raw,bytes):raise ValueError('Missing packaged publication resource')
    else:
        with (plugin_root()/name).open('rb') as stream:raw=stream.read(limit+1)
    if len(raw)>limit:raise ValueError('Packaged publication resource exceeds bound')
    return raw


def _source_stat(name):
    if globals().get('get_resources') is not None:return () # ZIP resources are immutable per loaded plugin.
    try:
        s=(plugin_root()/name).stat()
        return (s.st_size,s.st_mtime_ns,s.st_ctime_ns,s.st_ino)
    except OSError:return ('unavailable',)


@lru_cache(maxsize=4)
def _packaged_registry(source_revision):
    raw=_resource_bytes(PACKAGED_REGISTRY,65536);data=json.loads(raw)
    if (not isinstance(data,dict) or data.get('contract')!='packaged-publication-bridges-v1'
            or not isinstance(data.get('artifacts'),list) or len(data['artifacts'])>32):
        raise ValueError('Unsupported packaged bridge registry')
    _text(data.get('revision'),'registry revision')
    seen=set()
    for entry in data['artifacts']:
        if not isinstance(entry,dict):raise ValueError('Invalid trusted registry entry')
        name=entry.get('path','')
        if (not re.fullmatch(r'assets/publication_identity/[A-Za-z0-9_-]+\.json',name)
                or name in seen or entry.get('status')!='reviewed'
                or not re.fullmatch(r'[a-f0-9]{64}',entry.get('sha256',''))):
            raise ValueError('Invalid trusted registry entry')
        seen.add(name);_text(entry.get('revision'),'artifact revision')
        scope=entry.get('scope') or {}
        for key in ('canonical_work','edition','layout','language'):_text(scope.get(key),key)
    return hashlib.sha256(raw).hexdigest(),data


def bridge_resource_stamp(enabled=False):
    """Cheap generation guard; the bounded file is read/validated in the worker.

    Explicit development sidecars take precedence over the packaged preference.
    Packaged resources are selected only from the trusted package registry.
    """
    path = os.environ.get('MANGAANKA_PUBLICATION_BRIDGE_PATH','')
    if not path:
        if not enabled:return ()
        try:
            digest,registry=_packaged_registry(_source_stat(PACKAGED_REGISTRY))
            return ('packaged',digest,tuple((e['path'],_source_stat(e['path'])) for e in registry['artifacts']))
        except (ValueError,OSError,TypeError,KeyError):return ('packaged','unavailable')
    try:
        stat = Path(path).stat()
        return (path,stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns,stat.st_ino)
    except OSError: return (path,'unavailable')


def load_bridge(stamp,work='',edition='',language=''):
    if not stamp: return None
    if stamp[0]=='packaged':
        if tuple(stamp)!=bridge_resource_stamp(True):raise InterruptedError('Bridge revision changed')
        _,registry=_packaged_registry(_source_stat(PACKAGED_REGISTRY))
        eligible=[]
        for entry in registry['artifacts']:
            scope=entry['scope']
            if (not canonical_work_scope_matches(work,scope['canonical_work']) or
                    (scope['edition'],scope['language'])!=(edition,language)):continue
            raw=_resource_bytes(entry['path'])
            if hashlib.sha256(raw).hexdigest()!=entry['sha256']:raise ValueError('Packaged bridge fingerprint mismatch')
            data=json.loads(raw);index=compile_bridge(data)
            if data['scope']!=scope or index.revision!=entry['revision']:raise ValueError('Packaged bridge registry scope or revision mismatch')
            eligible.append(data)
        if len(eligible)>1:raise ValueError('Multiple packaged bridges claim the same scope')
        if tuple(stamp)!=bridge_resource_stamp(True):raise InterruptedError('Bridge revision changed')
        return eligible[0] if eligible else None
    if tuple(stamp) != bridge_resource_stamp(): raise InterruptedError('Bridge revision changed')
    with Path(stamp[0]).open('rb') as stream: raw = stream.read(MAX_BYTES+1)
    if len(raw)>MAX_BYTES: raise ValueError('Bridge exceeds size bound')
    data=json.loads(raw); compile_bridge(data)
    if tuple(stamp) != bridge_resource_stamp(): raise InterruptedError('Bridge revision changed')
    return data


def structural_claim_inventory(aggregate, metadata=None, manga_id=''):
    """Store shared source facts once; expand exact releases only on demand.

    Repeating an aggregate's full `others` list for every release costs quadratic
    serialized space. The raw response and bounded metadata preserve all facts.
    The digest is a local content identity, not an invented upstream revision.
    """
    facts=dict(contract='mangadex-release-claims-v1',manga_id=manga_id,
               aggregate=aggregate,metadata=metadata or {},status='unclassified')
    facts['digest']=hashlib.sha256(json.dumps(facts,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return facts


def structural_release_claims(aggregate, metadata=None, manga_id=''):
    """Lossless aggregate claims; optional already-fetched metadata, no new HTTP.

    Unclassified release IDs never acquire a namespace from a language/group.
    The caller retains aggregate integrity diagnostics independently.
    """
    details={r['id']:r for r in (metadata or {}).get('data',[]) if isinstance(r,dict) and r.get('id')}
    result=[]; volumes=aggregate.get('volumes') or {}
    for vi,volume in enumerate(volumes.values() if isinstance(volumes,dict) else volumes):
        chapters=volume.get('chapters') or {}
        for ci,chapter in enumerate(chapters.values() if isinstance(chapters,dict) else chapters):
            for rid in (chapter.get('id'),*(chapter.get('others') or ())):
                if not rid: continue
                record=details.get(rid) or {}; attrs=record.get('attributes') or {}
                parents={r.get('id') for r in record.get('relationships') or () if r.get('type')=='manga'}
                metadata_status=('verified_record' if record and parents=={manga_id}
                    and attrs.get('chapter')==chapter.get('chapter') and attrs.get('volume')==volume.get('volume')
                    else 'mismatch' if record else 'not_fetched')
                result.append(dict(provider='mangadex',source_work=manga_id,record_id=rid,
                    url='https://mangadex.org/chapter/'+rid,raw_label=chapter.get('chapter'),
                    volume=volume.get('volume'),title=attrs.get('title'),language=attrs.get('translatedLanguage'),
                    group_ids=[r.get('id') for r in record.get('relationships') or () if r.get('type')=='scanlation_group'],
                    metadata=record,metadata_status=metadata_status,aggregate_record=chapter,source_position=[vi,ci],
                    classification='unresolved'))
    return result


def qualify_structural_claims(claims, index):
    """Classify only exact reviewed release aliases, preserving every raw claim."""
    if isinstance(claims,dict):
        if claims.get('contract')!='mangadex-release-claims-v1':
            raise ValueError('Unsupported structural release claims')
        claims=structural_release_claims(claims['aggregate'],claims.get('metadata'),claims['manga_id'])
    classified=[]; memberships={}
    for claim in claims:
        row=dict(claim)
        aid=AcquisitionIdentity(str(row['provider']),str(row['source_work']),str(row['record_id']),
            str(row['url']),str(row['raw_label']),str(row.get('numbering_namespace') or ''),str(row.get('language') or ''))
        target=index.resolve(aid) if index and row.get('metadata_status')!='mismatch' else None
        if target:
            row.update(publication_identity=asdict(target.identity),classification='verified')
            memberships.setdefault(target.identity,set()).add(str(row.get('volume')))
        classified.append(row)
    conflicts={identity for identity,volumes in memberships.items()
        if len(volumes)>1 or volumes!={index.targets[identity].volume}}
    for row in classified:
        if row.get('publication_identity') and PublicationIdentity(**row['publication_identity']) in conflicts:
            row['classification']='conflict'
    return tuple(classified),frozenset(conflicts)
