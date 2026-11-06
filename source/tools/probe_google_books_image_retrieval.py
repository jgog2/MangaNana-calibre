#!/usr/bin/env python3
"""Probe alternate image retrieval for already-qualified Google Volume IDs."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import re
import urllib.parse
import urllib.request

from PIL import Image


API='https://www.googleapis.com/books/v1/volumes/'
FRONT='https://books.google.com/books/publisher/content/images/frontcover/'
PREFERRED={
    'bleach':(1,60,61,74),'one_piece':(1,57,58,112),
    'attack_on_titan':(1,34),'death_note':(1,12),
}


def redact_url(url):
    parsed=urllib.parse.urlsplit(str(url or '')); query=urllib.parse.parse_qsl(parsed.query,keep_blank_values=True)
    return urllib.parse.urlunsplit((parsed.scheme,parsed.netloc,parsed.path,
        urllib.parse.urlencode([(k,'REDACTED' if k.casefold() in ('key','api_key') else v) for k,v in query]),parsed.fragment))


def quality(width,height,placeholder=False):
    if placeholder: return 'PLACEHOLDER'
    if not width or not height: return 'NONE'
    if width >= 575: return 'HIGH'
    if width >= 300: return 'USABLE'
    if width >= 100: return 'THUMBNAIL_ONLY'
    return 'TINY'


def image_facts(raw,content_type=''):
    digest=hashlib.sha256(raw or b'').hexdigest() if raw else ''
    try:
        with Image.open(io.BytesIO(raw)) as image:
            image.load(); width,height=image.size
            thumb=image.convert('L').resize((16,16))
            values=list(thumb.getdata()); mean=sum(values)/len(values)
            perceptual=''.join('1' if value >= mean else '0' for value in values)
            return {'decodable':True,'width':width,'height':height,
                    'aspect_ratio':round(width/height,6) if height else None,
                    'format':str(image.format or ''),'image_hash':digest,'perceptual_hash':perceptual,
                    'bytes':len(raw),'content_type':content_type}
    except Exception as exc:
        return {'decodable':False,'width':0,'height':0,'aspect_ratio':None,'format':'',
                'image_hash':digest,'perceptual_hash':'','bytes':len(raw or b''),
                'content_type':content_type,'error':str(exc)}


def hamming(first,second):
    if not first or not second or len(first) != len(second): return None
    return sum(a != b for a,b in zip(first,second))


def same_cover(official,candidate):
    if not official.get('decodable') or not candidate.get('decodable'): return None
    if not official.get('width') or not candidate.get('width'): return False
    ratio=max(official['aspect_ratio'],candidate['aspect_ratio'])/min(official['aspect_ratio'],candidate['aspect_ratio'])
    distance=hamming(official.get('perceptual_hash'),candidate.get('perceptual_hash'))
    return bool(ratio <= 1.12 and distance is not None and distance <= 42)


def best_attempt(attempts):
    order={'NONE':0,'TINY':1,'THUMBNAIL_ONLY':2,'USABLE':3,'HIGH':4}
    return sorted((row for row in attempts if row.get('same_cover') is not False and not row.get('placeholder')),
                  key=lambda row:(-order.get(row.get('quality'),0),-int(row.get('bytes') or 0),row.get('method',''),row.get('requested_url','')))[0] if attempts else None


def _download(url,timeout=15):
    request=urllib.request.Request(url,headers={'User-Agent':'MangaNana image retrieval probe/0.11','Accept':'image/*,*/*;q=0.8'})
    try:
        with urllib.request.urlopen(request,timeout=timeout) as response:
            raw=response.read(); facts=image_facts(raw,response.headers.get_content_type() or '')
            return {'http_status':getattr(response,'status',200),'final_url':redact_url(response.geturl()),**facts}
    except Exception as exc:
        return {'http_status':getattr(exc,'code',None),'final_url':'','decodable':False,'width':0,'height':0,
                'aspect_ratio':None,'format':'','image_hash':'','perceptual_hash':'','bytes':0,
                'content_type':'','error':str(exc)}


def _get(volume_id,key):
    url=API+urllib.parse.quote(volume_id,safe='')+'?'+urllib.parse.urlencode({'projection':'full','key':key})
    request=urllib.request.Request(url,headers={'User-Agent':'MangaNana image retrieval probe/0.11','Accept':'application/json'})
    try:
        with urllib.request.urlopen(request,timeout=15) as response:
            return json.loads(response.read().decode('utf-8')),{'http_status':response.status,'requested_url':redact_url(url)}
    except Exception as exc:
        return {},{'http_status':getattr(exc,'code',None),'requested_url':redact_url(url),'error':str(exc)}


def _variants(url):
    parsed=urllib.parse.urlsplit(url); pairs=urllib.parse.parse_qsl(parsed.query,keep_blank_values=True)
    if not any(key.casefold() == 'zoom' for key,_ in pairs): return ()
    values=[]
    for zoom in ('2','3'):
        updated=[(key,zoom if key.casefold() == 'zoom' else value) for key,value in pairs]
        values.append(urllib.parse.urlunsplit((parsed.scheme,parsed.netloc,parsed.path,urllib.parse.urlencode(updated),parsed.fragment)))
    return tuple(dict.fromkeys(values))


def _subjects(report):
    chosen=[]; substitutions=[]
    for work,wanted in PREFERRED.items():
        candidates=[]
        for row in report['series'][work]['result'].get('candidates') or ():
            if row.get('classification') == 'EXACT_STANDARD' and row.get('google_volume_id'):
                candidates.append(row)
        by_volume=defaultdict(list)
        for row in candidates: by_volume[str(row.get('target_volume') or '')].append(row)
        for target in wanted:
            exact=by_volume.get(str(target),[])
            pool=exact or candidates
            if not pool: continue
            row=sorted(pool,key=lambda value:(abs(float(value.get('target_volume') or 9999)-target),value['google_volume_id']))[0]
            if not exact: substitutions.append({'work':work,'requested_volume':target,'used_volume':row.get('target_volume'),'google_volume_id':row['google_volume_id']})
            chosen.append((work,row))
    seen=set(); output=[]
    for work,row in chosen:
        if row['google_volume_id'] not in seen:
            seen.add(row['google_volume_id']); output.append((work,row))
    return output[:12],substitutions


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--qualification',required=True); parser.add_argument('--output',required=True)
    args=parser.parse_args(); key=os.environ.get('MANGANANA_GOOGLE_BOOKS_API_KEY','')
    if not key: raise SystemExit('MANGANANA_GOOGLE_BOOKS_API_KEY is absent')
    report=json.loads(Path(args.qualification).read_text(encoding='utf-8')); subjects,substitutions=_subjects(report)
    results=[]; request_count=0
    for work,row in subjects:
        volume_id=row['google_volume_id']; attempts=[]; links=dict(row.get('image_links') or ())
        original_url=row.get('selected_artwork_url') or links.get('thumbnail') or links.get('smallThumbnail') or ''
        official={'method':'official_image_link','requested_url':redact_url(original_url),**_download(original_url)} if original_url else {'method':'official_image_link','requested_url':'','quality':'NONE'}
        official['quality']=quality(official.get('width'),official.get('height')); attempts.append(official); request_count+=bool(original_url)
        full,api_meta=_get(volume_id,key); request_count+=1; full_links=dict((full.get('volumeInfo') or {}).get('imageLinks') or {})
        get_record={'method':'volumes.get/full','requested_url':api_meta['requested_url'],'http_status':api_meta.get('http_status'),
                    'image_links':full_links,'additional_fields':sorted(set(full_links)-set(links)),'error':api_meta.get('error','')}
        best_full_url=next((full_links.get(field) for field in (
            'extraLarge','large','medium','small','thumbnail','smallThumbnail'
        ) if full_links.get(field)), '')
        for url in (best_full_url,):
            if not url:
                continue
            probe={'method':'volumes.get/image_link','requested_url':redact_url(url),**_download(url)}; probe['same_cover']=same_cover(official,probe); probe['quality']=quality(probe.get('width'),probe.get('height')); attempts.append(probe); request_count+=1
        for size in ('w300-h450','w600-h900','w900-h1350','w1200-h1800'):
            url=FRONT+urllib.parse.quote(volume_id,safe='')+'?'+urllib.parse.urlencode({'fife':size})
            probe={'method':'frontcover:'+size,'requested_url':redact_url(url),**_download(url)}; probe['same_cover']=same_cover(official,probe); probe['quality']=quality(probe.get('width'),probe.get('height')); attempts.append(probe); request_count+=1
        for url in _variants(original_url):
            probe={'method':'official_url_variant','requested_url':redact_url(url),**_download(url)}; probe['same_cover']=same_cover(official,probe); probe['quality']=quality(probe.get('width'),probe.get('height')); attempts.append(probe); request_count+=1
        results.append({'work':work,'canonical_volume':row.get('target_volume'),'google_volume_id':volume_id,
                        'series_id':row.get('series_id'),'order_number':row.get('order_number'),'title':row.get('title'),
                        'authors':row.get('authors'),'language':row.get('language'),'classification':row.get('classification'),
                        'list_image_links':links,'volumes_get':get_record,'attempts':attempts})
    hashes=defaultdict(set)
    for subject in results:
        for attempt in subject['attempts']:
            if attempt.get('image_hash'): hashes[attempt['image_hash']].add(subject['google_volume_id'])
    for subject in results:
        official=next((row for row in subject['attempts'] if row['method']=='official_image_link'),{})
        for attempt in subject['attempts']:
            attempt['placeholder']=bool(attempt.get('width',0) < 100 or len(hashes.get(attempt.get('image_hash'),())) > 1)
            attempt['quality']=quality(attempt.get('width'),attempt.get('height'),attempt['placeholder'])
            if attempt is not official: attempt['same_cover']=same_cover(official,attempt)
        subject['best']=best_attempt(subject['attempts'])
    all_attempts=[row for subject in results for row in subject['attempts']]
    aggregate=Counter(row.get('quality') for row in all_attempts)
    aggregate.update({'subjects':len(results),'requests':request_count,'identity_mismatches':sum(row.get('same_cover') is False for row in all_attempts),
                      'real_usable_subjects':sum(bool(subject.get('best')) and subject['best'].get('quality') in ('USABLE','HIGH') for subject in results)})
    output={'contract':'phase1f1-google-image-retrieval-v1','created_at':datetime.now().isoformat(),
            'qualification_artifact':str(Path(args.qualification)),'substitutions':substitutions,'subjects':results,'aggregate':dict(aggregate)}
    Path(args.output).write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'artifact':args.output,'aggregate':output['aggregate'],'subjects':len(results)},indent=2))


if __name__=='__main__': main()
