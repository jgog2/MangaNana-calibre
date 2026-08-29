"""Calibre- and Qt-independent MangaDex discovery/data-access implementation."""

import json
import re
import time
import urllib.parse
import urllib.error
import urllib.request

try:
    from .core_helpers import _iter_aggregate_nodes, choose_preferred_title, collect_titles, is_doujinshi_entry
    from .source_adapter import SourceAdapter
    from .version_info import USER_AGENT
except ImportError:
    from core_helpers import _iter_aggregate_nodes, choose_preferred_title, collect_titles, is_doujinshi_entry
    from source_adapter import SourceAdapter
    from version_info import USER_AGENT


UUID_RE = re.compile(r'/title/([0-9a-fA-F-]{36})')
RATINGS = ('safe', 'suggestive', 'erotica', 'pornographic')


class MangaDexSource(SourceAdapter):
    source_id = 'mangadex'
    key = source_id
    display_name = 'MangaDex'
    domains = ('mangadex.org', 'www.mangadex.org')
    enabled_by_default = True
    capabilities = frozenset({'search', 'metadata', 'volumes', 'chapters', 'covers',
                              'pages', 'data_saver', 'binary'})

    def __init__(self, api_json=None, fetch_binary=None):
        self._api_json = api_json or self._default_api_json
        self._fetch_binary = fetch_binary or self._default_fetch_binary

    @staticmethod
    def _default_api_json(url, timeout=30, retries=3, retry_callback=None):
        transient={429,500,502,503,504}; last=None
        for attempt in range(1,max(1,int(retries))+1):
            try:
                req=urllib.request.Request(url,headers={'User-Agent':USER_AGENT})
                with urllib.request.urlopen(req,timeout=timeout) as response:
                    return json.loads(response.read().decode('utf-8'))
            except urllib.error.HTTPError as exc:
                last=exc
                if exc.code not in transient or attempt>=retries: break
                wait=min(8,0.8*(2**(attempt-1)))
                if exc.code==429:
                    try: wait=max(wait,float(exc.headers.get('Retry-After') or 0))
                    except Exception: pass
                if retry_callback: retry_callback(f'MangaDex request temporarily failed (HTTP {exc.code}). Retrying {attempt + 1}/{retries} in {wait:g}s...')
                time.sleep(wait)
            except Exception as exc:
                last=exc
                if attempt>=retries: break
                wait=min(8,0.8*(2**(attempt-1)))
                if retry_callback: retry_callback(f'Network request failed. Retrying {attempt + 1}/{retries} in {wait:g}s...')
                time.sleep(wait)
        raise RuntimeError(f'MangaDex request failed after {retries} attempt(s): {last}')

    @staticmethod
    def _default_fetch_binary(url, timeout=45, retries=5, user_agent=USER_AGENT, retry_callback=None):
        last=None
        for attempt in range(1,retries+1):
            try:
                req=urllib.request.Request(url,headers={'User-Agent':user_agent,'Accept':'*/*'})
                with urllib.request.urlopen(req,timeout=timeout) as response: return response.read()
            except Exception as exc:
                last=exc
                if attempt<retries:
                    wait=min(8,0.75*(2**(attempt-1)))
                    if retry_callback: retry_callback(f'Download interrupted. Retrying {attempt + 1}/{retries} in {wait:g}s...')
                    time.sleep(wait)
        raise RuntimeError(f'Failed to download after {retries} attempts: {last}')

    def parse_manga_ref(self, value):
        text = value or ''
        parsed = urllib.parse.urlparse(text if '://' in text else f'https://{text}')
        if (parsed.hostname or '').casefold() not in self.domains:
            return None
        match = UUID_RE.search(parsed.path or '')
        return match.group(1) if match else None

    def _require_id(self, value, message='Enter a valid MangaDex title URL.'):
        manga_id = self.parse_manga_ref(value)
        if not manga_id:
            raise ValueError(message)
        return manga_id

    def get_manga(self, value, preferred='en'):
        manga_id = self._require_id(value, 'Paste a MangaDex title-page URL, for example https://mangadex.org/title/...')
        query = urllib.parse.urlencode([('includes[]', 'author'), ('includes[]', 'artist'), ('includes[]', 'cover_art')])
        data = self._api_json(f'https://api.mangadex.org/manga/{manga_id}?{query}')['data']
        attrs = data.get('attributes', {}); titles = collect_titles(attrs)
        author = ''; cover_filename = ''
        for rel in data.get('relationships', []):
            if rel.get('type') == 'author' and rel.get('attributes') and not author:
                author = rel['attributes'].get('name', '')
            elif rel.get('type') == 'cover_art' and rel.get('attributes') and not cover_filename:
                cover_filename = rel['attributes'].get('fileName', '') or ''
        selected_title = choose_preferred_title(titles, preferred)
        return {
            'uuid': manga_id, 'title': selected_title, 'author': author,
            'titles': titles,
            'alternate_titles': [row.get('title') for row in titles if str(row.get('title') or '').casefold() != selected_title.casefold()],
            'year': attrs.get('year'),
            'available_languages': [str(x) for x in (attrs.get('availableTranslatedLanguages') or []) if x],
            'original_language': attrs.get('originalLanguage') or '',
            'main_cover_url': f'https://uploads.mangadex.org/covers/{manga_id}/{cover_filename}' if cover_filename else '',
        }

    @staticmethod
    def _score(query, title, full_title='', preferred_available=False):
        q=(query or '').casefold().strip(); t=(title or '').casefold().strip(); raw=(full_title or title or '').casefold().strip(); score=0
        if t == q: score += 1000
        elif t.startswith(q): score += 500
        elif q in t: score += 250
        if preferred_available: score += 75
        if 'official colored' in raw or 'official coloured' in raw: score += 120
        elif any(x in raw for x in ('digital colored','digital coloured','digital color','digital colour')): score += 55
        if any(x in raw for x in ('fan-colored','fan colored','fan-coloured','fan coloured')): score -= 350
        if 'doujinshi' in raw or 'doujin' in raw: score -= 500
        return score - abs(len(t)-len(q)) * 0.25

    def has_downloadable_content(self, manga_id, attrs=None):
        if not manga_id: return False
        reported = (attrs or {}).get('availableTranslatedLanguages')
        if isinstance(reported, list) and not reported: return False
        offset=0; limit=20
        for _ in range(3):
            params=[('limit',str(limit)),('offset',str(offset)),('order[readableAt]','desc')]
            params.extend(('contentRating[]', rating) for rating in RATINGS)
            rows=(self._api_json(f'https://api.mangadex.org/manga/{manga_id}/feed?{urllib.parse.urlencode(params)}', timeout=18).get('data') or [])
            if any(row.get('id') and not (row.get('attributes') or {}).get('externalUrl') for row in rows): return True
            if len(rows) < limit: break
            offset += len(rows)
        return False

    def search(self, query, offset=0, limit=12, include_adult=False, preferred='en', availability_cache=None):
        cache=availability_cache if availability_cache is not None else {}; rows=[]; filtered_doujinshi=0; filtered_empty=0
        api_offset=max(0,int(offset)); api_total=0; scanned=0; exhausted=False; batch_size=max(12,min(40,int(limit)*2))
        while len(rows) < limit and not exhausted:
            params=[('title',query),('limit',str(batch_size)),('offset',str(api_offset)),('order[relevance]','desc'),('includes[]','author'),('includes[]','cover_art')]
            if not include_adult: params += [('contentRating[]','safe'),('contentRating[]','suggestive')]
            data=self._api_json('https://api.mangadex.org/manga?'+urllib.parse.urlencode(params), timeout=30)
            fetched=data.get('data') or []; api_total=max(api_total,int(data.get('total') or 0))
            if not fetched: exhausted=True; break
            processed=0
            for entry in fetched:
                processed += 1; attrs=entry.get('attributes') or {}
                if is_doujinshi_entry(attrs): filtered_doujinshi += 1; continue
                manga_id=entry.get('id'); available=cache.get(manga_id) if manga_id else False
                if available is None:
                    try: available=self.has_downloadable_content(manga_id, attrs)
                    except Exception: available=True
                    if manga_id: cache[manga_id]=bool(available)
                if not available: filtered_empty += 1; continue
                titles=collect_titles(attrs); full_title=choose_preferred_title(titles, preferred) or 'Untitled'
                raw=' '.join(row.get('title','') for row in titles).casefold()
                badge='FAN COLOR' if ('fan-colored' in raw or 'fan colored' in raw) else ('COLOR' if any(x in raw for x in ('digital colored','digital colour','full color','full colour','color edition','colored comics','colour edition')) else '')
                display=re.sub(r'(?i)\s*[-–—:(]*\s*(digital\s+colou?red\s+comics|full\s+colou?r(?:\s+edition)?|colou?red\s+edition|fan[- ]colou?red)\s*[)]*\s*$', '', full_title).strip(' -–—:()') or full_title
                author=''; cover=''
                for rel in entry.get('relationships') or []:
                    if rel.get('type')=='author' and not author: author=(rel.get('attributes') or {}).get('name') or ''
                    elif rel.get('type')=='cover_art' and not cover: cover=(rel.get('attributes') or {}).get('fileName') or ''
                alternate_titles=[row.get('title') for row in titles if str(row.get('title') or '').casefold() != display.casefold()]
                rows.append({'score':self._score(query,display,full_title,preferred in (attrs.get('availableTranslatedLanguages') or [])), 'title':display,'full_title':full_title,'alternate_titles':alternate_titles,'author':author,'year':attrs.get('year'),'id':manga_id,'cover_url':f'https://uploads.mangadex.org/covers/{manga_id}/{cover}' if manga_id and cover else '','badge':badge})
                if len(rows)>=limit: break
            api_offset += processed; scanned += processed
            exhausted=bool((api_total and api_offset>=api_total) or (processed>=len(fetched) and len(fetched)<batch_size))
        rows.sort(key=lambda row:row['score'], reverse=True)
        return {'query':query,'offset':int(offset),'next_offset':api_offset,'limit':int(limit),'total':api_total,'rows':rows,'fetched_count':scanned,'filtered_doujinshi':filtered_doujinshi,'filtered_empty':filtered_empty,'has_more':bool(api_total and api_offset<api_total and not exhausted)}

    def get_chapters(self, value, language, start_volume=None, end_volume=None):
        manga_id=self._require_id(value); entries=[]; seen_ids=set(); seen_logical=set(); offset=0; limit=500
        while True:
            params=[('limit',str(limit)),('offset',str(offset)),('order[volume]','asc'),('order[chapter]','asc'),('order[readableAt]','asc'),('translatedLanguage[]',language)]
            params.extend(('contentRating[]', rating) for rating in RATINGS)
            rows=(self._api_json(f'https://api.mangadex.org/manga/{manga_id}/feed?{urllib.parse.urlencode(params)}', timeout=35).get('data') or [])
            if not rows: break
            for item in rows:
                chapter_id=item.get('id')
                if not chapter_id or chapter_id in seen_ids: continue
                seen_ids.add(chapter_id); attrs=item.get('attributes') or {}
                if attrs.get('externalUrl'): continue
                raw_volume=attrs.get('volume'); numeric=None
                try:
                    if raw_volume not in (None,''): numeric=float(str(raw_volume).strip())
                except Exception: numeric=None
                if numeric is not None:
                    if start_volume is not None and numeric<start_volume: continue
                    if end_volume is not None and numeric>end_volume: continue
                elif start_volume is not None or end_volume is not None: continue
                chapter=str(attrs.get('chapter') or '').strip(); logical=(numeric,chapter) if chapter else ('bonus',chapter_id)
                if logical in seen_logical: continue
                seen_logical.add(logical); entries.append({'id':chapter_id,'volume':numeric,'chapter':chapter,'title':str(attrs.get('title') or '').strip(),'pages':int(attrs.get('pages') or 0)})
            offset += len(rows)
            if len(rows)<limit: break
        return entries

    def _aggregate_plan(self, value, language, start_volume=None, end_volume=None):
        manga_id=self._require_id(value); params=[('translatedLanguage[]',language),('includeUnavailable','0')]
        data=self._api_json(f'https://api.mangadex.org/manga/{manga_id}/aggregate?{urllib.parse.urlencode(params)}', timeout=35)
        volumes={}; bonus=0
        for key, volume_data in _iter_aggregate_nodes(data.get('volumes') or {}):
            raw=volume_data.get('volume')
            if raw in (None,''): raw=key
            usable=0
            for _key, chapter in _iter_aggregate_nodes(volume_data.get('chapters') or {}):
                if chapter.get('isUnavailable') is True: continue
                if chapter.get('id') or chapter.get('chapter') not in (None,'') or int(chapter.get('count') or 0)>0: usable += max(1,int(chapter.get('count') or 1))
            if usable<=0: usable=int(volume_data.get('count') or 0)
            if usable<=0: continue
            try: numeric=float(str(raw).strip())
            except Exception: numeric=None
            if numeric is not None and numeric>0:
                if start_volume is not None and numeric<start_volume: continue
                if end_volume is not None and numeric>end_volume: continue
                volumes[numeric]=max(volumes.get(numeric,0),usable)
            else: bonus += usable
        return volumes,bonus

    def get_download_plan(self, value, language, start_volume=None, end_volume=None):
        self._require_id(value); aggregate={}; aggregate_bonus=0; feed={}; feed_bonus=0; aggregate_error=''; feed_error=''
        try: aggregate,aggregate_bonus=self._aggregate_plan(value,language,start_volume,end_volume)
        except Exception as exc: aggregate_error=str(exc)
        try:
            for entry in self.get_chapters(value,language,start_volume,end_volume):
                volume=entry.get('volume')
                if volume is None: feed_bonus += 1
                else: feed[float(volume)]=feed.get(float(volume),0)+1
        except Exception as exc: feed_error=str(exc)
        if aggregate_error and feed_error: raise RuntimeError(f'MangaDex volume lookup failed. Aggregate: {aggregate_error} | Feed: {feed_error}')
        volumes=dict(aggregate)
        for volume,count in feed.items(): volumes[volume]=max(volumes.get(volume,0),count)
        ordered=sorted(volumes)
        return {'volumes':ordered,'pages_by_volume':{v:0 for v in ordered},'chapters_by_volume':{v:volumes[v] for v in ordered},'bonus_pages':0,'bonus_chapters':max(aggregate_bonus,feed_bonus),'aggregate_error':aggregate_error,'feed_error':feed_error}

    def get_volume_covers(self, value):
        manga_id=self.parse_manga_ref(value)
        if not manga_id: return {}
        result={}; offset=0; limit=100
        while True:
            params=[('limit',str(limit)),('offset',str(offset)),('manga[]',manga_id),('order[volume]','asc')]
            rows=self._api_json('https://api.mangadex.org/cover?'+urllib.parse.urlencode(params), timeout=30).get('data') or []
            if not rows: break
            for item in rows:
                attrs=item.get('attributes') or {}; filename=attrs.get('fileName')
                if not filename: continue
                raw=attrs.get('volume')
                try: key=float(str(raw).strip()) if raw not in (None,'') else None
                except Exception: key=None
                result[key]=f'https://uploads.mangadex.org/covers/{manga_id}/{filename}'
            offset += len(rows)
            if len(rows)<limit: break
        return result

    def get_page_manifest(self, chapter_id, retry_callback=None):
        data=self._api_json(f'https://api.mangadex.org/at-home/server/{chapter_id}', timeout=30, retries=3, retry_callback=retry_callback)
        base=data.get('baseUrl'); chapter=data.get('chapter') or {}; page_hash=chapter.get('hash'); full=chapter.get('data') or []; saver=chapter.get('dataSaver') or []
        if not base or not page_hash or not full: raise RuntimeError('MangaDex returned no readable page data for this chapter.')
        return {'full':[f'{base}/data/{page_hash}/{name}' for name in full], 'data_saver':[f'{base}/data-saver/{page_hash}/{name}' for name in saver] if saver else []}

    def fetch_binary(self, url, **kwargs):
        return self._fetch_binary(url, **kwargs)

    def fetch_preview_page(self, saver_url, full_url, page_number, log=None, check_cancel=None):
        """Fetch a data-saver page with MangaDex retry/fallback behavior."""
        transient={429,500,502,503,504}; delays=(1,2,4); last=None
        check=check_cancel or (lambda: None); emit=log or (lambda _message: None)
        for attempt in range(1,4):
            check()
            try:
                req=urllib.request.Request(saver_url,headers={'User-Agent':USER_AGENT,'Accept':'*/*'})
                with urllib.request.urlopen(req,timeout=35) as response: return response.read(),False
            except urllib.error.HTTPError as exc:
                last=exc
                if exc.code not in transient: break
                if attempt<3:
                    wait=delays[attempt-1]
                    if exc.code==429:
                        try: wait=max(wait,min(30,int(exc.headers.get('Retry-After',wait))))
                        except Exception: pass
                    emit(f'Preview: page {page_number} returned HTTP {exc.code}. Retry {attempt}/3 in {wait}s...')
                    for _ in range(wait*10): check(); time.sleep(0.1)
            except Exception as exc:
                last=exc
                if attempt<3:
                    wait=delays[attempt-1]; emit(f'Preview: page {page_number} download failed. Retry {attempt}/3 in {wait}s...')
                    for _ in range(wait*10): check(); time.sleep(0.1)
        check(); emit(f'Preview: reduced-quality page {page_number} unavailable after retries. Using full-quality fallback.')
        try: return self.fetch_binary(full_url,timeout=45,retries=4,user_agent=USER_AGENT),True
        except Exception as exc: raise RuntimeError(f'Preview page {page_number} failed in both reduced and full quality. Data-saver error: {last}; full-quality error: {exc}')
