"""Bounded capability/projection diagnostics; never log paths or page contents."""
from collections import Counter
from calibre_plugins.manganana.publication.publication_identity import AcquisitionIdentity, compile_bridge


def evidence_capabilities(bundle):
    """Capabilities describe evidence, not a rank or a claim of completeness."""
    madb=bundle.get('madb') or {}
    catalog_valid=madb.get('status')=='valid' and (madb.get('match') or {}).get('confidence')=='confident'
    return {'madb':{'work_identity':catalog_valid,'bibliographic_volume_coverage':catalog_valid,
            'exact_collected_membership':False,'edition_layout_equivalence':False},
        'wikipedia':{'exact_collected_membership':bool((bundle.get('wikipedia') or {}).get('chapters'))},
        'mangadex_structure':{'exact_collected_membership':bool((bundle.get('mangadex_structure') or {}).get('mappings'))}}


def publication_diagnostics(bundle,manifest,projection):
    runtime=manifest.runtime_publication
    messages=[]
    if evidence_capabilities(bundle)['madb']['bibliographic_volume_coverage']:
        messages.append('Catalog capability: work bibliography; no exact chapter membership or edition/layout equivalence asserted.')
    for source in ('wikipedia','mangadex_structure'):
        row=bundle.get(source) or {};status=str(row.get('status') or 'unavailable')
        qualified=any(c.effective_volume.present and c.effective_volume.source==source for c in projection.chapters)
        # Only structured, public reference reason fields; errors may contain paths.
        reason=str((row.get('match') or {}).get('reason') or row.get('reason') or '')
        reason=' '.join(reason.split())[:160]
        if any(token in reason for token in ('\\',':/','://')):reason='See detailed reference diagnostics.'
        cache=str(row.get('cache_state') or 'uncached')[:40]
        messages.append(f'Publication reference {source}: {status}; cache {cache}; '+('qualified membership' if qualified else 'no applied membership')+(f'; {reason}' if reason else '.'))
    artifact=runtime.get('identity_bridge');count=0
    if artifact:
        index=compile_bridge(artifact);context=runtime.get('identity_acquisition_context') or {}
        count=sum(index.resolve(AcquisitionIdentity.from_row(c.acquisition,c.acquisition_provider,context.get('source_work',''),context.get('language',''))) is not None for c in projection.chapters)
    messages.append('Verified mappings: '+str(runtime.get('identity_bridge_status') or 'disabled')+
        '; origin '+str(runtime.get('identity_bridge_origin') or 'none')+f'; {count} approved exact acquisition associations eligible.')
    categories=Counter(c.effective_volume.source for c in projection.chapters if c.effective_volume.present)
    messages.append('Applied membership: '+(', '.join(f'{k}={v}' for k,v in sorted(categories.items())) or 'none')+'.')
    reasons=Counter()
    for c in projection.unmapped:
        if c.mapping_state=='identity_bridge_conflict':reason='verified identity conflict'
        elif c.canonical_key in runtime.get('unresolved_reference_chapters',()):reason='reference conflict'
        elif c.canonical_key in manifest.ambiguous_chapter_keys:reason='ambiguous chapter identity'
        elif c.publication_state=='UNCOMPILED':reason='uncollected publication episode'
        elif not c.canonical_key:reason='namespace association unavailable'
        else:reason='no compatible membership'
        reasons[reason]+=1
    messages.append(f'Standalone: {len(projection.unmapped)}'+('; '+', '.join(f'{k}={v}' for k,v in sorted(reasons.items())) if reasons else '')+'.')
    return messages
