"""Pure, provenance-preserving selection of Atsu parallel acquisitions.

The site's Recommended mode uses API scanlator order. Alternate numbering is
not canonical evidence; independent structure or two other providers may
justify an exact missing acquisition. No special taxonomy is inferred.
"""
from decimal import Decimal
import re

from calibre_plugins.manganana.discovery.canonical_identity import edition_identity, normalize_identity_text
from calibre_plugins.manganana.providers.cross_source_fallback import (
    chapter_identity,
    chapter_identities_match,
    normalize_chapter_number,
)
from calibre_plugins.manganana.publication.chapter_workflow import chapter_sort_key

CONTRACT='atsu-groups-v1'


def recommended_inventory(rows, page, manga_id):
    """Return primary rows carrying the complete alternate inventory once."""
    groups={}
    for row in rows:
        group=row.get('_scanlation_id')
        if not group:return rows
        groups.setdefault(group,[]).append(dict(row))
    if len(groups)<2:return rows
    metadata={}
    if isinstance(page,dict) and str(page.get('id'))==manga_id and page.get('title'):
        scanlators=page.get('scanlators') or []
        metadata={str(s['id']):s for s in scanlators if isinstance(s,dict) and s.get('id')}
        primary=str(scanlators[0].get('id') or '') if scanlators and isinstance(scanlators[0],dict) else ''
        basis='api_recommended_order'
    else:primary='';basis=''
    if primary not in groups:
        # Preserve the earlier complete-union fallback when recommendation
        # metadata is unavailable. Do not infer a default from feed order.
        keys={normalize_chapter_number(r.get('chapter')) for r in rows}
        complete=[g for g,items in groups.items() if None not in keys and len(items)==len(keys)
                  and {normalize_chapter_number(r.get('chapter')) for r in items}==keys]
        if not complete:return rows
        primary=min(complete);basis='complete_union_fallback'
    selected=groups[primary]
    identities=[normalize_chapter_number(r.get('chapter')) for r in selected]
    if None in identities or len(identities)!=len(set(identities)):return rows
    def compatible(group):
        if not metadata:return basis=='complete_union_fallback'
        info=metadata.get(group)
        if not info:return False
        if info.get('mangaId') and str(info['mangaId'])!=manga_id:return False
        if info.get('mangaTitle') and normalize_identity_text(info['mangaTitle'])!=normalize_identity_text(page['title']):return False
        if info.get('edition') and str(info['edition'])!=edition_identity({'title':page['title']}):return False
        return True
    if not compatible(primary):return rows
    alternatives=[]
    for group,items in groups.items():
        for row in items:
            row.update(_atsu_group_role='primary' if group==primary else 'alternate',
                _atsu_group_name=(metadata.get(group) or {}).get('name') or '',
                _atsu_group_compatible=compatible(group))
            if group!=primary:alternatives.append(row)
    selected=sorted(selected,key=chapter_sort_key)
    selected[0]['_atsu_group_inventory']=dict(contract=CONTRACT,primary_group=primary,
        recommendation_basis=basis,series_id=manga_id,edition=edition_identity({'title':(page or {}).get('title') or ''}),
        language='en',alternatives=alternatives,
        groups=[dict(id=g,name=(metadata.get(g) or {}).get('name') or '',count=len(items)) for g,items in groups.items()])
    return selected


def resolve_atsu_acquisition(rows, manifest=None, independent_inventories=()):
    """Recover only independently justified missing records; retain all others."""
    selected=[dict(r) for r in rows or ()]
    envelopes=[r['_atsu_group_inventory'] for r in selected if
               isinstance(r.get('_atsu_group_inventory'),dict) and r['_atsu_group_inventory'].get('contract')==CONTRACT]
    if len(envelopes)!=1:return dict(rows=selected,alternatives=[],raw_count=len(selected),primary_group=None)
    envelope=envelopes[0];alternates=envelope.get('alternatives') or []
    known={}
    if manifest:
        for c in manifest.chapters:
            if (c.key not in manifest.ambiguous_chapter_keys and c.volume.present and
                c.volume.source in ('wikipedia','mangadex_structure','curated_database') and
                c.volume.confidence in ('explicit','validated','reviewed','verified')):
                title=c.title.value if c.title.source in ('wikipedia','mangadex_structure','curated_database') else ''
                if re.fullmatch(r'(?:Chapter|Episode)\s+[\d.]+',str(title or ''),re.I):title=''
                known[c.key]=dict(chapter=c.key,volume=c.volume.value,title=title or '')
        for key in manifest.runtime_publication.get('uncompiled_identifiers') or ():
            known.setdefault(key,dict(chapter=key))
    originals=[r for r in selected if r.get('_atsu_group_role')=='primary']
    keys={normalize_chapter_number(r.get('chapter')) for r in originals}
    integers=sorted(int(Decimal(k)) for k in keys if k is not None and Decimal(k)==Decimal(k).to_integral_value())
    coherent=bool(integers and integers==list(range(integers[0],integers[-1]+1)) and
                  integers[0] in (0,1) and keys<=set(known))
    by_key={normalize_chapter_number(r.get('chapter')):r for r in selected}
    diagnostics=[]
    for original in sorted(alternates,key=chapter_sort_key):
        row=dict(original);key=normalize_chapter_number(row.get('chapter'));identity=chapter_identity(row)
        current=by_key.get(key);recovered=False
        if not row.get('_atsu_group_compatible'):
            classification='incompatible_group';review=True;reason='Group ownership/title/edition is incompatible or unproven.'
        elif current:
            parallel=(row.get('_unit_kind','chapter')==current.get('_unit_kind','chapter') and
                      chapter_identities_match(identity,chapter_identity(current)))
            classification='parallel_release' if parallel else 'conflicting_parallel_release'
            review=not parallel;reason='Alternate release of the selected numeric chapter.' if parallel else 'Parallel releases disagree on explicit acquisition metadata.'
        else:
            choices=[r for r in alternates if r.get('_atsu_group_compatible') and
                     normalize_chapter_number(r.get('chapter'))==key]
            agree=bool(choices and all(chapter_identities_match(chapter_identity(choices[0]),chapter_identity(r))
                                       for r in choices[1:]))
            independent={inv.source_id for inv in independent_inventories or () if
                inv.usable and inv.complete and inv.source_id!='atsu' and
                inv.language==envelope.get('language') and inv.edition==envelope.get('edition') and
                any(chapter_identities_match(identity,chapter_identity(r)) for r in inv.chapter_records or ())}
            trusted=key in known and chapter_identities_match(identity,chapter_identity(known[key]))
            if key is not None and agree and row.get('_unit_kind')!='volume' and (trusted or len(independent)>=2):
                row['_atsu_group_role']='fallback';selected.append(row);by_key[key]=row;recovered=True
                classification='supported_fallback';review=False;reason='Exact independently supported chapter absent from the recommended group.'
            else:
                fractional=key is not None and Decimal(key)!=Decimal(key).to_integral_value()
                bounded=bool(fractional and agree and coherent and str(int(Decimal(key))) in keys and
                             Decimal(key)<max(Decimal(k) for k in keys))
                classification=('conflicting_alternate_identity' if not agree else
                                'alternate_fractional' if fractional else 'unconfirmed_alternate')
                review=not bounded;reason=('Noncanonical alternate numbering within the independently resolved primary sequence.' if bounded
                    else 'Alternate-only identifier lacks independent canonical evidence; retained for review.')
        diagnostics.append(dict(row,classification=classification,requires_review=review,
                                recovered=recovered,reason=reason))
    return dict(rows=sorted(selected,key=chapter_sort_key),alternatives=diagnostics,
        raw_count=len(originals)+len(alternates),primary_group=envelope['primary_group'],
        recommendation_basis=envelope['recommendation_basis'],groups=envelope.get('groups') or [])
