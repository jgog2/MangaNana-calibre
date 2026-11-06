"""Pure generation-bound publication preparation; no Qt or network ownership."""
from dataclasses import dataclass
from copy import deepcopy
import hashlib
import json
import pickle
import time
from datetime import date
from threading import RLock
from calibre_plugins.manganana.common.bounded_cache import BoundedCache
from calibre_plugins.manganana.publication.publication_manifest import PublicationManifestBuilder, build_publication_projection
from calibre_plugins.manganana.publication.unified_volume import build_unified_volume_plan
from calibre_plugins.manganana.publication.publication_identity import (
    bridge_resource_stamp,
    load_bridge,
    compile_bridge,
)


def presentation_identity(inputs):
    """Bind every preparation input, including contracts/evidence via the bundle.

    Runtime evidence is scoped to this worker invocation; never persist derived
    results by title. The caller also checks request and selection generations.
    """
    def canonical(value):
        # Native cover maps legitimately mix None and numeric volume keys.
        # Encode key types rather than sorting incomparable keys or merging
        # a numeric key with its textual spelling.
        if isinstance(value,dict):
            return {'mapping':sorted([[type(k).__name__,repr(k),canonical(v)] for k,v in value.items()],key=lambda row:row[:2])}
        if isinstance(value,(list,tuple)):
            return [canonical(v) for v in value]
        return value
    return hashlib.sha256(json.dumps(canonical(inputs),sort_keys=True,default=str,
        ensure_ascii=False,separators=(',',':')).encode('utf-8')).hexdigest()


@dataclass(frozen=True)
class PreparedPublication:
    input_identity: str
    payload: bytes

    def materialize(self):
        # Only this module's in-process worker creates these bytes. No external
        # file/cache/network input is ever unpickled. Consumers own fresh copies.
        return pickle.loads(self.payload)


class PublicationPreparationCache:
    """Session-only exact-input memo, after current reference qualification.

    Retain immutable worker-produced bytes, not mutable manifests or Qt objects.
    Every acquisition, evidence, edition, bridge and mode input participates.
    """
    def __init__(self, clock=time.monotonic, max_bytes=32*1024*1024):
        self.clock=clock
        self.values=BoundedCache(max_bytes,16,lambda row:len(row[1].payload)+256)
        self.lock=RLock()
        self.hits=self.misses=0

    def prepare(self, inputs, bundle, cancelled=lambda:False):
        if cancelled():raise InterruptedError('Publication selection changed')
        key=presentation_identity((inputs,bundle,date.today().isoformat()))
        with self.lock:
            row=self.values.get(key)
            if row and 0 <= self.clock()-row[0] < 300:
                self.hits+=1
                return row[1]
            if row:self.values.pop(key,None)
            self.misses+=1
        result=prepare_publication(inputs,bundle,cancelled)
        if cancelled():raise InterruptedError('Publication selection changed')
        if not bundle.get('errors'):
            with self.lock:self.values[key]=(self.clock(),result)
        return result


def prepare_publication(inputs, bundle, cancelled=lambda:False):
    """Perform the former final callback and projection on plain Python data."""
    inputs=deepcopy(inputs);bundle=deepcopy(bundle)
    def check():
        if cancelled():raise InterruptedError('Publication selection changed')
    check()
    work=dict(inputs['work'])
    evidence=bundle.get('publication_evidence') or {}
    work['publication_context']=dict(evidence,
        shareable=bool(evidence.get('identity_confidence')=='high' and
                       evidence.get('canonical_work_id')==work['canonical_identity']),
        canonical_title=evidence.get('title') or '',trusted_aliases=evidence.get('aliases') or ())
    builder=PublicationManifestBuilder(work,inputs['edition'],existing=inputs.get('existing'))
    rows=inputs['chapters'];source=inputs['source_id']
    errors=bundle.get('errors') or {}
    wiki=bundle.get('wikipedia') or ({'status':'transient_failure','error':errors['wikipedia']} if errors.get('wikipedia') else {})
    book=bundle.get('bookwalker') or ({'status':'transient_failure','error':errors['bookwalker']} if errors.get('bookwalker') else {})
    builder.apply_provider_inventory(rows,source)
    builder.apply_madb(bundle.get('madb')).apply_mangadex_structure(bundle.get('mangadex_structure')).apply_wikipedia(wiki)
    check()
    builder.apply_provider_covers(inputs['covers'],source)
    builder.apply_mangadex_artwork(bundle.get('mangadex_artwork')).apply_bookwalker(book).apply_google_books(bundle.get('google_books')).apply_enrichment(inputs['enrichment'])
    manifest=builder.build(inputs['language'])
    check()
    # Preserve the original promotion/reseed semantics, including curated anchors
    # and provider-explicit membership. This is no longer performed in Qt.
    projected_builder=PublicationManifestBuilder(work,inputs['edition'],existing=manifest)
    by_source={}
    for row in rows:by_source.setdefault(str(row.get('_source_id') or source),[]).append(row)
    for sid,source_rows in by_source.items():projected_builder.apply_provider_inventory(source_rows,sid)
    projected_manifest=projected_builder.build(inputs['language'])
    bridge_state={'identity_bridge_status':'disabled','identity_bridge_origin':'none'}
    for snapshot in (manifest,projected_manifest):
        for key in tuple(snapshot.runtime_publication):
            if key.startswith('identity_bridge') or key in ('identity_acquisition_context','identity_reference_claims'):
                snapshot.runtime_publication.pop(key,None)
    stamp=inputs.get('identity_bridge_stamp',())
    if stamp:
        try:
            artifact=load_bridge(stamp,work['canonical_identity'],inputs['edition'],inputs['language'])
            index=compile_bridge(artifact) if artifact else None
            bridge_state.update(identity_bridge_origin='packaged' if stamp[0]=='packaged' else 'explicit_sidecar',
                                identity_bridge_status='scope_not_available')
            if index and index.compatible(work['canonical_identity'],inputs['edition'],inputs['language']):
                bridge_state.update(identity_bridge=artifact,
                    identity_bridge_status='eligible',identity_bridge_revision=index.revision,
                    identity_bridge_digest=index.digest,
                    identity_acquisition_context=dict(source_work=inputs['source_url'],language=inputs['language']),
                    identity_reference_claims=(bundle.get('mangadex_structure') or {}).get('release_claims') or ())
            elif index:
                bridge_state['identity_bridge_error']='Bridge scope does not match selected work, edition or language'
        except InterruptedError:
            raise
        except (ValueError,OSError,KeyError,TypeError) as exc:
            # A bad optional export never destroys a selectable native inventory.
            bridge_state.update(identity_bridge_status='invalid',identity_bridge_error='Optional publication bridge failed validation; legacy inventory retained.')
    for snapshot in (manifest,projected_manifest):
        snapshot.runtime_publication.update(deepcopy(bridge_state))
    if tuple(stamp) != bridge_resource_stamp(bool(inputs.get('verified_publication_mappings',False))):
        raise InterruptedError('Bridge revision changed')
    projection=build_publication_projection(rows,projected_manifest,source,source)
    plan=build_unified_volume_plan(inputs.get('native_plan'),rows,projection,source,inputs['source_name']) if inputs['mode']=='volume' else None
    check()
    return PreparedPublication(presentation_identity(inputs),pickle.dumps(
        (manifest,projected_manifest,projection,plan),protocol=pickle.HIGHEST_PROTOCOL))
