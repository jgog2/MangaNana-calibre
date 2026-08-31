"""Synchronous WeebCentral HTML adapter derived from browser HAR captures."""

from html import unescape
import re
import time
import urllib.error
import urllib.parse
import urllib.request

try:
    from .chapter_workflow import chapter_sort_key
    from .source_adapter import SourceAdapter
    from .version_info import USER_AGENT
except ImportError:
    from chapter_workflow import chapter_sort_key
    from source_adapter import SourceAdapter
    from version_info import USER_AGENT


BASE_URL = 'https://weebcentral.com'
SERIES_RE = re.compile(r'^/series/([0-9A-Z]{26})(?:/[^/?#]+)?/?$', re.I)
CHAPTER_RE = re.compile(r'^/chapters/([0-9A-Z]{26})/?$', re.I)


class WeebCentralAccessBlocked(RuntimeError):
    """Raised when the site explicitly rejects non-browser access."""


def _text(value):
    return ' '.join(re.sub(r'<[^>]+>', ' ', unescape(value or '')).split())


class WeebCentralSource(SourceAdapter):
    source_id='weebcentral'; key=source_id; display_name='WeebCentral'
    domains=('weebcentral.com','www.weebcentral.com'); enabled_by_default=True
    content_languages=('en',)
    capabilities=frozenset({'search','direct_series','direct_chapters','metadata','chapters','covers','pages','binary','adult_metadata','alternate_titles','authors'})

    def __init__(self, fetch_text=None, fetch_binary=None, cancel_check=None, sleeper=None):
        self._fetch_text=fetch_text or self._default_fetch_text
        self._fetch_binary=fetch_binary or self._default_fetch_binary
        self._cancel_check=cancel_check or (lambda: None)
        self._sleep=sleeper or time.sleep

    def with_cancel_check(self, cancel_check):
        """Return a request-local adapter for a cooperative worker cancel hook."""
        return type(self)(self._fetch_text,self._fetch_binary,cancel_check,self._sleep)

    def _headers(self, target=None, referer=None, form=False):
        headers={'User-Agent':USER_AGENT,'Accept':'text/html,application/xhtml+xml,*/*;q=0.8','Referer':referer or BASE_URL+'/'}
        if target: headers.update({'HX-Request':'true','HX-Target':target})
        if form: headers['Content-Type']='application/x-www-form-urlencoded'
        return headers

    def _default_fetch_text(self, url, method='GET', data=None, headers=None, timeout=40):
        request=urllib.request.Request(url,data=data,headers=headers or {},method=method)
        with urllib.request.urlopen(request,timeout=timeout) as response:
            return response.read().decode('utf-8',errors='replace')

    def _request_text(self,url,method='GET',data=None,headers=None,retries=3):
        last=None
        for attempt in range(retries):
            self._cancel_check()
            try:
                return self._fetch_text(url,method=method,data=data,headers=headers or {},timeout=40)
            except urllib.error.HTTPError as exc:
                last=exc
                if exc.code == 403:
                    raise WeebCentralAccessBlocked(
                        'WeebCentral access blocked by site protection (HTTP 403).'
                    ) from exc
                if exc.code == 404 or exc.code < 500: raise
            except Exception as exc:
                last=exc
            if attempt + 1 < retries:
                self._cooperative_wait(min(4,0.75*(2**attempt)))
        raise RuntimeError(f'WeebCentral request failed after {retries} attempt(s): {last}')

    def _cooperative_wait(self, seconds):
        remaining=max(0,float(seconds))
        while remaining > 0:
            self._cancel_check()
            interval=min(0.1,remaining)
            self._sleep(interval)
            remaining-=interval
        self._cancel_check()

    def _default_fetch_binary(self,url,timeout=45,retries=4,**_kwargs):
        last=None
        for attempt in range(retries):
            self._cancel_check()
            try:
                request=urllib.request.Request(url,headers={'User-Agent':USER_AGENT,'Accept':'*/*','Referer':BASE_URL+'/'})
                with urllib.request.urlopen(request,timeout=timeout) as response: return response.read()
            except Exception as exc: last=exc
            if attempt+1<retries: self._cooperative_wait(min(4,0.75*(2**attempt)))
        raise RuntimeError(f'WeebCentral image request failed: {last}')

    def parse_manga_ref(self,value):
        parsed=urllib.parse.urlparse(value if '://' in (value or '') else 'https://'+(value or ''))
        if (parsed.hostname or '').casefold() not in self.domains: return None
        match=SERIES_RE.match(parsed.path or '')
        if match: return match.group(1).upper()
        match=CHAPTER_RE.match(parsed.path or '')
        return BASE_URL+parsed.path if match else None

    def resolve_manga_ref(self,value):
        ref=self.parse_manga_ref(value)
        if ref is None: raise ValueError('Enter a valid WeebCentral series or chapter URL.')
        if not str(ref).startswith('http'): return ref
        return self._chapter_parent(ref)[0]

    def _chapter_parent(self, chapter_url):
        """Return the verified parent id and canonical series link from a reader."""
        ref=self.parse_manga_ref(chapter_url)
        if ref is None or not str(ref).startswith('http'):
            raise ValueError('Enter a valid WeebCentral chapter URL.')
        html=self._request_text(ref,headers=self._headers(referer=BASE_URL+'/'))
        for candidate in re.findall(r'https?://(?:www\.)?weebcentral\.com/series/[0-9A-Z]{26}(?:/[^\"<\s?]+)?',html,re.I):
            parsed=urllib.parse.urlparse(candidate)
            match=SERIES_RE.match(parsed.path or '')
            if match and not parsed.path.casefold().endswith('/chapter-select'):
                canonical=urllib.parse.urlunparse(('https','weebcentral.com',parsed.path,'','',''))
                return match.group(1).upper(),canonical
        cover=re.search(r'/cover/(?:fallback|normal)/([0-9A-Z]{26})',html,re.I)
        if cover:
            series_id=cover.group(1).upper()
            return series_id,f'{BASE_URL}/series/{series_id}'
        raise RuntimeError('WeebCentral chapter page did not identify its parent series.')

    def _series_url(self,value):
        ref=self.parse_manga_ref(value)
        if ref is None: raise ValueError('Enter a valid WeebCentral series or chapter URL.')
        if str(ref).startswith('http'):
            return self._chapter_parent(ref)
        series_id=ref
        parsed=urllib.parse.urlparse(value or '')
        match=SERIES_RE.match(parsed.path or '')
        if match and (parsed.hostname or '').casefold() in self.domains:
            return series_id,urllib.parse.urlunparse(('https','weebcentral.com',parsed.path,'','',''))
        return series_id,f'{BASE_URL}/series/{series_id}'

    def search(self,query,offset=0,limit=12,include_adult=False,preferred='en',availability_cache=None):
        del include_adult,preferred,availability_cache
        body=urllib.parse.urlencode({'text':query},quote_via=urllib.parse.quote).encode('ascii')
        url=BASE_URL+'/search/simple?location=main'
        html=self._request_text(url,method='POST',data=body,headers=self._headers('quick-search-result',BASE_URL+'/',True))
        rows=[]
        pattern=re.compile(r'<a[^>]+href="([^\"]*/series/([0-9A-Z]{26})(?:/[^\"]*)?)"[^>]*>(.*?)</a>',re.I|re.S)
        for href,series_id,block in pattern.findall(html):
            href=urllib.parse.urljoin(BASE_URL+'/',unescape(href))
            if (urllib.parse.urlparse(href).hostname or '').casefold() not in self.domains:
                continue
            title_match=re.search(r'<div[^>]*class="[^"]*flex-1[^"]*"[^>]*>(.*?)</div>',block,re.I|re.S)
            title=_text(title_match.group(1) if title_match else '')
            cover_match=re.search(r'<source[^>]+srcset="([^"]+)"',block,re.I)
            if not cover_match: cover_match=re.search(r'<img[^>]+src="([^"]+)"',block,re.I)
            cover=unescape(cover_match.group(1)).split()[0] if cover_match else ''
            if title: rows.append({'score':1000 if title.casefold()==query.casefold() else 250,'title':title,'full_title':title,'author':'','alternate_titles':[],'year':None,'available_languages':['en'],'adult':None,'id':series_id.upper(),'url':href,'cover_url':cover,'badge':'','source_id':self.source_id,'source_name':self.display_name})
        rows=rows[int(offset):int(offset)+int(limit)]
        return {'query':query,'offset':int(offset),'next_offset':int(offset)+len(rows),'limit':int(limit),'total':len(rows),'rows':rows,'fetched_count':len(rows),'filtered_doujinshi':0,'filtered_empty':0,'has_more':False}

    def _title_html(self,value):
        series_id,url=self._series_url(value)
        return series_id,url,self._request_text(url,headers=self._headers(referer=BASE_URL+'/'))

    def get_manga(self,value,preferred='en'):
        del preferred
        series_id,url,html=self._title_html(value)
        title_match=re.search(r'<meta property="og:title" content="(.*?)\s*\|\s*Weeb Central">',html,re.I)
        title=unescape(title_match.group(1)).strip() if title_match else ''
        if not title: raise RuntimeError('WeebCentral title page did not contain metadata.')
        author_match=re.search(r'Author\(s\).*?/search\?author=[^"]+"[^>]*>(.*?)</a>',html,re.I|re.S)
        associated=re.search(r'Associated Name\(s\)</strong>\s*<ul[^>]*>(.*?)</ul>',html,re.I|re.S)
        alternates=[_text(item) for item in re.findall(r'<li[^>]*>(.*?)</li>',associated.group(1),re.I|re.S)] if associated else []
        year_match=re.search(r'<strong>Released:\s*</strong>\s*<span>(\d{4})</span>',html,re.I)
        adult_match=re.search(r'<strong>Adult Content:\s*</strong>.*?>(Yes|No)</a>',html,re.I|re.S)
        cover_match=re.search(r'https?://[^"\s]+/cover/normal/'+re.escape(series_id)+r'\.(?:webp|jpe?g|png)',html,re.I)
        if not cover_match:
            cover_match=re.search(r'<meta property="og:image" content="([^"]+)">',html,re.I)
        cover=unescape(cover_match.group(0) if cover_match and not cover_match.lastindex else cover_match.group(1)) if cover_match else ''
        desc_match=re.search(r'<strong>Description</strong>\s*<p[^>]*>(.*?)</p>',html,re.I|re.S)
        type_match=re.search(r'<strong>Type:\s*</strong>\s*<a[^>]*>(.*?)</a>',html,re.I|re.S)
        status_match=re.search(r'<strong>Status:\s*</strong>\s*<a[^>]*>(.*?)</a>',html,re.I|re.S)
        official_match=re.search(r'<strong>Official Translation:\s*</strong>\s*<a[^>]*>(Yes|No)</a>',html,re.I|re.S)
        tags_block=re.search(r'<strong>Tags\(s\):\s*</strong>(.*?)</li>',html,re.I|re.S)
        tags=[_text(tag) for tag in re.findall(r'<a[^>]*>(.*?)</a>',tags_block.group(1),re.I|re.S)] if tags_block else []
        titles=[{'language':'en','title':title,'primary':True}]+[{'language':'','title':alt,'primary':False} for alt in alternates]
        return {'uuid':series_id,'title':title,'author':_text(author_match.group(1)) if author_match else '','titles':titles,'alternate_titles':alternates,'year':int(year_match.group(1)) if year_match else None,'available_languages':['en'],'original_language':'','main_cover_url':cover,'description':_text(desc_match.group(1)) if desc_match else '','source_url':url,'adult':bool(adult_match and adult_match.group(1).casefold()=='yes'),'type':_text(type_match.group(1)) if type_match else '','status':_text(status_match.group(1)) if status_match else '','official_translation':bool(official_match and official_match.group(1).casefold()=='yes'),'tags':tags}

    def get_chapters(self,value,language,start_volume=None,end_volume=None):
        if language and language!='en' or start_volume is not None or end_volume is not None: return []
        series_id,url=self._series_url(value); endpoint=f'{BASE_URL}/series/{series_id}/full-chapter-list'
        html=self._request_text(endpoint,headers=self._headers('chapter-list',url))
        chapters=[]
        for chapter_id,block in re.findall(
                r'<a[^>]+href="/chapters/([0-9A-Z]{26})"[^>]*>(.*?)</a>',html,re.I|re.S):
            label_match=re.search(r'\b(?:Episode|Chapter)\s+([^\s<]+)',_text(block),re.I)
            if not label_match:
                continue
            chapters.append({'id':chapter_id.upper(),'volume':None,
                             'chapter':label_match.group(1).strip(),'title':'','pages':None})
        chapters.sort(key=chapter_sort_key); return chapters

    def get_download_plan(self,value,language,start_volume=None,end_volume=None):
        chapters=self.get_chapters(value,language,start_volume,end_volume)
        return {'volumes':[],'pages_by_volume':{},'chapters_by_volume':{},'bonus_pages':0,'bonus_chapters':len(chapters),'aggregate_error':'','feed_error':''}

    def get_volume_covers(self,value):
        series_id=self.resolve_manga_ref(value); return {None:f'https://temp.compsci88.com/cover/normal/{series_id}.webp'}

    def get_page_manifest(self,chapter_id,retry_callback=None):
        del retry_callback
        chapter_url=chapter_id if str(chapter_id).startswith('http') else f'{BASE_URL}/chapters/{chapter_id}'
        endpoint=chapter_url+'/images?is_prev=False&reading_style=double_page_v2&current_page=1'
        html=self._request_text(endpoint,headers=self._headers('chapter-images',chapter_url))
        urls=list(dict.fromkeys(unescape(url) for url in re.findall(r'<img[^>]+src="(https?://[^"]+)"',html,re.I)))
        def page_key(url):
            match=re.search(r'-(\d+)\.[a-z0-9]+(?:\?|$)',url,re.I)
            return int(match.group(1)) if match else len(urls)
        urls.sort(key=page_key)
        if not urls: raise RuntimeError('WeebCentral chapter reader did not contain page images.')
        return {'full':urls,'data_saver':list(urls)}

    def fetch_binary(self,url,**kwargs): return self._fetch_binary(url,**kwargs)
    def fetch_preview_page(self,saver_url,full_url,page_number,log=None,check_cancel=None):
        del page_number,log
        if check_cancel: check_cancel()
        return self.fetch_binary(full_url or saver_url,timeout=45,retries=4),True
