"""Network-free SourceAdapter scaffold. Not registered with the application.

Replace the injected operation transport with a reviewed provider implementation;
do not mistake these synthetic example.invalid records for a working provider.
"""
from copy import deepcopy
from urllib.parse import urlsplit
from calibre_plugins.manganana.providers.source_adapter import SourceAdapter

class ExampleSource(SourceAdapter):
    source_id='example'
    key=source_id
    display_name='Example (synthetic)'
    domains=('example.invalid',)
    content_languages=('en',)
    capabilities=frozenset({'search','metadata','chapters','pages','binary'})
    enabled_by_default=False

    def __init__(self,transport,check_cancel=lambda:None):
        self.transport=transport;self.check_cancel=check_cancel

    def with_cancel_check(self,check_cancel):return type(self)(self.transport,check_cancel)

    def call(self,operation,reference):
        self.check_cancel();value=self.transport(operation,reference);self.check_cancel()
        return deepcopy(value)

    def parse_manga_ref(self,value):
        try:parts=urlsplit(str(value))
        except ValueError:return None
        path=parts.path.strip('/').split('/')
        if (parts.scheme=='https' and parts.hostname in self.domains and not parts.username
                and not parts.password and len(path)==2 and path[0]=='series' and path[1]):return path[1]
        return None

    def require(self,value):
        reference=self.parse_manga_ref(value)
        if reference is None:raise ValueError('Expected an Example series URL')
        return reference

    def get_manga(self,value,preferred='en'):
        return self.call('metadata',self.require(value))

    def search(self,query,offset=0,limit=12,include_adult=False,preferred='en',availability_cache=None):
        # This fixture transport returns a finite listing, not a real HTTP API.
        rows=self.call('search',query);offset=max(0,int(offset));limit=max(1,int(limit))
        page=rows[offset:offset+limit]
        return dict(query=query,offset=offset,next_offset=offset+len(page),limit=limit,total=len(rows),
                    rows=page,fetched_count=len(page),has_more=offset+len(page)<len(rows))

    @SourceAdapter.capture_chapter_inventory
    def get_chapters(self,value,language,start_volume=None,end_volume=None):
        if language!='en' or start_volume is not None or end_volume is not None:return []
        rows=self.call('chapters',self.require(value));seen=set();result=[]
        for row in rows:
            identity=row.get('id')
            if not identity:raise ValueError('Missing exact acquisition identity')
            if identity in seen:continue
            seen.add(identity);result.append(row)
        return result  # Preserve the fixture's verified source order.

    def get_download_plan(self,value,language,start_volume=None,end_volume=None):
        rows=self.get_chapters(value,language,start_volume,end_volume)
        return dict(volumes=[],pages_by_volume={},chapters_by_volume={},bonus_pages=0,
                    bonus_chapters=len(rows),aggregate_error='',feed_error='')

    def get_volume_covers(self,value):
        url=self.get_manga(value).get('main_cover_url')
        return {None:url} if url else {}

    def get_page_manifest(self,chapter_id,retry_callback=None):
        manifest=self.call('pages',chapter_id)
        urls=manifest.get('full')
        if not isinstance(urls,list) or not urls:raise ValueError('No complete page manifest')
        for url in urls:
            p=urlsplit(url)
            if p.scheme!='https' or not p.hostname or p.username or p.password:raise ValueError('Invalid page URL')
        return manifest

    def fetch_binary(self,url,**kwargs):return self.call('binary',url)

    def fetch_preview_page(self,saver_url,full_url,page_number,log=None,check_cancel=None):
        if check_cancel:check_cancel()
        raw=self.fetch_binary(full_url or saver_url)
        if check_cancel:check_cancel()
        return raw,True
