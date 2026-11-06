"""Presentation-only groups; exact provider records and their rank stay intact."""
from dataclasses import dataclass
from calibre_plugins.manganana.discovery.canonical_identity import (
    normalize_identity_text,
    creator_comparison_identity,
    edition_classification,
)


def provider_key(row):
    return str(row.get('source_id') or ''),str(row.get('id') or row.get('url') or '')


def evidence_key(row):
    # Explicit publication/format qualifiers partition even a shared work ID.
    edition=edition_classification(row).value
    qualifiers=tuple(normalize_identity_text(row.get(k)) for k in
        ('edition','publication_format','publication_type','medium','language','remake_of','publication_identity'))
    work=str(row.get('canonical_work_id') or '')
    confidence=row.get('_canonical_identity_confidence') or row.get('identity_confidence')
    if work and str(confidence).casefold()=='high':
        # Broad Comic/Manga labels describe the medium, not a distinct edition.
        # Atsu supplies Comic where other adapters leave medium unspecified.
        # Keep explicit Webcomic and all publication/layout qualifiers distinct.
        qualifiers=list(qualifiers)
        if qualifiers[3] in ('comic','manga','manhwa','manhua'):qualifiers[3]=''
        if qualifiers[0] in ('original','standard','b w','bw'):qualifiers[0]='standard'
        qualifiers=tuple(qualifiers)
        return ('trusted',work,edition,qualifiers)
    title=normalize_identity_text(row.get('canonical_title') or row.get('title'))
    creator=creator_comparison_identity(row.get('author'))
    year=row.get('year')
    # Similarity, missing creator/year or unknown edition never justify joining.
    if title and creator and year and edition!='unknown':
        return ('corroborated',title,creator,str(year),edition,qualifiers)
    return ('listing',*provider_key(row))


@dataclass
class DiscoveryGroup:
    key: tuple
    title: str
    records: list


def group_records(ranked_records):
    output=[];buckets={}
    for record in ranked_records:
        row=dict(record);key=evidence_key(row);source=provider_key(row)[0]
        bucket=buckets.setdefault(key,[]);candidates=bucket
        if key[0]=='trusted':
            # Partial composite IDs may join only through a shared trusted ID,
            # with no contradiction against ANY existing member. This avoids
            # transitive joins through an ambiguous partial record.
            candidates=[g for g in candidates if all(_compatible_trusted(row,r) for r in g.records)]
            for group in output:
                if group not in candidates and all(_compatible_trusted(row,r) for r in group.records):
                    candidates.append(group)
        group=next((g for g in candidates if all(provider_key(r)[0]!=source for r in g.records)),None)
        if group is None:
            group=DiscoveryGroup((key,provider_key(row)),str(row.get('title') or 'Untitled'),[])
            bucket.append(group);output.append(group)
        group.records.append(row)
    return output


def _compatible_trusted(first,second):
    a,b=evidence_key(first),evidence_key(second)
    if a[0]!='trusted' or b[0]!='trusted' or a[2:]!=b[2:]:return False
    left_external=dict(first.get('external_ids') or {});right_external=dict(second.get('external_ids') or {})
    if any(str(left_external[k])!=str(right_external[k]) for k in left_external.keys() & right_external.keys()
           if left_external[k] and right_external[k]):return False
    if a[1]==b[1]:return True
    def identifiers(value):
        result={}
        for part in value.split('|'):
            service,separator,identity=part.partition(':')
            if not separator or not service or not identity or service in result:return {}
            result[service]=identity
        return result
    left,right=identifiers(a[1]),identifiers(b[1]);shared=left.keys() & right.keys()
    return bool(shared) and all(left[k]==right[k] for k in shared)
