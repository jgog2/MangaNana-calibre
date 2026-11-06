"""Exact cover metadata for an already-confident MangaDex publication ID."""
from concurrent.futures import CancelledError
from decimal import Decimal
import re
import urllib.parse

from calibre_plugins.manganana.metadata.references.mangadex_structure_reference import MangaDexStructureResolver, _UUID
from calibre_plugins.manganana.providers.mangadex_source import cover_metadata_rank
from calibre_plugins.manganana.discovery.canonical_identity import edition_identity
from calibre_plugins.manganana.publication.publication_manifest import normalize_publication_number, structural_edition_family

CACHE_CONTRACT='mangadex-artwork-v1'
MAX_CATALOG_REQUESTS=4


def exact_cover_catalog(records, manga_id):
    """Prefer Japanese publication artwork; then locale and stable UUID.

    Version/timestamps describe record edits, not edition superiority. Neither
    is used to infer volume identity or choose a supposedly better edition.
    """
    by_volume={}
    for row in records:
        attrs=row.get('attributes') or {};volume=normalize_publication_number(attrs.get('volume'))
        filename=str(attrs.get('fileName') or '');identifier=str(row.get('id') or '')
        related={r.get('id') for r in row.get('relationships') or () if r.get('type')=='manga'}
        if (volume is None or not _UUID.fullmatch(identifier) or
                not re.fullmatch(r'[A-Za-z0-9_.-]+\.(?:jpg|jpeg|png|webp)',filename,re.I) or
                related != {manga_id}):
            continue
        locale=str(attrs.get('locale') or '').casefold()
        url=f'https://uploads.mangadex.org/covers/{manga_id}/{filename}'
        candidate={'volume':volume,'cover_id':identifier,'url':url,'preview_url':url+'.256.jpg',
                   'locale':locale,'source':'mangadex_artwork','confidence':'exact','artwork_type':'volume'}
        rank=cover_metadata_rank(row)
        by_volume.setdefault(volume,[]).append((rank,candidate))
    return [min(candidates,key=lambda pair:pair[0])[1] for _,candidates in sorted(by_volume.items(),key=lambda p:Decimal(p[0]))]


class MangaDexArtworkResolver:
    def __init__(self,cache=None,request_json=None):
        self.cache=cache;self.request_json=request_json or MangaDexStructureResolver._http_json

    def lookup(self,evidence,identity,should_cancel=None,*,catalog=None):
        cancel=should_cancel or (lambda:False);identity=dict(identity or {});row=dict(evidence or {})
        manga_id=str(identity.get('manga_id') or '');work=str(row.get('canonical_work_id') or '')
        edition=edition_identity({'edition':row.get('edition') or row.get('edition_profile')})
        result={'source':'mangadex_artwork','cache_contract':CACHE_CONTRACT,'canonical_work_id':work,
                'manga_id':manga_id,'edition':edition,'status':'unavailable_identity','covers':[],
                'ambiguous_volumes':[],'network':{'requests':0}}
        def check():
            if cancel():raise CancelledError()
        def get(path,params=()):
            check()
            if path not in ('/cover','/manga/'+manga_id):raise ValueError('Not an artwork metadata endpoint')
            url='https://api.mangadex.org'+path+('?' + urllib.parse.urlencode(params) if params else '')
            result['network']['requests']+=1
            value=self.request_json(url);check();return value
        check()
        if (not _UUID.fullmatch(manga_id) or row.get('identity_confidence')!='high' or not work or
                identity.get('canonical_work_id')!=work or
                identity.get('cache_contract')!='mangadex-structure-v1' or
                not structural_edition_family(row.get('edition') or row.get('edition_profile'))):return result
        key=CACHE_CONTRACT+':'+manga_id+':'+edition
        def usable(hit):
            return bool(hit and hit.value.get('cache_contract')==CACHE_CONTRACT and
                        hit.value.get('manga_id')==manga_id and hit.value.get('edition')==edition and
                        hit.value.get('status')=='valid')
        hit=self.cache.get_reference_catalog(key) if self.cache else None
        if usable(hit):return dict(hit.value,canonical_work_id=work,cache_state='hit',network={'requests':0})
        stale=self.cache.get('reference_catalog',key,allow_stale=True) if self.cache else None
        try:
            actual=identity.get('identity_edition')
            if not actual:
                # Migration for Patch 1C pointers: verify edition by known-ID detail,
                # never run another title search and never transfer color artwork blindly.
                detail=get('/manga/'+manga_id)
                data=detail.get('data') or {}
                if data.get('id')!=manga_id:raise ValueError('MangaDex identity mismatch')
                attrs=data.get('attributes') or {}
                titles=tuple((attrs.get('title') or {}).values())+tuple(
                    t for alias in attrs.get('altTitles') or () for t in alias.values())
                if not titles:raise ValueError('Missing title edition evidence')
                actual=edition_identity({'title':' '.join(titles)})
            if actual!=edition:
                result['status']='incompatible_edition';return result
            packet=dict(catalog or {})
            records=packet.get('records')
            if (packet.get('contract')=='mangadex-cover-response-v1' and packet.get('source')=='mangadex'
                    and packet.get('manga_id')==manga_id and packet.get('complete') is True
                    and isinstance(records,list) and len(records)<=400
                    and all(isinstance(r,dict) and _UUID.fullmatch(str(r.get('id') or ''))
                        and {v.get('id')for v in r.get('relationships')or()if v.get('type')=='manga'}=={manga_id}
                        for r in records)
                    and len({r['id']for r in records})==len(records)):
                result.update(status='valid',covers=exact_cover_catalog(records,manga_id),record_count=len(records),
                              cache_state='acquisition_catalog')
                if self.cache:check();self.cache.put_reference_catalog(key,result)
                return result
            records=[];seen=set();offset=0
            for _ in range(MAX_CATALOG_REQUESTS):
                payload=get('/cover',[('manga[]',manga_id),('limit',100),('offset',offset),('order[volume]','asc')])
                if payload.get('result')!='ok' or not isinstance(payload.get('data'),list):raise ValueError('Invalid cover catalog')
                batch=payload['data'];total=int(payload['total'])
                identifiers=[r.get('id') for r in batch]
                if (len(batch)>100 or total<offset+len(batch) or
                        len(identifiers)!=len(set(identifiers)) or any(value in seen for value in identifiers)):
                    raise ValueError('Invalid or repeated cover page')
                seen.update(r.get('id') for r in batch);records.extend(batch);offset+=len(batch)
                if offset>=total:break
                if not batch:raise ValueError('Incomplete cover catalog')
            else:raise ValueError('Cover catalog exceeds bounded pagination')
            result.update(status='valid',covers=exact_cover_catalog(records,manga_id),record_count=len(records),cache_state='refreshed')
            if self.cache:check();self.cache.put_reference_catalog(key,result)
            return result
        except CancelledError:raise
        except Exception:
            if usable(stale):return dict(stale.value,canonical_work_id=work,cache_state='last_known_good',network=result['network'])
            result['status']='transient_failure';return result
