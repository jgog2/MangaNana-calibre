"""Bounded search-artwork evidence; no request/selection behavior changes.

Only allowlisted public artwork URLs and request headers are retained.
No cookies, authorization, image bodies, or local reading-file paths are logged.
"""
from collections import deque
from contextlib import contextmanager
import functools,json,os,threading,time,uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit,urlunsplit

_local=threading.local();_installed=False
def public_url(value):
    try:
        p=urlsplit(str(value or ''))
        allowed=p.hostname in ('uploads.mangadex.org','mangadex.org','api.mangadex.org')
        allowed=allowed or (p.hostname=='temp.compsci88.com' and p.path.startswith('/cover/'))
        allowed=allowed or (p.hostname=='rx.resmk.org' and p.path.startswith('/covers/'))
        if not allowed or p.scheme not in ('http','https') or p.username or p.password:return ''
        return urlunsplit((p.scheme,p.netloc,p.path,'',''))[:768]
    except Exception:return ''

class ThumbnailAudit:
    def __init__(self,path):
        self.path=Path(path);self.events=deque(maxlen=384);self.lock=threading.Lock()
        self.session=uuid.uuid4().hex;self.started=time.monotonic();self.dirty=False;self.seen={};self.sequence=0;self.opened=False
    def event(self,event,**fields):
        try:
            if 'url' in fields:fields['url']=public_url(fields['url'])
            def bounded(value,depth=0):
                if depth>3:return None
                if isinstance(value,dict):return {str(k)[:64]:bounded(v,depth+1) for k,v in list(value.items())[:24]}
                if isinstance(value,(list,tuple)):return [bounded(v,depth+1) for v in value[:32]]
                return value if value is None or isinstance(value,(int,float,bool)) else str(value)[:1024]
            row=dict(event=event,**{k:bounded(v) for k,v in fields.items()})
            signature=json.dumps(row,sort_keys=True,default=str)
            with self.lock:
                # Repainting an unchanged row does not evict useful failures.
                if event in ('paint','pixmap','search.pixmap','schedule.skip','schedule.scheduled','metadata') and self.seen.get(event+str(fields.get('key') or fields.get('id') or fields.get('url')))==signature:return
                self.seen[event+str(fields.get('key') or fields.get('id') or fields.get('url'))]=signature
                if len(self.seen)>192:self.seen.clear()
                self.sequence+=1;row.update(session=self.session,pid=os.getpid(),utc=datetime.now(timezone.utc).isoformat(),sequence=self.sequence,elapsed_ms=round((time.monotonic()-self.started)*1000,3))
                self.events.append(row);self.dirty=True
        except Exception:pass # Diagnostics must not prevent acquisition/rendering.
    def flush(self):
        try:
            with self.lock:
                if not self.dirty:return
                rows=list(self.events);self.dirty=False
            payload=json.dumps(dict(schema=1,events=rows,dropped_before_sequence=rows[0]['sequence']-1 if rows else 0),ensure_ascii=True,default=str).encode('utf-8')
            while len(payload)>256*1024 and len(rows)>1:
                rows=rows[len(rows)//4:];payload=json.dumps(dict(schema=1,events=rows,dropped_before_sequence=rows[0]['sequence']-1),ensure_ascii=True,default=str).encode('utf-8')
            self.path.parent.mkdir(parents=True,exist_ok=True)
            if not self.opened:
                if self.path.exists():os.replace(self.path,self.path.with_suffix('.previous.json'))
                self.opened=True
            temp=self.path.with_suffix('.tmp');temp.write_bytes(payload);os.replace(temp,self.path)
        except Exception:pass

@contextmanager
def scope(audit):
    previous=getattr(_local,'audit',None);_local.audit=audit
    try:yield
    finally:_local.audit=previous

def install_worker_hooks(main):
    global _installed
    if _installed:return
    _installed=True
    from calibre_plugins.manganana.providers.mangadex_source import MangaDexSource
    from calibre_plugins.manganana.books.imaging.artwork_delivery import ArtworkResolver
    original=main.ImageBatchWorker.run
    @functools.wraps(original)
    def run(worker):
        audit=getattr(worker,'thumbnail_audit',None)
        if audit:audit.event('worker.start',batch=worker.batch_id)
        try:
            with scope(audit):return original(worker)
        except Exception as exc:
            if audit:audit.event('worker.error',batch=worker.batch_id,error=type(exc).__name__)
            raise
        finally:
            if audit:audit.event('worker.finish',batch=worker.batch_id,cancelled=worker.isInterruptionRequested())
    main.ImageBatchWorker.run=run
    resolve=ArtworkResolver.resolve_url
    @functools.wraps(resolve)
    def resolve_url(resolver,url,provider,*a,**k):
        audit=getattr(_local,'audit',None);watch=audit is not None and bool(public_url(url))
        if watch:audit.event('resolver.start',url=url,provider=provider.source_id)
        value=resolve(resolver,url,provider,*a,**k)
        if watch:audit.event('resolver.finish',url=url,bytes=len(value.get('raw') or b''),failures=value.get('failures'),candidate_url=getattr(value.get('candidate'),'url',''))
        return value
    ArtworkResolver.resolve_url=resolve_url
    fetch=MangaDexSource._default_fetch_binary
    @functools.wraps(fetch)
    def binary(url,*a,**k):
        audit=getattr(_local,'audit',None)
        if audit:audit.event('transport.call',url=url,retries=k.get('retries',5))
        return fetch(url,*a,**k)
    MangaDexSource._default_fetch_binary=staticmethod(binary)

def http_event(event,**fields):
    audit=getattr(_local,'audit',None)
    if audit and ('url' not in fields or public_url(fields['url'])):audit.event(event,**fields)

def enable(dialog):
    """Attach local GUI observers and one dirty-only flush timer to this dialog."""
    from calibre.constants import config_dir
    from qt.core import QTimer
    from calibre_plugins.manganana.app import main
    install_worker_hooks(main)
    audit=ThumbnailAudit(Path(config_dir)/'plugins/MangaNana-search-thumbnails.json')
    dialog.thumbnail_audit=audit
    def wrap(name,observer):
        original=getattr(dialog,name)
        @functools.wraps(original)
        def call(*a,**k):
            try:observer('before',a,k,None)
            except Exception:pass
            result=original(*a,**k)
            try:observer('after',a,k,result)
            except Exception:pass
            return result
        setattr(dialog,name,call)
    def publish(phase,args,kwargs,result):
        if phase!='after':return
        for row in args[0]:
            if row.get('source_id') in ('mangadex','weebcentral','mangak','mangapill','atsu'):audit.event('record',provider=row.get('source_id'),id=str(row.get('id'))[:96],title=str(row.get('title'))[:160],url=row.get('cover_url'),canonical=str(row.get('canonical_work_id') or '')[:160],generation=dialog._cover_generation,token=dialog._search_cover_batch_token)
    wrap('_publish_discovery_records',publish)
    def schedule(phase,args,kwargs,result):
        if phase=='after':
            worker=dialog.search_thumb_worker
            if worker:
                for entry in worker.entries:
                    if public_url(entry[0]):audit.event('schedule.scheduled',url=entry[0],batch=worker.batch_id,candidates=[public_url(u) for u in entry[1]])
            return
        for row in dialog.discovery_view.visible_records():
            if row.get('source_id') in ('mangadex','weebcentral','mangak','mangapill','atsu'):
                url=row.get('cover_url') or '';reason='no_url' if not url else 'cached' if url in getattr(dialog,'_search_image_cache',dialog._image_cache) else 'failed' if url in dialog._failed_image_urls else 'worker_busy' if dialog.search_thumb_worker and dialog.search_thumb_worker.isRunning() else 'eligible'
                audit.event('schedule.skip' if reason!='eligible' else 'schedule.eligible',provider=row.get('source_id'),id=row.get('id'),url=url,reason=reason,generation=dialog._cover_generation,token=dialog._search_cover_batch_token,search_request=dialog._search_request_id)
    wrap('_load_visible_search_thumbs',schedule)
    def callback(phase,args,kwargs,result):
        data=args[0];key=data.get('key');batch=data.get('batch_id') or ()
        kind=batch[0] if isinstance(batch,(tuple,list)) and batch else 'unknown'
        token=dialog._volume_cover_batch_token if kind=='volume' else dialog._search_cover_batch_token
        if public_url(key):audit.event('callback.'+phase,url=key,batch=data.get('batch_id'),current=[kind,token,dialog._cover_generation],closing=dialog._closing,bytes=len(data.get('raw') or b''),cache_present=key in dialog._image_cache,failed=key in dialog._failed_image_urls)
    for name in ('_on_search_thumb_ready','_on_search_thumb_failed','_on_volume_thumb_ready','_on_volume_thumb_failed'):wrap(name,callback)
    def store(phase,args,kwargs,result):
        if phase=='after' and public_url(args[0]):audit.event('cache.insert',url=args[0],bytes=len(args[1]),lookup_key=str(args[0])[:768])
    wrap('_store_image_bytes',store)
    def pixmap(phase,args,kwargs,result):
        if phase=='after' and public_url(args[0]):audit.event('pixmap',url=args[0],key=[str(args[0])[:768],args[1],args[2]],cached=args[0] in dialog._image_cache,decoded=result is not None and not result.isNull(),size=[result.width(),result.height(),result.devicePixelRatio()] if result and not result.isNull() else None)
    wrap('_pix_for_url',pixmap)
    if hasattr(dialog,'_search_pixmap'):
        def search_pixmap(phase,args,kwargs,result):
            if phase=='after' and public_url(args[0]):audit.event('search.pixmap',url=args[0],cached=args[0] in dialog._search_image_cache,
                shared_cached=args[0] in dialog._image_cache,key=[str(args[0])[:768],36,50,dialog.devicePixelRatioF()],
                decoded=result is not None and not result.isNull(),size=[result.width(),result.height(),result.devicePixelRatio()] if result and not result.isNull() else None)
        wrap('_search_pixmap',search_pixmap)
    publication_before={}
    def publication(phase,args,kwargs,result):
        rows=[r for r in dialog.discovery_view.records if r.get('source_id') in ('mangadex','weebcentral','mangak','mangapill','atsu')][:16]
        if phase=='before':publication_before.clear();publication_before.update({r.get('cover_url'):r.get('cover_url') in dialog._image_cache for r in rows})
        else:
            for r in rows:
                url=r.get('cover_url')
                if publication_before.get(url) and url not in dialog._image_cache:audit.event('publication.invalidate',id=r.get('id'),url=url,
                    shared_cached=False,search_cached=url in getattr(dialog,'_search_image_cache',{}))
    wrap('_on_reference_lookup_ready',publication)
    def select(phase,args,kwargs,result):
        row=args[0]
        if isinstance(row,dict) and row.get('source_id') in ('mangadex','weebcentral','mangak','mangapill','atsu'):audit.event('select.'+phase,provider=row.get('source_id'),id=row.get('id'),url=row.get('cover_url'),generation=dialog._cover_generation,token=dialog._search_cover_batch_token)
    wrap('_begin_search_result',select)
    def metadata(phase,args,kwargs,result):
        if phase=='after' and dialog.current_source_id in ('mangadex','weebcentral','mangak','mangapill','atsu'):audit.event('metadata',provider=dialog.current_source_id,id=dialog.current_manga_url,url=(dialog.loaded_metadata or {}).get('main_cover_url'),selected_url=public_url(dialog._selected_cover_url),pending_url=public_url(dialog._pending_search_cover_url))
    wrap('_refresh_hero',metadata)
    def model_change(first,last,roles):
        if not first.isValid():return
        node=first.internalPointer();row=node.record or node.group.records[0]
        if row.get('source_id') in ('mangadex','weebcentral','mangak','mangapill','atsu'):audit.event('model.dataChanged',provider=row.get('source_id'),id=row.get('id'),url=row.get('cover_url'),row=first.row(),parent=first.parent().row() if first.parent().isValid() else None)
    dialog.discovery_view.model().dataChanged.connect(model_change)
    timer=QTimer(dialog);timer.setInterval(1000);timer.timeout.connect(audit.flush);timer.start()
    dialog.finished.connect(lambda *_:(timer.stop(),audit.flush()))
    dialog._thumbnail_audit_timer=timer
