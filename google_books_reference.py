"""Bounded English-only Google Books exact-volume artwork qualification."""

from dataclasses import asdict, dataclass
from enum import Enum
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
import re
import threading
import urllib.error
import urllib.parse
import urllib.request

try:
    from .canonical_identity import (
        creator_comparison_identity, creator_query_variants, normalize_identity_text,
    )
except ImportError:
    from canonical_identity import (
        creator_comparison_identity, creator_query_variants, normalize_identity_text,
    )


BASE_URL = 'https://www.googleapis.com/books/v1/volumes'
CACHE_CONTRACT = 'google-books-artwork-v2'
DETAIL_CACHE_CONTRACT = 'google-books-volume-detail-v1'
MAX_BROAD_RESULTS = 40
MAX_TARGETED_QUERIES = 6
MAX_DISCOVERY_QUERIES = 6
MAX_TOTAL_QUERIES = 10
_VOLUME = re.compile(
    r'(?:,?\s*(?:vol(?:ume)?\.?|book)\s+)(\d+(?:\.\d+)?)(?=\s*(?::|[-–—]|$))', re.I,
)
_COLLECTION = re.compile(r'\b(?:omnibus|3[ -]?in[ -]?1|box\s*set)\b', re.I)
_ALTERNATE = re.compile(r'\b(?:deluxe|collector(?:\'s)? edition|library edition|black edition|limited edition)\b', re.I)
_NOVEL = re.compile(r'\b(?:novel|guidebook|character book|art of)\b', re.I)
_SPINOFF = re.compile(r'\b(?:before the fall|buddy stories|lost girls|junior high)\b', re.I)


class Classification(str, Enum):
    EXACT_STANDARD = 'EXACT_STANDARD'
    EXACT_STANDARD_PREORDER = 'EXACT_STANDARD_PREORDER'
    EXACT_STANDARD_COVERLESS = 'EXACT_STANDARD_COVERLESS'
    OMNIBUS_COLLECTION = 'OMNIBUS_COLLECTION'
    ALTERNATE_EDITION = 'ALTERNATE_EDITION'
    BOX_SET = 'BOX_SET'
    SPINOFF = 'SPINOFF'
    NOVEL_GUIDEBOOK = 'NOVEL_GUIDEBOOK'
    FOREIGN_LANGUAGE = 'FOREIGN_LANGUAGE'
    AMBIGUOUS = 'AMBIGUOUS'
    UNRELATED = 'UNRELATED'


@dataclass(frozen=True)
class GoogleManifestation:
    google_volume_id: str
    title: str
    subtitle: str
    authors: tuple
    publisher: str
    language: str
    published_date: str
    isbns: tuple
    series_id: str
    order_number: str
    series_book_type: str
    issues: tuple
    preorder: bool
    image_links: tuple
    selected_image_field: str
    selected_artwork_url: str
    artwork_quality: str


def _number(value):
    try:
        number=float(value)
    except (TypeError,ValueError):
        return ''
    return str(int(number)) if number.is_integer() else str(number)


def _creator(value):
    return creator_comparison_identity(value)


def _volume_from_title(title):
    match=_VOLUME.search(str(title or '').strip())
    return _number(match.group(1)) if match else ''


def _base_title(title):
    text=str(title or '').strip(); match=_VOLUME.search(text)
    return normalize_identity_text((text[:match.start()] if match else text).strip(' ,:-'))


def _discovery_queries(context):
    title=str(context.get('canonical_title') or '').strip()
    aliases=tuple(dict.fromkeys(str(value).strip() for value in
        context.get('trusted_aliases') or () if str(value or '').strip()
        and normalize_identity_text(value) != normalize_identity_text(title)))[:2]
    creators=[]; creator_keys=set()
    for value in (*(context.get('canonical_creators') or ()),
                  *(context.get('canonical_creator_aliases') or ())):
        for variant in creator_query_variants(value):
            key=normalize_identity_text(variant)
            if key and key not in creator_keys:
                creator_keys.add(key); creators.append(variant)
    creators=creators[:3]
    seen=set(); queries=[]
    for work_title in (title,*aliases):
        for creator in creators:
            query=f'intitle:"{work_title}" inauthor:"{creator}"'
            key=normalize_identity_text(query)
            if key not in seen:
                seen.add(key); queries.append(query)
    return tuple(queries[:MAX_DISCOVERY_QUERIES])


def _series_record(info):
    values=tuple(dict(row or {}) for row in dict(info or {}).get('volumeSeries') or ())
    if len(values) != 1:
        return {}, values
    return values[0], values


def _issues(series):
    rows=[]
    for issue in series.get('issue') or ():
        item=dict(issue or {})
        rows.append((_number(item.get('issueOrderNumber')),str(item.get('issueDisplayNumber') or '')))
    return tuple(rows)


def _select_image(links):
    row=dict(links or {})
    for field,quality in (('extraLarge','HIGH'),('large','HIGH'),('medium','HIGH'),
                          ('small','USABLE'),('thumbnail','THUMBNAIL_ONLY'),
                          ('smallThumbnail','THUMBNAIL_ONLY')):
        if row.get(field):
            return field,str(row[field]),quality
    return '','','NONE'


def select_preview_rendition(links):
    row=dict(links or {})
    for field in ('small','thumbnail','medium','large','extraLarge','smallThumbnail'):
        if row.get(field): return field,str(row[field])
    return '',''


def select_source_rendition(links):
    row=dict(links or {})
    for field in ('extraLarge','large','medium','small'):
        if row.get(field): return field,str(row[field])
    return '',''


def normalize_google_volume(record):
    row=dict(record or {}); info=dict(row.get('volumeInfo') or {}); sale=dict(row.get('saleInfo') or {})
    series,all_series=_series_record(info.get('seriesInfo'))
    field,url,quality=_select_image(info.get('imageLinks'))
    identifiers=tuple(sorted((str(item.get('type') or ''),str(item.get('identifier') or ''))
                             for item in info.get('industryIdentifiers') or () if item.get('identifier')))
    images=tuple(sorted((str(key),str(value)) for key,value in dict(info.get('imageLinks') or {}).items() if value))
    return GoogleManifestation(
        str(row.get('id') or ''),str(info.get('title') or ''),str(info.get('subtitle') or ''),
        tuple(str(value) for value in info.get('authors') or ()),str(info.get('publisher') or ''),
        str(info.get('language') or '').casefold(),str(info.get('publishedDate') or ''),identifiers,
        str(series.get('seriesId') or '') if len(all_series)==1 else '',
        _number(series.get('orderNumber')) if len(all_series)==1 else '',
        str(series.get('seriesBookType') or '') if len(all_series)==1 else '',
        _issues(series) if len(all_series)==1 else (),
        str(sale.get('saleability') or '').upper() == 'FOR_PREORDER',images,field,url,quality,
    )


def _title_compatible(candidate, context):
    identities={normalize_identity_text(context.get('canonical_title'))}
    identities.update(normalize_identity_text(value) for value in context.get('trusted_aliases') or ())
    identities.discard('')
    return _base_title(candidate.title) in identities


def _creator_compatible(candidate, context):
    trusted={_creator(value) for value in context.get('canonical_creators') or () if _creator(value)}
    aliases={_creator(value) for value in context.get('canonical_creator_aliases') or () if _creator(value)}
    offered={_creator(value) for value in candidate.authors if _creator(value)}
    return bool(offered & (trusted | aliases)) if trusted or aliases else False


def trusted_series_ids(candidates, context):
    grouped={}
    for candidate in candidates:
        if (candidate.language == 'en' and candidate.series_id and candidate.order_number and
                _title_compatible(candidate,context) and _creator_compatible(candidate,context) and
                not (_COLLECTION.search(candidate.title) or _ALTERNATE.search(candidate.title) or
                     _SPINOFF.search(candidate.title) or len(candidate.issues) > 1)):
            grouped.setdefault(candidate.series_id,set()).add(candidate.order_number)
    return tuple(sorted(series_id for series_id,orders in grouped.items() if len(orders) >= 2))


def classify_manifestation(candidate, context, target_volume, trusted_series=()):
    target=_number(target_volume); combined=' '.join((candidate.title,candidate.subtitle))
    evidence=[]
    if str(context.get('requested_language') or 'en').casefold() != 'en' or candidate.language != 'en':
        return Classification.FOREIGN_LANGUAGE,('language mismatch',)
    if re.search(r'\bbox\s*set\b',combined,re.I):
        return Classification.BOX_SET,('explicit box set',)
    if _COLLECTION.search(combined) or len(candidate.issues) > 1:
        return Classification.OMNIBUS_COLLECTION,('collection marker or multiple structured issues',)
    if _ALTERNATE.search(combined):
        return Classification.ALTERNATE_EDITION,('explicit alternate-edition marker',)
    if _SPINOFF.search(combined):
        return Classification.SPINOFF,('explicit spinoff marker',)
    if _NOVEL.search(combined):
        return Classification.NOVEL_GUIDEBOOK,('explicit non-manga material marker',)
    if not _title_compatible(candidate,context):
        return Classification.UNRELATED,('canonical title mismatch',)
    evidence.append('canonical title')
    if not _creator_compatible(candidate,context):
        return Classification.AMBIGUOUS,tuple(evidence+['creator unconfirmed'])
    evidence.append('trusted creator')
    title_volume=_volume_from_title(candidate.title)
    structured=(candidate.series_id in set(trusted_series) and candidate.order_number == target)
    textual=bool(target and title_volume == target)
    if structured:
        evidence.extend(('corroborated seriesId','exact orderNumber'))
    if textual:
        evidence.append('explicit title volume')
    if not target or not (structured or textual):
        return Classification.AMBIGUOUS,tuple(evidence+['target volume unconfirmed'])
    if candidate.preorder:
        return Classification.EXACT_STANDARD_PREORDER,tuple(evidence+['preorder'])
    if not candidate.selected_artwork_url:
        return Classification.EXACT_STANDARD_COVERLESS,tuple(evidence+['coverless'])
    return Classification.EXACT_STANDARD,tuple(evidence)


def _quality_rank(value):
    return {'NONE':0,'THUMBNAIL_ONLY':1,'USABLE':2,'HIGH':3}.get(str(value),0)


def _candidate_record(candidate, target, classification, evidence, accepted=False, rejection_reason=''):
    row=asdict(candidate); row.update({
        'target_volume':_number(target),'classification':classification.value,
        'identity_evidence':list(evidence),'accepted':bool(accepted),
        'rejection_reason':str(rejection_reason or ''),
    })
    return row


class GoogleBooksArtworkResolver:
    source_id='google_books'
    supports_detail_cache=True

    def __init__(self,request_json=None,request_detail=None,api_key=None,enabled=None):
        self.api_key=api_key if api_key is not None else os.environ.get('MANGANANA_GOOGLE_BOOKS_API_KEY','')
        self.enabled=(os.environ.get('MANGANANA_GOOGLE_BOOKS_ENABLED','1') != '0') if enabled is None else bool(enabled)
        self._request_json=request_json or self._http_json
        self._request_detail=request_detail or self._http_detail
        self.request_count=0
        self.detail_request_count=0

    def _http_json(self,params):
        query=dict(params)
        if self.api_key:
            query['key']=self.api_key
        request=urllib.request.Request(BASE_URL+'?'+urllib.parse.urlencode(query),headers={
            'User-Agent':'MangaNana reference/0.11','Accept':'application/json',
        })
        with urllib.request.urlopen(request,timeout=12) as response:
            return json.loads(response.read().decode('utf-8'))

    def _query(self,text,max_results):
        self.request_count+=1
        return tuple((self._request_json({
            'q':text,'langRestrict':'en','printType':'books','projection':'full',
            'maxResults':min(MAX_BROAD_RESULTS,int(max_results)),
        }) or {}).get('items') or ())

    def _http_detail(self,volume_id):
        if not self.api_key:
            raise RuntimeError('Google Books detail API key unavailable')
        params=urllib.parse.urlencode({'projection':'full','key':self.api_key})
        request=urllib.request.Request(
            BASE_URL+'/'+urllib.parse.quote(str(volume_id),safe='')+'?'+params,
            headers={'User-Agent':'MangaNana reference/0.11','Accept':'application/json'},
        )
        with urllib.request.urlopen(request,timeout=12) as response:
            return json.loads(response.read().decode('utf-8'))

    @staticmethod
    def _detail_status(exc):
        code=getattr(exc,'code',None)
        if code in (401,403): return 'AUTH_FAILURE'
        if code == 429: return 'RATE_LIMITED'
        return 'TRANSIENT_FAILURE'

    def _fetch_detail(self,candidate,context,target,trusted,cache_get,cache_put,circuit):
        volume_id=candidate.google_volume_id
        cached=cache_get(volume_id) if cache_get else None
        if cached and cached.get('cache_contract') == DETAIL_CACHE_CONTRACT:
            return dict(cached,cache_state='hit')
        with circuit['lock']:
            if circuit['open']:
                return {'cache_contract':DETAIL_CACHE_CONTRACT,'status':'CIRCUIT_OPEN','google_volume_id':volume_id}
        try:
            with circuit['lock']:
                self.detail_request_count+=1
            raw=self._request_detail(volume_id)
            full=normalize_google_volume(raw)
            classification,evidence=classify_manifestation(full,context,target,trusted)
            contradiction=classification not in (
                Classification.EXACT_STANDARD,Classification.EXACT_STANDARD_COVERLESS,
            )
            preview_field,preview_url=select_preview_rendition(dict(full.image_links))
            source_field,source_url=select_source_rendition(dict(full.image_links))
            status=('FULL_RECORD_CONTRADICTION' if contradiction else
                    'FULL_DETAIL_SUCCESS' if source_url else
                    'THUMBNAIL_ONLY' if preview_url else 'COVERLESS')
            detail={'cache_contract':DETAIL_CACHE_CONTRACT,'status':status,
                    'google_volume_id':volume_id,'classification':classification.value,
                    'validation_evidence':list(evidence),'image_links':dict(full.image_links),
                    'preview_field':preview_field,'preview_url':preview_url,
                    'source_field':source_field,'source_url':source_url,'cache_state':'refreshed'}
            if cache_put: cache_put(volume_id,detail)
            return detail
        except Exception as exc:
            status=self._detail_status(exc)
            with circuit['lock']:
                circuit['transient_failures']+=1
                if status in ('AUTH_FAILURE','RATE_LIMITED') or circuit['transient_failures'] >= 2:
                    circuit['open']=True; circuit['reason']=status
            return {'cache_contract':DETAIL_CACHE_CONTRACT,'status':status,
                    'google_volume_id':volume_id,'error':str(exc)}

    def _promote_volume(self,target,rows,context,trusted,cache_get,cache_put,circuit,shared,shared_lock):
        attempts=[]
        for candidate,evidence in rows[:2]:
            with circuit['lock']:
                if circuit['open']: break
            with shared_lock:
                entry=shared.get(candidate.google_volume_id)
                if entry is None:
                    event=threading.Event(); shared[candidate.google_volume_id]=[event,None]; owner=True
                else:
                    event=entry[0]; owner=False
            if owner:
                detail=self._fetch_detail(candidate,context,target,trusted,cache_get,cache_put,circuit)
                with shared_lock:
                    shared[candidate.google_volume_id][1]=detail; event.set()
            else:
                event.wait()
                with shared_lock:
                    detail=shared[candidate.google_volume_id][1]
            attempts.append({'google_volume_id':candidate.google_volume_id,'status':detail.get('status')})
            if detail.get('status') != 'FULL_DETAIL_SUCCESS':
                continue
            return {'url':detail['source_url'],'preview_url':detail.get('preview_url') or detail['source_url'],
                    'source_url':detail['source_url'],'source_field':detail['source_field'],
                    'preview_field':detail.get('preview_field') or '',
                    'artwork_type':'volume','volume':target,'source':'google_books','confidence':'exact',
                    'publication_id':str(context.get('reference_key') or ''),'edition_id':'standard:en',
                    'volume_id':candidate.google_volume_id,'artwork_quality':
                    ('HIGH' if detail['source_field'] in ('extraLarge','large','medium') else 'USABLE'),
                    'classification':'EXACT_STANDARD','retrieval':'volumes_get_full',
                    'identity_evidence':list(evidence),'detail_attempts':attempts}
        return None

    def resolve(self,context,target_volumes,detail_cache_get=None,detail_cache_put=None):
        context=dict(context or {}); targets=tuple(sorted({_number(value) for value in target_volumes if _number(value)},key=float))
        empty={'cache_contract':CACHE_CONTRACT,'status':'disabled','covers':[],'candidates':[],
               'trusted_series_ids':[],'target_volumes':list(targets),'network':{'requests':0}}
        if (not self.enabled or str(context.get('requested_language') or '').casefold() != 'en' or
                str(context.get('edition_profile') or '') != 'standard'):
            return empty
        if not targets:
            return {**empty,'status':'no_remaining_artwork_gaps'}
        title=str(context.get('canonical_title') or '').strip(); creators=tuple(context.get('canonical_creators') or ())
        if not title or not creators:
            return {**empty,'status':'insufficient_canonical_evidence'}
        candidates={}; discovery_queries=[]
        for query in _discovery_queries(context):
            discovery_queries.append(query)
            for original in self._query(query,MAX_BROAD_RESULTS):
                candidate=normalize_google_volume(original)
                if candidate.google_volume_id:
                    candidates[candidate.google_volume_id]=candidate
            trusted=trusted_series_ids(tuple(candidates.values()),context)
            safe=False
            for candidate in candidates.values():
                target=candidate.order_number or _volume_from_title(candidate.title)
                if target in targets and classify_manifestation(candidate,context,target,trusted)[0] in (
                        Classification.EXACT_STANDARD, Classification.EXACT_STANDARD_COVERLESS,
                        Classification.EXACT_STANDARD_PREORDER):
                    safe=True; break
            if safe:
                break
        trusted=trusted_series_ids(tuple(candidates.values()),context)
        covered={row.order_number or _volume_from_title(row.title) for row in candidates.values()}
        targeted_budget=min(MAX_TARGETED_QUERIES,max(0,MAX_TOTAL_QUERIES-len(discovery_queries)))
        targeted_requests=0
        target_titles=tuple(dict.fromkeys((title,*(str(value).strip() for value in
            context.get('trusted_aliases') or () if str(value or '').strip()))))[:3]
        for target in tuple(value for value in targets if value not in covered):
            for target_title in target_titles:
                if targeted_requests >= targeted_budget:
                    break
                targeted_requests+=1
                for original in self._query(
                        f'intitle:"{target_title} Vol. {target}" inauthor:"{creators[0]}"',10):
                    row=normalize_google_volume(original)
                    if row.google_volume_id:
                        candidates[row.google_volume_id]=row
                trusted=trusted_series_ids(tuple(candidates.values()),context)
                if any((row.order_number or _volume_from_title(row.title)) == target and
                       classify_manifestation(row,context,target,trusted)[0] in (
                           Classification.EXACT_STANDARD, Classification.EXACT_STANDARD_COVERLESS,
                           Classification.EXACT_STANDARD_PREORDER)
                       for row in candidates.values()):
                    break
            if targeted_requests >= targeted_budget:
                break
        trusted=trusted_series_ids(tuple(candidates.values()),context)
        evaluations=[]; qualified={}
        for candidate in sorted(candidates.values(),key=lambda row:row.google_volume_id):
            suggested=candidate.order_number or _volume_from_title(candidate.title)
            target=suggested if suggested in targets else ''
            classification,evidence=classify_manifestation(candidate,context,target,trusted)
            promotable=(classification is Classification.EXACT_STANDARD and
                        _quality_rank(candidate.artwork_quality) >= _quality_rank('USABLE'))
            evaluations.append(_candidate_record(
                candidate,target,classification,evidence,promotable,
                '' if promotable else ('image quality below USABLE' if classification is Classification.EXACT_STANDARD else classification.value),
            ))
            if promotable:
                qualified.setdefault(target,[]).append((candidate,evidence))
        # Detail promotion considers every independently qualified released manifestation,
        # including list records whose preview is thumbnail-only or absent.
        detail_groups={}
        for candidate in sorted(candidates.values(),key=lambda row:row.google_volume_id):
            target=candidate.order_number or _volume_from_title(candidate.title)
            if target not in targets: continue
            classification,evidence=classify_manifestation(candidate,context,target,trusted)
            if classification is Classification.EXACT_STANDARD:
                detail_groups.setdefault(target,[]).append((candidate,evidence))
        for rows in detail_groups.values():
            rows.sort(key=lambda item:(
                -(item[0].series_id in set(trusted)),-bool(item[0].order_number),
                item[0].google_volume_id,
            ))
        covers=[]; circuit={'open':False,'reason':'','transient_failures':0,'lock':threading.Lock()}
        shared={}; shared_lock=threading.Lock()
        if self.api_key and detail_groups:
            with ThreadPoolExecutor(max_workers=4) as executor:
                futures={executor.submit(self._promote_volume,target,rows,context,trusted,
                                         detail_cache_get,detail_cache_put,circuit,shared,shared_lock):target
                         for target,rows in sorted(detail_groups.items(),key=lambda item:float(item[0]))}
                for future in as_completed(futures):
                    cover=future.result()
                    if cover: covers.append(cover)
        covers.sort(key=lambda row:float(row['volume']))
        return {'cache_contract':CACHE_CONTRACT,'detail_cache_contract':DETAIL_CACHE_CONTRACT,
                'status':'valid' if candidates else 'no_discovery_candidates','covers':covers,
                'candidates':evaluations,'trusted_series_ids':list(trusted),
                'discovery_queries':discovery_queries,
                'target_volumes':list(targets),'network':{'requests':self.request_count,
                'detail_requests':self.detail_request_count,'detail_concurrency':4,
                'detail_circuit_open':circuit['open'],'detail_circuit_reason':circuit['reason']}}
